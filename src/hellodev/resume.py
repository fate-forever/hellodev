"""Deterministic cross-session recovery from project-local HelloDev state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import capabilities, contracts, gates, lifecycle, sagas
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
    if lifecycle_state["phase"] == "checking":
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
    decision: dict[str, Any] = {
        "schemaVersion": 1,
        **_lifecycle_decision(lifecycle_state["phase"]),
        "suggestedLevel": "L1" if lifecycle_state["phase"] not in {"new", "finished"} else "L0",
        "executionPerformed": False,
    }
    if lifecycle_state["phase"] == "finished":
        from . import optimization

        hint = optimization.next_hint(root)
        if hint is not None:
            decision["efficiency"] = hint
    return decision


def build(root: Path) -> dict[str, Any]:
    """Build a bounded local recovery projection; no adapters or models run."""
    decision = next_decision(root)
    if not project_initialized(root):
        return {
            "schemaVersion": 1,
            "initialized": False,
            "lifecyclePhase": None,
            "capabilityState": "unavailable",
            "currentWorkItem": None,
            "incompleteSaga": None,
            "gateState": "unavailable",
            "next": decision,
            "executionPerformed": False,
        }
    capability = capabilities.status(root)
    lifecycle_state = lifecycle.status(root)
    work_item = contracts.current_work_item(root)
    incomplete = _incomplete_saga(root)
    gate = gates.status(root)
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
        "finishPolicy": gate["finishPolicy"],
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
    lines = [
        "HelloDev resume",
        f"phase: {projection['lifecyclePhase'] or 'uninitialized'}",
        f"capabilities: {projection['capabilityState']}",
        (
            f"work: {work['id']} {work['backend']} {work['nativeRef']} current={str(work['fingerprintCurrent']).lower()}"
            if work is not None
            else "work: none"
        ),
        f"gate: {projection['gateState']} policy={projection.get('finishPolicy', 'suggest')}",
        f"saga: {saga['id']} {saga['phase']}" if saga is not None else "saga: none",
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
