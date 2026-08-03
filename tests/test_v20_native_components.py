from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev.adapters import nocturne, trellis
from hellodev.component_protocol import canonical_sha256, operation_id, text_error
from hellodev.project import configure_nocturne, init_project
from hellodev.trellis_bridge import execute


FAKE_MCP_SERVER = PACKAGE_ROOT / "tests" / "fixtures" / "fake_mcp_server.py"


def _trellis_project(root: Path) -> None:
    init_project(root)
    task = root / ".trellis" / "tasks" / "07-28-native-bridge"
    task.mkdir(parents=True)
    record = {
        "id": task.name, "name": "native-bridge", "title": "Native bridge", "description": "",
        "status": "planning", "dev_type": None, "scope": "backend", "package": None,
        "priority": "P1", "creator": "test", "assignee": "", "createdAt": "2026-07-28",
        "completedAt": None, "branch": None, "base_branch": None, "worktree_path": None,
        "commit": None, "pr_url": None, "subtasks": [], "children": [], "parent": None,
        "relatedFiles": [], "notes": "", "meta": {},
    }
    (task / "task.json").write_text(json.dumps(record), encoding="utf-8")
    (task / "prd.md").write_text("# PRD\n", encoding="utf-8")


class NativeComponentProtocolTests(unittest.TestCase):
    def test_trellis_bridge_is_structured_idempotent_and_digest_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _trellis_project(root)
            listed = execute(root, "task-list", {}, operation_id("trellis", "task-list", {}))
            self.assertTrue(listed["ok"])
            task = listed["data"]["tasks"][0]
            op_id = operation_id("trellis", "task-start", {"task": task["id"], "expectedDigest": task["digest"]})
            started = execute(root, "task-start", {"task": task["id"], "expectedDigest": task["digest"]}, op_id)
            self.assertEqual(started["data"]["task"]["status"], "in_progress")
            replayed = execute(root, "task-start", {"task": task["id"], "expectedDigest": task["digest"]}, op_id)
            self.assertTrue(replayed["replayed"])
            conflict = execute(root, "task-start", {"task": task["id"], "expectedDigest": "0" * 64}, operation_id("trellis", "task-start", {"task": task["id"], "expectedDigest": "0" * 64}))
            self.assertFalse(conflict["ok"])
            self.assertEqual(conflict["error"]["code"], "digest-conflict")

    def test_bundled_trellis_intent_uses_component_bridge_not_task_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _trellis_project(root)
            launch = {
                "source": "bundled", "version": "0.6.7+hellodev.0.20.3", "revision": "test",
                "component": "hellodev@trellis", "protocolVersion": "hellodev.component/v1",
                "prefix": ["trellis"], "environment": {}, "executionIdentity": [], "manifestSha256": "0" * 64,
            }
            with patch("hellodev.adapters.trellis._launch", return_value=launch):
                payload, risk = trellis._intent_payload(root, "task-list")
            self.assertEqual(risk, "read")
            self.assertEqual(payload["component"], "hellodev@trellis")
            self.assertIn("trellis_bridge_runner.py", " ".join(payload["argv"]))
            self.assertNotIn("task.py", " ".join(payload["argv"]))

    def test_nocturne_enhanced_mode_enforces_read_receipt_and_replays_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            executable = str(Path(sys.executable).resolve())
            base = {
                "mode": "stdio", "source": "external", "command": executable,
                "args": [str(FAKE_MCP_SERVER)], "cwd": str(root), "environment": {},
                "protocolVersion": "hellodev.component/v1", "component": "hellodev@nocturne",
            }
            with patch("hellodev.adapters.nocturne._configuration", return_value=base):
                read_plan = nocturne.prepare_call(root, "read_memory", {"uri": "core://agent"})
                read = nocturne.call(root, "read_memory", {"uri": "core://agent"}, read_plan["approval"], 10)
                self.assertIn("readReceipt", read["result"]["structuredContent"])
                parameters = {"uri": "core://agent", "append": "note"}
                write_plan = nocturne.prepare_call(root, "update_memory", parameters)
                written = nocturne.call(root, "update_memory", parameters, write_plan["approval"], 10)
                self.assertFalse(written["result"]["structuredContent"]["replayed"])
                metadata = write_plan["componentProtocol"]
                replayed = nocturne.nocturne_protocol.replay(
                    root, metadata["operationId"], canonical_sha256({"tool": "update_memory", "parameters": parameters})
                )
                self.assertTrue(replayed["structuredContent"]["replayed"])

    def test_legacy_text_error_is_never_recorded_as_success(self) -> None:
        payload = {"content": [{"type": "text", "text": "Error: missing memory"}], "isError": False}
        self.assertEqual(text_error(payload), "Error: missing memory")
        self.assertFalse(nocturne.call_succeeded({"result": payload}))


if __name__ == "__main__":
    unittest.main()
