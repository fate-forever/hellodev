"""Versioned contracts shared by HelloDev component integrations."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .project import ProjectError


PROTOCOL_VERSION = "hellodev.component/v1"
ENHANCED_COMPONENTS = {
    "trellis": "hellodev@trellis",
    "nocturne": "hellodev@nocturne",
}
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def operation_id(component: str, action: str, parameters: dict[str, Any]) -> str:
    if component not in ENHANCED_COMPONENTS:
        raise ProjectError(f"unsupported component protocol identity: {component}")
    digest = canonical_sha256({"component": component, "action": action, "parameters": parameters})
    return f"hd-{component}-{digest[:32]}"


def validate_operation_id(value: str) -> str:
    if not isinstance(value, str) or OPERATION_ID_PATTERN.fullmatch(value) is None:
        raise ProjectError("component operationId is invalid")
    return value


def handshake(component: str, capabilities: list[str]) -> dict[str, Any]:
    identity = ENHANCED_COMPONENTS.get(component)
    if identity is None:
        raise ProjectError(f"unsupported component protocol identity: {component}")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "component": identity,
        "mode": "enhanced",
        "capabilities": sorted(set(capabilities)),
    }


def result_ok(component: str, action: str, op_id: str, data: Any, *, replayed: bool = False) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "component": ENHANCED_COMPONENTS[component],
        "operationId": validate_operation_id(op_id),
        "action": action,
        "ok": True,
        "replayed": replayed,
        "data": data,
    }


def result_error(component: str, action: str, op_id: str, code: str, message: str) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "component": ENHANCED_COMPONENTS[component],
        "operationId": validate_operation_id(op_id),
        "action": action,
        "ok": False,
        "error": {"code": code, "message": message[:1024]},
    }


def text_error(result: Any) -> str | None:
    """Recognize legacy MCP text errors without pretending they succeeded."""
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        value = item.get("text")
        if isinstance(value, str) and value.lstrip().casefold().startswith("error:"):
            return value.strip()[:1024]
    return None


def content_text(result: Any) -> str:
    if not isinstance(result, dict) or not isinstance(result.get("content"), list):
        raise ProjectError("component result has no MCP content array")
    parts = [
        item["text"]
        for item in result["content"]
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
    ]
    if not parts:
        raise ProjectError("component result has no text content")
    return "\n".join(parts)
