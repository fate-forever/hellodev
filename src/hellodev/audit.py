"""Privacy-preserving local audit and recovery projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import capabilities, governance, profiles, receipts
from .project import ProjectError, ProjectPaths, load_config


def _root_digest(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()


def _saga_summaries(root: Path) -> list[dict[str, Any]]:
    directory = ProjectPaths(root).sagas_dir
    if directory.is_symlink() or not directory.is_dir():
        raise ProjectError("refusing unsafe HelloDev Saga directory")
    summaries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("saga-*.json")):
        if path.is_symlink() or not path.is_file():
            raise ProjectError(f"refusing unsafe Saga audit entry: {path.name}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectError(f"invalid Saga audit entry: {path.name}: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("steps"), list):
            raise ProjectError(f"invalid Saga audit entry: {path.name}")
        summaries.append(
            {
                "id": value.get("id"),
                "phase": value.get("phase"),
                "updatedAt": value.get("updatedAt"),
                "stepCount": len(value["steps"]),
            }
        )
    return summaries


def export(root: Path) -> dict[str, Any]:
    """Return hash-only/pointer-only audit state without persisting a report."""
    from . import contracts, drift, gates, host_bridge, optimization, policy_evolution, resume

    load_config(root)
    capability_state = capabilities.status(root)
    usage = governance.usage_status(root)
    latest = usage.get("latest")
    usage_projection = {key: usage[key] for key in ("state", "records", "totalTokens", "subagentTokens", "rootTokens", "accuracy")}
    if isinstance(latest, dict):
        usage_projection["latest"] = {
            "usageRecordId": latest.get("usageRecordId"),
            "recordedAt": latest.get("recordedAt"),
            "totalTokens": latest.get("totalTokens"),
            "subagentTokens": latest.get("subagentTokens"),
            "subagentCount": latest.get("subagentCount"),
            "sourceKind": latest.get("sourceKind"),
            "sourceTrust": latest.get("sourceTrust"),
            "sourceSha256": latest.get("sourceSha256"),
            "scopeSha256": latest.get("scopeSha256"),
        }
    else:
        usage_projection["latest"] = None
    host = host_bridge.status(root)
    policy = policy_evolution.status(root)
    drift_value = drift.status(root)
    return {
        "schemaVersion": 1,
        "rootSha256": _root_digest(root),
        "capabilities": {
            "state": capability_state["state"],
            "fingerprint": capability_state["fingerprint"],
        },
        "authorizationPolicy": profiles.current_policy(root),
        "workItems": contracts.list_work_items(root),
        "lessonProposals": contracts.list_lesson_proposals(root),
        "evidenceLinks": contracts.list_evidence_links(root),
        "receipts": receipts.list_receipts(root),
        "sagas": _saga_summaries(root),
        "gate": gates.status(root),
        "resume": resume.build(root),
        "usage": usage_projection,
        "optimization": optimization.audit_summary(root),
        "hostBridge": {
            "state": host["state"],
            "completionCount": host["completionCount"],
            "lateCount": host["lateCount"],
            "budgetExceededCount": host["budgetExceededCount"],
            "usageTrustCounts": host["usageTrustCounts"],
        },
        "evolutionPolicy": {
            "state": policy["state"],
            "eventCount": policy["eventCount"],
            "ledgerHead": policy["ledgerHead"],
            "activeProposalId": policy["activeProposalId"],
        },
        "drift": {
            "state": drift_value["state"],
            "reasonCode": drift_value["reasonCode"],
            "integrityState": drift_value["integrityState"],
            "runtimeState": drift_value["runtimeState"],
            "counts": drift_value["counts"],
        },
        "persisted": False,
    }


def fix_hints(root: Path) -> dict[str, Any]:
    """Return deterministic recovery hints without changing local state."""
    from . import gates, resume

    decision = resume.next_decision(root)
    return {
        "state": "actionable",
        "next": decision,
        "gate": gates.status(root),
        "commands": [decision["command"]],
        "executionPerformed": False,
    }
