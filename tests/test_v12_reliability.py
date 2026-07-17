from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import (
    audit,
    capabilities,
    checkpoints,
    gates,
    host_bridge,
    lifecycle,
    optimization,
    policy_evolution,
    resume,
    transactions,
)
from hellodev.cli import _doctor
from hellodev.host_sdk import HostClient, HostRequest, HostResult
from hellodev.project import ProjectError, ProjectPaths, init_project


class V12ReliabilityTests(unittest.TestCase):
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

    def _result(self, *, retries: int = 0, total: int | None = 1_000) -> dict[str, object]:
        return {
            "outcome": "succeeded",
            "retryCount": retries,
            "retrievalMode": "none",
            "delegationMode": "none",
            "totalTokens": total,
            "subagentTokens": None if total is None else 0,
            "subagentCount": 0,
        }

    def _prepared_policy(self, root: Path) -> tuple[str, dict[str, object], str]:
        proposal = self._proposal(root)
        policy_evolution.stage(root, proposal)
        action = policy_evolution.canary_action(root, proposal, 1, 3_600)
        token = policy_evolution.prepare_authorization(root, action)["approval"]
        return proposal, action, token

    def _baseline(self, root: Path, count: int = 1, *, retries: int = 0, total: int | None = 1_000) -> None:
        for _ in range(count):
            envelope = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
            host_bridge.complete(root, envelope, self._result(retries=retries, total=total))

    def test_wal_failure_before_write_preserves_same_approval_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal, action, token = self._prepared_policy(root)
            with patch("hellodev.transactions.write_json", side_effect=OSError("disk unavailable")):
                with self.assertRaisesRegex(OSError, "disk unavailable"):
                    policy_evolution.authorize(root, action, token)
            self.assertEqual(transactions.status(root)["pendingCount"], 0)
            receipt = policy_evolution.authorize(root, action, token)
            applied = policy_evolution.start_canary(root, proposal, 1, 3_600, receipt["id"])
            self.assertEqual(applied["transaction"]["state"], "ledger-applied")

    def test_crash_after_wal_before_token_store_recovers_without_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            _, action, token = self._prepared_policy(root)
            with patch("hellodev.approval.write_json", side_effect=OSError("power loss")):
                with self.assertRaisesRegex(OSError, "power loss"):
                    policy_evolution.authorize(root, action, token)
            pending = transactions.status(root)["pending"][0]
            self.assertEqual(pending["state"], "authorized")
            recovered = policy_evolution.recover_transaction(root, pending["id"])
            self.assertEqual(recovered["state"], "recovered")
            self.assertFalse(recovered["newAuthorizationRequired"])
            state_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in ProjectPaths(root).state_dir.rglob("*.json")
                if path.is_file() and not path.is_symlink()
            )
            self.assertNotIn(token, state_text)

    def test_crash_after_token_before_receipt_recovers_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            _, action, token = self._prepared_policy(root)
            with patch("hellodev.receipts.record", side_effect=OSError("receipt write interrupted")):
                with self.assertRaisesRegex(OSError, "receipt write interrupted"):
                    policy_evolution.authorize(root, action, token)
            pending = transactions.status(root)["pending"][0]
            self.assertEqual(pending["state"], "token-consumed")
            first = policy_evolution.recover_transaction(root, pending["id"])
            second = policy_evolution.recover_transaction(root, pending["id"])
            self.assertEqual(first["state"], "recovered")
            self.assertEqual(second["state"], "recovered")

    def test_crash_after_ledger_before_wal_completion_recovers_existing_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal, action, token = self._prepared_policy(root)
            receipt = policy_evolution.authorize(root, action, token)
            with patch("hellodev.transactions.mark_ledger_applied", side_effect=OSError("process interrupted")):
                with self.assertRaisesRegex(OSError, "process interrupted"):
                    policy_evolution.start_canary(root, proposal, 1, 3_600, receipt["id"])
            self.assertEqual(policy_evolution.status(root)["state"], "canary-active")
            pending = transactions.status(root)["pending"][0]
            self.assertEqual(pending["state"], "receipt-recorded")
            recovered = policy_evolution.recover_transaction(root, pending["id"])
            self.assertEqual(recovered["transaction"]["state"], "ledger-applied")

    def test_resume_prioritizes_one_transaction_recovery_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            _, action, token = self._prepared_policy(root)
            with patch("hellodev.receipts.record", side_effect=OSError("stop")):
                with self.assertRaises(OSError):
                    policy_evolution.authorize(root, action, token)
            decision = resume.next_decision(root)
            self.assertEqual(decision["reasonCode"], "policy-transaction-recovery-required")
            self.assertEqual(decision["command"], transactions.status(root)["nextRecoveryCommand"])
            self.assertEqual(len(audit.fix_hints(root)["commands"]), 1)

    def test_host_sdk_negotiates_types_schemas_and_pending_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            client = HostClient(root, ("1.1", "1.0"))
            schemas = client.schemas()
            self.assertEqual(client.protocol_version, "1.0")
            self.assertEqual(set(schemas), {"hostEnvelope", "hostResult", "hostProtocol"})
            envelope = client.prepare(HostRequest("code", total_token_ceiling=2_000))
            self.assertEqual(resume.next_decision(root)["reasonCode"], "host-envelope-pending")
            self.assertEqual(client.pending()[0]["id"], envelope.id)
            completed = client.complete(envelope, HostResult("succeeded", total_tokens=1_000, subagent_tokens=0))
            self.assertEqual(completed["state"], "completed")
            self.assertEqual(client.pending(), [])
            with self.assertRaisesRegex(ProjectError, "no compatible"):
                HostClient(root, ("2.0",))

    def test_canary_v2_requires_baseline_and_rejects_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal = self._proposal(root)
            policy_evolution.stage(root, proposal)
            action = policy_evolution.canary_action(root, proposal, 1, 3_600)
            receipt = policy_evolution.authorize(root, action, policy_evolution.prepare_authorization(root, action)["approval"])
            policy_evolution.start_canary(root, proposal, 1, 3_600, receipt["id"])
            host_bridge.complete(root, host_bridge.prepare(root, "code"), self._result())
            insufficient = policy_evolution.evaluate(root, proposal)
            self.assertEqual(insufficient["evaluationVersion"], 2)
            self.assertEqual(insufficient["reasonCode"], "insufficient-baseline-completions")
            with self.assertRaisesRegex(ProjectError, "not ready to commit"):
                policy_evolution.commit_action(root, proposal)

        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self._baseline(root, retries=0)
            proposal = self._proposal(root)
            policy_evolution.stage(root, proposal)
            action = policy_evolution.canary_action(root, proposal, 1, 3_600)
            receipt = policy_evolution.authorize(root, action, policy_evolution.prepare_authorization(root, action)["approval"])
            policy_evolution.start_canary(root, proposal, 1, 3_600, receipt["id"])
            host_bridge.complete(root, host_bridge.prepare(root, "code"), self._result(retries=1))
            regressed = policy_evolution.evaluate(root, proposal)
            self.assertEqual(regressed["reasonCode"], "canary-regressed-against-baseline")
            self.assertIn("retry-average-regressed", regressed["regressions"])

    def test_canary_v2_passes_bounded_host_asserted_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            self._baseline(root, retries=1, total=1_200)
            proposal = self._proposal(root)
            policy_evolution.stage(root, proposal)
            action = policy_evolution.canary_action(root, proposal, 1, 3_600)
            receipt = policy_evolution.authorize(root, action, policy_evolution.prepare_authorization(root, action)["approval"])
            policy_evolution.start_canary(root, proposal, 1, 3_600, receipt["id"])
            host_bridge.complete(root, host_bridge.prepare(root, "code"), self._result(retries=0, total=1_000))
            evaluation = policy_evolution.evaluate(root, proposal)
            self.assertEqual(evaluation["state"], "passed")
            self.assertTrue(evaluation["evidenceSufficient"])
            self.assertEqual(evaluation["comparison"]["tokenTrust"], "host-asserted-not-provider-verified")
            self.assertEqual(evaluation["comparison"]["averageTokenDelta"], -200)

    def test_portable_checkpoint_detects_divergence_and_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            checkpoint = checkpoints.export(root)
            self.assertTrue(checkpoints.verify(root, checkpoint)["matched"])
            checkpoints.save(root)
            proposal = self._proposal(root)
            policy_evolution.stage(root, proposal)
            self.assertEqual(checkpoints.status(root)["state"], "mismatch")
            self.assertFalse(checkpoints.verify(root, checkpoint)["matched"])
            tampered = json.loads(json.dumps(checkpoint))
            tampered["headSha256"] = "0" * 64
            with self.assertRaisesRegex(ProjectError, "digest mismatch"):
                checkpoints.verify(root, tampered)

    def test_doctor_gate_audit_expose_compatibility_without_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            task = root / ".trellis" / "tasks" / "07-17-v12"
            task.mkdir(parents=True)
            (task / "prd.md").write_text("PRIVATE-TASK-CONTENT", encoding="utf-8")
            capabilities.refresh(root)
            from hellodev import contracts

            contracts.create_work_item(root, "trellis", task.name)
            for phase in ("planned", "working", "checking", "finished"):
                lifecycle.transition(root, phase)
            gate = gates.status(root)
            self.assertEqual(gate["lifecycleConsistency"]["state"], "attention")
            checks = {item["name"]: item for item in _doctor(root)["checks"]}
            self.assertEqual(checks["host-sdk"]["state"], "ok")
            self.assertEqual(checks["trellis-compatibility"]["state"], "ok")
            self.assertEqual(checks["nocturne-compatibility"]["state"], "ok")
            exported = audit.export(root)
            self.assertEqual(exported["schemaVersion"], 2)
            self.assertEqual(exported["hostProtocol"]["selectedVersion"], "1.0")
            serialized = json.dumps(exported)
            self.assertNotIn("PRIVATE-TASK-CONTENT", serialized)
            self.assertNotIn("APPROVE-", serialized)
            self.assertNotIn('"totalTokens"', serialized)
            self.assertNotIn('"rootTokens"', serialized)
            self.assertNotIn('"subagentTokens"', serialized)
            self.assertFalse(exported["usage"]["tokenValuesIncluded"])


if __name__ == "__main__":
    unittest.main()
