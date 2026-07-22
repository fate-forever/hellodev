from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import audit, capabilities, dashboard, repository_tools
from hellodev.application import ProjectClient
from hellodev.bounded_results import RESULT_META_KEY, annotate
from hellodev.cli import _doctor
from hellodev.integrations import show
from hellodev.mcp_gateway import Gateway
from hellodev.project import ProjectError


class V15RepositoryToolTests(unittest.TestCase):
    def test_native_fallback_is_complete_and_never_claims_mcp_connection(self) -> None:
        with patch("hellodev.repository_tools._candidate", return_value=(None, "not-found")):
            value = repository_tools.discover()
        self.assertEqual(value["activeProvider"], "native")
        self.assertEqual(value["suggestedProvider"], "native")
        self.assertEqual(value["activationState"], "native-context-plane")
        self.assertEqual(value["providers"]["fastctx"]["state"], "unavailable")
        self.assertEqual(value["providers"]["fastctx"]["mcpConnection"], "not-inspected")
        self.assertFalse(value["executionPerformed"])
        self.assertFalse(value["configurationInspected"])

    def test_fastctx_discovery_and_registration_are_read_only_and_host_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / ("fastctx.exe" if sys.platform == "win32" else "fastctx")
            command.write_bytes(b"fixture-binary")
            with patch("hellodev.repository_tools._candidate", return_value=(command, "environment")):
                value = repository_tools.discover()
                codex = repository_tools.registration("codex")
                cursor = repository_tools.registration("cursor")
            self.assertEqual(value["activeProvider"], "native")
            self.assertEqual(value["suggestedProvider"], "native")
            self.assertEqual(value["activationState"], "native-context-plane")
            self.assertEqual(value["acceleratorState"], "available-not-active")
            self.assertEqual(value["providers"]["fastctx"]["state"], "available")
            self.assertIn("[mcp_servers.fastctx]", codex["snippet"])
            self.assertIn('"fastctx"', cursor["snippet"])
            self.assertEqual(codex["approvalMode"], "writes")
            self.assertFalse(codex["writePerformed"])

    def test_bounded_result_metadata_is_hash_bound_and_fail_closed(self) -> None:
        value = annotate(
            {"message": "hello"},
            byte_limit=4096,
            token_budget=128,
            budget_scope="context-text",
            continuation={"tool": "hellodev_context", "arguments": {"token_budget": 256}},
            partial=True,
        )
        meta = value[RESULT_META_KEY]
        self.assertEqual(meta["state"], "partial")
        self.assertEqual(meta["provider"], "hellodev-native")
        self.assertEqual(len(meta["payloadSha256"]), 64)
        self.assertGreater(meta["payloadBytes"], 0)
        self.assertGreater(meta["payloadTokens"], 0)
        self.assertIn(meta["tokenMeasurement"], {"exact-o200k-base", "conservative-utf8-byte-ceiling"})
        with self.assertRaisesRegex(ProjectError, "reserves"):
            annotate({RESULT_META_KEY: {}}, byte_limit=4096)
        with self.assertRaisesRegex(ProjectError, "exceeds"):
            annotate({"body": "x" * 5000}, byte_limit=256)

    def test_gateway_adds_measurement_and_structured_context_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            workflow = root / ".trellis" / "workflow.md"
            workflow.parent.mkdir()
            workflow.write_text("repository context\n" * 1000, encoding="utf-8")
            capabilities.refresh(root)
            value = Gateway(root).call(
                "hellodev_context",
                {"intent": "code", "token_budget": 128},
            )
            meta = value[RESULT_META_KEY]
            self.assertEqual(meta["state"], "partial")
            self.assertEqual(meta["tokenBudget"], 128)
            self.assertEqual(meta["budgetScope"], "context-text")
            self.assertEqual(meta["continuation"]["tool"], "hellodev_context")
            self.assertEqual(meta["continuation"]["arguments"]["token_budget"], 256)

    def test_status_doctor_audit_dashboard_and_integration_share_provider_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as tools:
            root = Path(directory)
            command = Path(tools) / ("fastctx.exe" if sys.platform == "win32" else "fastctx")
            command.write_bytes(b"fixture-binary")
            with patch("hellodev.repository_tools._candidate", return_value=(command, "environment")):
                client = ProjectClient(root)
                opened = client.open()
                status = client.status(verbose=True)
                checks = {item["name"]: item for item in _doctor(root)["checks"]}
                exported = audit.export(root)
                control = dashboard.snapshot(root, "fixture", "2026-07-22T00:00:00Z")
                integration = show(root, "codex")
            self.assertEqual(opened["repositoryTools"]["suggestedProvider"], "native")
            self.assertEqual(status["repositoryTools"]["suggestedProvider"], "native")
            self.assertEqual(checks["repository-tool-provider"]["state"], "ok")
            self.assertEqual(exported["repositoryTools"]["activationState"], "native-context-plane")
            self.assertEqual(control["schemaVersion"], 12)
            self.assertEqual(control["diagnostics"]["repositoryTools"]["suggestedProvider"], "native")
            self.assertEqual(integration["repositoryTools"]["state"], "available")
            serialized = json.dumps(exported)
            self.assertNotIn(str(command), serialized)


if __name__ == "__main__":
    unittest.main()
