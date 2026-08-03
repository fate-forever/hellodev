from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import dashboard, onboarding
from hellodev.application import ProjectClient
from hellodev.project import ProjectError, ProjectPaths, list_tasks


class V17UsabilityTests(unittest.TestCase):
    def test_local_begin_is_one_idempotent_task_cycle_with_context_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)

            value = client.do("begin", {"goal": "Implement login timeout", "acceptance": "All tests pass"})
            self.assertEqual(value["state"], "ready")
            self.assertEqual(value["currentTask"]["backend"], "local")
            self.assertEqual(value["currentTask"]["title"], "Implement login timeout")
            self.assertEqual(value["currentTask"]["lifecyclePhase"], "planned")
            self.assertEqual(value["contextPlan"]["query"], "Implement login timeout")
            self.assertEqual(value["contextPlan"]["scope"], "code")
            self.assertFalse(value["contextPlan"]["repositoryReadPerformed"])
            self.assertIn("context pack", value["contextPlan"]["command"])
            self.assertEqual(value["next"]["command"], "hellodev do work")

            repeated = client.do("begin", {"goal": "Implement login timeout", "acceptance": "All tests pass"})
            self.assertEqual(repeated["state"], "already-active")
            self.assertFalse(repeated["executionPerformed"])
            self.assertEqual(len(list_tasks(root)), 1)
            self.assertEqual(client.status()["currentTask"]["title"], "Implement login timeout")

    def test_begin_selects_one_trellis_task_and_rejects_ambiguous_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / ".trellis" / "tasks" / "07-22-login"
            task.mkdir(parents=True)
            client = ProjectClient(root)

            selected = client.do("begin", {"goal": "Continue login work"})
            self.assertEqual(selected["state"], "ready")
            self.assertEqual(selected["selectedTask"], "07-22-login")
            self.assertEqual(selected["currentTask"]["backend"], "trellis")
            self.assertEqual(selected["currentTask"]["lifecyclePhase"], "planned")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("07-22-a", "07-22-b"):
                (root / ".trellis" / "tasks" / name).mkdir(parents=True, exist_ok=True)
            value = ProjectClient(root).do("begin", {"goal": "Choose work"})
            self.assertEqual(value["state"], "selection-required")
            self.assertEqual(value["candidates"], ["07-22-a", "07-22-b"])
            self.assertIsNone(value["currentTask"]["id"])

    def test_begin_preserves_trellis_approval_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            prepared = {
                "route": "trellis.task-create",
                "executionPerformed": False,
                "approval": "APPROVE-test",
                "resumeCommand": "hellodev do begin --goal Goal --approve APPROVE-test",
            }
            with patch("hellodev.application._run_trellis", return_value=prepared):
                value = ProjectClient(root).do("begin", {"goal": "Goal"})
            self.assertEqual(value["state"], "awaiting-confirmation")
            self.assertEqual(value["approval"], "APPROVE-test")
            self.assertIn("do begin", value["resumeCommand"])
            self.assertFalse(value["executionPerformed"])

    def test_approved_begin_creates_and_links_one_native_trellis_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            client = ProjectClient(root)
            prepared = client.do("begin", {"goal": "Create through Trellis"})
            self.assertEqual(prepared["state"], "awaiting-confirmation")

            approved = client.do(
                "begin",
                {"goal": "Create through Trellis", "approve": prepared["approval"]},
            )
            self.assertEqual(approved["state"], "ready")
            self.assertIn("create-through-trellis", approved["selectedTask"])
            self.assertEqual(approved["currentTask"]["backend"], "trellis")
            self.assertEqual(approved["currentTask"]["nativeRef"], approved["selectedTask"])
            self.assertEqual(approved["currentTask"]["lifecyclePhase"], "planned")

    def test_core_onboard_is_idempotent_and_never_invents_nocturne(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                first = onboarding.onboard(root, host="cursor")
                second = onboarding.onboard(root, host="cursor")
            self.assertEqual(first["mode"], "core")
            self.assertEqual(first["runtime"]["state"], "core")
            self.assertEqual(first["nocturne"]["state"], "configuration-required")
            self.assertTrue((root / ".cursor" / "mcp.json").is_file())
            self.assertTrue((root / ".cursor" / "rules" / "hellodev.mdc").is_file())
            config = json.loads((root / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertIn("hellodev", config["mcpServers"])
            self.assertFalse(second["project"]["created"])
            self.assertFalse(second["host"]["changed"])

    def test_dashboard_projects_one_current_task_and_keeps_internal_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectClient(root).do("begin", {"goal": "Dashboard task"})
            value = dashboard.snapshot(root, "instance", "started")
            self.assertEqual(value["schemaVersion"], 23)
            self.assertEqual(value["currentTask"]["title"], "Dashboard task")
            self.assertEqual(value["now"]["currentTask"]["id"], value["currentTask"]["id"])
            self.assertEqual(value["tasks"], {"localCount": 1, "trellisActiveCount": 0, "linkedWorkItemCount": 1})
            self.assertTrue(value["readOnly"])

    def test_begin_refuses_to_replace_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = ProjectClient(directory)
            client.do("begin", {"goal": "First"})
            with self.assertRaisesRegex(ProjectError, "current lifecycle cycle"):
                client.do("begin", {"goal": "Second"})


if __name__ == "__main__":
    unittest.main()
