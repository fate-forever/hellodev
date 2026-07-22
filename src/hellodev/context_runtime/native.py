"""Safe, bounded, dependency-free repository inventory for Context Plane."""

from __future__ import annotations

import codecs
import fnmatch
import hashlib
import json
import os
import threading
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Iterable

from ..project import ProjectError
from .contracts import RepositoryFile, RepositorySnapshot


MAX_FILES = 3000
MAX_FILE_BYTES = 512 * 1024
MAX_SCAN_BYTES = 12 * 1024 * 1024
MAX_CACHE_ROOTS = 4

EXCLUDED_DIRECTORIES = {
    ".git", ".hellodev", ".codex", ".cursor", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__",
    ".venv", "venv", "node_modules", "dist", "build", "out", "target", "vendor",
}
SENSITIVE_NAMES = {".env", ".npmrc", ".pypirc", "credentials", "credentials.json"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}
TEXT_SUFFIXES = {
    ".bat", ".c", ".cc", ".cfg", ".cmd", ".cpp", ".cs", ".css", ".csv",
    ".go", ".graphql", ".h", ".hpp", ".html", ".ini", ".java", ".js", ".json",
    ".jsx", ".kt", ".md", ".php", ".proto", ".ps1", ".py", ".rb", ".rs",
    ".rst", ".scss", ".sh", ".sql", ".svelte", ".swift", ".toml", ".ts", ".tsx",
    ".txt", ".vue", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {"dockerfile", "makefile", "license", "readme", "agents.md", ".gitignore"}

_CACHE: "OrderedDict[str, RepositorySnapshot]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _increment(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def _safe_gitignore_rules(root: Path) -> list[tuple[str, bool]]:
    path = root / ".gitignore"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 64 * 1024:
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    rules: list[tuple[str, bool]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        if line:
            rules.append((line.replace("\\", "/"), negated))
    return rules[:512]


def _rule_matches(relative: str, pattern: str, *, is_dir: bool) -> bool:
    anchored = pattern.startswith("/")
    pattern = pattern.lstrip("/")
    directory_rule = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    if not pattern:
        return False
    if directory_rule:
        return is_dir and (relative == pattern or relative.startswith(pattern + "/") or f"/{pattern}/" in f"/{relative}/")
    if anchored:
        return fnmatch.fnmatchcase(relative, pattern)
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(part, pattern) for part in PurePosixPath(relative).parts)
    return PurePosixPath(relative).match(pattern) or fnmatch.fnmatchcase(relative, pattern)


def _ignored(relative: str, rules: Iterable[tuple[str, bool]], *, is_dir: bool) -> bool:
    decision = False
    for pattern, negated in rules:
        if _rule_matches(relative, pattern, is_dir=is_dir):
            decision = not negated
    return decision


def _text_candidate(path: Path) -> bool:
    name = path.name.lower()
    if name in SENSITIVE_NAMES or name.startswith(".env."):
        return False
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or name in TEXT_NAMES


def _candidates(root: Path) -> tuple[list[tuple[str, Path, os.stat_result]], dict[str, int], str]:
    rules = _safe_gitignore_rules(root)
    counts: dict[str, int] = {}
    candidates: list[tuple[str, Path, os.stat_result]] = []
    for directory, nested, names in os.walk(root, followlinks=False):
        base = Path(directory)
        kept: list[str] = []
        for name in sorted(nested):
            child = base / name
            relative = child.relative_to(root).as_posix()
            if child.is_symlink():
                _increment(counts, "symlink-directory")
            elif name in EXCLUDED_DIRECTORIES or _ignored(relative, rules, is_dir=True):
                _increment(counts, "excluded-directory")
            else:
                kept.append(name)
        nested[:] = kept
        for name in sorted(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                _increment(counts, "symlink-file")
                continue
            if _ignored(relative, rules, is_dir=False):
                _increment(counts, "gitignore")
                continue
            if not _text_candidate(path):
                _increment(counts, "non-text-or-sensitive")
                continue
            try:
                stat = path.stat()
                path.resolve().relative_to(root)
            except (OSError, ValueError):
                _increment(counts, "unsafe-path")
                continue
            if not path.is_file():
                _increment(counts, "non-regular")
                continue
            candidates.append((relative, path, stat))
            if len(candidates) >= MAX_FILES:
                _increment(counts, "file-limit")
                break
        if len(candidates) >= MAX_FILES:
            break
    markers = [
        {"path": relative, "size": stat.st_size, "mtime": stat.st_mtime_ns, "ctime": stat.st_ctime_ns}
        for relative, _, stat in candidates
    ]
    fingerprint = hashlib.sha256(json.dumps(markers, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return candidates, counts, fingerprint


def _decode(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig")
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16")
    return data.decode("utf-8")


def snapshot(root: Path) -> RepositorySnapshot:
    resolved = root.resolve()
    candidates, skipped, metadata_fingerprint = _candidates(resolved)
    key = str(resolved)
    with _CACHE_LOCK:
        existing = _CACHE.get(key)
        if existing is not None and existing.metadata_fingerprint == metadata_fingerprint:
            _CACHE.move_to_end(key)
            return replace(existing, cache_hit=True)

    records: list[RepositoryFile] = []
    scanned_bytes = 0
    bounded = "file-limit" in skipped
    for relative, path, stat in candidates:
        if stat.st_size > MAX_FILE_BYTES:
            _increment(skipped, "file-too-large")
            continue
        if scanned_bytes + stat.st_size > MAX_SCAN_BYTES:
            _increment(skipped, "scan-byte-limit")
            bounded = True
            continue
        try:
            data = path.read_bytes()
            if b"\x00" in data:
                _increment(skipped, "binary-content")
                continue
            text = _decode(data)
        except (OSError, UnicodeError):
            _increment(skipped, "encoding-or-read-error")
            continue
        scanned_bytes += len(data)
        records.append(
            RepositoryFile(
                path=relative,
                size=len(data),
                modified_ns=stat.st_mtime_ns,
                changed_ns=stat.st_ctime_ns,
                sha256=hashlib.sha256(data).hexdigest(),
                text=text,
                lines=tuple(text.splitlines()),
            )
        )
    identity = [{"path": item.path, "sha256": item.sha256, "size": item.size} for item in records]
    snapshot_id = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    value = RepositorySnapshot(
        snapshot_id=snapshot_id,
        metadata_fingerprint=metadata_fingerprint,
        files=tuple(records),
        scanned_bytes=scanned_bytes,
        skipped=tuple(sorted(skipped.items())),
        state="bounded" if bounded else "complete",
    )
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > MAX_CACHE_ROOTS:
            _CACHE.popitem(last=False)
    return value


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["MAX_FILE_BYTES", "MAX_FILES", "MAX_SCAN_BYTES", "clear_cache", "snapshot"]
