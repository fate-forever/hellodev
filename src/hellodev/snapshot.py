"""Deterministic, read-only source tree verification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


IGNORED_PARTS = {"__pycache__", ".git", ".pytest_cache", "build", "dist"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _ignored(relative: Path) -> bool:
    return any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in relative.parts)


def default_snapshot_path(module_file: str | Path | None = None) -> Path:
    """Choose the source tree in development and the package directory when installed."""
    module = Path(module_file or __file__).resolve()
    source_root = module.parents[2]
    # In a wheel, two parents is site-packages. Do not hash dependencies.
    return source_root if (source_root / "pyproject.toml").is_file() else module.parent


def verify(path: Path) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"snapshot path is not a directory: {root}")

    files: list[dict[str, str]] = []
    aggregate = hashlib.sha256()
    for item in sorted(root.rglob("*")):
        if _ignored(item.relative_to(root)):
            continue
        if not item.is_file() or item.is_symlink() or item.suffix in IGNORED_SUFFIXES:
            continue
        relative = item.relative_to(root).as_posix()
        digest = hashlib.sha256(item.read_bytes()).hexdigest()
        files.append({"path": relative, "sha256": digest})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return {
        "root": str(root),
        "fileCount": len(files),
        "sha256": aggregate.hexdigest(),
        "files": files,
    }
