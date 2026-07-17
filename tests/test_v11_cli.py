from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev.cli import main


def run_cli(*args: str) -> dict:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    if code:
        raise AssertionError(f"CLI failed with {code}: {stderr.getvalue()}")
    return json.loads(stdout.getvalue())


class V11CliTests(unittest.TestCase):
    def _proposal(self, root: Path) -> str:
        for retries in (2, 3, 4):
            run_cli(
                "--root", str(root), "optimize", "reflect",
                "--intent", "code", "--context-level", "L1",
                "--outcome", "partial", "--retries", str(retries),
            )
        return run_cli("--root", str(root), "optimize", "proposals")["proposals"][0]["id"]

    def _baseline(self, root: Path, count: int) -> None:
        result = {
            "outcome": "succeeded", "retryCount": 1,
            "retrievalMode": "none", "delegationMode": "none",
            "totalTokens": None, "subagentTokens": None, "subagentCount": 0,
        }
        for _ in range(count):
            envelope = run_cli("--root", str(root), "host", "prepare", "--intent", "code")
            run_cli(
                "--root", str(root), "host", "complete",
                "--envelope", json.dumps(envelope, separators=(",", ":")),
                "--result", json.dumps(result, separators=(",", ":")),
            )

    def test_host_prepare_complete_and_drift_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            envelope = run_cli(
                "--root", str(root), "host", "prepare",
                "--intent", "code", "--total-token-ceiling", "2000",
            )
            result = {
                "outcome": "succeeded", "retryCount": 0,
                "retrievalMode": "none", "delegationMode": "none",
                "totalTokens": 1000, "subagentTokens": 0, "subagentCount": 0,
            }
            completed = run_cli(
                "--root", str(root), "host", "complete",
                "--envelope", json.dumps(envelope, separators=(",", ":")),
                "--result", json.dumps(result, separators=(",", ":")),
            )
            self.assertEqual(completed["state"], "completed")
            self.assertEqual(run_cli("--root", str(root), "host", "status")["completionCount"], 1)
            self.assertEqual(run_cli("--root", str(root), "drift", "status")["state"], "clean")

    def test_host_complete_accepts_strict_stdin_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            envelope = run_cli("--root", str(root), "host", "prepare", "--intent", "code")
            result = {
                "outcome": "succeeded", "retryCount": 0,
                "retrievalMode": "none", "delegationMode": "none",
                "totalTokens": None, "subagentTokens": None, "subagentCount": 0,
            }
            payload = json.dumps({"envelope": envelope, "result": result}, separators=(",", ":"))
            with patch("sys.stdin", io.StringIO(payload)):
                completed = run_cli("--root", str(root), "host", "complete", "--stdin")
            self.assertEqual(completed["state"], "completed")

            with patch("sys.stdin", io.StringIO(json.dumps({"envelope": envelope, "result": result, "extra": 1}))):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(["--json", "--root", str(root), "host", "complete", "--stdin"])
            self.assertEqual(code, 2)
            self.assertIn("exactly {envelope,result}", stderr.getvalue())

    def test_policy_stage_cancel_cli_is_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            proposal = self._proposal(root)
            run_cli("--root", str(root), "policy", "stage", "--proposal", proposal)
            cancelled = run_cli("--root", str(root), "policy", "cancel", "--proposal", proposal)
            repeated = run_cli("--root", str(root), "policy", "cancel", "--proposal", proposal)
            self.assertEqual(cancelled["state"], "stage-cancelled")
            self.assertEqual(repeated["state"], "existing")

    def test_policy_two_phase_cli_canary_commit_and_revert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "open")
            self._baseline(root, 1)
            proposal = self._proposal(root)
            run_cli("--root", str(root), "policy", "stage", "--proposal", proposal)
            prepared = run_cli(
                "--root", str(root), "policy", "canary", "--proposal", proposal,
                "--turns", "1", "--ttl", "3600",
            )
            self.assertIn("policy canary", prepared["resumeCommand"])
            started = run_cli(
                "--root", str(root), "policy", "canary", "--proposal", proposal,
                "--turns", "1", "--ttl", "3600", "--approve", prepared["approval"],
            )
            recovered_canary = run_cli(
                "--root", str(root), "policy", "canary", "--proposal", proposal,
                "--turns", "1", "--ttl", "3600", "--receipt", started["receipt"]["id"],
            )
            self.assertEqual(recovered_canary["state"], "existing")
            envelope = run_cli("--root", str(root), "host", "prepare", "--intent", "code")
            result = {
                "outcome": "succeeded", "retryCount": 1,
                "retrievalMode": "none", "delegationMode": "none",
                "totalTokens": None, "subagentTokens": None, "subagentCount": 0,
            }
            run_cli(
                "--root", str(root), "host", "complete",
                "--envelope", json.dumps(envelope, separators=(",", ":")),
                "--result", json.dumps(result, separators=(",", ":")),
            )
            self.assertEqual(run_cli("--root", str(root), "policy", "evaluate", "--proposal", proposal)["state"], "passed")
            commit = run_cli("--root", str(root), "policy", "commit", "--proposal", proposal)
            committed = run_cli(
                "--root", str(root), "policy", "commit", "--proposal", proposal,
                "--approve", commit["approval"],
            )
            recovered_commit = run_cli(
                "--root", str(root), "policy", "commit", "--proposal", proposal,
                "--receipt", committed["receipt"]["id"],
            )
            self.assertEqual(recovered_commit["state"], "existing")
            self.assertEqual(run_cli("--root", str(root), "policy", "status")["effectivePolicy"]["retry.maxAttempts"], 2)
            revert = run_cli("--root", str(root), "policy", "revert")
            reverted = run_cli("--root", str(root), "policy", "revert", "--approve", revert["approval"])
            recovered_revert = run_cli(
                "--root", str(root), "policy", "revert", "--receipt", reverted["receipt"]["id"],
            )
            self.assertEqual(recovered_revert["state"], "existing")
            self.assertEqual(run_cli("--root", str(root), "policy", "status")["effectivePolicy"]["retry.maxAttempts"], 3)

    def test_policy_has_no_direct_apply_or_unapproved_commit_surface(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
            main(["policy", "apply"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
