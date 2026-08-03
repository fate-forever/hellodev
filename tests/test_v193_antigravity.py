from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import dashboard, integrations, onboarding, repository_tools
from hellodev.application import ProjectClient
from hellodev.cli import main
from hellodev.mcp_gateway import TOOL_NAMES
from hellodev.project import ProjectError


class V193AntigravityTests(unittest.TestCase):
    def test_integration_uses_official_workspace_mcp_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = integrations.show(root, "antigravity")
            payload = json.loads(rendered["snippet"])
            server = payload["mcpServers"]["hellodev"]
            self.assertEqual(rendered["suggestedPath"], ".agents/mcp_config.json")
            self.assertEqual(rendered["format"], "json")
            self.assertEqual(rendered["tools"], list(TOOL_NAMES))
            self.assertEqual(Path(server["command"]).resolve(), Path(sys.executable).resolve())
            self.assertEqual(server["cwd"], str(root.resolve()))
            self.assertEqual(server["args"][-2:], ["--root", str(root.resolve())])
            self.assertIn("hellodev", server["args"])
            self.assertIn("serve", server["args"])
            self.assertFalse(rendered["writePerformed"])

    def test_onboard_merges_workspace_config_and_rule_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / ".agents"
            agents.mkdir()
            config_path = agents / "mcp_config.json"
            config_path.write_text(
                json.dumps({"mcpServers": {"existing": {"command": "existing-tool"}}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                first = onboarding.onboard(root, host="antigravity")
                second = onboarding.onboard(root, host="antigravity")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("existing", config["mcpServers"])
            self.assertIn("hellodev", config["mcpServers"])
            self.assertEqual(first["host"]["host"], "antigravity")
            self.assertTrue(first["host"]["changed"])
            self.assertFalse(second["host"]["changed"])
            self.assertEqual(first["host"]["ruleActivation"], "review-workspace-rule-settings")
            rule = root / ".agents" / "rules" / "hellodev.md"
            self.assertEqual(rule.read_text(encoding="utf-8"), onboarding.ANTIGRAVITY_RULE)
            self.assertFalse((root / ".cursor").exists())
            self.assertFalse((root / ".codex").exists())
            project_config = json.loads((root / ".hellodev" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(project_config["host"], {"kind": "antigravity"})

    def test_antigravity_does_not_import_codex_runtime_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}),
                patch("hellodev.application.usage_collector.sync_codex_usage") as application_sync,
            ):
                onboarding.onboard(root, host="antigravity")
                opened = ProjectClient(root).open(verbose=True)
            application_sync.assert_not_called()
            self.assertEqual(opened["usageSync"]["state"], "unavailable")
            self.assertEqual(opened["usageSync"]["host"], "antigravity")
            self.assertEqual(opened["usageSync"]["reasonCode"], "host-usage-receipt-unavailable")
            self.assertFalse(opened["usageSync"]["estimated"])

            output = io.StringIO()
            with (
                patch("hellodev.cli.usage_collector.sync_codex_usage") as cli_sync,
                redirect_stdout(output),
            ):
                code = main(["--root", str(root), "--json", "open", "--verbose"])
            self.assertEqual(code, 0)
            cli_sync.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["usageSync"]["host"], "antigravity")

    def test_onboard_rejects_conflicting_entry_before_project_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".agents" / "mcp_config.json"
            config.parent.mkdir()
            config.write_text(
                json.dumps({"mcpServers": {"hellodev": {"command": "different"}}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                with self.assertRaisesRegex(ProjectError, "different hellodev MCP entry"):
                    onboarding.onboard(root, host="antigravity")
            self.assertFalse((root / ".hellodev").exists())
            self.assertFalse((root / ".agents" / "rules" / "hellodev.md").exists())

    def test_trellis_initialization_stays_host_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = {"approval": "APPROVE-test", "operation": "trellis-init"}
            with (
                patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}),
                patch("hellodev.onboarding.trellis.prepare_run", return_value=prepared) as prepare,
            ):
                value = onboarding.onboard(root, host="antigravity", prepare_trellis=True)
            self.assertEqual(prepare.call_args.args[1], ["init", "--yes"])
            self.assertEqual(value["trellis"]["state"], "awaiting-confirmation")
            self.assertNotIn("--antigravity", value["trellis"]["resumeCommand"])

    def test_cli_dashboard_and_optional_provider_disclose_antigravity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "--json", "integrate", "show", "--host", "antigravity"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["host"], "antigravity")

            ProjectClient(root).open()
            control = dashboard.snapshot(root, "fixture", "2026-07-24T00:00:00Z")
            self.assertIn("antigravity", control["diagnostics"]["hosts"])

            command = root / "fastctx.cmd"
            command.write_text("@echo off\n", encoding="utf-8")
            with patch("hellodev.repository_tools._candidate", return_value=(command, "fixture")):
                registration = repository_tools.registration("antigravity")
            self.assertEqual(registration["host"], "antigravity")
            self.assertIn('"mcpServers"', registration["snippet"])


if __name__ == "__main__":
    unittest.main()
