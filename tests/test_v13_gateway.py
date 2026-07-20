from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev.application import ProjectClient
from hellodev.cli import main
from hellodev.integrations import check, show
from hellodev.mcp_gateway import Gateway, INSTALL_HINT, TOOL_NAMES, sdk_available
from hellodev.project import ProjectError, ProjectPaths
from scripts.verify_release_version import verify as verify_release_version


def run_cli(*args: str) -> dict:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    if code:
        raise AssertionError(f"CLI failed with {code}: {stderr.getvalue()}")
    return json.loads(stdout.getvalue())


def state_snapshot(root: Path) -> dict[str, bytes]:
    state = ProjectPaths(root).state_dir
    return {
        path.relative_to(state).as_posix(): path.read_bytes()
        for path in state.rglob("*")
        if path.is_file()
    }


class V13GatewayTests(unittest.TestCase):
    def test_project_client_matches_cli_daily_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            opened = client.open()
            self.assertEqual(opened["next"]["command"], "hellodev do plan")
            self.assertEqual(client.next(), run_cli("--root", str(root), "next"))
            self.assertEqual(client.status(), run_cli("--root", str(root), "status"))
            self.assertEqual(client.resume(), run_cli("--root", str(root), "resume"))
            planned = client.do("plan")
            self.assertEqual(planned["lifecycle"]["phase"], "planned")

    def test_project_client_rejects_unknown_or_cross_intent_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = ProjectClient(directory)
            client.open()
            with self.assertRaisesRegex(ProjectError, "unknown HelloDev daily intent"):
                client.do("shell", {})
            with self.assertRaisesRegex(ProjectError, "unsupported plan argument"):
                client.do("plan", {"approve": "not-allowed"})
            with self.assertRaisesRegex(ProjectError, "recall requires"):
                client.do("recall", {})
            with self.assertRaisesRegex(ProjectError, "query must be a string"):
                client.do("recall", {"query": {"nested": "forbidden"}})
            with self.assertRaisesRegex(ProjectError, "limit must be an integer"):
                client.do("recall", {"query": "bounded", "limit": True})
            with self.assertRaisesRegex(ProjectError, "timeout must be"):
                client.do("task", {"operation": "list", "timeout": 0})

    def test_gateway_is_root_bound_and_read_tools_do_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as sibling:
            root = Path(directory)
            gateway = Gateway(root)
            self.assertEqual(tuple(TOOL_NAMES), tuple(TOOL_NAMES))
            gateway.call("hellodev_open")
            before = state_snapshot(root)
            for name, arguments in (
                ("hellodev_next", {}),
                ("hellodev_status", {}),
                ("hellodev_resume", {"include_context": False, "token_budget": 256}),
                ("hellodev_context", {"intent": "status", "token_budget": 256}),
            ):
                value = gateway.call(name, arguments)
                self.assertIsInstance(value, dict)
            self.assertEqual(before, state_snapshot(root))
            self.assertFalse((Path(sibling) / ".hellodev").exists())
            with self.assertRaisesRegex(ProjectError, "unsupported hellodev_status argument"):
                gateway.call("hellodev_status", {"root": sibling})

    def test_integrations_render_without_reading_or_writing_host_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with tempfile.TemporaryDirectory() as obsolete:
                (Path(obsolete) / "hellodev.cmd").write_text("@echo old", encoding="utf-8")
                with patch.dict(os.environ, {"PATH": obsolete}, clear=False):
                    codex = show(root, "codex")
            cursor = show(root, "cursor")
            self.assertIn("[mcp_servers.hellodev]", codex["snippet"])
            self.assertIn('"mcpServers"', cursor["snippet"])
            self.assertEqual(codex["tools"], list(TOOL_NAMES))
            self.assertEqual(Path(codex["command"]).resolve(), Path(sys.executable).resolve())
            self.assertEqual(codex["launchSource"], "current-python-module")
            self.assertFalse(codex["writePerformed"])
            self.assertFalse(cursor["writePerformed"])
            with patch("hellodev.integrations.sdk_available", return_value=False):
                checked = check(root, "codex")
            self.assertEqual(checked["state"], "action-required")
            self.assertFalse(checked["writePerformed"])
            self.assertFalse((root / ".codex").exists())
            self.assertFalse((root / ".cursor").exists())

    def test_progressive_help_hides_advanced_families_until_requested(self) -> None:
        daily = io.StringIO()
        with contextlib.redirect_stdout(daily), self.assertRaises(SystemExit):
            main(["--help"])
        text = daily.getvalue()
        self.assertIn("{open,next,do,status,resume,setup,onboard,components,integrate,doctor}", text)
        self.assertNotIn("policy             stage", text)
        complete = io.StringIO()
        with contextlib.redirect_stdout(complete):
            code = main(["--help-all"])
        self.assertEqual(code, 0)
        self.assertIn("policy", complete.getvalue())
        self.assertIn("mcp", complete.getvalue())

    def test_optional_dependency_and_release_workflow_are_bounded(self) -> None:
        pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        ci = (PACKAGE_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        publish = (PACKAGE_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
        self.assertIn('version = "0.14.1"', pyproject)
        self.assertIn("dependencies = []", pyproject)
        self.assertIn('mcp = ["mcp==1.28.1"]', pyproject)
        self.assertIn('python -m pip install ".[mcp]"', ci)
        self.assertNotIn("id-token: write", ci)
        self.assertIn("types: [published]", publish)
        self.assertNotIn("workflow_dispatch", publish)
        self.assertIn("environment:\n      name: pypi", publish)
        self.assertEqual(publish.count("id-token: write"), 1)
        self.assertNotIn("PYPI_API_TOKEN", publish)
        self.assertIn("actions/download-artifact", publish)
        self.assertIn("pypa/gh-action-pypi-publish", publish)
        self.assertIn('mcp-smoke/bin/python -m pip install "mcp==1.28.1"', publish)
        self.assertIn("mcp-smoke/bin/python scripts/mcp_smoke.py", publish)
        self.assertTrue((PACKAGE_ROOT / "scripts" / "mcp_smoke.py").is_file())
        self.assertEqual(verify_release_version("v0.14.1")["version"], "0.14.1")
        with self.assertRaisesRegex(ValueError, "release version mismatch"):
            verify_release_version("v0.14.0")

    def test_base_core_does_not_import_or_require_mcp(self) -> None:
        self.assertNotIn("mcp", sys.modules)
        with tempfile.TemporaryDirectory() as directory:
            ProjectClient(directory).open()
            if not sdk_available():
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(["mcp", "serve", "--root", directory])
                self.assertEqual(code, 2)
                self.assertIn(INSTALL_HINT, stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
