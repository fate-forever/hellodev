"""Tiny stdio MCP fixture used by HelloDev adapter tests."""

from __future__ import annotations

import json
import sys


def respond(request_id: int, result: dict) -> None:
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    if request.get("method") == "initialize":
        respond(request["id"], {"protocolVersion": "2025-03-26", "serverInfo": {"name": "fake-nocturne"}})
    elif request.get("method") == "tools/list":
        respond(
            request["id"],
            {"tools": [{"name": "read_memory"}, {"name": "create_memory"}, {"name": "search_memory"}]},
        )
    elif request.get("method") == "tools/call":
        serialized = json.dumps(request["params"], ensure_ascii=False)
        is_error = "force-mcp-error" in serialized
        respond(
            request["id"],
            {
                "content": [{"type": "text", "text": serialized}],
                "isError": is_error,
            },
        )
