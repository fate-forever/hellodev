"""Smoke the installed HelloDev wheel through the official stdio MCP client."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hellodev import __version__
from hellodev.mcp_gateway import TOOL_NAMES


async def _exercise(root: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-X", "utf8", "-B", "-I", "-m", "hellodev", "mcp", "serve", "--root", str(root)],
        cwd=str(root),
        env=environment,
    )
    called: list[str] = []
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = [tool.name for tool in listed.tools]
            if names != list(TOOL_NAMES):
                raise RuntimeError(f"unexpected MCP tools: {names}")
            for tool in listed.tools:
                if "root" in tool.inputSchema.get("properties", {}):
                    raise RuntimeError(f"MCP tool unexpectedly exposes root: {tool.name}")
                if tool.inputSchema.get("additionalProperties", True):
                    raise RuntimeError(f"MCP tool schema is not closed: {tool.name}")
            for name, arguments in (
                ("hellodev_open", {}),
                ("hellodev_next", {}),
                ("hellodev_status", {}),
                ("hellodev_resume", {"include_context": True, "token_budget": 256}),
                ("hellodev_context", {"intent": "status", "token_budget": 256}),
                ("hellodev_do", {"intent": "plan", "arguments": {}}),
            ):
                result = await session.call_tool(name, arguments)
                if result.isError or not isinstance(result.structuredContent, dict):
                    raise RuntimeError(f"MCP tool failed: {name}")
                called.append(name)
    return {
        "schemaVersion": 1,
        "hellodevVersion": __version__,
        "mcpVersion": version("mcp"),
        "serverName": initialized.serverInfo.name,
        "tools": list(TOOL_NAMES),
        "called": called,
        "succeeded": True,
    }


def main() -> int:
    if __version__ != "0.14.1":
        raise RuntimeError(f"expected installed HelloDev 0.14.1, found {__version__}")
    if version("mcp") != "1.28.1":
        raise RuntimeError(f"expected official MCP SDK 1.28.1, found {version('mcp')}")
    with tempfile.TemporaryDirectory() as directory:
        result = anyio.run(_exercise, Path(directory))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
