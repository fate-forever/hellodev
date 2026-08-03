from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, changesets, contracts, dashboard, lifecycle, repository_tools, trellis_execution
from hellodev.application import ProjectClient
from hellodev.context_runtime import build_context, clear_result_sessions
from hellodev.context_runtime import semantic
from hellodev.context_runtime.native import clear_cache
from hellodev.mcp_gateway import Gateway, TOOL_NAMES
from hellodev.project import ProjectPaths, init_project


class V197SemanticContextTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()
        clear_result_sessions()
        semantic.clear_cache()

    @staticmethod
    def _symbol_project(root: Path) -> None:
        source = root / "src"
        source.mkdir(parents=True)
        (source / "sessions.py").write_text(
            "class SessionManager:\n"
            "    def refresh_access_token(self, user_id: str) -> str:\n"
            "        token = f'fresh-{user_id}'\n"
            "        return token\n\n"
            "def unrelated_helper():\n"
            "    return 'noise'\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text("SessionManager refresh_access_token documentation\n", encoding="utf-8")

    def test_exact_symbol_query_uses_bounded_python_ast_then_pages_normally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._symbol_project(root)
            value = build_context(
                root,
                query="SessionManager.refresh_access_token",
                scope="code",
                byte_budget=800,
            )
            self.assertEqual(value["retrieval"]["strategy"], "symbol")
            self.assertEqual(value["retrieval"]["provider"], "native-python-ast")
            self.assertEqual(value["retrieval"]["state"], "matched")
            self.assertEqual(len(value["items"]), 1)
            item = value["items"][0]
            self.assertEqual(item["sourceType"], "Repository symbol")
            self.assertEqual(item["symbol"]["qualifiedName"], "SessionManager.refresh_access_token")
            self.assertIn("def refresh_access_token", item["text"])
            self.assertNotIn("unrelated_helper", item["text"])
            self.assertTrue(value["readOnly"])
            self.assertFalse(value["executionPerformed"])

    def test_natural_language_query_keeps_lexical_path_without_ast_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._symbol_project(root)
            with mock.patch.object(semantic, "_index", side_effect=AssertionError("AST index should not run")):
                value = build_context(root, query="access token documentation", scope="project", byte_budget=800)
            self.assertEqual(value["retrieval"]["strategy"], "lexical")
            self.assertEqual(value["retrieval"]["state"], "not-requested")
            self.assertGreater(value["metrics"]["returnedItemCount"], 0)

    def test_persisted_semantic_metrics_exclude_query_symbol_path_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._symbol_project(root)
            client = ProjectClient(root)
            client.open()
            value = client.context(
                query="SessionManager.refresh_access_token",
                scope="code",
                token_budget=512,
            )
            self.assertEqual(value["contextPlane"]["retrieval"]["strategy"], "symbol")
            state = json.loads((ProjectPaths(root).state_dir / "context-plane.json").read_text(encoding="utf-8"))
            self.assertEqual(state["schemaVersion"], 2)
            serialized = json.dumps(state)
            self.assertNotIn("SessionManager", serialized)
            self.assertNotIn("refresh_access_token", serialized)
            self.assertNotIn("sessions.py", serialized)
            self.assertNotIn("fresh-", serialized)
            self.assertFalse(state["rawContentPersisted"])
            control = dashboard.snapshot(root, "instance", "started")
            self.assertEqual(control["schemaVersion"], 23)
            self.assertEqual(control["contextPlane"]["lastQuery"]["retrieval"]["strategy"], "symbol")
            control_text = json.dumps(control)
            self.assertNotIn("SessionManager", control_text)
            self.assertNotIn("refresh_access_token", control_text)
            self.assertNotIn("sessions.py", control_text)

    def test_serena_is_optional_discovery_only_and_never_claims_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / ("serena.exe" if sys.platform == "win32" else "serena")
            command.write_bytes(b"fixture")
            with (
                mock.patch("hellodev.repository_tools._candidate", return_value=(None, "not-found")),
                mock.patch("hellodev.repository_tools._serena_candidate", return_value=(command, "environment")),
            ):
                value = repository_tools.discover()
            self.assertEqual(value["schemaVersion"], 2)
            self.assertEqual(value["semanticContext"]["activeProvider"], "native-python-ast")
            self.assertEqual(value["semanticContext"]["externalProviderState"], "available-not-connected")
            self.assertEqual(value["providers"]["serena"]["mcpConnection"], "not-inspected")
            self.assertFalse(value["serenaContract"]["connectionAttested"])
            self.assertEqual(value["serenaContract"]["verificationAuthority"], "advisory-only")
            self.assertFalse(value["executionPerformed"])

    @staticmethod
    def _trellis_project(root: Path) -> None:
        (root / "core.py").write_text("def critical(value):\n    return value + 1\n", encoding="utf-8")
        for index in range(4):
            (root / f"consumer_{index}.py").write_text(
                "from core import critical\n\n"
                f"def consume_{index}(value):\n    return critical(value)\n",
                encoding="utf-8",
            )
        script = root / "scripts" / "verify.py"
        script.parent.mkdir()
        script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        init_project(root)
        lifecycle.start(root)
        lifecycle.transition(root, "planned")
        lifecycle.transition(root, "working")
        task = root / ".trellis" / "tasks" / "07-27-semantic"
        task.mkdir(parents=True)
        (task / "task.json").write_text(
            json.dumps({"priority": "P2", "scope": "code", "status": "in_progress"}),
            encoding="utf-8",
        )
        capabilities.refresh(root)
        contracts.create_work_item(root, "trellis", task.name)
        changesets.capture_baseline(root)

    def test_wide_symbol_impact_can_only_escalate_t1_to_t2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._trellis_project(root)
            (root / "core.py").write_text("def critical(value):\n    return value + 2\n", encoding="utf-8")
            value = trellis_execution.status(root)
            self.assertEqual((value["profile"], value["requiredLevel"]), ("strict", "T2"))
            self.assertIn("semantic-impact-wide", value["reasonCodes"])
            self.assertTrue(value["semanticImpact"]["wideImpact"])
            self.assertEqual(value["semanticImpact"]["referencingFileCount"], 4)
            self.assertFalse(value["semanticImpact"]["rawSymbolsExposed"])
            self.assertFalse(value["semanticImpact"]["rawPathsExposed"])

    def test_semantic_context_does_not_expand_daily_mcp_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._symbol_project(root)
            ProjectClient(root).open()
            value = Gateway(root).call(
                "hellodev_context",
                {
                    "intent": "code",
                    "query": "SessionManager.refresh_access_token",
                    "scope": "code",
                    "token_budget": 512,
                },
            )
            self.assertEqual(value["contextPlane"]["retrieval"]["strategy"], "symbol")
            self.assertEqual(len(TOOL_NAMES), 6)
        dashboard_script = (PACKAGE_ROOT / "src" / "hellodev" / "dashboard_assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('metric("Semantic provider"', dashboard_script)
        self.assertIn('metric("Semantic impact"', dashboard_script)


if __name__ == "__main__":
    unittest.main()
