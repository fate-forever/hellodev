from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import capabilities, contracts, dashboard, receipts, verification
from hellodev.application import ProjectClient
from hellodev.cli import main
from hellodev.mcp_gateway import TOOL_NAMES
from hellodev.project import ProjectError, ProjectPaths, init_project


def invoke(*args: str) -> tuple[int, dict | None, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *args])
    value = json.loads(stdout.getvalue()) if code == 0 and stdout.getvalue() else None
    return code, value, stderr.getvalue()


class V18ProgressiveVerificationTests(unittest.TestCase):
    def _project(self, directory: str) -> tuple[Path, ProjectClient]:
        root = Path(directory)
        (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
        client = ProjectClient(root)
        client.do(
            "begin",
            {"goal": "Progressive verification", "acceptance": "project verification succeeds"},
        )
        return root, client

    def test_success_is_reused_only_for_the_exact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            planned = client.do("verify", {"level": "T1", "command": "pytest tests/unit -q"})["result"]
            self.assertEqual(planned["state"], "run-required")
            recorded = client.do(
                "verify",
                {
                    "level": "T1",
                    "command": "pytest tests/unit -q",
                    "snapshot": planned["repositorySnapshot"],
                    "outcome": "succeeded",
                    "duration_ms": 125,
                },
            )["result"]
            self.assertEqual(recorded["state"], "recorded")
            reused = client.do("verify", {"level": "T1", "command": "pytest tests/unit -q"})["result"]
            self.assertEqual(reused["state"], "reused-success")
            self.assertEqual(reused["estimatedAvoidedDurationMs"], 125)
            stronger = client.do("verify", {"level": "T2", "command": "pytest tests/unit -q"})["result"]
            self.assertEqual(stronger["state"], "run-required")

            (root / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
            changed = client.do("verify", {"level": "T1", "command": "pytest tests/unit -q"})["result"]
            self.assertEqual(changed["state"], "run-required")
            self.assertNotEqual(changed["repositorySnapshot"], planned["repositorySnapshot"])

    def test_unchanged_failure_blocks_repeat_and_stale_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            planned = client.do("verify", {"level": "T0", "command": "python -m compileall src.py"})["result"]
            client.do(
                "verify",
                {
                    "level": "T0",
                    "command": "python -m compileall src.py",
                    "snapshot": planned["repositorySnapshot"],
                    "outcome": "failed",
                },
            )
            blocked = client.do("verify", {"level": "T0", "command": "python -m compileall src.py"})["result"]
            self.assertEqual(blocked["state"], "blocked-unchanged-failure")
            with self.assertRaisesRegex(ProjectError, "cannot be recorded again"):
                client.do(
                    "verify",
                    {
                        "level": "T0",
                        "command": "python -m compileall src.py",
                        "snapshot": planned["repositorySnapshot"],
                        "outcome": "failed",
                    },
                )

            next_plan = client.do("verify", {"level": "T2", "command": "pytest -q"})["result"]
            (root / "src.py").write_text("VALUE = 3\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "repository changed"):
                client.do(
                    "verify",
                    {
                        "level": "T2",
                        "command": "pytest -q",
                        "snapshot": next_plan["repositorySnapshot"],
                        "outcome": "succeeded",
                    },
                )

    def test_store_is_hash_only_idempotent_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            raw_command = "pytest secret_test_name -q"
            planned = verification.plan(root, "T1", raw_command)
            first = verification.record(root, "T1", raw_command, planned["repositorySnapshot"], "succeeded", 10)
            second = verification.record(root, "T1", raw_command, planned["repositorySnapshot"], "succeeded", 10)
            self.assertEqual(first["state"], "recorded")
            self.assertEqual(second["state"], "already-recorded")
            raw = ProjectPaths(root).verification_file.read_text(encoding="utf-8")
            self.assertNotIn(raw_command, raw)
            self.assertNotIn("output", raw.lower())

            ProjectPaths(root).verification_file.write_text('{"schemaVersion":1,"records":[{}]}', encoding="utf-8")
            with self.assertRaisesRegex(ProjectError, "record fields"):
                verification.summary(root)

    def test_source_mutation_invalidates_trellis_gate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_project(root)
            (root / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / ".trellis" / "tasks" / "07-22-current").mkdir(parents=True)
            capabilities.refresh(root)
            contracts.create_work_item(root, "trellis", "07-22-current")
            gate = receipts.record(
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
            link = contracts.reconcile_evidence(root, gate["id"])
            self.assertEqual(contracts.current_valid_evidence_links(root), [link])
            (root / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
            self.assertEqual(contracts.current_valid_evidence_links(root), [])

    def test_cli_client_mcp_and_dashboard_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, client = self._project(directory)
            client_value = client.do("verify", {"level": "T0", "command": "python -m compileall src.py"})
            code, cli_value, error = invoke(
                "--root", str(root), "do", "verify", "--level", "T0", "--command", "python -m compileall src.py"
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(cli_value["result"]["state"], client_value["result"]["state"])
            self.assertEqual(len(TOOL_NAMES), 6)
            self.assertIn("hellodev_do", TOOL_NAMES)
            control = dashboard.snapshot(root, "instance", "started")
            self.assertEqual(control["schemaVersion"], 23)
            self.assertEqual(control["verification"]["sourceTrust"], "host-asserted")
            self.assertFalse(control["verification"]["rawCommandPersisted"])

    def test_unknown_fields_and_types_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, client = self._project(directory)
            with self.assertRaisesRegex(ProjectError, "unsupported verify"):
                client.do("verify", {"level": "T0", "command": "pytest", "unknown": True})
            with self.assertRaisesRegex(ProjectError, "duration_ms must be an integer"):
                client.do("verify", {"level": "T0", "command": "pytest", "duration_ms": "1"})
            with self.assertRaisesRegex(ProjectError, "requires snapshot"):
                client.do("verify", {"level": "T0", "command": "pytest", "outcome": "succeeded"})


if __name__ == "__main__":
    unittest.main()
