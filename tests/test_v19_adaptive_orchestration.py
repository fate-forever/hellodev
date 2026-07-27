from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import changesets, contracts, dashboard, verification, workflow_projection
from hellodev.application import ProjectClient
from hellodev.project import ProjectError, ProjectPaths, create_task, init_project


class V19AdaptiveOrchestrationTests(unittest.TestCase):
    def _project(self, directory: str) -> tuple[Path, ProjectClient]:
        root = Path(directory)
        (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "README.md").write_text("baseline\n", encoding="utf-8")
        client = ProjectClient(root)
        result = client.do("begin", {"goal": "Adaptive orchestration"})
        self.assertEqual(result["changeSet"]["changedFileCount"], 0)
        return root, client

    def test_authority_projection_distinguishes_local_trellis_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            self.assertEqual(workflow_projection.status(root)["mode"], "local")
            task_dir = root / ".trellis" / "tasks" / "07-23-current"
            task_dir.mkdir(parents=True)
            recovery = workflow_projection.status(root)
            self.assertEqual(recovery["mode"], "hybrid-recovery")
            self.assertEqual(recovery["reasonCode"], "trellis-work-item-missing")
            contracts.create_work_item(root, "trellis", task_dir.name)
            native = workflow_projection.status(root)
            self.assertEqual(native["mode"], "trellis-native")
            self.assertTrue(native["projectionOnly"])
            self.assertEqual(native["authoritativeSystem"], "trellis")

    def test_changeset_is_hash_only_and_classifies_code_and_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            (root / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "README.md").write_text("changed\n", encoding="utf-8")
            value = changesets.summary(root)
            self.assertEqual(value["changedFileCount"], 2)
            self.assertEqual(value["scopeCounts"], {"code": 1, "docs": 1, "project": 2})
            raw = ProjectPaths(root).changeset_file.read_text(encoding="utf-8")
            self.assertNotIn("src.py", raw)
            self.assertNotIn("README.md", raw)
            self.assertNotIn("VALUE", raw)
            self.assertFalse(value["rawPathsPersisted"])
            self.assertEqual(changesets.classify_path(".trellis/workflow.md"), "code")
            self.assertEqual(changesets.classify_path("AGENTS.md"), "code")

    def test_t1_session_survives_docs_change_and_reuses_scoped_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            raw_command = "pytest tests/unit -q"
            planned = client.do("verify", {"level": "T1", "command": raw_command})["result"]
            self.assertEqual(planned["scope"], "code")
            self.assertEqual(planned["state"], "run-required")
            session_id = planned["session"]["id"]
            repeated = client.do("verify", {"level": "T1", "command": raw_command})["result"]
            self.assertEqual(repeated["session"]["id"], session_id)
            self.assertEqual(verification.summary(root)["pendingSessionCount"], 1)
            (root / "README.md").write_text("docs-only change\n", encoding="utf-8")
            recorded = client.do(
                "verify", {"session": session_id, "outcome": "succeeded", "duration_ms": 40}
            )["result"]
            self.assertEqual(recorded["record"]["scope"], "code")
            reused = client.do("verify", {"level": "T1", "command": raw_command})["result"]
            self.assertEqual(reused["state"], "reused-success")
            raw = ProjectPaths(root).verification_file.read_text(encoding="utf-8")
            self.assertNotIn(raw_command, raw)
            with self.assertRaisesRegex(ProjectError, "already been consumed"):
                verification.record_session(root, session_id, "succeeded", 40)

    def test_t2_session_rejects_any_project_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            planned = client.do("verify", {"level": "T2", "command": "pytest -q"})["result"]
            self.assertEqual(planned["scope"], "project")
            (root / "README.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "scope changed"):
                client.do("verify", {"session": planned["session"]["id"], "outcome": "succeeded"})

    def test_session_rejects_work_item_switch_and_resume_selects_one_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            planned = client.do("verify", {"level": "T0", "command": "python -m compileall src.py"})["result"]
            next_step = client.next()
            self.assertEqual(next_step["reasonCode"], "verification-session-pending")
            self.assertIn(planned["session"]["id"], next_step["command"])
            other = create_task(root, "Other work")
            work = contracts.create_work_item(root, "local", other["id"], make_current=False)
            contracts.set_current_work_item(root, work["id"])
            with self.assertRaisesRegex(ProjectError, "WorkItem changed"):
                client.do("verify", {"session": planned["session"]["id"], "outcome": "failed"})

    def test_dashboard_schema_15_exposes_only_sanitized_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            value = dashboard.snapshot(root, "instance", "started")
            self.assertEqual(value["schemaVersion"], 15)
            self.assertEqual(value["projectMode"]["mode"], "local")
            self.assertFalse(value["changeSet"]["rawPathsPersisted"])
            self.assertFalse(value["verification"]["rawCommandPersisted"])
            self.assertEqual(value["gateProjection"]["unlinkedDetection"], "unavailable")

    def test_schema_1_store_loads_and_upgrades_on_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            legacy = {
                "schemaVersion": 1,
                "records": [],
            }
            ProjectPaths(root).verification_file.write_text(json.dumps(legacy), encoding="utf-8")
            planned = client.do("verify", {"level": "T0", "command": "python -m compileall src.py"})["result"]
            self.assertEqual(planned["state"], "run-required")
            upgraded = json.loads(ProjectPaths(root).verification_file.read_text(encoding="utf-8"))
            self.assertEqual(upgraded["schemaVersion"], 2)
            self.assertEqual(len(upgraded["sessions"]), 1)


if __name__ == "__main__":
    unittest.main()
