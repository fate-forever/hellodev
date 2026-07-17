"""Standalone delegation audit and source-labelled usage receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json
from .state_lock import locked_state


USAGE_SCHEMA_VERSION = 1
RUNTIME_USAGE_SCHEMA_VERSION = 1
MAX_USAGE_TOKENS = 10**15
USAGE_SOURCE_CONTRACTS = {
    ("operator-report", "asserted"): {
        "accuracy": "externally-reported; not host-verified",
        "measurement": "reported",
        "attestation": "none",
    },
    ("codex-runtime", "runtime-observed"): {
        "accuracy": "codex-runtime-completed-turn; exact; attestation=none; not estimated",
        "measurement": "exact",
        "attestation": "none",
    },
    ("codex-runtime-import", "asserted-runtime"): {
        "accuracy": "caller-selected Codex runtime metadata; exact file delta; attestation=none",
        "measurement": "exact",
        "attestation": "none",
    },
}


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _overlap(left: str, right: str) -> bool:
    a, b = left.replace("\\", "/").strip("/").casefold(), right.replace("\\", "/").strip("/").casefold()
    return not a or not b or a == b or a.startswith(b + "/") or b.startswith(a + "/")


def audit_delegation(payload: Any) -> dict[str, Any]:
    errors: list[str] = []
    reasons: list[str] = []
    if not isinstance(payload, dict):
        payload = {}
        errors.append("payload must be an object")
    context = payload.get("context")
    candidates = payload.get("candidates")
    if not isinstance(context, dict):
        errors.append("context must be an object")
    else:
        for field in ("userRequest", "repositoryRoot", "authorityStatus", "workflowState", "taskState", "returnFormat"):
            if not _nonblank(context.get(field)):
                errors.append(f"context.{field} is required")
    if not isinstance(candidates, list) or not candidates:
        errors.append("at least one candidate is required")
        candidates = []
    writes: list[tuple[str, str]] = []
    envelopes: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not all(_nonblank(candidate.get(key)) for key in ("role", "objective", "deliverable")):
            errors.append("each candidate requires role, objective, and deliverable")
            continue
        if candidate.get("independent") is not True:
            reasons.append(f"{candidate['role']} is not independently delegable")
        paths = candidate.get("writePaths", [])
        if not isinstance(paths, list) or not all(_nonblank(path) for path in paths):
            errors.append(f"{candidate['role']}.writePaths must be a string list")
            continue
        for path in paths:
            for previous_role, previous_path in writes:
                if previous_role != candidate["role"] and _overlap(path, previous_path):
                    errors.append(f"write overlap: {candidate['role']}:{path} and {previous_role}:{previous_path}")
            writes.append((candidate["role"], path))
        envelopes.append({"role": candidate["role"], "objective": candidate["objective"], "deliverable": candidate["deliverable"], "writePaths": paths})
    benefit = payload.get("parallelBenefit")
    effort = payload.get("mainAgentEffort")
    requested = payload.get("userExplicitlyRequested") is True
    valuable = (len(envelopes) > 1 and benefit in {"material", "high"} and effort in {"moderate", "large"}) or (requested and effort in {"moderate", "large"})
    if not valuable:
        reasons.append("main agent preferred: insufficient independent parallel value")
    delegate = not errors and not reasons and valuable
    result = {"schemaVersion": 1, "delegate": delegate, "decision": "delegate" if delegate else "main-agent", "errors": errors, "reasons": reasons, "contextEnvelopes": envelopes if delegate else [], "executionPerformed": False}
    result["auditReceiptSha256"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode("utf-8")).hexdigest()
    return result


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _validate_legacy_usage_record(record: Any) -> dict[str, Any]:
    fields = {"id", "recordedAt", "totalTokens", "subagentTokens", "subagentCount", "source", "scope", "accuracy"}
    if not isinstance(record, dict) or set(record) != fields:
        raise ProjectError("invalid legacy HelloDev usage record fields")
    identifier = record.get("id")
    if not isinstance(identifier, str) or not identifier.startswith("usage-") or not identifier[6:].isdigit():
        raise ProjectError("invalid legacy HelloDev usage record id")
    counts = (record.get("totalTokens"), record.get("subagentTokens"), record.get("subagentCount"))
    if any(type(value) is not int or value < 0 for value in counts) or counts[1] > counts[0]:
        raise ProjectError("invalid legacy HelloDev usage counts")
    if not _nonblank(record.get("recordedAt")) or not _nonblank(record.get("source")) or not _nonblank(record.get("scope")):
        raise ProjectError("invalid legacy HelloDev usage labels")
    if record.get("accuracy") != "reported":
        raise ProjectError("invalid legacy HelloDev usage accuracy")
    return record


def _normalize_legacy_usage_record(record: Any) -> dict[str, Any]:
    value = _validate_legacy_usage_record(record)
    normalized = {
        "id": value["id"],
        "recordedAt": value["recordedAt"],
        "completedAt": value["recordedAt"],
        "totalTokens": value["totalTokens"],
        "inputTokens": None,
        "cachedInputTokens": None,
        "outputTokens": None,
        "reasoningOutputTokens": None,
        "subagentTokens": value["subagentTokens"],
        "subagentCount": value["subagentCount"],
        "sourceKind": "operator-report",
        "sourceTrust": "asserted",
        **USAGE_SOURCE_CONTRACTS[("operator-report", "asserted")],
        "sourceSha256": _sha256_text(value["source"]),
        "scopeSha256": _sha256_text(value["scope"]),
        "receiptSha256": "",
    }
    normalized["receiptSha256"] = _usage_receipt_digest(normalized)
    return normalized


def _read_json_store(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev {label} store")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev {label} store: {error}") from error
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "records"} or not isinstance(value.get("records"), list):
        raise ProjectError(f"invalid HelloDev {label} store schema")
    return value


def _legacy_usage_store(root: Path) -> dict[str, Any]:
    load_config(root)
    value = _read_json_store(ProjectPaths(root).usage_file, "usage")
    if value is None:
        return {"schemaVersion": USAGE_SCHEMA_VERSION, "records": []}
    if value.get("schemaVersion") != USAGE_SCHEMA_VERSION:
        raise ProjectError("invalid HelloDev usage store schema")
    records = [_validate_legacy_usage_record(record) for record in value["records"]]
    identifiers = [record["id"] for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ProjectError("duplicate HelloDev usage record id")
    return {"schemaVersion": USAGE_SCHEMA_VERSION, "records": records}


def _runtime_usage_store(root: Path) -> dict[str, Any]:
    load_config(root)
    value = _read_json_store(ProjectPaths(root).runtime_usage_file, "runtime usage receipt")
    if value is None:
        return {"schemaVersion": RUNTIME_USAGE_SCHEMA_VERSION, "records": []}
    if value.get("schemaVersion") != RUNTIME_USAGE_SCHEMA_VERSION:
        raise ProjectError("invalid HelloDev runtime usage receipt store schema")
    records = [_validate_usage_record(record) for record in value["records"]]
    if any(record["sourceTrust"] not in {"runtime-observed", "asserted-runtime"} for record in records):
        raise ProjectError("invalid HelloDev runtime usage receipt source")
    identifiers = [record["id"] for record in records]
    receipts = [record["receiptSha256"] for record in records]
    scopes = [(record["sourceKind"], record["scopeSha256"]) for record in records]
    if len(identifiers) != len(set(identifiers)) or len(receipts) != len(set(receipts)) or len(scopes) != len(set(scopes)):
        raise ProjectError("duplicate HelloDev runtime usage receipt")
    return {"schemaVersion": RUNTIME_USAGE_SCHEMA_VERSION, "records": records}


def _usage_store(root: Path) -> dict[str, Any]:
    manual = [_normalize_legacy_usage_record(record) for record in _legacy_usage_store(root)["records"]]
    runtime = _runtime_usage_store(root)["records"]
    records = sorted([*manual, *runtime], key=lambda item: (item["completedAt"], item["recordedAt"], item["id"]))
    identifiers = [record["id"] for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ProjectError("duplicate HelloDev usage record id")
    return {"schemaVersion": 2, "records": records}


def _usage_receipt_digest(record: dict[str, Any]) -> str:
    if record["sourceKind"] == "operator-report":
        payload = {
            "kind": "operator-report",
            "recordedAt": record["recordedAt"],
            "totalTokens": record["totalTokens"],
            "subagentTokens": record["subagentTokens"],
            "subagentCount": record["subagentCount"],
            "sourceSha256": record["sourceSha256"],
            "scopeSha256": record["scopeSha256"],
        }
    else:
        payload = {
            "kind": record["sourceKind"],
            "completedAt": record["completedAt"],
            "totalTokens": record["totalTokens"],
            "inputTokens": record["inputTokens"],
            "cachedInputTokens": record["cachedInputTokens"],
            "outputTokens": record["outputTokens"],
            "reasoningOutputTokens": record["reasoningOutputTokens"],
            "subagentTokens": record["subagentTokens"],
            "subagentCount": record["subagentCount"],
            "sourceTrust": record["sourceTrust"],
            "sourceSha256": record["sourceSha256"],
            "scopeSha256": record["scopeSha256"],
        }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_usage_record(record: Any) -> dict[str, Any]:
    fields = {
        "id",
        "recordedAt",
        "completedAt",
        "totalTokens",
        "inputTokens",
        "cachedInputTokens",
        "outputTokens",
        "reasoningOutputTokens",
        "subagentTokens",
        "subagentCount",
        "sourceKind",
        "sourceTrust",
        "accuracy",
        "measurement",
        "attestation",
        "sourceSha256",
        "scopeSha256",
        "receiptSha256",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise ProjectError("invalid HelloDev usage record fields")
    identifier = record.get("id")
    valid_identifier = isinstance(identifier, str) and (
        (identifier.startswith("usage-") and identifier[6:].isdigit())
        or (identifier.startswith("runtime-usage-") and identifier[14:].isdigit())
    )
    if not valid_identifier:
        raise ProjectError("invalid HelloDev usage record id")
    counts = (record.get("totalTokens"), record.get("subagentTokens"), record.get("subagentCount"))
    if any(type(value) is not int or value < 0 for value in counts) or counts[0] > MAX_USAGE_TOKENS or counts[1] > counts[0] or counts[2] > 128:
        raise ProjectError("invalid HelloDev usage counts")
    if not _nonblank(record.get("recordedAt")) or not _nonblank(record.get("completedAt")):
        raise ProjectError("invalid HelloDev usage record labels")
    source_key = (record.get("sourceKind"), record.get("sourceTrust"))
    contract = USAGE_SOURCE_CONTRACTS.get(source_key)
    if contract is None or any(record.get(field) != contract[field] for field in ("accuracy", "measurement", "attestation")):
        raise ProjectError("invalid HelloDev usage source classification")
    breakdown = tuple(record.get(field) for field in ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens"))
    if source_key == ("operator-report", "asserted"):
        if any(value is not None for value in breakdown):
            raise ProjectError("operator-reported usage cannot claim a runtime breakdown")
    else:
        if any(type(value) is not int or value < 0 or value > MAX_USAGE_TOKENS for value in breakdown):
            raise ProjectError("invalid HelloDev runtime usage breakdown")
        input_tokens, cached_tokens, output_tokens, reasoning_tokens = breakdown
        if cached_tokens > input_tokens or reasoning_tokens > output_tokens or input_tokens + output_tokens != record["totalTokens"]:
            raise ProjectError("inconsistent HelloDev runtime usage breakdown")
    if not all(_valid_digest(record.get(field)) for field in ("sourceSha256", "scopeSha256", "receiptSha256")):
        raise ProjectError("invalid HelloDev usage digest")
    if record["receiptSha256"] != _usage_receipt_digest(record):
        raise ProjectError("HelloDev usage receipt digest mismatch")
    return record


def list_usage_records(root: Path) -> list[dict[str, Any]]:
    return list(_usage_store(root)["records"])


def list_runtime_usage_records(root: Path) -> list[dict[str, Any]]:
    """Return validated additive runtime receipts in stable insertion order."""
    return list(_runtime_usage_store(root)["records"])


def get_usage_record(root: Path, usage_id: str) -> dict[str, Any]:
    if not isinstance(usage_id, str):
        raise ProjectError("usage id is required")
    records = list_usage_records(root)
    if usage_id == "latest":
        if not records:
            raise ProjectError("no externally reported usage is available")
        return records[-1]
    for record in records:
        if record["id"] == usage_id:
            return record
    raise ProjectError(f"usage record not found: {usage_id}")


def usage_projection(record: dict[str, Any]) -> dict[str, Any]:
    _validate_usage_record(record)
    return {
        "state": "reported",
        "usageRecordId": record["id"],
        "recordedAt": record["recordedAt"],
        "totalTokens": record["totalTokens"],
        "rootTokens": record["totalTokens"] - record["subagentTokens"],
        "subagentTokens": record["subagentTokens"],
        "subagentCount": record["subagentCount"],
        "sourceKind": record["sourceKind"],
        "sourceTrust": record["sourceTrust"],
        "accuracy": record["accuracy"],
        "sourceSha256": record["sourceSha256"],
        "scopeSha256": record["scopeSha256"],
    }


def usage_breakdown_projection(record: dict[str, Any]) -> dict[str, Any] | None:
    _validate_usage_record(record)
    if record["inputTokens"] is None:
        return None
    return {
        "inputTokens": record["inputTokens"],
        "cachedInputTokens": record["cachedInputTokens"],
        "outputTokens": record["outputTokens"],
        "reasoningOutputTokens": record["reasoningOutputTokens"],
    }


def usage_public_projection(record: dict[str, Any]) -> dict[str, Any]:
    value = usage_projection(record)
    return {
        **value,
        "completedAt": record["completedAt"],
        "measurement": record["measurement"],
        "attestation": record["attestation"],
        "breakdown": usage_breakdown_projection(record),
    }


def record_usage(root: Path, total: int, subagent: int, subagents: int, source: str, scope: str) -> dict[str, Any]:
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (total, subagent, subagents)) or subagent > total:
        raise ProjectError("usage counts must be non-negative integers and subagent tokens cannot exceed total")
    if not _nonblank(source) or not _nonblank(scope):
        raise ProjectError("usage source and scope are required")
    if len(source) > 128 or len(scope) > 256 or "\n" in source or "\r" in source or "\n" in scope or "\r" in scope:
        raise ProjectError("usage source and scope must be bounded single-line labels")
    with locked_state(root, "usage"):
        store = _legacy_usage_store(root)
        if len(store["records"]) >= 100_000:
            raise ProjectError("HelloDev usage store record limit reached")
        highest = max((int(item["id"].removeprefix("usage-")) for item in store["records"]), default=0)
        recorded_at = utc_now()
        legacy_record = {
            "id": f"usage-{highest + 1:04d}",
            "recordedAt": recorded_at,
            "totalTokens": total,
            "subagentTokens": subagent,
            "subagentCount": subagents,
            "source": source,
            "scope": scope,
            "accuracy": "reported",
        }
        store["records"].append(legacy_record)
        write_json(ProjectPaths(root).usage_file, store)
    return legacy_record


def record_runtime_usage(
    root: Path,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_output_tokens: int,
    subagent_tokens: int,
    subagent_count: int,
    completed_at: str,
    source_sha256: str,
    scope_sha256: str,
    source_kind: str,
    source_trust: str,
) -> dict[str, Any]:
    total = input_tokens + output_tokens
    candidate = {
        "id": "runtime-usage-0000",
        "recordedAt": utc_now(),
        "completedAt": completed_at,
        "totalTokens": total,
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_input_tokens,
        "outputTokens": output_tokens,
        "reasoningOutputTokens": reasoning_output_tokens,
        "subagentTokens": subagent_tokens,
        "subagentCount": subagent_count,
        "sourceKind": source_kind,
        "sourceTrust": source_trust,
        **USAGE_SOURCE_CONTRACTS.get((source_kind, source_trust), {}),
        "sourceSha256": source_sha256,
        "scopeSha256": scope_sha256,
        "receiptSha256": "",
    }
    if (source_kind, source_trust) not in USAGE_SOURCE_CONTRACTS or source_trust == "asserted":
        raise ProjectError("invalid runtime usage source classification")
    candidate["receiptSha256"] = _usage_receipt_digest(candidate)
    _validate_usage_record(candidate)
    with locked_state(root, "usage"):
        store = _runtime_usage_store(root)
        for existing in store["records"]:
            if existing["receiptSha256"] == candidate["receiptSha256"]:
                return {"state": "existing", "record": existing}
            if existing["scopeSha256"] == scope_sha256:
                raise ProjectError("conflicting Codex runtime usage for the same completed turn")
        if len(store["records"]) >= 100_000:
            raise ProjectError("HelloDev usage store record limit reached")
        highest = max((int(item["id"].removeprefix("runtime-usage-")) for item in store["records"]), default=0)
        candidate["id"] = f"runtime-usage-{highest + 1:04d}"
        store["records"].append(candidate)
        write_json(ProjectPaths(root).runtime_usage_file, store)
    return {"state": "recorded", "record": candidate}


def usage_status(root: Path) -> dict[str, Any]:
    records = _usage_store(root)["records"]
    if not records:
        return {
            "state": "unavailable",
            "records": 0,
            "totalTokens": None,
            "subagentTokens": None,
            "rootTokens": None,
            "latest": None,
            "latestBreakdown": None,
            "preferred": None,
            "preferredBreakdown": None,
            "preferredDetails": None,
            "trustCounts": {"asserted": 0, "asserted-runtime": 0, "runtime-observed": 0},
            "accuracy": "unavailable; no externally reported usage",
        }
    total = sum(item.get("totalTokens", 0) for item in records)
    subagent = sum(item.get("subagentTokens", 0) for item in records)
    observed = [item for item in records if item["sourceTrust"] == "runtime-observed"]
    imported = [item for item in records if item["sourceTrust"] == "asserted-runtime"]
    preferred = observed[-1] if observed else imported[-1] if imported else records[-1]
    trust_values = {item["sourceTrust"] for item in records}
    accuracy = (
        "reported-only; externally reported; no Codex runtime receipt"
        if trust_values == {"asserted"}
        else "runtime-observed exact completed-turn receipts; attestation=none"
        if trust_values == {"runtime-observed"}
        else "caller-selected exact runtime metadata; attestation=none"
        if trust_values == {"asserted-runtime"}
        else "mixed-trust usage ledger; runtime-observed preferred over caller-selected and asserted values"
    )
    return {
        "state": "reported",
        "records": len(records),
        "totalTokens": total,
        "subagentTokens": subagent,
        "rootTokens": total - subagent,
        "latest": usage_projection(records[-1]),
        "latestBreakdown": usage_breakdown_projection(records[-1]),
        "preferred": usage_projection(preferred),
        "preferredBreakdown": usage_breakdown_projection(preferred),
        "preferredDetails": usage_public_projection(preferred),
        "trustCounts": {
            "asserted": sum(1 for item in records if item["sourceTrust"] == "asserted"),
            "asserted-runtime": sum(1 for item in records if item["sourceTrust"] == "asserted-runtime"),
            "runtime-observed": sum(1 for item in records if item["sourceTrust"] == "runtime-observed"),
        },
        "accuracy": accuracy,
    }
