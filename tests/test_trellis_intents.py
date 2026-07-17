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


def run_cli(*args: str) -> tuple[int, dict]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    if code:
        raise AssertionError(f"CLI failed with {code}: {stderr.getvalue()}")
    return code, json.loads(stdout.getvalue())


class TrellisIntentTests(unittest.TestCase):
    def _root_with_native_task_script(self, root: Path) -> None:
        scripts = root / ".trellis" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "task.py").write_text("import sys\nprint('native-task:' + ' '.join(sys.argv[1:]))\n", encoding="utf-8")

    def test_task_and_gate_intents_bind_native_script_and_one_time_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._root_with_native_task_script(root)
            run_cli("--root", str(root), "init")
            _, plan = run_cli("--root", str(root), "trellis", "intent", "task-list")
            self.assertEqual(plan["risk"], "read")
            self.assertTrue(plan["argv"][-2].endswith("task.py"))
            self.assertEqual(plan["argv"][-1], "list")
            _, result = run_cli(
                "--root", str(root), "trellis", "intent", "task-list", "--approve", plan["approval"]
            )
            self.assertEqual(result["exitCode"], 0)
            self.assertIn("native-task:list", result["stdout"])
            _, gate = run_cli("--root", str(root), "trellis", "intent", "task-validate", "--task", "07-15-p0")
            self.assertEqual(gate["risk"], "read")
            self.assertEqual(gate["intent"], "task-validate")

    def test_channel_rename_is_structured_write_and_worktree_is_an_explicit_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._root_with_native_task_script(root)
            run_cli("--root", str(root), "init")
            with patch("hellodev.adapters.trellis.executable", return_value=sys.executable):
                _, plan = run_cli(
                    "--root",
                    str(root),
                    "trellis",
                    "intent",
                    "channel-thread-rename",
                    "--channel",
                    "design-feedback",
                    "--old-thread",
                    "old-key",
                    "--new-thread",
                    "new-key",
                    "--as",
                    "main",
                )
            self.assertEqual(plan["risk"], "write")
            self.assertEqual(plan["argv"][-10:], [
                "channel", "thread", "rename", "design-feedback", "old-key", "new-key", "--as", "main", "--scope", "project"
            ])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["--root", str(root), "trellis", "intent", "worktree"])
            self.assertEqual(code, 2)
            self.assertIn("unsupported", stderr.getvalue())
