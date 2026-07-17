"""Read-only Trellis gate projection and HelloDev finish policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from . import capabilities, contracts, lifecycle
from .project import ProjectError, ProjectPaths, load_config, write_json


FinishPolicy = Literal["suggest", "require-current-gate"]
FINISH_POLICIES = {"suggest", "require-current-gate"}
DEFAULT_FINISH_POLICY: FinishPolicy = "suggest"


def _lifecycle_consistency(root: Path, gate_state: str, work_item: dict[str, Any] | None) -> dict[str, Any]:
    phase = lifecycle.status(root)["phase"]
    if work_item is None:
        state, reason = "not-applicable", "no-current-work"
    elif work_item.get("backend") != "trellis":
        state, reason = "not-applicable", "local-work-item"
    elif gate_state == "aligned" and phase in {"checking", "finished"}:
        state, reason = "consistent", "trellis-gate-and-lifecycle-aligned"
    elif gate_state == "aligned":
        state, reason = "attention", "trellis-gate-ahead-of-lifecycle"
    elif phase == "finished":
        state, reason = "attention", "hellodev-finished-without-current-trellis-gate"
    elif phase == "checking":
        state, reason = "attention", "hellodev-checking-awaits-current-trellis-gate"
    else:
        state, reason = "consistent", "gate-not-yet-required-for-active-phase"
    return {
        "state": state,
        "reasonCode": reason,
        "lifecyclePhase": phase,
        "readOnly": True,
        "trellisMutationPerformed": False,
    }


def _policy(value: Any) -> FinishPolicy:
    if value not in FINISH_POLICIES:
        raise ProjectError("finish policy must be suggest or require-current-gate")
    return value


def policy_show(root: Path) -> dict[str, Any]:
    config = load_config(root)
    value = _policy(config.get("finishPolicy", DEFAULT_FINISH_POLICY))
    return {
        "schemaVersion": 1,
        "finishPolicy": value,
        "source": "project-config" if "finishPolicy" in config else "default-0.8-compatible",
        "executionPerformed": False,
    }


def policy_set(root: Path, value: str) -> dict[str, Any]:
    """Persist a validated local policy; CLI approval remains the caller's job."""
    selected = _policy(value)
    paths = ProjectPaths(root)
    config = load_config(root)
    changed = config.get("finishPolicy", DEFAULT_FINISH_POLICY) != selected or "finishPolicy" not in config
    config["finishPolicy"] = selected
    write_json(paths.config_file, config)
    return {
        "schemaVersion": 1,
        "finishPolicy": selected,
        "changed": changed,
        "executionPerformed": True,
    }


def show_policy(root: Path) -> dict[str, Any]:
    return policy_show(root)


def set_policy(root: Path, value: str) -> dict[str, Any]:
    return policy_set(root, value)


def status(root: Path) -> dict[str, Any]:
    """Project current WorkItem and current-fingerprint gate evidence."""
    policy = policy_show(root)["finishPolicy"]
    capability = capabilities.status(root)
    work_item = contracts.current_work_item(root)
    if work_item is None:
        consistency = _lifecycle_consistency(root, "no-current-work", None)
        return {
            "schemaVersion": 1,
            "state": "no-current-work",
            "finishPolicy": policy,
            "capabilityState": capability["state"],
            "sourceFingerprint": capability["fingerprint"],
            "currentWorkItem": None,
            "validEvidence": [],
            "staleEvidenceCount": 0,
            "lifecycleConsistency": consistency,
            "trellisMutationPerformed": False,
        }
    all_links = contracts.list_evidence_links(root, work_item["id"])
    valid_links = contracts.current_valid_evidence_links(root, work_item["id"])
    if valid_links:
        state = "aligned"
    elif all_links:
        state = "stale-evidence"
    else:
        state = "evidence-missing"
    consistency = _lifecycle_consistency(root, state, work_item)
    return {
        "schemaVersion": 1,
        "state": state,
        "finishPolicy": policy,
        "capabilityState": capability["state"],
        "sourceFingerprint": capability["fingerprint"],
        "currentWorkItem": {
            key: work_item[key]
            for key in ("id", "backend", "nativeRef", "linkedPhase", "sourceFingerprint")
            if key in work_item
        },
        "validEvidence": [
            {
                key: link[key]
                for key in ("id", "receiptId", "evidenceKind", "sourceFingerprint")
                if key in link
            }
            for link in valid_links
        ],
        "staleEvidenceCount": len(all_links) - len(valid_links),
        "lifecycleConsistency": consistency,
        "trellisMutationPerformed": False,
    }


def reconcile(root: Path, receipt_id: str, work_item_id: str | None = None) -> dict[str, Any]:
    """Link existing typed evidence to HelloDev work without mutating Trellis."""
    link = contracts.reconcile_evidence(root, receipt_id, work_item_id)
    return {
        "schemaVersion": 1,
        "state": "reconciled",
        "evidenceLink": link,
        "trellisMutationPerformed": False,
    }


def finish_decision(root: Path) -> dict[str, Any]:
    projection = status(root)
    selected = projection["finishPolicy"]
    has_current_evidence = projection["state"] == "aligned" and projection["capabilityState"] == "fresh"
    current = projection["currentWorkItem"]
    evidence = projection["validEvidence"]
    if has_current_evidence:
        return {
            "schemaVersion": 1,
            "allowed": True,
            "finishPolicy": selected,
            "reasonCode": "current-gate-present",
            "reason": "Current fingerprint-bound gate or test evidence is linked to the current work item.",
            "workItemId": current["id"],
            "evidenceLinkId": evidence[0]["id"],
            "nextCommand": "hellodev do finish",
            "executionPerformed": False,
        }
    if selected == "require-current-gate":
        reason_code = {
            "no-current-work": "finish-current-work-required",
            "stale-evidence": "finish-current-gate-stale",
        }.get(projection["state"], "finish-current-gate-required")
        if projection["capabilityState"] != "fresh":
            reason_code = "finish-capability-cache-not-fresh"
        return {
            "schemaVersion": 1,
            "allowed": False,
            "finishPolicy": selected,
            "reasonCode": reason_code,
            "reason": "Finish requires successful gate or test evidence bound to the current work item and fingerprint.",
            "workItemId": current["id"] if current else None,
            "evidenceLinkId": None,
            "nextCommand": (
                "hellodev capabilities refresh"
                if projection["capabilityState"] != "fresh"
                else "hellodev gate status"
            ),
            "executionPerformed": False,
        }
    return {
        "schemaVersion": 1,
        "allowed": True,
        "finishPolicy": selected,
        "reasonCode": "finish-gate-suggested",
        "reason": "No current gate evidence is linked; suggest policy preserves the 0.8 finish behavior.",
        "workItemId": current["id"] if current else None,
        "evidenceLinkId": None,
        "nextCommand": "hellodev do finish",
        "warningCommand": "hellodev gate status",
        "executionPerformed": False,
    }
