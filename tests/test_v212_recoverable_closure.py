from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, closure_transactions, contracts, lifecycle, response_chain, trellis_bridge, verification
from hellodev.application import ProjectClient
from hellodev.project import ProjectError


class V212RecoverableClosureTests(unittest.TestCase):
    def _trellis_work(self, root: Path) -> tuple[ProjectClient, dict[str, object]]:
        (root / ".trellis" / "tasks").mkdir(parents=True)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
        )
        client = ProjectClient(root)
        prepared = client.do("begin", {"goal": "Task", "acceptance": "npm test passes"})
        ready = client.do(
            "begin",
            {
                "goal": "Task",
                "acceptance": "npm test passes",
                "approve": prepared["approval"],
            },
        )
        return client, ready

    def _checking(self, root: Path) -> tuple[ProjectClient, dict[str, object]]:
        client, ready = self._trellis_work(root)
        client.do("work")
        action = client.next()["action"]
        client.do(
            "verify",
            {
                "results": [
                    {
                        "level": "T1",
                        "command": action["hostCommand"],
                        "scope": "code",
                        "outcome": "succeeded",
                    }
                ]
            },
        )
        task_path = root / ".trellis" / "tasks" / str(ready["selectedTask"]) / "task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        acceptance.record_context_validation(
            root,
            str(ready["selectedTask"]),
            trellis_bridge.canonical_sha256(task),
            True,
            "component-protocol",
        )
        client.do("check")
        return client, ready

    def test_finish_before_check_is_read_only_and_discloses_one_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, ready = self._trellis_work(root)
            task_path = root / ".trellis" / "tasks" / str(ready["selectedTask"]) / "task.json"
            receipt_path = root / ".hellodev" / "receipts.json"
            operation_path = root / ".hellodev" / "component-operations.json"
            receipts_before = receipt_path.read_bytes()
            operations_before = operation_path.read_bytes()

            result = client.do("finish")

            self.assertEqual(result["state"], "check-required")
            self.assertEqual(result["reasonCode"], "finish-requires-checking-phase")
            self.assertFalse(result["approvalPrepared"])
            self.assertFalse(result["trellisMutationPerformed"])
            self.assertEqual(result["agentGuidance"]["disclosureLevel"], "repair")
            self.assertIn("nextAction", result)
            self.assertEqual(json.loads(task_path.read_text(encoding="utf-8"))["status"], "in_progress")
            self.assertEqual(receipt_path.read_bytes(), receipts_before)
            self.assertEqual(operation_path.read_bytes(), operations_before)
            self.assertFalse((root / ".hellodev" / "closure-transactions.json").exists())

    def test_native_completion_crash_resumes_without_second_adapter_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, _ = self._checking(root)
            approval = client.do("finish")["trellisCompletion"]["approval"]
            original_transition = lifecycle.transition

            def fail_finished(*args: object, **kwargs: object) -> dict[str, object]:
                if len(args) > 1 and args[1] == "finished":
                    raise RuntimeError("simulated process crash after native completion")
                return original_transition(*args, **kwargs)

            with mock.patch("hellodev.application.lifecycle.transition", side_effect=fail_finished):
                with self.assertRaisesRegex(RuntimeError, "simulated process crash"):
                    client.do("finish", {"approve": approval})

            transaction = closure_transactions.current(root, contracts.current_work_item(root))
            self.assertIsNotNone(transaction)
            self.assertEqual(transaction["state"], "native-completed")
            self.assertEqual(lifecycle.status(root)["phase"], "checking")
            operations_before = json.loads(
                (root / ".hellodev" / "component-operations.json").read_text(encoding="utf-8")
            )

            recovered = client.do("finish")

            operations_after = json.loads(
                (root / ".hellodev" / "component-operations.json").read_text(encoding="utf-8")
            )
            self.assertEqual(operations_after, operations_before)
            self.assertEqual(recovered["lifecycle"]["phase"], "finished")
            self.assertEqual(recovered["closureTransaction"]["state"], "committed")
            self.assertTrue(recovered["trellisCompletion"]["recovered"])
            self.assertFalse(recovered["trellisCompletion"]["executionPerformed"])

    def test_trellis_governance_drift_preserves_verification_but_source_drift_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, ready = self._trellis_work(root)
            client.do("work")
            command = client.next()["action"]["hostCommand"]
            client.do(
                "verify",
                {
                    "level": "T1",
                    "command": command,
                    "scope": "code",
                    "outcome": "succeeded",
                    "current_snapshot": True,
                },
            )
            self.assertEqual(verification.inspect(root, "T1", command, "code")["state"], "reused-success")

            task_dir = root / ".trellis" / "tasks" / str(ready["selectedTask"])
            task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
            task["status"] = "completed"
            (task_dir / "task.json").write_text(json.dumps(task), encoding="utf-8")
            (task_dir / ".gates").mkdir()
            (task_dir / ".gates" / "quality.json").write_text('{"state":"passed"}', encoding="utf-8")
            self.assertEqual(verification.inspect(root, "T1", command, "code")["state"], "reused-success")

            (root / "feature.ts").write_text("export const changed = true\n", encoding="utf-8")
            self.assertNotEqual(verification.inspect(root, "T1", command, "code")["state"], "reused-success")

    def test_legacy_partial_commit_can_reenter_check_and_adopt_unique_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, _ = self._checking(root)
            approval = client.do("finish")["trellisCompletion"]["approval"]
            original_transition = lifecycle.transition

            def fail_finished(*args: object, **kwargs: object) -> dict[str, object]:
                if len(args) > 1 and args[1] == "finished":
                    raise RuntimeError("legacy partial commit")
                return original_transition(*args, **kwargs)

            with mock.patch("hellodev.application.lifecycle.transition", side_effect=fail_finished):
                with self.assertRaisesRegex(RuntimeError, "legacy partial commit"):
                    client.do("finish", {"approve": approval})

            # Recreate the pre-0.21.2 shape: Trellis is completed, the managed
            # lifecycle is still working, and no closure transaction exists.
            (root / ".hellodev" / "closure-transactions.json").unlink()
            lifecycle_path = root / ".hellodev" / "lifecycle.json"
            lifecycle_value = json.loads(lifecycle_path.read_text(encoding="utf-8"))
            lifecycle_value["phase"] = "working"
            lifecycle_path.write_text(json.dumps(lifecycle_value), encoding="utf-8")

            blocked = client.do("finish")
            self.assertEqual(blocked["state"], "check-required")
            self.assertEqual(client.do("check")["lifecycle"]["phase"], "checking")
            recovered = client.do("finish")

            self.assertEqual(recovered["lifecycle"]["phase"], "finished")
            self.assertTrue(recovered["trellisCompletion"]["recovered"])
            self.assertTrue(recovered["closureTransaction"]["legacyAdopted"])
            self.assertEqual(recovered["closureTransaction"]["state"], "committed")

    def test_commit_crash_recovers_after_current_pointer_was_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client, _ = self._checking(root)
            approval = client.do("finish")["trellisCompletion"]["approval"]
            with mock.patch(
                "hellodev.application.closure_transactions.commit",
                side_effect=RuntimeError("simulated crash before transaction commit"),
            ):
                with self.assertRaisesRegex(RuntimeError, "before transaction commit"):
                    client.do("finish", {"approve": approval})

            self.assertEqual(lifecycle.status(root)["phase"], "finished")
            self.assertIsNone(contracts.current_work_item(root))
            pending = closure_transactions.current(root)
            self.assertEqual(pending["state"], "lifecycle-finished")
            operations_before = (root / ".hellodev" / "component-operations.json").read_bytes()

            recovered = client.do("finish")

            self.assertEqual(recovered["state"], "recovered-finished")
            self.assertEqual(recovered["closureTransaction"]["state"], "committed")
            self.assertEqual(
                (root / ".hellodev" / "component-operations.json").read_bytes(), operations_before
            )

    def test_bare_verify_is_a_bounded_project_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = ProjectClient(Path(directory))
            client.do("begin", {"goal": "Task", "acceptance": "tests pass"})
            with self.assertRaisesRegex(ProjectError, "requires level and command"):
                client.do("verify")

    def test_guidance_is_disclosed_only_for_confirmation_repair_or_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ordinary = response_chain.attach(root, {"state": "ready", "next": "hellodev do work"})
            confirmation = response_chain.attach(
                root,
                {
                    "state": "awaiting-confirmation",
                    "resumeCommand": "hellodev do finish --approve token",
                    "nextAction": {"command": "hellodev do finish --approve token"},
                },
            )
            diagnostic = response_chain.attach(
                root,
                {"state": "recovery-required", "reasonCode": "closure-transaction-recovery-required"},
            )

            self.assertNotIn("agentGuidance", ordinary)
            self.assertEqual(confirmation["agentGuidance"]["disclosureLevel"], "confirmation")
            self.assertEqual(diagnostic["agentGuidance"]["disclosureLevel"], "diagnostic")
            self.assertEqual(len(diagnostic["agentGuidance"]["diagnosticCommands"]), 3)
            self.assertIn("stop changing state", diagnostic["agentGuidance"]["instruction"])


if __name__ == "__main__":
    unittest.main()
