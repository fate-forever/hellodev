from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import intelligence, receipts, sagas
from hellodev.project import ProjectError, ProjectPaths, init_project, write_json


class TypedReceiptTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        return root

    def test_typed_receipts_store_only_digests_and_verification_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            gate = receipts.record(
                root,
                "trellis",
                "quality-gate",
                "read",
                {"command": "private gate command"},
                {"output": "private gate output"},
                True,
                kind="gate",
            )
            verification = receipts.record_verification(
                root,
                gate["id"],
                "private reviewer evidence",
            )

            self.assertEqual(gate["kind"], "gate")
            self.assertRegex(gate["requestSha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(gate["resultSha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(verification["kind"], "verification")
            self.assertEqual(verification["subjectReceiptId"], gate["id"])
            self.assertRegex(verification["evidenceSha256"], r"^[0-9a-f]{64}$")

            raw_store = ProjectPaths(root).receipts_file.read_text(encoding="utf-8")
            self.assertNotIn("private gate command", raw_store)
            self.assertNotIn("private gate output", raw_store)
            self.assertNotIn("private reviewer evidence", raw_store)
            self.assertEqual(json.loads(raw_store)["schemaVersion"], 3)

    def test_receipt_kind_adapter_and_verification_contracts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            with self.assertRaisesRegex(ProjectError, "incompatible"):
                receipts.record(
                    root,
                    "nocturne",
                    "tests",
                    "read",
                    {},
                    {},
                    True,
                    kind="test",
                )
            with self.assertRaisesRegex(ProjectError, "kind"):
                receipts.record(  # type: ignore[arg-type]
                    root,
                    "trellis",
                    "tests",
                    "read",
                    {},
                    {},
                    True,
                    kind="report",
                )
            with self.assertRaisesRegex(ProjectError, "subject"):
                receipts.record(
                    root,
                    "hellodev",
                    "receipt.verify",
                    "read",
                    {},
                    {},
                    True,
                    kind="verification",
                )

            failed = receipts.record(
                root,
                "trellis",
                "tests",
                "read",
                {},
                {"exitCode": 1},
                False,
                kind="test",
            )
            with self.assertRaisesRegex(ProjectError, "failed"):
                receipts.record_verification(root, failed["id"], "failure observed")

    def test_store_rejects_unknown_fields_bad_digests_and_duplicate_ids(self) -> None:
        corruptions = (
            lambda payload: payload["receipts"][0].update({"rawOutput": "secret"}),
            lambda payload: payload["receipts"][0].update({"resultSha256": "0" * 63}),
            lambda payload: payload["receipts"].append(dict(payload["receipts"][0])),
        )
        for corrupt in corruptions:
            with self.subTest(corrupt=corrupt):
                with tempfile.TemporaryDirectory() as directory:
                    root = self._root(directory)
                    receipts.record(root, "trellis", "status", "read", {}, {}, True)
                    path = ProjectPaths(root).receipts_file
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    corrupt(payload)
                    write_json(path, payload)
                    with self.assertRaises(ProjectError):
                        receipts.list_receipts(root)

    def test_schema_one_receipts_are_strictly_migrated_to_command_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            current = receipts.record(root, "trellis", "status", "read", {}, {}, True)
            legacy = {
                key: value
                for key, value in current.items()
                if key not in {"kind", "profileUsed", "authorizationMode"}
            }
            write_json(
                ProjectPaths(root).receipts_file,
                {"schemaVersion": 1, "receipts": [legacy]},
            )
            loaded = receipts.list_receipts(root)
            self.assertEqual(loaded[0]["kind"], "command")
            receipts.record(root, "trellis", "status", "read", {}, {}, True)
            persisted = json.loads(
                ProjectPaths(root).receipts_file.read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["schemaVersion"], 3)
            self.assertEqual([item["kind"] for item in persisted["receipts"]], ["command", "command"])


class SagaEvidenceTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        return root

    def _typed_evidence(
        self,
        root: Path,
        kind: receipts.ReceiptKind,
        succeeded: bool = True,
    ) -> dict:
        return receipts.record(
            root,
            "trellis",
            f"{kind}-evidence",
            "read",
            {"selection": "targeted"},
            {"exitCode": 0 if succeeded else 1},
            succeeded,
            kind=kind,
        )

    def test_generic_trellis_command_cannot_satisfy_saga(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            saga = sagas.create(root, "Persist only verified evidence")
            command = receipts.record(
                root,
                "trellis",
                "command",
                "write",
                {"argv": ["trellis", "update"]},
                {"exitCode": 0},
                True,
            )
            with self.assertRaisesRegex(ProjectError, "gate or test"):
                sagas.attach(root, saga["id"], command["id"])
            with self.assertRaisesRegex(ProjectError, "generic Trellis write"):
                sagas.require_trellis_write(root, saga["id"])
            self.assertEqual(sagas.status(root, saga["id"])["phase"], "trellis-pending")

    def test_failed_trellis_evidence_makes_saga_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            saga = sagas.create(root, "Do not persist failed evidence")
            failed = self._typed_evidence(root, "test", succeeded=False)
            state = sagas.attach(root, saga["id"], failed["id"])
            self.assertEqual(state["phase"], "partial")
            with self.assertRaisesRegex(ProjectError, "successful, verified"):
                sagas.require_nocturne_write(root, saga["id"])

    def test_verified_gate_allows_nocturne_write_and_creates_verification_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            saga = sagas.create(root, "Persist verified gate lesson")
            gate = self._typed_evidence(root, "gate")
            attached = sagas.attach(root, saga["id"], gate["id"])
            self.assertEqual(attached["phase"], "trellis-executed")

            verified = sagas.verify(
                root,
                saga["id"],
                gate["id"],
                "quality gate passed against the selected revision",
            )
            self.assertEqual(verified["phase"], "trellis-verified")
            trellis_verification = receipts.get(
                root,
                verified["trellisVerification"]["verificationReceiptId"],
            )
            self.assertEqual(trellis_verification["kind"], "verification")
            self.assertEqual(trellis_verification["subjectReceiptId"], gate["id"])
            sagas.require_nocturne_write(root, saga["id"])

            nocturne = receipts.record(
                root,
                "nocturne",
                "tools/call",
                "write",
                {"tool": "create_memory", "parameterSha256": "a" * 64},
                {"status": "stored"},
                True,
            )
            nocturne_attached = sagas.attach(root, saga["id"], nocturne["id"])
            self.assertEqual(nocturne_attached["phase"], "nocturne-executed")
            completed = sagas.verify(
                root,
                saga["id"],
                nocturne["id"],
                "public MCP result was verified",
            )
            self.assertEqual(completed["phase"], "completed")
            self.assertEqual(
                [item["kind"] for item in receipts.list_receipts(root)],
                ["gate", "verification", "command", "verification"],
            )
            stores = (
                ProjectPaths(root).receipts_file.read_text(encoding="utf-8")
                + (ProjectPaths(root).sagas_dir / f"{saga['id']}.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("quality gate passed", stores)
            self.assertNotIn("public MCP result", stores)

    def test_preverified_evidence_can_enter_unified_remember_saga_without_reentering_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            saga = sagas.create(root, "Remember verified lesson")
            gate = self._typed_evidence(root, "gate")
            verification = receipts.record_verification(root, gate["id"], "gate already verified")
            state = sagas.attach_verified_evidence(root, saga["id"], gate["id"])
            self.assertEqual(state["phase"], "trellis-verified")
            self.assertEqual(state["trellisVerification"]["verificationReceiptId"], verification["id"])
            sagas.require_nocturne_write(root, saga["id"])

    def test_tampered_verification_link_blocks_nocturne(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            saga = sagas.create(root, "Reject forged evidence link")
            test_receipt = self._typed_evidence(root, "test")
            sagas.attach(root, saga["id"], test_receipt["id"])
            state = sagas.verify(root, saga["id"], test_receipt["id"], "targeted tests passed")
            state["trellisVerification"]["evidenceSha256"] = "0" * 64
            write_json(ProjectPaths(root).sagas_dir / f"{saga['id']}.json", state)
            with self.assertRaisesRegex(ProjectError, "verification receipt is invalid"):
                sagas.require_nocturne_write(root, saga["id"])

    def test_legacy_saga_is_inspectable_but_cannot_continue_as_typed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            saga = sagas.create(root, "Legacy generic evidence")
            path = ProjectPaths(root).sagas_dir / f"{saga['id']}.json"
            legacy = json.loads(path.read_text(encoding="utf-8"))
            legacy.pop("requiredTrellisEvidenceKinds")
            write_json(path, legacy)
            inspected = sagas.status(root, saga["id"])
            self.assertTrue(inspected["legacyEvidenceContract"])
            gate = self._typed_evidence(root, "gate")
            with self.assertRaisesRegex(ProjectError, "legacy Saga"):
                sagas.attach(root, saga["id"], gate["id"])

    def test_smart_nocturne_plan_accepts_only_typed_trellis_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            command = receipts.record(root, "trellis", "command", "write", {}, {}, True)
            with self.assertRaisesRegex(ProjectError, "gate or test"):
                intelligence.persistence_plan(root, "nocturne", command["id"])
            test_receipt = self._typed_evidence(root, "test")
            with self.assertRaisesRegex(ProjectError, "verified"):
                intelligence.persistence_plan(root, "nocturne", test_receipt["id"])
            verification = receipts.record_verification(root, test_receipt["id"], "targeted tests passed")
            plan = intelligence.persistence_plan(root, "nocturne", test_receipt["id"])
            self.assertEqual(plan["evidenceKind"], "test")
            self.assertEqual(plan["evidenceReceipt"], test_receipt["id"])
            self.assertEqual(plan["verificationReceipt"], verification["id"])


if __name__ == "__main__":
    unittest.main()
