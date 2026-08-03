from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, contracts
from hellodev.application import ProjectClient
from hellodev.component_protocol import operation_id
from hellodev.project import ProjectError, init_project
from hellodev.trellis_bridge import execute


def _project_contract(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'acceptance-fixture'\nversion = '1.0.0'\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()


def _trellis_task(root: Path, *, status: str = "in_progress") -> str:
    init_project(root)
    task_id = "07-28-acceptance-flow"
    task = root / ".trellis" / "tasks" / task_id
    task.mkdir(parents=True)
    record = {
        "id": task_id,
        "name": "acceptance-flow",
        "title": "Acceptance flow",
        "description": "",
        "status": status,
        "dev_type": None,
        "scope": "backend",
        "package": None,
        "priority": "P2",
        "creator": "test",
        "assignee": "",
        "createdAt": "2026-07-28",
        "completedAt": None,
        "branch": None,
        "base_branch": None,
        "worktree_path": None,
        "commit": None,
        "pr_url": None,
        "subtasks": [],
        "children": [],
        "parent": None,
        "relatedFiles": [],
        "notes": "",
        "meta": {},
    }
    (task / "task.json").write_text(json.dumps(record), encoding="utf-8")
    (task / "prd.md").write_text("# Acceptance flow\n", encoding="utf-8")
    (task / "implement.jsonl").write_text("", encoding="utf-8")
    (task / "check.jsonl").write_text("", encoding="utf-8")
    return task_id


def _satisfy(client: ProjectClient, root: Path) -> None:
    state = acceptance.status(root)
    planned = client.do(
        "verify",
        {"level": state["runtime"]["level"], "command": state["runtime"]["command"], "scope": state["runtime"]["scope"]},
    )
    client.do(
        "verify",
        {"session": planned["result"]["session"]["id"], "outcome": "succeeded", "duration_ms": 25},
    )


def _validate_context(client: ProjectClient, task_id: str) -> None:
    launch = {
        "source": "bundled",
        "version": "0.6.7+hellodev.0.20.3",
        "revision": "test",
        "component": "hellodev@trellis",
        "protocolVersion": "hellodev.component/v1",
        "prefix": ["trellis"],
        "environment": {},
        "executionIdentity": [],
        "manifestSha256": "0" * 64,
    }
    with patch("hellodev.adapters.trellis._launch", return_value=launch):
        context = client.do("validate", {"task": task_id})
        client.do("validate", {"task": task_id, "approve": context["approval"]})


class AcceptanceContinuityTests(unittest.TestCase):
    def test_local_acceptance_persists_drives_next_and_completes_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            client = ProjectClient(root)
            client.open()
            begun = client.do(
                "begin",
                {"goal": "Add health endpoint", "acceptance": "targeted tests pass"},
            )
            self.assertTrue(begun["objective"]["persistedByHelloDev"])
            self.assertEqual(begun["acceptanceContract"]["acceptance"], "targeted tests pass")
            task_body = (root / ".hellodev" / "tasks" / "task-0001.md").read_text(encoding="utf-8")
            self.assertIn("## Acceptance", task_body)
            self.assertIn("targeted tests pass", task_body)

            working = client.do("work")
            self.assertEqual(working["next"]["reasonCode"], "guided-acceptance-blocked")
            with self.assertRaisesRegex(ProjectError, "check blocked"):
                client.do("check")
            (root / "health.py").write_text("def health():\n    return 'ok'\n", encoding="utf-8")
            self.assertEqual(client.next()["reasonCode"], "acceptance-verification-required")
            _satisfy(client, root)
            self.assertEqual(client.next()["command"], "hellodev do check")
            client.do("check")
            finished = client.do("finish")
            self.assertEqual(finished["lifecycle"]["phase"], "finished")
            self.assertIsNone(contracts.current_work_item(root))
            self.assertEqual(
                json.loads((root / ".hellodev" / "tasks" / "task-0001.md").read_text(encoding="utf-8").splitlines()[1])["status"],
                "completed",
            )

    def test_trellis_context_validation_is_not_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_id = _trellis_task(root)
            parameters = {"task": task_id}
            result = execute(root, "task-validate", parameters, operation_id("trellis", "task-validate", parameters))
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["evidenceClass"], "context-validation")
            self.assertFalse(result["data"]["qualityGateSatisfied"])

    def test_trellis_completion_is_digest_guarded_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_id = _trellis_task(root)
            shown = execute(root, "task-show", {"task": task_id}, operation_id("trellis", "task-show", {"task": task_id}))
            parameters = {"task": task_id, "expectedDigest": shown["data"]["task"]["digest"]}
            op_id = operation_id("trellis", "task-complete", parameters)
            completed = execute(root, "task-complete", parameters, op_id)
            self.assertEqual(completed["data"]["task"]["status"], "completed")
            self.assertTrue(execute(root, "task-complete", parameters, op_id)["replayed"])
            stale = {"task": task_id, "expectedDigest": "0" * 64}
            conflict = execute(root, "task-complete", stale, operation_id("trellis", "task-complete", stale))
            self.assertFalse(conflict["ok"])
            self.assertEqual(conflict["error"]["code"], "digest-conflict")

    def test_trellis_finish_requires_confirmation_and_removes_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _project_contract(root)
            task_id = _trellis_task(root)
            client = ProjectClient(root)
            client.open()
            client.do(
                "begin",
                {"goal": "Finish native task", "acceptance": "project tests pass", "task": task_id},
            )
            client.do("work")
            _satisfy(client, root)
            _validate_context(client, task_id)
            client.do("check")
            prepared = client.do("finish")
            self.assertEqual(prepared["state"], "awaiting-confirmation")
            finished = client.do(
                "finish",
                {"approve": prepared["trellisCompletion"]["approval"], "timeout": 60},
            )
            self.assertEqual(finished["lifecycle"]["phase"], "finished")
            record = json.loads((root / ".trellis" / "tasks" / task_id / "task.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "completed")
            self.assertEqual(contracts.list_trellis_tasks(root), [])
            self.assertIsNone(contracts.current_work_item(root))


if __name__ == "__main__":
    unittest.main()
