from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import knowledge_flows, verification
from hellodev.application import ProjectClient
from hellodev.project import ProjectError, configure_nocturne, init_project


FAKE_MCP_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


class V205AdaptiveGovernanceTests(unittest.TestCase):
    def test_current_snapshot_attestation_records_without_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            result = verification.record_current(
                root, "T1", "python -m pytest -q", "succeeded", 1234, "code"
            )
            self.assertEqual(result["recordMode"], "atomic-current-snapshot")
            self.assertTrue(result["currentSnapshotAttested"])
            self.assertEqual(result["record"]["sourceTrust"], "host-asserted")
            self.assertIsNone(result["record"]["sessionId"])
            summary = verification.summary(root)
            self.assertEqual(summary["pendingSessionCount"], 0)
            self.assertEqual(summary["reusableSuccessCount"], 1)

    def test_daily_verify_requires_explicit_current_snapshot_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Verify current snapshot", "acceptance": "project tests pass"})
            with self.assertRaisesRegex(ProjectError, "snapshot or explicit current_snapshot"):
                client.do(
                    "verify",
                    {
                        "level": "T1",
                        "command": "python -m pytest -q",
                        "scope": "code",
                        "outcome": "succeeded",
                    },
                )
            recorded = client.do(
                "verify",
                {
                    "level": "T1",
                    "command": "python -m pytest -q",
                    "scope": "code",
                    "outcome": "succeeded",
                    "duration_ms": 10,
                    "current_snapshot": True,
                },
            )
            self.assertTrue(recorded["result"]["currentSnapshotAttested"])
            self.assertTrue(recorded["arguments"]["currentSnapshotAttested"])

    def test_next_returns_host_command_and_atomic_receipt_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"name": "sample", "scripts": {"test": "vitest run"}}),
                encoding="utf-8",
            )
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Add a feature", "acceptance": "project tests pass"})
            source = root / "src" / "feature.ts"
            source.parent.mkdir()
            source.write_text("export const feature = true\n", encoding="utf-8")
            client.do("work")
            decision = client.next()
            self.assertEqual(decision["command"], verification.executable_command("npm test"))
            self.assertEqual(decision["action"]["kind"], "host-verification")
            self.assertEqual(decision["action"]["hostCommand"], verification.executable_command("npm test"))
            self.assertIn("--current-snapshot", decision["action"]["recordSuccessCommand"])
            self.assertIn("--outcome succeeded", decision["action"]["recordSuccessCommand"])
            self.assertFalse(decision["action"]["helpOrStatusProbeRequired"])

            client.do(
                "verify",
                {
                    "level": "T1",
                    "command": "npm test",
                    "scope": "code",
                    "outcome": "succeeded",
                    "duration_ms": 50,
                    "current_snapshot": True,
                },
            )
            self.assertEqual(client.next()["command"], "hellodev do check")
            self.assertEqual(verification.summary(root)["pendingSessionCount"], 0)

    def test_recall_defaults_to_core_and_enriches_one_query_from_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "banxue-plan",
                        "scripts": {"test": "vitest run", "typecheck": "tsc -b"},
                        "devDependencies": {"typescript": "latest"},
                    }
                ),
                encoding="utf-8",
            )
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            plan = knowledge_flows.recall_plan(
                root, "project quality lessons", None, None, None, also_memory=True
            )
            self.assertEqual(plan["nocturne"]["parameters"]["domain"], "core")
            query = plan["nocturne"]["parameters"]["query"]
            self.assertIn("vitest", query)
            self.assertIn("tsc", query)
            self.assertEqual(plan["queryEnrichment"]["state"], "applied")
            self.assertFalse(plan["queryEnrichment"]["automaticRetry"])
            self.assertEqual(
                plan["scopeDerivation"]["namespaceEnforcement"],
                "audit-only-upstream-contract-unavailable",
            )

    def test_empty_memory_payload_is_a_diagnostic_zero_result(self) -> None:
        raw = {
            "result": {
                "content": [
                    {"type": "text", "text": "[]"},
                    {"type": "text", "text": "No memories found."},
                ]
            }
        }
        value = knowledge_flows.project_memory_result(raw, {"results": []}, 3)
        self.assertEqual(value["state"], "zero-result")
        self.assertEqual(value["acceptedCount"], 0)
        self.assertEqual(value["reasonCodes"], ["nocturne-zero-accepted-items"])
        self.assertFalse(value["automaticRetryPerformed"])


if __name__ == "__main__":
    unittest.main()
