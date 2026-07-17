from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import knowledge_flows, receipts
from hellodev.project import configure_nocturne, create_task, init_project


FAKE_MCP_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


class KnowledgeFlowTests(unittest.TestCase):
    def test_local_recall_strong_weak_and_no_hit_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            task = create_task(root, "Release gate")
            path = Path(task["path"])
            path.write_text(path.read_text(encoding="utf-8") + "\nRun targeted release validation before publishing.\n", encoding="utf-8")
            strong = knowledge_flows.local_recall(root, "release validation")
            weak = knowledge_flows.local_recall(root, "release missing-term")
            none = knowledge_flows.local_recall(root, "no-such-convention")
            self.assertEqual(strong["state"], "strong-hit")
            self.assertTrue(strong["localSufficient"])
            self.assertEqual(strong["results"][0]["sourceLabel"], "Repository fact")
            self.assertEqual(weak["state"], "weak-hit")
            self.assertEqual(none["state"], "no-hit")
            self.assertFalse((root / ".hellodev" / "recall.json").exists())

    def test_local_recall_reads_only_bounded_prefixes_and_reserves_trellis_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            task = create_task(root, "Bounded source")
            task_path = Path(task["path"])
            task_path.write_text(
                task_path.read_text(encoding="utf-8") + "\nbounded-signal\n" + ("x" * 100_000),
                encoding="utf-8",
            )
            with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read is forbidden")):
                bounded = knowledge_flows.local_recall(root, "bounded-signal")
            self.assertEqual(bounded["state"], "strong-hit")
            self.assertLessEqual(bounded["scannedBytes"], knowledge_flows.MAX_FILE_BYTES)

            trellis = root / ".trellis"
            trellis.mkdir()
            (trellis / "workflow.md").write_text("trellis-reserved-signal\n", encoding="utf-8")
            for index in range(30):
                create_task(root, f"Noise task {index:02d}")
            reserved = knowledge_flows.local_recall(root, "trellis-reserved-signal")
            self.assertEqual(reserved["state"], "strong-hit")
            self.assertEqual(reserved["results"][0]["path"], ".trellis/workflow.md")

    def test_recall_degrades_without_nocturne_and_builds_narrow_plan_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            local_only = knowledge_flows.recall_plan(root, "handoff preference", "preferences", 3, "shared")
            self.assertEqual(local_only["state"], "local-only")
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            planned = knowledge_flows.recall_plan(root, "handoff preference", "preferences", 3, "shared")
            self.assertEqual(planned["state"], "memory-plan-required")
            self.assertEqual(planned["nocturne"]["parameters"]["limit"], 3)
            with self.assertRaisesRegex(ValueError, "explicit narrow value"):
                knowledge_flows.recall_plan(root, "handoff preference", "global", 3, "shared")

    def test_remember_project_route_does_not_invent_write_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            plan = knowledge_flows.remember_plan(root, "This project release gate must run before publish", scope="project")
            self.assertEqual(plan["state"], "project-plan")
            self.assertIsNone(plan["writeCommand"])
            self.assertNotIn("This project", str(root / ".hellodev"))

    def test_remember_auto_classifies_chinese_cross_project_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            plan = knowledge_flows.remember_plan(root, "这是我的跨项目偏好：输出保持简洁")
            self.assertEqual(plan["state"], "evidence-required")
            self.assertEqual(plan["destination"], "nocturne")

    def test_remember_cross_project_covers_evidence_and_configuration_branches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            missing = knowledge_flows.remember_plan(root, "Always keep handoffs compact", scope="cross-project")
            self.assertEqual(missing["state"], "evidence-required")
            gate = receipts.record(root, "trellis", "quality-gate", "read", {}, {}, True, kind="gate")
            receipts.record_verification(root, gate["id"], "targeted tests passed")
            no_memory = knowledge_flows.remember_plan(
                root, "Always keep handoffs compact", receipt_id=gate["id"], scope="cross-project"
            )
            self.assertEqual(no_memory["state"], "configuration-required")
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            ready = knowledge_flows.remember_plan(
                root, "Always keep handoffs compact", receipt_id=gate["id"], scope="cross-project"
            )
            self.assertEqual(ready["state"], "saga-plan-ready")
            self.assertEqual(ready["writeParameters"]["tool"], "create_memory")


if __name__ == "__main__":
    unittest.main()
