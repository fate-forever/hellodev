"""Deterministic twenty-turn token reflection cycles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import governance
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
WINDOW_SIZE = 20
MAX_CYCLES = 5_000
RECOMMENDATION_CODES = {
    "reduce-subagent-overhead",
    "increase-context-reuse",
    "prefer-bounded-context",
    "keep-current-efficiency-policy",
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _cycle_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in (
        "schemaVersion",
        "id",
        "windowNumber",
        "windowSha256",
        "receiptCount",
        "firstCompletedAt",
        "lastCompletedAt",
        "metrics",
        "signals",
        "recommendation",
        "policyEffect",
        "createdAt",
        "executionPerformed",
        "persistencePerformed",
        "adapterCalls",
        "modelCalls",
    )}


def _validate_cycle(record: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "id", "windowNumber", "windowSha256", "receiptCount",
        "firstCompletedAt", "lastCompletedAt", "metrics", "signals", "recommendation",
        "policyEffect", "createdAt", "cycleSha256", "executionPerformed",
        "persistencePerformed", "adapterCalls", "modelCalls",
    }
    if not isinstance(record, dict) or set(record) != fields or record.get("schemaVersion") != SCHEMA_VERSION:
        raise ProjectError("invalid ReflectionCycle fields")
    number = record.get("windowNumber")
    if type(number) is not int or number < 1 or record.get("id") != f"reflection-cycle-{number:04d}":
        raise ProjectError("invalid ReflectionCycle id")
    if record.get("receiptCount") != WINDOW_SIZE or not _valid_digest(record.get("windowSha256")):
        raise ProjectError("invalid ReflectionCycle window")
    if not all(isinstance(record.get(field), str) and record[field] for field in ("firstCompletedAt", "lastCompletedAt", "createdAt")):
        raise ProjectError("invalid ReflectionCycle timestamps")
    if not _valid_digest(record.get("cycleSha256")) or record["cycleSha256"] != _digest(_cycle_payload(record)):
        raise ProjectError("ReflectionCycle digest mismatch")
    metrics = record.get("metrics")
    metric_fields = {
        "totalTokens", "rootTokens", "subagentTokens", "subagentCount", "inputTokens",
        "cachedInputTokens", "outputTokens", "reasoningOutputTokens", "averageTokens",
        "cacheShareBasisPoints", "subagentShareBasisPoints",
    }
    if not isinstance(metrics, dict) or set(metrics) != metric_fields:
        raise ProjectError("invalid ReflectionCycle metrics")
    if any(type(value) is not int or value < 0 for value in metrics.values()):
        raise ProjectError("invalid ReflectionCycle metric value")
    if metrics["rootTokens"] + metrics["subagentTokens"] != metrics["totalTokens"]:
        raise ProjectError("invalid ReflectionCycle token components")
    if metrics["inputTokens"] + metrics["outputTokens"] != metrics["totalTokens"]:
        raise ProjectError("invalid ReflectionCycle token breakdown")
    if metrics["cachedInputTokens"] > metrics["inputTokens"] or metrics["reasoningOutputTokens"] > metrics["outputTokens"]:
        raise ProjectError("invalid ReflectionCycle subset metrics")
    if not 0 <= metrics["cacheShareBasisPoints"] <= 10_000 or not 0 <= metrics["subagentShareBasisPoints"] <= 10_000:
        raise ProjectError("invalid ReflectionCycle share metrics")
    expected_average = metrics["totalTokens"] // WINDOW_SIZE
    expected_cache_share = metrics["cachedInputTokens"] * 10_000 // metrics["inputTokens"] if metrics["inputTokens"] else 0
    expected_subagent_share = metrics["subagentTokens"] * 10_000 // metrics["totalTokens"] if metrics["totalTokens"] else 0
    if (
        metrics["averageTokens"] != expected_average
        or metrics["cacheShareBasisPoints"] != expected_cache_share
        or metrics["subagentShareBasisPoints"] != expected_subagent_share
    ):
        raise ProjectError("invalid ReflectionCycle derived metrics")
    signals = record.get("signals")
    if not isinstance(signals, list) or not signals or len(signals) != len(set(signals)) or not all(isinstance(item, str) for item in signals):
        raise ProjectError("invalid ReflectionCycle signals")
    recommendation = record.get("recommendation")
    if not isinstance(recommendation, dict) or set(recommendation) != {"code", "command", "reasonCode"}:
        raise ProjectError("invalid ReflectionCycle recommendation")
    if recommendation["code"] not in RECOMMENDATION_CODES or not all(isinstance(recommendation[key], str) and recommendation[key] for key in recommendation):
        raise ProjectError("invalid ReflectionCycle recommendation")
    expected_signals, expected_recommendation = _advice(metrics)
    if signals != expected_signals or recommendation != expected_recommendation:
        raise ProjectError("ReflectionCycle advice does not match deterministic metrics")
    policy = record.get("policyEffect")
    if policy != {"applyAllowed": False, "requiresHumanReview": True, "tightenOnly": True}:
        raise ProjectError("invalid ReflectionCycle policy boundary")
    if record.get("executionPerformed") is not False or record.get("persistencePerformed") is not True:
        raise ProjectError("invalid ReflectionCycle execution boundary")
    if record.get("adapterCalls") != [] or record.get("modelCalls") != []:
        raise ProjectError("ReflectionCycle cannot call adapters or models")
    return record


def _store(root: Path) -> dict[str, Any]:
    load_config(root)
    path = ProjectPaths(root).reflection_cycles_file
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "windowSize": WINDOW_SIZE, "cycles": []}
    if path.is_symlink():
        raise ProjectError("refusing symlinked ReflectionCycle store")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid ReflectionCycle store: {error}") from error
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "windowSize", "cycles"}:
        raise ProjectError("invalid ReflectionCycle store schema")
    if value.get("schemaVersion") != SCHEMA_VERSION or value.get("windowSize") != WINDOW_SIZE or not isinstance(value.get("cycles"), list):
        raise ProjectError("invalid ReflectionCycle store schema")
    cycles = [_validate_cycle(item) for item in value["cycles"]]
    if len(cycles) > MAX_CYCLES or [item["windowNumber"] for item in cycles] != list(range(1, len(cycles) + 1)):
        raise ProjectError("invalid ReflectionCycle ordering")
    return {"schemaVersion": SCHEMA_VERSION, "windowSize": WINDOW_SIZE, "cycles": cycles}


def _metrics(receipts: list[dict[str, Any]]) -> dict[str, int]:
    total = sum(item["totalTokens"] for item in receipts)
    root = sum(item["totalTokens"] - item["subagentTokens"] for item in receipts)
    subagent = sum(item["subagentTokens"] for item in receipts)
    input_tokens = sum(item["inputTokens"] for item in receipts)
    cached = sum(item["cachedInputTokens"] for item in receipts)
    output = sum(item["outputTokens"] for item in receipts)
    reasoning = sum(item["reasoningOutputTokens"] for item in receipts)
    return {
        "totalTokens": total,
        "rootTokens": root,
        "subagentTokens": subagent,
        "subagentCount": sum(item["subagentCount"] for item in receipts),
        "inputTokens": input_tokens,
        "cachedInputTokens": cached,
        "outputTokens": output,
        "reasoningOutputTokens": reasoning,
        "averageTokens": total // WINDOW_SIZE,
        "cacheShareBasisPoints": cached * 10_000 // input_tokens if input_tokens else 0,
        "subagentShareBasisPoints": subagent * 10_000 // total if total else 0,
    }


def _advice(metrics: dict[str, int]) -> tuple[list[str], dict[str, str]]:
    signals: list[str] = []
    if metrics["subagentTokens"] > 0 and metrics["subagentShareBasisPoints"] >= 3_500:
        signals.append("subagent-share-high")
    if metrics["inputTokens"] > 0 and metrics["cacheShareBasisPoints"] < 5_000:
        signals.append("context-reuse-low")
    if metrics["averageTokens"] > 100_000:
        signals.append("average-turn-cost-high")
    if not signals:
        signals.append("efficiency-within-bounds")
    if "subagent-share-high" in signals:
        recommendation = {
            "code": "reduce-subagent-overhead",
            "command": "hellodev optimize plan --intent code --max-subagents 0",
            "reasonCode": "twenty-turn-subagent-share-high",
        }
    elif "context-reuse-low" in signals:
        recommendation = {
            "code": "increase-context-reuse",
            "command": "hellodev context pack --intent code --token-budget 1200",
            "reasonCode": "twenty-turn-cache-share-low",
        }
    elif "average-turn-cost-high" in signals:
        recommendation = {
            "code": "prefer-bounded-context",
            "command": "hellodev context suggest --intent code",
            "reasonCode": "twenty-turn-average-cost-high",
        }
    else:
        recommendation = {
            "code": "keep-current-efficiency-policy",
            "command": "hellodev optimize status",
            "reasonCode": "twenty-turn-efficiency-within-bounds",
        }
    return signals, recommendation


def _build_cycle(window: list[dict[str, Any]], number: int) -> dict[str, Any]:
    metrics = _metrics(window)
    signals, recommendation = _advice(metrics)
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "id": f"reflection-cycle-{number:04d}",
        "windowNumber": number,
        "windowSha256": _digest([item["receiptSha256"] for item in window]),
        "receiptCount": WINDOW_SIZE,
        "firstCompletedAt": window[0]["completedAt"],
        "lastCompletedAt": window[-1]["completedAt"],
        "metrics": metrics,
        "signals": signals,
        "recommendation": recommendation,
        "policyEffect": {"applyAllowed": False, "requiresHumanReview": True, "tightenOnly": True},
        "createdAt": utc_now(),
        "executionPerformed": False,
        "persistencePerformed": True,
        "adapterCalls": [],
        "modelCalls": [],
        "cycleSha256": "",
    }
    record["cycleSha256"] = _digest(_cycle_payload(record))
    return _validate_cycle(record)


def reconcile(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    receipts = [
        item for item in governance.list_runtime_usage_records(resolved)
        if item["sourceTrust"] == "runtime-observed" and item["measurement"] == "exact"
    ]
    with locked_state(resolved, "reflection-cycles"):
        store = _store(resolved)
        complete_windows = len(receipts) // WINDOW_SIZE
        if complete_windows > MAX_CYCLES:
            raise ProjectError("ReflectionCycle store limit reached")
        for index, existing in enumerate(store["cycles"]):
            window = receipts[index * WINDOW_SIZE : (index + 1) * WINDOW_SIZE]
            if len(window) != WINDOW_SIZE or existing["windowSha256"] != _digest([item["receiptSha256"] for item in window]):
                raise ProjectError("ReflectionCycle receipt history changed")
        created: list[dict[str, Any]] = []
        for index in range(len(store["cycles"]), complete_windows):
            window = receipts[index * WINDOW_SIZE : (index + 1) * WINDOW_SIZE]
            cycle = _build_cycle(window, index + 1)
            store["cycles"].append(cycle)
            created.append(cycle)
        if created:
            write_json(ProjectPaths(resolved).reflection_cycles_file, store)
    return {**status(resolved), "createdCycles": len(created), "persistencePerformed": bool(created)}


def status(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    store = _store(resolved)
    observed = sum(
        1 for item in governance.list_runtime_usage_records(resolved)
        if item["sourceTrust"] == "runtime-observed" and item["measurement"] == "exact"
    )
    consumed = len(store["cycles"]) * WINDOW_SIZE
    pending = max(0, observed - consumed)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "ready" if store["cycles"] else "pending",
        "windowSize": WINDOW_SIZE,
        "observedReceiptCount": observed,
        "cycleCount": len(store["cycles"]),
        "pendingReceiptCount": pending,
        "remainingUntilNextCycle": WINDOW_SIZE - pending if pending else WINDOW_SIZE,
        "latest": store["cycles"][-1] if store["cycles"] else None,
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def next_hint(root: str | Path) -> dict[str, Any] | None:
    value = status(root)
    latest = value["latest"]
    if latest is None:
        return None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "cycle-ready",
        "reasonCode": latest["recommendation"]["reasonCode"],
        "trend": {
            "sampleSize": latest["receiptCount"],
            "averageTokens": latest["metrics"]["averageTokens"],
            "cacheShareBasisPoints": latest["metrics"]["cacheShareBasisPoints"],
            "subagentShareBasisPoints": latest["metrics"]["subagentShareBasisPoints"],
        },
        "signal": {"codes": latest["signals"], "cycleId": latest["id"]},
        "suggestion": latest["recommendation"],
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }
