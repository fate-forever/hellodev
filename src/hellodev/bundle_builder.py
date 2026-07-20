"""Deterministic builder and verifier for platform HelloDev bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__, components


MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
_FORBIDDEN_SEGMENTS = {".git", ".venv", "__pycache__", ".cache"}
_FORBIDDEN_NAMES = {".env"}
_FORBIDDEN_SUFFIXES = (".db", ".db-wal", ".db-shm", ".wal", ".shm", ".log", ".bak")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _canonical(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if components._is_link_or_reparse(path) or not path.is_file():
        raise components.ComponentError(f"bundle spec is missing or unsafe: {path}")
    if path.stat().st_size > components.MAX_MANIFEST_BYTES:
        raise components.ComponentError("bundle spec exceeds the 8 MiB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=components._pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise components.ComponentError(f"invalid bundle spec: {error}") from error
    if not isinstance(value, dict):
        raise components.ComponentError("bundle spec must be an object")
    return value


def _lexical_absolute(value: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(value).expanduser())))


def _reject_reparse_chain(path: Path, label: str) -> None:
    for candidate in (path, *path.parents):
        if components._is_link_or_reparse(candidate):
            raise components.ComponentError(f"{label} contains a link or reparse point: {candidate}")


def _safe_directory(value: str | Path, label: str) -> Path:
    selected = _lexical_absolute(value)
    _reject_reparse_chain(selected, label)
    if not selected.is_dir():
        raise components.ComponentError(f"{label} is missing or not a directory: {selected}")
    return selected


def _safe_destination(value: str | Path) -> Path:
    selected = _lexical_absolute(value)
    _reject_reparse_chain(selected, "bundle output path")
    if selected.exists() and not selected.is_file():
        raise components.ComponentError(f"bundle output is not a regular file: {selected}")
    return selected


def _safe_relative(value: str) -> PurePosixPath:
    # Reuse the production manifest validator through a tiny temporary-free
    # equivalent; builder input is not trusted merely because it is local.
    path = PurePosixPath(value)
    if not value or "\\" in value or "\x00" in value or path.is_absolute() or any(
        part in {"", ".", ".."}
        or ":" in part
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
        for part in path.parts
    ):
        raise components.ComponentError(f"unsafe bundle path: {value}")
    return path


def _unsafe_payload(relative: str) -> bool:
    folded = relative.casefold()
    parts = PurePosixPath(relative).parts
    if any(part.casefold() in _FORBIDDEN_SEGMENTS for part in parts):
        return True
    name = parts[-1].casefold()
    nocturne_payload = folded.startswith("components/nocturne/")
    return name in _FORBIDDEN_NAMES or (nocturne_payload and name == "config.json") or name.endswith(_FORBIDDEN_SUFFIXES)


def _safe_runtime_value(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) > 1024 or "\x00" in value:
        raise components.ComponentError(f"{label} must be a bounded string")
    placeholders = set(re.findall(r"\{[^{}]*\}", value))
    if not placeholders <= {"{bundle}", "{data}"} or ("{" in value.replace("{bundle}", "").replace("{data}", "") or "}" in value.replace("{bundle}", "").replace("{data}", "")):
        raise components.ComponentError(f"{label} contains an unknown placeholder")
    scrubbed = value.replace("{bundle}", "BUNDLE").replace("{data}", "DATA")
    if re.search(r"(?:^|[=\s])[A-Za-z]:[\\/]", scrubbed) or scrubbed.startswith(("\\\\", "//", "/")) or "=/" in scrubbed:
        raise components.ComponentError(f"{label} contains an absolute host path")


def _walk(root: Path, relative_root: PurePosixPath) -> list[dict[str, Any]]:
    directory = root.joinpath(*relative_root.parts)
    if components._is_link_or_reparse(directory) or not directory.is_dir():
        raise components.ComponentError(f"bundle controlled root is missing or unsafe: {relative_root}")
    records: list[dict[str, Any]] = []
    for current, directories, names in os.walk(directory, followlinks=False):
        current_path = Path(current)
        for directory_name in list(directories):
            candidate = current_path / directory_name
            if components._is_link_or_reparse(candidate):
                raise components.ComponentError(f"bundle payload contains a directory link: {candidate}")
        for name in names:
            candidate = current_path / name
            if components._is_link_or_reparse(candidate) or not candidate.is_file():
                raise components.ComponentError(f"bundle payload contains an unsafe file: {candidate}")
            relative = candidate.relative_to(root).as_posix()
            if _unsafe_payload(relative):
                raise components.ComponentError(f"bundle payload contains forbidden runtime/user data: {relative}")
            records.append({"path": relative, "size": candidate.stat().st_size, "sha256": _sha256(candidate)})
    return sorted(records, key=lambda item: _canonical(item["path"]))


def _launcher(root: Path, target: dict[str, str]) -> None:
    bin_dir = root / "bin"
    _reject_reparse_chain(bin_dir, "bundle launcher directory")
    bin_dir.mkdir(parents=True, exist_ok=True)
    runner_content = resources.files("hellodev").joinpath("trellis_script_runner.py").read_text(encoding="utf-8")
    (bin_dir / "trellis-script-runner.py").write_text(runner_content, encoding="utf-8", newline="\n")
    if target["os"] == "windows":
        content = (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "set \"HELLODEV_BUNDLE_ROOT=%~dp0..\"\r\n"
            "if not defined HELLODEV_HOME set \"HELLODEV_HOME=%LOCALAPPDATA%\\HelloDev\"\r\n"
            "\"%~dp0..\\runtime\\python\\python.exe\" -X utf8 -B -I -m hellodev %*\r\n"
        )
        (bin_dir / "hellodev.cmd").write_text(content, encoding="utf-8", newline="")
        trellis_python = (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            '"%~dp0..\\runtime\\python\\python.exe" -X utf8 -B -I "%~dp0trellis-script-runner.py" %*\r\n'
        )
        (bin_dir / "trellis-python.cmd").write_text(trellis_python, encoding="utf-8", newline="")
    else:
        content = (
            "#!/bin/sh\n"
            "set -eu\n"
            "ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\n"
            "export HELLODEV_BUNDLE_ROOT=\"$ROOT\"\n"
            "export HELLODEV_HOME=${HELLODEV_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/hellodev}\n"
            "exec \"$ROOT/runtime/python/bin/python\" -X utf8 -B -I -m hellodev \"$@\"\n"
        )
        launcher = bin_dir / "hellodev"
        launcher.write_text(content, encoding="utf-8", newline="\n")
        launcher.chmod(0o755)
        trellis_python = bin_dir / "trellis-python"
        trellis_python.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            'ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
            'exec "$ROOT/runtime/python/bin/python" -X utf8 -B -I "$ROOT/bin/trellis-script-runner.py" "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        trellis_python.chmod(0o755)


def build(staging: str | Path, spec_path: str | Path, output: str | Path) -> dict[str, Any]:
    root = _safe_directory(staging, "bundle staging root")
    spec = _json(_lexical_absolute(spec_path))
    if set(spec) != {"distributionVersion", "target", "components"}:
        raise components.ComponentError("bundle spec fields must be distributionVersion, target, and components")
    if spec["distributionVersion"] != __version__:
        raise components.ComponentError("bundle spec version does not match HelloDev")
    if spec["target"] != components.current_target():
        raise components.ComponentError("this builder only emits an archive for the current OS and architecture")
    if not isinstance(spec["components"], dict) or set(spec["components"]) != set(components.COMPONENT_NAMES):
        raise components.ComponentError("bundle spec must contain exactly trellis and nocturne")
    lock = components.component_lock()["components"]
    rendered: dict[str, Any] = {}
    claimed: set[str] = set()
    for name in components.COMPONENT_NAMES:
        entry = spec["components"][name]
        expected = {
            "version", "revision", "repository", "licenseSpdx", "command", "args", "cwd",
            "dataPolicy", "environment", "identityFiles", "controlledRoots",
        }
        if not isinstance(entry, dict) or set(entry) != expected:
            raise components.ComponentError(f"invalid {name} bundle spec fields")
        _safe_runtime_value(entry["command"], f"{name} command")
        if entry["cwd"] is not None:
            _safe_runtime_value(entry["cwd"], f"{name} cwd")
        if not isinstance(entry["args"], list):
            raise components.ComponentError(f"{name} args must be an array")
        for index, value in enumerate(entry["args"]):
            _safe_runtime_value(value, f"{name} arg {index}")
        if not isinstance(entry["environment"], dict):
            raise components.ComponentError(f"{name} environment must be an object")
        for key, value in entry["environment"].items():
            _safe_runtime_value(value, f"{name} environment {key}")
        for field in ("version", "revision", "repository", "licenseSpdx"):
            if entry[field] != lock[name][field]:
                raise components.ComponentError(f"{name} {field} does not match packaged lock")
        roots = entry["controlledRoots"]
        if not isinstance(roots, list) or not roots:
            raise components.ComponentError(f"{name} controlledRoots must be non-empty")
        files: list[dict[str, Any]] = []
        for item in roots:
            relative_root = _safe_relative(item)
            records = _walk(root, relative_root)
            for record in records:
                folded = _canonical(record["path"])
                if folded in claimed:
                    raise components.ComponentError(f"bundle file is claimed by multiple components: {record['path']}")
                claimed.add(folded)
            files.extend(records)
        rendered[name] = {**entry, "files": sorted(files, key=lambda item: _canonical(item["path"]))}
    _launcher(root, spec["target"])
    distribution_roots = [PurePosixPath("bin"), PurePosixPath("licenses"), PurePosixPath("sources")]
    distribution_files: list[dict[str, Any]] = []
    for controlled in distribution_roots:
        distribution_files.extend(_walk(root, controlled))
    for name in ("THIRD_PARTY_NOTICES.md", "SBOM.spdx.json"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise components.ComponentError(f"required bundle metadata is missing or unsafe: {name}")
        distribution_files.append({"path": name, "size": path.stat().st_size, "sha256": _sha256(path)})
    distribution_files.sort(key=lambda item: _canonical(item["path"]))
    manifest = {
        "schemaVersion": 1,
        "distributionVersion": __version__,
        "target": spec["target"],
        "controlledRoots": [item.as_posix() for item in distribution_roots],
        "distributionFiles": distribution_files,
        "components": rendered,
    }
    manifest_dir = root / "manifest"
    _reject_reparse_chain(manifest_dir, "bundle manifest directory")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "components-v1.json"
    if components._is_link_or_reparse(manifest_path):
        raise components.ComponentError("bundle manifest path is linked or unsafe")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    components.verify_all(root)

    destination = _safe_destination(output)
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise components.ComponentError("bundle output must be outside the staging root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        if components._is_link_or_reparse(temporary) or not temporary.is_file():
            raise components.ComponentError(f"temporary bundle output is unsafe: {temporary}")
        temporary.unlink()
    elif components._is_link_or_reparse(temporary):
        raise components.ComponentError(f"temporary bundle output is unsafe: {temporary}")
    files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.relative_to(root).as_posix().casefold())
    executable_paths = {"bin/hellodev", "bin/trellis-python", *(entry["command"] for entry in rendered.values())}
    seen: set[str] = set()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            if components._is_link_or_reparse(path):
                raise components.ComponentError(f"refusing linked bundle file: {path}")
            relative = path.relative_to(root).as_posix()
            folded = _canonical(relative)
            if folded in seen:
                raise components.ComponentError(f"case-colliding archive path: {relative}")
            seen.add(folded)
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            permissions = 0o755 if relative in executable_paths else 0o644
            info.external_attr = ((stat.S_IFREG | permissions) & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    try:
        verification = verify_archive(temporary)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, destination)
    return {
        "schemaVersion": 1,
        "state": "built",
        "path": str(destination),
        "size": destination.stat().st_size,
        "sha256": _sha256(destination),
        "fileCount": len(files),
        "expandedBytes": verification["expandedBytes"],
        "target": spec["target"],
    }


def verify_archive(archive_path: str | Path) -> dict[str, Any]:
    selected = _lexical_absolute(archive_path)
    _reject_reparse_chain(selected, "bundle archive path")
    if not selected.is_file():
        raise components.ComponentError(f"bundle archive is missing or unsafe: {selected}")
    total = 0
    seen: set[str] = set()
    with zipfile.ZipFile(selected, "r") as archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_FILES:
            raise components.ComponentError("bundle archive file count is invalid")
        for info in infos:
            relative = _safe_relative(info.filename)
            folded = _canonical(relative.as_posix())
            if folded in seen:
                raise components.ComponentError(f"duplicate or case-colliding archive member: {relative}")
            seen.add(folded)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or (mode and not stat.S_ISREG(mode)) or info.is_dir():
                raise components.ComponentError(f"bundle archive contains a link or directory entry: {relative}")
            total += info.file_size
            if total > MAX_ARCHIVE_BYTES:
                raise components.ComponentError("bundle archive expands beyond the 2 GiB limit")
        with tempfile.TemporaryDirectory(prefix="hellodev-bundle-") as directory:
            root = Path(directory)
            for info in infos:
                destination = root.joinpath(*PurePosixPath(info.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
            report = components.verify_all(root)
    return {
        "schemaVersion": 1,
        "state": "verified",
        "path": str(selected),
        "size": selected.stat().st_size,
        "sha256": _sha256(selected),
        "fileCount": len(infos),
        "expandedBytes": total,
        "components": report["components"],
    }


__all__ = ["build", "verify_archive"]
