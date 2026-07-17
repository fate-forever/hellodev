"""Read-only, trust-aware drift aggregation for Host and evolution policy state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import capabilities, contracts, host_bridge, policy_evolution
from .project import ProjectError, load_config, resolve_root


SCHEMA_VERSION = 1


def status(root: str | Path, expected_head: str | None = None) -> dict[str, Any]:
    resolved = resolve_root(root)
    load_config(resolved)
    if expected_head is not None and not (
        isinstance(expected_head, str) and (len(expected_head) == 64 or expected_head == policy_evolution.GENESIS)
    ):
        raise ProjectError("expected ledger head must be a lowercase SHA-256 digest")
    try:
        policy = policy_evolution.status(resolved)
    except ProjectError:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "invalid",
            "reasonCode": "policy-ledger-invalid",
            "integrityState": "invalid",
            "runtimeState": "unavailable",
            "findings": [{"code": "policy-ledger-invalid", "severity": "warning"}],
            "counts": {"currentCompletions": 0, "historicalCompletions": 0, "violations": 0, "assertedUsage": 0, "unavailableUsage": 0},
            "repairCommand": "hellodev policy status",
            "executionPerformed": False,
            "persistencePerformed": False,
            "adapterCalls": [],
            "modelCalls": [],
        }
    try:
        completions = host_bridge.list_completions(resolved)
    except ProjectError:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "invalid",
            "reasonCode": "host-completion-store-invalid",
            "integrityState": "invalid",
            "runtimeState": "unavailable",
            "findings": [{"code": "host-completion-store-invalid", "severity": "warning"}],
            "counts": {"currentCompletions": 0, "historicalCompletions": 0, "violations": 0, "assertedUsage": 0, "unavailableUsage": 0},
            "repairCommand": "hellodev host status",
            "executionPerformed": False,
            "persistencePerformed": False,
            "adapterCalls": [],
            "modelCalls": [],
        }
    findings: list[dict[str, str]] = []
    capability = capabilities.status(resolved)
    if capability["state"] != "fresh":
        findings.append({"code": "capability-fingerprint-stale", "severity": "warning"})
    work = contracts.current_work_item(resolved)
    if work is not None and work["sourceFingerprint"] != capability["fingerprint"]:
        findings.append({"code": "work-item-fingerprint-stale", "severity": "warning"})
    if policy["activeCanary"] is not None and policy["activeCanary"]["expired"]:
        findings.append({"code": "canary-expired", "severity": "warning"})
    head = policy["ledgerHead"]["eventSha256"]
    if expected_head is not None and expected_head != head:
        findings.append({"code": "external-checkpoint-mismatch", "severity": "warning"})
    current = [item for item in completions[-100:] if item["policyLedgerHeadSha256"] == head]
    historical = [item for item in completions[-100:] if item["policyLedgerHeadSha256"] != head]
    effective = policy["effectivePolicy"]
    violations = 0
    for completion in current[-10:]:
        if completion["retryCount"] > effective["retry.maxAttempts"]:
            findings.append({"code": "retry-policy-exceeded", "severity": "warning"})
            violations += 1
        if completion["subagentCount"] > effective["delegation.effectiveMaxAgents"]:
            findings.append({"code": "delegation-policy-exceeded", "severity": "warning"})
            violations += 1
        if completion["budgetState"] == "exceeded":
            findings.append({"code": "declared-budget-exceeded", "severity": "warning"})
            violations += 1
        if completion["late"]:
            findings.append({"code": "host-envelope-completed-late", "severity": "info"})
    unique_findings = list({(item["code"], item["severity"]): item for item in findings}.values())
    if any(item["severity"] == "warning" for item in unique_findings):
        state, reason = "detected", "policy-or-binding-drift"
    elif not current:
        state, reason = "unavailable", "no-current-head-host-completions"
    else:
        state, reason = "clean", "current-head-completions-within-policy"
    repair = None
    if any(item["code"] == "capability-fingerprint-stale" for item in unique_findings):
        repair = "hellodev capabilities refresh"
    elif any(item["code"] == "work-item-fingerprint-stale" for item in unique_findings):
        repair = f"hellodev work refresh {work['id']}" if work is not None else "hellodev work current"
    elif any(item["code"] == "canary-expired" for item in unique_findings):
        repair = "hellodev policy revert"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": state,
        "reasonCode": reason,
        "integrityState": "structurally-valid",
        "runtimeState": "observed" if current else "unavailable",
        "policyState": policy["state"],
        "ledgerHeadSha256": head,
        "expectedHeadMatched": None if expected_head is None else expected_head == head,
        "findings": unique_findings,
        "counts": {
            "currentCompletions": len(current),
            "historicalCompletions": len(historical),
            "violations": violations,
            "assertedUsage": sum(1 for item in current if item["usageTrust"] == "host-asserted"),
            "unavailableUsage": sum(1 for item in current if item["usageTrust"] == "unavailable"),
        },
        "trustContract": "host completion counts are envelope-bound assertions unless an external verifier exists",
        "integrityGuarantee": "project-local hash chains cannot detect a full rewrite without an external checkpoint",
        "repairCommand": repair,
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }
