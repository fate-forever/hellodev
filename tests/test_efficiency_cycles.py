from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, efficiency_cycles, governance, lifecycle, routing
from hellodev.project import ProjectError, ProjectPaths, init_project


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(
    root: Path,
    number: int,
    *,
    source_trust: str = "runtime-observed",
    input_tokens: int = 1_000,
    cached_input_tokens: int = 800,
    output_tokens: int = 100,
    subagent_tokens: int = 0,
    subagent_count: int = 0,
) -> dict[str, object]:
    source_kind = "codex-runtime" if source_trust == "runtime-observed" else "codex-runtime-import"
    return governance.record_runtime_usage(
        root,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=min(25, output_tokens),
        subagent_tokens=subagent_tokens,
        subagent_count=subagent_count,
        completed_at=f"2026-07-17T00:{number // 60:02d}:{number % 60:02d}Z",
        source_sha256=_sha(f"source-{source_trust}"),
        scope_sha256=_sha(f"scope-{source_trust}-{number}"),
        source_kind=source_kind,
        source_trust=source_trust,
    )


class EfficiencyCycleTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory)
        init_project(root)
        return root

    def test_non_overlapping_twenty_turn_window_and_pending_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(19):
                _record(root, number)
            pending = efficiency_cycles.reconcile(root)
            self.assertEqual(pending["cycleCount"], 0)
            self.assertEqual(pending["pendingReceiptCount"], 19)
            self.assertEqual(pending["remainingUntilNextCycle"], 1)

            _record(root, 19)
            complete = efficiency_cycles.reconcile(root)
            self.assertEqual(complete["createdCycles"], 1)
            self.assertEqual(complete["cycleCount"], 1)
            self.assertEqual(complete["pendingReceiptCount"], 0)
            self.assertEqual(complete["latest"]["receiptCount"], 20)

            _record(root, 20)
            extra = efficiency_cycles.reconcile(root)
            self.assertEqual(extra["createdCycles"], 0)
            self.assertEqual(extra["cycleCount"], 1)
            self.assertEqual(extra["pendingReceiptCount"], 1)
            self.assertEqual(extra["remainingUntilNextCycle"], 19)

    def test_reconcile_is_idempotent_and_creates_stable_consecutive_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(40):
                _record(root, number)
            first = efficiency_cycles.reconcile(root)
            path = ProjectPaths(root).reflection_cycles_file
            before = path.read_bytes()
            cycles = json.loads(before)["cycles"]
            repeated = efficiency_cycles.reconcile(root)
            self.assertEqual(first["createdCycles"], 2)
            self.assertEqual(repeated["createdCycles"], 0)
            self.assertEqual(repeated["cycleCount"], 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotEqual(cycles[0]["windowSha256"], cycles[1]["windowSha256"])

    def test_explicit_runtime_imports_never_drive_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(25):
                _record(root, number, source_trust="asserted-runtime")
            value = efficiency_cycles.reconcile(root)
            self.assertEqual(value["observedReceiptCount"], 0)
            self.assertEqual(value["cycleCount"], 0)
            self.assertFalse(ProjectPaths(root).reflection_cycles_file.exists())

    def test_advice_prioritizes_high_subagent_share(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(20):
                _record(
                    root,
                    number,
                    input_tokens=900,
                    cached_input_tokens=800,
                    output_tokens=100,
                    subagent_tokens=500,
                    subagent_count=1,
                )
            latest = efficiency_cycles.reconcile(root)["latest"]
            self.assertIn("subagent-share-high", latest["signals"])
            self.assertEqual(latest["recommendation"]["code"], "reduce-subagent-overhead")
            self.assertEqual(latest["recommendation"]["command"], "hellodev optimize plan --intent code --max-subagents 0")

    def test_advice_detects_low_context_cache_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(20):
                _record(root, number, cached_input_tokens=100)
            latest = efficiency_cycles.reconcile(root)["latest"]
            self.assertIn("context-reuse-low", latest["signals"])
            self.assertEqual(latest["recommendation"]["code"], "increase-context-reuse")
            self.assertEqual(latest["recommendation"]["command"], "hellodev context pack --intent code --token-budget 1200")

    def test_cycle_store_digest_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(20):
                _record(root, number)
            efficiency_cycles.reconcile(root)
            path = ProjectPaths(root).reflection_cycles_file
            store = json.loads(path.read_text(encoding="utf-8"))
            store["cycles"][0]["recommendation"]["command"] = "hellodev policy commit"
            path.write_text(json.dumps(store), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "digest mismatch"):
                efficiency_cycles.status(root)

    def test_rehashed_non_deterministic_advice_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(20):
                _record(root, number)
            efficiency_cycles.reconcile(root)
            path = ProjectPaths(root).reflection_cycles_file
            store = json.loads(path.read_text(encoding="utf-8"))
            cycle = store["cycles"][0]
            cycle["recommendation"]["command"] = "hellodev policy commit"
            cycle["cycleSha256"] = efficiency_cycles._digest(efficiency_cycles._cycle_payload(cycle))
            path.write_text(json.dumps(store), encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "does not match deterministic metrics"):
                efficiency_cycles.status(root)

    def test_cycle_is_advisory_and_cannot_authorize_or_mutate_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for number in range(20):
                _record(root, number)
            latest = efficiency_cycles.reconcile(root)["latest"]
            self.assertEqual(
                latest["policyEffect"],
                {"applyAllowed": False, "requiresHumanReview": True, "tightenOnly": True},
            )
            self.assertFalse(latest["executionPerformed"])
            self.assertEqual(latest["adapterCalls"], [])
            self.assertEqual(latest["modelCalls"], [])
            self.assertFalse(ProjectPaths(root).evolution_policy_file.exists())

    def test_finished_next_discloses_cycle_but_active_and_safety_states_preempt_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            capabilities.refresh(root)
            lifecycle.start(root)
            lifecycle.transition(root, "planned")
            for number in range(20):
                _record(root, number)
            efficiency_cycles.reconcile(root)

            active = routing.next_decision(root)
            self.assertEqual(active["reasonCode"], "lifecycle-planned")
            self.assertNotIn("efficiency", active)

            for phase in ("working", "checking", "finished"):
                lifecycle.transition(root, phase)
            finished = routing.next_decision(root)
            self.assertEqual(finished["efficiency"]["state"], "cycle-ready")
            self.assertEqual(finished["efficiency"]["trend"]["sampleSize"], 20)

            (root / "AGENTS.md").write_text("safety fingerprint changed\n", encoding="utf-8")
            safety = routing.next_decision(root)
            self.assertEqual(safety["reasonCode"], "capability-cache-not-fresh")
            self.assertNotIn("efficiency", safety)


if __name__ == "__main__":
    unittest.main()
