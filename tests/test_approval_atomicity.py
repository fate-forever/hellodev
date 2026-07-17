from __future__ import annotations

import json
import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import approval
from hellodev.project import ProjectError, ProjectPaths, init_project


def _process_prepare(root: str, index: int, start: object, results: object) -> None:
    start.wait(20)
    try:
        prepared = approval.prepare(Path(root), {"index": index}, "read")
        results.put(("prepared", index, prepared["approval"]))
    except BaseException as error:  # pragma: no cover - reported to the parent
        results.put(("error", index, repr(error)))


def _process_consume(root: str, payload: dict, token: str, start: object, results: object) -> None:
    start.wait(20)
    try:
        approval.consume(Path(root), payload, token, "read")
        results.put(("consumed", None, None))
    except ProjectError as error:
        results.put(("rejected", None, str(error)))
    except BaseException as error:  # pragma: no cover - reported to the parent
        results.put(("error", None, repr(error)))


class ApprovalAtomicityTests(unittest.TestCase):
    def _run_processes(self, target: object, arguments: list[tuple]) -> list[tuple]:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(target=target, args=(*items, start, results))
            for items in arguments
        ]
        try:
            for process in processes:
                process.start()
            start.set()
            messages: list[tuple] = []
            for _ in processes:
                try:
                    messages.append(results.get(timeout=30))
                except Empty as error:
                    self.fail(f"concurrent approval worker did not report a result: {error}")
            for process in processes:
                process.join(timeout=30)
                self.assertFalse(process.is_alive(), "concurrent approval worker hung")
                self.assertEqual(process.exitcode, 0)
            return messages
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            results.close()
            results.join_thread()

    def test_threaded_prepare_preserves_every_plan_and_token_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            workers = 16
            prepare_barrier = threading.Barrier(workers)

            def prepare_one(index: int) -> dict:
                prepare_barrier.wait(timeout=10)
                return approval.prepare(root, {"index": index}, "read")

            with ThreadPoolExecutor(max_workers=workers) as executor:
                prepared = list(executor.map(prepare_one, range(workers)))

            store = json.loads(ProjectPaths(root).approvals_file.read_text(encoding="utf-8"))
            self.assertEqual(len(store["plans"]), workers)
            self.assertEqual(len({item["approval"] for item in prepared}), workers)

            payload = {"index": 0}
            token = prepared[0]["approval"]
            consume_barrier = threading.Barrier(workers)

            def consume_once(_: int) -> str:
                consume_barrier.wait(timeout=10)
                try:
                    approval.consume(root, payload, token, "read")
                    return "consumed"
                except ProjectError:
                    return "rejected"

            with ThreadPoolExecutor(max_workers=workers) as executor:
                outcomes = list(executor.map(consume_once, range(workers)))
            self.assertEqual(outcomes.count("consumed"), 1)
            self.assertEqual(outcomes.count("rejected"), workers - 1)

    def test_process_prepare_preserves_every_plan_and_token_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            workers = 6
            prepared = self._run_processes(
                _process_prepare,
                [(str(root), index) for index in range(workers)],
            )
            self.assertFalse([item for item in prepared if item[0] == "error"], prepared)
            store = json.loads(ProjectPaths(root).approvals_file.read_text(encoding="utf-8"))
            self.assertEqual(len(store["plans"]), workers)

            token_by_index = {index: token for state, index, token in prepared if state == "prepared"}
            self.assertEqual(len(token_by_index), workers)
            outcomes = self._run_processes(
                _process_consume,
                [(str(root), {"index": 0}, token_by_index[0]) for _ in range(workers)],
            )
            self.assertFalse([item for item in outcomes if item[0] == "error"], outcomes)
            self.assertEqual(sum(item[0] == "consumed" for item in outcomes), 1)
            self.assertEqual(sum(item[0] == "rejected" for item in outcomes), workers - 1)

    def test_prepare_refuses_symlinked_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            init_project(root)
            target = Path(outside) / "approvals.json"
            target.write_text('{"schemaVersion":1,"plans":[]}', encoding="utf-8")
            store_path = ProjectPaths(root).approvals_file
            try:
                os.symlink(target, store_path)
            except OSError:
                original_is_symlink = Path.is_symlink
                with patch.object(
                    Path,
                    "is_symlink",
                    lambda candidate: candidate == store_path or original_is_symlink(candidate),
                ):
                    with self.assertRaisesRegex(ProjectError, "symlinked HelloDev approval store"):
                        approval.prepare(root, {"operation": "read"}, "read")
            else:
                with self.assertRaisesRegex(ProjectError, "symlinked HelloDev approval store"):
                    approval.prepare(root, {"operation": "read"}, "read")

    def test_prepare_refuses_symlinked_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            init_project(root)
            target = Path(outside) / "approval.lock"
            target.write_bytes(b"\0")
            store_path = ProjectPaths(root).approvals_file
            lock_path = store_path.with_name(f"{store_path.name}.lock")
            try:
                os.symlink(target, lock_path)
            except OSError:
                original_is_symlink = Path.is_symlink
                with patch.object(
                    Path,
                    "is_symlink",
                    lambda candidate: candidate == lock_path or original_is_symlink(candidate),
                ):
                    with self.assertRaisesRegex(ProjectError, "symlinked HelloDev approval store lock"):
                        approval.prepare(root, {"operation": "read"}, "read")
            else:
                with self.assertRaisesRegex(ProjectError, "symlinked HelloDev approval store lock"):
                    approval.prepare(root, {"operation": "read"}, "read")


if __name__ == "__main__":
    unittest.main()
