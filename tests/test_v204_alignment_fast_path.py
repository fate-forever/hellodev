from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import acceptance, task_alignment, trellis_execution, typescript_impact
from hellodev.application import ProjectClient


def _task(root: Path, task_id: str, title: str, *, priority: str = "P2", status: str = "planning") -> None:
    task = root / ".trellis" / "tasks" / task_id
    task.mkdir(parents=True)
    (task / "task.json").write_text(
        json.dumps({
            "id": task_id, "name": title.lower().replace(" ", "-"), "title": title,
            "description": "", "status": status, "scope": "frontend",
            "package": None, "priority": priority,
        }),
        encoding="utf-8",
    )


class V204AlignmentFastPathTests(unittest.TestCase):
    def test_unrelated_single_trellis_task_is_not_auto_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _task(root, "07-20-study-companion-mvp", "Study companion MVP")
            prepared = {
                "route": "trellis.task-create", "executionPerformed": False,
                "approval": "APPROVE-create", "resumeCommand": "hellodev do begin --approve APPROVE-create",
            }
            with patch("hellodev.application._run_trellis", return_value=prepared):
                value = ProjectClient(root).do(
                    "begin",
                    {"goal": "Implement difficultyLevel and calculateTaskWeight", "acceptance": "tests pass"},
                )
            self.assertEqual(value["state"], "awaiting-confirmation")
            self.assertIsNone(value["currentTask"]["id"])
            self.assertFalse((root / ".hellodev" / "task-bindings.json").exists())
            record = json.loads((root / ".trellis" / "tasks" / "07-20-study-companion-mvp" / "task.json").read_text())
            self.assertEqual(record["status"], "planning")

    def test_meaningful_goal_overlap_remains_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _task(root, "07-22-login", "Login timeout")
            value = task_alignment.evaluate(root, "07-22-login", "Continue login work")
            self.assertTrue(value["aligned"])
            self.assertEqual(value["overlapCount"], 1)

    def test_small_trellis_change_reuses_equal_level_same_snapshot_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"vitest run"}}', encoding="utf-8")
            source = root / "planning.ts"
            source.write_text("export const base = 1;\n", encoding="utf-8")
            _task(root, "07-29-difficulty-level", "Difficulty level", status="in_progress")
            client = ProjectClient(root)
            client.do("begin", {"goal": "Implement difficultyLevel", "acceptance": "domain tests pass"})
            client.do("work")
            source.write_text("export const base = 1;\nexport const difficultyLevel = 'easy';\n", encoding="utf-8")
            planned = client.do("verify", {"level": "T1", "command": "npm test -- planning", "scope": "code"})
            client.do("verify", {"session": planned["result"]["session"]["id"], "outcome": "succeeded", "duration_ms": 10})

            adaptive = trellis_execution.status(root)
            self.assertEqual(adaptive["profile"], "standard")
            self.assertEqual(adaptive["verificationState"], "covered-success")
            self.assertFalse(adaptive["runRequired"])
            self.assertFalse(adaptive["commandEquivalenceClaimed"])
            self.assertEqual(acceptance.status(root)["state"], "satisfied")

            source.write_text(
                "export const base = 1;\nexport const difficultyLevel = 'hard';\n",
                encoding="utf-8",
            )
            stale = trellis_execution.status(root)
            self.assertEqual(stale["verificationState"], "missing")
            self.assertTrue(stale["runRequired"])

    def test_strict_task_does_not_reuse_small_change_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"vitest run"}}', encoding="utf-8")
            source = root / "auth.ts"
            source.write_text("export const auth = false;\n", encoding="utf-8")
            _task(root, "07-29-auth-security", "Auth security", priority="P0", status="in_progress")
            client = ProjectClient(root)
            client.do("begin", {"goal": "Implement auth security", "acceptance": "security tests pass"})
            client.do("work")
            source.write_text("export const auth = true;\n", encoding="utf-8")
            planned = client.do("verify", {"level": "T1", "command": "npm test -- auth", "scope": "code"})
            client.do("verify", {"session": planned["result"]["session"]["id"], "outcome": "succeeded", "duration_ms": 10})
            adaptive = trellis_execution.status(root)
            self.assertEqual(adaptive["profile"], "strict")
            self.assertEqual(adaptive["verificationState"], "missing")
            self.assertTrue(adaptive["runRequired"])

    def test_typescript_export_impact_is_count_only_and_cross_file(self) -> None:
        from hellodev.context_runtime.contracts import RepositoryFile

        def item(path: str, text: str) -> RepositoryFile:
            return RepositoryFile(path, len(text), 1, 1, "0" * 64, text, tuple(text.splitlines()))

        changed = item("src/planning.ts", "export function calculateTaskWeight() { return 1 }\n")
        consumer = item("src/view.tsx", "calculateTaskWeight()\n")
        value = typescript_impact.change_impact((changed, consumer), (changed,))
        self.assertEqual(value["state"], "ready")
        self.assertEqual(value["exportedDeclarationCount"], 1)
        self.assertEqual(value["referencingFileCount"], 1)
        self.assertFalse(value["rawSymbolsExposed"])
        self.assertFalse(value["rawPathsExposed"])


if __name__ == "__main__":
    unittest.main()
