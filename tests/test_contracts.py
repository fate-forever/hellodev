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

from hellodev import capabilities, contracts, receipts, sagas
from hellodev.project import ProjectError, ProjectPaths, create_task, init_project, write_json


class ContractTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        return root

    def _verified_gate(self, root: Path) -> dict:
        gate = receipts.record(root, "trellis", "quality-gate", "read", {}, {}, True, kind="gate")
        receipts.record_verification(root, gate["id"], "targeted gate passed")
        return gate

    def test_missing_f2_stores_are_nondestructive_08_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self.assertEqual(contracts.list_work_items(root), [])
            self.assertIsNone(contracts.current_work_item(root))
            self.assertEqual(contracts.list_lesson_proposals(root), [])
            self.assertEqual(contracts.list_evidence_links(root), [])
            self.assertEqual(contracts.current_valid_evidence_links(root), [])
            self.assertFalse((ProjectPaths(root).state_dir / "work-items.json").exists())
            self.assertFalse((ProjectPaths(root).state_dir / "lesson-proposals.json").exists())
            self.assertFalse((ProjectPaths(root).state_dir / "evidence-links.json").exists())

    def test_work_items_are_pointer_only_and_validate_local_and_trellis_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            local = create_task(root, "Private local task body")
            work = contracts.create_work_item(root, "local", local["id"])
            self.assertEqual(contracts.current_work_item(root), work)
            self.assertEqual(contracts.validate_work_item_reference(root, work), work)
            self.assertNotIn(
                "Private local task body",
                (ProjectPaths(root).state_dir / "work-items.json").read_text(encoding="utf-8"),
            )
            with self.assertRaisesRegex(ProjectError, "task not found"):
                contracts.create_work_item(root, "local", "task-9999")

            trellis_task = root / ".trellis" / "tasks" / "07-16-f2"
            trellis_task.mkdir(parents=True)
            (trellis_task / "prd.md").write_text("Private Trellis PRD", encoding="utf-8")
            native = contracts.create_work_item(root, "trellis", "07-16-f2")
            self.assertEqual(native["nativeRef"], "07-16-f2")
            self.assertEqual(contracts.current_work_item(root)["id"], native["id"])
            self.assertNotIn(
                "Private Trellis PRD",
                (ProjectPaths(root).state_dir / "work-items.json").read_text(encoding="utf-8"),
            )
            with self.assertRaisesRegex(ProjectError, "safe"):
                contracts.create_work_item(root, "trellis", "../outside")

    def test_work_item_refresh_tracks_phase_and_invalidates_old_evidence_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            (root / ".trellis" / "tasks" / "07-16-f2").mkdir(parents=True)
            work = contracts.create_work_item(root, "trellis", "07-16-f2")
            gate = receipts.record(
                root,
                "trellis",
                "quality-gate",
                "read",
                {},
                {},
                True,
                kind="gate",
                evidence_binding=contracts.evidence_binding(root),
            )
            link = contracts.reconcile_evidence(root, gate["id"])
            self.assertEqual(link["workItemId"], work["id"])
            self.assertEqual(contracts.current_valid_evidence_links(root), [link])

            (root / "AGENTS.md").write_text("changed contract", encoding="utf-8")
            self.assertEqual(contracts.current_valid_evidence_links(root), [])
            with self.assertRaisesRegex(ProjectError, "stale"):
                contracts.reconcile_evidence(root, gate["id"])
            refreshed = contracts.refresh_work_item(root)
            self.assertEqual(refreshed["sourceFingerprint"], capabilities.fingerprint(root))
            with self.assertRaisesRegex(ProjectError, "not bound"):
                contracts.reconcile_evidence(root, gate["id"])
            fresh_gate = receipts.record(
                root,
                "trellis",
                "quality-gate",
                "read",
                {},
                {},
                True,
                kind="gate",
                evidence_binding=contracts.evidence_binding(root),
            )
            second = contracts.reconcile_evidence(root, fresh_gate["id"])
            self.assertNotEqual(second["id"], link["id"])
            self.assertEqual(contracts.current_valid_evidence_links(root), [second])

            (root / ".trellis" / "tasks" / "07-16-other").mkdir()
            other = contracts.create_work_item(root, "trellis", "07-16-other")
            with self.assertRaisesRegex(ProjectError, "not bound"):
                contracts.reconcile_evidence(root, fresh_gate["id"], other["id"])

    def test_evidence_reconciliation_requires_successful_typed_trellis_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            (root / ".trellis" / "tasks" / "07-16-evidence").mkdir(parents=True)
            contracts.create_work_item(root, "trellis", "07-16-evidence")
            binding = contracts.evidence_binding(root)
            command = receipts.record(root, "trellis", "status", "read", {}, {}, True)
            with self.assertRaisesRegex(ProjectError, "gate or test"):
                contracts.reconcile_evidence(root, command["id"])
            failed = receipts.record(
                root, "trellis", "tests", "read", {}, {}, False, kind="test", evidence_binding=binding
            )
            with self.assertRaisesRegex(ProjectError, "successful"):
                contracts.reconcile_evidence(root, failed["id"])
            unbound = receipts.record(root, "trellis", "tests", "read", {}, {}, True, kind="test")
            with self.assertRaisesRegex(ProjectError, "not bound"):
                contracts.reconcile_evidence(root, unbound["id"])
            test_receipt = receipts.record(
                root, "trellis", "tests", "read", {}, {}, True, kind="test", evidence_binding=binding
            )
            first = contracts.reconcile_evidence(root, test_receipt["id"])
            self.assertEqual(contracts.reconcile_evidence(root, test_receipt["id"]), first)

    def test_lesson_proposal_is_hash_only_and_requires_verified_nocturne_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            private_lesson = "Always keep private handoffs compact"
            gate = self._verified_gate(root)
            saga = sagas.create(root, "Preserve verified lesson")
            proposal = contracts.create_lesson_proposal(
                root,
                private_lesson,
                "cross-project",
                "nocturne",
                evidence_receipt_id=gate["id"],
                saga_id=saga["id"],
                state="saga-active",
            )
            self.assertTrue(contracts.validate_lesson_digest(root, proposal["id"], private_lesson))
            self.assertEqual(contracts.proposal_for_saga(root, saga["id"]), proposal)
            raw = (ProjectPaths(root).state_dir / "lesson-proposals.json").read_text(encoding="utf-8")
            self.assertNotIn(private_lesson, raw)
            self.assertNotIn("targeted gate passed", raw)
            with self.assertRaisesRegex(ProjectError, "digest"):
                contracts.validate_lesson_digest(root, proposal["id"], private_lesson + " changed")

            unverified = receipts.record(root, "trellis", "gate", "read", {}, {}, True, kind="gate")
            with self.assertRaisesRegex(ProjectError, "verification"):
                contracts.create_lesson_proposal(
                    root,
                    "Another private lesson",
                    "cross-project",
                    "nocturne",
                    evidence_receipt_id=unverified["id"],
                )
            with self.assertRaisesRegex(ProjectError, "incompatible"):
                contracts.create_lesson_proposal(root, "Project-specific rule", "project", "nocturne")

    def test_lesson_update_and_saga_lookup_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal = contracts.create_lesson_proposal(root, "Repository test rule", "project", "trellis")
            updated = contracts.update_lesson_proposal(root, proposal["id"], state="completed")
            self.assertEqual(updated["state"], "completed")
            with self.assertRaisesRegex(ProjectError, "transition"):
                contracts.update_lesson_proposal(root, proposal["id"], state="invented")
            with self.assertRaisesRegex(ProjectError, "transition"):
                contracts.update_lesson_proposal(root, proposal["id"], state="saga-active")

            gate = self._verified_gate(root)
            first_saga = sagas.create(root, "First immutable Saga")
            second_saga = sagas.create(root, "Second immutable Saga")
            active = contracts.create_lesson_proposal(
                root,
                "Immutable continuity links",
                "cross-project",
                "nocturne",
                evidence_receipt_id=gate["id"],
                saga_id=first_saga["id"],
                state="saga-active",
            )
            with self.assertRaisesRegex(ProjectError, "immutable"):
                contracts.update_lesson_proposal(root, active["id"], saga_id=second_saga["id"])

    def test_stores_reject_unknown_fields_duplicates_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            task = create_task(root, "Strict store")
            contracts.create_work_item(root, "local", task["id"])
            path = ProjectPaths(root).state_dir / "work-items.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["workItems"][0]["taskBody"] = "secret"
            write_json(path, payload)
            with self.assertRaisesRegex(ProjectError, "fields"):
                contracts.list_work_items(root)

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = self._root(directory)
            path = ProjectPaths(root).state_dir / "lesson-proposals.json"
            target = Path(outside) / "lessons.json"
            target.write_text('{"schemaVersion":1,"lessonProposals":[]}', encoding="utf-8")
            try:
                os.symlink(target, path)
            except OSError:
                original = Path.is_symlink
                with patch.object(Path, "is_symlink", lambda candidate: candidate == path or original(candidate)):
                    with self.assertRaisesRegex(ProjectError, "symlinked"):
                        contracts.list_lesson_proposals(root)
            else:
                with self.assertRaisesRegex(ProjectError, "symlinked"):
                    contracts.list_lesson_proposals(root)


if __name__ == "__main__":
    unittest.main()
