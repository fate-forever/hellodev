"""Typed application facade for HelloDev's bounded daily workflow.

The CLI and optional MCP transport share this module.  It deliberately owns no
cross-call cache: project state, adapter identities, profiles, and approvals
are revalidated for every operation.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, TypedDict, cast

from . import __version__
from . import (
    briefs,
    capabilities,
    components,
    context_policy,
    contracts,
    efficiency_cycles,
    gates,
    knowledge_flows,
    lifecycle,
    profiles,
    receipts,
    resume,
    routing,
    sagas,
    usage_collector,
)
from .adapters import nocturne, trellis
from .command_rendering import command_line, rewrite_commands
from .project import (
    ProjectError,
    create_task,
    init_project,
    list_tasks,
    load_config,
    nocturne_config,
    project_initialized,
    resolve_root,
    show_task,
)


DailyIntent = Literal[
    "plan",
    "work",
    "check",
    "finish",
    "task",
    "validate",
    "recall",
    "remember",
]


class DoArguments(TypedDict, total=False):
    """Typed input accepted by :meth:`ProjectClient.do`."""

    note: str | None
    operation: Literal["create", "list", "show", "current", "start", "validate"]
    title: str | None
    task: str | None
    query: str
    domain: str | None
    limit: int | None
    namespace_scope: str | None
    also_memory: bool
    lesson: str
    scope: Literal["auto", "project", "cross-project"]
    receipt: str | None
    saga: str | None
    proposal: str | None
    approve: str | None
    timeout: int


@dataclass(frozen=True)
class _DoRequest:
    do_intent: str
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


_INTENTS = frozenset({"plan", "work", "check", "finish", "task", "validate", "recall", "remember"})
_ALLOWED_ARGUMENTS: dict[str, frozenset[str]] = {
    "plan": frozenset({"note"}),
    "work": frozenset({"note"}),
    "check": frozenset({"note"}),
    "finish": frozenset({"note"}),
    "task": frozenset({"operation", "title", "task", "approve", "timeout"}),
    "validate": frozenset({"task", "approve", "timeout"}),
    "recall": frozenset(
        {"query", "domain", "limit", "namespace_scope", "also_memory", "approve", "timeout"}
    ),
    "remember": frozenset(
        {"lesson", "scope", "receipt", "saga", "proposal", "approve", "timeout"}
    ),
}
_REQUIRED_ARGUMENTS: dict[str, frozenset[str]] = {
    "task": frozenset({"operation"}),
    "validate": frozenset({"task"}),
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
    }
    for name in string_fields & set(values):
        if values[name] is not None and not isinstance(values[name], str):
            raise ProjectError(f"{name} must be a string")
    if "limit" in values and values["limit"] is not None and type(values["limit"]) is not int:
        raise ProjectError("limit must be an integer")
    missing = [
        name
        for name in _REQUIRED_ARGUMENTS.get(intent, ())
        if values.get(name) is None or values.get(name) == ""
    ]
    if missing:
        raise ProjectError(f"{intent} requires: {', '.join(sorted(missing))}")
    timeout = values.get("timeout", 30)
    timeout_ceiling = 300 if intent in {"task", "validate"} else 120
    if type(timeout) is not int or not 1 <= timeout <= timeout_ceiling:
        raise ProjectError(f"timeout must be between 1 and {timeout_ceiling} seconds")
    if "also_memory" in values and type(values["also_memory"]) is not bool:
        raise ProjectError("also_memory must be a boolean")
    if intent == "task" and values.get("operation") not in {"create", "list", "show", "current", "start", "validate"}:
        raise ProjectError("task operation must be create, list, show, current, start, or validate")
    if intent == "remember" and values.get("scope", "auto") not in {"auto", "project", "cross-project"}:
        raise ProjectError("remember scope must be auto, project, or cross-project")
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
    else:
        trellis_state = trellis.discover(root)
        nocturne_state = nocturne.status(root)
    return {
        "version": __version__,
        "root": str(root),
        "initialized": initialized,
        "project": config,
        "taskCount": task_count,
        "lifecycle": lifecycle_state,
        "capabilities": capability_cache,
        "trellis": trellis_state,
        "nocturne": nocturne_state,
        "distribution": components.availability(),
    }


def _roots_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        try:
            right.relative_to(left)
            return True
        except ValueError:
            return False


def _auto_usage_sync(root: Path) -> dict[str, Any]:
    if os.environ.get("CODEX_THREAD_ID") is None:
        return {"state": "unavailable", "reasonCode": "codex-thread-id-unavailable", "persistencePerformed": False}
    if not _roots_overlap(root.resolve(), Path.cwd().resolve()):
        return {"state": "skipped", "reasonCode": "selected-root-not-current-cwd", "persistencePerformed": False}
    try:
        value = usage_collector.sync_codex_usage(root)
    except ProjectError:
        return {"state": "unavailable", "reasonCode": "codex-runtime-sync-unavailable", "persistencePerformed": False}
    return {
        "state": value["state"],
        "recordedCount": value["recordedCount"],
        "skippedCount": value["skippedCount"],
        "remainingUnrecordedCount": value["remainingUnrecordedCount"],
        "cycleCount": value["reflectionCycle"]["cycleCount"],
        "pendingReceiptCount": value["reflectionCycle"]["pendingReceiptCount"],
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
    return blockers


def _compact_status(state: dict[str, Any]) -> dict[str, Any]:
    lifecycle_state = state.get("lifecycle") or {}
    next_step = routing.next_decision(Path(state["root"])) if state["initialized"] else None
    next_command = next_step["command"] if next_step is not None else "hellodev open"
    value: dict[str, Any] = {
        "version": state["version"],
        "root": state["root"],
        "initialized": state["initialized"],
        "phase": lifecycle_state.get("phase"),
        "blockers": _blockers(state),
        "next": next_command,
        "suggestedLevel": next_step.get("suggestedLevel", context_policy.suggested_level("status"))
        if next_step is not None
        else "L0",
    }
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


def _open(root: Path, verbose: bool) -> dict[str, Any]:
    created: dict[str, Any] | None = None
    if not project_initialized(root):
        created = init_project(root)
    state = lifecycle.status(root)
    if state["phase"] == "new":
        started = _start(root)
        usage_sync = _auto_usage_sync(root)
        result: dict[str, Any] = {"state": "opened", "created": bool(created and created["created"])}
        if verbose:
            result["start"] = started
        else:
            result.update(_compact_status(_status(root)))
        result["next"] = routing.next_decision(root)
        result["resume"] = resume.build(root)
        result["usageSync"] = usage_sync
        return result
    usage_sync = _auto_usage_sync(root)
    decision = routing.next_decision(root)
    return {
        "state": "resumed",
        "created": False,
        **(_status(root) if verbose else _compact_status(_status(root))),
        "next": decision,
        "resume": resume.build(root),
        "usageSync": usage_sync,
    }


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
        current = contracts.current_work_item(root)
        if current is not None and current["backend"] == "trellis" and current["nativeRef"] == task:
            execution["gateReconciliation"] = gates.reconcile(root, execution["receipt"]["id"])
        else:
            execution["gateReconciliation"] = {
                "state": "not-linked",
                "reason": (
                    "Validation succeeded without a matching current Trellis WorkItem, so the receipt is not "
                    "eligible for later gate reconciliation. Select the work item and rerun validation."
                ),
                "next": command_line(root, "work", "link", "--trellis-task", task),
                "then": command_line(root, "do", "validate", "--task", task),
            }
    return execution


def trellis_evidence_binding(root: Path, native_intent: str, task: str | None) -> dict[str, Any] | None:
    if native_intent != "task-validate" or not isinstance(task, str):
        return None
    current = contracts.current_work_item(root)
    if current is None or current["backend"] != "trellis" or current["nativeRef"] != task:
        return None
    return contracts.evidence_binding(root, current["id"])


def _trellis_values(decision: dict[str, Any]) -> dict[str, Any]:
    arguments = decision["arguments"]
    return {
        "title": arguments.get("title"),
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
        receipt_kind="gate" if native_intent == "task-validate" else "command",
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
            memory_domain=request.domain,
            memory_limit=request.limit,
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
    memory_projection = knowledge_flows.project_memory_result(result, plan["local"], request.limit)
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


def _run_do(root: Path, request: _DoRequest) -> dict[str, Any]:
    intent = request.do_intent
    if intent in {"plan", "work", "check", "finish"}:
        decision = routing.decide(root, intent, {"note": request.note})
        gate_decision = gates.finish_decision(root) if intent == "finish" else None
        if gate_decision is not None and not gate_decision["allowed"]:
            raise ProjectError(f"finish blocked: {gate_decision['reason']} Next: {gate_decision['nextCommand']}")
        state = lifecycle.transition(root, decision["arguments"]["target"], decision["arguments"]["note"])
        current_work = contracts.current_work_item(root)
        if current_work is not None:
            current_work = contracts.refresh_work_item(root, current_work["id"])
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
        if gate_decision is not None:
            value["finishDecision"] = gate_decision
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
        with components.verification_session():
            return rewrite_commands(_open(self._root, verbose))

    def next(self) -> dict[str, Any]:
        with components.verification_session():
            return rewrite_commands(routing.next_decision(self._root))

    def resume(self, *, include_context: bool = False, token_budget: int = 256) -> dict[str, Any]:
        with components.verification_session():
            value = resume.build(self._root)
            if include_context:
                value["context"] = resume.context_pack(self._root, token_budget)
            return rewrite_commands(value)

    def status(self, *, verbose: bool = False) -> dict[str, Any]:
        with components.verification_session():
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
    ) -> dict[str, Any]:
        with components.verification_session():
            if resume_context:
                if intent is not None or level is not None or task is not None or allow_l2:
                    raise ProjectError("resume context cannot be combined with level, intent, task, or allow_l2")
                return rewrite_commands(resume.context_pack(self._root, token_budget))
            if intent is not None and intent not in context_policy.INTENT_LEVELS:
                raise ProjectError(f"unsupported context intent: {intent}")
            if level is not None and level not in {"L0", "L1", "L2"}:
                raise ProjectError("context level must be L0, L1, or L2")
            selected = context_policy.select_level(intent, level) if intent is not None else level or "L1"
            renderer = briefs.preview_context_pack if preview else briefs.context_pack
            value = renderer(self._root, selected, task, allow_l2, token_budget)
            value["selection"] = (
                context_policy.suggest(intent, level)
                if intent is not None
                else {"level": selected, "selectionSource": "legacy-default" if level is None else "explicit"}
            )
            return rewrite_commands(value)

    def do(self, intent: DailyIntent | str, arguments: DoArguments | Mapping[str, Any] | None = None) -> dict[str, Any]:
        with components.verification_session():
            return rewrite_commands(_run_do(self._root, _do_request(intent, arguments)))


__all__ = ["DailyIntent", "DoArguments", "ProjectClient"]
