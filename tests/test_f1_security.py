from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import receipts
from hellodev.cli import main
from hellodev.project import configure_nocturne


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


class F1SecurityTests(unittest.TestCase):
    def _trellis_root(self, directory: str) -> Path:
        root = Path(directory)
        scripts = root / ".trellis" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "task.py").write_text("import sys\nprint('task:' + ' '.join(sys.argv[1:]))\n", encoding="utf-8")
        run_cli("--root", str(root), "open")
        return root

    def _configured_root(self, directory: str) -> tuple[Path, Path]:
        root = Path(directory)
        run_cli("--root", str(root), "open")
        server = root / "fake_mcp_server.py"
        shutil.copyfile(FAKE_MCP_SERVER, server)
        configure_nocturne(root, sys.executable, [str(server)], root)
        return root, server

    def test_trellis_token_rejects_script_replacement_after_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._trellis_root(directory)
            prepared = run_cli("--root", str(root), "do", "task", "list")
            script = root / ".trellis" / "scripts" / "task.py"
            script.write_text("print('replacement')\n", encoding="utf-8")
            code, _, error = invoke(
                "--root",
                str(root),
                "do",
                "task",
                "list",
                "--approve",
                prepared["approval"],
            )
            self.assertEqual(code, 2)
            self.assertIn("does not match", error)

    def test_nocturne_token_rejects_server_replacement_after_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, server = self._configured_root(directory)
            prepared = run_cli(
                "--root",
                str(root),
                "nocturne",
                "call",
                "search_memory",
                "--params",
                '{"query":"bounded"}',
            )
            server.write_text(server.read_text(encoding="utf-8") + "\n# replacement\n", encoding="utf-8")
            code, _, error = invoke(
                "--root",
                str(root),
                "nocturne",
                "call",
                "search_memory",
                "--params",
                '{"query":"bounded"}',
                "--approve",
                prepared["approval"],
            )
            self.assertEqual(code, 2)
            self.assertIn("does not match", error)

    def test_mcp_error_marks_recall_failed_and_remember_saga_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._configured_root(directory)
            recall_plan = run_cli(
                "--root",
                str(root),
                "recall",
                "--query",
                "force-mcp-error",
                "--domain",
                "preferences",
                "--limit",
                "2",
                "--namespace-scope",
                "shared",
            )
            recalled = run_cli(
                "--root",
                str(root),
                "recall",
                "--query",
                "force-mcp-error",
                "--domain",
                "preferences",
                "--limit",
                "2",
                "--namespace-scope",
                "shared",
                "--approve",
                recall_plan["approval"],
            )
            self.assertEqual(recalled["state"], "memory-error")
            self.assertEqual(recalled["memory"]["receipt"]["outcome"], "failed")

            gate = receipts.record(root, "trellis", "quality-gate", "read", {}, {}, True, kind="gate")
            receipts.record_verification(root, gate["id"], "gate passed")
            remember_plan = run_cli(
                "--root",
                str(root),
                "remember",
                "--lesson",
                "Always force-mcp-error for this fixture",
                "--scope",
                "cross-project",
                "--receipt",
                gate["id"],
            )
            saga_id = remember_plan["saga"]["id"]
            remembered = run_cli(
                "--root",
                str(root),
                "remember",
                "--lesson",
                "Always force-mcp-error for this fixture",
                "--scope",
                "cross-project",
                "--receipt",
                gate["id"],
                "--saga",
                saga_id,
                "--approve",
                remember_plan["approval"],
            )
            self.assertEqual(remembered["state"], "partial")
            self.assertEqual(remembered["result"]["receipt"]["outcome"], "failed")
            self.assertEqual(remembered["result"]["saga"]["phase"], "partial")


if __name__ == "__main__":
    unittest.main()
