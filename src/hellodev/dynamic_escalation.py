"""Deterministic failure escalation for the current WorkItem and snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import contracts
from .command_rendering import command_line
from .context_runtime.native import snapshot as repository_snapshot
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
MAX_EVENTS = 300
EVENTS = {"verification-failed", "unchanged-retry", "verification-succeeded", "finish-blocked"}
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _path(root: Path) -> Path:
    load_config(root)
    path = ProjectPaths(root).state_dir / "dynamic-escalation.json"
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ProjectError("dynamic escalation store is unsafe")
    return path


def _load(root: Path) -> dict[str, Any]:
    path = _path(root)
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "events": [], "diagnoses": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid dynamic escalation store: {error}") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ProjectError("invalid dynamic escalation store schema")
    if not isinstance(value.get("events"), list) or not isinstance(value.get("diagnoses"), list):
        raise ProjectError("invalid dynamic escalation store schema")
    if len(value["events"]) > MAX_EVENTS or len(value["diagnoses"]) > MAX_EVENTS:
        raise ProjectError("dynamic escalation store exceeds safety limit")
    return value


def _identity(root: Path, command_sha256: str) -> dict[str, str]:
    if DIGEST.fullmatch(command_sha256 or "") is None:
        raise ProjectError("dynamic escalation command identity must be a SHA-256 digest")
    work = contracts.current_work_item(root)
    if work is None:
        raise ProjectError("dynamic escalation requires a current WorkItem")
    return {
        "workItemId": work["id"],
        "commandSha256": command_sha256,
        "repositorySnapshot": repository_snapshot(root).snapshot_id,
    }


def record(root: str | Path, event: str, command_sha256: str, reason_code: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    if event not in EVENTS or not isinstance(reason_code, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", reason_code):
        raise ProjectError("invalid dynamic escalation event")
    identity = _identity(resolved, command_sha256)
    item = {**identity, "event": event, "reasonCode": reason_code, "recordedAt": utc_now()}
    with locked_state(resolved, "dynamic-escalation"):
        store = _load(resolved)
        store["events"].append(item)
        store["events"] = store["events"][-MAX_EVENTS:]
        write_json(_path(resolved), store)
    return item


def record_finish_blocked(root: str | Path, reason_code: str) -> dict[str, Any]:
    digest = hashlib.sha256(b"hellodev do finish").hexdigest()
    return record(root, "finish-blocked", digest, reason_code)


def status(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    work = contracts.current_work_item(resolved)
    if work is None:
        return {"schemaVersion": 1, "state": "inactive", "active": False, "failureCount": 0}
    current_snapshot = repository_snapshot(resolved).snapshot_id
    store = _load(resolved)
    matching = [
        item for item in store["events"]
        if item["workItemId"] == work["id"] and item["repositorySnapshot"] == current_snapshot
    ]
    if not matching:
        return {"schemaVersion": 1, "state": "inactive", "active": False, "failureCount": 0}
    by_command: dict[str, list[dict[str, Any]]] = {}
    for item in matching:
        by_command.setdefault(item["commandSha256"], []).append(item)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for command, events in by_command.items():
        last_success = max(
            (index for index, item in enumerate(events) if item["event"] == "verification-succeeded"),
            default=-1,
        )
        grouped[command] = [item for item in events[last_success + 1:] if item["event"] != "verification-succeeded"]
    command_sha, repeated = max(grouped.items(), key=lambda pair: len(pair[1]), default=("", []))
    active = len(repeated) >= 2
    diagnosis = next(
        (
            item for item in reversed(store["diagnoses"])
            if item["workItemId"] == work["id"]
            and item["repositorySnapshot"] == current_snapshot
            and item["commandSha256"] == command_sha
        ),
        None,
    )
    state = "diagnosed" if active and diagnosis is not None else "strict" if active else "watching"
    return {
        "schemaVersion": 1,
        "state": state,
        "active": active,
        "failureCount": len(repeated),
        "workItemId": work["id"],
        "repositorySnapshot": current_snapshot,
        "commandSha256": command_sha or None,
        "reasonCodes": list(dict.fromkeys(item["reasonCode"] for item in repeated)),
        "diagnosis": diagnosis,
        "policy": {
            "verificationLevel": "T2" if active else None,
            "strictDiagnosticsRequired": active and diagnosis is None,
            "targetedContextAllowed": True,
            "outputNoiseReduction": active,
            "contextBudgetHalved": False,
            "subagentSpawned": False,
        },
    }


def diagnose(root: str | Path, cause: str, strategy: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    current = status(resolved)
    if not current["active"]:
        raise ProjectError("dynamic escalation diagnosis requires an active repeated-failure escalation")
    for label, value in (("diagnostic cause", cause), ("replacement strategy", strategy)):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500 or any(c in value for c in "\r\n\x00"):
            raise ProjectError(f"{label} must be one non-empty line of at most 500 characters")
    item = {
        "workItemId": current["workItemId"],
        "commandSha256": current["commandSha256"],
        "repositorySnapshot": current["repositorySnapshot"],
        "causeSha256": hashlib.sha256(cause.strip().encode("utf-8")).hexdigest(),
        "strategySha256": hashlib.sha256(strategy.strip().encode("utf-8")).hexdigest(),
        "recordedAt": utc_now(),
    }
    with locked_state(resolved, "dynamic-escalation"):
        store = _load(resolved)
        store["diagnoses"].append(item)
        store["diagnoses"] = store["diagnoses"][-MAX_EVENTS:]
        write_json(_path(resolved), store)
    return {
        "schemaVersion": 1,
        "state": "diagnosed",
        "diagnosis": item,
        "next": command_line(resolved, "do", "work", "--note", "apply-the-reviewed-replacement-strategy"),
        "rawDiagnosticPersisted": False,
        "subagentSpawned": False,
        "executionPerformed": False,
    }


def next_action(root: str | Path) -> dict[str, Any] | None:
    resolved = resolve_root(root)
    current = status(resolved)
    if not current["active"]:
        return None
    if current["diagnosis"] is None:
        return {
            "schemaVersion": 1,
            "command": command_line(
                resolved, "escalation", "diagnose", "--cause", "<bounded-root-cause>",
                "--strategy", "<different-bounded-strategy>",
            ),
            "reason": "Repeated failure on the same WorkItem, command and repository snapshot requires a diagnostic summary before retry.",
            "reasonCode": "dynamic-escalation-diagnostic-required",
            "suggestedLevel": "L2",
            "escalation": current,
            "executionPerformed": False,
        }
    return {
        "schemaVersion": 1,
        "command": command_line(resolved, "do", "work", "--note", "apply-the-reviewed-replacement-strategy"),
        "reason": "The strict diagnostic is recorded; change the affected inputs before verification retry.",
        "reasonCode": "dynamic-escalation-strategy-required",
        "suggestedLevel": "L2",
        "escalation": current,
        "executionPerformed": False,
    }


__all__ = ["diagnose", "next_action", "record", "record_finish_blocked", "status"]
