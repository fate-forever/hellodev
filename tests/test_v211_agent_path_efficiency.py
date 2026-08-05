from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, acceptance_planning, capabilities, changesets, contracts, lifecycle, trellis_preflight
from hellodev.application import ProjectClient
from hellodev.project import ProjectError, create_task, init_project


class V211AgentPathEfficiencyTests(unittest.TestCase):
    @staticmethod
    def _requirements(root: Path) -> None:
        (root / "TASK.md").write_text(
            """# Weekly goals
- Learner confirms the generated schedule
- Supporter sees authorized aggregate progress only
- Local and Supabase persistence stay consistent
- The production UI exposes explicit rollover
- npm test, npm run test:integration, npm run typecheck, and npm run build pass
""",
            encoding="utf-8",
        )
        (root / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {
                        "test": "vitest run",
                        "test:integration": "vitest run tests/integration",
                        "typecheck": "tsc -b",
                        "build": "tsc -b && vite build",
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_exact_requirements_compile_criteria_and_progressive_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._requirements(root)
            client = ProjectClient(root)
            begun = client.do(
                "begin",
                {
                    "goal": "Deliver weekly goals",
                    "acceptance": "npm test, npm run test:integration, npm run typecheck, and npm run build pass",
                    "requirements_file": "TASK.md",
                },
            )
            plan = begun["acceptanceGatePlan"]
            self.assertEqual(plan["state"], "ready")
            self.assertEqual(plan["criterionCount"], 5)
            self.assertEqual(
                [gate["command"] for gate in plan["gates"]],
                ["npm test", "npm run test:integration", "npm run typecheck", "npm run build"],
            )
            self.assertTrue(plan["allCriteriaMapped"])
            self.assertFalse(plan["executionPerformed"])
            self.assertFalse(plan["verificationEvidenceCreated"])
            self.assertEqual(begun["nextAction"]["command"], begun["next"]["command"])
            self.assertEqual(begun["operationMetrics"]["measurement"], "local-monotonic")
            self.assertFalse(begun["operationMetrics"]["persisted"])

            direct = acceptance_planning.build(root)
            self.assertEqual(direct["planSha256"], plan["planSha256"])
            self.assertEqual(direct["requirementsSha256"], acceptance.current(root)["requirementsSource"]["sha256"])

            (root / "TASK.md").write_text("changed requirement\n", encoding="utf-8")
            invalid = acceptance_planning.build(root)
            self.assertEqual(invalid["state"], "requirements-invalid")
            self.assertEqual(invalid["criteria"], [])
            self.assertFalse(invalid["verificationEvidenceCreated"])

    def test_trellis_preflight_is_actionable_but_not_native_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._requirements(root)
            task = root / ".trellis" / "tasks" / "08-04-weekly-goals"
            task.mkdir(parents=True)
            (task / "task.json").write_text(json.dumps({"status": "planning"}), encoding="utf-8")
            (task / "prd.md").write_text("# PRD\nReviewed requirements\n", encoding="utf-8")
            init_project(root)
            lifecycle.start(root)
            work = contracts.create_work_item(root, "trellis", task.name)
            lifecycle.transition(root, "planned")
            acceptance.record(
                root,
                work["id"],
                "Deliver weekly goals",
                "npm test and npm run build pass",
                "TASK.md",
            )
            value = trellis_preflight.status(root)
            self.assertEqual(value["state"], "planning-required")
            self.assertIn("design.md", value["missing"])
            self.assertIn("implement.jsonl", value["missing"])
            self.assertFalse(value["nativeValidationSatisfied"])
            self.assertFalse(value["qualityGateSatisfied"])
            self.assertFalse(value["executionPerformed"])

            (task / "design.md").write_text("# Design\nReviewed design\n", encoding="utf-8")
            (task / "implement.md").write_text("# Plan\nReviewed implementation\n", encoding="utf-8")
            for name in ("implement.jsonl", "check.jsonl"):
                (task / name).write_text(
                    json.dumps({"file": "TASK.md", "reason": "Exact reviewed requirements"}) + "\n",
                    encoding="utf-8",
                )
            self.assertEqual(trellis_preflight.status(root)["state"], "ready")

            (task / "implement.jsonl").write_text(
                json.dumps({"file": 42, "reason": "invalid type"}) + "\n",
                encoding="utf-8",
            )
            invalid_type = trellis_preflight.status(root)
            self.assertEqual(invalid_type["state"], "planning-required")
            self.assertEqual(invalid_type["contextManifests"]["implement.jsonl"]["state"], "invalid")

            (task / "implement.jsonl").write_text(
                json.dumps({"file": "../outside.py", "reason": "unsafe path"}) + "\n",
                encoding="utf-8",
            )
            unsafe_path = trellis_preflight.status(root)
            self.assertEqual(unsafe_path["state"], "planning-required")
            self.assertEqual(unsafe_path["contextManifests"]["implement.jsonl"]["state"], "invalid")

    def test_only_isolated_context_drift_auto_refreshes_on_do(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / ".trellis" / "spec" / "context" / "CONTEXT.md"
            context.parent.mkdir(parents=True)
            context.write_text("baseline\n", encoding="utf-8")
            init_project(root)
            lifecycle.start(root)
            task = create_task(root, "Local task", "tests pass")
            work = contracts.create_work_item(root, "local", task["id"])
            lifecycle.transition(root, "planned")
            acceptance.record(root, work["id"], "Local task", "tests pass")
            capabilities.refresh(root)
            changesets.capture_baseline(root)
            context.write_text("updated project context\n", encoding="utf-8")

            value = ProjectClient(root).do("work")
            self.assertEqual(value["capabilityRefresh"]["reasonCode"], "project-context-only-auto-refresh")
            self.assertTrue(value["capabilityRefresh"]["componentIdentityRevalidated"])
            self.assertEqual(value["lifecycle"]["phase"], "working")
            self.assertEqual(capabilities.status(root)["state"], "fresh")

            (root / "AGENTS.md").write_text("changed safety instruction\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "explicit review"):
                ProjectClient(root).do("check")
            self.assertEqual(capabilities.status(root)["state"], "stale")

    def test_auxiliary_do_response_chains_without_recomputing_routing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            value = ProjectClient(root).do("task", {"operation": "list"})
            self.assertEqual(value["nextAction"]["chainSource"], "explicit-next-hop")
            self.assertIn(" next", value["nextAction"]["command"])
            self.assertFalse(value["nextAction"]["executionPerformed"])


if __name__ == "__main__":
    unittest.main()
