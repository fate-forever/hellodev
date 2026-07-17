"""Independent stdio MCP adapter for Nocturne's public tool interface."""

from __future__ import annotations

import json
import hashlib
import queue
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..approval import consume, prepare
from ..project import ProjectError, nocturne_config


WRITE_TOOLS = {"create_memory", "update_memory", "delete_memory", "add_alias", "manage_triggers"}
TOOL_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_RESPONSE_BYTES = 1024 * 1024


class McpProtocolError(ProjectError):
    """Raised when the configured stdio process is not a usable MCP server."""


class _StdioMcp:
    def __init__(self, configuration: dict[str, Any], timeout_seconds: int) -> None:
        startup_info: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL, "text": True}
        creation_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creation_flag:
            startup_info["creationflags"] = creation_flag
        self._process = subprocess.Popen(
            [configuration["command"], *configuration["args"]],
            cwd=configuration["cwd"],
            **startup_info,
        )
        self._timeout = timeout_seconds
        self._messages: queue.Queue[str | None] = queue.Queue()
        self._counter = 0
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._messages.put(line)
        self._messages.put(None)

    def _send(self, message: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise McpProtocolError("Nocturne MCP stdin is unavailable")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> Any:
        self._counter += 1
        request_id = self._counter
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        ignored_bytes = 0
        while True:
            try:
                raw = self._messages.get(timeout=self._timeout)
            except queue.Empty as error:
                raise McpProtocolError(f"Nocturne MCP timed out while waiting for {method}") from error
            if raw is None:
                raise McpProtocolError("Nocturne MCP closed stdout before replying")
            ignored_bytes += len(raw.encode("utf-8", errors="replace"))
            if ignored_bytes > MAX_RESPONSE_BYTES:
                raise McpProtocolError("Nocturne MCP emitted too much non-response output")
            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise McpProtocolError(f"Nocturne MCP error: {response['error']}")
            if "result" not in response:
                raise McpProtocolError("Nocturne MCP returned a response without result")
            return response["result"]

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)


def _configuration(root: Path) -> dict[str, Any]:
    configuration = nocturne_config(root)
    if configuration is None:
        raise ProjectError(
            "Nocturne is not configured for this project; use 'hellodev nocturne configure' with its independent stdio command"
        )
    return configuration


def _risk_for_tool(tool: str) -> str:
    return "write" if tool in WRITE_TOOLS else "read"


def risk_for_tool(tool: str) -> str:
    _validate_tool(tool)
    return _risk_for_tool(tool)


def _validate_tool(tool: str) -> None:
    if not TOOL_PATTERN.fullmatch(tool):
        raise ProjectError("Nocturne tool name must be lowercase letters, digits, and underscores")


def _payload(configuration: dict[str, Any], action: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter": "nocturne",
        "mode": "stdio",
        "command": configuration["command"],
        "args": configuration["args"],
        "cwd": configuration["cwd"],
        "action": action,
        "parameters": parameters,
        "executionIdentity": _execution_identity(configuration),
    }


def _file_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProjectError(f"Nocturne execution dependency is missing or unsafe: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "size": path.stat().st_size}


def _execution_identity(configuration: dict[str, Any]) -> list[dict[str, Any]]:
    identities = [_file_identity(Path(configuration["command"]))]
    base = Path(configuration["cwd"]) if configuration["cwd"] is not None else None
    for index, argument in enumerate(configuration["args"]):
        candidate = Path(argument)
        if not candidate.is_absolute() and base is not None:
            candidate = base / candidate
        if candidate.is_file() and not candidate.is_symlink():
            identities.append({"argumentIndex": index, **_file_identity(candidate)})
    return identities


def status(root: Path) -> dict[str, Any]:
    configuration = nocturne_config(root) if (root / ".hellodev" / "config.json").is_file() else None
    if configuration is None:
        return {
            "state": "unconfigured",
            "mode": "stdio",
            "reason": "No independent Nocturne stdio command is configured for this project.",
            "execution": "requires-one-time-approval",
        }
    return {
        "state": "configured",
        "mode": "stdio",
        "command": configuration["command"],
        "cwd": configuration["cwd"],
        "execution": "requires-one-time-approval",
        "supportedOperations": ["tools/list", "tools/call"],
    }


def prepare_tools(root: Path) -> dict[str, Any]:
    configuration = _configuration(root)
    payload = _payload(configuration, "tools/list", {})
    return {**prepare(root, payload, "read"), "adapter": "nocturne", "operation": "tools/list"}


def prepare_call(root: Path, tool: str, parameters: dict[str, Any]) -> dict[str, Any]:
    _validate_tool(tool)
    if not isinstance(parameters, dict):
        raise ProjectError("Nocturne tool parameters must be a JSON object")
    configuration = _configuration(root)
    payload = _payload(configuration, "tools/call", {"name": tool, "arguments": parameters})
    return {
        **prepare(root, payload, _risk_for_tool(tool)),
        "adapter": "nocturne",
        "tool": tool,
        "parameterSha256": hashlib.sha256(
            json.dumps(parameters, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _invoke(configuration: dict[str, Any], method: str, parameters: dict[str, Any], timeout_seconds: int) -> Any:
    if not 1 <= timeout_seconds <= 120:
        raise ProjectError("Nocturne timeout must be between 1 and 120 seconds")
    session = _StdioMcp(configuration, timeout_seconds)
    try:
        session.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "hellodev", "version": "0.11.0"},
            },
        )
        session.notify("notifications/initialized", {})
        return session.request(method, parameters)
    finally:
        session.close()


def list_tools(root: Path, approval: str, timeout_seconds: int) -> dict[str, Any]:
    configuration = _configuration(root)
    payload = _payload(configuration, "tools/list", {})
    consume(root, payload, approval, "read")
    return {"adapter": "nocturne", "result": _invoke(configuration, "tools/list", {}, timeout_seconds)}


def call(root: Path, tool: str, parameters: dict[str, Any], approval: str, timeout_seconds: int) -> dict[str, Any]:
    _validate_tool(tool)
    if not isinstance(parameters, dict):
        raise ProjectError("Nocturne tool parameters must be a JSON object")
    configuration = _configuration(root)
    arguments = {"name": tool, "arguments": parameters}
    payload = _payload(configuration, "tools/call", arguments)
    consume(root, payload, approval, _risk_for_tool(tool))
    return {"adapter": "nocturne", "tool": tool, "result": _invoke(configuration, "tools/call", arguments, timeout_seconds)}


def call_succeeded(result: dict[str, Any]) -> bool:
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise McpProtocolError("Nocturne tools/call result must be an object")
    is_error = payload.get("isError", False)
    if not isinstance(is_error, bool):
        raise McpProtocolError("Nocturne tools/call isError must be a boolean when present")
    return not is_error
