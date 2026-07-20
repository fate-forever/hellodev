from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))


@unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "official MCP SDK extra is not installed")
class V13McpTests(unittest.TestCase):
    def test_official_stdio_initialize_list_and_daily_calls(self) -> None:
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise(root: Path) -> None:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "hellodev", "mcp", "serve", "--root", str(root)],
                cwd=str(PACKAGE_ROOT),
                env=environment,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "HelloDev")
                    listed = await session.list_tools()
                    self.assertEqual(
                        [tool.name for tool in listed.tools],
                        [
                            "hellodev_open",
                            "hellodev_next",
                            "hellodev_resume",
                            "hellodev_status",
                            "hellodev_context",
                            "hellodev_do",
                        ],
                    )
                    for tool in listed.tools:
                        self.assertNotIn("root", tool.inputSchema.get("properties", {}))
                        self.assertFalse(tool.inputSchema.get("additionalProperties", True))
                    do_tool = next(tool for tool in listed.tools if tool.name == "hellodev_do")
                    self.assertFalse(do_tool.annotations.readOnlyHint)
                    self.assertTrue(do_tool.annotations.destructiveHint)
                    opened = await session.call_tool("hellodev_open", {})
                    self.assertFalse(opened.isError)
                    self.assertEqual(opened.structuredContent["next"]["command"], "hellodev do plan")
                    for name, arguments in (
                        ("hellodev_next", {}),
                        ("hellodev_status", {}),
                        ("hellodev_resume", {"include_context": True, "token_budget": 256}),
                        ("hellodev_context", {"intent": "status", "token_budget": 256}),
                    ):
                        result = await session.call_tool(name, arguments)
                        self.assertFalse(result.isError, name)
                        self.assertIsInstance(result.structuredContent, dict)
                    planned = await session.call_tool("hellodev_do", {"intent": "plan", "arguments": {}})
                    self.assertFalse(planned.isError)
                    self.assertEqual(planned.structuredContent["lifecycle"]["phase"], "planned")
                    ignored = await session.call_tool("hellodev_status", {"root": str(root.parent)})
                    self.assertTrue(ignored.isError)
                    self.assertFalse((root.parent / ".hellodev").exists())

        with tempfile.TemporaryDirectory() as directory:
            anyio.run(exercise, Path(directory))


if __name__ == "__main__":
    unittest.main()
