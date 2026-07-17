"""Standalone delegation audit and source-labelled usage receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json
from .state_lock import locked_state


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


def _usage_store(root: Path) -> dict[str, Any]:
    load_config(root)
    path = ProjectPaths(root).usage_file
    if not path.exists():
        return {"schemaVersion": 1, "records": []}
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev usage store")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev usage store: {error}") from error
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "records"}:
        raise ProjectError("invalid HelloDev usage store schema")
    if value.get("schemaVersion") != 1 or not isinstance(value.get("records"), list):
        raise ProjectError("invalid HelloDev usage store schema")
    for record in value["records"]:
        _validate_usage_record(record)
    identifiers = [record["id"] for record in value["records"]]
    if len(identifiers) != len(set(identifiers)):
        raise ProjectError("duplicate HelloDev usage record id")
    return value


def _validate_usage_record(record: Any) -> dict[str, Any]:
    fields = {
        "id",
        "recordedAt",
        "totalTokens",
        "subagentTokens",
        "subagentCount",
        "source",
        "scope",
        "accuracy",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise ProjectError("invalid HelloDev usage record fields")
    identifier = record.get("id")
    if not isinstance(identifier, str) or not identifier.startswith("usage-") or not identifier[6:].isdigit():
        raise ProjectError("invalid HelloDev usage record id")
    counts = (record.get("totalTokens"), record.get("subagentTokens"), record.get("subagentCount"))
    if any(type(value) is not int or value < 0 for value in counts) or counts[1] > counts[0]:
        raise ProjectError("invalid HelloDev usage counts")
    if not _nonblank(record.get("recordedAt")) or not _nonblank(record.get("source")) or not _nonblank(record.get("scope")):
        raise ProjectError("invalid HelloDev usage record labels")
    if record.get("accuracy") != "reported":
        raise ProjectError("invalid HelloDev usage accuracy")
    return record


def list_usage_records(root: Path) -> list[dict[str, Any]]:
    return list(_usage_store(root)["records"])


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
        "sourceKind": "operator-report",
        "sourceTrust": "asserted",
        "accuracy": "externally-reported; not host-verified",
        "sourceSha256": hashlib.sha256(record["source"].encode("utf-8")).hexdigest(),
        "scopeSha256": hashlib.sha256(record["scope"].encode("utf-8")).hexdigest(),
    }


def record_usage(root: Path, total: int, subagent: int, subagents: int, source: str, scope: str) -> dict[str, Any]:
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (total, subagent, subagents)) or subagent > total:
        raise ProjectError("usage counts must be non-negative integers and subagent tokens cannot exceed total")
    if not _nonblank(source) or not _nonblank(scope):
        raise ProjectError("usage source and scope are required")
    if len(source) > 128 or len(scope) > 256 or "\n" in source or "\r" in source or "\n" in scope or "\r" in scope:
        raise ProjectError("usage source and scope must be bounded single-line labels")
    with locked_state(root, "usage"):
        store = _usage_store(root)
        if len(store["records"]) >= 100_000:
            raise ProjectError("HelloDev usage store record limit reached")
        highest = max((int(item["id"].removeprefix("usage-")) for item in store["records"]), default=0)
        record = {"id": f"usage-{highest + 1:04d}", "recordedAt": utc_now(), "totalTokens": total, "subagentTokens": subagent, "subagentCount": subagents, "source": source, "scope": scope, "accuracy": "reported"}
        _validate_usage_record(record)
        store["records"].append(record)
        write_json(ProjectPaths(root).usage_file, store)
    return record


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
            "accuracy": "unavailable; no externally reported usage",
        }
    total = sum(item.get("totalTokens", 0) for item in records)
    subagent = sum(item.get("subagentTokens", 0) for item in records)
    return {
        "state": "reported",
        "records": len(records),
        "totalTokens": total,
        "subagentTokens": subagent,
        "rootTokens": total - subagent,
        "latest": usage_projection(records[-1]),
        "accuracy": "reported-only; externally reported; no Codex runtime transcript is read",
    }
