"""One-time confirmations for direct external adapter invocations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json


_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approval_lock_path(paths: ProjectPaths) -> Path:
    return paths.approvals_file.with_name(f"{paths.approvals_file.name}.lock")


def _thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


def _safe_lstat(path: Path, label: str) -> os.stat_result | None:
    """Return path identity while refusing links and unreadable path state."""
    try:
        # Keep the explicit check as a clear policy boundary on platforms whose
        # lstat metadata exposes reparse points differently.
        if path.is_symlink():
            raise ProjectError(f"refusing symlinked HelloDev {label}: {path}")
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except ProjectError:
        raise
    except OSError as error:
        raise ProjectError(f"cannot inspect HelloDev {label}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise ProjectError(f"refusing symlinked HelloDev {label}: {path}")
    return metadata


def _verify_open_identity(path: Path, descriptor: int, label: str) -> os.stat_result:
    path_metadata = _safe_lstat(path, label)
    if path_metadata is None:
        raise ProjectError(f"HelloDev {label} disappeared while opening: {path}")
    try:
        open_metadata = os.fstat(descriptor)
    except OSError as error:
        raise ProjectError(f"cannot inspect open HelloDev {label}: {error}") from error
    if not os.path.samestat(path_metadata, open_metadata):
        raise ProjectError(f"HelloDev {label} changed while opening: {path}")
    return open_metadata


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
        raise ProjectError(f"cannot acquire HelloDev approval store lock: {error}") from error


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
        raise ProjectError(f"cannot release HelloDev approval store lock: {error}") from error


def _open_lock(path: Path) -> int:
    _safe_lstat(path, "approval store lock")
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise ProjectError(f"cannot open HelloDev approval store lock: {error}") from error
    try:
        metadata = _verify_open_identity(path, descriptor, "approval store lock")
        if not stat.S_ISREG(metadata.st_mode):
            raise ProjectError(f"HelloDev approval store lock is not a regular file: {path}")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _locked_store(paths: ProjectPaths) -> Iterator[None]:
    """Serialize approval-store read/modify/write across threads and processes."""
    lock_path = _approval_lock_path(paths)
    local_lock = _thread_lock(lock_path)
    with local_lock:
        # Check both before and after acquiring the OS lock. This refuses an
        # existing unsafe store without relying on the lock file to protect it.
        _safe_lstat(paths.approvals_file, "approval store")
        descriptor = _open_lock(lock_path)
        acquired = False
        try:
            _lock_descriptor(descriptor)
            acquired = True
            _verify_open_identity(lock_path, descriptor, "approval store lock")
            _safe_lstat(paths.approvals_file, "approval store")
            yield
        finally:
            try:
                if acquired:
                    _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)


def _read_store(paths: ProjectPaths) -> dict[str, Any]:
    metadata = _safe_lstat(paths.approvals_file, "approval store")
    if metadata is None:
        return {"schemaVersion": 1, "plans": []}
    if not stat.S_ISREG(metadata.st_mode):
        raise ProjectError("HelloDev approval store is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(paths.approvals_file, flags)
        try:
            _verify_open_identity(paths.approvals_file, descriptor, "approval store")
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                store = json.load(handle)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev approval store: {error}") from error
    if not isinstance(store, dict) or store.get("schemaVersion") != 1 or not isinstance(store.get("plans"), list):
        raise ProjectError("invalid HelloDev approval store schema")
    return store


def prepare(root: Path, payload: dict[str, Any], risk: str) -> dict[str, Any]:
    if risk not in {"read", "write", "policy"}:
        raise ProjectError("approval risk must be read, write, or policy")
    load_config(root)
    paths = ProjectPaths(Path(root).expanduser().resolve())
    secret = secrets.token_hex(24)
    token_prefix = {
        "read": "APPROVE-EXTERNAL",
        "write": "APPROVE-WRITE",
        "policy": "APPROVE-POLICY",
    }[risk]
    token = f"{token_prefix}:{secret}"
    payload_hash = _canonical_digest(payload)
    with _locked_store(paths):
        store = _read_store(paths)
        store["plans"].append(
            {
                "payloadSha256": payload_hash,
                "risk": risk,
                "tokenSha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "createdAt": utc_now(),
                "consumedAt": None,
            }
        )
        _safe_lstat(paths.approvals_file, "approval store")
        write_json(paths.approvals_file, store)
    return {"state": "awaiting-confirmation", "risk": risk, "approval": token, "payloadSha256": payload_hash}


def consume(root: Path, payload: dict[str, Any], token: str, risk: str) -> None:
    if risk not in {"read", "write", "policy"}:
        raise ProjectError("approval risk must be read, write, or policy")
    load_config(root)
    paths = ProjectPaths(Path(root).expanduser().resolve())
    payload_hash = _canonical_digest(payload)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _locked_store(paths):
        store = _read_store(paths)
        for plan in store["plans"]:
            if (
                plan.get("consumedAt") is None
                and plan.get("risk") == risk
                and hmac.compare_digest(str(plan.get("payloadSha256", "")), payload_hash)
                and hmac.compare_digest(str(plan.get("tokenSha256", "")), token_hash)
            ):
                plan["consumedAt"] = utc_now()
                _safe_lstat(paths.approvals_file, "approval store")
                write_json(paths.approvals_file, store)
                return
    raise ProjectError("approval token is invalid, already consumed, or does not match this exact operation")


def prepare_policy_change(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Prepare an exact profile/policy mutation under a distinct token class."""
    from . import profiles

    payload = profiles.policy_change_payload(root, policy)
    plan = prepare(root, payload, "policy")
    return {
        **plan,
        "authorizationProfile": payload["proposedPolicy"]["authorizationProfile"],
        "policySha256": _canonical_digest(payload["proposedPolicy"]),
    }


def consume_policy_change(
    root: Path,
    policy: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    """Consume the policy token, apply the exact proposal, and write an audit receipt."""
    from . import profiles, receipts

    payload = profiles.policy_change_payload(root, policy)
    previous = profiles.current_policy(root)
    # Fail before consuming the one-time token if the receipt store is unsafe.
    receipts.list_receipts(root)
    consume(root, payload, token, "policy")
    applied = profiles._apply_policy(root, payload["proposedPolicy"])
    receipt = receipts.record(
        root,
        "hellodev",
        "authorization-policy.change",
        "write",
        {"proposedPolicy": payload["proposedPolicy"]},
        {"previousProfile": previous["authorizationProfile"], "applied": applied},
        True,
        kind="policy",
        profile_used=previous["authorizationProfile"],
        authorization_mode="token-required",
    )
    return {"policy": applied, "receipt": receipt}
