from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import __version__


class V121OssTests(unittest.TestCase):
    def test_version_typing_ci_and_public_docs_are_aligned(self) -> None:
        pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        workflow = (PACKAGE_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = (PACKAGE_ROOT / "docs" / "QUICK_START.md").read_text(encoding="utf-8")

        self.assertEqual(__version__, "0.12.1")
        self.assertIn('version = "0.12.1"', pyproject)
        self.assertIn('"py.typed"', pyproject)
        self.assertTrue((PACKAGE_ROOT / "src" / "hellodev" / "py.typed").is_file())
        self.assertIn("fail-fast: false", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        self.assertIn('python: ["3.10", "3.12"]', workflow)
        self.assertIn("python scripts/verify.py --scope full", workflow)
        self.assertNotIn("cache: pip", workflow)
        self.assertIn('python -m pip install "setuptools>=68"', workflow)
        self.assertLess(
            workflow.index('python -m pip install "setuptools>=68"'),
            workflow.index("python -m pip wheel"),
        )
        self.assertIn("retention-days: 7", workflow)
        self.assertNotIn("pypi", workflow.lower())
        self.assertIn("HelloDev Core 0.12.1", readme)
        self.assertIn("HelloDev 0.12.1 快速上手", quick_start)
        self.assertIn("PyPI publishing is intentionally separate", readme)
        for path in (
            PACKAGE_ROOT / "CONTRIBUTING.md",
            PACKAGE_ROOT / "docs" / "CASE_STUDY.md",
            PACKAGE_ROOT / "docs" / "WHY_HELLODEV.md",
            PACKAGE_ROOT / "examples" / "minimal" / "README.md",
            PACKAGE_ROOT / "scripts" / "demo.ps1",
        ):
            self.assertTrue(path.is_file(), path)

    def test_minimal_host_sdk_example_runs_without_upstreams(self) -> None:
        path = PACKAGE_ROOT / "examples" / "host_sdk_minimal.py"
        spec = importlib.util.spec_from_file_location("hellodev_host_sdk_minimal", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            value = module.run(Path(directory))
        self.assertEqual(value["protocolVersion"], "1.0")
        self.assertEqual(value["completionState"], "completed")
        self.assertEqual(value["usageTrust"], "unavailable")
        self.assertTrue(value["checkpointMatched"])
        self.assertEqual(value["pendingCount"], 0)

    def test_demo_is_local_only_and_uses_daily_contract(self) -> None:
        script = (PACKAGE_ROOT / "scripts" / "demo.ps1").read_text(encoding="utf-8")
        for command in ("open", "next", "do task create", "do plan", "do work", "do check", "do finish", "resume"):
            self.assertIn(command, script)
        self.assertNotIn("nocturne", script.lower())
        self.assertNotIn("trellis", script.lower())
        self.assertNotIn("Invoke-WebRequest", script)
        self.assertNotIn("git ", script.lower())

    def test_local_markdown_links_and_fences_are_valid(self) -> None:
        markdown = [PACKAGE_ROOT / "README.md", PACKAGE_ROOT / "CONTRIBUTING.md"]
        markdown.extend((PACKAGE_ROOT / "docs").rglob("*.md"))
        markdown.extend((PACKAGE_ROOT / "examples").rglob("*.md"))
        missing: list[str] = []
        unbalanced: list[str] = []
        for path in markdown:
            text = path.read_text(encoding="utf-8")
            if text.count("```") % 2:
                unbalanced.append(path.relative_to(PACKAGE_ROOT).as_posix())
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                if target.startswith(("http://", "https://", "#")):
                    continue
                clean = target.split("#", 1)[0]
                if clean and not (path.parent / clean).resolve().exists():
                    missing.append(f"{path.relative_to(PACKAGE_ROOT).as_posix()} -> {target}")
        self.assertEqual(missing, [])
        self.assertEqual(unbalanced, [])


if __name__ == "__main__":
    unittest.main()
