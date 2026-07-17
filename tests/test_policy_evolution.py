from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, drift, host_bridge, lifecycle, optimization, policy_evolution, receipts
from hellodev.project import ProjectError, ProjectPaths, init_project


class PolicyEvolutionTests(unittest.TestCase):
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

    def _authorize(self, root: Path, action: dict[str, object]) -> str:
        token = policy_evolution.prepare_authorization(root, action)["approval"]
        return policy_evolution.authorize(root, action, token)["id"]

    def _result(self, retry_count: int = 1, subagents: int = 0, outcome: str = "succeeded") -> dict[str, object]:
        return {
            "outcome": outcome,
            "retryCount": retry_count,
            "retrievalMode": "none",
            "delegationMode": "none" if subagents == 0 else "executed",
            "totalTokens": 1_000,
            "subagentTokens": 0 if subagents == 0 else 300,
            "subagentCount": subagents,
        }

    def test_missing_policy_is_read_only_and_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            value = policy_evolution.status(root)
            self.assertEqual(value["state"], "default")
            self.assertEqual(value["effectivePolicy"]["retry.maxAttempts"], 3)
            self.assertEqual(value["ledgerHead"]["eventSha256"], "GENESIS")
            self.assertFalse(ProjectPaths(root).evolution_policy_file.exists())
            self.assertIn("external checkpoint", value["integrity"]["guarantee"])

    def test_stage_is_tighten_only_and_does_not_change_effective_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            staged = policy_evolution.stage(root, proposal_id)
            status = policy_evolution.status(root)
            self.assertEqual(staged["state"], "staged")
            self.assertEqual(status["state"], "staged")
            self.assertEqual(status["effectivePolicy"], policy_evolution.DEFAULT_POLICY)
            self.assertIsNone(staged["event"]["authorizationReceiptId"])
            self.assertNotIn("APPROVE-", ProjectPaths(root).evolution_policy_file.read_text(encoding="utf-8"))

    def test_staged_proposal_can_be_cancelled_without_policy_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            cancelled = policy_evolution.cancel_stage(root, proposal_id)
            repeated = policy_evolution.cancel_stage(root, proposal_id)
            status = policy_evolution.status(root)
            self.assertEqual(cancelled["state"], "stage-cancelled")
            self.assertEqual(repeated["state"], "existing")
            self.assertEqual(status["state"], "stage-cancelled")
            self.assertEqual(status["effectivePolicy"], policy_evolution.DEFAULT_POLICY)
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 1, 3_600)
            policy_evolution.start_canary(root, proposal_id, 1, 3_600, self._authorize(root, action))
            with self.assertRaisesRegex(ProjectError, "active canary"):
                policy_evolution.cancel_stage(root, proposal_id)

    def test_canary_requires_exact_non_replayable_policy_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 3, 3_600)
            token = policy_evolution.prepare_authorization(root, action)["approval"]
            wrong = json.loads(json.dumps(action))
            wrong["canary"]["turnLimit"] = 4
            with self.assertRaisesRegex(ProjectError, "invalid, already consumed"):
                policy_evolution.authorize(root, wrong, token)
            receipt = policy_evolution.authorize(root, action, token)
            with self.assertRaisesRegex(ProjectError, "invalid, already consumed"):
                policy_evolution.authorize(root, action, token)
            started = policy_evolution.start_canary(root, proposal_id, 3, 3_600, receipt["id"])
            self.assertEqual(started["state"], "canary-active")
            self.assertEqual(started["event"]["authorizationReceiptId"], receipt["id"])
            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in ProjectPaths(root).state_dir.rglob("*.json")
                if path.is_file()
            )
            self.assertNotIn(token, persisted)

    def test_policy_receipt_preflight_does_not_consume_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 1, 3_600)
            token = policy_evolution.prepare_authorization(root, action)["approval"]
            receipt_path = ProjectPaths(root).receipts_file
            receipt_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "receipt store"):
                policy_evolution.authorize(root, action, token)
            receipt_path.unlink()
            receipt = policy_evolution.authorize(root, action, token)
            self.assertEqual(receipts.get(root, receipt["id"]), receipt)

    def test_canary_turn_limit_exhausts_runtime_overlay_and_stales_prepared_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 1, 3_600)
            receipt_id = self._authorize(root, action)
            policy_evolution.start_canary(root, proposal_id, 1, 3_600, receipt_id)

            first = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
            preprepared = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
            completed = host_bridge.complete(root, first, self._result())
            repeated = host_bridge.complete(root, first, self._result())
            self.assertEqual(repeated["state"], "existing")
            self.assertEqual(repeated["completion"]["id"], completed["completion"]["id"])

            status = policy_evolution.status(root)
            self.assertEqual(status["state"], "canary-exhausted")
            self.assertTrue(status["activeCanary"]["exhausted"])
            self.assertEqual(status["activeCanary"]["observedTurns"], 1)
            self.assertEqual(status["effectivePolicy"], status["committedPolicy"])
            with self.assertRaisesRegex(ProjectError, "bindings are stale"):
                host_bridge.complete(root, preprepared, self._result())

            after = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
            self.assertEqual(after["usagePlan"]["retryMaxAttempts"], 3)
            host_bridge.complete(root, after, self._result())
            exhausted = policy_evolution.status(root)
            self.assertTrue(exhausted["activeCanary"]["exhausted"])
            self.assertEqual(exhausted["activeCanary"]["observedTurns"], 1)
            evaluation = policy_evolution.evaluate(root, proposal_id)
            self.assertEqual(evaluation["state"], "passed")
            self.assertEqual(evaluation["observedCompletions"], 1)

    def test_canary_commit_cancelled_stage_and_immediate_revert_form_a_verified_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 3, 3_600)
            canary_receipt = self._authorize(root, action)
            started = policy_evolution.start_canary(root, proposal_id, 3, 3_600, canary_receipt)
            self.assertEqual(
                policy_evolution.start_canary(root, proposal_id, 3, 3_600, canary_receipt)["state"],
                "existing",
            )
            for _ in range(3):
                envelope = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
                host_bridge.complete(root, envelope, self._result())
            evaluation = policy_evolution.evaluate(root, proposal_id)
            self.assertEqual(evaluation["state"], "passed")
            self.assertEqual(evaluation["usageTrust"], ["host-asserted"])

            commit_action = policy_evolution.commit_action(root, proposal_id)
            commit_receipt = self._authorize(root, commit_action)
            committed = policy_evolution.commit(root, proposal_id, commit_receipt)
            self.assertEqual(policy_evolution.commit(root, proposal_id, commit_receipt)["state"], "existing")
            self.assertEqual(committed["state"], "committed")
            self.assertEqual(policy_evolution.status(root)["effectivePolicy"]["retry.maxAttempts"], 2)

            for retries in (2, 3, 4):
                optimization.reflect(root, "code", "L1", "partial", retry_count=retries)
            next_proposal_id = next(
                item["id"]
                for item in reversed(optimization.list_proposals(root)["proposals"])
                if not item["stale"]
            )
            policy_evolution.stage(root, next_proposal_id)
            policy_evolution.cancel_stage(root, next_proposal_id)

            revert_action = policy_evolution.revert_action(root)
            revert_receipt = self._authorize(root, revert_action)
            reverted = policy_evolution.revert(root, revert_receipt)
            self.assertEqual(policy_evolution.revert(root, revert_receipt)["state"], "existing")
            self.assertEqual(reverted["state"], "reverted")
            self.assertEqual(policy_evolution.status(root)["effectivePolicy"]["retry.maxAttempts"], 3)
            with self.assertRaisesRegex(ProjectError, "no active canary"):
                policy_evolution.revert_action(root)

    def test_failed_canary_cannot_commit_and_can_be_reverted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 1, 3_600)
            policy_evolution.start_canary(root, proposal_id, 1, 3_600, self._authorize(root, action))
            envelope = host_bridge.prepare(root, "code", max_subagents=2)
            host_bridge.complete(root, envelope, self._result(retry_count=3))
            evaluation = policy_evolution.evaluate(root, proposal_id)
            self.assertEqual(evaluation["state"], "failed")
            self.assertEqual(evaluation["violations"][0]["reasonCode"], "retry-policy-exceeded")
            with self.assertRaisesRegex(ProjectError, "not ready to commit"):
                policy_evolution.commit_action(root, proposal_id)
            revert_action = policy_evolution.revert_action(root)
            policy_evolution.revert(root, self._authorize(root, revert_action))
            self.assertEqual(policy_evolution.status(root)["state"], "reverted")

    def test_revert_restores_only_the_latest_commit_and_cannot_cross_two_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            first_proposal_id = self._proposal(root)
            policy_evolution.stage(root, first_proposal_id)
            first_canary = policy_evolution.canary_action(root, first_proposal_id, 1, 3_600)
            policy_evolution.start_canary(
                root,
                first_proposal_id,
                1,
                3_600,
                self._authorize(root, first_canary),
            )
            host_bridge.complete(root, host_bridge.prepare(root, "code", total_token_ceiling=2_000), self._result())
            first_commit = policy_evolution.commit_action(root, first_proposal_id)
            policy_evolution.commit(root, first_proposal_id, self._authorize(root, first_commit))
            self.assertEqual(policy_evolution.status(root)["committedPolicy"]["retry.maxAttempts"], 2)

            for retries in (2, 3, 4):
                optimization.reflect(root, "code", "L1", "partial", retry_count=retries)
            second_proposal_id = next(
                item["id"]
                for item in reversed(optimization.list_proposals(root)["proposals"])
                if not item["stale"]
            )
            policy_evolution.stage(root, second_proposal_id)
            second_canary = policy_evolution.canary_action(root, second_proposal_id, 1, 3_600)
            policy_evolution.start_canary(
                root,
                second_proposal_id,
                1,
                3_600,
                self._authorize(root, second_canary),
            )
            host_bridge.complete(root, host_bridge.prepare(root, "code", total_token_ceiling=2_000), self._result())
            second_commit = policy_evolution.commit_action(root, second_proposal_id)
            policy_evolution.commit(root, second_proposal_id, self._authorize(root, second_commit))
            self.assertEqual(policy_evolution.status(root)["committedPolicy"]["retry.maxAttempts"], 1)

            revert_action = policy_evolution.revert_action(root)
            policy_evolution.revert(root, self._authorize(root, revert_action))
            self.assertEqual(policy_evolution.status(root)["committedPolicy"]["retry.maxAttempts"], 2)
            with self.assertRaisesRegex(ProjectError, "no active canary"):
                policy_evolution.revert_action(root)

    def test_hash_chain_and_receipt_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            proposal_id = self._proposal(root)
            policy_evolution.stage(root, proposal_id)
            path = ProjectPaths(root).evolution_policy_file
            store = json.loads(path.read_text(encoding="utf-8"))
            store["events"][0]["patches"][0]["toValue"] = 1
            path.write_text(json.dumps(store), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "hash mismatch"):
                policy_evolution.status(root)
            audited = drift.status(root)
            self.assertEqual(audited["state"], "invalid")
            self.assertEqual(audited["reasonCode"], "policy-ledger-invalid")

    def test_drift_is_unavailable_clean_detected_and_checkpoint_aware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            missing = drift.status(root)
            self.assertEqual(missing["state"], "unavailable")
            self.assertEqual(missing["runtimeState"], "unavailable")

            envelope = host_bridge.prepare(root, "code", total_token_ceiling=2_000)
            host_bridge.complete(root, envelope, self._result())
            clean = drift.status(root)
            self.assertEqual(clean["state"], "clean")
            self.assertEqual(clean["counts"]["assertedUsage"], 1)

            mismatch = drift.status(root, "0" * 64)
            self.assertEqual(mismatch["state"], "detected")
            self.assertFalse(mismatch["expectedHeadMatched"])
            self.assertIn("cannot detect a full rewrite", mismatch["integrityGuarantee"])


if __name__ == "__main__":
    unittest.main()
