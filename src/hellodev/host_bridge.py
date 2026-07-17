"""Host-neutral prepare/complete bridge for bounded Agent execution."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import briefs, capabilities, contracts, delegation, optimization, policy_evolution, resume
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
MAX_COMPLETIONS = 100_000
OUTCOMES = optimization.OUTCOMES
RETRIEVAL_MODES = optimization.RETRIEVAL_MODES
DELEGATION_MODES = optimization.DELEGATION_MODES


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProjectError(f"invalid {label} timestamp")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(timezone.utc)
    except ValueError as error:
        raise ProjectError(f"invalid {label} timestamp") from error


def _bounded_int(value: Any, label: str, minimum: int = 0, maximum: int = 100_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProjectError(f"invalid {label}")
    return value


def _validate_envelope(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "id", "state", "intent", "workItemId", "next", "context",
        "delegation", "usagePlan", "bindings", "authorization", "requestPayloadSha256", "nonceSha256",
        "createdAt", "expiresAt", "envelopeSha256",
    }
    if not isinstance(value, dict) or set(value) != fields or value["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid HostEnvelope fields")
    if value["state"] != "prepared" or not isinstance(value["id"], str) or not value["id"].startswith("host-envelope-"):
        raise ProjectError("invalid HostEnvelope identity")
    from . import context_policy

    context_policy.validate_intent(value["intent"])
    if value["workItemId"] is not None and not isinstance(value["workItemId"], str):
        raise ProjectError("invalid HostEnvelope WorkItem id")
    next_value = value["next"]
    if not isinstance(next_value, dict) or set(next_value) != {"command", "reasonCode", "suggestedLevel"}:
        raise ProjectError("invalid HostEnvelope next projection")
    if not all(isinstance(next_value[field], str) and next_value[field] for field in next_value):
        raise ProjectError("invalid HostEnvelope next values")
    context = value["context"]
    context_fields = {"level", "tokenBudget", "byteCap", "truncated", "text", "textSha256", "sourceFingerprint"}
    if not isinstance(context, dict) or set(context) != context_fields:
        raise ProjectError("invalid HostEnvelope context")
    if context["level"] not in {"L0", "L1", "L2"} or type(context["truncated"]) is not bool:
        raise ProjectError("invalid HostEnvelope context state")
    _bounded_int(context["tokenBudget"], "HostEnvelope context token budget", 128, 12_000)
    _bounded_int(context["byteCap"], "HostEnvelope context byte cap", 512, 48_000)
    if not isinstance(context["text"], str) or len(context["text"].encode("utf-8")) > context["byteCap"]:
        raise ProjectError("HostEnvelope context exceeds its byte cap")
    if hashlib.sha256(context["text"].encode("utf-8")).hexdigest() != context["textSha256"]:
        raise ProjectError("HostEnvelope context digest mismatch")
    if not isinstance(context["sourceFingerprint"], str) or len(context["sourceFingerprint"]) != 64:
        raise ProjectError("invalid HostEnvelope context fingerprint")
    delegation_value = value["delegation"]
    delegation_fields = {"state", "decision", "maxSubagents", "selectedRoles", "planSha256"}
    if not isinstance(delegation_value, dict) or set(delegation_value) != delegation_fields:
        raise ProjectError("invalid HostEnvelope delegation")
    if delegation_value["state"] not in {"main-only", "audit-required", "planned"}:
        raise ProjectError("invalid HostEnvelope delegation state")
    _bounded_int(delegation_value["maxSubagents"], "HostEnvelope max subagents", 0, 4)
    if not isinstance(delegation_value["selectedRoles"], list) or len(delegation_value["selectedRoles"]) > delegation_value["maxSubagents"]:
        raise ProjectError("invalid HostEnvelope selected roles")
    if not all(isinstance(item, str) and item for item in delegation_value["selectedRoles"]):
        raise ProjectError("invalid HostEnvelope selected role")
    if delegation_value["planSha256"] is not None and (
        not isinstance(delegation_value["planSha256"], str) or len(delegation_value["planSha256"]) != 64
    ):
        raise ProjectError("invalid HostEnvelope delegation digest")
    usage = value["usagePlan"]
    usage_fields = {"totalTokenCeiling", "subagentTokenCeiling", "maxSubagents", "retryMaxAttempts", "contextTokenCeiling"}
    if not isinstance(usage, dict) or set(usage) != usage_fields:
        raise ProjectError("invalid HostEnvelope usage plan")
    for field in ("totalTokenCeiling", "subagentTokenCeiling"):
        if usage[field] is not None:
            _bounded_int(usage[field], f"HostEnvelope {field}", 0)
    _bounded_int(usage["maxSubagents"], "HostEnvelope usage max subagents", 0, 4)
    _bounded_int(usage["retryMaxAttempts"], "HostEnvelope retry maximum", 1, 10)
    _bounded_int(usage["contextTokenCeiling"], "HostEnvelope context ceiling", 128, 12_000)
    if usage["subagentTokenCeiling"] is not None and usage["totalTokenCeiling"] is None:
        raise ProjectError("HostEnvelope subagent ceiling requires a total ceiling")
    if usage["subagentTokenCeiling"] is not None and usage["subagentTokenCeiling"] > usage["totalTokenCeiling"]:
        raise ProjectError("HostEnvelope subagent ceiling exceeds total")
    if usage["maxSubagents"] != delegation_value["maxSubagents"]:
        raise ProjectError("HostEnvelope delegation and usage limits disagree")
    bindings = value["bindings"]
    binding_fields = {
        "rootSha256", "capabilityFingerprint", "workItemFingerprint",
        "optimizationPolicyFingerprint", "policyLedgerHeadSha256",
    }
    if not isinstance(bindings, dict) or set(bindings) != binding_fields:
        raise ProjectError("invalid HostEnvelope bindings")
    for field, digest in bindings.items():
        if digest is not None and not (
            isinstance(digest, str)
            and (len(digest) == 64 or (field == "policyLedgerHeadSha256" and digest == policy_evolution.GENESIS))
        ):
            raise ProjectError(f"invalid HostEnvelope {field}")
    authorization = value["authorization"]
    if authorization != {"grantsExecution": False, "grantsEvidenceAuthority": False, "approvalReceiptId": None}:
        raise ProjectError("HostEnvelope cannot grant execution or evidence authority")
    for field in ("requestPayloadSha256", "nonceSha256", "envelopeSha256"):
        if not isinstance(value[field], str) or len(value[field]) != 64:
            raise ProjectError("invalid HostEnvelope digest")
    created = _parse_utc(value["createdAt"], "HostEnvelope creation")
    expires = _parse_utc(value["expiresAt"], "HostEnvelope expiry")
    if not timedelta(minutes=1) <= expires - created <= timedelta(hours=24):
        raise ProjectError("HostEnvelope expiry is outside the allowed range")
    expected_id = _canonical_digest({key: item for key, item in value.items() if key not in {"id", "envelopeSha256"}})
    expected = _canonical_digest({key: item for key, item in value.items() if key != "envelopeSha256"})
    if expected != value["envelopeSha256"] or value["id"] != f"host-envelope-{expected_id[:16]}":
        raise ProjectError("HostEnvelope digest or id mismatch")
    return value


def _validate_result(value: Any) -> dict[str, Any]:
    fields = {"outcome", "retryCount", "retrievalMode", "delegationMode", "totalTokens", "subagentTokens", "subagentCount"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectError("invalid host completion result fields")
    if value["outcome"] not in OUTCOMES or value["retrievalMode"] not in RETRIEVAL_MODES or value["delegationMode"] not in DELEGATION_MODES:
        raise ProjectError("invalid host completion result enum")
    _bounded_int(value["retryCount"], "host retry count", 0, 100)
    _bounded_int(value["subagentCount"], "host subagent count", 0, 128)
    total, subagent = value["totalTokens"], value["subagentTokens"]
    if total is None or subagent is None:
        if total is not None or subagent is not None:
            raise ProjectError("host token counts must both be reported or both unavailable")
    else:
        _bounded_int(total, "host total tokens")
        _bounded_int(subagent, "host subagent tokens")
        if subagent > total:
            raise ProjectError("host subagent tokens exceed total tokens")
    return dict(value)


def _validate_completion(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "id", "envelopeId", "envelopeSha256", "resultSha256",
        "policyLedgerHeadSha256", "capabilityFingerprint", "workItemId", "outcome",
        "retryCount", "retrievalMode", "delegationMode", "subagentCount", "usageTrust",
        "budgetState", "traceId", "late", "recordedAt",
    }
    if not isinstance(value, dict) or set(value) != fields or value["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid host completion record fields")
    if not isinstance(value["id"], str) or not value["id"].startswith("host-completion-"):
        raise ProjectError("invalid host completion id")
    if not isinstance(value["envelopeId"], str) or not value["envelopeId"].startswith("host-envelope-"):
        raise ProjectError("invalid host completion envelope id")
    for field in ("envelopeSha256", "resultSha256", "policyLedgerHeadSha256", "capabilityFingerprint"):
        if not isinstance(value[field], str) or not (
            len(value[field]) == 64 or (field == "policyLedgerHeadSha256" and value[field] == policy_evolution.GENESIS)
        ):
            raise ProjectError("invalid host completion digest")
    if value["workItemId"] is not None and not isinstance(value["workItemId"], str):
        raise ProjectError("invalid host completion WorkItem id")
    if value["outcome"] not in OUTCOMES or value["retrievalMode"] not in RETRIEVAL_MODES or value["delegationMode"] not in DELEGATION_MODES:
        raise ProjectError("invalid host completion enum")
    _bounded_int(value["retryCount"], "host completion retries", 0, 100)
    _bounded_int(value["subagentCount"], "host completion subagent count", 0, 128)
    if value["usageTrust"] not in {"host-asserted", "unavailable"} or value["budgetState"] not in {"unavailable", "unplanned", "within", "exceeded"}:
        raise ProjectError("invalid host completion trust or budget state")
    if not isinstance(value["traceId"], str) or not value["traceId"].startswith("trace-") or type(value["late"]) is not bool:
        raise ProjectError("invalid host completion trace or late state")
    _parse_utc(value["recordedAt"], "host completion")
    return value


def _load_store(root: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved = resolve_root(root)
    load_config(resolved)
    path = ProjectPaths(resolved).host_completions_file
    if not path.exists():
        return resolved, {"schemaVersion": SCHEMA_VERSION, "completions": []}
    if path.is_symlink() or not path.is_file():
        raise ProjectError("refusing unsafe host completion store")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid host completion store: {error}") from error
    if not isinstance(store, dict) or set(store) != {"schemaVersion", "completions"} or store["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid host completion store schema")
    if not isinstance(store["completions"], list) or len(store["completions"]) > MAX_COMPLETIONS:
        raise ProjectError("invalid host completion records")
    for completion in store["completions"]:
        _validate_completion(completion)
    ids = [item["id"] for item in store["completions"]]
    envelopes = [item["envelopeSha256"] for item in store["completions"]]
    if len(ids) != len(set(ids)) or len(envelopes) != len(set(envelopes)):
        raise ProjectError("duplicate host completion id or envelope")
    return resolved, store


def list_completions(root: str | Path) -> list[dict[str, Any]]:
    return list(_load_store(root)[1]["completions"])


def status(root: str | Path) -> dict[str, Any]:
    completions = list_completions(root)
    latest = completions[-1] if completions else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "ready" if completions else "unavailable",
        "completionCount": len(completions),
        "lateCount": sum(1 for item in completions if item["late"]),
        "budgetExceededCount": sum(1 for item in completions if item["budgetState"] == "exceeded"),
        "usageTrustCounts": {
            "host-asserted": sum(1 for item in completions if item["usageTrust"] == "host-asserted"),
            "unavailable": sum(1 for item in completions if item["usageTrust"] == "unavailable"),
        },
        "latest": None if latest is None else {
            key: latest[key]
            for key in ("id", "outcome", "budgetState", "usageTrust", "late", "recordedAt")
        },
        "trustContract": "standalone hosts are envelope-bound assertions, never provider-verified",
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def prepare(
    root: str | Path,
    intent: str,
    level: str | None = None,
    total_token_ceiling: int | None = None,
    subagent_token_ceiling: int | None = None,
    max_subagents: int = 0,
    work_item_id: str | None = None,
    delegation_payload: dict[str, Any] | None = None,
    ttl_seconds: int = 3_600,
    allow_l2: bool = False,
) -> dict[str, Any]:
    resolved = resolve_root(root)
    load_config(resolved)
    _bounded_int(ttl_seconds, "HostEnvelope ttl", 60, 86_400)
    evolution = policy_evolution.effective_policy(resolved)
    effective = evolution["effectivePolicy"]
    requested_agents = _bounded_int(max_subagents, "requested max subagents", 0, 4)
    bounded_agents = min(requested_agents, effective["delegation.effectiveMaxAgents"])
    planned = optimization.plan(
        resolved,
        intent,
        level,
        total_token_ceiling,
        subagent_token_ceiling,
        bounded_agents,
        work_item_id,
    )
    work = contracts.get_work_item(resolved, planned["workItemId"]) if planned["workItemId"] else None
    task_id = work["nativeRef"] if work is not None and work["backend"] == "local" else None
    context = briefs.preview_context_pack(
        resolved,
        planned["context"]["level"],
        task_id,
        allow_l2,
        planned["context"]["tokenBudget"],
    )
    if delegation_payload is None:
        delegation_view = {
            "state": "main-only" if bounded_agents == 0 else "audit-required",
            "decision": "main-only" if bounded_agents == 0 else "run-delegate-plan",
            "maxSubagents": bounded_agents,
            "selectedRoles": [],
            "planSha256": None,
        }
        delegation_sha = None
    else:
        if bounded_agents == 0:
            raise ProjectError("host delegation payload requires a positive effective max-subagents value")
        proposal = json.loads(json.dumps(delegation_payload))
        if not isinstance(proposal, dict) or not isinstance(proposal.get("limits"), dict):
            raise ProjectError("host delegation payload must use the strict delegation schema")
        proposal["limits"]["maxAgents"] = bounded_agents
        decision = delegation.plan(proposal)
        selected = decision["selectedRoles"] if decision["decision"] == "delegate" else []
        delegation_sha = _canonical_digest(decision)
        delegation_view = {
            "state": "planned",
            "decision": decision["decision"],
            "maxSubagents": bounded_agents,
            "selectedRoles": selected,
            "planSha256": delegation_sha,
        }
    next_value = resume.next_decision(resolved)
    created = datetime.now(timezone.utc).replace(microsecond=0)
    request_payload = {
        "intent": planned["intent"],
        "level": planned["context"]["level"],
        "workItemId": planned["workItemId"],
        "totalTokenCeiling": total_token_ceiling,
        "subagentTokenCeiling": subagent_token_ceiling,
        "requestedMaxSubagents": requested_agents,
        "boundedMaxSubagents": bounded_agents,
        "delegationPlanSha256": delegation_sha,
    }
    envelope: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "id": "pending",
        "state": "prepared",
        "intent": planned["intent"],
        "workItemId": planned["workItemId"],
        "next": {
            "command": next_value["command"],
            "reasonCode": next_value["reasonCode"],
            "suggestedLevel": next_value["suggestedLevel"],
        },
        "context": {
            "level": context["level"],
            "tokenBudget": context["tokenBudget"],
            "byteCap": context["byteCap"],
            "truncated": context["truncated"],
            "text": context["text"],
            "textSha256": hashlib.sha256(context["text"].encode("utf-8")).hexdigest(),
            "sourceFingerprint": context["sourceFingerprint"],
        },
        "delegation": delegation_view,
        "usagePlan": {
            "totalTokenCeiling": total_token_ceiling,
            "subagentTokenCeiling": subagent_token_ceiling,
            "maxSubagents": bounded_agents,
            "retryMaxAttempts": effective["retry.maxAttempts"],
            "contextTokenCeiling": context["tokenBudget"],
        },
        "bindings": {
            "rootSha256": planned["fingerprints"]["rootSha256"],
            "capabilityFingerprint": planned["fingerprints"]["capabilityFingerprint"],
            "workItemFingerprint": planned["fingerprints"]["workItemFingerprint"],
            "optimizationPolicyFingerprint": planned["fingerprints"]["policyFingerprint"],
            "policyLedgerHeadSha256": evolution["ledgerHeadSha256"],
        },
        "authorization": {
            "grantsExecution": False,
            "grantsEvidenceAuthority": False,
            "approvalReceiptId": None,
        },
        "requestPayloadSha256": _canonical_digest(request_payload),
        "nonceSha256": hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "expiresAt": (created + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
        "envelopeSha256": "pending",
    }
    provisional = _canonical_digest({key: value for key, value in envelope.items() if key not in {"id", "envelopeSha256"}})
    envelope["id"] = f"host-envelope-{provisional[:16]}"
    envelope["envelopeSha256"] = _canonical_digest({key: value for key, value in envelope.items() if key != "envelopeSha256"})
    return _validate_envelope(envelope)


def _current_bindings(root: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    planned = optimization.plan(
        root,
        envelope["intent"],
        envelope["context"]["level"],
        envelope["usagePlan"]["totalTokenCeiling"],
        envelope["usagePlan"]["subagentTokenCeiling"],
        envelope["usagePlan"]["maxSubagents"],
        envelope["workItemId"],
    )
    evolution = policy_evolution.effective_policy(root)
    return {
        "rootSha256": planned["fingerprints"]["rootSha256"],
        "capabilityFingerprint": planned["fingerprints"]["capabilityFingerprint"],
        "workItemFingerprint": planned["fingerprints"]["workItemFingerprint"],
        "optimizationPolicyFingerprint": planned["fingerprints"]["policyFingerprint"],
        "policyLedgerHeadSha256": evolution["ledgerHeadSha256"],
    }


def complete(root: str | Path, envelope_value: Any, result_value: Any) -> dict[str, Any]:
    resolved = resolve_root(root)
    envelope = _validate_envelope(envelope_value)
    result = _validate_result(result_value)
    result_sha256 = _canonical_digest(result)
    with locked_state(resolved, "host-completions"):
        _, store = _load_store(resolved)
        existing = next((item for item in store["completions"] if item["envelopeSha256"] == envelope["envelopeSha256"]), None)
        if existing is not None:
            if existing["resultSha256"] != result_sha256:
                raise ProjectError("HostEnvelope is already completed with a different result")
            return {
                "schemaVersion": SCHEMA_VERSION,
                "state": "existing",
                "completion": existing,
                "trace": optimization.get_trace(resolved, existing["traceId"]),
                "persistencePerformed": False,
            }
        current = _current_bindings(resolved, envelope)
        if current != envelope["bindings"]:
            raise ProjectError("HostEnvelope bindings are stale; prepare a new envelope")
        late = _parse_utc(envelope["expiresAt"], "HostEnvelope expiry") <= datetime.now(timezone.utc)
        actual = None
        if result["totalTokens"] is not None:
            actual = {
                "state": "reported",
                "usageRecordId": f"host-usage-{envelope['envelopeSha256'][:16]}",
                "recordedAt": envelope["createdAt"],
                "totalTokens": result["totalTokens"],
                "rootTokens": result["totalTokens"] - result["subagentTokens"],
                "subagentTokens": result["subagentTokens"],
                "subagentCount": result["subagentCount"],
                "sourceKind": "host-envelope",
                "sourceTrust": "host-asserted",
                "accuracy": "externally-reported; envelope-bound; not provider-verified",
                "sourceSha256": envelope["envelopeSha256"],
                "scopeSha256": result_sha256,
            }
        reflected = optimization.reflect(
            resolved,
            envelope["intent"],
            envelope["context"]["level"],
            result["outcome"],
            None,
            envelope["workItemId"],
            envelope["usagePlan"]["totalTokenCeiling"],
            envelope["usagePlan"]["subagentTokenCeiling"],
            envelope["usagePlan"]["maxSubagents"],
            result["retrievalMode"],
            result["delegationMode"],
            result["retryCount"],
            actual,
        )
        highest = max((int(item["id"].removeprefix("host-completion-")) for item in store["completions"]), default=0)
        completion = {
            "schemaVersion": SCHEMA_VERSION,
            "id": f"host-completion-{highest + 1:04d}",
            "envelopeId": envelope["id"],
            "envelopeSha256": envelope["envelopeSha256"],
            "resultSha256": result_sha256,
            "policyLedgerHeadSha256": envelope["bindings"]["policyLedgerHeadSha256"],
            "capabilityFingerprint": envelope["bindings"]["capabilityFingerprint"],
            "workItemId": envelope["workItemId"],
            "outcome": result["outcome"],
            "retryCount": result["retryCount"],
            "retrievalMode": result["retrievalMode"],
            "delegationMode": result["delegationMode"],
            "subagentCount": result["subagentCount"],
            "usageTrust": "host-asserted" if actual is not None else "unavailable",
            "budgetState": reflected["trace"]["usageEnvelope"]["budgetState"],
            "traceId": reflected["trace"]["id"],
            "late": late,
            "recordedAt": utc_now(),
        }
        _validate_completion(completion)
        store["completions"].append(completion)
        write_json(ProjectPaths(resolved).host_completions_file, store)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "completed",
        "completion": completion,
        "trace": reflected["trace"],
        "report": reflected["report"],
        "proposals": reflected["proposals"],
        "persistencePerformed": True,
    }
