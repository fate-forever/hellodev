from __future__ import annotations

import contextlib
import io
import json
import socket
import urllib.error
import urllib.request
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev.cli import main
from hellodev.snapshot import default_snapshot_path


FAKE_MCP_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"


def run_cli(*args: str) -> tuple[int, dict]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    if code:
        raise AssertionError(f"CLI failed with {code}: {stderr.getvalue()}")
    return code, json.loads(stdout.getvalue())


class HelloDevCliTests(unittest.TestCase):
    def test_init_is_idempotent_and_creates_only_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, first = run_cli("--root", str(root), "init")
            _, second = run_cli("--root", str(root), "init")
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertTrue((root / ".hellodev" / "config.json").is_file())
            self.assertTrue((root / ".hellodev" / "tasks").is_dir())
            self.assertEqual(list(root.iterdir()), [root / ".hellodev"])

    def test_task_lifecycle_uses_markdown_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            _, created = run_cli("--root", str(root), "task", "create", "Implement direct CLI")
            _, listed = run_cli("--root", str(root), "task", "list")
            _, shown = run_cli("--root", str(root), "task", "show", "task-0001")
            self.assertEqual(created["id"], "task-0001")
            self.assertEqual(listed["tasks"][0]["title"], "Implement direct CLI")
            self.assertEqual(shown["status"], "open")
            self.assertTrue((root / ".hellodev" / "tasks" / "task-0001.md").is_file())

    def test_init_rejects_state_file_at_hellodev_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".hellodev").write_text("not a directory", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["--root", str(root), "init"])
            self.assertEqual(code, 2)
            self.assertIn(".hellodev is not a directory", stderr.getvalue())

    def test_start_reports_uninitialized_project_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, started = run_cli("--root", str(root), "start")
            self.assertEqual(started["state"], "uninitialized")
            self.assertFalse(started["initialized"])
            self.assertEqual(started["phase"], None)
            self.assertEqual(started["next"], "hellodev open")
            self.assertEqual(list(root.iterdir()), [])

    def test_start_initializes_lifecycle_and_capability_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            _, started = run_cli("--root", str(root), "start")
            _, status = run_cli("--root", str(root), "status")
            _, verbose = run_cli("--root", str(root), "status", "--verbose")
            self.assertEqual(started["phase"], "started")
            self.assertEqual(started["next"], "hellodev do plan")
            self.assertEqual(status["phase"], "started")
            self.assertEqual(verbose["capabilities"]["state"], "fresh")
            self.assertEqual(verbose["lifecycle"]["phase"], "started")

    def test_lifecycle_transitions_are_ordered_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "start")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["--root", str(root), "lifecycle", "finish"])
            self.assertEqual(code, 2)
            self.assertIn("cannot transition", stderr.getvalue())
            _, planned = run_cli("--root", str(root), "lifecycle", "plan", "--note", "task planned")
            _, working = run_cli("--root", str(root), "lifecycle", "work")
            _, blocked = run_cli("--root", str(root), "lifecycle", "block", "--note", "waiting")
            _, resumed = run_cli("--root", str(root), "lifecycle", "resume")
            self.assertEqual(planned["phase"], "planned")
            self.assertEqual(working["phase"], "working")
            self.assertEqual(blocked["resumePhase"], "working")
            self.assertEqual(resumed["phase"], "working")

    def test_bounded_briefs_cache_context_and_detect_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "spec" / "context").mkdir(parents=True)
            (root / ".trellis" / "workflow.md").write_text("# Workflow\nUse gates.\n", encoding="utf-8")
            (root / ".trellis" / "spec" / "context" / "CONTEXT.md").write_text(
                "# Context\nProject terms.\n", encoding="utf-8"
            )
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "start")
            run_cli("--root", str(root), "task", "create", "Build brief cache")
            _, l0 = run_cli("--root", str(root), "brief", "build", "--task", "task-0001")
            _, cached_l0 = run_cli("--root", str(root), "brief", "build", "--task", "task-0001")
            _, l1 = run_cli("--root", str(root), "brief", "build", "--level", "L1", "--task", "task-0001")
            self.assertEqual(l0["payload"]["level"], "L0")
            self.assertEqual(l0["payload"]["sources"], [])
            self.assertTrue(cached_l0["cached"])
            self.assertEqual({source["path"] for source in l1["payload"]["sources"]}, {
                ".hellodev/tasks/task-0001.md",
                ".trellis/workflow.md",
                ".trellis/spec/context/CONTEXT.md",
            })
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["--root", str(root), "brief", "build", "--level", "L2", "--task", "task-0001"])
            self.assertEqual(code, 2)
            self.assertIn("requires --allow-l2", stderr.getvalue())
            task_path = root / ".hellodev" / "tasks" / "task-0001.md"
            task_path.write_text(task_path.read_text(encoding="utf-8") + "\nNew detail.\n", encoding="utf-8")
            _, stale = run_cli("--root", str(root), "brief", "show", "--level", "L1", "--task", "task-0001")
            self.assertEqual(stale["state"], "stale")

    def test_fingerprint_content_inputs_and_context_pack_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "scripts").mkdir(parents=True)
            (root / ".trellis" / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
            (root / ".trellis" / "scripts" / "gate.py").write_text("print('one')\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "start")
            _, initial = run_cli("--root", str(root), "capabilities", "status")
            (root / ".trellis" / "scripts" / "gate.py").write_text("print('two')\n", encoding="utf-8")
            _, stale = run_cli("--root", str(root), "capabilities", "status")
            self.assertEqual(initial["state"], "fresh")
            self.assertEqual(stale["state"], "stale")
            _, pack = run_cli(
                "--root", str(root), "context", "pack", "--level", "L1", "--token-budget", "128"
            )
            self.assertLessEqual(len(pack["text"].encode("utf-8")), pack["byteCap"])
            self.assertTrue(pack["budgetContract"].startswith("conservative"))
            self.assertIn("HelloDev context pack", pack["text"])

    def test_trellis_detection_is_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            (root / ".trellis" / "workflow.md").write_text("# workflow\n", encoding="utf-8")
            (root / ".trellis" / "spec" / "context").mkdir(parents=True)
            (root / ".trellis" / "spec" / "context" / "CONTEXT.md").write_text("# context\n", encoding="utf-8")
            (root / ".trellis" / "tasks" / "task.md").write_text("# task\n", encoding="utf-8")
            (root / ".trellis" / "tasks" / "07-15-native-task").mkdir()
            (root / ".trellis" / "tasks" / "archive").mkdir()
            _, result = run_cli("--root", str(root), "trellis", "status")
            self.assertEqual(result["state"], "detected")
            self.assertTrue(result["workflow"])
            self.assertTrue(result["context"])
            self.assertEqual(result["taskCount"], 2)
            self.assertEqual(result["execution"], "requires-one-time-approval")

    def test_nocturne_requires_explicit_project_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, result = run_cli("--root", directory, "nocturne", "status")
            self.assertEqual(result["state"], "unconfigured")
            self.assertEqual(result["execution"], "requires-one-time-approval")

    def test_nocturne_stdio_mcp_reads_and_writes_with_one_time_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            _, configured = run_cli(
                "--root",
                str(root),
                "nocturne",
                "configure",
                "--command",
                sys.executable,
                "--arg",
                str(FAKE_MCP_SERVER),
                "--cwd",
                str(root),
            )
            self.assertEqual(configured["mode"], "stdio")
            _, plan = run_cli("--root", str(root), "nocturne", "tools")
            self.assertTrue(plan["approval"].startswith("APPROVE-EXTERNAL:"))
            _, tools = run_cli(
                "--root", str(root), "nocturne", "tools", "--approve", plan["approval"]
            )
            self.assertEqual(tools["result"]["tools"][0]["name"], "read_memory")
            _, write_plan = run_cli(
                "--root",
                str(root),
                "nocturne",
                "call",
                "create_memory",
                "--params",
                '{"content":"safe fixture"}',
            )
            self.assertTrue(write_plan["approval"].startswith("APPROVE-WRITE:"))
            _, write_result = run_cli(
                "--root",
                str(root),
                "nocturne",
                "call",
                "create_memory",
                "--params",
                '{"content":"safe fixture"}',
                "--approve",
                write_plan["approval"],
            )
            self.assertEqual(write_result["tool"], "create_memory")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--root",
                        str(root),
                        "nocturne",
                        "call",
                        "create_memory",
                        "--params",
                        '{"content":"safe fixture"}',
                        "--approve",
                        write_plan["approval"],
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("already consumed", stderr.getvalue())

    def test_trellis_adapter_binds_command_to_one_time_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            with patch("hellodev.adapters.trellis.executable", return_value=sys.executable):
                _, plan = run_cli("--root", str(root), "trellis", "prepare", "--", "--version")
                self.assertTrue(plan["approval"].startswith("APPROVE-EXTERNAL:"))
                _, result = run_cli(
                    "--root", str(root), "trellis", "run", "--approve", plan["approval"], "--", "--version"
                )
            self.assertEqual(result["exitCode"], 0)
            self.assertIn("Python", result["stdout"])

    def test_saga_requires_verified_trellis_before_nocturne_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "start")
            _, saga = run_cli("--root", str(root), "saga", "create", "Persist verified lesson")
            scripts = root / ".trellis" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "task.py").write_text("import sys\nprint('gate passed')\n", encoding="utf-8")
            _, trellis_plan = run_cli(
                "--root", str(root), "trellis", "intent", "task-validate", "--task", "07-15-p0"
            )
            _, trellis_result = run_cli(
                "--root",
                str(root),
                "trellis",
                "intent",
                "task-validate",
                "--task",
                "07-15-p0",
                "--approve",
                trellis_plan["approval"],
            )
            self.assertEqual(trellis_result["receipt"]["kind"], "gate")
            _, attached = run_cli("--root", str(root), "saga", "attach", saga["id"], trellis_result["receipt"]["id"])
            self.assertEqual(attached["phase"], "trellis-executed")
            _, verified = run_cli(
                "--root",
                str(root),
                "saga",
                "verify",
                saga["id"],
                trellis_result["receipt"]["id"],
                "--evidence",
                "test command exited successfully",
            )
            self.assertEqual(verified["phase"], "trellis-verified")
            run_cli(
                "--root",
                str(root),
                "nocturne",
                "configure",
                "--command",
                sys.executable,
                "--arg",
                str(FAKE_MCP_SERVER),
                "--cwd",
                str(root),
            )
            _, nocturne_plan = run_cli(
                "--root",
                str(root),
                "nocturne",
                "call",
                "create_memory",
                "--params",
                '{"content":"verified lesson"}',
            )
            _, nocturne_result = run_cli(
                "--root",
                str(root),
                "nocturne",
                "call",
                "create_memory",
                "--params",
                '{"content":"verified lesson"}',
                "--saga",
                saga["id"],
                "--approve",
                nocturne_plan["approval"],
            )
            self.assertEqual(nocturne_result["saga"]["phase"], "nocturne-executed")
            _, completed = run_cli(
                "--root",
                str(root),
                "saga",
                "verify",
                saga["id"],
                nocturne_result["receipt"]["id"],
                "--evidence",
                "fixture MCP returned success",
            )
            self.assertEqual(completed["phase"], "completed")
            _, receipt_list = run_cli("--root", str(root), "receipt", "list")
            self.assertEqual([receipt["kind"] for receipt in receipt_list["receipts"]], ["gate", "verification", "command", "verification"])
            self.assertNotIn("verified lesson", json.dumps(receipt_list))

    def test_smart_layer_routes_without_automatic_memory_access(self) -> None:
        _, project_lesson = run_cli(
            "smart", "classify", "--lesson", "This project workflow test gate must run before release."
        )
        _, preference_lesson = run_cli(
            "smart", "classify", "--lesson", "This is my preference across projects: always keep output compact."
        )
        self.assertEqual(project_lesson["destination"], "trellis")
        self.assertEqual(preference_lesson["destination"], "nocturne")
        self.assertEqual(preference_lesson["autonomy"], "prepare-only")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "start")
            _, project_plan = run_cli(
                "--root", str(root), "smart", "retrieve", "--scope", "project", "--query", "release", "--level", "L1"
            )
            _, cross_plan = run_cli(
                "--root",
                str(root),
                "smart",
                "retrieve",
                "--scope",
                "cross-project",
                "--query",
                "preference",
                "--domain",
                "preferences",
                "--limit",
                "5",
                "--namespace-scope",
                "shared",
            )
            _, persist_plan = run_cli("--root", str(root), "smart", "persist", "--destination", "nocturne")
            self.assertEqual(project_plan["nocturne"], "not-queried")
            self.assertEqual(cross_plan["state"], "configuration-required")
            self.assertEqual(cross_plan["nocturne"]["parameters"], {"query": "preference", "domain": "preferences", "limit": 5})
            self.assertEqual(persist_plan["autonomy"], "evidence-required")

    def test_smart_retrieval_requires_explicit_narrow_scope_and_can_prepare_nocturne(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            run_cli(
                "--root",
                str(root),
                "nocturne",
                "configure",
                "--command",
                sys.executable,
                "--arg",
                str(FAKE_MCP_SERVER),
            )
            _, prepared = run_cli(
                "--root",
                str(root),
                "smart",
                "retrieve",
                "--scope",
                "cross-project",
                "--query",
                "handoff",
                "--domain",
                "preferences",
                "--limit",
                "3",
                "--namespace-scope",
                "shared",
            )
            self.assertEqual(prepared["state"], "awaiting-confirmation")
            self.assertNotIn("namespace", prepared["nocturne"]["parameters"])
            _, result = run_cli(
                "--root",
                str(root),
                "smart",
                "retrieve",
                "--scope",
                "cross-project",
                "--query",
                "handoff",
                "--domain",
                "preferences",
                "--limit",
                "3",
                "--namespace-scope",
                "shared",
                "--approve",
                prepared["approval"],
            )
            self.assertEqual(result["receipt"]["kind"], "command")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--root",
                        str(root),
                        "smart",
                        "retrieve",
                        "--scope",
                        "cross-project",
                        "--query",
                        "handoff",
                        "--domain",
                        "global",
                        "--limit",
                        "3",
                        "--namespace-scope",
                        "shared",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("explicit narrow value", stderr.getvalue())

    def test_delegate_audit_and_reported_usage_are_explicit(self) -> None:
        payload = {
            "mainAgentEffort": "large",
            "parallelBenefit": "material",
            "userExplicitlyRequested": False,
            "context": {
                "userRequest": "Audit two independent modules",
                "repositoryRoot": "C:/repo",
                "authorityStatus": "no Trellis",
                "workflowState": "started",
                "taskState": "working",
                "returnFormat": "short report",
            },
            "candidates": [
                {"role": "review", "objective": "review", "deliverable": "report", "independent": True, "writePaths": []},
                {"role": "tests", "objective": "test", "deliverable": "results", "independent": True, "writePaths": []},
            ],
        }
        _, audit = run_cli("delegate", "audit", "--payload", json.dumps(payload))
        self.assertTrue(audit["delegate"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "usage", "record", "--total", "120", "--subagent", "40", "--subagents", "2", "--source", "api-receipt")
            _, status = run_cli("--root", str(root), "usage", "status")
            self.assertEqual(status["rootTokens"], 80)
            self.assertIn("reported-only", status["accuracy"])

    def test_standalone_dashboard_start_status_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_cli("--root", str(root), "init")
            run_cli("--root", str(root), "start")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            _, started = run_cli("--root", str(root), "dashboard", "start", "--port", str(port))
            _, status = run_cli("--root", str(root), "dashboard", "status")
            self.assertTrue(started["running"])
            self.assertIn("?token=", started["url"])
            self.assertTrue(status["running"])
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2)
            self.assertEqual(denied.exception.code, 401)
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with opener.open(started["url"], timeout=2):
                pass
            with opener.open(f"http://127.0.0.1:{port}/api/status", timeout=2) as response:
                dashboard = json.loads(response.read().decode("utf-8"))
            self.assertNotIn("actionToken", dashboard)
            self.assertEqual(
                {item["command"] for item in dashboard["actions"]},
                {
                    "hellodev capabilities refresh",
                    "hellodev brief build --level L0",
                    "hellodev lifecycle plan",
                    "hellodev lifecycle work",
                },
            )
            action_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/action",
                method="POST",
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
                data=json.dumps({"action": "lifecycle.plan", "args": {}}).encode("utf-8"),
            )
            with self.assertRaises(urllib.error.HTTPError) as absent_action:
                opener.open(action_request, timeout=2)
            self.assertEqual(absent_action.exception.code, 405)
            _, lifecycle_state = run_cli("--root", str(root), "lifecycle", "status")
            self.assertEqual(lifecycle_state["phase"], "started")
            _, stopped = run_cli("--root", str(root), "dashboard", "stop")
            self.assertFalse(stopped["running"])

    def test_snapshot_verification_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "ignored.pyc").write_bytes(b"x")
            (root / "demo.egg-info").mkdir()
            (root / "demo.egg-info" / "ignored.txt").write_text("x", encoding="utf-8")
            _, first = run_cli("snapshot", "verify", "--path", str(root))
            _, second = run_cli("snapshot", "verify", "--path", str(root))
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(first["fileCount"], 1)

    def test_default_snapshot_path_uses_source_root_or_installed_package(self) -> None:
        self.assertEqual(default_snapshot_path(), PACKAGE_ROOT)
        with tempfile.TemporaryDirectory() as directory:
            installed_module = Path(directory) / "site-packages" / "hellodev" / "snapshot.py"
            installed_module.parent.mkdir(parents=True)
            installed_module.write_text("# installed\n", encoding="utf-8")
            self.assertEqual(default_snapshot_path(installed_module), installed_module.parent)


if __name__ == "__main__":
    unittest.main()
