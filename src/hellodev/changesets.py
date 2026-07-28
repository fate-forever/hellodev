"""Hash-only repository baselines and deterministic change projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, cast

from .context_runtime.contracts import RepositoryFile, RepositorySnapshot
from .context_runtime.native import snapshot as repository_snapshot
from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json
from .state_lock import locked_state


Scope = Literal["code", "docs", "project"]
SCOPES = {"code", "docs", "project"}
STORE_SCHEMA_VERSION = 1
DOC_SUFFIXES = {".md", ".rst", ".txt"}
DOC_ROOTS = {"docs", "doc", "documentation"}
DOC_NAMES = {"readme", "readme.md", "license", "license.md", "changelog", "changelog.md"}


def classify_path(path: str) -> Literal["code", "docs"]:
    normalized = path.replace("\\", "/").lower().strip("/")
    parts = normalized.split("/") if normalized else []
    name = parts[-1] if parts else ""
    suffix = Path(name).suffix
    if (parts and parts[0] == ".trellis") or name == "agents.md":
        return "code"
    if (parts and parts[0] in DOC_ROOTS) or name in DOC_NAMES or suffix in DOC_SUFFIXES:
        return "docs"
    return "code"


def _path_digest(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _entries(snapshot: RepositorySnapshot) -> list[dict[str, str]]:
    return sorted(
        (
            {
                "pathSha256": _path_digest(item.path),
                "contentSha256": item.sha256,
                "scope": classify_path(item.path),
            }
            for item in snapshot.files
        ),
        key=lambda item: item["pathSha256"],
    )


def _snapshot_digest(entries: list[dict[str, str]], scope: Scope) -> str:
    selected = entries if scope == "project" else [item for item in entries if item["scope"] == scope]
    payload = [{"pathSha256": item["pathSha256"], "contentSha256": item["contentSha256"]} for item in selected]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def identities(snapshot: RepositorySnapshot) -> dict[str, Any]:
    entries = _entries(snapshot)
    return {
        "repositorySnapshot": snapshot.snapshot_id,
        "scopeSnapshots": {scope: _snapshot_digest(entries, cast(Scope, scope)) for scope in ("code", "docs", "project")},
        "scanState": snapshot.state,
        "entries": entries,
    }


def scope_identity(root: Path, scope: str) -> dict[str, Any]:
    selected = scope.lower()
    if selected not in SCOPES:
        raise ProjectError("verification scope must be code, docs, or project")
    snapshot = repository_snapshot(root)
    if snapshot.state != "complete":
        raise ProjectError("repository context is bounded; refusing scoped verification reuse")
    value = identities(snapshot)
    return {
        "scope": selected,
        "scopeSnapshot": value["scopeSnapshots"][selected],
        "repositorySnapshot": value["repositorySnapshot"],
        "scanState": value["scanState"],
    }


def capture_baseline(root: Path) -> dict[str, Any]:
    load_config(root)
    current = repository_snapshot(root)
    value = identities(current)
    store = {
        "schemaVersion": STORE_SCHEMA_VERSION,
        "capturedAt": utc_now(),
        "repositorySnapshot": value["repositorySnapshot"],
        "scopeSnapshots": value["scopeSnapshots"],
        "scanState": value["scanState"],
        "entries": value["entries"],
    }
    with locked_state(root, "changeset"):
        write_json(ProjectPaths(root).changeset_file, store)
    return summary(root)


def _load(root: Path) -> dict[str, Any] | None:
    load_config(root)
    path = ProjectPaths(root).changeset_file
    if not path.exists():
        return None
    if path.is_symlink():
        raise ProjectError("refusing symlinked ChangeSet baseline")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid ChangeSet baseline: {error}") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != STORE_SCHEMA_VERSION:
        raise ProjectError("invalid ChangeSet baseline schema")
    entries = value.get("entries")
    if not isinstance(entries, list) or any(
        not isinstance(item, dict)
        or set(item) != {"pathSha256", "contentSha256", "scope"}
        or item.get("scope") not in {"code", "docs"}
        or not all(isinstance(item.get(field), str) and len(item[field]) == 64 for field in ("pathSha256", "contentSha256"))
        for item in entries
    ):
        raise ProjectError("invalid ChangeSet baseline entries")
    return value


def changed_files_for_analysis(root: Path) -> dict[str, Any]:
    """Return in-memory changed files for trusted local analysis only."""
    baseline = _load(root)
    if baseline is None:
        return {
            "state": "baseline-missing",
            "repositoryFiles": (),
            "changedFiles": (),
            "deletedCount": 0,
            "scanState": "not-evaluated",
        }
    current_snapshot = repository_snapshot(root)
    if current_snapshot.state != "complete":
        return {
            "state": "bounded",
            "repositoryFiles": (),
            "changedFiles": (),
            "deletedCount": 0,
            "scanState": current_snapshot.state,
        }
    base_entries = {item["pathSha256"]: item for item in baseline["entries"]}
    current_entries = {item["pathSha256"]: item for item in _entries(current_snapshot)}
    added = set(current_entries) - set(base_entries)
    deleted = set(base_entries) - set(current_entries)
    modified = {
        key
        for key in set(base_entries) & set(current_entries)
        if base_entries[key]["contentSha256"] != current_entries[key]["contentSha256"]
    }
    changed_current = added | modified
    selected = tuple(item for item in current_snapshot.files if _path_digest(item.path) in changed_current)
    return {
        "state": "ready",
        "repositoryFiles": current_snapshot.files,
        "changedFiles": selected,
        "deletedCount": len(deleted),
        "scanState": current_snapshot.state,
    }


def summary(root: Path) -> dict[str, Any]:
    baseline = _load(root)
    if baseline is None:
        return {
            "schemaVersion": 1,
            "state": "baseline-missing",
            "baselineCapturedAt": None,
            "scanState": "not-evaluated",
            "changedFileCount": 0,
            "scopeCounts": {"code": 0, "docs": 0, "project": 0},
            "changeKinds": {"added": 0, "modified": 0, "deleted": 0},
            "scopeSnapshots": {},
            "repositorySnapshot": None,
            "rawPathsPersisted": False,
            "rawSourcePersisted": False,
        }
    current_snapshot = repository_snapshot(root)
    current = identities(current_snapshot)
    base_entries = {} if baseline is None else {item["pathSha256"]: item for item in baseline["entries"]}
    current_entries = {item["pathSha256"]: item for item in current["entries"]}
    added = set() if baseline is None else set(current_entries) - set(base_entries)
    deleted = set() if baseline is None else set(base_entries) - set(current_entries)
    modified = set() if baseline is None else {
        key for key in set(base_entries) & set(current_entries)
        if base_entries[key]["contentSha256"] != current_entries[key]["contentSha256"]
    }
    changed = added | deleted | modified

    def count(scope: str) -> int:
        return sum(
            1
            for key in changed
            if (current_entries.get(key) or base_entries[key])["scope"] == scope
        )

    return {
        "schemaVersion": 1,
        "state": "ready",
        "baselineCapturedAt": baseline.get("capturedAt"),
        "scanState": current["scanState"],
        "changedFileCount": len(changed),
        "scopeCounts": {"code": count("code"), "docs": count("docs"), "project": len(changed)},
        "changeKinds": {"added": len(added), "modified": len(modified), "deleted": len(deleted)},
        "scopeSnapshots": current["scopeSnapshots"],
        "repositorySnapshot": current["repositorySnapshot"],
        "rawPathsPersisted": False,
        "rawSourcePersisted": False,
    }


__all__ = [
    "capture_baseline", "changed_files_for_analysis", "classify_path", "identities", "scope_identity", "summary",
]
