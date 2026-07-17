from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, gates, governance, host_bridge, lifecycle
from hellodev.project import ProjectError, ProjectPaths, init_project


class HostBridgeTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        lifecycle.start(root)
        capabilities.refresh(root)
        return root

    def _result(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "outcome": "succeeded",
            "retryCount": 0,
            "retrievalMode": "none",
            "delegationMode": "none",
            "totalTokens": 1_000,
            "subagentTokens": 0,
            "subagentCount": 0,
        }
        value.update(overrides)
        return value

    def test_prepare_is_read_only_bounded_and_capped_by_effective_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in ProjectPaths(root).state_dir.rglob("*")
                if path.is_file()
            }
            envelope = host_bridge.prepare(root, "code", total_token_ceiling=8_000, max_subagents=4)

            self.assertEqual(envelope["state"], "prepared")
            self.assertEqual(envelope["usagePlan"]["maxSubagents"], 2)
            self.assertEqual(envelope["usagePlan"]["retryMaxAttempts"], 3)
            self.assertLessEqual(len(envelope["context"]["text"].encode("utf-8")), envelope["context"]["byteCap"])
            self.assertFalse(envelope["authorization"]["grantsExecution"])
            self.assertFalse(envelope["authorization"]["grantsEvidenceAuthority"])
            self.assertFalse(ProjectPaths(root).host_completions_file.exists())
            self.assertFalse(ProjectPaths(root).evolution_policy_file.exists())
            self.assertFalse(ProjectPaths(root).optimization_file.exists())
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in ProjectPaths(root).state_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_complete_is_idempotent_private_and_host_asserted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            canary = "HOST-CONTEXT-CANARY-MUST-NOT-PERSIST"
            (root / ".trellis").mkdir()
            (root / ".trellis" / "workflow.md").write_text(canary, encoding="utf-8")
            capabilities.refresh(root)
            envelope = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
            first = host_bridge.complete(root, envelope, self._result())
            repeated = host_bridge.complete(root, envelope, self._result())

            self.assertEqual(first["state"], "completed")
            self.assertEqual(repeated["state"], "existing")
            self.assertEqual(first["completion"]["id"], repeated["completion"]["id"])
            self.assertEqual(first["completion"]["usageTrust"], "host-asserted")
            actual = first["trace"]["usageEnvelope"]["actual"]
            self.assertEqual(actual["sourceKind"], "host-envelope")
            self.assertEqual(actual["sourceTrust"], "host-asserted")
            self.assertIn("not provider-verified", actual["accuracy"])
            self.assertEqual(governance.usage_status(root)["state"], "unavailable")
            with self.assertRaises(ProjectError):
                gates.reconcile(root, first["trace"]["id"])
            state_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in ProjectPaths(root).state_dir.rglob("*.json")
                if path.is_file()
            )
            self.assertNotIn(canary, state_text)

    def test_unavailable_host_usage_stays_null_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            envelope = host_bridge.prepare(root, "status")
            result = self._result(totalTokens=None, subagentTokens=None, subagentCount=0)
            completed = host_bridge.complete(root, envelope, result)
            self.assertEqual(completed["completion"]["usageTrust"], "unavailable")
            self.assertEqual(completed["completion"]["budgetState"], "unavailable")
            self.assertIsNone(completed["trace"]["usageEnvelope"]["actual"])

    def test_tampered_stale_and_conflicting_envelopes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            envelope = host_bridge.prepare(root, "code")
            tampered = json.loads(json.dumps(envelope))
            tampered["context"]["text"] += "tamper"
            with self.assertRaisesRegex(ProjectError, "context digest"):
                host_bridge.complete(root, tampered, self._result())

            (root / "AGENTS.md").write_text("changed binding\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "bindings are stale"):
                host_bridge.complete(root, envelope, self._result())

            capabilities.refresh(root)
            current = host_bridge.prepare(root, "code")
            host_bridge.complete(root, current, self._result())
            with self.assertRaisesRegex(ProjectError, "different result"):
                host_bridge.complete(root, current, self._result(outcome="failed"))

    def test_store_schema_and_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            path = ProjectPaths(root).host_completions_file
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "store schema"):
                host_bridge.status(root)

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = self._root(directory)
            target = Path(outside) / "host.json"
            target.write_text('{"schemaVersion":1,"completions":[]}\n', encoding="utf-8")
            try:
                ProjectPaths(root).host_completions_file.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ProjectError, "unsafe host completion"):
                host_bridge.status(root)

    def test_multiple_prepares_in_one_second_have_distinct_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            first = host_bridge.prepare(root, "code")
            second = host_bridge.prepare(root, "code")
            self.assertNotEqual(first["id"], second["id"])
            self.assertNotEqual(first["nonceSha256"], second["nonceSha256"])


if __name__ == "__main__":
    unittest.main()
