from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, dynamic_escalation, executable_acceptance, verification
from hellodev.application import ProjectClient
from hellodev.project import ProjectError


class V210DynamicExecutableAcceptanceTests(unittest.TestCase):
    def test_bound_requirements_require_reviewed_executable_acceptance_before_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.md").write_text("- Preserve privacy\n- Add weekly goals\n", encoding="utf-8")
            client = ProjectClient(root)
            client.do(
                "begin",
                {
                    "goal": "Implement weekly goals",
                    "acceptance": "python -m unittest discover passes",
                    "requirements_file": "requirements.md",
                },
            )

            decision = client.next()
            self.assertEqual(decision["reasonCode"], "executable-acceptance-proposal-required")
            self.assertIn("acceptance propose", decision["command"])
            with self.assertRaisesRegex(ProjectError, "executable acceptance"):
                client.do("work")

            proposed = executable_acceptance.propose(
                root,
                "red",
                "tests/test_weekly_goals.py",
                "python -m unittest discover",
                "Weekly goals preserve privacy and require learner confirmation",
            )
            self.assertEqual(proposed["state"], "proposed")
            self.assertFalse((root / "tests" / "test_weekly_goals.py").exists())
            self.assertEqual(verification.summary(root)["recordCount"], 0)
            self.assertEqual(client.next()["reasonCode"], "executable-acceptance-review-required")

            reviewed = executable_acceptance.review(
                root, proposed["proposal"]["id"], "approve", "Covers the bound requirements"
            )
            self.assertEqual(reviewed["state"], "approved")
            self.assertFalse(reviewed["verificationEvidenceCreated"])
            self.assertEqual(client.next()["reasonCode"], "lifecycle-planned")
            self.assertEqual(client.do("work")["lifecycle"]["phase"], "working")
            target = root / "tests" / "test_weekly_goals.py"
            target.parent.mkdir(parents=True)
            target.write_text("# implemented after review\n", encoding="utf-8")
            replay = executable_acceptance.review(
                root, proposed["proposal"]["id"], "approve", "Covers the bound requirements"
            )
            self.assertTrue(replay["idempotent"])
            self.assertEqual(
                acceptance.evidence(root)["executableAcceptance"]["state"], "approved"
            )

    def test_summary_only_acceptance_keeps_small_task_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do("begin", {"goal": "Fix typo", "acceptance": "docs reviewed"})
            value = executable_acceptance.status(root)
            self.assertFalse(value["required"])
            self.assertTrue(value["satisfied"])
            self.assertEqual(client.do("work")["lifecycle"]["phase"], "working")

    def test_unchanged_failure_retry_escalates_and_diagnosis_is_hash_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do("begin", {"goal": "Implement feature", "acceptance": "python -m unittest discover passes"})
            client.do("work")
            (root / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
            client.do(
                "verify",
                {
                    "level": "T1",
                    "command": "python -m unittest discover",
                    "scope": "code",
                    "outcome": "failed",
                    "current_snapshot": True,
                },
            )
            watching = dynamic_escalation.status(root)
            self.assertEqual(watching["state"], "watching")
            self.assertEqual(watching["failureCount"], 1)

            retry = client.do(
                "verify",
                {"level": "T1", "command": "python -m unittest discover", "scope": "code"},
            )
            self.assertEqual(retry["result"]["state"], "blocked-unchanged-failure")
            strict = client.next()
            self.assertEqual(strict["reasonCode"], "dynamic-escalation-diagnostic-required")
            self.assertEqual(strict["escalation"]["policy"]["verificationLevel"], "T2")
            self.assertFalse(strict["escalation"]["policy"]["subagentSpawned"])
            self.assertFalse(strict["escalation"]["policy"]["contextBudgetHalved"])

            diagnosed = dynamic_escalation.diagnose(
                root, "The fixture does not initialize the dependency", "Add a focused fixture before rerunning T2"
            )
            self.assertEqual(diagnosed["state"], "diagnosed")
            self.assertFalse(diagnosed["rawDiagnosticPersisted"])
            raw = (root / ".hellodev" / "dynamic-escalation.json").read_text(encoding="utf-8")
            self.assertNotIn("fixture does not initialize", raw)
            self.assertEqual(client.next()["reasonCode"], "dynamic-escalation-strategy-required")

            (root / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
            self.assertFalse(dynamic_escalation.status(root)["active"])
            self.assertNotIn("dynamic-escalation", client.next()["reasonCode"])

    def test_two_invalid_finish_attempts_trigger_current_snapshot_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do("begin", {"goal": "Implement feature", "acceptance": "tests pass"})
            client.do("work")
            first = client.do("finish")
            second = client.do("finish")
            self.assertEqual(first["state"], "check-required")
            self.assertEqual(first["agentGuidance"]["disclosureLevel"], "repair")
            self.assertEqual(second["state"], "recovery-required")
            self.assertEqual(second["reasonCode"], "dynamic-escalation-diagnostic-required")
            self.assertEqual(second["agentGuidance"]["disclosureLevel"], "diagnostic")
            value = dynamic_escalation.status(root)
            self.assertTrue(value["active"])
            self.assertEqual(value["failureCount"], 2)
            self.assertEqual(client.next()["reasonCode"], "dynamic-escalation-diagnostic-required")

    def test_rejected_proposal_does_not_satisfy_bound_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.md").write_text("- Exact behavior\n", encoding="utf-8")
            client = ProjectClient(root)
            client.do(
                "begin",
                {"goal": "Feature", "acceptance": "tests pass", "requirements_file": "requirements.md"},
            )
            proposed = executable_acceptance.propose(
                root, "invariant", "tests/test_feature.py", "python -m unittest", "Preserve exact behavior"
            )
            executable_acceptance.review(root, proposed["proposal"]["id"], "reject", "Missing privacy case")
            value = executable_acceptance.status(root)
            self.assertEqual(value["state"], "proposal-required")
            self.assertFalse(value["satisfied"])


if __name__ == "__main__":
    unittest.main()
