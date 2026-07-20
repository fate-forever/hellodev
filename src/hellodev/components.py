"""Strict resolution and integrity checks for unified-distribution components."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from . import __version__


COMPONENT_NAMES = ("trellis", "nocturne")
MANIFEST_RELATIVE_PATH = Path("manifest") / "components-v1.json"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CONTROLLED_FILES = 50_000
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_VERIFICATION_CACHE: ContextVar[dict[tuple[Any, ...], Any] | None] = ContextVar(
    "hellodev_component_verification_cache", default=None
)
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class ComponentError(ValueError):
    """Raised when a bundled component is absent, unsafe, or inconsistent."""


@dataclass(frozen=True)
class ResolvedComponent:
    name: Literal["trellis", "nocturne"]
    version: str
    revision: str
    source: Literal["bundled"]
    command: str
    args: tuple[str, ...]
    cwd: str | None
    environment: tuple[tuple[str, str], ...]
    data_root: str | None
    manifest_sha256: str
    execution_identity: tuple[dict[str, Any], ...]

    @property
    def argv(self) -> list[str]:
        return [self.command, *self.args]


def _canonical(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


@contextmanager
def verification_session():
    """Reuse exact verification only within one top-level request."""

    if _VERIFICATION_CACHE.get() is not None:
        yield
        return
    token = _VERIFICATION_CACHE.set({})
    try:
        yield
    finally:
        _VERIFICATION_CACHE.reset(token)


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise ComponentError(f"duplicate JSON key in component manifest: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if _is_link_or_reparse(path) or not path.is_file():
        raise ComponentError(f"component manifest is missing or unsafe: {path}")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ComponentError("component manifest exceeds the 8 MiB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ComponentError(f"invalid component manifest: {error}") from error
    if not isinstance(value, dict):
        raise ComponentError("component manifest must be a JSON object")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _lexical_absolute(value: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(value).expanduser())))


def _is_lexically_within(candidate: str | Path, root: str | Path) -> bool:
    """Return whether an absolute path is under a root without following links.

    `Path.relative_to()` compares Windows path spelling case-sensitively in some
    hosted-Python combinations.  Bundle write boundaries must instead follow
    the platform's path-equivalence rules, while reparse-point checks remain
    separate and mandatory.
    """

    candidate_value = os.path.normcase(os.path.normpath(os.fspath(candidate)))
    root_value = os.path.normcase(os.path.normpath(os.fspath(root)))
    try:
        shared = os.path.commonpath((candidate_value, root_value))
    except ValueError:
        return False
    return shared == root_value


def _reject_reparse_chain(path: Path, label: str) -> None:
    for candidate in (path, *path.parents):
        if _is_link_or_reparse(candidate):
            raise ComponentError(f"{label} contains a link or reparse point: {candidate}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_digest(path: Path) -> str:
    return _sha256_file(path)


def _strict_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    keys = set(value)
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        raise ComponentError(f"invalid {label} fields: missing={missing}, unknown={unknown}")


def _relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value or "\\" in value:
        raise ComponentError(f"{label} must be a bounded POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ComponentError(f"{label} must not be absolute or traverse directories")
    for part in path.parts:
        if ":" in part or part.endswith((" ", ".")):
            raise ComponentError(f"{label} contains a Windows-unsafe path segment")
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED:
            raise ComponentError(f"{label} contains a reserved Windows name")
    return path


def _inside(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ComponentError(f"component path escapes bundle root: {relative}") from error
    return candidate


def current_target() -> dict[str, str]:
    os_name = "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"
    machine = platform.machine().lower()
    architecture = "x86_64" if machine in {"amd64", "x86_64"} else "arm64" if machine in {"arm64", "aarch64"} else machine
    return {"os": os_name, "architecture": architecture}


def default_home() -> Path:
    override = os.environ.get("HELLODEV_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "HelloDev"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "hellodev"


def bundle_root(value: str | Path | None = None) -> Path | None:
    selected = value if value is not None else os.environ.get("HELLODEV_BUNDLE_ROOT")
    if selected is None or str(selected).strip() == "":
        executable = Path(sys.executable).resolve()
        matches = [
            candidate
            for candidate in executable.parents[:5]
            if (candidate / MANIFEST_RELATIVE_PATH).is_file()
            and not _is_link_or_reparse(candidate / MANIFEST_RELATIVE_PATH)
        ]
        if len(matches) > 1:
            raise ComponentError("portable Python path maps to multiple HelloDev bundle manifests")
        if matches:
            selected = matches[0]
        if selected is None or str(selected).strip() == "":
            return None
    root = _lexical_absolute(selected)
    _reject_reparse_chain(root, "HelloDev bundle root")
    if not root.is_dir():
        raise ComponentError(f"HelloDev bundle root is missing or unsafe: {root}")
    return root


def component_lock() -> dict[str, Any]:
    lock = resources.files("hellodev").joinpath("distribution/component-lock-v1.json")
    try:
        value = json.loads(lock.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ComponentError(f"invalid packaged component lock: {error}") from error
    if not isinstance(value, dict):
        raise ComponentError("packaged component lock must be an object")
    return value


def load_manifest(value: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    root = bundle_root(value)
    if root is None:
        raise ComponentError("no unified HelloDev bundle is selected; set HELLODEV_BUNDLE_ROOT or use the platform bundle launcher")
    manifest_path = root / MANIFEST_RELATIVE_PATH
    manifest = _read_json(manifest_path)
    _strict_keys(
        manifest,
        {"schemaVersion", "distributionVersion", "target", "controlledRoots", "distributionFiles", "components"},
        "manifest",
    )
    if manifest["schemaVersion"] != 1:
        raise ComponentError("unsupported component manifest schema")
    if manifest["distributionVersion"] != __version__:
        raise ComponentError("component manifest version does not match HelloDev")
    target = manifest["target"]
    if not isinstance(target, dict):
        raise ComponentError("component manifest target must be an object")
    _strict_keys(target, {"os", "architecture"}, "manifest target")
    if target != current_target():
        raise ComponentError(f"bundle target {target} does not match runtime {current_target()}")
    if not isinstance(manifest["components"], dict) or set(manifest["components"]) != set(COMPONENT_NAMES):
        raise ComponentError("component manifest must contain exactly trellis and nocturne")
    return root, manifest


def _validate_lock(name: str, entry: dict[str, Any]) -> None:
    lock = component_lock()
    _strict_keys(lock, {"schemaVersion", "distributionVersion", "components"}, "component lock")
    if lock["schemaVersion"] != 1 or lock["distributionVersion"] != __version__:
        raise ComponentError("packaged component lock version mismatch")
    locked = lock["components"].get(name) if isinstance(lock["components"], dict) else None
    if not isinstance(locked, dict):
        raise ComponentError(f"packaged component lock is missing {name}")
    for field in ("version", "revision", "repository", "licenseSpdx"):
        if entry.get(field) != locked.get(field):
            raise ComponentError(f"{name} {field} does not match packaged component lock")


def _entry(root: Path, manifest: dict[str, Any], name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if name not in COMPONENT_NAMES:
        raise ComponentError(f"unknown bundled component: {name}")
    cache = _VERIFICATION_CACHE.get()
    cache_key = ("entry", str(root), _manifest_digest(root / MANIFEST_RELATIVE_PATH), name)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    value = manifest["components"][name]
    if not isinstance(value, dict):
        raise ComponentError(f"{name} component entry must be an object")
    expected = {
        "version", "revision", "repository", "licenseSpdx", "command", "args", "cwd",
        "dataPolicy", "environment", "identityFiles", "controlledRoots", "files",
    }
    _strict_keys(value, expected, f"{name} component")
    for field in ("version", "revision", "repository", "licenseSpdx"):
        if not isinstance(value[field], str) or not value[field] or len(value[field]) > 256:
            raise ComponentError(f"{name} {field} must be a bounded string")
    _validate_lock(name, value)
    command = _relative(value["command"], f"{name} command")
    if not isinstance(value["args"], list) or len(value["args"]) > 32 or not all(
        isinstance(item, str) and len(item) <= 1024 and "\x00" not in item for item in value["args"]
    ):
        raise ComponentError(f"{name} args must be a bounded string array")
    if value["cwd"] is not None:
        _relative(value["cwd"], f"{name} cwd")
    if value["dataPolicy"] not in {"none", "separate-user-data"}:
        raise ComponentError(f"invalid {name} data policy")
    environment = value["environment"]
    if not isinstance(environment, dict) or len(environment) > 16:
        raise ComponentError(f"{name} environment must be a bounded object")
    for key, item in environment.items():
        if not isinstance(key, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) is None:
            raise ComponentError(f"invalid {name} environment key")
        if not isinstance(item, str) or len(item) > 1024 or "\x00" in item:
            raise ComponentError(f"invalid {name} environment value")
    if not isinstance(value["identityFiles"], list) or not value["identityFiles"]:
        raise ComponentError(f"{name} identityFiles must be a non-empty array")
    identities = [_relative(item, f"{name} identity file") for item in value["identityFiles"]]
    roots = value["controlledRoots"]
    if not isinstance(roots, list) or not roots:
        raise ComponentError(f"{name} controlledRoots must be a non-empty array")
    controlled_roots = [_relative(item, f"{name} controlled root") for item in roots]
    if value["cwd"] is not None:
        cwd_relative = _relative(value["cwd"], f"{name} cwd")
        cwd_path = _inside(root, cwd_relative)
        if not any(cwd_relative.is_relative_to(controlled) for controlled in controlled_roots):
            raise ComponentError(f"{name} cwd must be inside a component controlled root")
        if _is_link_or_reparse(cwd_path) or not cwd_path.is_dir():
            raise ComponentError(f"{name} cwd is missing or unsafe")
    files = value["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_CONTROLLED_FILES:
        raise ComponentError(f"{name} files must contain 1-{MAX_CONTROLLED_FILES} entries")
    normalized: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            raise ComponentError(f"{name} file entry must be an object")
        _strict_keys(item, {"path", "size", "sha256"}, f"{name} file entry")
        relative = _relative(item["path"], f"{name} file")
        folded = _canonical(relative.as_posix())
        if folded in seen:
            raise ComponentError(
                f"duplicate, Unicode-normalization, or case-colliding {name} file: {seen[folded]} / {relative}"
            )
        seen[folded] = relative.as_posix()
        if not isinstance(item["size"], int) or isinstance(item["size"], bool) or not 0 <= item["size"] <= 2**31:
            raise ComponentError(f"invalid {name} file size: {relative}")
        if not isinstance(item["sha256"], str) or not SHA256_PATTERN.fullmatch(item["sha256"]):
            raise ComponentError(f"invalid {name} file SHA-256: {relative}")
        path = _inside(root, relative)
        if _is_link_or_reparse(path) or not path.is_file():
            raise ComponentError(f"missing or unsafe {name} file: {relative}")
        if path.stat().st_size != item["size"] or _sha256_file(path) != item["sha256"]:
            raise ComponentError(f"integrity mismatch for {name} file: {relative}")
        normalized.append({"path": relative.as_posix(), "size": item["size"], "sha256": item["sha256"]})
    file_names = {item["path"] for item in normalized}
    if command.as_posix() not in file_names:
        raise ComponentError(f"{name} command is not controlled by the manifest")
    for identity in identities:
        if identity.as_posix() not in file_names:
            raise ComponentError(f"{name} identity file is not controlled: {identity}")
    actual: dict[str, str] = {}
    for controlled in controlled_roots:
        directory = _inside(root, controlled)
        if _is_link_or_reparse(directory) or not directory.is_dir():
            raise ComponentError(f"missing or unsafe {name} controlled root: {controlled}")
        for current, directories, names in os.walk(directory, followlinks=False):
            current_path = Path(current)
            for directory_name in list(directories):
                candidate = current_path / directory_name
                if _is_link_or_reparse(candidate):
                    raise ComponentError(f"unsafe link in {name} controlled root: {candidate.relative_to(root)}")
            for file_name in names:
                candidate = current_path / file_name
                if _is_link_or_reparse(candidate) or not candidate.is_file():
                    raise ComponentError(f"unsafe file in {name} controlled root: {candidate.relative_to(root)}")
                actual_path = candidate.relative_to(root).as_posix()
                key = _canonical(actual_path)
                if key in actual and actual[key] != actual_path:
                    raise ComponentError(f"{name} controlled root contains a path collision: {actual[key]} / {actual_path}")
                actual[key] = actual_path
    expected_under_roots = {
        _canonical(item["path"])
        for item in normalized
        if any(PurePosixPath(item["path"]).is_relative_to(controlled) for controlled in controlled_roots)
    }
    if set(actual) != expected_under_roots:
        raise ComponentError(f"{name} controlled roots contain unlisted or missing files")
    result = (value, normalized)
    if cache is not None:
        cache[cache_key] = result
    return result


def _verify_component(name: str, value: str | Path | None = None) -> dict[str, Any]:
    root, manifest = load_manifest(value)
    entry, files = _entry(root, manifest, name)
    return {
        "name": name,
        "state": "verified",
        "source": "bundled",
        "version": entry["version"],
        "revision": entry["revision"],
        "licenseSpdx": entry["licenseSpdx"],
        "fileCount": len(files),
        "manifestSha256": _manifest_digest(root / MANIFEST_RELATIVE_PATH),
    }


def _verify_all(value: str | Path | None = None) -> dict[str, Any]:
    root, manifest = load_manifest(value)
    cache = _VERIFICATION_CACHE.get()
    manifest_sha = _manifest_digest(root / MANIFEST_RELATIVE_PATH)
    cache_key = ("all", str(root), manifest_sha)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    verified: list[dict[str, Any]] = []
    controlled_component_files: set[str] = set()
    for name in COMPONENT_NAMES:
        entry, files = _entry(root, manifest, name)
        current_files = {_canonical(item["path"]) for item in files}
        overlap = controlled_component_files & current_files
        if overlap:
            raise ComponentError(f"component file is claimed more than once: {sorted(overlap)[0]}")
        controlled_component_files.update(current_files)
        verified.append(
            {
                "name": name,
                "state": "verified",
                "source": "bundled",
                "version": entry["version"],
                "revision": entry["revision"],
                "licenseSpdx": entry["licenseSpdx"],
                "fileCount": len(files),
                "manifestSha256": manifest_sha,
            }
        )
    roots = manifest["controlledRoots"]
    distribution_files = manifest["distributionFiles"]
    if not isinstance(roots, list) or not roots or not isinstance(distribution_files, list) or not distribution_files:
        raise ComponentError("distribution controlledRoots and distributionFiles must be non-empty arrays")
    controlled_roots = [_relative(item, "distribution controlled root") for item in roots]
    distribution_paths: dict[str, str] = {}
    for item in distribution_files:
        if not isinstance(item, dict):
            raise ComponentError("distribution file entry must be an object")
        _strict_keys(item, {"path", "size", "sha256"}, "distribution file entry")
        relative = _relative(item["path"], "distribution file")
        folded = _canonical(relative.as_posix())
        if folded in distribution_paths or folded in controlled_component_files:
            raise ComponentError(f"duplicate or overlapping distribution file: {relative}")
        distribution_paths[folded] = relative.as_posix()
        if not isinstance(item["size"], int) or isinstance(item["size"], bool) or item["size"] < 0:
            raise ComponentError(f"invalid distribution file size: {relative}")
        if not isinstance(item["sha256"], str) or not SHA256_PATTERN.fullmatch(item["sha256"]):
            raise ComponentError(f"invalid distribution file SHA-256: {relative}")
        path = _inside(root, relative)
        if _is_link_or_reparse(path) or not path.is_file():
            raise ComponentError(f"missing or unsafe distribution file: {relative}")
        if path.stat().st_size != item["size"] or _sha256_file(path) != item["sha256"]:
            raise ComponentError(f"integrity mismatch for distribution file: {relative}")
    actual_distribution: dict[str, str] = {}
    for controlled in controlled_roots:
        directory = _inside(root, controlled)
        if _is_link_or_reparse(directory) or not directory.is_dir():
            raise ComponentError(f"missing or unsafe distribution controlled root: {controlled}")
        for current, directories, names in os.walk(directory, followlinks=False):
            current_path = Path(current)
            for directory_name in list(directories):
                if _is_link_or_reparse(current_path / directory_name):
                    raise ComponentError("distribution controlled root contains an unsafe link")
            for name in names:
                path = current_path / name
                if _is_link_or_reparse(path) or not path.is_file():
                    raise ComponentError("distribution controlled root contains an unsafe file")
                actual_path = path.relative_to(root).as_posix()
                key = _canonical(actual_path)
                if key in actual_distribution and actual_distribution[key] != actual_path:
                    raise ComponentError(
                        f"distribution controlled root contains a path collision: {actual_distribution[key]} / {actual_path}"
                    )
                actual_distribution[key] = actual_path
    expected_under_roots = {
        path
        for path in distribution_paths
        if any(PurePosixPath(path).is_relative_to(PurePosixPath(_canonical(controlled.as_posix()))) for controlled in controlled_roots)
    }
    if set(actual_distribution) != expected_under_roots:
        raise ComponentError("distribution controlled roots contain unlisted or missing files")
    all_actual: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        actual_path = path.relative_to(root).as_posix()
        key = _canonical(actual_path)
        if key in all_actual and all_actual[key] != actual_path:
            raise ComponentError(f"bundle contains a path collision: {all_actual[key]} / {actual_path}")
        all_actual[key] = actual_path
    all_expected = controlled_component_files | set(distribution_paths) | {_canonical(MANIFEST_RELATIVE_PATH.as_posix())}
    if set(all_actual) != all_expected:
        raise ComponentError("bundle contains files outside the strict manifest inventory")
    report = {
        "schemaVersion": 1,
        "state": "ready",
        "distributionVersion": __version__,
        "bundleRoot": str(root),
        "target": current_target(),
        "components": {item["name"]: item for item in verified},
        "writePerformed": False,
        "integrityClaim": "bytes-match-included-manifest; not a remote signature or tamper-proof witness",
    }
    if cache is not None:
        cache[cache_key] = report
    return report


def verify_component(name: str, value: str | Path | None = None) -> dict[str, Any]:
    try:
        return _verify_component(name, value)
    except OSError as error:
        raise ComponentError(f"component verification failed while reading the bundle: {error}") from error


def _describe_component(name: Literal["trellis", "nocturne"], value: str | Path | None = None) -> dict[str, Any]:
    """Validate the manifest and execution identities without hashing all payload files.

    Discovery and capability fingerprinting are advisory, so they validate the
    files that can start execution and defer the complete inventory hash walk
    to ``resolve`` immediately before approval preparation or execution.
    """

    root, manifest = load_manifest(value)
    cache = _VERIFICATION_CACHE.get()
    cache_key = ("describe", str(root), _manifest_digest(root / MANIFEST_RELATIVE_PATH), name)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    entry = manifest["components"][name]
    if not isinstance(entry, dict):
        raise ComponentError(f"{name} component entry must be an object")
    expected = {
        "version", "revision", "repository", "licenseSpdx", "command", "args", "cwd",
        "dataPolicy", "environment", "identityFiles", "controlledRoots", "files",
    }
    _strict_keys(entry, expected, f"{name} component")
    _validate_lock(name, entry)
    command = _relative(entry["command"], f"{name} command")
    identities = entry["identityFiles"]
    if not isinstance(identities, list) or not identities:
        raise ComponentError(f"{name} identityFiles must be a non-empty array")
    required = {command.as_posix(), *(_relative(item, f"{name} identity file").as_posix() for item in identities)}
    if name == "trellis":
        environment = entry["environment"]
        if not isinstance(environment, dict):
            raise ComponentError("trellis environment must be an object")
        python_command = environment.get("TRELLIS_PYTHON_CMD")
        expected_launcher = "{bundle}/bin/trellis-python.cmd" if current_target()["os"] == "windows" else "{bundle}/bin/trellis-python"
        if python_command != expected_launcher:
            raise ComponentError("bundled Trellis Python command must use the verified HelloDev script launcher")
        required.add("bin/trellis-python.cmd" if current_target()["os"] == "windows" else "bin/trellis-python")
        required.add("bin/trellis-script-runner.py")
        required.add("runtime/python/python.exe" if current_target()["os"] == "windows" else "runtime/python/bin/python")

    records: dict[str, dict[str, Any]] = {}
    inventories = []
    for component_name, component in manifest["components"].items():
        if not isinstance(component, dict) or not isinstance(component.get("files"), list):
            raise ComponentError(f"{component_name} component manifest inventory must be an array")
        inventories.append(component["files"])
    inventories.append(manifest["distributionFiles"])
    for inventory in inventories:
        if not isinstance(inventory, list):
            raise ComponentError("component manifest inventory must be an array")
        for item in inventory:
            if not isinstance(item, dict):
                raise ComponentError("component manifest file entry must be an object")
            _strict_keys(item, {"path", "size", "sha256"}, "component manifest file entry")
            relative = _relative(item["path"], "component manifest file")
            folded = _canonical(relative.as_posix())
            if folded in records:
                raise ComponentError(f"duplicate or colliding component manifest file: {relative}")
            if not isinstance(item["size"], int) or isinstance(item["size"], bool) or item["size"] < 0:
                raise ComponentError(f"invalid component manifest file size: {relative}")
            if not isinstance(item["sha256"], str) or not SHA256_PATTERN.fullmatch(item["sha256"]):
                raise ComponentError(f"invalid component manifest file SHA-256: {relative}")
            records[folded] = {**item, "path": relative.as_posix()}

    checked = []
    for relative_value in sorted(required, key=_canonical):
        record = records.get(_canonical(relative_value))
        if record is None:
            raise ComponentError(f"{name} execution identity is not controlled by the manifest: {relative_value}")
        path = _inside(root, PurePosixPath(record["path"]))
        if _is_link_or_reparse(path) or not path.is_file():
            raise ComponentError(f"missing or unsafe {name} execution identity: {relative_value}")
        if path.stat().st_size != record["size"] or _sha256_file(path) != record["sha256"]:
            raise ComponentError(f"integrity mismatch for {name} execution identity: {relative_value}")
        checked.append({"path": str(path.resolve()), "size": record["size"], "sha256": record["sha256"]})
    result = {
        "name": name,
        "state": "available",
        "source": "bundled",
        "version": entry["version"],
        "revision": entry["revision"],
        "licenseSpdx": entry["licenseSpdx"],
        "command": str(_inside(root, command).resolve()),
        "manifestSha256": _manifest_digest(root / MANIFEST_RELATIVE_PATH),
        "executionIdentity": checked,
        "verificationMode": "execution-identities; full-inventory-before-adapter-use",
    }
    if cache is not None:
        cache[cache_key] = result
    return result


def describe(name: Literal["trellis", "nocturne"], value: str | Path | None = None) -> dict[str, Any]:
    try:
        return _describe_component(name, value)
    except OSError as error:
        raise ComponentError(f"component description failed while reading the bundle: {error}") from error


def verify_all(value: str | Path | None = None) -> dict[str, Any]:
    try:
        return _verify_all(value)
    except OSError as error:
        raise ComponentError(f"component verification failed while reading the bundle: {error}") from error


def status(value: str | Path | None = None) -> dict[str, Any]:
    try:
        root = bundle_root(value)
        if root is None:
            return {
                "schemaVersion": 1,
                "state": "unbundled",
                "distributionVersion": __version__,
                "components": {},
                "writePerformed": False,
            }
        return verify_all(root)
    except ComponentError as error:
        return {
            "schemaVersion": 1,
            "state": "invalid",
            "distributionVersion": __version__,
            "reason": str(error),
            "components": {},
            "writePerformed": False,
        }


def availability(value: str | Path | None = None) -> dict[str, Any]:
    """Return bounded runtime availability without the complete inventory walk."""

    try:
        root = bundle_root(value)
        if root is None:
            return {
                "schemaVersion": 1,
                "state": "unbundled",
                "distributionVersion": __version__,
                "components": {},
                "writePerformed": False,
            }
        described = {name: describe(name, root) for name in COMPONENT_NAMES}
        return {
            "schemaVersion": 1,
            "state": "available",
            "distributionVersion": __version__,
            "bundleRoot": str(root),
            "target": current_target(),
            "components": {
                name: {
                    "name": name,
                    "state": item["state"],
                    "source": item["source"],
                    "version": item["version"],
                    "revision": item["revision"],
                    "licenseSpdx": item["licenseSpdx"],
                    "manifestSha256": item["manifestSha256"],
                    "verificationMode": item["verificationMode"],
                }
                for name, item in described.items()
            },
            "writePerformed": False,
            "integrityClaim": "execution identities match included manifest; full inventory is verified before adapter use",
        }
    except ComponentError as error:
        return {
            "schemaVersion": 1,
            "state": "invalid",
            "distributionVersion": __version__,
            "reason": str(error),
            "components": {},
            "writePerformed": False,
        }


def _expand(value: str, root: Path, data_root: Path) -> str:
    # Upstream tools may embed these values into generated Python/template
    # text. Forward slashes keep Windows drive paths valid in both argv and
    # source literals (for example, avoiding an accidental ``\U`` escape).
    return value.replace("{bundle}", root.as_posix()).replace("{data}", data_root.as_posix())


def _resolve_component(name: Literal["trellis", "nocturne"], value: str | Path | None = None) -> ResolvedComponent:
    root, manifest = load_manifest(value)
    if name == "trellis":
        verify_all(root)
    entry, files = _entry(root, manifest, name)
    home_data = default_home() / "data"
    command = _inside(root, _relative(entry["command"], f"{name} command"))
    cwd = None if entry["cwd"] is None else str(_inside(root, _relative(entry["cwd"], f"{name} cwd")))
    identities = []
    file_map = {item["path"]: item for item in files}
    for identity in entry["identityFiles"]:
        relative = _relative(identity, f"{name} identity file")
        item = file_map[relative.as_posix()]
        identities.append({"path": str(_inside(root, relative).resolve()), "sha256": item["sha256"], "size": item["size"]})
    data_root = home_data / name if entry["dataPolicy"] == "separate-user-data" else None
    environment = dict(entry["environment"])
    if name == "trellis":
        environment.update(
            {
                "NODE_OPTIONS": "",
                "NODE_PATH": "",
                "PYTHONHOME": "",
                "PYTHONPATH": "",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
    else:
        environment.update(
            {
                "PYTHONHOME": "",
                "PYTHONPATH": "",
                "PYTHONSTARTUP": "",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
    if name == "trellis":
        python_command = _expand(environment.get("TRELLIS_PYTHON_CMD", ""), root, home_data)
        try:
            python_relative = _lexical_absolute(python_command).relative_to(root).as_posix()
        except ValueError as error:
            raise ComponentError("bundled Trellis Python command must stay inside the verified bundle") from error
        expected_launcher = "bin/trellis-python.cmd" if current_target()["os"] == "windows" else "bin/trellis-python"
        if python_relative != expected_launcher:
            raise ComponentError("bundled Trellis Python command must use the verified HelloDev script launcher")
        dependency: dict[str, Any] | None = None
        inventories = [component["files"] for component in manifest["components"].values()]
        inventories.append(manifest["distributionFiles"])
        for inventory in inventories:
            for candidate in inventory:
                if candidate["path"] == python_relative:
                    dependency = candidate
                    break
            if dependency is not None:
                break
        if dependency is None:
            raise ComponentError("bundled Trellis Python command is not controlled by the manifest")
        identities.append(
            {"path": str((root / Path(*PurePosixPath(python_relative).parts)).resolve()), "sha256": dependency["sha256"], "size": dependency["size"]}
        )
        runtime_relative = "runtime/python/python.exe" if current_target()["os"] == "windows" else "runtime/python/bin/python"
        runtime_dependency: dict[str, Any] | None = None
        for inventory in inventories:
            for candidate in inventory:
                if candidate["path"] == runtime_relative:
                    runtime_dependency = candidate
                    break
            if runtime_dependency is not None:
                break
        if runtime_dependency is None:
            raise ComponentError("bundled Trellis Python runtime is not controlled by the manifest")
        identities.append(
            {
                "path": str((root / Path(*PurePosixPath(runtime_relative).parts)).resolve()),
                "sha256": runtime_dependency["sha256"],
                "size": runtime_dependency["size"],
            }
        )
    return ResolvedComponent(
        name=name,
        version=entry["version"],
        revision=entry["revision"],
        source="bundled",
        command=str(command.resolve()),
        args=tuple(_expand(item, root, home_data) for item in entry["args"]),
        cwd=cwd,
        environment=tuple(sorted((key, _expand(item, root, home_data)) for key, item in environment.items())),
        data_root=str(data_root) if data_root is not None else None,
        manifest_sha256=_manifest_digest(root / MANIFEST_RELATIVE_PATH),
        execution_identity=tuple(identities),
    )


def resolve(name: Literal["trellis", "nocturne"], value: str | Path | None = None) -> ResolvedComponent:
    try:
        return _resolve_component(name, value)
    except OSError as error:
        raise ComponentError(f"component resolution failed while reading the bundle: {error}") from error


def runtime_fingerprint() -> str:
    try:
        root = bundle_root()
        report: dict[str, Any]
        if root is None:
            report = {"state": "unbundled", "distributionVersion": __version__}
        else:
            report = {
                "state": "available",
                "bundleRoot": str(root),
                "components": {name: describe(name, root) for name in COMPONENT_NAMES},
            }
    except ComponentError as error:
        report = {"state": "invalid", "distributionVersion": __version__, "reason": str(error)}
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _setup(home: str | Path | None = None) -> dict[str, Any]:
    configured_bundle = os.environ.get("HELLODEV_BUNDLE_ROOT")
    configured_home = os.environ.get("HELLODEV_HOME")
    if configured_bundle and configured_home and _is_lexically_within(
        _lexical_absolute(configured_home), _lexical_absolute(configured_bundle)
    ):
        raise ComponentError("HelloDev home must be outside the immutable bundle root")
    report = verify_all()
    selected_home = _lexical_absolute(home) if home is not None else _lexical_absolute(default_home())
    _reject_reparse_chain(selected_home, "HelloDev home")
    bundle = _lexical_absolute(report["bundleRoot"])
    configured_bundle_root = _lexical_absolute(configured_bundle) if configured_bundle else None
    if _is_lexically_within(selected_home, bundle) or (
        configured_bundle_root is not None and _is_lexically_within(selected_home, configured_bundle_root)
    ):
        raise ComponentError("HelloDev home must be outside the immutable bundle root")
    if home is not None and selected_home != _lexical_absolute(default_home()):
        raise ComponentError("custom --home must also be selected through HELLODEV_HOME so later component launches use it")
    home_created = not selected_home.exists()
    selected_home.mkdir(parents=True, exist_ok=True)
    _reject_reparse_chain(selected_home, "HelloDev home")
    data_root = selected_home / "data" / "nocturne"
    if _is_link_or_reparse(data_root):
        raise ComponentError(f"Nocturne data root is unsafe: {data_root}")
    data_created = not data_root.exists()
    data_root.mkdir(parents=True, exist_ok=True)
    _reject_reparse_chain(data_root, "Nocturne data root")
    runtime_dir = selected_home / "runtime"
    if _is_link_or_reparse(runtime_dir):
        raise ComponentError(f"HelloDev runtime directory is unsafe: {runtime_dir}")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _reject_reparse_chain(runtime_dir, "HelloDev runtime directory")
    marker = runtime_dir / f"{__version__}.json"
    payload = {
        "schemaVersion": 1,
        "distributionVersion": __version__,
        "bundleRoot": report["bundleRoot"],
        "target": report["target"],
        "manifestSha256": report["components"]["trellis"]["manifestSha256"],
        "dataRoots": {"nocturne": str(data_root)},
    }
    created = not marker.exists()
    if marker.exists():
        existing = _read_json(marker)
        if existing != payload:
            raise ComponentError("HelloDev runtime marker differs; choose a new --home or review the existing runtime")
    else:
        descriptor, temp_name = tempfile.mkstemp(prefix=".runtime.", dir=runtime_dir, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_name, marker)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
    return {
        **report,
        "state": "configured",
        "home": str(selected_home),
        "runtimeMarker": str(marker),
        "created": created,
        "writePerformed": home_created or data_created or created,
    }


def setup(home: str | Path | None = None) -> dict[str, Any]:
    try:
        return _setup(home)
    except OSError as error:
        raise ComponentError(f"HelloDev setup failed while accessing local state: {error}") from error


__all__ = [
    "COMPONENT_NAMES", "ComponentError", "ResolvedComponent", "bundle_root", "component_lock",
    "current_target", "default_home", "load_manifest", "resolve", "runtime_fingerprint", "setup", "status",
    "verify_all", "verify_component",
    "verification_session",
]
