from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, lifecycle, optimization, resume, routing
from hellodev.project import ProjectError, ProjectPaths, init_project, write_json


class RoutingTests(unittest.TestCase):
    def test_lifecycle_and_unknown_intents_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            decision = routing.decide(root, "plan", {"note": "requirements accepted"})
            self.assertEqual(decision["route"], "lifecycle.plan")
            self.assertEqual(decision["contextIntent"], "lifecycle")
            self.assertFalse(decision["executionPerformed"])
            with self.assertRaisesRegex(ProjectError, "available intents"):
                routing.decide(root, "deploy", {})

    def test_task_routing_prefers_trellis_and_local_fallback_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = routing.decide(root, "task", {"operation": "create", "title": "Local task"})
            self.assertEqual(local["route"], "local-task.create")
            (root / ".trellis").mkdir()
            native = routing.decide(root, "task", {"operation": "create", "title": "Native task"})
            self.assertEqual(native["route"], "trellis.task-create")
            self.assertEqual(native["risk"], "write")
            gate = routing.decide(root, "validate", {"task": "07-16-f1"})
            self.assertEqual(gate["route"], "trellis.task-validate")
            self.assertEqual(gate["intent"], "validate")
            with self.assertRaisesRegex(ProjectError, "not in the Trellis F1 allowlist"):
                routing.decide(root, "task", {"operation": "show", "task": "task-0001"})

    def test_next_is_read_only_and_returns_one_complete_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = routing.next_decision(root)
            self.assertEqual(first["command"], "hellodev open")
            init_project(root)
            missing_cache = routing.next_decision(root)
            self.assertEqual(missing_cache["command"], "hellodev capabilities refresh")
            capabilities.refresh(root)
            started = lifecycle.start(root)
            self.assertEqual(started["phase"], "started")
            planned = routing.next_decision(root)
            self.assertEqual(planned["command"], "hellodev do plan")
            self.assertNotIn("...", planned["command"])

    def test_incomplete_saga_preempts_lifecycle_recommendation(self) -> None:
        for phase in ("trellis-pending", "partial"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                init_project(root)
                lifecycle.start(root)
                capabilities.refresh(root)
                saga_path = ProjectPaths(root).sagas_dir / "saga-0001.json"
                write_json(
                    saga_path,
                    {
                        "schemaVersion": 1,
                        "id": "saga-0001",
                        "title": "Incomplete",
                        "phase": phase,
                        "requiredTrellisEvidenceKinds": ["gate", "test"],
                        "createdAt": "2026-07-16T00:00:00Z",
                        "updatedAt": "2026-07-16T00:00:00Z",
                        "steps": [],
                    },
                )
                decision = routing.next_decision(root)
                self.assertEqual(decision["command"], "hellodev saga next saga-0001")
                self.assertEqual(decision["reasonCode"], "saga-incomplete")

    def test_finished_next_discloses_one_optional_efficiency_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            capabilities.refresh(root)
            lifecycle.start(root)
            for phase in ("planned", "working", "checking", "finished"):
                lifecycle.transition(root, phase)

            quiet = routing.next_decision(root)
            self.assertEqual(quiet["command"], "hellodev receipt list")
            self.assertNotIn("efficiency", quiet)
            self.assertFalse(ProjectPaths(root).optimization_file.exists())

            optimization.reflect(root, "code", "L1", "partial", retry_count=2)
            path = ProjectPaths(root).optimization_file
            before = path.read_bytes()
            attention = routing.next_decision(root)
            resumed = resume.build(root)
            self.assertEqual(attention["command"], "hellodev receipt list")
            self.assertEqual(attention["efficiency"]["state"], "attention")
            self.assertEqual(
                attention["efficiency"]["suggestion"]["command"],
                "hellodev optimize status",
            )
            self.assertEqual(resumed["next"], attention)
            self.assertFalse(attention["efficiency"]["executionPerformed"])
            self.assertFalse(attention["efficiency"]["persistencePerformed"])
            self.assertEqual(attention["efficiency"]["adapterCalls"], [])
            self.assertEqual(attention["efficiency"]["modelCalls"], [])
            self.assertEqual(path.read_bytes(), before)
            self.assertLessEqual(len(json.dumps(attention).encode("utf-8")), 1024)

            optimization.reflect(root, "code", "L1", "partial", retry_count=3)
            optimization.reflect(root, "code", "L1", "partial", retry_count=4)
            review = routing.next_decision(root)
            self.assertEqual(review["command"], "hellodev receipt list")
            self.assertEqual(review["efficiency"]["state"], "review-due")
            self.assertEqual(
                review["efficiency"]["suggestion"]["command"],
                "hellodev optimize proposals",
            )

    def test_safety_priority_suppresses_efficiency_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            capabilities.refresh(root)
            lifecycle.start(root)
            for phase in ("planned", "working", "checking", "finished"):
                lifecycle.transition(root, phase)
            optimization.reflect(root, "code", "L1", "partial", retry_count=2)
            (root / "AGENTS.md").write_text("changed safety context\n", encoding="utf-8")

            decision = routing.next_decision(root)
            self.assertEqual(decision["command"], "hellodev capabilities refresh")
            self.assertEqual(decision["reasonCode"], "capability-cache-not-fresh")
            self.assertNotIn("efficiency", decision)

    def test_active_workflow_hides_efficiency_until_finished(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            capabilities.refresh(root)
            lifecycle.start(root)
            lifecycle.transition(root, "planned")
            optimization.reflect(root, "code", "L1", "partial", retry_count=2)

            decision = routing.next_decision(root)
            self.assertEqual(decision["command"], "hellodev do work")
            self.assertEqual(decision["reasonCode"], "lifecycle-planned")
            self.assertNotIn("efficiency", decision)

    def test_invalid_advisory_state_does_not_block_finished_next(self) -> None:
        invalid_states = {
            "malformed-optimization": ("optimization_file", "{}\n"),
            "future-optimization": (
                "optimization_file",
                '{"schemaVersion":2,"traces":[],"reports":[],"proposals":[]}\n',
            ),
            "malformed-usage": ("usage_file", "{}\n"),
        }
        for label, (path_name, content) in invalid_states.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                init_project(root)
                capabilities.refresh(root)
                lifecycle.start(root)
                for phase in ("planned", "working", "checking", "finished"):
                    lifecycle.transition(root, phase)

                getattr(ProjectPaths(root), path_name).write_text(content, encoding="utf-8")
                decision = routing.next_decision(root)
                self.assertEqual(decision["command"], "hellodev receipt list")
                self.assertEqual(decision["reasonCode"], "lifecycle-finished")
                self.assertNotIn("efficiency", decision)
                with self.assertRaises(ProjectError):
                    optimization.status(root)


if __name__ == "__main__":
    unittest.main()
