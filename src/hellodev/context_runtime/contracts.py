"""Internal immutable contracts for native repository context acquisition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    path: str
    size: int
    modified_ns: int
    changed_ns: int
    sha256: str
    text: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    snapshot_id: str
    metadata_fingerprint: str
    files: tuple[RepositoryFile, ...]
    scanned_bytes: int
    skipped: tuple[tuple[str, int], ...]
    state: str
    cache_hit: bool = False


__all__ = ["RepositoryFile", "RepositorySnapshot"]
