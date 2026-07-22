"""Cached, read-only capability discovery for HelloDev adapters."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import components, context_runtime, repository_tools
from .adapters import nocturne, trellis
from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _marker(path: Path) -> dict[str, Any]:
    """Return a content identity without exposing the source contents.

    Capability discovery must react to durable workflow inputs even when a
    tool preserves timestamps.  Content digests are intentionally retained in
    the local cache fingerprint only; they are never printed as context.
    """
    if path.is_symlink():
        return {"state": "symlink"}
    if not path.exists():
        return {"state": "absent"}
    if not path.is_file():
        return {"state": "not-regular"}
    stat = path.stat()
    return {"state": "present", "size": stat.st_size, "sha256": _sha256_file(path)}


def _script_markers(root: Path) -> dict[str, Any]:
    """Fingerprint the Trellis script surface without traversing links."""
    scripts = root / ".trellis" / "scripts"
    if scripts.is_symlink():
        return {"state": "symlink"}
    if not scripts.exists():
        return {"state": "absent"}
    if not scripts.is_dir():
        return {"state": "not-directory"}
    try:
        scripts.resolve().relative_to(root.resolve())
    except ValueError:
        return {"state": "outside-root"}

    files: list[dict[str, Any]] = []
    for directory, nested_dirs, names in os.walk(scripts, followlinks=False):
        directory_path = Path(directory)
        nested_dirs[:] = sorted(name for name in nested_dirs if not (directory_path / name).is_symlink())
        for name in sorted(names):
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            files.append({"path": relative, **_marker(path)})
    return {"state": "present", "files": files}


def fingerprint(root: Path) -> str:
    paths = ProjectPaths(root)
    load_config(root)
    config = _marker(paths.config_file)
    trellis_dir = root / ".trellis"
    payload = {
        "config": config,
        "agents": _marker(root / "AGENTS.md"),
        "trellis": _marker(trellis_dir),
        "workflow": _marker(trellis_dir / "workflow.md"),
        "context": _marker(trellis_dir / "spec" / "context" / "CONTEXT.md"),
        "scripts": _script_markers(root),
        "componentRuntime": components.runtime_fingerprint(),
        "repositoryTools": repository_tools.fingerprint_material(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _load(root: Path) -> dict[str, Any] | None:
    path = ProjectPaths(root).capabilities_file
    if not path.exists():
        return None
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev capability cache")
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev capability cache: {error}") from error
    if not isinstance(cache, dict) or cache.get("schemaVersion") != 1:
        raise ProjectError("invalid HelloDev capability cache schema")
    return cache


def status(root: Path) -> dict[str, Any]:
    cache = _load(root)
    current = fingerprint(root)
    if cache is None:
        return {"state": "missing", "fingerprint": current, "capabilities": None}
    cached_fingerprint = cache.get("fingerprint")
    if not isinstance(cached_fingerprint, str):
        raise ProjectError("invalid HelloDev capability cache fingerprint")
    return {
        "state": "fresh" if cached_fingerprint == current else "stale",
        "fingerprint": current,
        "generatedAt": cache.get("generatedAt"),
        "capabilities": cache.get("capabilities"),
    }


def refresh(root: Path) -> dict[str, Any]:
    current = fingerprint(root)
    capabilities = {
        "trellis": trellis.discover(root),
        "nocturne": nocturne.status(root),
        "repositoryTools": repository_tools.discover(),
        "contextPlane": context_runtime.status(root),
    }
    cache = {"schemaVersion": 1, "fingerprint": current, "generatedAt": utc_now(), "capabilities": capabilities}
    write_json(ProjectPaths(root).capabilities_file, cache)
    return {"state": "fresh", "fingerprint": current, "generatedAt": cache["generatedAt"], "capabilities": capabilities}
