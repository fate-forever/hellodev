from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, contracts, dashboard, gates, lifecycle, task_alignment, trellis_bridge
from hellodev.application import ProjectClient
from hellodev.project import ProjectError, init_project


def _trellis_task(root: Path, name: str, title: str, *, status: str = "in_progress") -> None:
    task = root / ".trellis" / "tasks" / name
    task.mkdir(parents=True)
    (task / "task.json").write_text(
        json.dumps(
            {
                "id": name,
                "name": name,
                "title": title,
                "description": "",
                "status": status,
                "scope": None,
                "package": None,
                "priority": "P2",
                "meta": {},
            }
        ),
        encoding="utf-8",
    )
    (task / "prd.md").write_text(f"# {title}\n", encoding="utf-8")


class V207IntentBootstrapTests(unittest.TestCase):
    def test_fresh_open_exposes_begin_as_the_only_daily_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opened = ProjectClient(root).open()
            self.assertEqual(set(opened), {"task", "phase", "blockers", "acceptance", "next", "approval"})
            self.assertEqual(opened["phase"], "started")
            self.assertFalse(opened["task"]["bound"])
            self.assertIn("work intake is required", opened["blockers"])
            self.assertEqual(opened["next"]["reasonCode"], "work-intake-required")
            self.assertEqual(opened["next"]["action"]["kind"], "begin-work")
            self.assertEqual(opened["next"]["action"]["requiredInputs"], ["goal", "acceptance"])
            self.assertIn("do begin", opened["next"]["command"])
            self.assertNotIn("do plan", opened["next"]["command"])
            self.assertLessEqual(len(json.dumps(opened).encode("utf-8")), 1400)
            control = dashboard.snapshot(root, "fixture", "2026-07-31T00:00:00Z")
            self.assertEqual(control["schemaVersion"], 23)
            self.assertEqual(control["now"]["next"]["action"]["kind"], "begin-work")
            self.assertEqual(
                control["integrity"],
                {
                    "workItemBound": False,
                    "acceptanceDeclared": False,
                    "trellisTaskBound": False,
                    "closureEligible": False,
                },
            )

    def test_unbound_daily_lifecycle_and_verification_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            for intent in ("plan", "work", "check", "finish"):
                with self.subTest(intent=intent), self.assertRaisesRegex(ProjectError, "no current WorkItem"):
                    client.do(intent)
            with self.assertRaisesRegex(ProjectError, "no current WorkItem"):
                client.do("verify", {"level": "T0", "command": "python -m compileall ."})
            decision = gates.finish_decision(root)
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["reasonCode"], "finish-current-work-required")

    def test_missing_acceptance_blocks_work_and_next_repairs_the_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            created = client.do("begin", {"goal": "Implement login timeout"})
            self.assertEqual(created["state"], "ready")
            with self.assertRaisesRegex(ProjectError, "no AcceptanceContract"):
                client.do("work")
            next_step = client.next()
            self.assertEqual(next_step["reasonCode"], "acceptance-contract-required")
            self.assertEqual(next_step["action"]["requiredInputs"], ["acceptance"])
            repaired = client.do(
                "begin", {"goal": "Implement login timeout", "acceptance": "project tests pass"}
            )
            self.assertEqual(repaired["state"], "already-active")
            self.assertIsNotNone(acceptance.current(root))
            self.assertEqual(client.do("work")["lifecycle"]["phase"], "working")

    def test_begin_repairs_a_legacy_unbound_planned_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            lifecycle.transition(root, "planned", "legacy unbound path")
            repaired = client.do(
                "begin", {"goal": "Repair orphan cycle", "acceptance": "tests pass"}
            )
            self.assertEqual(repaired["state"], "ready")
            self.assertEqual(repaired["workItem"]["linkedPhase"], "planned")
            self.assertEqual(acceptance.current(root)["goal"], "Repair orphan cycle")

    def test_trellis_begin_creates_starts_and_binds_with_one_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            client = ProjectClient(root)
            prepared = client.do(
                "begin", {"goal": "Implement push infrastructure", "acceptance": "npm test passes"}
            )
            self.assertEqual(prepared["state"], "awaiting-confirmation")
            self.assertEqual(prepared["trellisBegin"]["route"], "trellis.task-begin")
            self.assertFalse(prepared["nativeFallbackAllowed"])
            approved = client.do(
                "begin",
                {
                    "goal": "Implement push infrastructure",
                    "acceptance": "npm test passes",
                    "approve": prepared["approval"],
                },
            )
            self.assertEqual(approved["state"], "ready")
            selected = approved["selectedTask"]
            self.assertEqual(contracts.trellis_task_state(root, selected), "in_progress")
            self.assertEqual(contracts.current_work_item(root)["nativeRef"], selected)
            self.assertEqual(acceptance.current(root)["acceptance"], "npm test passes")
            self.assertEqual(task_alignment.binding(root, approved["workItem"]["id"])["nativeRef"], selected)

    def test_component_begin_replay_does_not_duplicate_a_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            init_project(root)
            parameters = {
                "title": "Replay safe task",
                "acceptance": "tests pass",
                "expectedTaskSetDigest": trellis_bridge.canonical_sha256([]),
            }
            operation_id = "op-" + "1" * 64
            first = trellis_bridge.execute(root, "task-begin", parameters, operation_id)
            second = trellis_bridge.execute(root, "task-begin", parameters, operation_id)
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertTrue(second["replayed"])
            self.assertEqual(first["data"]["task"]["id"], second["data"]["task"]["id"])
            self.assertEqual(len(contracts.list_trellis_tasks(root)), 1)

    def test_unique_aligned_trellis_candidate_is_selected_without_help_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _trellis_task(root, "07-31-push-infrastructure", "Push infrastructure")
            _trellis_task(root, "07-31-login-copy", "Login copy")
            result = ProjectClient(root).do(
                "begin", {"goal": "Implement push infrastructure", "acceptance": "npm test passes"}
            )
            self.assertEqual(result["state"], "ready")
            self.assertEqual(result["selectedTask"], "07-31-push-infrastructure")


if __name__ == "__main__":
    unittest.main()
