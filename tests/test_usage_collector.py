from __future__ import annotations

import json
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import governance, usage_collector
from hellodev.cli import main
from hellodev.project import ProjectError, ProjectPaths, init_project


ROOT_THREAD = "11111111-1111-4111-8111-111111111111"
ROOT_TURN = "22222222-2222-4222-8222-222222222222"
CHILD_THREAD = "33333333-3333-4333-8333-333333333333"
CHILD_TURN = "44444444-4444-4444-8444-444444444444"
GRAND_THREAD = "55555555-5555-4555-8555-555555555555"
GRAND_TURN = "66666666-6666-4666-8666-666666666666"
CANARY = 'RAW-TRANSCRIPT-CANARY-MUST-NOT-PERSIST "type":"token_count" "type":"task_complete"'


def _run_cli(*args: str) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    if code:
        raise AssertionError(f"CLI failed with {code}: {stderr.getvalue()}")
    return json.loads(stdout.getvalue())


def _usage(input_tokens: int, cached: int, output: int, reasoning: int) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "reasoning_output_tokens": reasoning,
        "total_tokens": input_tokens + output,
    }


def _write(path: Path, items: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, separators=(",", ":")) for item in items) + "\n", encoding="utf-8")


def _meta(thread_id: str, timestamp: str, cwd: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {"id": thread_id, "timestamp": timestamp, "cwd": str(cwd), "base_instructions": CANARY},
    }


def _event(timestamp: str, event_type: str, **payload: object) -> dict[str, object]:
    return {"timestamp": timestamp, "type": "event_msg", "payload": {"type": event_type, **payload}}


def _token(timestamp: str, usage: dict[str, int]) -> dict[str, object]:
    return _event(timestamp, "token_count", info={"total_token_usage": usage, "last_token_usage": usage})


