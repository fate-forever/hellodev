from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from importlib import resources
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import agent_skill, onboarding
from hellodev.project import ProjectError


class V213ProjectSkillTests(unittest.TestCase):
    def _resource(self, relative: str) -> str:
        resource = resources.files("hellodev").joinpath(
            "skill_bundle", "hellodev", *relative.split("/")
        )
        return resource.read_text(encoding="utf-8")

    def test_bundled_skill_metadata_is_valid_concise_and_progressive(self) -> None:
        skill = self._resource("SKILL.md")
        metadata = self._resource("agents/openai.yaml")
        recovery = self._resource("references/recovery.md")
        lines = skill.splitlines()

        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[1], "name: hellodev")
        self.assertTrue(lines[2].startswith("description: Follow HelloDev"))
        self.assertEqual(lines[3], "---")
        self.assertLess(len(lines), 100)
        self.assertNotIn("TODO", skill + metadata + recovery)
        self.assertIn("$hellodev", metadata)
        self.assertIn("references/recovery.md", skill)
        self.assertIn("same `reasonCode`", skill)
        self.assertIn("closure-transaction-recovery-required", recovery)

    def test_cursor_onboard_installs_skill_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                first = onboarding.onboard(root, host="cursor")
                before = {
                    path.relative_to(root).as_posix(): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                second = onboarding.onboard(root, host="cursor")
                after = {
                    path.relative_to(root).as_posix(): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }

            destination = root / ".cursor" / "skills" / "hellodev"
            self.assertEqual(first["skill"]["state"], "installed")
            self.assertTrue(first["skill"]["changed"])
            self.assertFalse(first["skill"]["globalInstallationPerformed"])
            self.assertFalse(second["skill"]["changed"])
            self.assertEqual(before, after)
            for relative in agent_skill.SKILL_FILES:
                self.assertEqual(
                    destination.joinpath(*relative.split("/")).read_text(encoding="utf-8"),
                    self._resource(relative),
                )

    def test_codex_and_antigravity_share_standard_project_skill_path(self) -> None:
        for host in ("codex", "antigravity"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                    result = onboarding.onboard(root, host=host)
                expected = root / ".agents" / "skills" / "hellodev"
                self.assertEqual(Path(result["skill"]["path"]), expected)
                self.assertTrue((expected / "SKILL.md").is_file())
                self.assertFalse((root / ".codex" / "skills").exists())

    def test_skill_conflict_fails_before_any_project_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / ".agents" / "skills" / "hellodev" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("user-owned skill\n", encoding="utf-8")

            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                with self.assertRaisesRegex(ProjectError, "ownership is unknown"):
                    onboarding.onboard(root, host="antigravity")

            self.assertFalse((root / ".hellodev").exists())
            self.assertFalse((root / ".agents" / "mcp_config.json").exists())
            self.assertFalse((root / ".agents" / "rules" / "hellodev.md").exists())
            self.assertEqual(skill.read_text(encoding="utf-8"), "user-owned skill\n")

    def test_matching_unmanaged_skill_is_not_silently_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / ".agents" / "skills" / "hellodev" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(self._resource("SKILL.md"), encoding="utf-8")

            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                with self.assertRaisesRegex(ProjectError, "ownership is unknown"):
                    onboarding.onboard(root, host="codex")

            self.assertFalse((root / ".hellodev").exists())
            self.assertFalse((skill.parent / agent_skill.MANAGED_FILE).exists())

    def test_non_directory_skill_path_fails_before_any_project_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            occupied = root / ".agents" / "skills" / "hellodev"
            occupied.parent.mkdir(parents=True)
            occupied.write_text("not a directory\n", encoding="utf-8")

            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                with self.assertRaisesRegex(ProjectError, "is not a directory"):
                    onboarding.onboard(root, host="codex")

            self.assertFalse((root / ".hellodev").exists())
            self.assertFalse((root / ".agents" / "mcp_config.json").exists())
            self.assertEqual(occupied.read_text(encoding="utf-8"), "not a directory\n")

    def test_managed_old_skill_upgrades_but_user_modified_skill_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                onboarding.onboard(root, host="cursor")
            destination = root / ".cursor" / "skills" / "hellodev"
            skill_path = destination / "SKILL.md"
            marker_path = destination / agent_skill.MANAGED_FILE
            marker = json.loads(marker_path.read_text(encoding="utf-8"))

            old_content = skill_path.read_text(encoding="utf-8") + "\n# Prior managed release\n"
            skill_path.write_text(old_content, encoding="utf-8")
            marker["distributionVersion"] = "0.21.2"
            marker["files"]["SKILL.md"] = hashlib.sha256(old_content.encode("utf-8")).hexdigest()
            marker_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                upgraded = onboarding.onboard(root, host="cursor")
            self.assertTrue(upgraded["skill"]["changed"])
            self.assertEqual(skill_path.read_text(encoding="utf-8"), self._resource("SKILL.md"))

            skill_path.write_text("user changed this managed skill\n", encoding="utf-8")
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                with self.assertRaisesRegex(ProjectError, "differs from the bundled version"):
                    onboarding.onboard(root, host="cursor")

    def test_host_none_does_not_install_a_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": ""}):
                result = onboarding.onboard(root, host="none")
            self.assertEqual(result["skill"]["state"], "not-requested")
            self.assertFalse((root / ".agents").exists())
            self.assertFalse((root / ".cursor").exists())


if __name__ == "__main__":
    unittest.main()
