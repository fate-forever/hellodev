"""Provider-neutral metadata for bounded Agent/MCP results."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from typing import Any

from .project import ProjectError


RESULT_META_KEY = "_hellodevResult"


def _measure(text: str) -> tuple[int, str]:
    """Return exact o200k tokens when available, otherwise a safe byte ceiling."""
    if importlib.util.find_spec("tiktoken") is not None:
        try:
            import tiktoken  # type: ignore[import-not-found]

            return len(tiktoken.get_encoding("o200k_base").encode(text)), "exact-o200k-base"
        except (ImportError, KeyError, RuntimeError, ValueError):
            pass
    return len(text.encode("utf-8")), "conservative-utf8-byte-ceiling"


def annotate(
    value: dict[str, Any],
    *,
    byte_limit: int,
    token_budget: int | None = None,
    budget_scope: str | None = None,
    continuation: dict[str, Any] | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    """Attach hash/size/token/continuation metadata without truncating JSON."""
    if RESULT_META_KEY in value:
        raise ProjectError(f"MCP result reserves {RESULT_META_KEY}")
    if type(byte_limit) is not int or byte_limit <= 0:
        raise ProjectError("MCP result byte limit must be a positive integer")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_bytes = payload.encode("utf-8")
    payload_tokens, measurement = _measure(payload)
    result = dict(value)
    result[RESULT_META_KEY] = {
        "schemaVersion": 1,
        "state": "partial" if partial else "complete",
        "provider": "hellodev-native",
        "payloadBytes": len(payload_bytes),
        "payloadSha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payloadTokens": payload_tokens,
        "tokenMeasurement": measurement,
        "tokenBudget": token_budget,
        "budgetScope": budget_scope,
        "continuation": continuation,
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > byte_limit:
        raise ProjectError(f"MCP result exceeds {byte_limit} bytes")
    return result


__all__ = ["RESULT_META_KEY", "annotate"]
