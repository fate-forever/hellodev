from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import receipts
from hellodev.cli import main
from hellodev.project import ProjectPaths, configure_nocturne


FAKE_MCP_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def run_cli(*args: str) -> dict:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    if code:
        raise AssertionError(f"CLI failed with {code}: {stderr.getvalue()}")
    return json.loads(stdout.getvalue())


class F1CliTests(unittest.TestCase):
    def _trellis_root(self, directory: str) -> Path:
        root = Path(directory)
        scripts = root / ".trellis" / "scripts"
        scripts.mkdir(parents=True)
        (root / ".trellis" / "workflow.md").write_text("# Workflow\nUse gates.\n", encoding="utf-8")
        (scripts / "task.py").write_text(
            "import sys\nprint('native-task:' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        return root

    def _set_profile(self, root: Path, *arguments: str) -> dict:
        prepared = run_cli("--root", str(root), "profile", "set", *arguments)
        return run_cli(
            "--root",
            str(root),
            "profile",
            "set",
            *arguments,
            "--approve",
            prepared["approval"],
        )

    def test_root_help_leads_with_progressive_disclosure(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as stopped:
            main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("daily = open -> next -> do", text)
        self.assertIn("recovery = resume", text)
        self.assertIn("advanced = host, policy, drift, optimize", text)
        self.assertIn("usage, delegate, audit", text)

    def test_open_next_and_context_selection_are_compact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opened = run_cli("--root", str(root), "open")
            self.assertTrue(opened["created"])
            self.assertEqual(opened["phase"], "started")
            self.assertEqual(opened["next"]["command"], "hellodev do plan")

            resumed = run_cli("--root", str(root), "open")
            self.assertFalse(resumed["created"])
            self.assertEqual(resumed["phase"], "started")
            next_step = run_cli("--root", str(root), "next")
            status = run_cli("--root", str(root), "status")
            self.assertEqual(next_step["command"], "hellodev do plan")
            self.assertEqual(next_step["suggestedLevel"], "L1")
            self.assertLessEqual(len(json.dumps(next_step).encode("utf-8")), 1024)
            self.assertLessEqual(len(json.dumps(status).encode("utf-8")), 1024)

            suggestion = run_cli("context", "suggest", "--intent", "remember")
            self.assertEqual(suggestion["level"], "L2")
            brief = run_cli("--root", str(root), "brief", "build", "--intent", "status")
            self.assertEqual(brief["payload"]["level"], "L0")
            pack = run_cli("--root", str(root), "context", "pack", "--intent", "code")
            self.assertEqual(pack["level"], "L1")

    def test_do_runs_local_daily_flow_and_finish_only_suggests_remember(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            created = run_cli("--root", str(root), "do", "task", "create", "--title", "F1 task")
            self.assertEqual(created["backend"], "hellodev-local")
            self.assertEqual(created["result"]["title"], "F1 task")
            for intent, phase in (("plan", "planned"), ("work", "working"), ("check", "checking")):
                result = run_cli("--root", str(root), "do", intent)
                self.assertEqual(result["lifecycle"]["phase"], phase)
            finished = run_cli("--root", str(root), "do", "finish")
            self.assertEqual(finished["lifecycle"]["phase"], "finished")
            self.assertFalse(finished["rememberSuggestion"]["writePerformed"])
            self.assertIn("do remember", finished["rememberSuggestion"]["command"])

    def test_strict_and_trusted_local_use_same_do_command_then_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._trellis_root(directory)
            run_cli("--root", str(root), "open")
            strict = run_cli("--root", str(root), "do", "task", "list")
            self.assertEqual(strict["state"], "awaiting-confirmation")
            self.assertIn("do task list", strict["resumeCommand"])
            approved = run_cli(
                "--root",
                str(root),
                "do",
                "task",
                "list",
                "--approve",
                strict["approval"],
            )
            self.assertEqual(approved["result"]["exitCode"], 0)
            self.assertEqual(approved["authorization"]["authorizationMode"], "token-required")

            self._set_profile(root, "trusted-local", "--lease-ttl", "60")
            run_cli("--root", str(root), "capabilities", "refresh")
            first = run_cli("--root", str(root), "do", "task", "list")
            leased = run_cli(
                "--root",
                str(root),
                "do",
                "task",
                "list",
                "--approve",
                first["approval"],
            )
            self.assertIn("lease", leased["result"])
            automatic = run_cli("--root", str(root), "do", "task", "list")
            self.assertEqual(automatic["authorization"]["authorizationMode"], "lease-allowed")
            self.assertEqual(automatic["result"]["exitCode"], 0)

    def test_autopilot_recall_is_narrow_but_remember_write_still_needs_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._trellis_root(directory)
            run_cli("--root", str(root), "open")
            configure_nocturne(root, sys.executable, [str(FAKE_MCP_SERVER)], root)
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
            self._set_profile(
                root,
                "autopilot-read",
                "--memory-domain",
                "preferences",
                "--memory-limit",
                "3",
                "--expires-at",
                expires,
            )
            run_cli("--root", str(root), "capabilities", "refresh")
            recalled = run_cli(
                "--root",
                str(root),
                "do",
                "recall",
                "--query",
                "handoff preference unavailable locally",
                "--domain",
                "preferences",
                "--limit",
                "3",
                "--namespace-scope",
                "shared",
            )
            self.assertEqual(recalled["state"], "memory-result")
            self.assertEqual(recalled["authorization"]["authorizationMode"], "profile-auto")
            self.assertEqual(recalled["memory"]["sourceLabel"], "Long-term memory")

            gate = receipts.record(root, "trellis", "quality-gate", "read", {}, {}, True, kind="gate")
            receipts.record_verification(root, gate["id"], "targeted tests passed")
            lesson = "Always keep cross-project handoffs compact"
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
            self.assertEqual(prepared["state"], "awaiting-confirmation")
            self.assertTrue(prepared["approval"].startswith("APPROVE-WRITE:"))
            self.assertEqual(prepared["authorization"]["authorizationMode"], "token-required")
            saga_id = prepared["saga"]["id"]
            completed = run_cli(
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
                "--saga",
                saga_id,
                "--approve",
                prepared["approval"],
            )
            self.assertEqual(completed["state"], "verification-required")
            self.assertEqual(completed["result"]["saga"]["phase"], "nocturne-executed")
            stores = "\n".join(
                path.read_text(encoding="utf-8")
                for path in ProjectPaths(root).state_dir.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(lesson, stores)

    def test_recall_degrades_without_nocturne_and_profile_change_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            local_only = run_cli("--root", str(root), "recall", "--query", "unknown preference")
            self.assertEqual(local_only["state"], "local-only")
            changed = self._set_profile(root, "trusted-local", "--lease-ttl", "90")
            self.assertEqual(changed["policy"]["authorizationProfile"], "trusted-local")
            self.assertEqual(changed["receipt"]["kind"], "policy")


if __name__ == "__main__":
    unittest.main()
