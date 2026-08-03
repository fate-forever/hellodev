from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import contextlib
import io
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, capabilities, contracts, trellis_bridge, verification
from hellodev.application import ProjectClient
from hellodev.cli import main
from hellodev.project import ProjectError


class V208MeasuredOverheadTests(unittest.TestCase):
    def test_cli_accepts_repeated_result_json_and_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectClient(root).do("begin", {"goal": "Task", "acceptance": "tests pass"})
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--json",
                        "--root",
                        str(root),
                        "do",
                        "verify",
                        "--result-json",
                        json.dumps(
                            {
                                "level": "T2",
                                "command": "npm.cmd test",
                                "scope": "project",
                                "outcome": "succeeded",
                            }
                        ),
                        "--result-json",
                        json.dumps(
                            {
                                "level": "T2",
                                "command": "npm.cmd run typecheck",
                                "scope": "project",
                                "outcome": "succeeded",
                            }
                        ),
                    ]
                )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["result"]["resultCount"], 2)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--json",
                        "--root",
                        str(root),
                        "do",
                        "verify",
                        "--result-json",
                        "{not-json}",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("invalid --result-json", stderr.getvalue())

    def test_cli_accepts_powershell_safe_structured_batch_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectClient(root).do("begin", {"goal": "Task", "acceptance": "tests pass"})
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--json", "--root", str(root), "do", "verify",
                        "--result", "T2", "project", "succeeded", "1200", "npm.cmd test",
                        "--result", "T2", "project", "succeeded", "800", "npm.cmd run typecheck",
                    ]
                )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["result"]["resultCount"], 2)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--json", "--root", str(root), "do", "verify",
                        "--result", "T2", "project", "succeeded", "bad", "npm.cmd test",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("invalid --result duration", stderr.getvalue())

    def test_trellis_begin_ignores_non_task_files_in_task_set_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / ".trellis" / "tasks"
            tasks.mkdir(parents=True)
            (tasks / "README.md").write_text("task guidance\n", encoding="utf-8")
            (tasks / ".gitkeep").write_text("", encoding="utf-8")
            client = ProjectClient(root)
            prepared = client.do(
                "begin", {"goal": "Implement weekly goals", "acceptance": "npm test passes"}
            )
            approved = client.do(
                "begin",
                {
                    "goal": "Implement weekly goals",
                    "acceptance": "npm test passes",
                    "approve": prepared["approval"],
                },
            )
            self.assertEqual(approved["state"], "ready")
            self.assertTrue(approved["selectedTask"].endswith("weekly-goals"))
            self.assertEqual(len(contracts.list_trellis_tasks(root)), 1)

    def test_npm_launcher_aliases_share_one_bounded_identity(self) -> None:
        self.assertEqual(verification.canonical_command("npm test"), "npm test")
        self.assertEqual(verification.canonical_command("npm.cmd   test"), "npm test")
        self.assertEqual(verification.canonical_command("cmd /c npm test"), "npm test")
        self.assertEqual(verification.canonical_command("cmd.exe /c npm.cmd run typecheck"), "npm run typecheck")
        self.assertEqual(
            verification.canonical_command("cmd /c npm test & echo unsafe"),
            "cmd /c npm test & echo unsafe",
        )
        host = verification.executable_command("npm test")
        self.assertEqual(host, "npm.cmd test" if os.name == "nt" else "npm test")

    def test_begin_discloses_conservative_closure_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc -b"}}),
                encoding="utf-8",
            )
            result = ProjectClient(root).do(
                "begin",
                {
                    "goal": "Implement weekly goals",
                    "acceptance": "npm test and npm run typecheck pass",
                },
            )
            closure = result["closurePlan"]
            self.assertEqual(closure["maximumProfile"], "strict")
            self.assertTrue(closure["requirementsMayTightenAfterChanges"])
            self.assertTrue(closure["batchReceiptSupported"])
            self.assertEqual(
                [(item["command"], item["level"], item["scope"]) for item in closure["requiredSteps"]],
                [("npm test", "T2", "project"), ("npm run typecheck", "T2", "project")],
            )

    def test_early_strict_receipt_covers_later_narrower_same_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
            )
            client = ProjectClient(root)
            started = client.do(
                "begin", {"goal": "Implement feature", "acceptance": "npm test passes"}
            )
            client.do("work")
            (root / "feature.ts").write_text("export const feature = true\n", encoding="utf-8")
            step = started["closurePlan"]["requiredSteps"][0]
            client.do(
                "verify",
                {
                    "results": [
                        {
                            "level": step["level"],
                            "command": step["hostCommand"],
                            "scope": step["scope"],
                            "outcome": "succeeded",
                        }
                    ]
                },
            )
            evidence = acceptance.status(root)
            self.assertEqual(evidence["state"], "satisfied")
            self.assertEqual(evidence["verification"]["state"], "covered-success")
            self.assertEqual(evidence["verification"]["evidenceLevel"], "T2")
            self.assertEqual(evidence["verification"]["evidenceScope"], "project")
            self.assertEqual(client.do("check")["lifecycle"]["phase"], "checking")

    def test_batch_receipt_canonicalizes_commands_and_refreshes_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc -b"}}),
                encoding="utf-8",
            )
            client = ProjectClient(root)
            started = client.do(
                "begin",
                {
                    "goal": "Implement weekly goals",
                    "acceptance": "npm test and npm run typecheck pass",
                },
            )
            work_id = started["workItem"]["id"]
            (root / "AGENTS.md").write_text("updated durable rule\n", encoding="utf-8")
            self.assertNotEqual(
                contracts.current_work_item(root)["sourceFingerprint"], capabilities.fingerprint(root)
            )
            result = client.do(
                "verify",
                {
                    "results": [
                        {
                            "level": "T2",
                            "command": "npm.cmd test",
                            "scope": "project",
                            "outcome": "succeeded",
                            "durationMs": 1200,
                        },
                        {
                            "level": "T2",
                            "command": "cmd /c npm run typecheck",
                            "scope": "project",
                            "outcome": "succeeded",
                            "durationMs": 800,
                        },
                    ]
                },
            )
            self.assertEqual(result["result"]["resultCount"], 2)
            self.assertEqual(result["workItem"]["id"], work_id)
            self.assertEqual(result["workItem"]["sourceFingerprint"], capabilities.fingerprint(root))
            self.assertEqual(
                verification.inspect(root, "T2", "npm test", "project")["state"],
                "reused-success",
            )
            self.assertEqual(
                verification.inspect(root, "T2", "npm run typecheck", "project")["state"],
                "reused-success",
            )

    def test_batch_receipt_is_bounded_and_cannot_mix_single_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do("begin", {"goal": "Task", "acceptance": "tests pass"})
            with self.assertRaisesRegex(ProjectError, "cannot be combined"):
                client.do(
                    "verify",
                    {
                        "results": [{"level": "T2", "command": "npm test", "scope": "project", "outcome": "succeeded"}],
                        "level": "T2",
                        "command": "npm test",
                    },
                )
            with self.assertRaisesRegex(ProjectError, "between 1 and 16"):
                client.do("verify", {"results": []})

    def test_invalid_batch_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do("begin", {"goal": "Task", "acceptance": "tests pass"})
            with self.assertRaisesRegex(ProjectError, "durationMs"):
                verification.record_current_batch(
                    root,
                    [
                        {"level": "T2", "command": "npm test", "scope": "project", "outcome": "succeeded"},
                        {"level": "T2", "command": "npm run typecheck", "scope": "project", "outcome": "succeeded", "durationMs": "bad"},
                    ],
                )
            self.assertEqual(verification.summary(root)["recordCount"], 0)

    def test_finish_projects_mergeable_hash_only_trellis_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
            )
            client = ProjectClient(root)
            prepared = client.do("begin", {"goal": "Task", "acceptance": "npm test passes"})
            ready = client.do(
                "begin",
                {"goal": "Task", "acceptance": "npm test passes", "approve": prepared["approval"]},
            )
            client.do("work")
            required = client.next()["action"]
            client.do(
                "verify",
                {"results": [{"level": "T1", "command": required["hostCommand"], "scope": "code", "outcome": "succeeded"}]},
            )
            task_record = json.loads(
                (root / ".trellis" / "tasks" / ready["selectedTask"] / "task.json").read_text(encoding="utf-8")
            )
            acceptance.record_context_validation(
                root, ready["selectedTask"], trellis_bridge.canonical_sha256(task_record), True, "component-protocol"
            )
            client.do("check")
            finish = client.do("finish")
            completed = client.do("finish", {"approve": finish["trellisCompletion"]["approval"]})
            self.assertEqual(completed["lifecycle"]["phase"], "finished")
            self.assertEqual(completed["workItem"]["linkedPhase"], "finished")
            self.assertEqual(completed["closureIntegrity"]["state"], "verified")
            self.assertEqual(
                completed["closureIntegrity"]["taskCompleteReceiptId"],
                completed["trellisCompletion"]["result"]["receipt"]["id"],
            )
            self.assertEqual(
                completed["trellisCompletion"]["result"]["receipt"]["operation"],
                "intent/task-complete",
            )
            gate = root / ".trellis" / "tasks" / ready["selectedTask"] / ".gates" / "hellodev-quality.json"
            value = json.loads(gate.read_text(encoding="utf-8"))
            self.assertEqual(value["state"], "passed")
            self.assertEqual(len(value["records"]), 1)
            self.assertFalse(value["rawCommandsPersisted"])
            self.assertNotIn("npm", gate.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
