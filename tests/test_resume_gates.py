from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, contracts, gates, lifecycle, receipts, resume, routing, sagas
from hellodev.project import create_task, init_project


class ResumeGateTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        lifecycle.start(root)
        capabilities.refresh(root)
        return root

    def _local_work(self, root: Path) -> dict:
        task = create_task(root, "Current implementation")
        return contracts.create_work_item(root, "local", task["id"])

    def _gate_receipt(self, root: Path) -> dict:
        return receipts.record(
            root,
            "trellis",
            "intent/task-validate",
            "read",
            {"task": "bounded"},
            {"exitCode": 0},
            True,
            kind="gate",
            evidence_binding=contracts.evidence_binding(root),
        )

    def test_resume_is_local_deterministic_and_compact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self._local_work(root)
            expected = resume.next_decision(root)
            with patch("hellodev.adapters.trellis.discover", side_effect=AssertionError("adapter called")), patch(
                "hellodev.adapters.nocturne.status", side_effect=AssertionError("adapter called")
            ):
                self.assertEqual(resume.next_decision(root), expected)
                projection = resume.build(root)
                pack = resume.context_pack(root)
            self.assertEqual(projection["currentWorkItem"]["backend"], "local")
            self.assertLessEqual(pack["byteCount"], 1024)
            self.assertEqual(pack["byteCount"], len(pack["content"].encode("ascii")))
            self.assertFalse(pack["executionPerformed"])
            self.assertEqual(routing.next_decision(root), expected)

    def test_resume_prioritizes_cache_saga_and_stale_work_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            self.assertEqual(resume.next_decision(root)["reasonCode"], "capability-cache-not-fresh")
            capabilities.refresh(root)
            work = self._local_work(root)
            saga = sagas.create(root, "Recover me")
            decision = resume.next_decision(root)
            self.assertEqual(decision["command"], f"hellodev saga next {saga['id']}")
            saga_path = root / ".hellodev" / "sagas" / f"{saga['id']}.json"
            state = sagas.status(root, saga["id"])
            state["phase"] = "completed"
            from hellodev.project import write_json

            write_json(saga_path, state)
            (root / "AGENTS.md").write_text("changed\n", encoding="utf-8")
            self.assertEqual(resume.next_decision(root)["reasonCode"], "capability-cache-not-fresh")
            capabilities.refresh(root)
            stale = resume.next_decision(root)
            self.assertEqual(stale["command"], f"hellodev work refresh {work['id']}")

    def test_default_suggest_preserves_finish_and_strict_policy_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self.assertTrue(gates.finish_decision(root)["allowed"])
            self.assertEqual(gates.policy_show(root)["source"], "default-0.8-compatible")
            gates.policy_set(root, "require-current-gate")
            capabilities.refresh(root)
            blocked = gates.finish_decision(root)
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["reasonCode"], "finish-current-work-required")

    def test_current_fingerprint_evidence_allows_finish_then_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            gates.policy_set(root, "require-current-gate")
            (root / ".trellis" / "tasks" / "07-16-gate").mkdir(parents=True)
            capabilities.refresh(root)
            work = contracts.create_work_item(root, "trellis", "07-16-gate")
            evidence = self._gate_receipt(root)
            linked = gates.reconcile(root, evidence["id"])
            self.assertFalse(linked["trellisMutationPerformed"])
            allowed = gates.finish_decision(root)
            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["workItemId"], work["id"])
            (root / "AGENTS.md").write_text("durable rule changed\n", encoding="utf-8")
            stale = gates.status(root)
            self.assertEqual(stale["state"], "stale-evidence")
            self.assertFalse(gates.finish_decision(root)["allowed"])

    def test_saga_next_uses_work_pointer_and_requires_real_operator_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            (root / ".trellis" / "tasks" / "07-16-f2").mkdir(parents=True)
            capabilities.refresh(root)
            contracts.create_work_item(root, "trellis", "07-16-f2")
            saga = sagas.create(root, "Persist a verified lesson")
            pending = sagas.next_step(root, saga["id"])
            self.assertEqual(pending["command"], "hellodev do validate --task 07-16-f2")
            gate = self._gate_receipt(root)
            sagas.attach(root, saga["id"], gate["id"])
            verification = sagas.next_step(root, saga["id"])
            self.assertEqual(verification["command"], f"hellodev receipt show {gate['id']}")
            self.assertTrue(verification["requiresInput"])
            self.assertIn("<operator evidence>", verification["followUpTemplate"])
            sagas.verify(root, saga["id"], gate["id"], "reviewed gate evidence")
            proposal = contracts.create_lesson_proposal(
                root,
                "Prefer narrow deterministic retrieval",
                "cross-project",
                "nocturne",
                evidence_receipt_id=gate["id"],
                saga_id=saga["id"],
                state="saga-active",
            )
            lesson = sagas.next_step(root, saga["id"])
            self.assertEqual(lesson["command"], f"hellodev lesson show {proposal['id']}")
            self.assertTrue(lesson["requiresInput"])
            self.assertNotIn("Prefer narrow", str(lesson))


if __name__ == "__main__":
    unittest.main()
