from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, trellis_execution, verification
from hellodev.application import ProjectClient
from hellodev.dashboard import snapshot


def _package(root: Path, *, typecheck: bool = True) -> None:
    scripts = {"test": "vitest run"}
    if typecheck:
        scripts["typecheck"] = "tsc -b"
    (root / "package.json").write_text(
        json.dumps({"name": "sample", "scripts": scripts}), encoding="utf-8"
    )


class V206ManifestVerificationPlanTests(unittest.TestCase):
    def test_typescript_tests_directory_does_not_select_pytest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _package(root)
            tests = root / "tests"
            tests.mkdir()
            (tests / "feature.test.ts").write_text("export {}\n", encoding="utf-8")
            plan = trellis_execution.verification_plan(
                root, "strict", "npm test and npm run typecheck pass"
            )
            self.assertEqual([step["command"] for step in plan["steps"]], ["npm test", "npm run typecheck"])
            self.assertEqual(plan["discovery"], "package-manifest-first")

    def test_python_project_and_bounded_python_tests_still_select_pytest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_feature.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
            plan = trellis_execution.verification_plan(root)
            self.assertEqual(plan["steps"][0]["command"], "python -m pytest -q")
            self.assertEqual(plan["discovery"], "python-project-evidence")

    def test_mixed_explicit_manifests_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _package(root)
            (root / "pyproject.toml").write_text("[project]\nname='mixed'\n", encoding="utf-8")
            plan = trellis_execution.verification_plan(root)
            self.assertEqual(plan["state"], "ambiguous")
            self.assertEqual(plan["steps"], [])

    def test_ordered_plan_advances_then_requires_both_current_snapshot_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _package(root)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Strict TS feature", "acceptance": "npm test and npm run typecheck pass"})
            source = root / "src" / "feature.ts"
            source.parent.mkdir()
            source.write_text("export const feature = true\n", encoding="utf-8")
            client.do("work")
            first = client.next()
            self.assertEqual(first["action"]["hostCommand"], verification.executable_command("npm test"))
            self.assertEqual(first["acceptance"]["coverage"], {"satisfied": 0, "required": 2, "ratio": 0.0})
            control = snapshot(root, "instance", "2026-07-31T00:00:00Z")
            self.assertEqual(control["acceptanceFlow"]["verificationPlan"]["requiredSteps"], 2)
            self.assertEqual(control["acceptanceFlow"]["verificationPlan"]["currentStep"], 0)
            client.do("verify", {"level": "T1", "command": "npm test", "scope": "code", "outcome": "succeeded", "current_snapshot": True})
            second = client.next()
            self.assertEqual(
                second["action"]["hostCommand"], verification.executable_command("npm run typecheck")
            )
            client.do("verify", {"level": "T1", "command": "npm run typecheck", "scope": "code", "outcome": "succeeded", "current_snapshot": True})
            self.assertEqual(client.next()["command"], "hellodev do check")
            value = acceptance.evidence(root)
            self.assertEqual(value["hostTest"]["verificationPlan"]["satisfiedSteps"], 2)

    def test_source_mutation_invalidates_all_plan_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _package(root)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Strict TS feature", "acceptance": "npm test and npm run typecheck pass"})
            source = root / "feature.ts"
            source.write_text("export const value = 1\n", encoding="utf-8")
            client.do("work")
            for command in ("npm test", "npm run typecheck"):
                client.do("verify", {"level": "T1", "command": command, "scope": "code", "outcome": "succeeded", "current_snapshot": True})
            source.write_text("export const value = 2\n", encoding="utf-8")
            decision = client.next()
            self.assertEqual(
                decision["action"]["hostCommand"], verification.executable_command("npm test")
            )
            self.assertEqual(decision["acceptance"]["hostTest"]["verificationPlan"]["satisfiedSteps"], 0)

    def test_unchanged_failure_exposes_no_executable_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _package(root)
            client = ProjectClient(root)
            client.open()
            client.do("begin", {"goal": "Strict TS feature", "acceptance": "npm test and npm run typecheck pass"})
            (root / "feature.ts").write_text("export const value = 1\n", encoding="utf-8")
            client.do("work")
            client.do("verify", {"level": "T1", "command": "npm test", "scope": "code", "outcome": "failed", "current_snapshot": True})
            decision = client.next()
            self.assertTrue(decision["command"].endswith("status --verbose"))
            self.assertEqual(decision["reasonCode"], "acceptance-unchanged-failure")
            self.assertNotIn("action", decision)
            self.assertFalse(decision["acceptance"]["hostTest"]["verification"]["runRequired"])


if __name__ == "__main__":
    unittest.main()
