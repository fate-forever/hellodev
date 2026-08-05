"""Project-local installation of the bundled HelloDev Agent Skill."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from . import components
from .project import ProjectError, resolve_root


SKILL_NAME = "hellodev"
SKILL_FILES = ("SKILL.md", "agents/openai.yaml", "references/recovery.md")
MAX_SKILL_FILE_BYTES = 64 * 1024
MANAGED_FILE = ".hellodev-managed.json"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _reject_reparse_chain(path: Path) -> None:
    try:
        components._reject_reparse_chain(path, "Agent Skill directory")
    except components.ComponentError as error:
        raise ProjectError(str(error)) from error


def _validate_directory_chain(path: Path) -> None:
    _reject_reparse_chain(path)
    for candidate in (path, *path.parents):
        if candidate.exists() and not candidate.is_dir():
            raise ProjectError(f"Agent Skill directory path is not a directory: {candidate}")


def _contents() -> dict[str, str]:
    base = resources.files("hellodev").joinpath("skill_bundle", SKILL_NAME)
    values: dict[str, str] = {}
    for relative in SKILL_FILES:
        resource = base.joinpath(*relative.split("/"))
        try:
            content = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeError) as error:
            raise ProjectError(f"bundled HelloDev Skill is missing or invalid: {relative}") from error
        if not content or len(content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise ProjectError(f"bundled HelloDev Skill file is empty or oversized: {relative}")
        values[relative] = content
    return values


def _destination(root: Path, host: str) -> Path | None:
    if host == "cursor":
        return root / ".cursor" / "skills" / SKILL_NAME
    if host in {"codex", "antigravity"}:
        return root / ".agents" / "skills" / SKILL_NAME
    if host == "none":
        return None
    raise ProjectError("HelloDev Skill host must be antigravity, codex, cursor, or none")


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _manifest(contents: dict[str, str]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "skill": SKILL_NAME,
        "distributionVersion": __version__,
        "files": {relative: _digest(contents[relative]) for relative in SKILL_FILES},
    }


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if components._is_link_or_reparse(path) or not path.is_file() or path.stat().st_size > 16 * 1024:
        raise ProjectError(f"existing HelloDev Skill ownership marker is unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"existing HelloDev Skill ownership marker is invalid: {path}") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"schemaVersion", "skill", "distributionVersion", "files"}
        or value.get("schemaVersion") != 1
        or value.get("skill") != SKILL_NAME
        or not isinstance(value.get("distributionVersion"), str)
        or not isinstance(value.get("files"), dict)
        or set(value["files"]) != set(SKILL_FILES)
        or any(not isinstance(item, str) or _DIGEST.fullmatch(item) is None for item in value["files"].values())
    ):
        raise ProjectError(f"existing HelloDev Skill ownership marker is invalid: {path}")
    return value


def _matches_managed_install(destination: Path, manifest: dict[str, Any]) -> bool:
    for relative in SKILL_FILES:
        path = destination.joinpath(*relative.split("/"))
        if components._is_link_or_reparse(path) or not path.is_file():
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        if _digest(content) != manifest["files"][relative]:
            return False
    return True


def plan(root: str | Path, host: str) -> dict[str, Any]:
    selected = resolve_root(root)
    destination = _destination(selected, host)
    if destination is None:
        return {"host": host, "destination": None, "files": [], "changed": False}
    contents = _contents()
    marker_path = destination / MANAGED_FILE
    _validate_directory_chain(marker_path.parent)
    previous_manifest = _read_manifest(marker_path)
    if previous_manifest is None:
        for relative in SKILL_FILES:
            existing = destination.joinpath(*relative.split("/"))
            _validate_directory_chain(existing.parent)
            if existing.exists():
                raise ProjectError(
                    f"existing HelloDev Skill ownership is unknown; review it before onboarding: {existing}"
                )
    managed_unchanged = (
        previous_manifest is not None and _matches_managed_install(destination, previous_manifest)
    )
    files: list[dict[str, Any]] = []
    for relative, content in contents.items():
        path = destination.joinpath(*relative.split("/"))
        _validate_directory_chain(path.parent)
        if path.exists():
            if components._is_link_or_reparse(path) or not path.is_file():
                raise ProjectError(f"refusing unsafe existing HelloDev Skill file: {path}")
            try:
                current = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise ProjectError(f"cannot read existing HelloDev Skill file: {path}") from error
            if current != content:
                if not managed_unchanged:
                    raise ProjectError(
                        f"existing HelloDev Skill differs from the bundled version; review it before onboarding: {path}"
                    )
                changed = True
            else:
                changed = False
        else:
            if previous_manifest is not None and not managed_unchanged:
                raise ProjectError(
                    f"managed HelloDev Skill is incomplete or modified; review it before onboarding: {destination}"
                )
            changed = True
        files.append({"path": path, "content": content, "changed": changed})
    desired_manifest = json.dumps(_manifest(contents), indent=2, sort_keys=True) + "\n"
    if marker_path.exists():
        current_marker = marker_path.read_text(encoding="utf-8")
        marker_changed = current_marker != desired_manifest
    else:
        marker_changed = True
    files.append({"path": marker_path, "content": desired_manifest, "changed": marker_changed})
    return {
        "host": host,
        "destination": destination,
        "files": files,
        "changed": any(item["changed"] for item in files),
    }


def _atomic_write(path: Path, content: str) -> None:
    _validate_directory_chain(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_directory_chain(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def install(skill_plan: dict[str, Any]) -> dict[str, Any]:
    destination = skill_plan["destination"]
    if destination is None:
        return {
            "schemaVersion": 1,
            "state": "not-requested",
            "host": skill_plan["host"],
            "path": None,
            "changed": False,
            "reloadRequired": False,
        }
    for item in skill_plan["files"]:
        if item["changed"]:
            _atomic_write(item["path"], item["content"])
    return {
        "schemaVersion": 1,
        "state": "installed",
        "host": skill_plan["host"],
        "path": str(destination),
        "changed": skill_plan["changed"],
        "fileCount": len(skill_plan["files"]),
        "reloadRequired": skill_plan["changed"],
        "globalInstallationPerformed": False,
    }


__all__ = ["SKILL_FILES", "SKILL_NAME", "install", "plan"]
