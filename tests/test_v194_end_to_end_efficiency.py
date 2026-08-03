from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import changesets, governance
from hellodev.application import ProjectClient
from hellodev.context_runtime import build_context, clear_result_sessions
from hellodev.context_runtime import native
from hellodev.mcp_gateway import Gateway


class V194EndToEndEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        native.clear_cache()
        clear_result_sessions()

    @staticmethod
    def _package(root: Path, name: str, filename: str, body: str) -> None:
        package = root / "packages" / name
        package.mkdir(parents=True)
        (package / "pyproject.toml").write_text(
            f"[project]\nname = '{name.replace('_', '-')}'\nversion = '1.0.0'\n",
            encoding="utf-8",
        )
        (package / filename).write_text(body, encoding="utf-8")

    def test_cross_package_natural_query_never_implicitly_focuses_one_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._package(root, "billing_service", "invoice_api.py", "def invoice_retry():\n    return 'policy'\n")
            self._package(root, "queue_worker", "invoice_handler.py", "def invoice_queue():\n    return 'retry'\n")
            self._package(root, "storage", "invoice_repository.py", "def persist_invoice():\n    return 'persistence'\n")
            result = build_context(
                root,
                query="invoice retry policy queue persistence",
                scope="code",
                byte_budget=4096,
            )
            self.assertEqual(result["focus"], {
                "strategy": "project-root", "root": ".", "projectRoot": True,
            })
            paths = {item["path"] for item in result["items"]}
            self.assertIn("packages/billing_service/invoice_api.py", paths)
            self.assertIn("packages/queue_worker/invoice_handler.py", paths)
            self.assertIn("packages/storage/invoice_repository.py", paths)

    def test_empty_project_open_performs_no_repository_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
            with mock.patch.object(native, "_candidates", wraps=native._candidates) as candidates:
                value = ProjectClient(root).open()
            self.assertEqual(value["phase"], "started")
            candidates.assert_not_called()
            self.assertEqual(ProjectClient(root).status(verbose=True)["changeSet"]["changedFileCount"], 0)

    def test_open_reuses_one_snapshot_when_baseline_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
            client = ProjectClient(root)
            client.do("begin", {"goal": "Snapshot reuse"})
            native.clear_cache()
            with mock.patch.object(native, "_candidates", wraps=native._candidates) as candidates:
                client.open()
            self.assertEqual(candidates.call_count, 1)

    def test_gateway_budget_covers_the_complete_context_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectClient(root).open()
            source = root / "src"
            source.mkdir()
            for index in range(20):
                (source / f"auth_{index}.py").write_text(
                    f"def refresh_session_{index}():\n    return 'session timeout token'\n",
                    encoding="utf-8",
                )
            value = Gateway(root).call(
                "hellodev_context",
                {"intent": "code", "query": "session timeout", "scope": "code", "token_budget": 1200},
            )
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            metadata = value["_hellodevResult"]
            self.assertEqual(metadata["budgetScope"], "complete-mcp-payload-envelope")
            self.assertLessEqual(len(encoded), metadata["resultByteLimit"])
            self.assertLessEqual(metadata["resultByteLimit"], 7200)
            self.assertIsNotNone(metadata["continuation"])

    def test_runtime_usage_backfill_commits_with_one_load_and_one_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectClient(root).open()
            records = [
                {
                    "input_tokens": 100 + index,
                    "cached_input_tokens": 20,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 2,
                    "subagent_tokens": 0,
                    "subagent_count": 0,
                    "completed_at": f"2026-07-24T00:{index:02d}:00Z",
                    "source_sha256": "a" * 64,
                    "scope_sha256": f"{index:064x}",
                    "source_kind": "codex-runtime",
                    "source_trust": "runtime-observed",
                }
                for index in range(40)
            ]
            with mock.patch.object(
                governance, "_runtime_usage_store", wraps=governance._runtime_usage_store
            ) as load_store, mock.patch.object(
                governance, "write_json", wraps=governance.write_json
            ) as write_store:
                stored = governance.record_runtime_usage_batch(root, records)
            self.assertEqual(load_store.call_count, 1)
            self.assertEqual(write_store.call_count, 1)
            self.assertEqual(len(stored), 40)
            self.assertEqual(stored[0]["record"]["id"], "runtime-usage-0001")
            self.assertEqual(stored[-1]["record"]["id"], "runtime-usage-0040")


if __name__ == "__main__":
    unittest.main()
