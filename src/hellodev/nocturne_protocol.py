"""Hash-only safety state for the hellodev@nocturne component profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .component_protocol import canonical_sha256, operation_id
from .project import ProjectError, ProjectPaths, utc_now, write_json
from .state_lock import locked_state


READ_RECEIPT_TOOLS = {"update_memory", "delete_memory"}
MAX_RECEIPTS = 256
MAX_OPERATIONS = 256


def namespace_for(root: Path) -> str:
    return f"hellodev-{canonical_sha256({'projectRoot': str(root.resolve())})[:24]}"


def _path(root: Path) -> Path:
    return ProjectPaths(root).state_dir / "nocturne-component.json"


def _load(root: Path) -> dict[str, Any]:
    path = _path(root)
    if not path.is_file():
        return {"schemaVersion": 1, "readReceipts": {}, "operations": {}}
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ProjectError("hellodev@nocturne state is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid hellodev@nocturne state: {error}") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ProjectError("unsupported hellodev@nocturne state")
    if not isinstance(value.get("readReceipts"), dict) or not isinstance(value.get("operations"), dict):
        raise ProjectError("invalid hellodev@nocturne state collections")
    return value


def record_read(root: Path, uri: str, content: str) -> dict[str, str]:
    uri_sha = canonical_sha256({"uri": uri})
    version = canonical_sha256({"content": content})
    receipt_id = f"read-{canonical_sha256({'uriSha256': uri_sha, 'version': version})[:32]}"
    with locked_state(root, "nocturne-component"):
        state = _load(root)
        receipts = state["readReceipts"]
        receipts[receipt_id] = {
            "uriSha256": uri_sha,
            "version": version,
            "createdAt": utc_now(),
        }
        if len(receipts) > MAX_RECEIPTS:
            for key in list(receipts)[:-MAX_RECEIPTS]:
                receipts.pop(key, None)
        write_json(_path(root), state)
    return {"readReceipt": receipt_id, "version": version}


def guard_for(root: Path, tool: str, parameters: dict[str, Any]) -> dict[str, str] | None:
    if tool not in READ_RECEIPT_TOOLS:
        return None
    uri = parameters.get("uri")
    if not isinstance(uri, str) or not uri:
        raise ProjectError(f"{tool} requires a URI")
    uri_sha = canonical_sha256({"uri": uri})
    state = _load(root)
    matches = [
        (key, item)
        for key, item in state["readReceipts"].items()
        if isinstance(item, dict) and item.get("uriSha256") == uri_sha and isinstance(item.get("version"), str)
    ]
    if not matches:
        raise ProjectError(f"hellodev@nocturne requires read_memory({uri}) before {tool}")
    receipt_id, receipt = matches[-1]
    return {"readReceipt": receipt_id, "expectedVersion": receipt["version"]}


def mutation_metadata(root: Path, tool: str, parameters: dict[str, Any]) -> dict[str, Any]:
    guard = guard_for(root, tool, parameters)
    namespace = namespace_for(root)
    metadata: dict[str, Any] = {
        "protocolVersion": "hellodev.component/v1",
        "component": "hellodev@nocturne",
        "operationId": operation_id(
            "nocturne", tool, {"parameters": parameters, "guard": guard, "namespace": namespace}
        ),
        "namespace": namespace,
    }
    if guard is not None:
        metadata.update(guard)
    return metadata


def replay(root: Path, op_id: str, request_sha256: str) -> dict[str, Any] | None:
    with locked_state(root, "nocturne-component"):
        item = _load(root)["operations"].get(op_id)
    if not isinstance(item, dict):
        return None
    if item.get("requestSha256") != request_sha256:
        raise ProjectError("hellodev@nocturne operationId was reused for another request")
    return {
        "content": [{"type": "text", "text": "Success: idempotent mutation already committed"}],
        "isError": False,
        "structuredContent": {
            "protocolVersion": "hellodev.component/v1",
            "component": "hellodev@nocturne",
            "operationId": op_id,
            "replayed": True,
            "resultSha256": item.get("resultSha256"),
        },
    }


def record_operation(root: Path, metadata: dict[str, Any], request_sha256: str, result: dict[str, Any]) -> None:
    with locked_state(root, "nocturne-component"):
        state = _load(root)
        operations = state["operations"]
        operations[metadata["operationId"]] = {
            "requestSha256": request_sha256,
            "resultSha256": canonical_sha256(result),
            "createdAt": utc_now(),
        }
        if len(operations) > MAX_OPERATIONS:
            for key in list(operations)[:-MAX_OPERATIONS]:
                operations.pop(key, None)
        write_json(_path(root), state)