class UsageCollectorTests(unittest.TestCase):
    def _fixture(self, directory: str, include_child: bool = True) -> tuple[Path, Path]:
        base = Path(directory)
        project = base / "project"
        project.mkdir()
        init_project(project)
        codex_home = base / "codex-home"
        root_file = codex_home / "sessions" / "2026" / "07" / "17" / f"rollout-test-{ROOT_THREAD}.jsonl"
        root_items = [
            _meta(ROOT_THREAD, "2026-07-17T00:00:00Z", project),
            _token("2026-07-17T00:00:01Z", _usage(80, 60, 20, 5)),
            _event("2026-07-17T00:01:00Z", "task_started", turn_id=ROOT_TURN),
            _token("2026-07-17T00:01:10Z", _usage(120, 90, 30, 8)),
            _token("2026-07-17T00:01:11Z", _usage(120, 90, 30, 8)),
            _event(
                "2026-07-17T00:01:12Z",
                "sub_agent_activity",
                agent_thread_id=CHILD_THREAD,
                agent_path="/root/review",
                event_id="event-1",
                kind="started",
                occurred_at_ms=1,
            ),
            _token("2026-07-17T00:01:40Z", _usage(145, 100, 35, 10)),
            _event(
                "2026-07-17T00:02:00Z",
                "task_complete",
                turn_id=ROOT_TURN,
                completed_at="2026-07-17T00:02:00Z",
                last_agent_message=CANARY,
            ),
        ]
        _write(root_file, root_items)
        if include_child:
            child_file = codex_home / "sessions" / "2026" / "07" / "17" / f"rollout-test-{CHILD_THREAD}.jsonl"
            child_items = [
                _meta(CHILD_THREAD, "2026-07-17T00:01:12Z", project),
                # Replayed parent history must not be counted as child usage.
                _token("2026-07-17T00:01:10Z", _usage(120, 90, 30, 8)),
                _event("2026-07-17T00:01:13Z", "task_started", turn_id=CHILD_TURN),
                _token("2026-07-17T00:01:14Z", _usage(120, 90, 30, 8)),
                _token("2026-07-17T00:01:30Z", _usage(140, 105, 35, 10)),
                _token("2026-07-17T00:01:31Z", _usage(140, 105, 35, 10)),
                _event(
                    "2026-07-17T00:01:32Z",
                    "task_complete",
                    turn_id=CHILD_TURN,
                    completed_at="2026-07-17T00:01:32Z",
                    last_agent_message=CANARY,
                ),
            ]
            _write(child_file, child_items)
        return project, codex_home

    def _multi_turn_fixture(self, directory: str, completed_turns: int = 21) -> tuple[Path, Path]:
        base = Path(directory)
        project = base / "project"
        project.mkdir()
        init_project(project)
        codex_home = base / "codex-home"
        root_file = codex_home / "sessions" / "2026" / "07" / "17" / f"rollout-sync-{ROOT_THREAD}.jsonl"
        items: list[dict[str, object]] = [
            _meta(ROOT_THREAD, "2026-07-17T00:00:00Z", project),
            _token("2026-07-17T00:00:01Z", _usage(0, 0, 0, 0)),
        ]
        for number in range(1, completed_turns + 1):
            turn_id = f"00000000-0000-4000-8000-{number:012x}"
            items.extend([
                _event(f"2026-07-17T00:{number:02d}:00Z", "task_started", turn_id=turn_id),
                _token(f"2026-07-17T00:{number:02d}:10Z", _usage(number * 100, number * 70, number * 10, number * 2)),
                _event(f"2026-07-17T00:{number:02d}:20Z", "task_complete", turn_id=turn_id),
            ])
        incomplete_turn = "77777777-7777-4777-8777-777777777777"
        items.extend([
            _event("2026-07-17T01:00:00Z", "task_started", turn_id=incomplete_turn),
            _token("2026-07-17T01:00:10Z", _usage((completed_turns + 1) * 100, (completed_turns + 1) * 70, (completed_turns + 1) * 10, (completed_turns + 1) * 2)),
        ])
        _write(root_file, items)
        return project, codex_home

    def test_sync_backfills_oldest_completed_turns_respects_limit_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._multi_turn_fixture(directory)
            environment = {"CODEX_THREAD_ID": ROOT_THREAD, "CODEX_HOME": str(codex_home)}
            with mock.patch.dict("os.environ", environment, clear=False):
                first = usage_collector.sync_codex_usage(root, limit=5)
                second = usage_collector.sync_codex_usage(root, limit=100)
                repeated = usage_collector.sync_codex_usage(root, limit=100)

            self.assertEqual(first["recordedCount"], 5)
            self.assertEqual(first["remainingUnrecordedCount"], 16)
            self.assertEqual(second["recordedCount"], 16)
            self.assertEqual(second["remainingUnrecordedCount"], 0)
            self.assertEqual(repeated["state"], "current")
            self.assertEqual(repeated["recordedCount"], 0)
            self.assertEqual(repeated["existingCount"], 0)
            records = governance.list_runtime_usage_records(root)
            self.assertEqual(len(records), 21)
            self.assertTrue(all(item["sourceTrust"] == "runtime-observed" for item in records))
            self.assertEqual(records[0]["totalTokens"], 110)
            self.assertEqual(records[-1]["totalTokens"], 110)

    def test_sync_creates_one_cycle_at_twenty_and_excludes_incomplete_current_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._multi_turn_fixture(directory, completed_turns=20)
            environment = {"CODEX_THREAD_ID": ROOT_THREAD, "CODEX_HOME": str(codex_home)}
            with mock.patch.dict("os.environ", environment, clear=False):
                value = usage_collector.sync_codex_usage(root)

            self.assertEqual(value["completedTurnCount"], 20)
            self.assertEqual(value["recordedCount"], 20)
            self.assertEqual(value["reflectionCycle"]["cycleCount"], 1)
            self.assertEqual(value["reflectionCycle"]["pendingReceiptCount"], 0)
            self.assertEqual(len(governance.list_runtime_usage_records(root)), 20)
            self.assertFalse(value["estimated"])

    def test_usage_sync_cli_and_status_expose_cycle_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._multi_turn_fixture(directory, completed_turns=3)
            environment = {"CODEX_THREAD_ID": ROOT_THREAD, "CODEX_HOME": str(codex_home)}
            with mock.patch.dict("os.environ", environment, clear=False):
                synced = _run_cli("--root", str(root), "usage", "sync", "--limit", "2")
                status = _run_cli("--root", str(root), "usage", "status")

            self.assertEqual(synced["recordedCount"], 2)
            self.assertEqual(synced["remainingUnrecordedCount"], 1)
            self.assertEqual(status["reflectionCycle"]["pendingReceiptCount"], 2)
            self.assertEqual(status["reflectionCycle"]["remainingUntilNextCycle"], 18)

    def test_open_opportunistically_syncs_previous_completed_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._multi_turn_fixture(directory, completed_turns=3)
            environment = {"CODEX_THREAD_ID": ROOT_THREAD, "CODEX_HOME": str(codex_home)}
            with mock.patch.dict("os.environ", environment, clear=False), mock.patch(
                "hellodev.application._roots_overlap", return_value=True
            ):
                opened = _run_cli("--root", str(root), "open")

            self.assertEqual(opened["usageSync"]["state"], "synced")
            self.assertEqual(opened["usageSync"]["recordedCount"], 3)
            self.assertEqual(opened["usageSync"]["pendingReceiptCount"], 3)
            self.assertEqual(opened["reflectionCycle"]["pendingReceiptCount"], 3)

    def test_collects_previous_completed_turn_and_subagent_by_cumulative_delta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            first = usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            repeated = usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)

            self.assertEqual(first["state"], "recorded")
            self.assertEqual(repeated["state"], "existing")
            self.assertEqual(first["totalTokens"], 105)
            self.assertEqual(first["rootTokens"], 80)
            self.assertEqual(first["subagentTokens"], 25)
            self.assertEqual(first["subagentCount"], 1)
            self.assertEqual(first["breakdown"], {
                "inputTokens": 85,
                "cachedInputTokens": 55,
                "outputTokens": 20,
                "reasoningOutputTokens": 7,
            })
            self.assertEqual(first["measurement"], "exact")
            self.assertEqual(first["sourceTrust"], "asserted-runtime")
            self.assertEqual(first["sourceKind"], "codex-runtime-import")
            self.assertEqual(first["attestation"], "none")
            self.assertFalse(first["estimated"])

            stored = ProjectPaths(root).runtime_usage_file.read_text(encoding="utf-8")
            for forbidden in (CANARY, ROOT_THREAD, ROOT_TURN, CHILD_THREAD, CHILD_TURN, str(codex_home)):
                self.assertNotIn(forbidden, stored)
            status = governance.usage_status(root)
            self.assertEqual(status["preferred"]["sourceTrust"], "asserted-runtime")
            self.assertEqual(status["preferredBreakdown"]["cachedInputTokens"], 55)

    def test_missing_subagent_fails_closed_without_persisting_partial_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory, include_child=False)
            with self.assertRaisesRegex(ProjectError, "subagent session file is missing"):
                usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            self.assertFalse(ProjectPaths(root).usage_file.exists())

    def test_cli_collect_uses_explicit_thread_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            first = _run_cli(
                "--root", str(root), "usage", "collect",
                "--thread-id", ROOT_THREAD, "--codex-home", str(codex_home),
            )
            repeated = _run_cli(
                "--root", str(root), "usage", "collect",
                "--thread-id", ROOT_THREAD, "--codex-home", str(codex_home),
            )
            self.assertEqual(first["state"], "recorded")
            self.assertEqual(repeated["state"], "existing")
            self.assertEqual(first["totalTokens"], 105)
            self.assertEqual(first["sourceTrust"], "asserted-runtime")

    def test_same_turn_with_conflicting_counts_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            root_file = next((codex_home / "sessions").rglob(f"*{ROOT_THREAD}.jsonl"))
            items = [json.loads(line) for line in root_file.read_text(encoding="utf-8").splitlines()]
            items[-2] = _token("2026-07-17T00:01:40Z", _usage(146, 100, 35, 10))
            _write(root_file, items)
            with self.assertRaisesRegex(ProjectError, "conflicting Codex runtime usage"):
                usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)

    def test_runtime_shape_and_cumulative_regression_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            root_file = next((codex_home / "sessions").rglob(f"*{ROOT_THREAD}.jsonl"))
            items = [json.loads(line) for line in root_file.read_text(encoding="utf-8").splitlines()]
            items[-2] = _token("2026-07-17T00:01:40Z", _usage(70, 60, 10, 2))
            _write(root_file, items)
            with self.assertRaisesRegex(ProjectError, "moved backwards"):
                usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            self.assertFalse(ProjectPaths(root).usage_file.exists())

    def test_legacy_usage_store_remains_schema_one_and_runtime_is_additive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            path = ProjectPaths(root).usage_file
            path.write_text(json.dumps({
                "schemaVersion": 1,
                "records": [{
                    "id": "usage-0001",
                    "recordedAt": "2026-07-16T00:00:00Z",
                    "totalTokens": 100,
                    "subagentTokens": 0,
                    "subagentCount": 0,
                    "source": "legacy-host",
                    "scope": "turn",
                    "accuracy": "reported",
                }],
            }), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(governance.usage_status(root)["preferred"]["totalTokens"], 100)
            self.assertEqual(path.read_bytes(), before)
            governance.record_usage(root, 50, 0, 0, "host", "turn-2")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schemaVersion"], 1)
            self.assertFalse(ProjectPaths(root).runtime_usage_file.exists())

    def test_implicit_desktop_selection_is_runtime_observed_and_project_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            with mock.patch.dict(
                "os.environ",
                {"CODEX_THREAD_ID": ROOT_THREAD, "CODEX_HOME": str(codex_home)},
                clear=False,
            ):
                value = usage_collector.collect_previous_codex_turn(root)
            self.assertEqual(value["sourceKind"], "codex-runtime")
            self.assertEqual(value["sourceTrust"], "runtime-observed")

            unrelated = Path(directory) / "unrelated"
            unrelated.mkdir()
            init_project(unrelated)
            with mock.patch.dict(
                "os.environ",
                {"CODEX_THREAD_ID": ROOT_THREAD, "CODEX_HOME": str(codex_home)},
                clear=False,
            ):
                with self.assertRaisesRegex(ProjectError, "cwd does not match"):
                    usage_collector.collect_previous_codex_turn(unrelated)

    def test_incomplete_child_and_missing_interval_snapshot_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            child_file = next((codex_home / "sessions").rglob(f"*{CHILD_THREAD}.jsonl"))
            child_items = [json.loads(line) for line in child_file.read_text(encoding="utf-8").splitlines()]
            _write(child_file, child_items[:-1])
            with self.assertRaisesRegex(ProjectError, "subagent task is incomplete"):
                usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            self.assertFalse(ProjectPaths(root).runtime_usage_file.exists())

        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            root_file = next((codex_home / "sessions").rglob(f"*{ROOT_THREAD}.jsonl"))
            root_items = [json.loads(line) for line in root_file.read_text(encoding="utf-8").splitlines()]
            root_items = [
                item
                for item in root_items
                if not (item.get("payload", {}).get("type") == "token_count" and item["timestamp"] >= "2026-07-17T00:01:00Z")
            ]
            _write(root_file, root_items)
            with self.assertRaisesRegex(ProjectError, "token metadata is unavailable"):
                usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            self.assertFalse(ProjectPaths(root).runtime_usage_file.exists())

    def test_nested_descendant_reported_by_parent_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            root_file = next((codex_home / "sessions").rglob(f"*{ROOT_THREAD}.jsonl"))
            root_items = [json.loads(line) for line in root_file.read_text(encoding="utf-8").splitlines()]
            root_items.insert(-1, _event("2026-07-17T00:01:21Z", "sub_agent_activity", agent_thread_id=GRAND_THREAD))
            _write(root_file, root_items)

            child_file = next((codex_home / "sessions").rglob(f"*{CHILD_THREAD}.jsonl"))
            child_items = [json.loads(line) for line in child_file.read_text(encoding="utf-8").splitlines()]
            child_items.insert(-2, _event("2026-07-17T00:01:20Z", "sub_agent_activity", agent_thread_id=GRAND_THREAD))
            _write(child_file, child_items)

            grand_file = child_file.with_name(f"rollout-test-{GRAND_THREAD}.jsonl")
            _write(grand_file, [
                _meta(GRAND_THREAD, "2026-07-17T00:01:20Z", root),
                _token("2026-07-17T00:01:20Z", _usage(140, 105, 35, 10)),
                _event("2026-07-17T00:01:21Z", "task_started", turn_id=GRAND_TURN),
                _token("2026-07-17T00:01:24Z", _usage(148, 110, 37, 11)),
                _event("2026-07-17T00:01:25Z", "task_complete", turn_id=GRAND_TURN, last_agent_message=CANARY),
            ])
            value = usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            self.assertEqual(value["subagentCount"], 2)
            self.assertEqual(value["subagentTokens"], 35)
            self.assertEqual(value["totalTokens"], 115)

    def test_runtime_receipt_digest_detects_count_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            usage_collector.collect_previous_codex_turn(root, thread_id=ROOT_THREAD, codex_home=codex_home)
            path = ProjectPaths(root).runtime_usage_file
            value = json.loads(path.read_text(encoding="utf-8"))
            value["records"][0]["totalTokens"] += 1
            value["records"][0]["inputTokens"] += 1
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "receipt digest mismatch"):
                governance.usage_status(root)

    def test_token_event_extra_content_is_never_json_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            root_file = next((codex_home / "sessions").rglob(f"*{ROOT_THREAD}.jsonl"))
            items = [json.loads(line) for line in root_file.read_text(encoding="utf-8").splitlines()]
            token = next(item for item in items if item.get("payload", {}).get("type") == "token_count")
            token["payload"]["prompt"] = CANARY
            _write(root_file, items)

            decoded: list[str] = []
            original_loads = json.loads

            def tracked_loads(value: str, *args: object, **kwargs: object) -> object:
                decoded.append(value)
                return original_loads(value, *args, **kwargs)

            with mock.patch.object(usage_collector.json, "loads", side_effect=tracked_loads):
                usage_collector.collect_previous_codex_turn(
                    root,
                    thread_id=ROOT_THREAD,
                    codex_home=codex_home,
                )
            self.assertFalse(any(CANARY in value for value in decoded))

    def test_discovery_budget_counts_unrelated_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, codex_home = self._fixture(directory)
            unrelated = codex_home / "sessions" / "unrelated"
            unrelated.mkdir()
            for index in range(4):
                (unrelated / f"noise-{index}.txt").write_text("noise", encoding="utf-8")
            with mock.patch.object(usage_collector, "MAX_DISCOVERY_ENTRIES", 2):
                with self.assertRaisesRegex(ProjectError, "discovery entry limit"):
                    usage_collector.collect_previous_codex_turn(
                        root,
                        thread_id=ROOT_THREAD,
                        codex_home=codex_home,
                    )


if __name__ == "__main__":
    unittest.main()
