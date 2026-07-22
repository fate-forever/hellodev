from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from hellodev import __version__
from hellodev import components
from hellodev.adapters import nocturne, trellis
from hellodev.bundle_builder import build, verify_archive
from hellodev.command_rendering import command_line, rewrite_commands
from hellodev.cli import main
from hellodev.onboarding import CURSOR_RULE, onboard
from hellodev.project import ProjectError, configure_nocturne, init_project, load_config
from hellodev.trellis_script_runner import main as run_trellis_script


LOCK = components.component_lock()["components"]


def _write(path: Path, content: bytes = b"fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _stage(root: Path, spec_path: Path) -> None:
    _write(root / "runtime" / "node" / ("node.exe" if os.name == "nt" else "node"), b"fake-node")
    _write(root / "components" / "trellis" / "bin" / "trellis.js", b"console.log('0.6.7')")
    _write(root / "components" / "trellis" / "lib" / "dependency.js", b"module.exports = {}")
    python_path = root / "runtime" / "python" / ("python.exe" if os.name == "nt" else "bin/python")
    _write(python_path, b"fake-python")
    _write(root / "components" / "nocturne" / "backend" / "mcp_server.py", b"print('mcp')")
    _write(root / "components" / "nocturne" / "backend" / "config.py", b"DEFAULTS = {}")
    _write(root / "licenses" / "trellis.txt", b"AGPL-3.0-only")
    _write(root / "licenses" / "nocturne.txt", b"MIT")
    _write(root / "sources" / "trellis-source.tar.gz", b"corresponding-source")
    _write(root / "sources" / "nocturne-source.tar.gz", b"source")
    _write(root / "THIRD_PARTY_NOTICES.md", b"notices")
    _write(root / "SBOM.spdx.json", b"{}")
    node_rel = (root / "runtime" / "node" / ("node.exe" if os.name == "nt" else "node")).relative_to(root).as_posix()
    python_rel = python_path.relative_to(root).as_posix()
    spec = {
        "distributionVersion": __version__,
        "target": components.current_target(),
        "components": {
            "trellis": {
                **LOCK["trellis"],
                "command": node_rel,
                "args": ["{bundle}/components/trellis/bin/trellis.js"],
                "cwd": "components/trellis",
                "dataPolicy": "none",
                "environment": {
                    "TRELLIS_PYTHON_CMD": "{bundle}/bin/trellis-python.cmd" if os.name == "nt" else "{bundle}/bin/trellis-python"
                },
                "identityFiles": [node_rel, "components/trellis/bin/trellis.js"],
                "controlledRoots": ["runtime/node", "components/trellis"],
            },
            "nocturne": {
                **LOCK["nocturne"],
                "command": python_rel,
                "args": [
                    "-X", "utf8", "-B", "-I", "-m", "hellodev.nocturne_runner", "--component-root", "{bundle}/components/nocturne",
                    "--data-root", "{data}/nocturne",
                ],
                "cwd": "components/nocturne",
                "dataPolicy": "separate-user-data",
                "environment": {},
                "identityFiles": [
                    python_rel,
                    "components/nocturne/backend/mcp_server.py",
                    "components/nocturne/backend/config.py",
                ],
                "controlledRoots": ["runtime/python", "components/nocturne"],
            },
        },
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")


def _bundle(directory: Path) -> tuple[Path, Path]:
    stage = directory / "stage"
    stage.mkdir()
    spec = directory / "bundle-spec.json"
    _stage(stage, spec)
    archive = directory / "hellodev.zip"
    build(stage, spec, archive)
    return stage, archive


def _cli(*arguments: str) -> tuple[int, dict, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--json", *arguments])
    value = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
    return code, value, stderr.getvalue()


class V14DistributionTests(unittest.TestCase):
    def test_component_lock_and_schema_match_release(self) -> None:
        self.assertEqual(__version__, "0.16.0")
        self.assertEqual(components.component_lock()["distributionVersion"], __version__)
        schema = json.loads(
            (Path(__file__).parents[1] / "src" / "hellodev" / "schemas" / "component-bundle-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["properties"]["distributionVersion"]["const"], __version__)

    def test_build_verify_is_deterministic_and_resolves_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, archive = _bundle(root)
            second = root / "second.zip"
            build(stage, root / "bundle-spec.json", second)
            self.assertEqual(archive.read_bytes(), second.read_bytes())
            self.assertTrue((stage / "bin" / ("trellis-python.cmd" if os.name == "nt" else "trellis-python")).is_file())
            self.assertTrue((stage / "bin" / "trellis-script-runner.py").is_file())
            verified = verify_archive(archive)
            self.assertEqual(verified["state"], "verified")
            home = root / "home"
            with patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": str(stage), "HELLODEV_HOME": str(home), "PATH": ""},
                clear=False,
            ):
                report = components.verify_all()
                self.assertEqual(report["components"]["trellis"]["version"], "0.6.7")
                selected = components.resolve("trellis")
                self.assertEqual(selected.source, "bundled")
                self.assertEqual(len(selected.execution_identity), 4)
                self.assertIn("trellis-python", selected.execution_identity[-2]["path"].casefold())
                self.assertIn("python", selected.execution_identity[-1]["path"].casefold())
                environment = dict(selected.environment)
                self.assertEqual(environment["NODE_OPTIONS"], "")
                self.assertEqual(environment["NODE_PATH"], "")
                self.assertEqual(environment["PYTHONPATH"], "")
                self.assertIn("TRELLIS_PYTHON_CMD", dict(selected.environment))
                self.assertIn("trellis-python", environment["TRELLIS_PYTHON_CMD"])
                if os.name == "nt":
                    self.assertNotIn("\\", environment["TRELLIS_PYTHON_CMD"])
                self.assertEqual(trellis.binding_identity()["source"], "bundled")

    def test_trellis_script_runner_imports_project_siblings_and_restores_process_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory) / ".trellis" / "scripts"
            common = scripts / "common"
            common.mkdir(parents=True)
            (common / "__init__.py").write_text("VALUE = 'runner-ok'\n", encoding="utf-8")
            task = scripts / "task.py"
            task.write_text("from common import VALUE\nprint(VALUE)\n", encoding="utf-8")
            original_argv, original_path = sys.argv[:], sys.path[:]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(run_trellis_script([str(task)]), 0)
            self.assertEqual(stdout.getvalue().strip(), "runner-ok")
            self.assertEqual(sys.argv, original_argv)
            self.assertEqual(sys.path, original_path)

    def test_discovery_checks_identities_but_adapter_prepare_checks_full_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            dependency = stage / "components" / "trellis" / "lib" / "dependency.js"
            dependency.write_bytes(b"tampered dependency")
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": str(stage)}, clear=False):
                self.assertEqual(components.describe("trellis")["state"], "available")
                with self.assertRaisesRegex(ProjectError, "bundled Trellis is invalid"):
                    trellis.prepare_run(root, ["--version"])

    def test_portable_python_infers_bundle_and_renders_path_safe_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            executable = stage / "runtime" / "python" / ("python.exe" if os.name == "nt" else "bin/python")
            project = root / "Unicode project 空格"
            project.mkdir()
            with patch.object(components.sys, "executable", str(executable)), patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": "", "HELLODEV_LAUNCHER": ""},
                clear=False,
            ):
                self.assertEqual(components.bundle_root(), stage.resolve())
                rendered = command_line(project, "open")
                launcher = stage / "bin" / ("hellodev.cmd" if os.name == "nt" else "hellodev")
                self.assertIn(str(launcher.resolve()), rendered)
                self.assertIn(str(project), rendered)
                rewritten = rewrite_commands({"resumeCommand": "hellodev do plan"})
                self.assertNotEqual(rewritten["resumeCommand"], "hellodev do plan")
                content = rewrite_commands({"title": "hellodev is task content", "command": "hellodev open"})
                self.assertEqual(content["title"], "hellodev is task content")
                self.assertNotEqual(content["command"], "hellodev open")

    def test_runtime_dependency_tamper_and_manifest_path_collision_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            python_path = stage / "runtime" / "python" / ("python.exe" if os.name == "nt" else "bin/python")
            python_path.write_bytes(b"tampered-python")
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": str(stage)}, clear=False):
                with self.assertRaisesRegex(ValueError, "bundled Trellis is invalid"):
                    trellis.prepare_run(root, ["--version"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            manifest_path = stage / "manifest" / "components-v1.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = dict(manifest["components"]["trellis"]["files"][0])
            record["path"] = record["path"].upper()
            manifest["components"]["trellis"]["files"].append(record)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": str(stage)}, clear=False):
                self.assertEqual(components.status()["state"], "invalid")

    def test_bundle_write_boundaries_and_cursor_conflict_are_preflighted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            with self.assertRaisesRegex(ValueError, "outside the staging root"):
                build(stage, root / "bundle-spec.json", stage / "nested.zip")
            with patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": str(stage), "HELLODEV_HOME": str(stage / "home")},
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "outside the immutable bundle"):
                    components.setup()
                project_inside = stage / "project"
                project_inside.mkdir()
                with self.assertRaisesRegex(ProjectError, "outside the immutable HelloDev bundle"):
                    onboard(project_inside, host="none")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            project = root / "project"
            rule = project / ".cursor" / "rules" / "hellodev.mdc"
            rule.parent.mkdir(parents=True)
            rule.write_text("different", encoding="utf-8")
            home = root / "home"
            with patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": str(stage), "HELLODEV_HOME": str(home)},
                clear=False,
            ):
                with self.assertRaisesRegex(ProjectError, "different HelloDev rule"):
                    onboard(project, host="cursor")
            self.assertFalse((project / ".hellodev").exists())
            self.assertFalse((project / ".cursor" / "mcp.json").exists())
            self.assertFalse(home.exists())

    def test_builder_rejects_secrets_and_host_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            stage.mkdir()
            spec = root / "bundle-spec.json"
            _stage(stage, spec)
            _write(stage / "components" / "trellis" / ".env", b"SECRET=x")
            with self.assertRaisesRegex(ValueError, "forbidden runtime/user data"):
                build(stage, spec, root / "secret.zip")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            stage.mkdir()
            spec = root / "bundle-spec.json"
            _stage(stage, spec)
            value = json.loads(spec.read_text(encoding="utf-8"))
            value["components"]["trellis"]["environment"]["LEAK"] = "C:\\Users\\builder\\secret"
            spec.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "absolute host path"):
                build(stage, spec, root / "leak.zip")

    def test_unknown_nocturne_tool_and_external_database_config_are_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectError, "audited read/write allowlist"):
            nocturne.risk_for_tool("future_mutation")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "component"
            backend = component / "backend"
            backend.mkdir(parents=True)
            (backend / "config.py").write_text(
                "from pathlib import Path\nROOT_DIR=Path(__file__).parent.parent\nCONFIG_PATH=ROOT_DIR/'config.json'\n"
                "DEFAULTS={'database_url':'invalid','auto_open_browser':False,'host':'127.0.0.1'}\n",
                encoding="utf-8",
            )
            (backend / "mcp_server.py").write_text("raise RuntimeError('must not launch')\n", encoding="utf-8")
            data = root / "data"
            data.mkdir()
            (data / "config.json").write_text(
                json.dumps({"database_url": "sqlite+aiosqlite:///C:/outside.db"}), encoding="utf-8"
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
            completed = subprocess.run(
                [sys.executable, "-m", "hellodev.nocturne_runner", "--component-root", str(component), "--data-root", str(data)],
                cwd=PACKAGE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("database_url must remain inside", completed.stderr)

    def test_manifest_and_payload_tamper_fail_before_adapter_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            target = stage / "components" / "trellis" / "bin" / "trellis.js"
            target.write_bytes(b"tampered")
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": str(stage)}, clear=False):
                self.assertEqual(components.status()["state"], "invalid")
                with self.assertRaisesRegex(ValueError, "bundled Trellis is invalid"):
                    trellis.prepare_run(root, ["--version"])

    def test_extra_unlisted_file_and_duplicate_manifest_key_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage, _ = _bundle(root)
            _write(stage / "components" / "nocturne" / "secret.log", b"private")
            with patch.dict(os.environ, {"HELLODEV_BUNDLE_ROOT": str(stage)}, clear=False):
                self.assertEqual(components.status()["state"], "invalid")
            manifest = stage / "manifest" / "components-v1.json"
            manifest.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                components.load_manifest(stage)

    def test_archive_traversal_reserved_names_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("traversal.zip", "reserved.zip", "link.zip"):
                archive = root / name
                with zipfile.ZipFile(archive, "w") as output:
                    if name == "traversal.zip":
                        output.writestr("../escape", b"x")
                    elif name == "reserved.zip":
                        output.writestr("CON.txt", b"x")
                    else:
                        info = zipfile.ZipInfo("linked")
                        info.external_attr = ((0o120777) & 0xFFFF) << 16
                        output.writestr(info, b"target")
                with self.assertRaises(ValueError, msg=name):
                    verify_archive(archive)

    def test_setup_and_cursor_onboard_are_idempotent_and_project_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            stage, _ = _bundle(base)
            project = base / "project"
            project.mkdir()
            home = base / "private-home"
            with patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": str(stage), "HELLODEV_HOME": str(home)},
                clear=False,
            ):
                first = onboard(project, host="cursor")
                before = {
                    path.relative_to(project).as_posix(): path.read_bytes()
                    for path in project.rglob("*")
                    if path.is_file()
                }
                second = onboard(project, host="cursor")
                after = {
                    path.relative_to(project).as_posix(): path.read_bytes()
                    for path in project.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(before, after)
                self.assertTrue(first["runtime"]["created"])
                self.assertFalse(second["runtime"]["created"])
                self.assertEqual(load_config(project)["adapters"]["nocturne"]["mode"], "bundled")
                self.assertEqual((project / ".cursor" / "rules" / "hellodev.mdc").read_text(encoding="utf-8"), CURSOR_RULE)
                self.assertTrue((home / "data" / "nocturne").is_dir())
                self.assertFalse((project / ".trellis").exists())

    def test_nocturne_runner_keeps_code_and_writable_data_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            component = root / "component"
            backend = component / "backend"
            backend.mkdir(parents=True)
            (backend / "config.py").write_text(
                "from pathlib import Path\n"
                "ROOT_DIR = Path(__file__).parent.parent\n"
                "CONFIG_PATH = ROOT_DIR / 'config.json'\n"
                "DEFAULTS = {'database_url': 'invalid', 'auto_open_browser': True, 'host': '0.0.0.0'}\n",
                encoding="utf-8",
            )
            (backend / "mcp_server.py").write_text(
                "import config\n"
                "(config.ROOT_DIR / 'observed.txt').write_text(str(config.CONFIG_PATH), encoding='utf-8')\n",
                encoding="utf-8",
            )
            data = root / "data"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hellodev.nocturne_runner",
                    "--component-root",
                    str(component),
                    "--data-root",
                    str(data),
                ],
                cwd=PACKAGE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            config = json.loads((data / "config.json").read_text(encoding="utf-8"))
            self.assertFalse(config["auto_open_browser"])
            self.assertIn((data / "nocturne_data.db").resolve().as_posix(), config["database_url"])
            self.assertEqual((data / "observed.txt").read_text(encoding="utf-8"), str(data / "config.json"))
            self.assertFalse((component / "config.json").exists())

    def test_onboard_preserves_external_nocturne_and_prepares_trellis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            stage, _ = _bundle(base)
            project = base / "project"
            project.mkdir()
            external = base / ("external.exe" if os.name == "nt" else "external")
            external.write_bytes(b"external")
            init_project(project)
            configure_nocturne(project, str(external), [], None)
            with patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": str(stage), "HELLODEV_HOME": str(base / "home")},
                clear=False,
            ):
                result = onboard(project, host="none", prepare_trellis=True)
                self.assertEqual(result["nocturne"]["state"], "external-preserved")
                self.assertEqual(result["trellis"]["state"], "awaiting-confirmation")
                self.assertIn("APPROVE-WRITE:", result["trellis"]["approval"])
                self.assertIn("trellis run", result["trellis"]["resumeCommand"])

    def test_cli_status_setup_components_and_onboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            stage, _ = _bundle(base)
            project = base / "project"
            project.mkdir()
            with patch.dict(
                os.environ,
                {"HELLODEV_BUNDLE_ROOT": str(stage), "HELLODEV_HOME": str(base / "home")},
                clear=False,
            ):
                code, report, error = _cli("components", "verify")
                self.assertEqual((code, error), (0, ""))
                self.assertEqual(report["state"], "ready")
                code, setup, error = _cli("setup")
                self.assertEqual((code, error), (0, ""))
                self.assertEqual(setup["state"], "configured")
                code, result, error = _cli("--root", str(project), "onboard", "--host", "none")
                self.assertEqual((code, error), (0, ""))
                self.assertEqual(result["state"], "onboarded")
                code, status, error = _cli("--root", str(project), "status", "--verbose")
                self.assertEqual((code, error), (0, ""))
                self.assertEqual(status["distribution"]["state"], "available")
                self.assertIn("full-inventory-before-adapter-use", status["distribution"]["components"]["trellis"]["verificationMode"])
                self.assertEqual(nocturne.status(project)["source"], "bundled")


if __name__ == "__main__":
    unittest.main()
