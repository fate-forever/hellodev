"""Portable policy ledger-head checkpoints for CI, Git, or external hosts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import host_bridge, policy_evolution
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json


SCHEMA_VERSION = 1
MAX_CHECKPOINT_BYTES = 64 * 1024


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _payload(checkpoint: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in checkpoint.items() if key != "checkpointSha256"}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "ledgerId", "sequence", "headSha256", "hostProtocolVersion",
        "exportedAt", "checkpointSha256",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ProjectError("invalid policy checkpoint fields")
    if value.get("ledgerId") != policy_evolution.LEDGER_ID:
        raise ProjectError("policy checkpoint belongs to another ledger")
    if type(value.get("sequence")) is not int or value["sequence"] < 0:
        raise ProjectError("invalid policy checkpoint sequence")
    head = value.get("headSha256")
    if head != policy_evolution.GENESIS and not _valid_sha256(head):
        raise ProjectError("invalid policy checkpoint head")
    host_bridge.protocol_info([value.get("hostProtocolVersion")])
    if not isinstance(value.get("exportedAt"), str) or not value["exportedAt"]:
        raise ProjectError("invalid policy checkpoint timestamp")
    if not _valid_sha256(value.get("checkpointSha256")) or value["checkpointSha256"] != _digest(_payload(value)):
        raise ProjectError("policy checkpoint digest mismatch")
    return value


def load_file(value: str | Path) -> dict[str, Any]:
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ProjectError("policy checkpoint file is unavailable or unsafe")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ProjectError(f"cannot inspect policy checkpoint file: {error}") from error
    if not 0 < size <= MAX_CHECKPOINT_BYTES:
        raise ProjectError(f"policy checkpoint file exceeds {MAX_CHECKPOINT_BYTES} bytes")
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid policy checkpoint file: {error}") from error
    return validate(checkpoint)


def export(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    status = policy_evolution.status(resolved)
    checkpoint = {
        "schemaVersion": SCHEMA_VERSION,
        "ledgerId": policy_evolution.LEDGER_ID,
        "sequence": status["ledgerHead"]["sequence"],
        "headSha256": status["ledgerHead"]["eventSha256"],
        "hostProtocolVersion": host_bridge.HOST_PROTOCOL_VERSION,
        "exportedAt": utc_now(),
        "checkpointSha256": "",
    }
    checkpoint["checkpointSha256"] = _digest(_payload(checkpoint))
    return validate(checkpoint)


def verify(root: str | Path, checkpoint_value: Any) -> dict[str, Any]:
    resolved = resolve_root(root)
    checkpoint = validate(checkpoint_value)
    policy = policy_evolution.status(resolved)
    current = policy["ledgerHead"]
    matched = checkpoint["sequence"] == current["sequence"] and checkpoint["headSha256"] == current["eventSha256"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "matched" if matched else "mismatch",
        "matched": matched,
        "expected": {"sequence": checkpoint["sequence"], "headSha256": checkpoint["headSha256"]},
        "current": current,
        "checkpointSha256": checkpoint["checkpointSha256"],
        "guarantee": "detects divergence from this portable checkpoint; not a tamper-proof or non-repudiation ledger",
        "executionPerformed": False,
        "persistencePerformed": False,
    }


def save(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    load_config(resolved)
    path = ProjectPaths(resolved).policy_checkpoint_file
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ProjectError("refusing unsafe policy checkpoint file")
    checkpoint = export(resolved)
    write_json(path, checkpoint)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "saved",
        "checkpoint": checkpoint,
        "portableCopyRequired": True,
        "persistencePerformed": True,
    }


def _saved(root: Path) -> dict[str, Any] | None:
    path = ProjectPaths(root).policy_checkpoint_file
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProjectError("refusing unsafe policy checkpoint file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid saved policy checkpoint: {error}") from error
    return validate(value)


def status(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    saved = _saved(resolved)
    if saved is None:
        current = policy_evolution.status(resolved)["ledgerHead"]
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "not-saved",
            "matched": None,
            "current": current,
            "checkpointSha256": None,
            "portableCopyRequired": True,
            "executionPerformed": False,
        }
    result = verify(resolved, saved)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": result["state"],
        "matched": result["matched"],
        "current": result["current"],
        "checkpointSha256": result["checkpointSha256"],
        "portableCopyRequired": True,
        "executionPerformed": False,
    }
