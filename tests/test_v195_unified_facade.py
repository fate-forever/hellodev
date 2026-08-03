from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hellodev import capabilities, contracts, dashboard, facade, gates, lifecycle, onboarding, receipts, resume
from hellodev.application import ProjectClient
from hellodev.project import init_project


class V195UnifiedFacadeTests(unittest.TestCase):
    @staticmethod
    def _finished_trellis_root(directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        lifecycle.start(root)
        for phase in ("planned", "working", "checking", "finished"):
            lifecycle.transition(root, phase)
        (root / ".trellis" / "tasks" / "07-24-facade").mkdir(parents=True)
        capabilities.refresh(root)
        return root

    def test_finished_native_task_reenters_through_do_begin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._finished_trellis_root(directory)
            decision = resume.next_decision(root)
            self.assertEqual(decision["reasonCode"], "single-native-task-ready-for-unified-begin")
            self.assertIn(" do begin ", f" {decision['command']} ")
            self.assertNotIn("work activate", decision["command"])
            self.assertEqual(resume.build(root)["facade"]["dailyNamespace"], "hellodev")
            result = ProjectClient(root).do(
                "begin", {"goal": "Continue 07-24-facade", "task": "07-24-facade"}
            )
            self.assertEqual(result["state"], "ready")
            self.assertEqual(result["selectedTask"], "07-24-facade")
            self.assertEqual(result["projectMode"]["mode"], "trellis-native")

    def test_strict_gate_requires_acceptance_contract_before_native_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            lifecycle.start(root)
            (root / ".trellis" / "tasks" / "07-24-gate").mkdir(parents=True)
            capabilities.refresh(root)
            work = contracts.create_work_item(root, "trellis", "07-24-gate")
            gates.policy_set(root, "require-current-gate")
            capabilities.refresh(root)
            contracts.refresh_work_item(root, work["id"])
            blocked = gates.finish_decision(root)
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["reasonCode"], "finish-acceptance-contract-required")
            self.assertIn("do begin", blocked["nextCommand"])

    def test_facade_counts_only_observable_generic_escape_hatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            receipts.record(root, "trellis", "intent/task-list", "read", {}, {"exitCode": 0}, True)
            receipts.record(root, "trellis", "command", "read", {}, {"exitCode": 0}, True)
            value = facade.status(root)
            self.assertEqual(value["state"], "escape-hatch-observed")
            self.assertEqual(value["dailyNamespace"], "hellodev")
            self.assertEqual(value["routedTrellisReceiptCount"], 1)
            self.assertEqual(value["observableEscapeHatchCount"], 1)
            self.assertEqual(value["externalDirectTrellisVisibility"], "unavailable")
            self.assertFalse(value["executionPerformed"])

    def test_dashboard_and_host_rules_disclose_the_unified_facade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            lifecycle.start(root)
            capabilities.refresh(root)
            value = dashboard.snapshot(root, "fixture", "2026-07-24T00:00:00Z")
            self.assertEqual(value["facade"]["dailyNamespace"], "hellodev")
            self.assertEqual(value["facade"]["directTrellisPolicy"], "advanced-escape-hatch-only")
        for rule in (onboarding.CURSOR_RULE, onboarding.ANTIGRAVITY_RULE):
            normalized = " ".join(rule.split())
            self.assertIn("Do not invoke the Trellis CLI", rule)
            self.assertIn("/trellis-continue", rule)
            self.assertIn("hellodev resume", rule)
            self.assertIn("advanced escape hatch", normalized)


if __name__ == "__main__":
    unittest.main()
