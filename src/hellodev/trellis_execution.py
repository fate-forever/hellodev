"""Read-only, risk-adaptive verification projection for Trellis-backed work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import changesets, contracts, typescript_impact, verification, workflow_projection
from .context_runtime import semantic
from .project import ProjectError, project_initialized


MAX_TASK_METADATA_BYTES = 64 * 1024
MAX_TEST_EVIDENCE_FILES = 200
HIGH_RISK_TERMS = {
    "auth", "authorization", "database", "deploy", "deployment", "migration",
    "permission", "release", "schema", "security",
}


def _bounded_task_metadata(root: Path, native_ref: str) -> tuple[dict[str, Any] | None, str]:
    task_dir = root / ".trellis" / "tasks" / native_ref
    task_file = task_dir / "task.json"
    if task_dir.is_symlink() or not task_dir.is_dir():
        return None, "task-directory-invalid"
    try:
        task_dir.resolve().relative_to((root / ".trellis" / "tasks").resolve())
    except ValueError:
        return None, "task-directory-escapes-store"
    if not task_file.exists():
        return None, "task-metadata-missing"
    if task_file.is_symlink() or not task_file.is_file():
        return None, "task-metadata-unsafe"
    try:
        if task_file.stat().st_size > MAX_TASK_METADATA_BYTES:
            return None, "task-metadata-oversized"
        value = json.loads(task_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "task-metadata-invalid"
    if not isinstance(value, dict):
        return None, "task-metadata-invalid"
    priority = value.get("priority")
    scope = value.get("scope")
    status = value.get("status")
    if (
        (priority is not None and (not isinstance(priority, str) or len(priority) > 16))
        or (scope is not None and (not isinstance(scope, str) or len(scope) > 256))
        or (status is not None and (not isinstance(status, str) or len(status) > 32))
    ):
        return None, "task-metadata-invalid"
    return {
        "priority": priority if isinstance(priority, str) and len(priority) <= 16 else None,
        "scope": scope if isinstance(scope, str) and len(scope) <= 256 else None,
        "status": status if isinstance(status, str) and len(status) <= 32 else None,
    }, "task-metadata-ready"


def _profile(
    change_set: dict[str, Any],
    metadata: dict[str, Any] | None,
    semantic_impact: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if metadata is None:
        return "strict", ["task-metadata-invalid"]
    priority = (metadata.get("priority") or "").upper()
    scope_terms = {
        part for part in (metadata.get("scope") or "").lower().replace("/", " ").replace("-", " ").split()
        if part
    }
    changed = int(change_set.get("changedFileCount", 0))
    kinds = change_set.get("changeKinds") or {}
    scopes = change_set.get("scopeCounts") or {}
    if priority in {"P0", "P1"}:
        reasons.append("high-priority-task")
    if scope_terms & HIGH_RISK_TERMS:
        reasons.append("high-risk-task-scope")
    if int(kinds.get("deleted", 0)) > 0:
        reasons.append("deletion-present")
    if changed > 10:
        reasons.append("large-change-set")
    if isinstance(semantic_impact, dict) and semantic_impact.get("wideImpact") is True:
        reasons.append("semantic-impact-wide")
    if reasons:
        return "strict", reasons
    docs_only = changed > 0 and int(scopes.get("docs", 0)) == changed and int(scopes.get("code", 0)) == 0
    declared_docs = scope_terms and scope_terms <= {"doc", "docs", "documentation"}
    if changed <= 5 and (docs_only or (changed == 0 and declared_docs)):
        return "quick", ["bounded-docs-only-change"]
    return "standard", ["default-bounded-code-change"]


def _safe_file(path: Path, limit: int = 1024 * 1024) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size <= limit
    except OSError:
        return False


def _package_scripts(root: Path) -> tuple[dict[str, str], str] | None:
    package = root / "package.json"
    if not _safe_file(package):
        return None
    try:
        value = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    scripts = value.get("scripts") if isinstance(value, dict) else None
    if not isinstance(scripts, dict):
        return None
    selected = {
        name: command.strip()
        for name, command in scripts.items()
        if isinstance(name, str) and isinstance(command, str) and command.strip()
    }
    if "test" not in selected:
        return None
    if _safe_file(root / "pnpm-lock.yaml"):
        manager = "pnpm"
    elif _safe_file(root / "yarn.lock"):
        manager = "yarn"
    else:
        manager = "npm"
    return selected, manager


def _package_test_command(root: Path) -> str | None:
    package = _package_scripts(root)
    if package is None:
        return None
    _, manager = package
    return f"{manager} test"


def _python_evidence(root: Path) -> bool:
    explicit = ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")
    if any(_safe_file(root / name) for name in explicit):
        return True
    tests = root / "tests"
    if tests.is_symlink() or not tests.is_dir():
        return False
    try:
        candidates = list(tests.glob("test_*.py")) + list(tests.glob("*_test.py"))
    except OSError:
        return False
    return 0 < len(candidates) <= MAX_TEST_EVIDENCE_FILES and all(_safe_file(path) for path in candidates)


def verification_plan(root: Path, profile: str = "standard", acceptance_text: str | None = None) -> dict[str, Any]:
    """Discover a bounded ordered host plan without executing or shell-chaining commands."""
    if profile not in {"quick", "standard", "strict"}:
        raise ProjectError("verification profile must be quick, standard, or strict")
    level = "T0" if profile == "quick" else "T1" if profile == "standard" else "T2"
    scope = "docs" if profile == "quick" else "code" if profile == "standard" else "project"
    if profile == "quick":
        git_marker = root / ".git"
        command = "git diff --check" if git_marker.exists() and not git_marker.is_symlink() else None
        return {"state": "ready" if command else "unavailable", "steps": [] if command is None else [{"command": command, "level": level, "scope": scope, "kind": "diff-check"}], "discovery": "bounded-project-contract"}
    verify_script = root / "scripts" / "verify.py"
    if _safe_file(verify_script):
        command = f"python scripts/verify.py --scope {'fast' if profile == 'standard' else 'full'}"
        return {"state": "ready", "steps": [{"command": command, "level": level, "scope": scope, "kind": "project-verify"}], "discovery": "explicit-verify-script"}
    package = _package_scripts(root)
    python = _python_evidence(root)
    if package is not None and python:
        return {"state": "ambiguous", "steps": [], "discovery": "mixed-runtime-manifests"}
    if package is not None:
        scripts, manager = package
        steps = [{"command": f"{manager} test", "level": level, "scope": scope, "kind": "test"}]
        criterion = (acceptance_text or "").lower()
        requested = (
            ("test:integration", "integration", ("test:integration", "integration test", "integration suite", "集成测试")),
            ("typecheck", "typecheck", ("typecheck", "type check", "tsc", "类型检查")),
            ("build", "build", ("build", "production build", "构建")),
            ("test:e2e", "e2e", ("test:e2e", "e2e", "end-to-end", "端到端")),
        )
        for script, kind, terms in requested:
            if script not in scripts or not any(term in criterion for term in terms):
                continue
            command = f"{manager} {script}" if manager == "yarn" else f"{manager} run {script}"
            steps.append({"command": command, "level": level, "scope": scope, "kind": kind})
        return {"state": "ready", "steps": steps, "discovery": "package-manifest-first"}
    if python:
        return {"state": "ready", "steps": [{"command": "python -m pytest -q", "level": level, "scope": scope, "kind": "test"}], "discovery": "python-project-evidence"}
    return {"state": "unavailable", "steps": [], "discovery": "runtime-unavailable"}
def _command(root: Path, profile: str) -> tuple[str | None, str, str]:
    if profile == "quick":
        git_marker = root / ".git"
        if git_marker.exists() and not git_marker.is_symlink():
            return "git diff --check", "T0", "docs"
        return None, "T0", "docs"
    plan = verification_plan(root, profile)
    if not plan["steps"]:
        return None, "T1" if profile == "standard" else "T2", "code" if profile == "standard" else "project"
    step = plan["steps"][0]
    return step["command"], step["level"], step["scope"]


def project_command(root: Path, profile: str = "standard") -> tuple[str | None, str, str]:
    """Discover one bounded host command without requiring a Trellis task."""
    if profile not in {"quick", "standard", "strict"}:
        raise ProjectError("verification profile must be quick, standard, or strict")
    return _command(Path(root), profile)


def status(
    root: Path,
    *,
    project_mode: dict[str, Any] | None = None,
    change_set: dict[str, Any] | None = None,
    semantic_impact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one adaptive host check without executing or persisting anything."""
    selected = Path(root)
    mode = project_mode or workflow_projection.status(selected)
    base = {
        "schemaVersion": 1,
        "policy": "adaptive",
        "trellisAuthority": "task-spec-gate" if mode.get("mode") == "trellis-native" else "not-active",
        "finalGatePolicyPreserved": True,
        "verificationReuse": "exact-command-scope-snapshot",
        "semanticImpactPolicy": "escalate-only",
        "readOnly": True,
        "executionPerformed": False,
        "persistencePerformed": False,
        "rawTaskBodyExposed": False,
        "rawTaskBodyPersisted": False,
        "rawPathsExposed": False,
    }
    if not project_initialized(selected) or mode.get("mode") != "trellis-native":
        return {
            **base,
            "state": "not-applicable",
            "profile": None,
            "reasonCodes": ["trellis-native-work-item-required"],
            "requiredLevel": None,
            "scope": None,
            "command": None,
            "commandDiscovery": "not-applicable",
            "verificationState": "not-applicable",
            "runRequired": False,
        }
    current = contracts.current_work_item(selected)
    if current is None or current.get("backend") != "trellis":
        raise ProjectError("adaptive Trellis execution requires a current Trellis WorkItem")
    metadata, metadata_state = _bounded_task_metadata(selected, current["nativeRef"])
    current_changes = change_set or changesets.summary(selected)
    if semantic_impact is None:
        inputs = changesets.changed_files_for_analysis(selected)
        if inputs["state"] == "ready":
            semantic_impact = semantic.change_impact(inputs["repositoryFiles"], inputs["changedFiles"])
            typescript = typescript_impact.change_impact(inputs["repositoryFiles"], inputs["changedFiles"])
            if typescript["state"] != "not-applicable":
                semantic_impact = typescript
        else:
            semantic_impact = {
                "state": inputs["state"],
                "provider": "native-python-ast",
                "changedPythonFileCount": 0,
                "definedSymbolCount": 0,
                "referencingFileCount": 0,
                "crossFileReferenceCount": 0,
                "parseErrorCount": 0,
                "wideImpact": False,
                "rawSymbolsExposed": False,
                "rawPathsExposed": False,
            }
    profile, reasons = _profile(current_changes, metadata, semantic_impact)
    if metadata_state != "task-metadata-ready":
        reasons = [metadata_state, *[item for item in reasons if item != "task-metadata-invalid"]]
    command, level, scope = _command(selected, profile)
    if command is None:
        return {
            **base,
            "state": "advisory-unavailable",
            "profile": profile,
            "reasonCodes": reasons,
            "semanticImpact": semantic_impact,
            "taskMetadataState": metadata_state,
            "metadataFieldsConsumed": ["priority", "scope", "status"],
            "requiredLevel": level,
            "scope": scope,
            "command": None,
            "commandDiscovery": "unavailable",
            "verificationState": "unavailable",
            "runRequired": False,
            "estimatedAvoidedDurationMs": 0,
        }
    evidence = verification.inspect(selected, level, command, scope)
    coverage = None
    if profile == "standard" and int(current_changes.get("changedFileCount", 0)) <= 5 and evidence["state"] == "missing":
        coverage = verification.coverage(selected, level, scope)
        if coverage["covered"]:
            evidence = {
                **evidence,
                "state": "covered-success",
                "runRequired": False,
                "reasonCode": "same-snapshot-equal-or-stronger-host-evidence",
                "reusedRecordId": coverage["reusedRecordId"],
                "estimatedAvoidedDurationMs": 0,
            }
    return {
        **base,
        "state": "ready",
        "profile": profile,
        "reasonCodes": reasons,
        "semanticImpact": semantic_impact,
        "taskMetadataState": metadata_state,
        "metadataFieldsConsumed": ["priority", "scope", "status"],
        "requiredLevel": level,
        "scope": scope,
        "command": command,
        "commandDiscovery": "deterministic-project-contract",
        "verificationState": evidence["state"],
        "runRequired": evidence["runRequired"],
        "reusedRecordId": evidence.get("reusedRecordId"),
        "failedRecordId": evidence.get("failedRecordId"),
        "pendingSessionId": evidence.get("sessionId"),
        "estimatedAvoidedDurationMs": evidence.get("estimatedAvoidedDurationMs", 0),
        "coverageEvidence": coverage,
        "commandEquivalenceClaimed": False,
    }


__all__ = ["project_command", "status", "verification_plan"]
