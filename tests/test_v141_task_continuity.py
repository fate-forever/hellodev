from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hellodev import capabilities, contracts, dashboard, lifecycle, resume
from hellodev.project import ProjectError, init_project


class TaskContinuityTests(unittest.TestCase):
    def _finished_root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        lifecycle.start(root)
        lifecycle.transition(root, "planned")
        lifecycle.transition(root, "working")
        lifecycle.transition(root, "checking")
        lifecycle.transition(root, "finished")
        (root / ".trellis" / "tasks" / "07-20-current").mkdir(parents=True)
        capabilities.refresh(root)
        return root

    def test_single_trellis_task_is_the_exact_finished_cycle_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._finished_root(directory)
            decision = resume.next_decision(root)
            self.assertEqual(decision["command"], "hellodev work activate --trellis-task 07-20-current")
            self.assertEqual(decision["reasonCode"], "single-trellis-task-ready-for-new-cycle")

    def test_activate_preserves_finished_cycle_and_sets_current_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._finished_root(directory)
            result = contracts.activate_trellis_task(root, "07-20-current")
            self.assertTrue(result["activated"])
            self.assertEqual(result["workItem"]["backend"], "trellis")
            self.assertEqual(result["workItem"]["nativeRef"], "07-20-current")
            self.assertEqual(result["lifecycle"]["phase"], "started")
            self.assertEqual(result["lifecycle"]["cycleId"], "cycle-0002")
            self.assertEqual(result["lifecycle"]["completedCycles"][0]["phase"], "finished")
            self.assertEqual(contracts.current_work_item(root)["id"], result["workItem"]["id"])
            self.assertEqual(resume.next_decision(root)["command"], "hellodev do plan")
            state = dashboard.snapshot(root, "fixture", "2026-07-20T00:00:00Z")
            self.assertEqual(state["schemaVersion"], 9)
            self.assertEqual(state["tasks"], {"localCount": 0, "trellisActiveCount": 1, "linkedWorkItemCount": 1})

    def test_activate_rejects_an_unfinished_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            lifecycle.start(root)
            (root / ".trellis" / "tasks" / "07-20-current").mkdir(parents=True)
            capabilities.refresh(root)
            with self.assertRaisesRegex(ProjectError, "while lifecycle is started"):
                contracts.activate_trellis_task(root, "07-20-current")


if __name__ == "__main__":
    unittest.main()
