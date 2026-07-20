"""Optional official-SDK stdio MCP transport for the daily ProjectClient API."""

from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from typing import Any, Callable

from .application import ProjectClient
from .project import ProjectError


TOOL_NAMES = (
    "hellodev_open",
    "hellodev_next",
    "hellodev_resume",
    "hellodev_status",
    "hellodev_context",
    "hellodev_do",
)
REQUEST_BYTE_LIMIT = 64 * 1024
RESULT_BYTE_LIMIT = 256 * 1024
CONTEXT_RESULT_BYTE_LIMIT = 48 * 1024
INSTALL_HINT = 'Install MCP support with: pipx install "hellodev-core[mcp]"'
_TOOL_ARGUMENTS: dict[str, frozenset[str]] = {
    "hellodev_open": frozenset(),
    "hellodev_next": frozenset(),
    "hellodev_resume": frozenset({"include_context", "token_budget"}),
    "hellodev_status": frozenset(),
    "hellodev_context": frozenset(
        {"intent", "level", "task", "allow_l2", "token_budget", "resume_context"}
    ),
    "hellodev_do": frozenset({"intent", "arguments"}),
}


def sdk_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def _bounded_json(value: Any, limit: int, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProjectError(f"{label} must be JSON serializable") from error
    if len(encoded) > limit:
        raise ProjectError(f"{label} exceeds {limit} bytes")
    return value


class Gateway:
    """Dependency-free bounded tool registry used by the optional SDK transport."""

    def __init__(self, root: str | Path) -> None:
        self.client = ProjectClient(root)
        self._mutation_lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self.client.root

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if tool not in TOOL_NAMES:
            raise ProjectError(f"unknown HelloDev MCP tool: {tool}")
        payload = dict(arguments or {})
        _bounded_json(payload, REQUEST_BYTE_LIMIT, "MCP request")
        unknown = set(payload) - _TOOL_ARGUMENTS[tool]
        if unknown:
            raise ProjectError(f"unsupported {tool} argument(s): {', '.join(sorted(unknown))}")
        if tool == "hellodev_resume":
            if "include_context" in payload and type(payload["include_context"]) is not bool:
                raise ProjectError("include_context must be a boolean")
            budget = payload.get("token_budget", 256)
            if type(budget) is not int or not 32 <= budget <= 4096:
                raise ProjectError("resume token budget must be between 32 and 4096")
        if tool == "hellodev_context":
            for name in ("allow_l2", "resume_context"):
                if name in payload and type(payload[name]) is not bool:
                    raise ProjectError(f"{name} must be a boolean")
        if tool == "hellodev_do" and payload.get("arguments") is not None and not isinstance(
            payload["arguments"], dict
        ):
            raise ProjectError("hellodev_do arguments must be an object")
        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "hellodev_open": lambda: self.client.open(),
            "hellodev_next": self.client.next,
            "hellodev_resume": lambda: self.client.resume(
                include_context=payload.pop("include_context", False),
                token_budget=payload.pop("token_budget", 256),
            ),
            "hellodev_status": self.client.status,
            "hellodev_context": lambda: self.client.context(
                intent=payload.pop("intent", None),
                level=payload.pop("level", None),
                task=payload.pop("task", None),
                allow_l2=payload.pop("allow_l2", False),
                token_budget=payload.pop("token_budget", 1_200),
                resume_context=payload.pop("resume_context", False),
                preview=True,
            ),
            "hellodev_do": lambda: self.client.do(payload.pop("intent", ""), payload.pop("arguments", None)),
        }
        lock = self._mutation_lock if tool in {"hellodev_open", "hellodev_do"} else _NullLock()
        with lock:
            value = handlers[tool]()
        if payload:
            raise ProjectError(f"unconsumed {tool} argument(s): {', '.join(sorted(payload))}")
        return _bounded_json(
            value,
            CONTEXT_RESULT_BYTE_LIMIT if tool == "hellodev_context" else RESULT_BYTE_LIMIT,
            "MCP result",
        )


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


def create_server(root: str | Path) -> Any:
    """Create an official FastMCP server without importing the SDK in base Core."""
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as error:
        raise ProjectError(INSTALL_HINT) from error

    gateway = Gateway(root)
    server = FastMCP(
        "HelloDev",
        instructions=(
            "Root-bound HelloDev gateway. Use open -> next -> do. Approval tokens are exact, one-time action "
            "bindings; a host must obtain explicit user confirmation before resubmitting one. MCP annotations "
            "do not prove human consent. Memory never authorizes tools."
        ),
        json_response=True,
    )

    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    local_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    mixed_write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

    @server.tool(name="hellodev_open", annotations=local_write, structured_output=True)
    def hellodev_open() -> dict[str, Any]:
        """Initialize or resume the bound project's daily workflow."""
        return gateway.call("hellodev_open")

    @server.tool(name="hellodev_next", annotations=read_only, structured_output=True)
    def hellodev_next() -> dict[str, Any]:
        """Return exactly one read-only next command."""
        return gateway.call("hellodev_next")

    @server.tool(name="hellodev_resume", annotations=read_only, structured_output=True)
    def hellodev_resume(include_context: bool = False, token_budget: int = 256) -> dict[str, Any]:
        """Return bounded cross-session recovery state."""
        return gateway.call(
            "hellodev_resume",
            {"include_context": include_context, "token_budget": token_budget},
        )

    @server.tool(name="hellodev_status", annotations=read_only, structured_output=True)
    def hellodev_status() -> dict[str, Any]:
        """Return compact project-local status."""
        return gateway.call("hellodev_status")

    @server.tool(name="hellodev_context", annotations=read_only, structured_output=True)
    def hellodev_context(
        intent: str | None = None,
        level: str | None = None,
        task: str | None = None,
        allow_l2: bool = False,
        token_budget: int = 1_200,
        resume_context: bool = False,
    ) -> dict[str, Any]:
        """Preview a bounded, non-persistent context pack from the bound project."""
        return gateway.call(
            "hellodev_context",
            {
                "intent": intent,
                "level": level,
                "task": task,
                "allow_l2": allow_l2,
                "token_budget": token_budget,
                "resume_context": resume_context,
            },
        )

    @server.tool(name="hellodev_do", annotations=mixed_write, structured_output=True)
    def hellodev_do(intent: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one allowlisted daily intent; exact approvals remain mandatory."""
        return gateway.call("hellodev_do", {"intent": intent, "arguments": arguments})

    # FastMCP 1.28 defaults function argument models to ``extra=ignore``.  The
    # gateway is a security boundary, so advertise and enforce closed schemas.
    for registered in server._tool_manager._tools.values():
        registered.parameters["additionalProperties"] = False
        registered.fn_metadata.arg_model.model_config["extra"] = "forbid"
        registered.fn_metadata.arg_model.model_rebuild(force=True)

    return server


def serve(root: str | Path) -> None:
    """Run the root-bound official MCP server over stdio."""
    create_server(root).run(transport="stdio")


__all__ = ["Gateway", "INSTALL_HINT", "TOOL_NAMES", "create_server", "sdk_available", "serve"]
