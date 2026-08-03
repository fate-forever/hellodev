"""Typed application facade for HelloDev's bounded daily workflow.

The CLI and optional MCP transport share this module.  It deliberately owns no
cross-call cache: project state, adapter identities, profiles, and approvals
are revalidated for every operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Mapping, TypedDict, cast

from . import __version__
from . import (
    acceptance,
    approval,
    briefs,
    capabilities,
    changesets,
    components,
    context_runtime,
    context_policy,
    contracts,
    efficiency_cycles,
    experience,
    facade,
    gates,
    knowledge_flows,
    lifecycle,
    profiles,
    receipts,
    repository_tools,
    resume,
    routing,
    sagas,
    trellis_execution,
    usage_collector,
    verification,
    task_alignment,
    workflow_projection,
)
from .adapters import nocturne, trellis
from .command_rendering import command_line, rewrite_commands
from .component_protocol import canonical_sha256
from .project import (
    ProjectError,
    complete_task,
    create_task,
    init_project,
    list_tasks,
    load_config,
    nocturne_config,
    project_initialized,
    resolve_root,
    selected_host,
    show_task,
)


DailyIntent = Literal[
    "begin",
    "plan",
    "work",
    "check",
    "finish",
    "task",
    "validate",
    "verify",
    "recall",
    "remember",
]


class DoArguments(TypedDict, total=False):
    """Typed input accepted by :meth:`ProjectClient.do`."""

    goal: str
    acceptance: str | None
    requirements_file: str | None
    note: str | None
    operation: Literal["create", "list", "show", "current", "start", "validate", "complete"]
    title: str | None
    task: str | None
    query: str
    domain: str | None
    limit: int | None
    namespace_scope: str | None
    also_memory: bool
    lesson: str
    scope: Literal["auto", "code", "docs", "project", "cross-project"]
    receipt: str | None
    saga: str | None
    proposal: str | None
    approve: str | None
    timeout: int
    level: Literal["T0", "T1", "T2"]
    command: str
    snapshot: str | None
    outcome: Literal["succeeded", "failed"] | None
    duration_ms: int | None
    session: str | None
    current_snapshot: bool
    results: list[dict[str, Any]]


@dataclass(frozen=True)
class _DoRequest:
    do_intent: str
    goal: str | None = None
    acceptance: str | None = None
    requirements_file: str | None = None
    note: str | None = None
    operation: str | None = None
    title: str | None = None
    task: str | None = None
    query: str | None = None
    domain: str | None = None
    limit: int | None = None
    namespace_scope: str | None = None
    also_memory: bool = False
    lesson: str | None = None
    scope: str = "auto"
    receipt: str | None = None
    saga: str | None = None
    proposal: str | None = None
    approve: str | None = None
    timeout: int = 30
    level: str | None = None
    command: str | None = None
    snapshot: str | None = None
    outcome: str | None = None
    duration_ms: int | None = None
    session: str | None = None
    current_snapshot: bool = False
    results: list[dict[str, Any]] | None = None


_INTENTS = frozenset({"begin", "plan", "work", "check", "finish", "task", "validate", "verify", "recall", "remember"})
_ALLOWED_ARGUMENTS: dict[str, frozenset[str]] = {
    "begin": frozenset({"goal", "acceptance", "requirements_file", "task", "approve", "timeout"}),
    "plan": frozenset({"note"}),
    "work": frozenset({"note"}),
    "check": frozenset({"note"}),
    "finish": frozenset({"note", "approve", "timeout"}),
    "task": frozenset({"operation", "title", "task", "approve", "timeout"}),
    "validate": frozenset({"task", "approve", "timeout"}),
    "verify": frozenset({"level", "command", "scope", "snapshot", "session", "outcome", "duration_ms", "current_snapshot", "results"}),
    "recall": frozenset(
        {"query", "domain", "limit", "namespace_scope", "also_memory", "approve", "timeout"}
    ),
    "remember": frozenset(
        {"lesson", "scope", "receipt", "saga", "proposal", "approve", "timeout"}
    ),
}
_REQUIRED_ARGUMENTS: dict[str, frozenset[str]] = {
    "begin": frozenset(),
    "task": frozenset({"operation"}),
    "validate": frozenset({"task"}),
    "verify": frozenset(),
    "recall": frozenset({"query"}),
    "remember": frozenset({"lesson"}),
}


def _do_request(intent: str, arguments: Mapping[str, Any] | None) -> _DoRequest:
    if intent not in _INTENTS:
        raise ProjectError(f"unknown HelloDev daily intent: {intent}")
    values = dict(arguments or {})
    unknown = set(values) - _ALLOWED_ARGUMENTS[intent]
    if unknown:
        raise ProjectError(f"unsupported {intent} argument(s): {', '.join(sorted(unknown))}")
    string_fields = {
        "note",
        "goal",
        "acceptance",
        "requirements_file",
        "operation",
        "title",
        "task",
        "query",
        "domain",
        "namespace_scope",
        "lesson",
        "scope",
        "receipt",
        "saga",
        "proposal",
        "approve",
        "level",
        "command",
        "snapshot",
        "outcome",
        "session",
    }
    for name in string_fields & set(values):
        if values[name] is not None and not isinstance(values[name], str):
            raise ProjectError(f"{name} must be a string")
    if "limit" in values and values["limit"] is not None and type(values["limit"]) is not int:
        raise ProjectError("limit must be an integer")
    if "duration_ms" in values and values["duration_ms"] is not None and type(values["duration_ms"]) is not int:
        raise ProjectError("duration_ms must be an integer")
    if "current_snapshot" in values and type(values["current_snapshot"]) is not bool:
        raise ProjectError("current_snapshot must be a boolean")
    if "results" in values and values["results"] is not None and not isinstance(values["results"], list):
        raise ProjectError("verification results must be a list")
    missing = [
        name
        for name in _REQUIRED_ARGUMENTS.get(intent, ())
        if values.get(name) is None or values.get(name) == ""
    ]
    if missing:
        raise ProjectError(f"{intent} requires: {', '.join(sorted(missing))}")
    timeout = values.get("timeout", 30)
    timeout_ceiling = 300 if intent in {"begin", "finish", "task", "validate"} else 120
    if type(timeout) is not int or not 1 <= timeout <= timeout_ceiling:
        raise ProjectError(f"timeout must be between 1 and {timeout_ceiling} seconds")
    if "also_memory" in values and type(values["also_memory"]) is not bool:
        raise ProjectError("also_memory must be a boolean")
    if intent == "task" and values.get("operation") not in {"create", "list", "show", "current", "start", "validate", "complete"}:
        raise ProjectError("task operation must be create, list, show, current, start, validate, or complete")
    if intent == "remember" and values.get("scope", "auto") not in {"auto", "project", "cross-project"}:
        raise ProjectError("remember scope must be auto, project, or cross-project")
    if intent == "verify":
        if values.get("results") is not None:
            if not 1 <= len(values["results"]) <= 16:
                raise ProjectError("verification results batch must contain between 1 and 16 items")
            conflicting = [
                name for name in ("level", "command", "scope", "snapshot", "session", "outcome", "duration_ms")
                if values.get(name) is not None
            ]
            if values.get("current_snapshot"):
                conflicting.append("current_snapshot")
            if conflicting:
                raise ProjectError("verification results batch cannot be combined with single-result arguments")
            # Item-level validation remains centralized in verification.py.
            return _DoRequest(do_intent=intent, **values)
        session = values.get("session")
        if session is None:
            if values.get("level", "").upper() not in {"T0", "T1", "T2"} or not values.get("command"):
                raise ProjectError("verification planning requires level and command")
            values["level"] = values["level"].upper()
            if values.get("scope") not in {None, "auto", "code", "docs", "project"}:
                raise ProjectError("verification scope must be auto, code, docs, or project")
        elif any(values.get(name) is not None for name in ("level", "command", "scope", "snapshot")) or values.get("current_snapshot"):
            raise ProjectError("verification session recording cannot include level, command, scope, or snapshot")
        if values.get("outcome") is not None and values["outcome"] not in {"succeeded", "failed"}:
            raise ProjectError("verification outcome must be succeeded or failed")
        if session is not None and values.get("outcome") is None:
            raise ProjectError("verification session recording requires outcome")
        if values.get("snapshot") is not None and values.get("current_snapshot"):
            raise ProjectError("verification recording accepts snapshot or current_snapshot, not both")
        if session is None and values.get("outcome") is not None and not values.get("snapshot") and not values.get("current_snapshot"):
            raise ProjectError("verification outcome recording requires snapshot or explicit current_snapshot attestation")
        if values.get("snapshot") is not None and values.get("outcome") is None:
            raise ProjectError("verification snapshot is only accepted when recording an outcome")
        if values.get("current_snapshot") and values.get("outcome") is None:
            raise ProjectError("current_snapshot attestation requires an outcome")
    return _DoRequest(do_intent=intent, **values)


def _file_identity(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"state": "absent"}
    selected = Path(path)
    if not selected.is_file() or selected.is_symlink():
        return {"state": "unavailable", "path": str(selected)}
    digest = hashlib.sha256()
    with selected.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return {"state": "present", "path": str(selected.resolve()), "sha256": digest.hexdigest()}


def _trellis_binding(root: Path) -> dict[str, Any]:
    return {
        "capability_fingerprint": capabilities.fingerprint(root),
        "executable_identity": {
            "trellis": trellis.binding_identity(),
            "python": _file_identity(sys.executable),
            "taskScript": _file_identity(root / ".trellis" / "scripts" / "task.py"),
        },
        "intent_registry": trellis.intent_catalog(),
    }


def _nocturne_binding(root: Path) -> dict[str, Any]:
    configuration = nocturne_config(root)
    if configuration is None:
        raise ProjectError("Nocturne is not configured for this project")
    return {
        "capability_fingerprint": capabilities.fingerprint(root),
        "executable_identity": {
            "command": _file_identity(configuration["command"]),
            "mode": configuration["mode"],
            "source": configuration.get("source", "external"),
            "componentFiles": configuration.get("executionIdentity", []),
            "manifestSha256": configuration.get("manifestSha256"),
        },
        "intent_registry": {"search_memory": {"risk": "read", "scope": "narrow"}},
    }


def _explicit_authorization(root: Path) -> dict[str, Any]:
    return {
        "decision": "token-required",
        "authorizationMode": "token-required",
        "profileUsed": profiles.current_policy(root)["authorizationProfile"],
        "reason": "an exact one-time token was supplied",
    }


def _status(root: Path) -> dict[str, Any]:
    initialized = project_initialized(root)
    task_count = 0
    config: dict[str, Any] | None = None
    capability_cache: dict[str, Any] | None = None
    lifecycle_state: dict[str, Any] | None = None
    if initialized:
        config = load_config(root)
        task_count = len(list_tasks(root))
        capability_cache = capabilities.status(root)
        lifecycle_state = lifecycle.status(root)
        cached = capability_cache.get("capabilities") if capability_cache["state"] == "fresh" else None
        trellis_state = cached["trellis"] if isinstance(cached, dict) else {"state": "cache-missing-or-stale"}
        nocturne_state = cached["nocturne"] if isinstance(cached, dict) else {"state": "cache-missing-or-stale"}
        repository_tool_state = (
            cached["repositoryTools"]
            if isinstance(cached, dict) and isinstance(cached.get("repositoryTools"), dict)
            else {"state": "cache-missing-or-stale", "activeProvider": "native", "suggestedProvider": "native"}
        )
        context_plane_state = context_runtime.status(root)
    else:
        trellis_state = trellis.discover(root)
        nocturne_state = nocturne.status(root)
        repository_tool_state = repository_tools.discover()
        context_plane_state = context_runtime.status(root)
    return {
        "version": __version__,
        "root": str(root),
        "initialized": initialized,
        "project": config,
        "taskCount": task_count,
        "currentTask": experience.current_task(root) if initialized else None,
        "lifecycle": lifecycle_state,
        "capabilities": capability_cache,
        "trellis": trellis_state,
        "nocturne": nocturne_state,
        "repositoryTools": repository_tool_state,
        "contextPlane": context_plane_state,
        "distribution": components.availability(),
        **(
            (lambda project_mode, change_set: {
                "projectMode": project_mode,
                "changeSet": change_set,
                "verification": verification.summary(root),
                "acceptance": acceptance.evidence(root),
                "trellisExecution": trellis_execution.status(
                    root, project_mode=project_mode, change_set=change_set
                ),
                "gate": gates.status(root),
                "facade": facade.status(root),
            })(workflow_projection.status(root), changesets.summary(root))
            if initialized
            else {}
        ),
    }


def _auto_usage_sync(root: Path) -> dict[str, Any]:
    host = selected_host(root)
    if host in {"antigravity", "cursor", "none"}:
        return {
            "state": "unavailable",
            "reasonCode": "host-usage-receipt-unavailable",
            "host": host,
            "sourceTrust": "unavailable",
            "measurement": "unavailable",
            "estimated": False,
            "persistencePerformed": False,
        }
    if os.environ.get("CODEX_THREAD_ID") is not None:
        try:
            root.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            try:
                Path.cwd().resolve().relative_to(root.resolve())
            except ValueError:
                return {
                    "state": "skipped",
                    "reasonCode": "environment-thread-does-not-own-selected-root",
                    "persistencePerformed": False,
                }
    try:
        value = usage_collector.sync_codex_usage(root)
    except ProjectError:
        return {
            "state": "unavailable",
            "reasonCode": "matching-codex-runtime-unavailable",
            "sourceTrust": "unavailable",
            "measurement": "unavailable",
            "estimated": False,
            "persistencePerformed": False,
        }
    return {
        "state": value["state"],
        "reasonCode": "completed-codex-turns-synchronized",
        "selectionMode": value["selectionMode"],
        "sourceTrust": value["sourceTrust"],
        "measurement": "exact",
        "estimated": False,
        "completedTurnCount": value["completedTurnCount"],
        "recordedCount": value["recordedCount"],
        "skippedCount": value["skippedCount"],
        "remainingUnrecordedCount": value["remainingUnrecordedCount"],
        "cycleCount": value["reflectionCycle"]["cycleCount"],
        "pendingReceiptCount": value["reflectionCycle"]["pendingReceiptCount"],
        "remainingUntilNextCycle": value["reflectionCycle"]["remainingUntilNextCycle"],
        "persistencePerformed": value["persistencePerformed"],
    }


def _start(root: Path) -> dict[str, Any]:
    if not project_initialized(root):
        return {"state": "uninitialized", "status": _status(root), "action": "run hellodev init first"}
    return {"state": "started", "lifecycle": lifecycle.start(root), "capabilities": capabilities.refresh(root)}


def _blockers(state: dict[str, Any]) -> list[str]:
    if not state["initialized"]:
        return ["HelloDev is not initialized"]
    phase = (state.get("lifecycle") or {}).get("phase", "unknown")
    blockers: list[str] = []
    if phase == "blocked":
        history = (state.get("lifecycle") or {}).get("history", [])
        note = history[-1].get("note") if history and isinstance(history[-1], dict) else None
        return [note or "lifecycle is blocked"]
    if state.get("capabilities", {}).get("state") != "fresh":
        blockers.append("capability cache is missing or stale")
    if state.get("trellis", {}).get("state") == "unsafe":
        blockers.append("Trellis metadata is unsafe")
    current_task = state.get("currentTask") or {}
    acceptance_state = state.get("acceptance") or {}
    if phase in {"started", "planned", "working", "checking"} and not current_task.get("id"):
        blockers.append("work intake is required")
    elif phase in {"planned", "working", "checking"} and not acceptance_state.get("required", False):
        blockers.append("acceptance contract is required")
    guided = (state.get("acceptance") or {}).get("guidedAcceptance") or {}
    blockers.extend(
        f"guided acceptance: {item}"
        for item in guided.get("blockers", [])
        if isinstance(item, str)
    )
    return blockers


def _compact_status(state: dict[str, Any]) -> dict[str, Any]:
    lifecycle_state = state.get("lifecycle") or {}
    project_mode = state.get("projectMode") or {}
    change_set = state.get("changeSet") or {}
    verification_state = state.get("verification") or {}
    acceptance_state = state.get("acceptance") or {}
    next_step = routing.next_decision(Path(state["root"])) if state["initialized"] else None
    next_command = next_step["command"] if next_step is not None else "hellodev open"
    current_task = state.get("currentTask")
    compact_task = (
        {
            key: current_task.get(key)
            for key in ("id", "backend", "nativeRef", "title", "lifecyclePhase", "candidate")
            if key in current_task
        }
        if isinstance(current_task, dict)
        else current_task
    )
    if isinstance(compact_task, dict) and compact_task.get("title") == compact_task.get("nativeRef"):
        compact_task.pop("title", None)
    value: dict[str, Any] = {
        "version": state["version"],
        "root": state["root"],
        "initialized": state["initialized"],
        "phase": lifecycle_state.get("phase"),
        "currentTask": compact_task,
        "projectMode": project_mode.get("mode", "unavailable"),
        "changeSet": {
            "changedFileCount": change_set.get("changedFileCount", 0),
            "scopeCounts": change_set.get("scopeCounts", {"code": 0, "docs": 0, "project": 0}),
        },
        "verification": {
            "levels": verification_state.get("levels", {"T0": 0, "T1": 0, "T2": 0}),
            "pendingSessionCount": verification_state.get("pendingSessionCount", 0),
        },
        "blockers": _blockers(state),
        "next": next_command,
        "suggestedLevel": next_step.get("suggestedLevel", context_policy.suggested_level("status"))
        if next_step is not None
        else "L0",
        "repositoryTools": {
            "state": state["repositoryTools"].get("state", "unknown"),
            "activeProvider": state["repositoryTools"].get("activeProvider", "native"),
            "suggestedProvider": state["repositoryTools"].get("suggestedProvider", "native"),
            "activationState": state["repositoryTools"].get("activationState", "native-context-plane"),
        },
        "contextPlane": {
            "state": state["contextPlane"].get("state", "unknown"),
            "backend": state["contextPlane"].get("backend", "native"),
            "lastQueryAvailable": isinstance(state["contextPlane"].get("lastQuery"), dict),
        },
    }
    if acceptance_state.get("state", "not-declared") != "not-declared":
        value["acceptance"] = {"state": acceptance_state["state"]}
    if state["initialized"]:
        try:
            cycle = efficiency_cycles.status(Path(state["root"]))
        except ProjectError:
            cycle = None
        if cycle is not None:
            value["reflectionCycle"] = {
                "state": cycle["state"],
                "cycleCount": cycle["cycleCount"],
                "pendingReceiptCount": cycle["pendingReceiptCount"],
                "remainingUntilNextCycle": cycle["remainingUntilNextCycle"],
            }
        if next_step is not None and "efficiency" in next_step:
            value["efficiency"] = next_step["efficiency"]
    return value


def _deferred_usage_sync(root: Path) -> dict[str, Any]:
    """Describe usage collection without scanning an in-flight host rollout."""
    host = selected_host(root)
    if host in {"antigravity", "cursor", "none"}:
        return {
            "state": "unavailable",
            "reasonCode": "host-usage-receipt-unavailable",
            "host": host,
            "sourceTrust": "unavailable",
            "measurement": "unavailable",
            "estimated": False,
            "persistencePerformed": False,
        }
    return {
        "state": "deferred",
        "reasonCode": "usage-sync-deferred-until-verbose-open-or-explicit-sync",
        "host": host,
        "sourceTrust": "runtime-observed",
        "measurement": "exact",
        "estimated": False,
        "persistencePerformed": False,
    }


def _daily_open(root: Path) -> dict[str, Any]:
    """Expose only the ordinary decision surface; verbose open keeps diagnostics."""
    state = _status(root)
    decision = routing.next_decision(root)
    acceptance_state = state.get("acceptance") or acceptance.evidence(root)
    task = state.get("currentTask")
    compact_task = None
    if isinstance(task, dict):
        compact_task = {
            key: task[key]
            for key in ("id", "backend", "nativeRef", "title", "state", "candidate")
            if key in task
        }
        compact_task["bound"] = bool(task.get("id"))
        compact_task["trellisBound"] = task.get("backend") == "trellis" and bool(task.get("id"))
    next_projection = {
        key: decision[key]
        for key in ("command", "reasonCode", "suggestedLevel")
        if key in decision
    }
    action = decision.get("action")
    if isinstance(action, dict):
        next_projection["action"] = {
            key: action[key]
            for key in ("kind", "commandTemplate", "requiredInputs", "workItemBound")
            if key in action
        }
    work_item_bound = isinstance(task, dict) and bool(task.get("id"))
    acceptance_declared = bool(acceptance_state["required"])
    return {
        "task": compact_task,
        "phase": (state.get("lifecycle") or {}).get("phase"),
        "blockers": _blockers(state),
        "acceptance": {
            "state": acceptance_state["state"],
            "satisfied": acceptance_state["satisfied"],
            "coverage": acceptance_state["coverage"],
            "mode": acceptance_state["guidedAcceptance"]["mode"],
            "quality": acceptance_state["qualityCoverage"],
            "declared": acceptance_declared,
            "workItemBound": work_item_bound,
            "closureEligible": work_item_bound and acceptance_declared and acceptance_state["satisfied"],
        },
        "next": next_projection,
        "approval": approval.status(root),
    }


def _open(root: Path, verbose: bool) -> dict[str, Any]:
    created: dict[str, Any] | None = None
    if not project_initialized(root):
        created = init_project(root)
    state = lifecycle.status(root)
    if state["phase"] == "new":
        started = _start(root)
        result: dict[str, Any] = {"state": "opened", "created": bool(created and created["created"])}
        if verbose:
            usage_sync = _auto_usage_sync(root)
            result["start"] = started
            result["resume"] = resume.build(root)
            result.update(_status(root))
            result["next"] = routing.next_decision(root)
            result["usageSync"] = usage_sync
        else:
            result = _daily_open(root)
        return result
    decision = routing.next_decision(root)
    result = (
        {
            "state": "resumed",
            "created": False,
            **_status(root),
            "next": decision,
            "usageSync": _auto_usage_sync(root),
        }
        if verbose
        else _daily_open(root)
    )
    if verbose:
        result["resume"] = resume.build(root)
    return result


def record_execution(
    root: Path,
    adapter: str,
    operation: str,
    risk: str,
    request: Any,
    result: dict[str, Any],
    succeeded: bool,
    saga_id: str | None = None,
    receipt_kind: str = "command",
    authorization: dict[str, Any] | None = None,
    evidence_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit_arguments: dict[str, Any] = {}
    if authorization is not None:
        audit_arguments = {
            "profile_used": authorization["profileUsed"],
            "authorization_mode": authorization["authorizationMode"],
            "lease_sha256": authorization.get("leaseSha256"),
        }
    receipt = receipts.record(
        root,
        adapter,
        operation,
        risk,
        request,
        result,
        succeeded,
        kind=receipt_kind,
        evidence_binding=evidence_binding,
        **audit_arguments,
    )
    response: dict[str, Any] = {**result, "receipt": receipt}
    if saga_id is not None:
        response["saga"] = sagas.attach(root, saga_id, receipt["id"])
    return response


def apply_trellis_continuity(
    root: Path, native_intent: str, task: str | None, execution: dict[str, Any]
) -> dict[str, Any]:
    if execution.get("exitCode") != 0 or not isinstance(task, str):
        return execution
    if native_intent == "task-start":
        execution["workItem"] = contracts.create_work_item(root, "trellis", task)
    elif native_intent == "task-validate":
        task_file = root / ".trellis" / "tasks" / task / "task.json"
        component_result = execution.get("componentResult")
        component_data = component_result.get("data") if isinstance(component_result, dict) else None
        context_valid = component_data.get("valid") is True if isinstance(component_data, dict) else True
        source = "component-protocol" if isinstance(component_data, dict) else "legacy-task-script"
        evidence = None
        if task_file.is_symlink() or (task_file.exists() and (not task_file.is_file() or task_file.stat().st_size > 64 * 1024)):
            raise ProjectError("Trellis task record is unsafe after context validation")
        if task_file.is_file():
            try:
                task_record = json.loads(task_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ProjectError(f"Trellis task record is invalid after context validation: {error}") from error
            if not isinstance(task_record, dict):
                raise ProjectError("Trellis task record is invalid after context validation")
            evidence = acceptance.record_context_validation(
                root, task, canonical_sha256(task_record), context_valid, source
            )
        execution["contextValidation"] = {
            "state": "passed" if context_valid else "failed",
            "evidenceClass": "context-validation",
            "qualityGateSatisfied": False,
            "reasonCode": "trellis-context-valid-not-quality-evidence",
            "evidence": evidence,
        }
    return execution


def trellis_evidence_binding(root: Path, native_intent: str, task: str | None) -> dict[str, Any] | None:
    return None


def _trellis_values(decision: dict[str, Any]) -> dict[str, Any]:
    arguments = decision["arguments"]
    return {
        "title": arguments.get("title"),
        "acceptance": arguments.get("acceptance"),
        "task": arguments.get("task"),
        "channel": None,
        "old_thread": None,
        "new_thread": None,
        "agent": None,
        "scope": "project",
    }


def _run_trellis(
    root: Path,
    decision: dict[str, Any],
    approve_token: str | None,
    timeout: int,
    continuation: list[str],
) -> dict[str, Any]:
    native_intent = decision["arguments"]["nativeIntent"]
    risk = decision["risk"]
    values = _trellis_values(decision)
    binding = _trellis_binding(root)
    if approve_token is not None:
        authorization = _explicit_authorization(root)
        token = approve_token
    else:
        authorization = profiles.authorization_decision(
            root,
            adapter="trellis",
            risk=risk,
            read_class="trellis-read" if risk == "read" else "trellis-write",
            **binding,
        )
        prepared = trellis.prepare_intent(root, native_intent, **values)
        if authorization["decision"] == "token-required":
            return {
                **decision,
                **prepared,
                "authorization": authorization,
                "context": context_policy.suggest(decision["contextIntent"]),
                "resumeCommand": command_line(root, *continuation, "--approve", prepared["approval"]),
            }
        token = prepared["approval"]
    evidence = trellis_evidence_binding(root, native_intent, values.get("task"))
    result = trellis.run_intent(root, native_intent, token, timeout, **values)
    response = record_execution(
        root,
        "trellis",
        f"intent/{native_intent}",
        risk,
        {"intent": native_intent, "argv": result["argv"]},
        result,
        result["exitCode"] == 0,
        receipt_kind="command",
        authorization=authorization,
        evidence_binding=evidence,
    )
    response = apply_trellis_continuity(root, native_intent, values.get("task"), response)
    if (
        result["exitCode"] == 0
        and authorization["authorizationMode"] == "token-required"
        and authorization["profileUsed"] == "trusted-local"
        and risk == "read"
    ):
        response["lease"] = profiles.grant_read_lease(root, **binding)
    return {
        **decision,
        "executionPerformed": True,
        "authorization": authorization,
        "context": context_policy.suggest(decision["contextIntent"]),
        "result": response,
    }


def _recall_continuation(prefix: list[str], request: _DoRequest) -> list[str]:
    values = [*prefix, "--query", cast(str, request.query)]
    if request.domain is not None:
        values.extend(("--domain", request.domain))
    if request.limit is not None:
        values.extend(("--limit", str(request.limit)))
    if request.namespace_scope is not None:
        values.extend(("--namespace-scope", request.namespace_scope))
    if request.also_memory:
        values.append("--also-memory")
    values.extend(("--timeout", str(request.timeout)))
    return values


def _run_recall(root: Path, request: _DoRequest, prefix: list[str]) -> dict[str, Any]:
    query = cast(str, request.query)
    route = routing.decide(root, "recall", {"query": query})
    plan = knowledge_flows.recall_plan(
        root,
        query,
        request.domain,
        request.limit,
        request.namespace_scope,
        also_memory=request.also_memory,
    )
    if plan["state"] != "memory-plan-required":
        return {**route, "context": context_policy.suggest("recall"), **plan}
    parameters = plan["nocturne"]["parameters"]
    effective_domain = parameters["domain"]
    effective_limit = parameters["limit"]
    binding = _nocturne_binding(root)
    if request.approve is not None:
        authorization = _explicit_authorization(root)
        token = request.approve
    else:
        authorization = profiles.authorization_decision(
            root,
            adapter="nocturne",
            risk="read",
            read_class="nocturne-search",
            memory_domain=effective_domain,
            memory_limit=effective_limit,
            **binding,
        )
        prepared = nocturne.prepare_call(root, "search_memory", parameters)
        if authorization["decision"] == "token-required":
            return {
                **route,
                **plan,
                **prepared,
                "state": "awaiting-confirmation",
                "authorization": authorization,
                "context": context_policy.suggest("recall"),
                "resumeCommand": command_line(
                    root, *_recall_continuation(prefix, request), "--approve", prepared["approval"]
                ),
            }
        token = prepared["approval"]
    result = nocturne.call(root, "search_memory", parameters, token, request.timeout)
    succeeded = nocturne.call_succeeded(result)
    recorded = record_execution(
        root,
        "nocturne",
        "search_memory",
        "read",
        {"tool": "search_memory", "parameters": parameters, "namespaceScope": plan["nocturne"]["namespaceScope"]},
        result,
        succeeded,
        authorization=authorization,
    )
    memory_projection = knowledge_flows.project_memory_result(result, plan["local"], effective_limit)
    return {
        **route,
        "state": "memory-result" if succeeded else "memory-error",
        "executionPerformed": True,
        "local": plan["local"],
        "memory": {**memory_projection, "receipt": recorded["receipt"]},
        "authorization": authorization,
        "context": context_policy.suggest("recall"),
    }


def _remember_continuation(
    prefix: list[str], request: _DoRequest, saga_id: str, proposal_id: str | None
) -> list[str]:
    values = [*prefix, "--lesson", cast(str, request.lesson), "--scope", request.scope]
    if request.receipt is not None:
        values.extend(("--receipt", request.receipt))
    if proposal_id is not None:
        values.extend(("--proposal", proposal_id))
    values.extend(("--saga", saga_id, "--timeout", str(request.timeout)))
    return values


def _run_remember(root: Path, request: _DoRequest, prefix: list[str]) -> dict[str, Any]:
    lesson = cast(str, request.lesson)
    route = routing.decide(root, "remember", {"lesson": lesson, "receipt": request.receipt})
    proposal = None
    effective_scope = request.scope
    if request.proposal is not None:
        contracts.validate_lesson_digest(root, request.proposal, lesson)
        proposal = contracts.get_lesson_proposal(root, request.proposal)
        if effective_scope != "auto" and effective_scope != proposal["scope"]:
            raise ProjectError("remember scope does not match the LessonProposal")
        effective_scope = proposal["scope"]
    plan = knowledge_flows.remember_plan(root, lesson, request.receipt, effective_scope)
    destination = plan.get("destination")
    if proposal is None and destination in {"trellis", "nocturne"}:
        proposal = contracts.create_lesson_proposal(
            root,
            lesson,
            "project" if destination == "trellis" else "cross-project",
            destination,
            state=plan["state"],
        )
    if proposal is not None:
        review = contracts.lesson_review_projection(proposal)
        if review["effectiveReviewState"] in {"rejected", "expired", "superseded"}:
            next_command = command_line(root, "lesson", "show", proposal["id"])
            if review["effectiveReviewState"] in {"rejected", "expired"} and request.receipt is not None:
                next_command = command_line(
                    root, "lesson", "review", proposal["id"], "--decision", "reactivate", "--receipt", request.receipt
                )
            return {
                **route,
                "state": "lesson-review-required",
                "executionPerformed": False,
                "lessonProposal": review,
                "context": context_policy.suggest("remember"),
                "next": next_command,
            }
    if proposal is not None and proposal["state"] in {"completed", "partial", "verification-required"}:
        next_command = (
            command_line(root, "saga", "next", proposal["sagaId"])
            if proposal["sagaId"] is not None
            else command_line(root, "lesson", "show", proposal["id"])
        )
        return {
            **route,
            "state": proposal["state"],
            "executionPerformed": False,
            "lessonProposal": proposal,
            "context": context_policy.suggest("remember"),
            "next": next_command,
        }
    if proposal is not None:
        updates: dict[str, Any] = {}
        if proposal["state"] not in {"saga-active", "verification-required", "completed", "partial"}:
            updates["state"] = plan["state"]
        if request.receipt is not None and plan["state"] in {"saga-plan-ready", "configuration-required"}:
            updates["evidence_receipt_id"] = request.receipt
        if updates:
            proposal = contracts.update_lesson_proposal(root, proposal["id"], **updates)
    if plan["state"] != "saga-plan-ready":
        return {**route, "context": context_policy.suggest("remember"), **plan, "lessonProposal": proposal}
    if request.receipt is None:
        raise ProjectError("remember requires an explicit verified evidence receipt before creating a Saga")
    if proposal is None:
        raise ProjectError("remember continuity requires a LessonProposal")
    selected_saga_id = request.saga or proposal["sagaId"]
    if request.saga is not None and proposal["sagaId"] not in {None, request.saga}:
        raise ProjectError("remember Saga does not match the immutable LessonProposal link")
    if selected_saga_id is None:
        saga = sagas.create(root, "Preserve verified cross-project lesson")
        saga = sagas.attach_verified_evidence(root, saga["id"], request.receipt)
    else:
        saga = sagas.status(root, selected_saga_id)
        evidence = saga.get("trellisEvidence", {})
        if evidence.get("receiptId") != request.receipt:
            raise ProjectError("remember Saga is not ready for this exact verified evidence receipt")
        if saga["phase"] == "nocturne-executed":
            proposal = contracts.update_lesson_proposal(root, proposal["id"], state="verification-required")
            return {
                **route,
                "state": "verification-required",
                "executionPerformed": False,
                "saga": saga,
                "lessonProposal": proposal,
                "context": context_policy.suggest("remember"),
                "next": command_line(root, "saga", "next", saga["id"]),
            }
        if saga["phase"] == "completed":
            proposal = contracts.update_lesson_proposal(root, proposal["id"], state="completed")
            return {
                **route,
                "state": "completed",
                "executionPerformed": False,
                "saga": saga,
                "lessonProposal": proposal,
                "context": context_policy.suggest("remember"),
            }
        if saga["phase"] in {"partial", "closed"}:
            proposal = contracts.update_lesson_proposal(root, proposal["id"], state="partial")
            return {
                **route,
                "state": "partial",
                "executionPerformed": False,
                "saga": saga,
                "lessonProposal": proposal,
                "context": context_policy.suggest("remember"),
                "next": command_line(root, "saga", "next", saga["id"]),
            }
        if saga["phase"] != "trellis-verified":
            raise ProjectError("remember Saga is not ready for a Nocturne write")
    saga_id = saga["id"]
    proposal = contracts.update_lesson_proposal(
        root, proposal["id"], evidence_receipt_id=request.receipt, saga_id=saga_id, state="saga-active"
    )
    sagas.require_nocturne_write(root, saga_id)
    write = plan["writeParameters"]
    assert isinstance(write, dict)
    parameters = write["arguments"]
    authorization = profiles.authorization_decision(
        root,
        adapter="nocturne",
        risk="write",
        read_class="nocturne-write",
    )
    if request.approve is None:
        prepared = nocturne.prepare_call(root, write["tool"], parameters)
        return {
            **route,
            **plan,
            **prepared,
            "state": "awaiting-confirmation",
            "saga": saga,
            "lessonProposal": proposal,
            "authorization": authorization,
            "context": context_policy.suggest("remember"),
            "resumeCommand": command_line(
                root,
                *_remember_continuation(prefix, request, saga_id, proposal["id"]),
                "--approve",
                prepared["approval"],
            ),
        }
    review = contracts.lesson_review_projection(proposal)
    if review["effectiveReviewState"] == "pending":
        proposal = contracts.review_lesson_proposal(
            root, proposal["id"], "verify", evidence_receipt_id=request.receipt, reason_code="confirmed-memory-write"
        )
    elif review["effectiveReviewState"] != "verified":
        raise ProjectError(f"LessonProposal is not eligible for memory write: {review['effectiveReviewState']}")
    authorization = _explicit_authorization(root)
    result = nocturne.call(root, write["tool"], parameters, request.approve, request.timeout)
    succeeded = nocturne.call_succeeded(result)
    recorded = record_execution(
        root,
        "nocturne",
        "tools/call",
        "write",
        {"tool": write["tool"], "parameters": parameters},
        result,
        succeeded,
        saga_id,
        authorization=authorization,
    )
    receipt_id = recorded["receipt"]["id"]
    if not succeeded:
        proposal = contracts.update_lesson_proposal(root, proposal["id"], state="partial")
        return {
            **route,
            "state": "partial",
            "executionPerformed": True,
            "result": recorded,
            "lessonProposal": proposal,
            "authorization": authorization,
            "context": context_policy.suggest("remember"),
            "next": command_line(root, "saga", "next", saga_id),
        }
    proposal = contracts.update_lesson_proposal(root, proposal["id"], state="verification-required")
    return {
        **route,
        "state": "verification-required",
        "executionPerformed": True,
        "result": recorded,
        "lessonProposal": proposal,
        "authorization": authorization,
        "context": context_policy.suggest("remember"),
        "next": command_line(root, "saga", "verify", saga_id, receipt_id, "--evidence", "<verification-evidence>"),
    }


def _begin_continuation(request: _DoRequest) -> list[str]:
    values = ["do", "begin", "--goal", cast(str, request.goal)]
    if request.acceptance is not None:
        values.extend(("--acceptance", request.acceptance))
    if request.requirements_file is not None:
        values.extend(("--requirements-file", request.requirements_file))
    if request.task is not None:
        values.extend(("--task", request.task))
    values.extend(("--timeout", str(request.timeout)))
    return values


def _begin_projection(
    root: Path,
    request: _DoRequest,
    route: dict[str, Any],
    *,
    state: str,
    execution_performed: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal = cast(str, request.goal)
    persisted_contract = acceptance.current(root)
    return {
        **route,
        "state": state,
        "executionPerformed": execution_performed,
        "objective": {
            "goal": goal,
            "acceptance": request.acceptance,
            "persistedByHelloDev": (
                request.acceptance is not None
                and persisted_contract is not None
                and persisted_contract["acceptance"] == request.acceptance.strip()
            ),
        },
        "acceptanceContract": persisted_contract,
        "currentTask": experience.current_task(root),
        "contextPlan": experience.context_plan(root, goal, request.acceptance),
        "next": routing.next_decision(root),
        **(extra or {}),
    }


def _closure_plan(root: Path) -> dict[str, Any] | None:
    """Disclose the conservative finish requirements before implementation."""

    contract = acceptance.current(root)
    if contract is None:
        return None
    strict = trellis_execution.verification_plan(root, "strict", contract["acceptance"])
    current = acceptance.evidence(root, include_finish=False)
    return {
        "schemaVersion": 1,
        "state": "declared",
        "requirementsIntegrity": current.get("requirementsIntegrity"),
        "requirementsFileRequiredForWideStrictClosure": True,
        "currentProfile": current.get("verificationPlan", {}).get("profile"),
        "maximumProfile": "strict",
        "requirementsMayTightenAfterChanges": True,
        "requiredSteps": [
            {
                "command": step["command"],
                "hostCommand": verification.executable_command(step["command"]),
                "level": step["level"],
                "scope": step["scope"],
            }
            for step in strict["steps"]
        ],
        "batchReceiptSupported": True,
        "batchReceiptCommand": command_line(
            root, "do", "verify", "--result-json", "<one JSON result per completed command>"
        ),
        "sourceTrust": "host-asserted",
        "testExecutionPerformed": False,
    }


def _trellis_begin_route(goal: str, criterion: str | None, task: str | None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "intent": "begin",
        "route": "trellis.task-begin",
        "backend": "trellis",
        "risk": "write",
        "contextIntent": "trellis-write",
        "arguments": {
            "nativeIntent": "task-begin",
            "title": goal,
            "acceptance": criterion,
            "task": task,
        },
        "reasonCode": "recoverable-trellis-begin",
        "executionPerformed": False,
        "persistent": False,
    }


def _candidate_begin_command(root: Path, request: _DoRequest, task: str) -> str:
    values = ["do", "begin", "--goal", cast(str, request.goal)]
    if request.acceptance is not None:
        values.extend(("--acceptance", request.acceptance))
    if request.requirements_file is not None:
        values.extend(("--requirements-file", request.requirements_file))
    values.extend(("--task", task, "--timeout", str(request.timeout)))
    return command_line(root, *values)


def _activate_begin_work(root: Path, backend: str, native_ref: str) -> tuple[dict[str, Any], bool]:
    phase = lifecycle.status(root)["phase"]
    current = contracts.current_work_item(root)
    if phase in {"planned", "working", "checking"}:
        if current is None:
            # Repair a legacy/unbound daily lifecycle without rewinding it.  The
            # subsequent AcceptanceContract and fresh verification still gate closure.
            return contracts.create_work_item(root, backend, native_ref), True
        if current["backend"] != backend or current["nativeRef"] != native_ref:
            raise ProjectError(f"cannot begin different work while lifecycle is {phase}; finish the current cycle first")
        return contracts.refresh_work_item(root, current["id"]), False
    if phase == "blocked":
        raise ProjectError("cannot begin work while lifecycle is blocked; resume the current cycle first")
    if phase == "finished":
        if backend == "trellis":
            activated = contracts.activate_trellis_task(root, native_ref)
            work_item = activated["workItem"]
        else:
            work_item = contracts.create_work_item(root, backend, native_ref)
            lifecycle.begin_cycle(root, work_item["id"])
        lifecycle.transition(root, "planned", "unified begin")
        return contracts.refresh_work_item(root, work_item["id"]), True
    if phase == "new":
        lifecycle.start(root, "unified begin")
        phase = "started"
    if phase == "started":
        work_item = contracts.create_work_item(root, backend, native_ref)
        lifecycle.transition(root, "planned", "unified begin")
        return contracts.refresh_work_item(root, work_item["id"]), True
    raise ProjectError(f"cannot begin work from lifecycle phase {phase}")


def _run_begin(root: Path, request: _DoRequest) -> dict[str, Any]:
    if request.goal is None:
        current_for_goal = contracts.current_work_item(root) if project_initialized(root) else None
        if current_for_goal is None:
            raise ProjectError("begin requires goal when no current WorkItem is bound")
        goal = (
            show_task(root, current_for_goal["nativeRef"])["title"]
            if current_for_goal["backend"] == "local"
            else f"Continue {current_for_goal['nativeRef']}"
        )
        request = replace(request, goal=goal)
    else:
        goal = request.goal
    if request.acceptance is None and project_initialized(root):
        existing_contract = acceptance.current(root)
        if existing_contract is not None:
            request = replace(request, acceptance=existing_contract["acceptance"])
    route = routing.decide(
        root,
        "begin",
        {"goal": goal, "acceptance": request.acceptance, "task": request.task},
    )
    if not project_initialized(root):
        init_project(root)
    if lifecycle.status(root)["phase"] == "new":
        lifecycle.start(root, "unified begin")
    capabilities.refresh(root)

    trellis_root = root / ".trellis"
    if trellis_root.is_symlink():
        raise ProjectError("refusing symlinked .trellis for unified begin")
    if trellis_root.is_dir():
        before = contracts.list_trellis_tasks(root)
        selected_task = request.task
        if selected_task is not None and selected_task not in before:
            raise ProjectError(f"Trellis task not found: {selected_task}")
        alignment = None
        if selected_task is None and before:
            evaluated = [(task, task_alignment.evaluate(root, task, goal)) for task in before]
            aligned = [(task, value) for task, value in evaluated if value["aligned"]]
            if len(aligned) == 1:
                selected_task, alignment = aligned[0]
            elif len(before) > 1:
                return _begin_projection(
                    root,
                    request,
                    route,
                    state="selection-required",
                    execution_performed=False,
                    extra={
                        "candidates": before,
                        "reasonCode": "multiple-or-ambiguous-trellis-tasks",
                        "candidateActions": [
                            {"task": task, "command": _candidate_begin_command(root, request, task)}
                            for task in before[:20]
                        ],
                    },
                )
            else:
                alignment = evaluated[0][1]
        trellis_begin = None
        created_by_begin = selected_task is None
        selected_state = None if selected_task is None else contracts.trellis_task_state(root, selected_task)
        if selected_task is None or selected_state == "planning":
            decision = _trellis_begin_route(goal, request.acceptance, selected_task)
            trellis_begin = _run_trellis(
                root, decision, request.approve, request.timeout, _begin_continuation(request)
            )
            if not trellis_begin.get("executionPerformed"):
                return _begin_projection(
                    root,
                    request,
                    route,
                    state="awaiting-confirmation",
                    execution_performed=False,
                    extra={
                        **{key: value for key, value in trellis_begin.items() if key not in route},
                        "trellisBegin": trellis_begin,
                        "nativeFallbackAllowed": False,
                    },
                )
            result = trellis_begin.get("result")
            if not isinstance(result, dict) or result.get("exitCode") != 0:
                return _begin_projection(
                    root,
                    request,
                    route,
                    state="trellis-begin-failed",
                    execution_performed=True,
                    extra={
                        "reasonCode": "recoverable-trellis-begin-failed",
                        "trellisBegin": trellis_begin,
                        "nativeFallbackAllowed": False,
                    },
                )
            component = result.get("componentResult")
            data = component.get("data") if isinstance(component, dict) else None
            task_value = data.get("task") if isinstance(data, dict) else None
            returned_task = task_value.get("id") if isinstance(task_value, dict) else None
            if selected_task is None and isinstance(returned_task, str):
                selected_task = returned_task
            if selected_task is None:
                after = contracts.list_trellis_tasks(root)
                added = [item for item in after if item not in before]
                if len(added) == 1:
                    selected_task = added[0]
            if selected_task is None:
                return _begin_projection(
                    root,
                    request,
                    route,
                    state="selection-required",
                    execution_performed=True,
                    extra={
                        "candidates": contracts.list_trellis_tasks(root),
                        "reasonCode": "trellis-begin-result-ambiguous",
                        "trellisBegin": trellis_begin,
                    },
                )
        work_item, changed = _activate_begin_work(root, "trellis", selected_task)
        binding_source = "explicit" if request.task is not None else "created" if created_by_begin else "aligned"
        task_alignment.record_binding(root, work_item["id"], selected_task, goal, binding_source, alignment)
        acceptance.record(
            root, work_item["id"], goal, request.acceptance, request.requirements_file
        )
        capabilities.refresh(root)
        work_item = contracts.refresh_work_item(root, work_item["id"])
        return _begin_projection(
            root,
            request,
            route,
            state="ready" if changed or trellis_begin is not None else "already-active",
            execution_performed=changed or trellis_begin is not None,
            extra={
                "workItem": work_item,
                "selectedTask": selected_task,
                **({"trellisBegin": trellis_begin} if trellis_begin is not None else {}),
                "taskAlignment": alignment or {
                    "schemaVersion": 1,
                    "state": "explicit-or-created",
                    "aligned": True,
                    "reasonCode": "explicit-task-selection" if request.task is not None else "task-created-for-goal",
                },
            },
        )

    current = contracts.current_work_item(root)
    if current is not None and lifecycle.status(root)["phase"] in {"started", "planned", "working", "checking"}:
        if current["backend"] == "local" and show_task(root, current["nativeRef"])["title"] == goal:
            current, changed = _activate_begin_work(root, "local", current["nativeRef"])
            acceptance.record(
                root, current["id"], goal, request.acceptance, request.requirements_file
            )
            return _begin_projection(
                root,
                request,
                route,
                state="ready" if changed else "already-active",
                execution_performed=changed,
                extra={"workItem": current, "selectedTask": current["nativeRef"]},
            )
        raise ProjectError("cannot begin a new local task before the current lifecycle cycle is finished")
    task = create_task(root, goal, request.acceptance)
    work_item, _ = _activate_begin_work(root, "local", task["id"])
    acceptance.record(root, work_item["id"], goal, request.acceptance, request.requirements_file)
    capabilities.refresh(root)
    work_item = contracts.refresh_work_item(root, work_item["id"])
    return _begin_projection(
        root,
        request,
        route,
        state="ready",
        execution_performed=True,
        extra={"workItem": work_item, "selectedTask": task["id"]},
    )


def _require_daily_binding(root: Path, intent: str, *, acceptance_required: bool) -> dict[str, Any]:
    """Enforce the managed daily-flow identity before any later-stage action."""

    current = contracts.current_work_item(root)
    if current is None:
        next_step = routing.next_decision(root)
        raise ProjectError(
            f"{intent} blocked: no current WorkItem is bound. Next: {next_step['command']}"
        )
    try:
        contracts.validate_work_item_reference(root, current)
    except ProjectError as error:
        raise ProjectError(
            f"{intent} blocked: Trellis task or local task reference is missing or unsafe; "
            "native archive cannot bypass HelloDev closure"
        ) from error
    contract = acceptance.current(root)
    if acceptance_required and contract is None:
        next_step = routing.next_decision(root)
        raise ProjectError(
            f"{intent} blocked: current WorkItem has no AcceptanceContract. Next: {next_step['command']}"
        )
    return current


def _require_trellis_completion_integrity(
    root: Path,
    work_item: dict[str, Any],
    completion: dict[str, Any],
) -> dict[str, Any]:
    """Verify every durable closure artifact before lifecycle may finish."""

    result = completion.get("result")
    receipt = result.get("receipt") if isinstance(result, dict) else None
    component = result.get("componentResult") if isinstance(result, dict) else None
    data = component.get("data") if isinstance(component, dict) else None
    task = data.get("task") if isinstance(data, dict) else None
    quality = data.get("qualityEvidence") if isinstance(data, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("exitCode") != 0
        or not isinstance(receipt, dict)
        or receipt.get("operation") != "intent/task-complete"
        or receipt.get("outcome") != "succeeded"
        or not isinstance(component, dict)
        or component.get("ok") is not True
        or component.get("action") != "task-complete"
        or not isinstance(task, dict)
        or task.get("id") != work_item["nativeRef"]
        or task.get("status") != "completed"
        or not isinstance(quality, dict)
        or quality.get("state") != "passed"
        or type(quality.get("recordCount")) is not int
        or quality["recordCount"] < 1
        or quality.get("path") != ".gates/hellodev-quality.json"
    ):
        raise ProjectError(
            "Trellis completion integrity failed; task-complete receipt and mergeable quality evidence are required"
        )
    gate_path = (
        root
        / ".trellis"
        / "tasks"
        / work_item["nativeRef"]
        / ".gates"
        / "hellodev-quality.json"
    )
    if gate_path.is_symlink() or not gate_path.is_file() or gate_path.stat().st_size > 256 * 1024:
        raise ProjectError("Trellis completion integrity failed: HelloDev quality evidence is missing or unsafe")
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"Trellis completion integrity failed: invalid quality evidence: {error}") from error
    if (
        not isinstance(gate, dict)
        or gate.get("state") != "passed"
        or gate.get("task") != work_item["nativeRef"]
        or gate.get("workItemId") != work_item["id"]
        or not isinstance(gate.get("records"), list)
        or not gate["records"]
    ):
        raise ProjectError("Trellis completion integrity failed: quality evidence is not bound to current work")
    if contracts.trellis_task_state(root, work_item["nativeRef"]) != "completed":
        raise ProjectError("Trellis completion integrity failed: native task is not completed")
    return {
        "state": "verified",
        "taskCompleteReceiptId": receipt.get("id"),
        "qualityRecordCount": len(gate["records"]),
        "workItemId": work_item["id"],
    }


def _run_do(root: Path, request: _DoRequest) -> dict[str, Any]:
    intent = request.do_intent
    if intent == "begin":
        value = _run_begin(root, request)
        if value.get("state") == "ready":
            value["changeSet"] = changesets.capture_baseline(root)
            value["projectMode"] = workflow_projection.status(root)
        elif value.get("state") == "already-active":
            current_changes = changesets.summary(root)
            value["changeSet"] = (
                changesets.capture_baseline(root)
                if current_changes["state"] == "baseline-missing"
                else current_changes
            )
            value["projectMode"] = workflow_projection.status(root)
        if "projectMode" in value and "changeSet" in value:
            value["trellisExecution"] = trellis_execution.status(
                root, project_mode=value["projectMode"], change_set=value["changeSet"]
            )
            value["closurePlan"] = _closure_plan(root)
        return value
    if intent in {"plan", "work", "check", "finish"}:
        _require_daily_binding(root, intent, acceptance_required=intent in {"work", "check", "finish"})
        decision = routing.decide(root, intent, {"note": request.note})
        if intent in {"check", "finish"}:
            acceptance.require_satisfied(root, intent)
        gate_decision = gates.finish_decision(root) if intent == "finish" else None
        if gate_decision is not None and not gate_decision["allowed"]:
            raise ProjectError(f"finish blocked: {gate_decision['reason']} Next: {gate_decision['nextCommand']}")
        trellis_completion = None
        closure_integrity = None
        current_before = contracts.current_work_item(root)
        if intent == "finish" and current_before is not None and current_before["backend"] == "trellis":
            binding = task_alignment.binding(root, current_before["id"])
            if binding is None:
                contract = acceptance.current(root)
                legacy_alignment = (
                    task_alignment.evaluate(root, current_before["nativeRef"], contract["goal"])
                    if contract is not None
                    else None
                )
                if legacy_alignment is not None and not legacy_alignment["aligned"]:
                    return {
                        **decision,
                        "state": "trellis-task-alignment-required",
                        "executionPerformed": False,
                        "reasonCode": "unattested-or-unaligned-trellis-binding",
                        "taskAlignment": legacy_alignment,
                        "next": command_line(root, "status", "--verbose"),
                    }
            native_record = root / ".trellis" / "tasks" / current_before["nativeRef"] / "task.json"
            if native_record.is_file() and not native_record.is_symlink():
                completion_decision = routing.decide(
                    root,
                    "task",
                    {"operation": "complete", "task": current_before["nativeRef"]},
                )
                trellis_completion = _run_trellis(
                    root,
                    completion_decision,
                    request.approve,
                    request.timeout,
                    ["do", "finish", "--timeout", str(request.timeout)],
                )
                if not trellis_completion.get("executionPerformed"):
                    return {
                        **decision,
                        "state": "awaiting-confirmation",
                        "executionPerformed": False,
                        "trellisCompletion": trellis_completion,
                        "authorization": trellis_completion.get("authorization"),
                        "resumeCommand": trellis_completion.get("resumeCommand"),
                        "next": trellis_completion.get("resumeCommand"),
                    }
                completion_result = trellis_completion.get("result", {})
                if not isinstance(completion_result, dict) or completion_result.get("exitCode") != 0:
                    return {
                        **decision,
                        "state": "trellis-completion-failed",
                        "executionPerformed": True,
                        "trellisCompletion": trellis_completion,
                        "next": command_line(root, "resume"),
                    }
                closure_integrity = _require_trellis_completion_integrity(
                    root, current_before, trellis_completion
                )
            else:
                raise ProjectError(
                    "Trellis task is missing from the active task store; native archive cannot bypass HelloDev closure"
                )
        if intent == "finish" and current_before is not None and current_before["backend"] == "local":
            complete_task(root, current_before["nativeRef"])
            closure_integrity = {
                "state": "verified",
                "workItemId": current_before["id"],
                "localTaskCompleted": True,
            }
        state = lifecycle.transition(
            root,
            decision["arguments"]["target"],
            decision["arguments"]["note"],
            _managed_closure_verified=intent == "finish" and closure_integrity is not None,
        )
        current_work = contracts.current_work_item(root)
        if current_work is not None:
            current_work = contracts.refresh_work_item(root, current_work["id"])
            if intent == "finish" and current_work["linkedPhase"] != "finished":
                raise ProjectError("closure integrity failed: WorkItem did not reach finished")
        if intent == "finish":
            contracts.set_current_work_item(root, None)
        value: dict[str, Any] = {
            **decision,
            "executionPerformed": True,
            "lifecycle": state,
            "context": context_policy.suggest(decision["contextIntent"]),
            "next": routing.next_decision(root),
            "workItem": current_work,
        }
        if intent in {"check", "finish"}:
            value["gate"] = gates.status(root)
            value["projectMode"] = workflow_projection.status(root)
            value["changeSet"] = changesets.summary(root)
            value["verification"] = verification.summary(root)
            value["trellisExecution"] = trellis_execution.status(
                root, project_mode=value["projectMode"], change_set=value["changeSet"]
            )
        if gate_decision is not None:
            value["finishDecision"] = gate_decision
        if trellis_completion is not None:
            value["trellisCompletion"] = trellis_completion
        if closure_integrity is not None:
            value["closureIntegrity"] = closure_integrity
        if intent == "finish":
            value["rememberSuggestion"] = {
                "state": "suggested-only",
                "command": command_line(
                    root,
                    "do",
                    "remember",
                    "--lesson",
                    "<verified reusable lesson>",
                    "--receipt",
                    "<verified gate-or-test receipt>",
                ),
                "writePerformed": False,
            }
        return value
    if intent == "recall":
        return _run_recall(root, request, ["do", "recall"])
    if intent == "remember":
        return _run_remember(root, request, ["do", "remember"])
    if intent == "verify":
        _require_daily_binding(root, intent, acceptance_required=True)
        first_result = request.results[0] if request.results else None
        decision = routing.decide(
            root,
            "verify",
            {
                "level": first_result.get("level") if first_result else request.level,
                "command": first_result.get("command") if first_result else request.command,
                "scope": first_result.get("scope") if first_result else request.scope,
                "snapshot": request.snapshot,
                "session": request.session,
                "outcome": request.outcome,
                "duration_ms": request.duration_ms,
                "current_snapshot": request.current_snapshot,
            },
        )
        refreshed_work = None
        if request.results is not None:
            result = verification.record_current_batch(root, request.results)
            refreshed_work = contracts.refresh_work_item(root)
        elif request.session is not None:
            result = verification.record_session(root, request.session, cast(str, request.outcome), request.duration_ms)
        elif request.outcome is None:
            result = verification.plan(root, cast(str, request.level), cast(str, request.command), request.scope)
        elif request.current_snapshot:
            result = verification.record_current(
                root,
                cast(str, request.level),
                cast(str, request.command),
                request.outcome,
                request.duration_ms,
                request.scope,
            )
            refreshed_work = contracts.refresh_work_item(root)
        else:
            result = verification.record(
                root,
                cast(str, request.level),
                cast(str, request.command),
                cast(str, request.snapshot),
                request.outcome,
                request.duration_ms,
                request.scope,
            )
        return {
            **decision,
            "executionPerformed": False,
            "context": context_policy.suggest(decision["contextIntent"]),
            "result": result,
            **({"workItem": refreshed_work} if refreshed_work is not None else {}),
        }
    if intent == "validate":
        decision = routing.decide(root, "validate", {"task": request.task})
        return _run_trellis(
            root,
            decision,
            request.approve,
            request.timeout,
            ["do", "validate", "--task", cast(str, request.task), "--timeout", str(request.timeout)],
        )
    decision = routing.decide(
        root,
        "task",
        {"operation": request.operation, "title": request.title, "task": request.task},
    )
    if decision["backend"] == "trellis":
        continuation = ["do", "task", cast(str, request.operation)]
        if request.title is not None:
            continuation.extend(("--title", request.title))
        if request.task is not None:
            continuation.extend(("--task", request.task))
        continuation.extend(("--timeout", str(request.timeout)))
        return _run_trellis(root, decision, request.approve, request.timeout, continuation)
    operation = request.operation
    if operation == "create":
        result = create_task(root, decision["arguments"]["title"])
        work_item = contracts.create_work_item(root, "local", result["id"])
    elif operation == "list":
        result = {"tasks": list_tasks(root)}
    else:
        result = show_task(root, decision["arguments"]["task"])
    return {
        **decision,
        "executionPerformed": True,
        "context": context_policy.suggest(decision["contextIntent"]),
        "result": result,
        **({"workItem": work_item} if operation == "create" else {}),
    }


class ProjectClient:
    """One-project, typed facade shared by CLI and Agent transports."""

    def __init__(self, root: str | Path) -> None:
        self._root = resolve_root(root)

    @property
    def root(self) -> Path:
        return self._root

    def open(self, *, verbose: bool = False) -> dict[str, Any]:
        with components.verification_session(), context_runtime.snapshot_session():
            return rewrite_commands(_open(self._root, verbose))

    def next(self) -> dict[str, Any]:
        with components.verification_session(), context_runtime.snapshot_session():
            return rewrite_commands(routing.next_decision(self._root))

    def resume(self, *, include_context: bool = False, token_budget: int = 256) -> dict[str, Any]:
        with components.verification_session(), context_runtime.snapshot_session():
            value = resume.build(self._root)
            if include_context:
                value["context"] = resume.context_pack(self._root, token_budget)
            return rewrite_commands(value)

    def status(self, *, verbose: bool = False) -> dict[str, Any]:
        with components.verification_session(), context_runtime.snapshot_session():
            state = _status(self._root)
            return rewrite_commands(state if verbose else _compact_status(state))

    def context(
        self,
        *,
        intent: str | None = None,
        level: str | None = None,
        task: str | None = None,
        allow_l2: bool = False,
        token_budget: int = 1_200,
        resume_context: bool = False,
        preview: bool = False,
        query: str | None = None,
        scope: str = "project",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with components.verification_session():
            if resume_context:
                if (
                    intent is not None
                    or level is not None
                    or task is not None
                    or allow_l2
                    or query is not None
                    or cursor is not None
                    or scope != "project"
                ):
                    raise ProjectError(
                        "resume context cannot be combined with level, intent, task, allow_l2, query, scope, or cursor"
                    )
                return rewrite_commands(resume.context_pack(self._root, token_budget))
            if intent is not None and intent not in context_policy.INTENT_LEVELS:
                raise ProjectError(f"unsupported context intent: {intent}")
            if level is not None and level not in {"L0", "L1", "L2"}:
                raise ProjectError("context level must be L0, L1, or L2")
            selected = context_policy.select_level(intent, level) if intent is not None else level or "L1"
            renderer = briefs.preview_context_pack if preview else briefs.context_pack
            value = renderer(
                self._root,
                selected,
                task,
                allow_l2,
                token_budget,
                query=query,
                scope=scope,
                cursor=cursor,
            )
            value["selection"] = (
                context_policy.suggest(intent, level)
                if intent is not None
                else {"level": selected, "selectionSource": "legacy-default" if level is None else "explicit"}
            )
            return rewrite_commands(value)

    def do(self, intent: DailyIntent | str, arguments: DoArguments | Mapping[str, Any] | None = None) -> dict[str, Any]:
        with components.verification_session():
            usage_sync = _deferred_usage_sync(self._root)
            return rewrite_commands({**_run_do(self._root, _do_request(intent, arguments)), "usageSync": usage_sync})


__all__ = ["DailyIntent", "DoArguments", "ProjectClient"]
