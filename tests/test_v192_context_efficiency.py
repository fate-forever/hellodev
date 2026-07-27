from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev.context_runtime import build_context, clear_result_sessions
from hellodev.context_runtime import native, planner
from hellodev.context_runtime.native import clear_cache


class V192ContextEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()
        clear_result_sessions()

    @staticmethod
    def _package(root: Path, name: str, marker_text: str, count: int = 8) -> Path:
        package = root / "packages" / name
        source = package / "src"
        source.mkdir(parents=True)
        (package / "pyproject.toml").write_text(marker_text, encoding="utf-8")
        for index in range(count):
            (source / f"context_{index}.py").write_text(
                f"def context_session_{index}():\n    return 'context-session-{index}'\n",
                encoding="utf-8",
            )
        return package

    def test_nested_cwd_does_not_implicitly_hide_other_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self._package(root, "hello-core", "name = 'hello-core'\n")
            self._package(root, "other-core", "name = 'other-core'\n")
            with mock.patch.object(Path, "cwd", return_value=package / "src"):
                result = build_context(root, query="context session", scope="code", byte_budget=600)
            self.assertEqual(result["focus"], {
                "strategy": "project-root", "root": ".", "projectRoot": True,
            })
            self.assertGreaterEqual(result["metrics"]["scannedFileCount"], 18)

    def test_only_explicit_package_identity_focuses_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alpha = self._package(root, "alpha", "description = 'reliable context engine'\n")
            beta = self._package(root, "beta", "description = 'unrelated service'\n")
            with mock.patch.object(Path, "cwd", return_value=root):
                broad = build_context(root, query="reliable context", scope="code", byte_budget=600)
            self.assertEqual(broad["focus"]["strategy"], "project-root")

            clear_cache()
            clear_result_sessions()
            with mock.patch.object(Path, "cwd", return_value=root):
                focused = build_context(root, query="alpha reliable context", scope="code", byte_budget=600)
            self.assertEqual(focused["focus"]["strategy"], "explicit-package")
            self.assertEqual(focused["focus"]["root"], "packages/alpha")

            (beta / "pyproject.toml").write_text("description = 'reliable context service'\n", encoding="utf-8")
            clear_cache()
            clear_result_sessions()
            with mock.patch.object(Path, "cwd", return_value=root):
                fallback = build_context(root, query="reliable context", scope="code", byte_budget=600)
            self.assertEqual(fallback["focus"]["strategy"], "project-root")
            self.assertEqual(fallback["focus"]["root"], ".")
            self.assertGreaterEqual(fallback["metrics"]["scannedFileCount"], 18)
            self.assertTrue(alpha.is_dir())

    def test_continuation_session_avoids_snapshot_and_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._package(root, "core", "name = 'core'\n", count=14)
            with mock.patch.object(Path, "cwd", return_value=root):
                first = build_context(root, query="context session", scope="code", byte_budget=300)
                with (
                    mock.patch.object(planner, "snapshot", side_effect=AssertionError("snapshot repeated")),
                    mock.patch.object(planner, "_rank", side_effect=AssertionError("rank repeated")),
                ):
                    second = build_context(
                        root, query=None, scope="project", byte_budget=300,
                        cursor=first["continuation"]["cursor"],
                    )
            self.assertTrue(second["continuationSession"]["hit"])
            self.assertFalse(second["continuationSession"]["reconstructed"])
            self.assertFalse({item["path"] for item in first["items"]} & {item["path"] for item in second["items"]})

    def test_lost_session_reconstructs_strictly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._package(root, "core", "name = 'core'\n", count=14)
            with mock.patch.object(Path, "cwd", return_value=root):
                first = build_context(root, query="context session", scope="code", byte_budget=300)
                clear_result_sessions()
                second = build_context(
                    root, query=None, scope="project", byte_budget=300,
                    cursor=first["continuation"]["cursor"],
                )
            self.assertFalse(second["continuationSession"]["hit"])
            self.assertTrue(second["continuationSession"]["reconstructed"])

    def test_session_ttl_and_count_limits_evict_to_safe_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_root = Path(first_dir)
            second_root = Path(second_dir)
            self._package(first_root, "first", "name = 'first'\n", count=14)
            self._package(second_root, "second", "name = 'second'\n", count=14)
            with mock.patch.object(Path, "cwd", return_value=first_root), mock.patch.object(
                planner.time, "monotonic", return_value=0.0
            ):
                ttl_page = build_context(first_root, query="context session", scope="code", byte_budget=300)
            with mock.patch.object(Path, "cwd", return_value=first_root), mock.patch.object(
                planner.time, "monotonic", return_value=planner.RESULT_SESSION_TTL_SECONDS + 1
            ):
                ttl_next = build_context(
                    first_root, query=None, scope="project", byte_budget=300,
                    cursor=ttl_page["continuation"]["cursor"],
                )
            self.assertTrue(ttl_next["continuationSession"]["reconstructed"])

            clear_result_sessions()
            with mock.patch.object(planner, "MAX_RESULT_SESSIONS", 1):
                with mock.patch.object(Path, "cwd", return_value=first_root):
                    first_page = build_context(first_root, query="context session", scope="code", byte_budget=300)
                with mock.patch.object(Path, "cwd", return_value=second_root):
                    build_context(second_root, query="context session", scope="code", byte_budget=300)
                with mock.patch.object(Path, "cwd", return_value=first_root):
                    first_next = build_context(
                        first_root, query=None, scope="project", byte_budget=300,
                        cursor=first_page["continuation"]["cursor"],
                    )
            self.assertTrue(first_next["continuationSession"]["reconstructed"])

    def test_oversized_session_is_not_cached_and_reconstructs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._package(root, "core", "name = 'core'\n", count=14)
            with mock.patch.object(Path, "cwd", return_value=root), mock.patch.object(
                planner, "MAX_RESULT_SESSION_BYTES", 1
            ):
                first = build_context(root, query="context session", scope="code", byte_budget=300)
                self.assertFalse(first["continuationSession"]["cached"])
                second = build_context(
                    root, query=None, scope="project", byte_budget=300,
                    cursor=first["continuation"]["cursor"],
                )
            self.assertTrue(second["continuationSession"]["reconstructed"])

    def test_native_hot_snapshot_does_not_walk_candidates_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._package(root, "core", "name = 'core'\n")
            first = native.snapshot(root)
            with mock.patch.object(native, "_candidates", side_effect=AssertionError("walk repeated")):
                second = native.snapshot(root)
            self.assertEqual(first.snapshot_id, second.snapshot_id)
            self.assertTrue(second.cache_hit)


if __name__ == "__main__":
    unittest.main()
