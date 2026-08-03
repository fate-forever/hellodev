"""Adaptive, local-only acceptance checks for the current ChangeSet."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import changesets, typescript_impact, verification
from .context_runtime import semantic
from .python_impact import override_forwarding_analysis


_LITE_TERMS = re.compile(
    r"\b(?:docs?|readme|changelog|copy|typo|comment)\b|\u6587\u6863|\u8bf4\u660e|\u9519\u522b\u5b57",
    re.IGNORECASE,
)
_STRICT_TERMS = re.compile(
    r"\b(?:security|auth|permission|migration|database|delete|payment|secret|token|p0|p1)\b|"
    r"\u5b89\u5168|\u9274\u6743|\u6743\u9650|\u8fc1\u79fb|\u6570\u636e\u5e93|\u5220\u9664|\u652f\u4ed8|\u5bc6\u94a5",
    re.IGNORECASE,
)
_FEATURE_TERMS = re.compile(
    r"\b(?:add|implement|create|build|fix|repair|change|refactor|support)\b|"
    r"\u65b0\u589e|\u5b9e\u73b0|\u521b\u5efa|\u6784\u5efa|\u4fee\u590d|\u4fee\u6539|\u91cd\u6784|\u652f\u6301",
    re.IGNORECASE,
)


def _mode(contract: dict[str, Any], change: dict[str, Any], impact: dict[str, Any]) -> tuple[str, list[str]]:
    goal = contract["goal"]
    reasons: list[str] = []
    if _LITE_TERMS.search(goal) and change.get("scopeCounts", {}).get("code", 0) == 0:
        return "lite", ["documentation-goal"]
    if _STRICT_TERMS.search(goal):
        reasons.append("high-risk-goal")
    if change.get("changeKinds", {}).get("deleted", 0):
        reasons.append("deletion-detected")
    if change.get("changedFileCount", 0) > 10:
        reasons.append("wide-changeset")
    if impact.get("wideImpact"):
        reasons.append("wide-semantic-impact")
    return ("strict", reasons) if reasons else ("guided", ["code-acceptance"])


def evaluate(root: Path, contract: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate bounded local quality signals without persisting source or executing tests."""
    if contract is None:
        return {
            "schemaVersion": 1,
            "state": "not-applicable",
            "mode": "lite",
            "required": False,
            "satisfied": True,
            "blockers": [],
            "reasonCodes": ["acceptance-not-declared"],
            "executionPerformed": False,
            "testExecutionPerformed": False,
            "rawPathsExposed": False,
            "rawSymbolsExposed": False,
        }

    change = changesets.summary(root)
    analysis = changesets.changed_files_for_analysis(root)
    if analysis["state"] == "ready":
        impact = semantic.change_impact(analysis["repositoryFiles"], analysis["changedFiles"])
        typescript = typescript_impact.change_impact(analysis["repositoryFiles"], analysis["changedFiles"])
        if typescript["state"] != "not-applicable":
            impact = typescript
        forwarding = override_forwarding_analysis(
            analysis["repositoryFiles"], analysis["changedFiles"]
        )
        baseline_quality = analysis["qualityBaseline"]
        if baseline_quality["state"] == "ready":
            baseline_hashes = set(baseline_quality["overrideForwardingIssueHashes"])
            current_hashes = set(forwarding["issueHashes"])
            forwarding_issues = len(current_hashes - baseline_hashes)
        else:
            forwarding_issues = 0
        forwarding_parse_errors = forwarding["parseErrorCount"]
        forwarding_baseline_state = baseline_quality["state"]
    else:
        impact = {
            "state": analysis["state"],
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
        forwarding_issues = 0
        forwarding_parse_errors = 0
        forwarding_baseline_state = "unavailable"
        typescript = {
            "state": analysis["state"],
            "provider": "native-typescript-declaration-index",
            "changedTypeScriptFileCount": 0,
            "exportedDeclarationCount": 0,
            "referencingFileCount": 0,
            "crossFileReferenceCount": 0,
            "wideImpact": False,
            "rawSymbolsExposed": False,
            "rawPathsExposed": False,
        }

    mode, reasons = _mode(contract, change, impact)
    blockers: list[str] = []
    if (
        change["state"] == "ready"
        and mode != "lite"
        and _FEATURE_TERMS.search(contract["goal"])
        and change["scopeCounts"]["code"] == 0
    ):
        blockers.append("feature-code-change-missing")
    if forwarding_issues:
        blockers.append("python-override-parameter-not-forwarded")
    if mode == "strict" and analysis["state"] != "ready":
        blockers.append("strict-impact-analysis-unavailable")

    verification_state = verification.summary(root)
    required = mode in {"guided", "strict"} and change["state"] == "ready"
    satisfied = not blockers
    return {
        "schemaVersion": 1,
        "state": "blocked" if blockers else "ready" if analysis["state"] == "ready" else "advisory-unavailable",
        "mode": mode,
        "required": required,
        "satisfied": satisfied,
        "blockers": blockers,
        "reasonCodes": reasons,
        "changeCoverage": {
            "state": change["state"],
            "changedFileCount": change["changedFileCount"],
            "codeFileCount": change["scopeCounts"]["code"],
            "docsFileCount": change["scopeCounts"]["docs"],
            "deletedFileCount": change["changeKinds"]["deleted"],
        },
        "semanticImpact": impact,
        "typescriptImpact": typescript,
        "overrideForwarding": {
            "state": (
                "blocked"
                if forwarding_issues
                else "clear"
                if forwarding_baseline_state == "ready"
                else "advisory-baseline-unavailable"
            ),
            "issueCount": forwarding_issues,
            "parseErrorCount": forwarding_parse_errors,
            "baselineState": forwarding_baseline_state,
        },
        "verificationQuality": {
            "sourceTrust": verification_state["sourceTrust"],
            "currentRecordCount": verification_state["currentRecordCount"],
            "distinctCommandCount": verification_state.get("distinctCommandCount", 0),
            "distinctSnapshotCount": verification_state.get("distinctSnapshotCount", 0),
            "repeatedCommandCount": verification_state.get("repeatedCommandCount", 0),
            "providerSignedCount": 0,
        },
        "next": "hellodev status --verbose" if blockers else None,
        "executionPerformed": analysis["state"] == "ready",
        "testExecutionPerformed": False,
        "persistencePerformed": False,
        "rawPathsExposed": False,
        "rawSymbolsExposed": False,
        "rawSourcePersisted": False,
    }


__all__ = ["evaluate"]
