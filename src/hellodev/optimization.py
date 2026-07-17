"""Deterministic, privacy-preserving optimization advice for HelloDev hosts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import capabilities, context_policy, contracts, governance
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
RULESET_CODE = "optimization-rules-v1"
ALLOWLIST_CODE = "evolution-allowlist-v1"
TRACE_PATTERN = re.compile(r"^trace-[0-9]{4,}$")
REPORT_PATTERN = re.compile(r"^reflection-[0-9]{4,}$")
PROPOSAL_PATTERN = re.compile(r"^evolution-[0-9]{4,}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
OUTCOMES = {"succeeded", "partial", "failed", "blocked"}
RETRIEVAL_MODES = {"none", "local", "narrow-memory"}
DELEGATION_MODES = {"none", "planned", "rejected", "executed"}
FINDING_CODES = {
    "usage-unavailable",
    "turn-budget-exceeded",
    "retry-threshold-exceeded",
    "outcome-not-complete",
    "delegation-cost-without-success",
}
RECOMMENDATION_CODES = {
    "record-reported-usage",
    "replan-turn-budget",
    "diagnose-before-retry",
    "prefer-main-agent",
    "keep-current-policy",
}
PROPOSAL_TARGETS = {"delegation.effectiveMaxAgents", "retry.maxAttempts"}
MAX_STORE_RECORDS = 20_000


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_digest(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"invalid {label} digest")
    return value


def _validate_id(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ProjectError(f"invalid {label} id")
    return value


def _validate_int(value: Any, label: str, minimum: int = 0, maximum: int = 100_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProjectError(f"invalid {label}")
    return value


def _validate_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) < 20:
        raise ProjectError(f"invalid {label} timestamp")
    return value


def _empty_store() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "traces": [], "reports": [], "proposals": []}


def _validate_actual(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    fields = {
        "state",
        "usageRecordId",
        "recordedAt",
        "totalTokens",
        "rootTokens",
        "subagentTokens",
        "subagentCount",
        "sourceKind",
        "sourceTrust",
        "accuracy",
        "sourceSha256",
        "scopeSha256",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectError("invalid UsageEnvelope actual fields")
    source_contracts = {
        ("operator-report", "asserted"): "externally-reported; not host-verified",
        ("host-envelope", "host-asserted"): "externally-reported; envelope-bound; not provider-verified",
    }
    source_key = (value["sourceKind"], value["sourceTrust"])
    if value["state"] != "reported" or source_key not in source_contracts:
        raise ProjectError("invalid UsageEnvelope source classification")
    if value["accuracy"] != source_contracts[source_key]:
        raise ProjectError("invalid UsageEnvelope accuracy")
    if not isinstance(value["usageRecordId"], str) or not (
        value["usageRecordId"].startswith("usage-")
        or re.fullmatch(r"host-usage-[0-9a-f]{16}", value["usageRecordId"])
    ):
        raise ProjectError("invalid UsageEnvelope usage id")
    _validate_timestamp(value["recordedAt"], "UsageEnvelope recordedAt")
    total = _validate_int(value["totalTokens"], "UsageEnvelope totalTokens")
    root = _validate_int(value["rootTokens"], "UsageEnvelope rootTokens")
    subagent = _validate_int(value["subagentTokens"], "UsageEnvelope subagentTokens")
    _validate_int(value["subagentCount"], "UsageEnvelope subagentCount", maximum=128)
    if root + subagent != total:
        raise ProjectError("UsageEnvelope token components do not equal total")
    _validate_digest(value["sourceSha256"], "UsageEnvelope source")
    _validate_digest(value["scopeSha256"], "UsageEnvelope scope")
    return value


def _validate_plan(value: Any) -> dict[str, Any]:
    fields = {"contextTokenCeiling", "totalTokenCeiling", "subagentTokenCeiling", "maxSubagents"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectError("invalid UsageEnvelope plan fields")
    _validate_int(value["contextTokenCeiling"], "context token ceiling", minimum=1)
    total = value["totalTokenCeiling"]
    subagent = value["subagentTokenCeiling"]
    if total is not None:
        total = _validate_int(total, "total token ceiling", minimum=1)
    if subagent is not None:
        subagent = _validate_int(subagent, "subagent token ceiling")
    if total is None and subagent is not None:
        raise ProjectError("subagent token ceiling requires a total token ceiling")
    if total is not None and subagent is not None and subagent > total:
        raise ProjectError("subagent token ceiling cannot exceed total token ceiling")
    maximum = _validate_int(value["maxSubagents"], "max subagents", maximum=32)
    if maximum == 0 and subagent not in {None, 0}:
        raise ProjectError("subagent token ceiling requires at least one subagent")
    return value


def _validate_usage_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "plan", "actual", "budgetState"}:
        raise ProjectError("invalid UsageEnvelope fields")
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("unsupported UsageEnvelope schema")
    _validate_plan(value["plan"])
    _validate_actual(value["actual"])
    if value["budgetState"] not in {"unavailable", "unplanned", "within", "exceeded"}:
        raise ProjectError("invalid UsageEnvelope budget state")
    return value


def _validate_trace(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "id",
        "workItemId",
        "intent",
        "contextLevel",
        "outcome",
        "retrievalMode",
        "delegationMode",
        "retryCount",
        "fingerprints",
        "usageEnvelope",
        "reasonCodes",
        "payloadSha256",
        "createdAt",
    }
    if not isinstance(value, dict) or set(value) != fields or value["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid DecisionTrace fields")
    _validate_id(value["id"], TRACE_PATTERN, "DecisionTrace")
    if value["workItemId"] is not None:
        if not isinstance(value["workItemId"], str) or contracts.WORK_ITEM_ID_PATTERN.fullmatch(value["workItemId"]) is None:
            raise ProjectError("invalid DecisionTrace WorkItem id")
    context_policy.validate_intent(value["intent"])
    context_policy.validate_level(value["contextLevel"])
    if value["outcome"] not in OUTCOMES or value["retrievalMode"] not in RETRIEVAL_MODES or value["delegationMode"] not in DELEGATION_MODES:
        raise ProjectError("invalid DecisionTrace enum")
    _validate_int(value["retryCount"], "DecisionTrace retry count", maximum=100)
    fingerprints = value["fingerprints"]
    fingerprint_fields = {
        "rootSha256",
        "capabilityFingerprint",
        "workItemFingerprint",
        "policyFingerprint",
        "contextRulesetSha256",
    }
    if not isinstance(fingerprints, dict) or set(fingerprints) != fingerprint_fields:
        raise ProjectError("invalid DecisionTrace fingerprint fields")
    for field in fingerprint_fields:
        _validate_digest(fingerprints[field], f"DecisionTrace {field}", nullable=field in {"capabilityFingerprint", "workItemFingerprint"})
    _validate_usage_envelope(value["usageEnvelope"])
    if not isinstance(value["reasonCodes"], list) or not value["reasonCodes"] or len(value["reasonCodes"]) > 16:
        raise ProjectError("invalid DecisionTrace reason codes")
    if not all(isinstance(item, str) and item in {
        "usage-unavailable",
        "usage-externally-reported",
        "total-budget-unplanned",
        "total-budget-within",
        "total-budget-exceeded",
        "outcome-succeeded",
        "outcome-incomplete",
        "retries-none",
        "retries-present",
    } for item in value["reasonCodes"]):
        raise ProjectError("invalid DecisionTrace reason code")
    _validate_digest(value["payloadSha256"], "DecisionTrace payload")
    _validate_timestamp(value["createdAt"], "DecisionTrace createdAt")
    return value


def _validate_report(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "id",
        "traceId",
        "basisSha256",
        "sampleSize",
        "metrics",
        "trend",
        "findings",
        "recommendations",
        "deepReflection",
        "deterministicPayloadSha256",
        "recordedAt",
        "executionPerformed",
        "applyPerformed",
        "adapterCalls",
        "modelCalls",
    }
    if not isinstance(value, dict) or set(value) != fields or value["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid ReflectionReport fields")
    _validate_id(value["id"], REPORT_PATTERN, "ReflectionReport")
    _validate_id(value["traceId"], TRACE_PATTERN, "ReflectionReport trace")
    _validate_digest(value["basisSha256"], "ReflectionReport basis")
    _validate_int(value["sampleSize"], "ReflectionReport sample size", minimum=1, maximum=MAX_STORE_RECORDS)
    metrics = value["metrics"]
    metric_fields = {"usageState", "budgetState", "totalTokens", "plannedTotalTokens", "retryCount", "outcome", "subagentShareBasisPoints"}
    if not isinstance(metrics, dict) or set(metrics) != metric_fields:
        raise ProjectError("invalid ReflectionReport metrics")
    if metrics["usageState"] not in {"reported", "unavailable"} or metrics["budgetState"] not in {"unavailable", "unplanned", "within", "exceeded"}:
        raise ProjectError("invalid ReflectionReport metric state")
    for field in ("totalTokens", "plannedTotalTokens", "subagentShareBasisPoints"):
        if metrics[field] is not None:
            _validate_int(metrics[field], f"ReflectionReport {field}")
    _validate_int(metrics["retryCount"], "ReflectionReport retry count", maximum=100)
    if metrics["outcome"] not in OUTCOMES:
        raise ProjectError("invalid ReflectionReport outcome")
    trend = value["trend"]
    trend_fields = {
        "scope",
        "sampleSize",
        "usageAvailableCount",
        "reportedTotalTokens",
        "averageReportedTokens",
        "reportedSubagentTokens",
        "outcomeCounts",
        "contextLevelCounts",
        "delegationExecutedCount",
        "narrowMemoryCount",
    }
    if not isinstance(trend, dict) or set(trend) != trend_fields or trend["scope"] not in {"work-item", "intent"}:
        raise ProjectError("invalid ReflectionReport trend fields")
    trend_size = _validate_int(trend["sampleSize"], "ReflectionReport trend sample size", minimum=1, maximum=MAX_STORE_RECORDS)
    if trend_size != value["sampleSize"]:
        raise ProjectError("ReflectionReport trend sample size mismatch")
    available = _validate_int(trend["usageAvailableCount"], "ReflectionReport usage count", maximum=trend_size)
    for field in ("reportedTotalTokens", "reportedSubagentTokens"):
        _validate_int(trend[field], f"ReflectionReport {field}")
    if trend["averageReportedTokens"] is not None:
        _validate_int(trend["averageReportedTokens"], "ReflectionReport average tokens")
    if available == 0 and trend["averageReportedTokens"] is not None:
        raise ProjectError("ReflectionReport average requires reported usage")
    expected_outcomes = {key: 0 for key in sorted(OUTCOMES)}
    expected_levels = {key: 0 for key in ("L0", "L1", "L2")}
    if not isinstance(trend["outcomeCounts"], dict) or set(trend["outcomeCounts"]) != set(expected_outcomes):
        raise ProjectError("invalid ReflectionReport outcome counts")
    if not isinstance(trend["contextLevelCounts"], dict) or set(trend["contextLevelCounts"]) != set(expected_levels):
        raise ProjectError("invalid ReflectionReport context counts")
    for field in ("outcomeCounts", "contextLevelCounts"):
        if any(type(count) is not int or count < 0 for count in trend[field].values()) or sum(trend[field].values()) != trend_size:
            raise ProjectError("invalid ReflectionReport trend counts")
    _validate_int(trend["delegationExecutedCount"], "ReflectionReport delegation count", maximum=trend_size)
    _validate_int(trend["narrowMemoryCount"], "ReflectionReport retrieval count", maximum=trend_size)
    if not isinstance(value["findings"], list) or len(value["findings"]) > 16:
        raise ProjectError("invalid ReflectionReport findings")
    for finding in value["findings"]:
        if not isinstance(finding, dict) or set(finding) != {"ruleCode", "severity", "observed", "threshold"}:
            raise ProjectError("invalid ReflectionReport finding")
        if finding["ruleCode"] not in FINDING_CODES or finding["severity"] not in {"info", "warning"}:
            raise ProjectError("invalid ReflectionReport finding enum")
        if not isinstance(finding["observed"], (str, int)) or isinstance(finding["observed"], bool):
            raise ProjectError("invalid ReflectionReport finding observation")
        if finding["threshold"] is not None and type(finding["threshold"]) is not int:
            raise ProjectError("invalid ReflectionReport finding threshold")
    if not isinstance(value["recommendations"], list) or not value["recommendations"] or len(value["recommendations"]) > 8:
        raise ProjectError("invalid ReflectionReport recommendations")
    for recommendation in value["recommendations"]:
        if not isinstance(recommendation, dict) or set(recommendation) != {"code", "command"}:
            raise ProjectError("invalid ReflectionReport recommendation")
        if recommendation["code"] not in RECOMMENDATION_CODES or not isinstance(recommendation["command"], str):
            raise ProjectError("invalid ReflectionReport recommendation enum")
        command = recommendation["command"]
        code = recommendation["code"]
        fixed = {
            "record-reported-usage": "hellodev usage record --total <tokens> --source <host> --scope turn",
            "diagnose-before-retry": "hellodev doctor --fix-hints",
            "keep-current-policy": "hellodev optimize status",
        }
        if code in fixed and command != fixed[code]:
            raise ProjectError("invalid ReflectionReport recommendation command")
        if code in {"replan-turn-budget", "prefer-main-agent"}:
            prefix = "hellodev optimize plan --intent "
            suffix = " --max-subagents 0" if code == "prefer-main-agent" else ""
            if not command.startswith(prefix) or not command.endswith(suffix):
                raise ProjectError("invalid ReflectionReport recommendation command")
            intent = command[len(prefix) : len(command) - len(suffix) if suffix else None]
            context_policy.validate_intent(intent)
    deep = value["deepReflection"]
    if not isinstance(deep, dict) or set(deep) != {"state", "anomaly", "tokenCeiling", "budgetRule", "usageTrust"}:
        raise ProjectError("invalid deep reflection fields")
    if deep["state"] not in {"not-triggered", "eligible", "unavailable"} or type(deep["anomaly"]) is not bool:
        raise ProjectError("invalid deep reflection state")
    if deep["tokenCeiling"] is not None:
        _validate_int(deep["tokenCeiling"], "deep reflection token ceiling", maximum=500)
    if deep["budgetRule"] != "min(500,floor(reportedTotal*0.05))" or deep["usageTrust"] not in {"asserted", "host-asserted", "unavailable"}:
        raise ProjectError("invalid deep reflection policy")
    _validate_digest(value["deterministicPayloadSha256"], "ReflectionReport deterministic payload")
    _validate_timestamp(value["recordedAt"], "ReflectionReport recordedAt")
    if value["executionPerformed"] is not False or value["applyPerformed"] is not False or value["adapterCalls"] != [] or value["modelCalls"] != []:
        raise ProjectError("ReflectionReport cannot execute or apply")
    return value


def _validate_proposal(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "id",
        "state",
        "proposalKind",
        "basePolicyFingerprint",
        "allowlistCode",
        "patches",
        "evidence",
        "reasonCodes",
        "applyAllowed",
        "requiresHumanReview",
        "proposalKeySha256",
        "createdAt",
    }
    if not isinstance(value, dict) or set(value) != fields or value["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid EvolutionProposal fields")
    _validate_id(value["id"], PROPOSAL_PATTERN, "EvolutionProposal")
    if value["state"] != "proposed" or value["proposalKind"] != "efficiency-tightening" or value["allowlistCode"] != ALLOWLIST_CODE:
        raise ProjectError("invalid EvolutionProposal policy")
    _validate_digest(value["basePolicyFingerprint"], "EvolutionProposal base policy")
    if not isinstance(value["patches"], list) or not 1 <= len(value["patches"]) <= 4:
        raise ProjectError("invalid EvolutionProposal patches")
    targets: set[str] = set()
    for patch in value["patches"]:
        patch_fields = {"target", "operation", "valueType", "fromValue", "toValue", "constraintCode"}
        if not isinstance(patch, dict) or set(patch) != patch_fields:
            raise ProjectError("invalid EvolutionProposal patch")
        if patch["target"] not in PROPOSAL_TARGETS or patch["target"] in targets:
            raise ProjectError("invalid or duplicate EvolutionProposal target")
        targets.add(patch["target"])
        if patch["operation"] != "replace" or patch["valueType"] != "integer" or patch["constraintCode"] != "tighten-only":
            raise ProjectError("invalid EvolutionProposal patch operation")
        before = _validate_int(patch["fromValue"], "EvolutionProposal fromValue", minimum=1, maximum=32)
        after = _validate_int(patch["toValue"], "EvolutionProposal toValue", minimum=1, maximum=32)
        if after >= before:
            raise ProjectError("EvolutionProposal must tighten its target")
    if not isinstance(value["evidence"], list) or not 3 <= len(value["evidence"]) <= 12:
        raise ProjectError("EvolutionProposal requires repeated bounded evidence")
    for evidence in value["evidence"]:
        if not isinstance(evidence, dict) or set(evidence) != {"kind", "id", "payloadSha256"} or evidence["kind"] != "reflection-report":
            raise ProjectError("invalid EvolutionProposal evidence")
        _validate_id(evidence["id"], REPORT_PATTERN, "EvolutionProposal evidence")
        _validate_digest(evidence["payloadSha256"], "EvolutionProposal evidence payload")
    if not isinstance(value["reasonCodes"], list) or value["reasonCodes"] not in (["repeated-retry-overhead"], ["repeated-delegation-overhead"]):
        raise ProjectError("invalid EvolutionProposal reason codes")
    if value["applyAllowed"] is not False or value["requiresHumanReview"] is not True:
        raise ProjectError("EvolutionProposal cannot be applied in 0.10.0")
    _validate_digest(value["proposalKeySha256"], "EvolutionProposal key")
    _validate_timestamp(value["createdAt"], "EvolutionProposal createdAt")
    return value


def _load_store(root: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved = resolve_root(root)
    load_config(resolved)
    path = ProjectPaths(resolved).optimization_file
    if not path.exists():
        return resolved, _empty_store()
    if path.is_symlink() or not path.is_file():
        raise ProjectError("refusing unsafe HelloDev optimization store")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev optimization store: {error}") from error
    if not isinstance(store, dict) or set(store) != {"schemaVersion", "traces", "reports", "proposals"}:
        raise ProjectError("invalid HelloDev optimization store fields")
    if store["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("unsupported HelloDev optimization store schema")
    for field in ("traces", "reports", "proposals"):
        if not isinstance(store[field], list) or len(store[field]) > MAX_STORE_RECORDS:
            raise ProjectError("invalid HelloDev optimization store entries")
    traces = [_validate_trace(item) for item in store["traces"]]
    reports = [_validate_report(item) for item in store["reports"]]
    proposals = [_validate_proposal(item) for item in store["proposals"]]
    for records, label in ((traces, "DecisionTrace"), (reports, "ReflectionReport"), (proposals, "EvolutionProposal")):
        identifiers = [item["id"] for item in records]
        if len(identifiers) != len(set(identifiers)):
            raise ProjectError(f"duplicate {label} id")
    trace_ids = {item["id"] for item in traces}
    if any(item["traceId"] not in trace_ids for item in reports):
        raise ProjectError("ReflectionReport references an unknown DecisionTrace")
    report_ids = {item["id"] for item in reports}
    if any(evidence["id"] not in report_ids for item in proposals for evidence in item["evidence"]):
        raise ProjectError("EvolutionProposal references an unknown ReflectionReport")
    return resolved, {"schemaVersion": SCHEMA_VERSION, "traces": traces, "reports": reports, "proposals": proposals}


def _next_id(records: list[dict[str, Any]], prefix: str) -> str:
    highest = max((int(item["id"].removeprefix(prefix + "-")) for item in records), default=0)
    return f"{prefix}-{highest + 1:04d}"


def _work_item(root: Path, work_item_id: str | None) -> dict[str, Any] | None:
    if work_item_id is not None:
        return contracts.get_work_item(root, work_item_id)
    return contracts.current_work_item(root)


def _fingerprints(root: Path, work: dict[str, Any] | None) -> dict[str, Any]:
    capability = capabilities.status(root)
    context_rules = {
        "levels": context_policy.LEVEL_TOKEN_BUDGETS,
        "intents": context_policy.INTENT_LEVELS,
        "reasons": context_policy.INTENT_REASON_CODES,
    }
    return {
        "rootSha256": hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest(),
        "capabilityFingerprint": capability.get("fingerprint"),
        "workItemFingerprint": work.get("sourceFingerprint") if work else None,
        "policyFingerprint": _policy_fingerprint(root),
        "contextRulesetSha256": _canonical_digest(context_rules),
    }


def _policy_fingerprint(root: Path) -> str:
    from . import policy_evolution

    return _canonical_digest(
        {
            "config": load_config(root),
            "optimizationRuleset": RULESET_CODE,
            "evolutionAllowlist": ALLOWLIST_CODE,
            "proposalTargets": sorted(PROPOSAL_TARGETS),
            "contextLevels": context_policy.LEVEL_TOKEN_BUDGETS,
            "contextIntents": context_policy.INTENT_LEVELS,
            "evolutionPolicy": policy_evolution.fingerprint_material(root),
        }
    )


def policy_fingerprint(root: str | Path) -> str:
    return _policy_fingerprint(resolve_root(root))


def _planned_usage(
    context_tokens: int,
    total_tokens: int | None,
    subagent_tokens: int | None,
    max_subagents: int,
) -> dict[str, Any]:
    value = {
        "contextTokenCeiling": context_tokens,
        "totalTokenCeiling": total_tokens,
        "subagentTokenCeiling": subagent_tokens,
        "maxSubagents": max_subagents,
    }
    return _validate_plan(value)


def _budget_state(plan_value: dict[str, Any], actual: dict[str, Any] | None) -> str:
    if actual is None:
        return "unavailable"
    total_ceiling = plan_value["totalTokenCeiling"]
    subagent_ceiling = plan_value["subagentTokenCeiling"]
    if actual["subagentCount"] > plan_value["maxSubagents"]:
        return "exceeded"
    if subagent_ceiling is not None and actual["subagentTokens"] > subagent_ceiling:
        return "exceeded"
    if total_ceiling is None:
        return "unplanned"
    if actual["totalTokens"] > total_ceiling:
        return "exceeded"
    return "within"


def plan(
    root: str | Path,
    intent: str,
    level: str | None = None,
    total_token_ceiling: int | None = None,
    subagent_token_ceiling: int | None = None,
    max_subagents: int = 0,
    work_item_id: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_root(root)
    load_config(resolved)
    decision = context_policy.suggest(intent, level)
    work = _work_item(resolved, work_item_id)
    planned = _planned_usage(
        decision["tokenBudget"], total_token_ceiling, subagent_token_ceiling, max_subagents
    )
    reason_codes = list(decision["reasonCodes"])
    if total_token_ceiling is None:
        reason_codes.append("total-token-ceiling-not-declared")
    elif total_token_ceiling < decision["tokenBudget"]:
        reason_codes.append("total-ceiling-below-context-policy-budget")
    if max_subagents:
        reason_codes.append("delegation-audit-required-before-spawn")
    else:
        reason_codes.append("main-agent-default")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "planned",
        "workItemId": work["id"] if work else None,
        "intent": decision["intent"],
        "context": decision,
        "usageEnvelope": {
            "schemaVersion": SCHEMA_VERSION,
            "plan": planned,
            "actual": None,
            "budgetState": "unavailable",
        },
        "delegation": {
            "auditRequiredBeforeSpawn": bool(max_subagents),
            "command": "hellodev delegate plan --payload <json>" if max_subagents else None,
        },
        "reflection": {
            "mode": "deterministic",
            "plannedDeepReflectionCeiling": (
                min(500, total_token_ceiling * 5 // 100) if total_token_ceiling is not None else None
            ),
            "eligibility": "anomaly-and-reported-usage-required",
            "budgetRule": "min(500,floor(reportedTotal*0.05))",
        },
        "fingerprints": _fingerprints(resolved, work),
        "reasonCodes": reason_codes,
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def _usage_envelope(
    root: Path,
    context_level: str,
    usage_id: str | None,
    total_token_ceiling: int | None,
    subagent_token_ceiling: int | None,
    max_subagents: int,
    actual_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planned = _planned_usage(
        context_policy.LEVEL_TOKEN_BUDGETS[context_level],
        total_token_ceiling,
        subagent_token_ceiling,
        max_subagents,
    )
    if usage_id is not None and actual_usage is not None:
        raise ProjectError("usage id and host actual usage cannot be combined")
    actual = governance.usage_projection(governance.get_usage_record(root, usage_id)) if usage_id else actual_usage
    if actual is not None:
        actual = _validate_actual(actual)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "plan": planned,
        "actual": actual,
        "budgetState": _budget_state(planned, actual),
    }


def _trace_reason_codes(envelope: dict[str, Any], outcome: str, retries: int) -> list[str]:
    reasons = ["usage-externally-reported" if envelope["actual"] else "usage-unavailable"]
    reasons.append(
        {
            "unavailable": "total-budget-unplanned" if envelope["actual"] else "total-budget-unplanned",
            "unplanned": "total-budget-unplanned",
            "within": "total-budget-within",
            "exceeded": "total-budget-exceeded",
        }[envelope["budgetState"]]
    )
    reasons.append("outcome-succeeded" if outcome == "succeeded" else "outcome-incomplete")
    reasons.append("retries-none" if retries == 0 else "retries-present")
    return reasons


def _trace_payload(
    root: Path,
    work: dict[str, Any] | None,
    intent: str,
    context_level: str,
    outcome: str,
    retrieval_mode: str,
    delegation_mode: str,
    retry_count: int,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    return {
        "workItemId": work["id"] if work else None,
        "intent": context_policy.validate_intent(intent),
        "contextLevel": context_policy.validate_level(context_level),
        "outcome": outcome,
        "retrievalMode": retrieval_mode,
        "delegationMode": delegation_mode,
        "retryCount": retry_count,
        "fingerprints": _fingerprints(root, work),
        "usageEnvelope": envelope,
        "reasonCodes": _trace_reason_codes(envelope, outcome, retry_count),
    }


def _findings(trace: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = trace["usageEnvelope"]
    actual = metrics["actual"]
    findings: list[dict[str, Any]] = []
    if actual is None:
        findings.append({"ruleCode": "usage-unavailable", "severity": "info", "observed": "unavailable", "threshold": None})
    if metrics["budgetState"] == "exceeded":
        findings.append({"ruleCode": "turn-budget-exceeded", "severity": "warning", "observed": actual["totalTokens"], "threshold": metrics["plan"]["totalTokenCeiling"]})
    if trace["retryCount"] >= 2:
        findings.append({"ruleCode": "retry-threshold-exceeded", "severity": "warning", "observed": trace["retryCount"], "threshold": 1})
    if trace["outcome"] != "succeeded":
        findings.append({"ruleCode": "outcome-not-complete", "severity": "warning", "observed": trace["outcome"], "threshold": None})
    if (
        trace["delegationMode"] == "executed"
        and actual is not None
        and actual["totalTokens"] > 0
        and actual["subagentTokens"] * 2 >= actual["totalTokens"]
        and trace["outcome"] != "succeeded"
    ):
        findings.append({"ruleCode": "delegation-cost-without-success", "severity": "warning", "observed": actual["subagentTokens"], "threshold": actual["totalTokens"] // 2})
    return findings


def _recommendations(trace: dict[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    codes = {item["ruleCode"] for item in findings}
    recommendations: list[dict[str, str]] = []
    if "usage-unavailable" in codes:
        recommendations.append({"code": "record-reported-usage", "command": "hellodev usage record --total <tokens> --source <host> --scope turn"})
    if "turn-budget-exceeded" in codes:
        recommendations.append({"code": "replan-turn-budget", "command": f"hellodev optimize plan --intent {trace['intent']}"})
    if "retry-threshold-exceeded" in codes or "outcome-not-complete" in codes:
        recommendations.append({"code": "diagnose-before-retry", "command": "hellodev doctor --fix-hints"})
    if "delegation-cost-without-success" in codes:
        recommendations.append({"code": "prefer-main-agent", "command": f"hellodev optimize plan --intent {trace['intent']} --max-subagents 0"})
    if not recommendations:
        recommendations.append({"code": "keep-current-policy", "command": "hellodev optimize status"})
    return recommendations


def _report_payload(trace: dict[str, Any], sample: list[dict[str, Any]]) -> dict[str, Any]:
    envelope = trace["usageEnvelope"]
    actual = envelope["actual"]
    total = actual["totalTokens"] if actual else None
    share = None if actual is None or total == 0 else actual["subagentTokens"] * 10_000 // total
    findings = _findings(trace)
    anomaly = any(item["ruleCode"] in {"turn-budget-exceeded", "retry-threshold-exceeded", "outcome-not-complete", "delegation-cost-without-success"} for item in findings)
    if not anomaly:
        deep = {"state": "not-triggered", "anomaly": False, "tokenCeiling": None, "budgetRule": "min(500,floor(reportedTotal*0.05))", "usageTrust": actual["sourceTrust"] if actual else "unavailable"}
    elif actual is None or total is None or total <= 0:
        deep = {"state": "unavailable", "anomaly": True, "tokenCeiling": None, "budgetRule": "min(500,floor(reportedTotal*0.05))", "usageTrust": "unavailable"}
    else:
        ceiling = min(500, total * 5 // 100)
        deep = {"state": "eligible" if ceiling > 0 else "unavailable", "anomaly": True, "tokenCeiling": ceiling if ceiling > 0 else None, "budgetRule": "min(500,floor(reportedTotal*0.05))", "usageTrust": actual["sourceTrust"]}
    reported = [item["usageEnvelope"]["actual"] for item in sample if item["usageEnvelope"]["actual"] is not None]
    reported_total = sum(item["totalTokens"] for item in reported)
    outcome_counts = {key: 0 for key in sorted(OUTCOMES)}
    context_counts = {key: 0 for key in ("L0", "L1", "L2")}
    for item in sample:
        outcome_counts[item["outcome"]] += 1
        context_counts[item["contextLevel"]] += 1
    return {
        "traceId": trace["id"],
        "basisSha256": trace["payloadSha256"],
        "sampleSize": len(sample),
        "metrics": {
            "usageState": "reported" if actual else "unavailable",
            "budgetState": envelope["budgetState"],
            "totalTokens": total,
            "plannedTotalTokens": envelope["plan"]["totalTokenCeiling"],
            "retryCount": trace["retryCount"],
            "outcome": trace["outcome"],
            "subagentShareBasisPoints": share,
        },
        "trend": {
            "scope": "work-item" if trace["workItemId"] else "intent",
            "sampleSize": len(sample),
            "usageAvailableCount": len(reported),
            "reportedTotalTokens": reported_total,
            "averageReportedTokens": reported_total // len(reported) if reported else None,
            "reportedSubagentTokens": sum(item["subagentTokens"] for item in reported),
            "outcomeCounts": outcome_counts,
            "contextLevelCounts": context_counts,
            "delegationExecutedCount": sum(1 for item in sample if item["delegationMode"] == "executed"),
            "narrowMemoryCount": sum(1 for item in sample if item["retrievalMode"] == "narrow-memory"),
        },
        "findings": findings,
        "recommendations": _recommendations(trace, findings),
        "deepReflection": deep,
        "executionPerformed": False,
        "applyPerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def _report_for_trace(reports: list[dict[str, Any]], trace_id: str) -> dict[str, Any] | None:
    return next((item for item in reports if item["traceId"] == trace_id), None)


def _proposal(
    proposals: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    evidence_trace_ids: list[str],
    target: str,
    before: int,
    after: int,
    reason: str,
    policy_fingerprint: str,
) -> dict[str, Any] | None:
    evidence_reports = [item for item in reports if item["traceId"] in evidence_trace_ids]
    if len(evidence_reports) < 3:
        return None
    evidence = [
        {"kind": "reflection-report", "id": item["id"], "payloadSha256": item["deterministicPayloadSha256"]}
        for item in evidence_reports[-3:]
    ]
    key = _canonical_digest({"target": target, "toValue": after, "basePolicyFingerprint": policy_fingerprint})
    existing = next((item for item in proposals if item["proposalKeySha256"] == key), None)
    if existing is not None:
        return existing
    if len(proposals) >= MAX_STORE_RECORDS:
        raise ProjectError("HelloDev evolution proposal limit reached")
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "id": _next_id(proposals, "evolution"),
        "state": "proposed",
        "proposalKind": "efficiency-tightening",
        "basePolicyFingerprint": policy_fingerprint,
        "allowlistCode": ALLOWLIST_CODE,
        "patches": [{"target": target, "operation": "replace", "valueType": "integer", "fromValue": before, "toValue": after, "constraintCode": "tighten-only"}],
        "evidence": evidence,
        "reasonCodes": [reason],
        "applyAllowed": False,
        "requiresHumanReview": True,
        "proposalKeySha256": key,
        "createdAt": utc_now(),
    }
    _validate_proposal(record)
    proposals.append(record)
    return record


def _generate_proposals(root: Path, store: dict[str, Any], trace: dict[str, Any]) -> list[dict[str, Any]]:
    from . import policy_evolution

    current_policy = policy_evolution.effective_policy(root)["effectivePolicy"]
    comparable = [item for item in store["traces"] if item["intent"] == trace["intent"]]
    created: list[dict[str, Any]] = []
    retry_traces = [item for item in comparable if item["retryCount"] >= 2][-3:]
    retry_before = current_policy["retry.maxAttempts"]
    if len(retry_traces) == 3 and retry_before > 1:
        proposal = _proposal(store["proposals"], store["reports"], [item["id"] for item in retry_traces], "retry.maxAttempts", retry_before, retry_before - 1, "repeated-retry-overhead", trace["fingerprints"]["policyFingerprint"])
        if proposal is not None:
            created.append(proposal)
    delegation_traces = [
        item for item in comparable
        if item["delegationMode"] == "executed"
        and item["outcome"] != "succeeded"
        and item["usageEnvelope"]["actual"] is not None
        and item["usageEnvelope"]["actual"]["subagentTokens"] > 0
    ][-3:]
    delegation_before = current_policy["delegation.effectiveMaxAgents"]
    if len(delegation_traces) == 3 and delegation_before > 1:
        proposal = _proposal(store["proposals"], store["reports"], [item["id"] for item in delegation_traces], "delegation.effectiveMaxAgents", delegation_before, delegation_before - 1, "repeated-delegation-overhead", trace["fingerprints"]["policyFingerprint"])
        if proposal is not None:
            created.append(proposal)
    return created


def reflect(
    root: str | Path,
    intent: str,
    context_level: str,
    outcome: str,
    usage_id: str | None = None,
    work_item_id: str | None = None,
    total_token_ceiling: int | None = None,
    subagent_token_ceiling: int | None = None,
    max_subagents: int = 0,
    retrieval_mode: str = "none",
    delegation_mode: str = "none",
    retry_count: int = 0,
    actual_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = resolve_root(root)
    load_config(resolved)
    context_policy.validate_intent(intent)
    context_policy.validate_level(context_level)
    if outcome not in OUTCOMES or retrieval_mode not in RETRIEVAL_MODES or delegation_mode not in DELEGATION_MODES:
        raise ProjectError("invalid optimize reflect enum")
    _validate_int(retry_count, "retry count", maximum=100)
    work = _work_item(resolved, work_item_id)
    envelope = _usage_envelope(
        resolved,
        context_level,
        usage_id,
        total_token_ceiling,
        subagent_token_ceiling,
        max_subagents,
        actual_usage,
    )
    payload = _trace_payload(resolved, work, intent, context_level, outcome, retrieval_mode, delegation_mode, retry_count, envelope)
    payload_sha256 = _canonical_digest(payload)
    with locked_state(resolved, "optimization"):
        _, store = _load_store(resolved)
        existing = next((item for item in store["traces"] if item["payloadSha256"] == payload_sha256), None)
        if existing is not None:
            report = _report_for_trace(store["reports"], existing["id"])
            return {"schemaVersion": SCHEMA_VERSION, "state": "existing", "trace": existing, "report": report, "proposals": [], "persistencePerformed": False}
        if len(store["traces"]) >= MAX_STORE_RECORDS or len(store["reports"]) >= MAX_STORE_RECORDS:
            raise ProjectError("HelloDev optimization store record limit reached")
        trace = {"schemaVersion": SCHEMA_VERSION, "id": _next_id(store["traces"], "trace"), **payload, "payloadSha256": payload_sha256, "createdAt": utc_now()}
        _validate_trace(trace)
        store["traces"].append(trace)
        sample = [item for item in store["traces"] if (item["workItemId"] == trace["workItemId"] if trace["workItemId"] else item["intent"] == trace["intent"])]
        report_payload = _report_payload(trace, sample)
        deterministic_sha256 = _canonical_digest(report_payload)
        report = {"schemaVersion": SCHEMA_VERSION, "id": _next_id(store["reports"], "reflection"), **report_payload, "deterministicPayloadSha256": deterministic_sha256, "recordedAt": utc_now()}
        _validate_report(report)
        store["reports"].append(report)
        created_proposals = _generate_proposals(resolved, store, trace)
        write_json(ProjectPaths(resolved).optimization_file, store)
    return {"schemaVersion": SCHEMA_VERSION, "state": "recorded", "trace": trace, "report": report, "proposals": created_proposals, "persistencePerformed": True}


def list_proposals(root: str | Path) -> dict[str, Any]:
    resolved, store = _load_store(root)
    current_fingerprint = _policy_fingerprint(resolved)
    values = [
        {**item, "stale": item["basePolicyFingerprint"] != current_fingerprint}
        for item in store["proposals"]
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "proposals": values,
        "applyAllowed": False,
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def get_trace(root: str | Path, trace_id: str) -> dict[str, Any]:
    _, store = _load_store(root)
    for trace in store["traces"]:
        if trace["id"] == trace_id:
            return trace
    raise ProjectError(f"DecisionTrace not found: {trace_id}")


def get_proposal(root: str | Path, proposal_id: str) -> dict[str, Any]:
    resolved, store = _load_store(root)
    for proposal in store["proposals"]:
        if proposal["id"] == proposal_id:
            return {
                **proposal,
                "stale": proposal["basePolicyFingerprint"] != _policy_fingerprint(resolved),
            }
    raise ProjectError(f"EvolutionProposal not found: {proposal_id}")


def status(root: str | Path) -> dict[str, Any]:
    resolved, store = _load_store(root)
    usage = governance.usage_status(resolved)
    proposal_view = list_proposals(resolved)["proposals"]
    latest_trace = store["traces"][-1] if store["traces"] else None
    latest_report = store["reports"][-1] if store["reports"] else None
    if proposal_view:
        state, reason = "review-due", "evolution-proposals-await-human-review"
    elif latest_report and any(item["severity"] == "warning" for item in latest_report["findings"]):
        state, reason = "attention", "latest-reflection-has-warning"
    elif latest_report:
        state, reason = "ready", "reflection-history-available"
    else:
        state, reason = "insufficient-data", "no-reflection-history"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": state,
        "reasonCode": reason,
        "usageState": usage["state"],
        "traceCount": len(store["traces"]),
        "reportCount": len(store["reports"]),
        "proposalCount": len(proposal_view),
        "staleProposalCount": sum(1 for item in proposal_view if item["stale"]),
        "currentWorkItemId": (contracts.current_work_item(resolved) or {}).get("id"),
        "latestUsageEnvelope": latest_trace["usageEnvelope"] if latest_trace else None,
        "latestReflection": ({"id": latest_report["id"], "traceId": latest_report["traceId"], "findingCount": len(latest_report["findings"]), "recommendations": latest_report["recommendations"], "deepReflection": latest_report["deepReflection"], "trend": latest_report["trend"]} if latest_report else None),
        "nextCommand": "hellodev optimize proposals" if proposal_view else "hellodev optimize plan --intent code",
        "applyAllowed": False,
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def next_hint(root: str | Path) -> dict[str, Any] | None:
    """Return one compact advanced hint only when optimization needs attention."""
    try:
        value = status(root)
    except ProjectError:
        # Optimization is advisory. Its invalid local state must remain visible
        # to advanced commands without blocking the daily next/resume path.
        return None
    if value["state"] not in {"attention", "review-due"}:
        return None
    latest = value["latestReflection"]
    trend = latest["trend"] if latest is not None else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": value["state"],
        "reasonCode": value["reasonCode"],
        "trend": (
            {
                "sampleSize": trend["sampleSize"],
                "usageAvailableCount": trend["usageAvailableCount"],
                "averageReportedTokens": trend["averageReportedTokens"],
            }
            if trend is not None
            else None
        ),
        "signal": {
            "findingCount": latest["findingCount"] if latest is not None else 0,
            "proposalCount": value["proposalCount"],
            "staleProposalCount": value["staleProposalCount"],
        },
        "suggestion": {
            "code": (
                "review-evolution-proposals"
                if value["state"] == "review-due"
                else "inspect-optimization-attention"
            ),
            "command": (
                "hellodev optimize proposals"
                if value["state"] == "review-due"
                else "hellodev optimize status"
            ),
        },
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def audit_summary(root: str | Path) -> dict[str, Any]:
    _, store = _load_store(root)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "traceCount": len(store["traces"]),
        "reportCount": len(store["reports"]),
        "proposalCount": len(store["proposals"]),
        "latestTraceId": store["traces"][-1]["id"] if store["traces"] else None,
        "latestReportId": store["reports"][-1]["id"] if store["reports"] else None,
        "latestProposalId": store["proposals"][-1]["id"] if store["proposals"] else None,
        "applyAllowed": False,
    }
