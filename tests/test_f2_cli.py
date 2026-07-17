from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import contracts, receipts
from hellodev.cli import main
from hellodev.project import ProjectPaths, configure_nocturne


FAKE_MCP_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def invoke(*args: str) -> tuple[int, dict | None, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    value = json.loads(stdout.getvalue()) if code == 0 and stdout.getvalue() else None
    return code, value, stderr.getvalue()


def run_cli(*args: str) -> dict:
    code, value, error = invoke(*args)
    if code or value is None:
        raise AssertionError(f"CLI failed with {code}: {error}")
    return value


class F2CliTests(unittest.TestCase):
    def _trellis_root(self, directory: str, task: str = "07-16-f2") -> Path:
        root = Path(directory)
        scripts = root / ".trellis" / "scripts"
        scripts.mkdir(parents=True)
        (root / ".trellis" / "workflow.md").write_text("# Workflow\nUse gates.\n", encoding="utf-8")
        (root / ".trellis" / "tasks" / task).mkdir(parents=True)
        (scripts / "task.py").write_text(
            "import sys\nprint('native-task:' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        return root

    def _subprocess_json(self, root: Path, *arguments: str) -> dict:
        environment = dict(os.environ)
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src") + (os.pathsep + existing if existing else "")
        completed = subprocess.run(
            [sys.executable, "-m", "hellodev", "--json", "--root", str(root), *arguments],
            cwd=PACKAGE_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode:
            self.fail(f"subprocess CLI failed: {completed.stderr}")
        return json.loads(completed.stdout)

    def test_work_commands_are_pointer_only_and_local_create_selects_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            created = run_cli("--root", str(root), "task", "create", "Pointer only task")
            self.assertEqual(created["workItem"]["nativeRef"], "task-0001")
            current = run_cli("--root", str(root), "work", "current")["workItem"]
            self.assertEqual(current["id"], "work-0001")
            self.assertNotIn("Pointer only task", json.dumps(current))
            shown = run_cli("--root", str(root), "work", "show", current["id"])
            self.assertEqual(shown, current)
            self.assertEqual(len(run_cli("--root", str(root), "work", "list")["workItems"]), 1)
            cleared = run_cli("--root", str(root), "work", "clear")
            self.assertTrue(cleared["cleared"])
            self.assertIsNone(run_cli("--root", str(root), "work", "current")["workItem"])
            selected = run_cli("--root", str(root), "work", "select", current["id"])
            self.assertEqual(selected["id"], current["id"])

    def test_08_state_reads_without_creating_f2_stores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            paths = ProjectPaths(root)
            names = ("work-items.json", "lesson-proposals.json", "evidence-links.json")
            for name in names:
                self.assertFalse((paths.state_dir / name).exists())
            self.assertEqual(run_cli("--root", str(root), "work", "list")["workItems"], [])
            self.assertEqual(run_cli("--root", str(root), "lesson", "list")["lessonProposals"], [])
            self.assertEqual(run_cli("--root", str(root), "gate", "status")["state"], "no-current-work")
            run_cli("--root", str(root), "resume")
            for name in names:
                self.assertFalse((paths.state_dir / name).exists())

    def test_resume_and_resume_context_are_stable_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            run_cli("--root", str(root), "task", "create", "Resume this work")
            first = self._subprocess_json(root, "resume")
            second = self._subprocess_json(root, "resume")
            self.assertEqual(first, second)
            self.assertEqual(first["currentWorkItem"]["nativeRef"], "task-0001")
            packed = self._subprocess_json(root, "context", "pack", "--resume", "--token-budget", "128")
            self.assertLessEqual(packed["byteCount"], 512)
            self.assertIn("work: work-0001", packed["content"])

    def test_gate_policy_is_confirmed_and_blocks_both_finish_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._trellis_root(directory)
            run_cli("--root", str(root), "open")
            run_cli("--root", str(root), "work", "link", "--trellis-task", "07-16-f2")
            for intent in ("plan", "work", "check"):
                run_cli("--root", str(root), "do", intent)
            prepared = run_cli(
                "--root", str(root), "gate", "policy", "set", "require-current-gate"
            )
            self.assertTrue(prepared["approval"].startswith("APPROVE-POLICY:"))
            applied = run_cli(
                "--root",
                str(root),
                "gate",
                "policy",
                "set",
                "require-current-gate",
                "--approve",
                prepared["approval"],
            )
            self.assertEqual(applied["receipt"]["kind"], "policy")
            run_cli("--root", str(root), "capabilities", "refresh")
            run_cli("--root", str(root), "work", "refresh")
            for arguments in (("do", "finish"), ("lifecycle", "finish")):
                code, _, error = invoke("--root", str(root), *arguments)
                self.assertEqual(code, 2)
                self.assertIn("finish blocked", error)

            evidence = receipts.record(
                root,
                "trellis",
                "intent/task-validate",
                "read",
                {},
                {},
                True,
                kind="gate",
                evidence_binding=contracts.evidence_binding(root),
            )
            linked = run_cli("--root", str(root), "gate", "reconcile", evidence["id"])
            self.assertEqual(linked["state"], "reconciled")
            self.assertEqual(run_cli("--root", str(root), "gate", "status")["state"], "aligned")
            finished = run_cli("--root", str(root), "do", "finish")
            self.assertEqual(finished["lifecycle"]["phase"], "finished")

    def test_validate_reconciles_only_matching_current_trellis_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._trellis_root(directory)
            run_cli("--root", str(root), "open")
            work = run_cli("--root", str(root), "work", "link", "--trellis-task", "07-16-f2")
            prepared = run_cli("--root", str(root), "do", "validate", "--task", "07-16-f2")
            completed = run_cli(
                "--root",
                str(root),
                "do",
                "validate",
                "--task",
                "07-16-f2",
                "--approve",
                prepared["approval"],
            )
            reconciliation = completed["result"]["gateReconciliation"]
            self.assertEqual(reconciliation["evidenceLink"]["workItemId"], work["id"])
            self.assertEqual(run_cli("--root", str(root), "gate", "status")["state"], "aligned")

    def test_stale_fingerprint_invalidates_gate_and_resume_prioritizes_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._trellis_root(directory)
            run_cli("--root", str(root), "open")
            run_cli("--root", str(root), "work", "link", "--trellis-task", "07-16-f2")
            evidence = receipts.record(
                root,
                "trellis",
                "quality-gate",
                "read",
                {},
                {},
                True,
                kind="gate",
                evidence_binding=contracts.evidence_binding(root),
            )
            run_cli("--root", str(root), "gate", "reconcile", evidence["id"])
            (root / "AGENTS.md").write_text("changed durable rule\n", encoding="utf-8")
            decision = run_cli("--root", str(root), "resume")["next"]
            self.assertEqual(decision["reasonCode"], "capability-cache-not-fresh")
            run_cli("--root", str(root), "capabilities", "refresh")
            decision = run_cli("--root", str(root), "resume")["next"]
            self.assertEqual(decision["reasonCode"], "work-item-fingerprint-stale")
            self.assertEqual(run_cli("--root", str(root), "gate", "status")["state"], "stale-evidence")

    def test_remember_resume_saga_completion_and_state_are_hash_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            gate = receipts.record(root, "trellis", "quality-gate", "read", {}, {}, True, kind="gate")
            receipts.record_verification(root, gate["id"], "verified targeted gate")
            lesson = "PRIVATE-F2-LESSON-DO-NOT-PERSIST"
            prepared = run_cli(
                "--root",
                str(root),
                "do",
                "remember",
                "--lesson",
                lesson,
                "--scope",
                "cross-project",
                "--receipt",
                gate["id"],
            )
            proposal = prepared["lessonProposal"]
            self.assertIn(f"--proposal {proposal['id']}", prepared["resumeCommand"])
            repeated = run_cli(
                "--root",
                str(root),
                "do",
                "remember",
                "--lesson",
                lesson,
                "--scope",
                "cross-project",
                "--receipt",
                gate["id"],
            )
            self.assertEqual(repeated["saga"]["id"], prepared["saga"]["id"])
            self.assertEqual(repeated["lessonProposal"]["id"], proposal["id"])
            self.assertEqual(len(list(ProjectPaths(root).sagas_dir.glob("saga-*.json"))), 1)
            executed = run_cli(
                "--root",
                str(root),
                "do",
                "remember",
                "--lesson",
                lesson,
                "--scope",
                "cross-project",
                "--receipt",
                gate["id"],
                "--proposal",
                proposal["id"],
                "--saga",
                prepared["saga"]["id"],
                "--approve",
                repeated["approval"],
            )
            write_receipt = executed["result"]["receipt"]["id"]
            next_step = run_cli("--root", str(root), "saga", "next", prepared["saga"]["id"])
            self.assertEqual(next_step["reasonCode"], "saga-nocturne-verification-required")
            verified = run_cli(
                "--root",
                str(root),
                "saga",
                "verify",
                prepared["saga"]["id"],
                write_receipt,
                "--evidence",
                "operator checked memory write",
            )
            self.assertEqual(verified["phase"], "completed")
            self.assertEqual(verified["lessonProposal"]["state"], "completed")
            persisted = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in ProjectPaths(root).state_dir.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(lesson, persisted)

    def test_partial_saga_can_be_closed_and_stops_preempting_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            saga = run_cli("--root", str(root), "saga", "create", "Recoverable failure")
            failed = receipts.record(root, "trellis", "quality-gate", "read", {}, {}, False, kind="gate")
            run_cli("--root", str(root), "saga", "attach", saga["id"], failed["id"])
            before = run_cli("--root", str(root), "resume")["next"]
            self.assertEqual(before["reasonCode"], "saga-incomplete")
            recovery = run_cli("--root", str(root), "saga", "next", saga["id"])
            self.assertEqual(recovery["command"], f"hellodev saga close {saga['id']}")
            closed = run_cli("--root", str(root), "saga", "close", saga["id"])
            self.assertEqual(closed["phase"], "closed")
            after = run_cli("--root", str(root), "resume")["next"]
            self.assertNotEqual(after["reasonCode"], "saga-incomplete")

    def test_delegate_audit_and_doctor_are_deterministic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            secret = "PRIVATE-TASK-TITLE-NOT-IN-AUDIT"
            run_cli("--root", str(root), "task", "create", secret)
            proposal = {
                "task": "Implement and review continuity",
                "intent": "code",
                "parallelizable": True,
                "sharedContext": "Bounded shared contract.",
                "candidates": [
                    {"role": "implement", "objective": "Implement contract", "contextDelta": "Source only."},
                    {"role": "review", "objective": "Review contract", "contextDelta": "Findings only."},
                ],
                "limits": {
                    "maxAgents": 2,
                    "sharedBytes": 1024,
                    "perAgentBytes": 2048,
                    "totalReportedTokenBudget": 1200,
                },
            }
            encoded = json.dumps(proposal)
            planned = run_cli("delegate", "plan", "--payload", encoded)
            self.assertEqual(planned["decision"], "delegate")
            packed = run_cli(
                "delegate", "pack", "--payload", encoded, "--role", "implement", "--token-budget", "600"
            )
            self.assertLessEqual(packed["byteCount"], packed["byteCap"])
            exported = run_cli("--root", str(root), "audit", "export")
            self.assertFalse(exported["persisted"])
            self.assertNotIn(secret, json.dumps(exported))
            hints = run_cli("--root", str(root), "doctor", "--fix-hints")["fixHints"]
            self.assertFalse(hints["executionPerformed"])
            self.assertEqual(len(hints["commands"]), 1)

    def test_optimize_cli_is_advisory_private_and_has_no_apply_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            optimization_path = ProjectPaths(root).optimization_file
            self.assertFalse(optimization_path.exists())
            status = run_cli("--root", str(root), "optimize", "status")
            planned = run_cli("--root", str(root), "optimize", "plan", "--intent", "code")
            proposals = run_cli("--root", str(root), "optimize", "proposals")
            self.assertEqual(status["usageState"], "unavailable")
            self.assertFalse(planned["executionPerformed"])
            self.assertFalse(proposals["applyAllowed"])
            self.assertFalse(optimization_path.exists())

            canary_source = "PRIVATE-OPTIMIZE-SOURCE"
            usage = run_cli(
                "--root",
                str(root),
                "usage",
                "record",
                "--total",
                "10000",
                "--subagent",
                "6000",
                "--subagents",
                "2",
                "--source",
                canary_source,
            )
            reflected = run_cli(
                "--root",
                str(root),
                "optimize",
                "reflect",
                "--intent",
                "code",
                "--context-level",
                "L1",
                "--outcome",
                "failed",
                "--usage",
                usage["id"],
                "--token-ceiling",
                "5000",
                "--subagent-token-ceiling",
                "2500",
                "--max-subagents",
                "2",
                "--delegation",
                "executed",
                "--retries",
                "2",
            )
            self.assertEqual(reflected["report"]["deepReflection"]["tokenCeiling"], 500)
            self.assertNotIn(canary_source, optimization_path.read_text(encoding="utf-8"))
            exported = run_cli("--root", str(root), "audit", "export")
            self.assertEqual(exported["optimization"]["traceCount"], 1)
            self.assertNotIn(canary_source, json.dumps(exported))

            with self.assertRaises(SystemExit) as denied:
                main(["--root", str(root), "optimize", "apply"])
            self.assertEqual(denied.exception.code, 2)

    def test_unknown_or_mismatched_continuity_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            for arguments, message in (
                (("work", "show", "work-9999"), "WorkItem not found"),
                (("lesson", "show", "lesson-9999"), "LessonProposal not found"),
                (("saga", "next", "saga-9999"), "saga not found"),
            ):
                code, _, error = invoke("--root", str(root), *arguments)
                self.assertEqual(code, 2)
                self.assertIn(message, error)


if __name__ == "__main__":
    unittest.main()
