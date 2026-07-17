from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import gates, governance, optimization
from hellodev.project import ProjectError, ProjectPaths, init_project


class OptimizationTests(unittest.TestCase):
    def test_read_only_commands_preserve_a_09_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            path = ProjectPaths(root).optimization_file
            self.assertFalse(path.exists())

            status = optimization.status(root)
            planned = optimization.plan(root, "code")
            proposals = optimization.list_proposals(root)

            self.assertEqual(status["state"], "insufficient-data")
            self.assertEqual(status["usageState"], "unavailable")
            self.assertIsNone(status["latestUsageEnvelope"])
            self.assertEqual(planned["context"]["level"], "L1")
            self.assertFalse(planned["persistencePerformed"])
            self.assertEqual(proposals["proposals"], [])
            self.assertFalse(path.exists())

    def test_reflection_without_usage_never_estimates_tokens_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            first = optimization.reflect(root, "code", "L1", "partial", retry_count=2)
            repeated = optimization.reflect(root, "code", "L1", "partial", retry_count=2)

            self.assertEqual(first["state"], "recorded")
            self.assertEqual(repeated["state"], "existing")
            self.assertEqual(first["trace"]["id"], repeated["trace"]["id"])
            self.assertIsNone(first["report"]["metrics"]["totalTokens"])
            self.assertEqual(first["report"]["deepReflection"]["state"], "unavailable")
            self.assertFalse(first["report"]["executionPerformed"])
            self.assertFalse(first["report"]["applyPerformed"])
            store = json.loads(ProjectPaths(root).optimization_file.read_text(encoding="utf-8"))
            self.assertEqual(len(store["traces"]), 1)
            self.assertEqual(len(store["reports"]), 1)

    def test_reported_usage_is_sanitized_and_deep_reflection_has_both_caps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            source = "PRIVATE-USAGE-SOURCE-CANARY"
            scope = "PRIVATE-USAGE-SCOPE-CANARY"
            usage = governance.record_usage(root, 20_000, 12_000, 2, source, scope)
            reflected = optimization.reflect(
                root,
                "code",
                "L1",
                "failed",
                usage_id=usage["id"],
                total_token_ceiling=8_000,
                subagent_token_ceiling=4_000,
                max_subagents=2,
                delegation_mode="executed",
                retry_count=2,
            )

            envelope = reflected["trace"]["usageEnvelope"]
            self.assertEqual(envelope["budgetState"], "exceeded")
            self.assertEqual(envelope["actual"]["sourceTrust"], "asserted")
            self.assertEqual(reflected["report"]["deepReflection"]["tokenCeiling"], 500)
            persisted = ProjectPaths(root).optimization_file.read_text(encoding="utf-8")
            self.assertNotIn(source, persisted)
            self.assertNotIn(scope, persisted)

            second_usage = governance.record_usage(root, 2_000, 0, 0, "host", "turn-2")
            second = optimization.reflect(
                root,
                "doctor",
                "L0",
                "failed",
                usage_id=second_usage["id"],
                total_token_ceiling=1_000,
                retry_count=2,
            )
            self.assertEqual(second["report"]["deepReflection"]["tokenCeiling"], 100)

            third_usage = governance.record_usage(root, 500, 200, 1, "host", "turn-3")
            third = optimization.reflect(
                root,
                "status",
                "L0",
                "succeeded",
                usage_id=third_usage["id"],
            )
            self.assertEqual(third["trace"]["usageEnvelope"]["budgetState"], "exceeded")

    def test_repeated_retry_evidence_creates_a_non_applicable_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            last = None
            for retries in (2, 3, 4):
                last = optimization.reflect(root, "code", "L1", "partial", retry_count=retries)
            self.assertIsNotNone(last)
            self.assertEqual(last["report"]["trend"]["sampleSize"], 3)
            self.assertEqual(last["report"]["trend"]["outcomeCounts"]["partial"], 3)
            self.assertEqual(last["report"]["trend"]["usageAvailableCount"], 0)
            proposals = optimization.list_proposals(root)["proposals"]
            self.assertEqual(len(proposals), 1)
            self.assertEqual(proposals[0]["patches"][0]["target"], "retry.maxAttempts")
            self.assertFalse(proposals[0]["applyAllowed"])
            self.assertTrue(proposals[0]["requiresHumanReview"])

            optimization.reflect(root, "code", "L1", "partial", retry_count=4)
            self.assertEqual(len(optimization.list_proposals(root)["proposals"]), 1)
            gates.policy_set(root, "require-current-gate")
            self.assertTrue(optimization.list_proposals(root)["proposals"][0]["stale"])

    def test_store_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            ProjectPaths(root).optimization_file.write_text(
                json.dumps({"schemaVersion": 1, "traces": [], "reports": [], "proposals": [], "extra": True}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ProjectError, "store fields"):
                optimization.status(root)

    def test_optimizer_records_cannot_authorize_gates_and_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            reflected = optimization.reflect(root, "code", "L1", "partial", retry_count=2)
            with self.assertRaises(ProjectError):
                gates.reconcile(root, reflected["trace"]["id"])
            with self.assertRaises(ProjectError):
                optimization.reflect(root, "code", "L1", "partial", retry_count=True)

            path = ProjectPaths(root).optimization_file
            store = json.loads(path.read_text(encoding="utf-8"))
            store["reports"][0]["recommendations"][0]["command"] = "hellodev profile set autopilot-read"
            path.write_text(json.dumps(store), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "recommendation command"):
                optimization.status(root)

    def test_usage_status_distinguishes_unavailable_from_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            missing = governance.usage_status(root)
            self.assertEqual(missing["state"], "unavailable")
            self.assertIsNone(missing["totalTokens"])

            governance.record_usage(root, 0, 0, 0, "host", "turn")
            reported = governance.usage_status(root)
            self.assertEqual(reported["state"], "reported")
            self.assertEqual(reported["totalTokens"], 0)


if __name__ == "__main__":
    unittest.main()
