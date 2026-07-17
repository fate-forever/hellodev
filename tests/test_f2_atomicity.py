from __future__ import annotations

import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path
from queue import Empty


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, contracts, governance, host_bridge, optimization, policy_evolution, receipts, sagas
from hellodev.project import init_project


def _create_work(root: str, native_ref: str, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = contracts.create_work_item(Path(root), "trellis", native_ref, make_current=False)
        results.put(("ok", value["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _create_saga(root: str, index: int, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = sagas.create(Path(root), f"Concurrent Saga {index}")
        results.put(("ok", value["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _create_receipt(root: str, index: int, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = receipts.record(Path(root), "trellis", "status", "read", {"index": index}, {}, True)
        results.put(("ok", value["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _create_lesson(root: str, index: int, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = contracts.create_lesson_proposal(
            Path(root), f"Concurrent lesson {index}", "project", "trellis", state="project-plan"
        )
        results.put(("ok", value["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _reconcile(root: str, receipt_id: str, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = contracts.reconcile_evidence(Path(root), receipt_id)
        results.put(("ok", value["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _record_usage(root: str, index: int, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = governance.record_usage(Path(root), 100 + index, index, 1, "atomicity", f"turn-{index}")
        results.put(("ok", value["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _reflect(root: str, retry_count: int, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = optimization.reflect(Path(root), "code", "L1", "partial", retry_count=retry_count)
        results.put(("ok", value["trace"]["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _complete_host(root: str, envelope: dict, result: dict, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = host_bridge.complete(Path(root), envelope, result)
        results.put(("ok", value["completion"]["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


def _stage_policy(root: str, proposal_id: str, start: object, results: object) -> None:
    start.wait(20)
    try:
        value = policy_evolution.stage(Path(root), proposal_id)
        results.put(("ok", value["event"]["id"]))
    except BaseException as error:  # pragma: no cover - reported to parent
        results.put(("error", repr(error)))


class F2AtomicityTests(unittest.TestCase):
    def _run(self, target: object, arguments: list[tuple], *, allow_errors: bool = False) -> list[tuple]:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [context.Process(target=target, args=(*items, start, results)) for items in arguments]
        try:
            for process in processes:
                process.start()
            start.set()
            messages = []
            for _ in processes:
                try:
                    messages.append(results.get(timeout=30))
                except Empty as error:
                    self.fail(f"F2 atomicity worker did not report: {error}")
            for process in processes:
                process.join(timeout=30)
                self.assertFalse(process.is_alive(), "F2 atomicity worker hung")
                self.assertEqual(process.exitcode, 0)
            if not allow_errors:
                self.assertFalse([message for message in messages if message[0] == "error"], messages)
            return messages
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            results.close()
            results.join_thread()

    def test_concurrent_f2_creates_preserve_records_and_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            task_names = [f"07-16-work-{index}" for index in range(6)]
            for name in task_names:
                (root / ".trellis" / "tasks" / name).mkdir(parents=True)
            capabilities.refresh(root)

            work = self._run(_create_work, [(str(root), name) for name in task_names])
            saga = self._run(_create_saga, [(str(root), index) for index in range(6)])
            receipt = self._run(_create_receipt, [(str(root), index) for index in range(6)])
            lesson = self._run(_create_lesson, [(str(root), index) for index in range(6)])

            for messages in (work, saga, receipt, lesson):
                identifiers = [message[1] for message in messages]
                self.assertEqual(len(identifiers), len(set(identifiers)))
            self.assertEqual(len(contracts.list_work_items(root)), 6)
            self.assertEqual(len(sagas.list_sagas(root)), 6)
            self.assertEqual(len(receipts.list_receipts(root)), 6)
            self.assertEqual(len(contracts.list_lesson_proposals(root)), 6)

    def test_concurrent_evidence_reconciliation_preserves_every_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            (root / ".trellis" / "tasks" / "07-16-current").mkdir(parents=True)
            capabilities.refresh(root)
            contracts.create_work_item(root, "trellis", "07-16-current")
            binding = contracts.evidence_binding(root)
            evidence = [
                receipts.record(
                    root,
                    "trellis",
                    "quality-gate",
                    "read",
                    {"index": index},
                    {},
                    True,
                    kind="gate",
                    evidence_binding=binding,
                )
                for index in range(6)
            ]
            messages = self._run(_reconcile, [(str(root), item["id"]) for item in evidence])
            identifiers = [message[1] for message in messages]
            self.assertEqual(len(identifiers), len(set(identifiers)))
            self.assertEqual(len(contracts.list_evidence_links(root)), 6)

    def test_concurrent_usage_and_reflection_preserve_unique_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            usage = self._run(_record_usage, [(str(root), index) for index in range(6)])
            traces = self._run(_reflect, [(str(root), index + 1) for index in range(6)])
            for messages in (usage, traces):
                identifiers = [message[1] for message in messages]
                self.assertEqual(len(identifiers), len(set(identifiers)))
            self.assertEqual(governance.usage_status(root)["records"], 6)
            optimized = optimization.status(root)
            self.assertEqual(optimized["traceCount"], 6)
            self.assertEqual(optimized["reportCount"], 6)
            self.assertEqual(optimized["proposalCount"], 1)

    def test_concurrent_host_completion_and_policy_stage_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            capabilities.refresh(root)
            envelopes = [host_bridge.prepare(root, "code", total_token_ceiling=2_000) for _ in range(6)]
            result = {
                "outcome": "succeeded",
                "retryCount": 0,
                "retrievalMode": "none",
                "delegationMode": "none",
                "totalTokens": 1_000,
                "subagentTokens": 0,
                "subagentCount": 0,
            }
            completed = self._run(
                _complete_host,
                [(str(root), envelope, result) for envelope in envelopes],
            )
            completion_ids = [message[1] for message in completed]
            self.assertEqual(len(completion_ids), len(set(completion_ids)))
            self.assertEqual(host_bridge.status(root)["completionCount"], 6)

            for retries in (2, 3, 4):
                optimization.reflect(root, "code", "L1", "partial", retry_count=retries)
            proposal_id = optimization.list_proposals(root)["proposals"][0]["id"]
            staged = self._run(_stage_policy, [(str(root), proposal_id) for _ in range(6)])
            self.assertEqual(set(message[1] for message in staged), {"policy-event-0001"})
            self.assertEqual(policy_evolution.status(root)["eventCount"], 1)

    def test_canary_turn_limit_is_enforced_inside_completion_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            capabilities.refresh(root)
            for retries in (2, 3, 4):
                optimization.reflect(root, "code", "L1", "partial", retry_count=retries)
            proposal_id = optimization.list_proposals(root)["proposals"][0]["id"]
            policy_evolution.stage(root, proposal_id)
            action = policy_evolution.canary_action(root, proposal_id, 1, 3_600)
            token = policy_evolution.prepare_authorization(root, action)["approval"]
            receipt_id = policy_evolution.authorize(root, action, token)["id"]
            policy_evolution.start_canary(root, proposal_id, 1, 3_600, receipt_id)

            envelopes = [host_bridge.prepare(root, "code", total_token_ceiling=2_000) for _ in range(2)]
            result = {
                "outcome": "succeeded",
                "retryCount": 0,
                "retrievalMode": "none",
                "delegationMode": "none",
                "totalTokens": 1_000,
                "subagentTokens": 0,
                "subagentCount": 0,
            }
            messages = self._run(
                _complete_host,
                [(str(root), envelope, result) for envelope in envelopes],
                allow_errors=True,
            )

            completed = [message for message in messages if message[0] == "ok"]
            rejected = [message for message in messages if message[0] == "error"]
            self.assertEqual(len(completed), 1, messages)
            self.assertEqual(len(rejected), 1, messages)
            self.assertIn("bindings are stale", rejected[0][1])
            self.assertEqual(host_bridge.status(root)["completionCount"], 1)
            canary = policy_evolution.status(root)["activeCanary"]
            self.assertTrue(canary["exhausted"])
            self.assertEqual(canary["observedTurns"], 1)


if __name__ == "__main__":
    unittest.main()
