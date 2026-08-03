from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, capabilities, changesets, contracts, dashboard, lifecycle, onboarding, resume, trellis_bridge, trellis_execution, verification
from hellodev.application import ProjectClient
from hellodev.mcp_gateway import TOOL_NAMES
from hellodev.project import ProjectPaths, init_project


class V196AdaptiveTrellisExecutionTests(unittest.TestCase):
    @staticmethod
    def _project(directory: str, *, priority: str = "P2", scope: str | None = None) -> tuple[Path, ProjectClient]:
        root = Path(directory)
        (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "README.md").write_text("baseline\n", encoding="utf-8")
        (root / ".git").mkdir()
        script = root / "scripts" / "verify.py"
        script.parent.mkdir()
        script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        init_project(root)
        lifecycle.start(root)
        lifecycle.transition(root, "planned")
        lifecycle.transition(root, "working")
        task = root / ".trellis" / "tasks" / "07-27-adaptive"
        task.mkdir(parents=True)
        (task / "task.json").write_text(
            json.dumps(
                {
                    "priority": priority,
                    "scope": scope,
                    "status": "in_progress",
                    "description": "PRIVATE TASK BODY MUST NOT LEAK",
                    "meta": {"private": "PRIVATE META MUST NOT LEAK"},
                }
            ),
            encoding="utf-8",
        )
        capabilities.refresh(root)
        work_item = contracts.create_work_item(root, "trellis", task.name)
        acceptance.record(root, work_item["id"], "Adaptive Trellis verification", "project verification succeeds")
        changesets.capture_baseline(root)
        return root, ProjectClient(root)

    def test_docs_only_selects_quick_t0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            (root / "README.md").write_text("docs changed\n", encoding="utf-8")
            value = trellis_execution.status(root)
            self.assertEqual((value["profile"], value["requiredLevel"], value["scope"]), ("quick", "T0", "docs"))
            self.assertEqual(value["command"], "git diff --check")
            self.assertEqual(value["verificationState"], "missing")

    def test_small_code_selects_standard_fast_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            (root / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
            value = trellis_execution.status(root)
            self.assertEqual((value["profile"], value["requiredLevel"], value["scope"]), ("standard", "T1", "code"))
            self.assertEqual(value["command"], "python scripts/verify.py --scope fast")

    def test_priority_deletion_and_large_change_select_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory, priority="P1")
            value = trellis_execution.status(root)
            self.assertEqual((value["profile"], value["requiredLevel"], value["scope"]), ("strict", "T2", "project"))
            self.assertIn("high-priority-task", value["reasonCodes"])
            self.assertEqual(value["command"], "python scripts/verify.py --scope full")
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            (root / "src.py").unlink()
            self.assertIn("deletion-present", trellis_execution.status(root)["reasonCodes"])
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            for index in range(11):
                (root / f"change_{index}.py").write_text("pass\n", encoding="utf-8")
            self.assertIn("large-change-set", trellis_execution.status(root)["reasonCodes"])

    def test_next_routes_one_verify_then_reuses_success_for_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            (root / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
            first = client.next()
            self.assertEqual(first["reasonCode"], "acceptance-verification-required")
            self.assertEqual(first["command"], "python scripts/verify.py --scope fast")
            self.assertEqual(first["action"]["hostCommand"], first["command"])
            self.assertIn("do verify", first["action"]["recordSuccessCommand"])
            self.assertIn("--current-snapshot", first["action"]["recordSuccessCommand"])
            self.assertIn("--outcome succeeded", first["action"]["recordSuccessCommand"])
            projection = trellis_execution.status(root)
            planned = verification.plan(root, projection["requiredLevel"], projection["command"], projection["scope"])
            verification.record_session(root, planned["session"]["id"], "succeeded", 91)
            reused = trellis_execution.status(root)
            self.assertEqual(reused["verificationState"], "reused-success")
            self.assertEqual(reused["estimatedAvoidedDurationMs"], 91)
            self.assertIn("do validate", client.next()["command"])
            task_record = json.loads(
                (root / ".trellis" / "tasks" / "07-27-adaptive" / "task.json").read_text(encoding="utf-8")
            )
            acceptance.record_context_validation(
                root,
                "07-27-adaptive",
                trellis_bridge.canonical_sha256(task_record),
                True,
                "component-protocol",
            )
            self.assertEqual(client.next()["command"], "hellodev do check")

    def test_unchanged_failure_does_not_recommend_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            (root / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
            projection = trellis_execution.status(root)
            planned = verification.plan(root, projection["requiredLevel"], projection["command"], projection["scope"])
            verification.record_session(root, planned["session"]["id"], "failed", 12)
            decision = client.next()
            self.assertEqual(decision["reasonCode"], "acceptance-unchanged-failure")
            self.assertNotIn("do verify", decision["command"])
            self.assertIn("status", decision["command"])

    def test_invalid_and_oversized_metadata_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            task_file = root / ".trellis" / "tasks" / "07-27-adaptive" / "task.json"
            task_file.write_text("{", encoding="utf-8")
            invalid = trellis_execution.status(root)
            self.assertEqual(invalid["profile"], "strict")
            self.assertIn("task-metadata-invalid", invalid["reasonCodes"])
            task_file.write_text("x" * (64 * 1024 + 1), encoding="utf-8")
            oversized = trellis_execution.status(root)
            self.assertEqual(oversized["profile"], "strict")
            self.assertIn("task-metadata-oversized", oversized["reasonCodes"])

    def test_local_projects_remain_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            lifecycle.start(root)
            lifecycle.transition(root, "planned")
            lifecycle.transition(root, "working")
            capabilities.refresh(root)
            value = trellis_execution.status(root)
            self.assertEqual(value["state"], "not-applicable")
            decision = resume.next_decision(root)
            self.assertEqual(decision["reasonCode"], "work-intake-required")
            self.assertEqual(decision["action"]["kind"], "begin-work")

    def test_projections_are_private_read_only_and_do_not_expand_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            serialized = json.dumps(
                {
                    "execution": trellis_execution.status(root),
                    "resume": client.resume(),
                    "status": client.status(verbose=True),
                    "dashboard": dashboard.snapshot(root, "instance", "started"),
                }
            )
            self.assertNotIn("PRIVATE TASK BODY", serialized)
            self.assertNotIn("PRIVATE META", serialized)
            self.assertFalse(trellis_execution.status(root)["executionPerformed"])
            self.assertFalse(trellis_execution.status(root)["persistencePerformed"])
            self.assertEqual(len(TOOL_NAMES), 6)
            self.assertLessEqual(len(json.dumps(client.status()).encode("utf-8")), 1024)
        for rule in (onboarding.CURSOR_RULE, onboarding.ANTIGRAVITY_RULE):
            self.assertIn("adaptive check", rule)
            self.assertIn("reused-success", rule)
            self.assertIn("final `do validate` remains authoritative", " ".join(rule.split()))
        dashboard_script = (PACKAGE_ROOT / "src" / "hellodev" / "dashboard_assets" / "app.js").read_text(encoding="utf-8")
        self.assertIn('metric("Trellis profile"', dashboard_script)
        self.assertIn('metric("Adaptive check"', dashboard_script)

    def test_inspect_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._project(directory)
            verification_file = ProjectPaths(root).verification_file
            value = verification.inspect(root, "T1", "python scripts/verify.py --scope fast", "code")
            self.assertEqual(value["state"], "missing")
            self.assertFalse(value["persistencePerformed"])
            self.assertFalse(verification_file.exists())


if __name__ == "__main__":
    unittest.main()
