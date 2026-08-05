"""Deterministic cross-session recovery from project-local HelloDev state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import acceptance, capabilities, changesets, closure_transactions, contracts, dynamic_escalation, executable_acceptance, facade, gates, lifecycle, repository_tools, sagas, trellis_execution, verification, workflow_projection
from .command_rendering import command_line
from .project import ProjectError, project_initialized


INCOMPLETE_SAGA_PHASES = {
    "trellis-pending",
    "trellis-executed",
    "trellis-verified",
    "nocturne-executed",
    "partial",
}


def _incomplete_saga(root: Path) -> dict[str, Any] | None:
    return next(
        (state for state in sagas.list_sagas(root) if state["phase"] in INCOMPLETE_SAGA_PHASES),
        None,
    )


def _lifecycle_decision(phase: str) -> dict[str, str]:
    if phase == "blocked":
        return {
            "command": "hellodev lifecycle resume",
            "reasonCode": "lifecycle-blocked",
            "reason": "The lifecycle is blocked.",
        }
    mapping = {
        "new": ("hellodev open", "lifecycle-new", "The lifecycle has not been started."),
        "started": ("hellodev do plan", "lifecycle-started", "Planning is the next allowed phase."),
        "planned": ("hellodev do work", "lifecycle-planned", "Implementation is the next allowed phase."),
        "working": ("hellodev do check", "lifecycle-working", "Checking is the next allowed phase."),
        "checking": ("hellodev do finish", "lifecycle-checking", "Finish is the next allowed phase."),
        "finished": ("hellodev receipt list", "lifecycle-finished", "The lifecycle is finished; inspect audit receipts."),
    }
    if phase not in mapping:
        raise ProjectError(f"unsupported lifecycle phase for resume: {phase}")
    command, reason_code, reason = mapping[phase]
    return {"command": command, "reasonCode": reason_code, "reason": reason}


def _begin_decision(root: Path, work_item: dict[str, Any] | None) -> dict[str, Any]:
    """Return one self-describing intake action before lifecycle work can advance."""

    if work_item is None:
        command = 'hellodev do begin --goal "<goal>" --acceptance "<acceptance>"'
        required_inputs = ["goal", "acceptance"]
        reason = "No WorkItem is bound; establish the task goal and acceptance contract before lifecycle work."
        reason_code = "work-intake-required"
    else:
        arguments = ["do", "begin", "--acceptance", "<acceptance>"]
        if work_item["backend"] == "trellis":
            arguments.extend(("--task", work_item["nativeRef"]))
        command = command_line(root, *arguments)
        required_inputs = ["acceptance"]
        reason = "The current WorkItem has no AcceptanceContract; bind acceptance before lifecycle work."
        reason_code = "acceptance-contract-required"
    return {
        "schemaVersion": 1,
        "command": command,
        "reason": reason,
        "reasonCode": reason_code,
        "suggestedLevel": "L0",
        "action": {
            "kind": "begin-work",
            "commandTemplate": command,
            "requiredInputs": required_inputs,
            "recommendedInputs": ["requirements_file"],
            "requirementsFileRequiredForWideStrictClosure": True,
            "workItemBound": work_item is not None,
        },
        "executionPerformed": False,
    }


def next_decision(root: Path) -> dict[str, Any]:
    """Return one stable command using only project-local state."""
    if not project_initialized(root):
        return {
            "schemaVersion": 1,
            "command": "hellodev open",
            "reason": "HelloDev project state is missing.",
            "reasonCode": "project-uninitialized",
            "suggestedLevel": "L0",
            "executionPerformed": False,
        }
    from . import host_bridge, policy_evolution, transactions

    transaction_state = transactions.status(root)
    if transaction_state["pendingCount"]:
        pending = transaction_state["pending"][0]
        return {
            "schemaVersion": 1,
            "command": pending["recoveryCommand"],
            "reason": f"Policy transaction {pending['id']} stopped after {pending['state']}.",
            "reasonCode": "policy-transaction-recovery-required",
            "suggestedLevel": "L2",
            "executionPerformed": False,
        }
    capability = capabilities.status(root)
    if capability["state"] != "fresh":
        return {
            "schemaVersion": 1,
            "command": "hellodev capabilities refresh",
            "reason": "The capability cache is missing or stale.",
            "reasonCode": "capability-cache-not-fresh",
            "suggestedLevel": "L0",
            "executionPerformed": False,
        }
    closure = closure_transactions.status(root)
    if closure["recoveryRequired"]:
        phase = lifecycle.status(root)["phase"]
        arguments = ("do", "check") if phase == "working" and closure["state"] == "native-completed" else ("do", "finish")
        return {
            "schemaVersion": 1,
            "command": command_line(root, *arguments),
            "reason": (
                "Trellis completion is already recorded; reconcile the managed lifecycle without repeating the external write."
                if closure["state"] == "native-completed"
                else "A managed closure transaction is incomplete and must resume before ordinary work."
            ),
            "reasonCode": "closure-transaction-recovery-required",
            "suggestedLevel": "L2",
            "closureRecovery": closure,
            "executionPerformed": False,
        }
    pending_envelopes = host_bridge.pending_envelopes(root)
    if pending_envelopes:
        pending = pending_envelopes[0]
        return {
            "schemaVersion": 1,
            "command": pending["recoveryCommand"],
            "reason": f"HostEnvelope {pending['id']} has no recorded HostCompletion.",
            "reasonCode": "host-envelope-pending",
            "suggestedLevel": "L1",
            "executionPerformed": False,
        }
    verification_state = verification.summary(root)
    acceptance_state = acceptance.evidence(root)
    pending_verification = verification_state.get("pendingSession")
    if pending_verification is not None:
        return {
            "schemaVersion": 1,
            "command": (
                f"hellodev do verify --session {pending_verification['id']} "
                "--outcome <succeeded|failed> --duration-ms <milliseconds>"
            ),
            "reason": (
                f"Verification session {pending_verification['id']} is waiting for the host-executed "
                f"{pending_verification['level']} result in {pending_verification['scope']} scope."
            ),
            "reasonCode": "verification-session-pending",
            "suggestedLevel": "L1",
            "executionPerformed": False,
        }
    incomplete = _incomplete_saga(root)
    if incomplete is not None:
        return {
            "schemaVersion": 1,
            "command": f"hellodev saga next {incomplete['id']}",
            "reason": f"Saga {incomplete['id']} is not complete ({incomplete['phase']}).",
            "reasonCode": "saga-incomplete",
            "suggestedLevel": "L2",
            "executionPerformed": False,
        }
    work_item = contracts.current_work_item(root)
    if work_item is not None and work_item.get("sourceFingerprint") != capability["fingerprint"]:
        return {
            "schemaVersion": 1,
            "command": f"hellodev work refresh {work_item['id']}",
            "reason": "The current work pointer predates the active project fingerprint.",
            "reasonCode": "work-item-fingerprint-stale",
            "suggestedLevel": "L1",
            "executionPerformed": False,
        }
    lifecycle_state = lifecycle.status(root)
    if lifecycle_state["phase"] in {"new", "started", "planned", "working", "checking"}:
        contract = acceptance.current(root)
        if work_item is None or contract is None:
            return _begin_decision(root, work_item)
    escalation_action = dynamic_escalation.next_action(root)
    if escalation_action is not None:
        return escalation_action
    executable = executable_acceptance.status(root)
    if lifecycle_state["phase"] == "planned" and executable["required"] and not executable["satisfied"]:
        return {
            "schemaVersion": 1,
            "command": executable["next"],
            "reason": "The exact requirements source requires a reviewable executable acceptance proposal before implementation.",
            "reasonCode": "executable-acceptance-" + executable["state"],
            "suggestedLevel": "L1",
            "executableAcceptance": executable,
            "executionPerformed": False,
        }
    if lifecycle_state["phase"] == "finished":
        trellis_tasks = contracts.list_trellis_tasks(root)
        if len(trellis_tasks) == 1:
            task = trellis_tasks[0]
            return {
                "schemaVersion": 1,
                "command": command_line(root, "do", "begin", "--goal", f"Continue {task}", "--task", task),
                "reason": "One native project task is ready; begin it through the HelloDev daily facade.",
                "reasonCode": "single-native-task-ready-for-unified-begin",
                "suggestedLevel": "L1",
                "executionPerformed": False,
            }
    policy = policy_evolution.status(root)
    active_canary = policy["activeCanary"]
    if active_canary is not None and (
        active_canary.get("expired", False) or active_canary.get("exhausted", False)
    ):
        return {
            "schemaVersion": 1,
            "command": f"hellodev policy evaluate --proposal {active_canary['proposalId']}",
            "reason": "The active canary is expired or has reached its bounded completion window.",
            "reasonCode": "canary-evaluation-required",
            "suggestedLevel": "L2",
            "executionPerformed": False,
        }
    if lifecycle_state["phase"] == "checking":
        acceptance_state = acceptance.evidence(root)
        if acceptance_state["required"] and not acceptance_state["satisfied"]:
            guided_blocked = not acceptance_state["guidedAcceptance"]["satisfied"]
            host_action = acceptance_state.get("hostTest", {}).get("action")
            unchanged_failed = acceptance_state.get("hostTest", {}).get("state") == "failed" and host_action is None
            return {
                "schemaVersion": 1,
                "command": acceptance_state["next"],
                "reason": (
                    "Local guided acceptance found a blocking implementation-quality issue; "
                    "repair the change and record verification for the new snapshot before finish."
                    if guided_blocked
                    else "The current host verification already failed for unchanged inputs; diagnose or change the affected scope before retrying."
                    if unchanged_failed
                    else f"Declared acceptance is {acceptance_state['state']} and must be satisfied before finish."
                ),
                "reasonCode": "guided-acceptance-blocked" if guided_blocked else "acceptance-unchanged-failure" if unchanged_failed else "acceptance-evidence-required",
                "suggestedLevel": "L1",
                "acceptance": acceptance_state,
                **({"action": host_action} if host_action is not None else {}),
                "executionPerformed": False,
            }
        finish = gates.finish_decision(root)
        if not finish["allowed"]:
            return {
                "schemaVersion": 1,
                "command": finish["nextCommand"],
                "reason": finish["reason"],
                "reasonCode": finish["reasonCode"],
                "suggestedLevel": "L1",
                "executionPerformed": False,
            }
    if lifecycle_state["phase"] == "finished":
        pending_lesson = contracts.pending_lesson_review(root)
        if pending_lesson is not None:
            return {
                "schemaVersion": 1,
                "command": pending_lesson["reviewCommand"],
                "reason": (
                    f"LessonProposal {pending_lesson['id']} is {pending_lesson['effectiveReviewState']} and needs review; "
                    "the command is read-only and does not persist memory."
                ),
                "reasonCode": "lesson-review-required",
                "suggestedLevel": "L2",
                "executionPerformed": False,
            }
    if lifecycle_state["phase"] == "working":
        acceptance_state = acceptance.evidence(root)
        if acceptance_state["required"] and not acceptance_state["satisfied"]:
            guided_blocked = not acceptance_state["guidedAcceptance"]["satisfied"]
            host_action = acceptance_state.get("hostTest", {}).get("action")
            unchanged_failed = acceptance_state.get("hostTest", {}).get("state") == "failed" and host_action is None
            return {
                "schemaVersion": 1,
                "command": acceptance_state["next"],
                "reason": (
                    "Local guided acceptance found a blocking implementation-quality issue; "
                    "repair the change and record verification for the new snapshot."
                    if guided_blocked
                    else "The current host verification already failed for unchanged inputs; diagnose or change the affected scope before retrying."
                    if unchanged_failed
                    else f"Declared acceptance is {acceptance_state['state']}; verification is the next step."
                ),
                "reasonCode": "guided-acceptance-blocked" if guided_blocked else "acceptance-unchanged-failure" if unchanged_failed else "acceptance-verification-required",
                "suggestedLevel": "L1",
                "acceptance": acceptance_state,
                **({"action": host_action} if host_action is not None else {}),
                "executionPerformed": False,
            }
        adaptive = trellis_execution.status(root)
        if adaptive["state"] == "ready" and adaptive["verificationState"] == "missing":
            action = verification.host_action(
                root, adaptive["requiredLevel"], adaptive["command"], adaptive["scope"]
            )
            return {
                "schemaVersion": 1,
                "command": action["hostCommand"],
                "reason": (
                    f"The adaptive Trellis {adaptive['profile']} profile requires one reusable "
                    f"{adaptive['requiredLevel']} host check before lifecycle checking."
                ),
                "reasonCode": "adaptive-trellis-verification-required",
                "suggestedLevel": "L1",
                "trellisExecution": adaptive,
                "action": action,
                "executionPerformed": False,
            }
        if adaptive["state"] == "ready" and adaptive["verificationState"] == "blocked-unchanged-failure":
            return {
                "schemaVersion": 1,
                "command": command_line(root, "status", "--verbose"),
                "reason": "The exact adaptive check already failed for unchanged inputs; diagnose or change the affected scope before retrying.",
                "reasonCode": "adaptive-trellis-unchanged-failure",
                "suggestedLevel": "L1",
                "trellisExecution": adaptive,
                "executionPerformed": False,
            }
    decision: dict[str, Any] = {
        "schemaVersion": 1,
        **_lifecycle_decision(lifecycle_state["phase"]),
        "suggestedLevel": "L1" if lifecycle_state["phase"] not in {"new", "finished"} else "L0",
        "executionPerformed": False,
    }
    if lifecycle_state["phase"] == "finished":
        from . import efficiency_cycles, optimization

        try:
            hint = efficiency_cycles.next_hint(root)
        except ProjectError:
            hint = None
        if hint is None:
            hint = optimization.next_hint(root)
        if hint is not None:
            decision["efficiency"] = hint
    return decision


def build(root: Path) -> dict[str, Any]:
    """Build a bounded local recovery projection; no adapters or models run."""
    decision = next_decision(root)
    repository_tool_state = repository_tools.discover()
    if not project_initialized(root):
        return {
            "schemaVersion": 1,
            "initialized": False,
            "lifecyclePhase": None,
            "capabilityState": "unavailable",
            "currentWorkItem": None,
            "incompleteSaga": None,
            "gateState": "unavailable",
            "facade": facade.status(root),
            "repositoryTools": {
                "activeProvider": repository_tool_state["activeProvider"],
                "suggestedProvider": repository_tool_state["suggestedProvider"],
                "activationState": repository_tool_state["activationState"],
            },
            "next": decision,
            "executionPerformed": False,
        }
    capability = capabilities.status(root)
    from . import checkpoints, host_bridge, policy_evolution, transactions

    lifecycle_state = lifecycle.status(root)
    work_item = contracts.current_work_item(root)
    incomplete = _incomplete_saga(root)
    gate = gates.status(root)
    transaction_state = transactions.status(root)
    pending_envelopes = host_bridge.pending_envelopes(root)
    policy = policy_evolution.status(root)
    checkpoint = checkpoints.status(root)
    project_mode = workflow_projection.status(root)
    change_set = changesets.summary(root)
    verification_state = verification.summary(root)
    acceptance_state = acceptance.evidence(root)
    trellis_execution_state = trellis_execution.status(
        root, project_mode=project_mode, change_set=change_set
    )
    pending_lesson = contracts.pending_lesson_review(root)
    work_projection = None
    if work_item is not None:
        work_projection = {
            "id": work_item["id"],
            "backend": work_item["backend"],
            "nativeRef": work_item["nativeRef"],
            "linkedPhase": work_item["linkedPhase"],
            "fingerprintCurrent": work_item["sourceFingerprint"] == capability["fingerprint"],
        }
    return {
        "schemaVersion": 1,
        "initialized": True,
        "lifecyclePhase": lifecycle_state["phase"],
        "capabilityState": capability["state"],
        "sourceFingerprint": capability["fingerprint"],
        "currentWorkItem": work_projection,
        "incompleteSaga": (
            {"id": incomplete["id"], "phase": incomplete["phase"]}
            if incomplete is not None
            else None
        ),
        "gateState": gate["state"],
        "facade": facade.status(root),
        "gateLifecycleConsistency": gate.get("lifecycleConsistency"),
        "finishPolicy": gate["finishPolicy"],
        "pendingTransaction": transaction_state["pending"][0] if transaction_state["pending"] else None,
        "pendingHostEnvelope": pending_envelopes[0] if pending_envelopes else None,
        "activeCanary": policy["activeCanary"],
        "checkpointState": checkpoint["state"],
        "projectMode": project_mode,
        "changeSet": change_set,
        "verification": verification_state,
        "acceptance": acceptance_state,
        "trellisExecution": trellis_execution_state,
        "repositoryTools": {
            "activeProvider": repository_tool_state["activeProvider"],
            "suggestedProvider": repository_tool_state["suggestedProvider"],
            "activationState": repository_tool_state["activationState"],
        },
        "pendingLessonReview": (
            {
                "id": pending_lesson["id"],
                "effectiveReviewState": pending_lesson["effectiveReviewState"],
                "expiresAt": pending_lesson["expiresAt"],
            }
            if pending_lesson is not None
            else None
        ),
        "next": decision,
        "executionPerformed": False,
    }


def context_pack(root: Path, token_budget: int = 256) -> dict[str, Any]:
    """Return an ASCII resume handoff capped at 1 KiB and the requested budget."""
    if type(token_budget) is not int or not 32 <= token_budget <= 4096:
        raise ProjectError("resume token budget must be between 32 and 4096")
    projection = build(root)
    work = projection["currentWorkItem"]
    saga = projection["incompleteSaga"]
    transaction = projection.get("pendingTransaction")
    envelope = projection.get("pendingHostEnvelope")
    canary = projection.get("activeCanary")
    lesson = projection.get("pendingLessonReview")
    repository_tool_state = projection["repositoryTools"]
    project_mode = projection.get("projectMode") or {"mode": "unavailable"}
    change_set = projection.get("changeSet") or {"changedFileCount": 0}
    verification_state = projection.get("verification") or {"pendingSessionCount": 0, "levels": {}}
    acceptance_state = projection.get("acceptance") or {"state": "not-declared", "satisfied": False}
    lines = [
        "HelloDev resume",
        f"phase: {projection['lifecyclePhase'] or 'uninitialized'}",
        f"mode: {project_mode['mode']}",
        f"capabilities: {projection['capabilityState']}",
        (
            f"work: {work['id']} {work['backend']} {work['nativeRef']} current={str(work['fingerprintCurrent']).lower()}"
            if work is not None
            else "work: none"
        ),
        f"gate: {projection['gateState']} policy={projection.get('finishPolicy', 'suggest')}",
        f"acceptance: {acceptance_state['state']} satisfied={str(acceptance_state.get('satisfied', False)).lower()}",
        f"changes: {change_set['changedFileCount']}",
        (
            "verification: "
            f"T0={verification_state.get('levels', {}).get('T0', 0)} "
            f"T1={verification_state.get('levels', {}).get('T1', 0)} "
            f"T2={verification_state.get('levels', {}).get('T2', 0)} "
            f"pending={verification_state.get('pendingSessionCount', 0)}"
        ),
        f"saga: {saga['id']} {saga['phase']}" if saga is not None else "saga: none",
        f"transaction: {transaction['id']} {transaction['state']}" if transaction is not None else "transaction: none",
        f"host-envelope: {envelope['id']} pending" if envelope is not None else "host-envelope: none",
        f"canary: {canary['proposalId']} {canary['observedTurns']}/{canary['turnLimit']}" if canary is not None else "canary: none",
        f"checkpoint: {projection.get('checkpointState', 'not-saved')}",
        f"lesson-review: {lesson['id']} {lesson['effectiveReviewState']}" if lesson is not None else "lesson-review: none",
        (
            "repository-tools: "
            f"active={repository_tool_state['activeProvider']} "
            f"suggested={repository_tool_state['suggestedProvider']} "
            f"activation={repository_tool_state['activationState']}"
        ),
        f"next: {projection['next']['command']}",
        f"reason: {projection['next']['reasonCode']}",
    ]
    content = "\n".join(lines)
    maximum = min(1024, token_budget * 4)
    encoded = content.encode("ascii", errors="replace")
    truncated = len(encoded) > maximum
    if truncated:
        suffix = b"\n[truncated]"
        encoded = encoded[: maximum - len(suffix)].rstrip() + suffix
        content = encoded.decode("ascii")
    return {
        "schemaVersion": 1,
        "tokenBudget": token_budget,
        "byteLimit": maximum,
        "byteCount": len(encoded),
        "truncated": truncated,
        "content": content,
        "executionPerformed": False,
    }
