from __future__ import annotations

import hashlib
import json
import multiprocessing
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from importlib.resources import files
from io import StringIO
from pathlib import Path
from queue import Empty
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import (
    capabilities,
    checkpoints,
    host_bridge,
    lifecycle,
    optimization,
    policy_evolution,
    receipts,
    resume,
    transactions,
)
from hellodev.cli import main as cli_main
from hellodev.host_sdk import (
    HostClient,
    HostEnvelopeStaleError,
    HostRequest,
    HostResult,
    HostProtocolError,
    sdk_info,
)
from hellodev.project import ProjectError, init_project


def _recover_worker(root: str, transaction_id: str, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = policy_evolution.recover_transaction(Path(root), transaction_id)
        results.put(("ok", value["transaction"]["state"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


class V121PolishTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        lifecycle.start(root)
        capabilities.refresh(root)
        return root

    def _proposal(self, root: Path) -> str:
        for retries in (2, 3, 4):
            optimization.reflect(root, "code", "L1", "partial", retry_count=retries)
        return optimization.list_proposals(root)["proposals"][0]["id"]

    def _pending_transaction(self, root: Path) -> str:
        proposal = self._proposal(root)
        policy_evolution.stage(root, proposal)
        action = policy_evolution.canary_action(root, proposal, 1, 3_600)
        token = policy_evolution.prepare_authorization(root, action)["approval"]
        with patch("hellodev.receipts.record", side_effect=OSError("stop after token")):
            with self.assertRaises(OSError):
                policy_evolution.authorize(root, action, token)
        return transactions.status(root)["pending"][0]["id"]

    def _run_recovery_processes(self, root: Path, transaction_id: str, workers: int = 4) -> list[tuple]:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(target=_recover_worker, args=(str(root), transaction_id, start, results))
            for _ in range(workers)
        ]
        try:
            for process in processes:
                process.start()
            start.set()
            messages = []
            for _ in processes:
                try:
                    messages.append(results.get(timeout=30))
                except Empty as error:
                    self.fail(f"transaction recovery worker did not report: {error}")
            for process in processes:
                process.join(timeout=30)
                self.assertFalse(process.is_alive(), "transaction recovery worker hung")
                self.assertEqual(process.exitcode, 0)
            return messages
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            results.close()
            results.join_thread()

    def test_receipt_persisted_before_wal_phase_recovers_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal = self._proposal(root)
            policy_evolution.stage(root, proposal)
            action = policy_evolution.canary_action(root, proposal, 1, 3_600)
            token = policy_evolution.prepare_authorization(root, action)["approval"]
            original_append = transactions._append

            def interrupted_append(*args: object, **kwargs: object) -> dict:
                event_type = args[2]
                if event_type == "receipt-recorded":
                    raise OSError("receipt WAL append interrupted")
                return original_append(*args, **kwargs)

            with patch("hellodev.transactions._append", side_effect=interrupted_append):
                with self.assertRaisesRegex(OSError, "receipt WAL append interrupted"):
                    policy_evolution.authorize(root, action, token)

            transaction = transactions.status(root)["pending"][0]
            self.assertEqual(transaction["state"], "token-consumed")
            self.assertEqual(len([item for item in receipts.list_receipts(root) if item["kind"] == "policy"]), 1)
            recovered = policy_evolution.recover_transaction(root, transaction["id"])
            self.assertEqual(recovered["transaction"]["state"], "ledger-applied")
            self.assertEqual(len([item for item in receipts.list_receipts(root) if item["kind"] == "policy"]), 1)
            self.assertEqual(policy_evolution.status(root)["eventCount"], 2)

    def test_concurrent_recovery_is_one_receipt_and_one_policy_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            transaction_id = self._pending_transaction(root)
            messages = self._run_recovery_processes(root, transaction_id)
            self.assertFalse([item for item in messages if item[0] == "error"], messages)
            self.assertEqual({item[1] for item in messages}, {"ledger-applied"})
            self.assertEqual(len([item for item in receipts.list_receipts(root) if item["kind"] == "policy"]), 1)
            self.assertEqual(policy_evolution.status(root)["eventCount"], 2)
            self.assertEqual(transactions.get(root, transaction_id)["state"], "ledger-applied")

    def test_checkpoint_is_strict_bounded_and_ci_match_can_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            checkpoint = checkpoints.export(root)
            invalid = json.loads(json.dumps(checkpoint))
            invalid["headSha256"] = "Z" * 64
            payload = {key: value for key, value in invalid.items() if key != "checkpointSha256"}
            invalid["checkpointSha256"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest()
            with self.assertRaisesRegex(ProjectError, "invalid policy checkpoint head"):
                checkpoints.validate(invalid)

            oversized = root / "oversized-checkpoint.json"
            oversized.write_text("x" * (checkpoints.MAX_CHECKPOINT_BYTES + 1), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "exceeds"):
                checkpoints.load_file(oversized)

            checkpoint_file = root / "checkpoint.json"
            checkpoint_file.write_text(json.dumps(checkpoint), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                matched_exit = cli_main([
                    "--root", str(root), "--json", "policy", "checkpoint", "verify",
                    "--file", str(checkpoint_file), "--require-match",
                ])
            self.assertEqual(matched_exit, 0)
            self.assertTrue(json.loads(output.getvalue())["matched"])

            policy_evolution.stage(root, self._proposal(root))
            output = StringIO()
            with redirect_stdout(output):
                mismatch_exit = cli_main([
                    "--root", str(root), "--json", "policy", "checkpoint", "verify",
                    "--file", str(checkpoint_file), "--require-match",
                ])
            self.assertEqual(mismatch_exit, 2)
            self.assertFalse(json.loads(output.getvalue())["matched"])

    def test_host_sdk_is_typed_and_pending_recovery_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self.assertTrue(files("hellodev").joinpath("py.typed").is_file())
            self.assertTrue(sdk_info()["pep561Typed"])
            client = HostClient(root, ("1.0",))
            envelope = client.prepare(HostRequest("code", total_token_ceiling=2_000))
            schemas = client.schemas()
            self.assertEqual(set(schemas["hostEnvelope"]["required"]), set(envelope.to_wire()))
            self.assertEqual(set(schemas["hostResult"]["required"]), set(HostResult("succeeded").to_wire()))
            decision = resume.next_decision(root)
            self.assertEqual(decision["command"], f"hellodev host pending {envelope.id}")
            pending = client.pending_one(envelope.id)
            self.assertTrue(pending["externalHostContinuationRequired"])
            self.assertEqual(pending["inspectionCommand"], decision["command"])
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    cli_main(["--root", str(root), "--json", "host", "pending", envelope.id]),
                    0,
                )
            self.assertEqual(json.loads(output.getvalue())["id"], envelope.id)
            reconciled = client.reconcile(envelope)
            self.assertEqual(reconciled["state"], "pending")
            self.assertTrue(reconciled["envelopeMatched"])

            completed = client.complete(
                envelope,
                HostResult("succeeded", total_tokens=None, subagent_tokens=None),
            )
            self.assertEqual(completed["state"], "completed")
            self.assertEqual(client.reconcile(envelope)["state"], "completed")

            second = client.prepare(HostRequest("code"))
            self.assertEqual(client.abandon(second.id)["state"], "abandoned")
            self.assertEqual(client.pending_one(second.id)["state"], "abandoned")
            with self.assertRaises(HostProtocolError):
                HostClient(root, ("2.0",))

    def test_reconcile_translates_stale_binding_to_public_sdk_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            client = HostClient(root)
            envelope = client.prepare(HostRequest("code"))
            (root / "AGENTS.md").write_text("changed", encoding="utf-8")
            capabilities.refresh(root)
            with self.assertRaises(HostEnvelopeStaleError):
                client.reconcile(envelope)

    def test_canary_v2_diagnostics_do_not_change_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal = self._proposal(root)
            policy_evolution.stage(root, proposal)
            action = policy_evolution.canary_action(root, proposal, 1, 3_600)
            receipt = policy_evolution.authorize(
                root,
                action,
                policy_evolution.prepare_authorization(root, action)["approval"],
            )
            policy_evolution.start_canary(root, proposal, 1, 3_600, receipt["id"])
            evaluation = policy_evolution.evaluate(root, proposal)
            self.assertEqual(evaluation["state"], "pending")
            self.assertFalse(evaluation["commitEligible"])
            self.assertEqual(evaluation["missingBaselineCompletions"], 1)
            self.assertEqual(evaluation["missingCanaryCompletions"], 1)


if __name__ == "__main__":
    unittest.main()
