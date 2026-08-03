from __future__ import annotations

import hashlib
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, contracts, lifecycle, trellis_bridge
from hellodev.application import ProjectClient
from hellodev.cli import main
from hellodev.project import ProjectError


class V209AcceptanceIntegrityTests(unittest.TestCase):
    def test_cli_accepts_project_relative_requirements_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "requirements.md").write_text("- Preserve every requirement\n", encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "--json", "--root", str(root), "do", "begin",
                        "--goal", "Implement feature",
                        "--acceptance", "tests pass",
                        "--requirements-file", "requirements.md",
                    ]
                )
            self.assertEqual(code, 0, stderr.getvalue())
            value = json.loads(stdout.getvalue())
            self.assertEqual(
                value["acceptanceContract"]["requirementsSource"]["state"], "bound"
            )
            self.assertEqual(
                value["closurePlan"]["requirementsIntegrity"]["state"], "bound"
            )
            self.assertTrue(
                value["closurePlan"]["requirementsIntegrity"]["exactSourcePersisted"]
            )

    def test_requirements_file_binds_exact_multiline_source_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "USER_REQUIREMENTS.md"
            raw = "学习者端：\n- 创建周目标\n- 阶段完成后仅允许一次轻量回应\n"
            source.write_text(raw, encoding="utf-8", newline="")

            result = ProjectClient(root).do(
                "begin",
                {
                    "goal": "Implement P1 weekly goals",
                    "acceptance": "npm test passes",
                    "requirements_file": "USER_REQUIREMENTS.md",
                },
            )

            contract = result["acceptanceContract"]
            bound = contract["requirementsSource"]
            self.assertEqual(bound["state"], "bound")
            self.assertEqual(bound["kind"], "project-file")
            self.assertEqual(bound["path"], "USER_REQUIREMENTS.md")
            self.assertEqual(bound["sha256"], hashlib.sha256(raw.encode("utf-8")).hexdigest())
            self.assertEqual(bound["byteCount"], len(raw.encode("utf-8")))
            self.assertEqual(bound["lineCount"], 3)

            source_store = json.loads(
                (root / ".hellodev" / "acceptance-sources.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source_store["sources"][0]["text"], raw)
            self.assertEqual(source_store["sources"][0]["sha256"], bound["sha256"])
            self.assertTrue(acceptance.evidence(root)["requirementsIntegrity"]["satisfied"])

    def test_wide_strict_change_requires_bound_original_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do(
                "begin",
                {"goal": "Implement P1 weekly goals", "acceptance": "project tests pass"},
            )
            client.do("work")
            for index in range(11):
                (root / f"feature_{index}.ts").write_text(
                    f"export const value{index} = {index}\n", encoding="utf-8"
                )

            evidence = acceptance.evidence(root)
            self.assertEqual(evidence["guidedAcceptance"]["mode"], "strict")
            self.assertEqual(evidence["requirementsIntegrity"]["state"], "source-required")
            self.assertFalse(evidence["requirementsIntegrity"]["satisfied"])
            self.assertFalse(evidence["satisfied"])
            with self.assertRaisesRegex(ProjectError, "requirements source"):
                client.do("check")

    def test_active_summary_contract_can_only_upgrade_to_exact_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ProjectClient(root)
            client.do("begin", {"goal": "Implement feature", "acceptance": "tests pass"})
            (root / "requirements.md").write_text("- Preserve privacy\n", encoding="utf-8")

            upgraded = client.do(
                "begin",
                {
                    "goal": "Implement feature",
                    "acceptance": "tests pass",
                    "requirements_file": "requirements.md",
                },
            )
            self.assertEqual(
                upgraded["acceptanceContract"]["requirementsSource"]["state"], "bound"
            )
            with self.assertRaisesRegex(ProjectError, "cannot be replaced"):
                client.do(
                    "begin",
                    {
                        "goal": "Implement feature",
                        "acceptance": "different tests pass",
                        "requirements_file": "requirements.md",
                    },
                )

    def test_changed_or_unsafe_requirements_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "requirements.md"
            source.write_text("- Original requirement\n", encoding="utf-8")
            client = ProjectClient(root)
            client.do(
                "begin",
                {
                    "goal": "Implement P1 feature",
                    "acceptance": "tests pass",
                    "requirements_file": "requirements.md",
                },
            )
            source.write_text("- Changed requirement\n", encoding="utf-8")
            integrity = acceptance.evidence(root)["requirementsIntegrity"]
            self.assertEqual(integrity["state"], "source-changed")
            self.assertFalse(integrity["satisfied"])

            outside = root.parent / "outside-requirements.md"
            outside.write_text("outside\n", encoding="utf-8")
            try:
                with tempfile.TemporaryDirectory() as other_directory:
                    other = Path(other_directory)
                    with self.assertRaisesRegex(ProjectError, "project-relative"):
                        ProjectClient(other).do(
                            "begin",
                            {
                                "goal": "Unsafe source",
                                "acceptance": "tests pass",
                                "requirements_file": str(outside.resolve()),
                            },
                        )
            finally:
                outside.unlink(missing_ok=True)

    def test_native_archive_and_low_level_finish_cannot_bypass_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trellis" / "tasks").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (root / "requirements.md").write_text("- Finish atomically\n", encoding="utf-8")
            client = ProjectClient(root)
            prepared = client.do(
                "begin",
                {
                    "goal": "Implement closure integrity",
                    "acceptance": "tests pass",
                    "requirements_file": "requirements.md",
                },
            )
            ready = client.do(
                "begin",
                {
                    "goal": "Implement closure integrity",
                    "acceptance": "tests pass",
                    "requirements_file": "requirements.md",
                    "approve": prepared["approval"],
                },
            )
            client.do("work")
            (root / "closure.py").write_text("CLOSURE_INTEGRITY = True\n", encoding="utf-8")
            required = client.next()["action"]
            client.do(
                "verify",
                {
                    "results": [
                        {
                            "level": "T1",
                            "command": required["hostCommand"],
                            "scope": "code",
                            "outcome": "succeeded",
                        }
                    ]
                },
            )
            record_file = root / ".trellis" / "tasks" / ready["selectedTask"] / "task.json"
            record = json.loads(record_file.read_text(encoding="utf-8"))
            acceptance.record_context_validation(
                root,
                ready["selectedTask"],
                trellis_bridge.canonical_sha256(record),
                True,
                "component-protocol",
            )
            client.do("check")

            archive = root / ".trellis" / "archive" / ready["selectedTask"]
            archive.parent.mkdir(parents=True)
            record_file.parent.rename(archive)

            with self.assertRaisesRegex(ProjectError, "Trellis task"):
                client.do("finish")
            with self.assertRaisesRegex(ProjectError, "managed finish"):
                lifecycle.transition(root, "finished")
            self.assertEqual(lifecycle.status(root)["phase"], "checking")
            self.assertEqual(contracts.current_work_item(root)["linkedPhase"], "checking")


if __name__ == "__main__":
    unittest.main()
