from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import audit, dashboard
from hellodev.application import ProjectClient
from hellodev.context_runtime import build_context, status
from hellodev.context_runtime.native import clear_cache
from hellodev.mcp_gateway import Gateway
from hellodev.project import ProjectError, ProjectPaths


class V16ContextPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    @staticmethod
    def _repository(root: Path, count: int = 8) -> None:
        source = root / "src"
        source.mkdir(parents=True)
        for index in range(count):
            (source / f"auth_{index}.py").write_text(
                f"def refresh_session_{index}():\n"
                f"    token = 'session-timeout-{index}'\n"
                "    return token\n",
                encoding="utf-8",
            )
        (root / ".env.secret").write_text("session-timeout=do-not-read", encoding="utf-8")
        ignored = root / "node_modules" / "fixture.js"
        ignored.parent.mkdir()
        ignored.write_text("session-timeout", encoding="utf-8")

    def test_native_query_is_root_bound_bounded_and_excludes_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            result = build_context(root, query="session timeout", scope="code", byte_budget=600)
            self.assertEqual(result["backend"], "native")
            self.assertTrue(result["readOnly"])
            self.assertFalse(result["persistencePerformed"])
            self.assertGreater(result["metrics"]["matchedFileCount"], 1)
            self.assertLessEqual(result["metrics"]["returnedTextBytes"], 600)
            paths = {item["path"] for item in result["items"]}
            self.assertTrue(paths)
            self.assertFalse(any("node_modules" in path or ".env" in path for path in paths))
            for item in result["items"]:
                self.assertEqual(item["sourceType"], "Repository fact")
                self.assertEqual(len(item["fileSha256"]), 64)
                self.assertGreaterEqual(item["startLine"], 1)

    def test_cursor_pages_without_repeating_and_fails_stale_after_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root, 12)
            first = build_context(root, query="session timeout", scope="code", byte_budget=300)
            self.assertEqual(first["state"], "partial")
            token = first["continuation"]["cursor"]
            second = build_context(root, query=None, scope="project", byte_budget=300, cursor=token)
            self.assertFalse(
                {item["path"] for item in first["items"]}
                & {item["path"] for item in second["items"]}
            )
            target = root / "src" / "auth_11.py"
            target.write_text(target.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "stale"):
                build_context(root, query=None, scope="project", byte_budget=300, cursor=token)

    def test_cursor_is_bound_to_project_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            left = Path(left_dir)
            right = Path(right_dir)
            self._repository(left, 12)
            self._repository(right, 12)
            token = build_context(left, query="session timeout", scope="code", byte_budget=300)["continuation"]["cursor"]
            with self.assertRaisesRegex(ProjectError, "another project"):
                build_context(right, query=None, scope="project", byte_budget=300, cursor=token)
            replacement = "A" if token[-1] != "A" else "B"
            with self.assertRaises(ProjectError):
                build_context(left, query=None, scope="project", byte_budget=300, cursor=token[:-1] + replacement)

    def test_preview_is_non_persistent_and_cli_context_records_metrics_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            self._repository(root)
            preview = client.context(query="session timeout", scope="code", token_budget=256, preview=True)
            self.assertIn("contextPlane", preview)
            self.assertFalse(preview["persistencePerformed"])
            state_path = ProjectPaths(root).state_dir / "context-plane.json"
            self.assertFalse(state_path.exists())
            recorded = client.context(query="session timeout", scope="code", token_budget=256)
            self.assertTrue(recorded["contextPlane"]["persistencePerformed"])
            self.assertTrue(state_path.is_file())
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            serialized = json.dumps(persisted)
            self.assertNotIn("session timeout", serialized)
            self.assertNotIn("auth_0.py", serialized)
            self.assertFalse(persisted["rawContentPersisted"])
            self.assertIsNotNone(status(root)["lastQuery"])

    def test_gateway_uses_cursor_continuation_without_adding_a_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            self._repository(root, 12)
            value = Gateway(root).call(
                "hellodev_context",
                {"intent": "code", "query": "session timeout", "scope": "code", "token_budget": 128},
            )
            self.assertEqual(value["contextPlane"]["state"], "partial")
            continuation = value["_hellodevResult"]["continuation"]
            self.assertEqual(continuation["tool"], "hellodev_context")
            self.assertIn("cursor", continuation["arguments"])
            self.assertEqual(continuation["arguments"]["token_budget"], 128)

    def test_audit_and_dashboard_expose_metrics_without_repository_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            self._repository(root)
            client.context(query="private session timeout phrase", scope="code", token_budget=256)
            exported = audit.export(root)
            control = dashboard.snapshot(root, "fixture", "2026-07-22T00:00:00Z")
            self.assertEqual(control["schemaVersion"], 12)
            self.assertEqual(control["contextPlane"]["backend"], "native")
            self.assertIn("contextPlane", exported)
            serialized = json.dumps({"audit": exported, "dashboard": control})
            self.assertNotIn("private session timeout phrase", serialized)
            self.assertNotIn("auth_0.py", serialized)
            self.assertNotIn("return token", serialized)

    def test_tampered_metrics_state_cannot_smuggle_repository_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.open()
            self._repository(root)
            client.context(query="session timeout", scope="code", token_budget=256)
            state_path = ProjectPaths(root).state_dir / "context-plane.json"
            value = json.loads(state_path.read_text(encoding="utf-8"))
            value["snapshot"] = "return private_session_token"
            state_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "privacy boundary"):
                status(root)
            with self.assertRaisesRegex(ProjectError, "privacy boundary"):
                audit.export(root)
            with self.assertRaisesRegex(ProjectError, "privacy boundary"):
                dashboard.snapshot(root, "fixture", "2026-07-22T00:00:00Z")

    def test_query_rejects_broad_input_and_result_budget_is_hard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repository(root)
            with self.assertRaisesRegex(ProjectError, "too broad"):
                build_context(root, query="the this project", scope="project", byte_budget=300)
            with self.assertRaisesRegex(ProjectError, "between"):
                build_context(root, query="session timeout", scope="project", byte_budget=255)


if __name__ == "__main__":
    unittest.main()
