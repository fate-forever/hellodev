"""Read-only Codex/Cursor/Antigravity MCP integration rendering and validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from . import components, repository_tools
from .mcp_gateway import INSTALL_HINT, TOOL_NAMES, create_server, sdk_available
from .project import ProjectError, resolve_root


Host = Literal["antigravity", "codex", "cursor"]


def _launch(root: Path) -> tuple[str, list[str], str]:
    # A PATH lookup can select an older global HelloDev than the process that
    # rendered and checked this snippet.  The current interpreter is exact for
    # pipx/venv installs and keeps rendering aligned with the checked package.
    return sys.executable, ["-X", "utf8", "-B", "-I", "-m", "hellodev", "mcp", "serve", "--root", str(root)], "current-python-module"


def _codex_snippet(root: Path, command: str, arguments: list[str]) -> str:
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    args = ", ".join(quote(value) for value in arguments)
    tools = ",\n  ".join(quote(value) for value in TOOL_NAMES)
    return (
        "[mcp_servers.hellodev]\n"
        f"command = {quote(command)}\n"
        f"args = [{args}]\n"
        f"cwd = {quote(str(root))}\n"
        "required = true\n"
        "startup_timeout_sec = 10\n"
        "tool_timeout_sec = 120\n"
        f"enabled_tools = [\n  {tools},\n]\n"
        "default_tools_approval_mode = \"writes\"\n\n"
        "[mcp_servers.hellodev.tools.hellodev_do]\n"
        "approval_mode = \"prompt\"\n"
    )


def _cursor_snippet(command: str, arguments: list[str]) -> str:
    return json.dumps(
        {"mcpServers": {"hellodev": {"command": command, "args": arguments}}},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def _antigravity_snippet(root: Path, command: str, arguments: list[str]) -> str:
    return json.dumps(
        {"mcpServers": {"hellodev": {"command": command, "args": arguments, "cwd": str(root)}}},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def show(root: str | Path, host: Host | str) -> dict[str, Any]:
    selected = resolve_root(root)
    if host not in {"antigravity", "codex", "cursor"}:
        raise ProjectError("integration host must be antigravity, codex, or cursor")
    command, arguments, source = _launch(selected)
    if host == "codex":
        snippet = _codex_snippet(selected, command, arguments)
    elif host == "antigravity":
        snippet = _antigravity_snippet(selected, command, arguments)
    else:
        snippet = _cursor_snippet(command, arguments)
    suggested_path = {
        "antigravity": ".agents/mcp_config.json",
        "codex": ".codex/config.toml",
        "cursor": ".cursor/mcp.json",
    }[host]
    repository_discovery = repository_tools.discover()
    return {
        "schemaVersion": 1,
        "host": host,
        "root": str(selected),
        "scope": "project",
        "suggestedPath": suggested_path,
        "format": "toml" if host == "codex" else "json",
        "launchSource": source,
        "command": command,
        "arguments": arguments,
        "tools": list(TOOL_NAMES),
        "contextPlane": {
            "state": "ready",
            "backend": "native",
            "requiredExternalRuntime": False,
        },
        "repositoryTools": repository_tools.registration(host),
        "semanticContext": repository_discovery["semanticContext"],
        "snippet": snippet,
        "writePerformed": False,
        "warning": (
            "Review the snippet before saving it. hellodev_do remains write-capable; a host prompt is not "
            "provider-attested proof of consent, and exact HelloDev approval tokens still apply."
        ),
    }


def check(root: str | Path, host: Host | str) -> dict[str, Any]:
    rendered = show(root, host)
    distribution = components.status()
    repository_tool = rendered["repositoryTools"]
    semantic_context = rendered["semanticContext"]
    checks: list[dict[str, str]] = [
        {"name": "project-root", "state": "ok", "detail": rendered["root"]},
        {
            "name": "unified-components",
            "state": (
                "ok"
                if distribution["state"] == "ready"
                else "optional"
                if distribution["state"] == "unbundled"
                else "incompatible"
            ),
            "detail": distribution.get("reason", distribution["state"]),
        },
        {
            "name": "launch-command",
            "state": "ok" if Path(rendered["command"]).is_file() else "unavailable",
            "detail": rendered["launchSource"],
        },
        {
            "name": "official-mcp-sdk",
            "state": "ok" if sdk_available() else "install-required",
            "detail": "official SDK importable" if sdk_available() else INSTALL_HINT,
        },
        {
            "name": "project-config",
            "state": "not-inspected",
            "detail": "global and project host configuration were not read or modified",
        },
        {
            "name": "context-plane",
            "state": "ok",
            "detail": "native repository context is included in HelloDev; FastCtx is not required",
        },
        {
            "name": "repository-tool-provider",
            "state": "optional" if repository_tool["state"] == "unavailable" else "ok",
            "detail": (
                "native provider remains active"
                if repository_tool["state"] == "unavailable"
                else "FastCtx command discovered; optional project-scoped MCP snippet is available"
            ),
        },
        {
            "name": "semantic-context-provider",
            "state": "ok",
            "detail": (
                "native Python AST retrieval is active; Serena was discovered but its MCP connection was not inspected"
                if semantic_context["externalProviderState"] == "available-not-connected"
                else "native Python AST retrieval is active; Serena is optional and unavailable"
            ),
        },
    ]
    if sdk_available():
        try:
            create_server(rendered["root"])
        except (ProjectError, TypeError, ValueError) as error:
            checks.append({"name": "server-construction", "state": "incompatible", "detail": str(error)})
        else:
            checks.append(
                {
                    "name": "server-construction",
                    "state": "ok",
                    "detail": f"official SDK registered {len(TOOL_NAMES)} bounded tools",
                }
            )
    state = "ready" if all(item["state"] in {"ok", "not-inspected", "optional"} for item in checks) else "action-required"
    return {
        "schemaVersion": 1,
        "state": state,
        "host": host,
        "root": rendered["root"],
        "checks": checks,
        "tools": rendered["tools"],
        "contextPlane": rendered["contextPlane"],
        "repositoryTools": repository_tool,
        "semanticContext": semantic_context,
        "next": None if state == "ready" else INSTALL_HINT,
        "writePerformed": False,
    }


__all__ = ["Host", "check", "show"]
