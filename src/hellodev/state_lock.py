"""Cross-process locks for small project-local read/modify/write stores."""

from __future__ import annotations

import os
import re
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .project import ProjectError, ProjectPaths, load_config, resolve_root


_LOCK_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_THREAD_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}


def _thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _THREAD_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


def _lstat(path: Path) -> os.stat_result | None:
    try:
        if path.is_symlink():
            raise ProjectError(f"refusing symlinked HelloDev state lock: {path}")
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except ProjectError:
        raise
    except OSError as error:
        raise ProjectError(f"cannot inspect HelloDev state lock: {error}") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise ProjectError(f"refusing symlinked HelloDev state lock: {path}")
    return metadata


def _lock_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
    except (ImportError, OSError) as error:
        raise ProjectError(f"cannot acquire HelloDev state lock: {error}") from error


def _unlock_descriptor(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except (ImportError, OSError) as error:
        raise ProjectError(f"cannot release HelloDev state lock: {error}") from error


@contextmanager
def locked_state(root: str | Path, name: str) -> Iterator[None]:
    if _LOCK_NAME.fullmatch(name) is None:
        raise ProjectError("HelloDev state lock name is invalid")
    resolved = resolve_root(root)
    load_config(resolved)
    lock_path = ProjectPaths(resolved).state_dir / f".{name}.lock"
    local_lock = _thread_lock(lock_path)
    with local_lock:
        _lstat(lock_path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as error:
            raise ProjectError(f"cannot open HelloDev state lock: {error}") from error
        acquired = False
        try:
            path_metadata = _lstat(lock_path)
            open_metadata = os.fstat(descriptor)
            if path_metadata is None or not os.path.samestat(path_metadata, open_metadata):
                raise ProjectError(f"HelloDev state lock changed while opening: {lock_path}")
            if not stat.S_ISREG(open_metadata.st_mode):
                raise ProjectError(f"HelloDev state lock is not a regular file: {lock_path}")
            _lock_descriptor(descriptor)
            acquired = True
            yield
        finally:
            try:
                if acquired:
                    _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)
