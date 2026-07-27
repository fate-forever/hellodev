"""Scoped, hash-only planning and sessions for host-executed verification."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast

from . import changesets, contracts
from .command_rendering import command_line
from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json
from .state_lock import locked_state


VerificationLevel = Literal["T0", "T1", "T2"]
VerificationOutcome = Literal["succeeded", "failed"]
VerificationScope = Literal["code", "docs", "project"]

STORE_SCHEMA_VERSION = 2
MAX_RECORDS = 500
MAX_SESSIONS = 500
SESSION_TTL_MINUTES = 60
LEVELS = {"T0", "T1", "T2"}
OUTCOMES = {"succeeded", "failed"}
SCOPES = {"code", "docs", "project"}
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^verification-[0-9]{4,}$")
SESSION_ID_PATTERN = re.compile(r"^verification-session-[0-9]{4,}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RECORD_FIELDS = {
    "id", "level", "commandSha256", "scope", "scopeSnapshot", "repositorySnapshot",
    "workItemId", "outcome", "sourceTrust", "durationMs", "recordedAt", "sessionId",
}
SESSION_FIELDS = {
    "id", "level", "commandSha256", "scope", "scopeSnapshot", "repositorySnapshot",
    "workItemId", "createdAt", "expiresAt", "state", "consumedAt", "outcome",
}
LEGACY_RECORD_FIELDS = RECORD_FIELDS - {"scope", "scopeSnapshot", "sessionId"}


def _command(value: str) -> str:
    if not isinstance(value, str):
        raise ProjectError("verification command must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 1000 or any(character in normalized for character in "\r\n\x00"):
        raise ProjectError("verification command must be a non-empty single line of 1000 characters or fewer")
    return normalized


def _level(value: str) -> VerificationLevel:
    if not isinstance(value, str) or value.upper() not in LEVELS:
        raise ProjectError("verification level must be T0, T1, or T2")
    return cast(VerificationLevel, value.upper())


def _scope(value: str | None, level: VerificationLevel) -> VerificationScope:
    selected = (value or "auto").lower()
    if selected == "auto":
        selected = "project" if level == "T2" else "code"
    if selected not in SCOPES:
        raise ProjectError("verification scope must be auto, code, docs, or project")
    return cast(VerificationScope, selected)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _work_item_id(root: Path) -> str | None:
    current = contracts.current_work_item(root)
    return current["id"] if current is not None else None


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"invalid progressive verification {field}")
    return value


def _validate_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"invalid progressive verification {field}")


def _validate_work_item(value: Any) -> None:
    if value is not None and (not isinstance(value, str) or re.fullmatch(r"work-[0-9]{4,}", value) is None):
        raise ProjectError("invalid progressive verification WorkItem id")


def _validate_duration(value: Any) -> None:
    if value is not None and (type(value) is not int or not 0 <= value <= 86_400_000):
        raise ProjectError("verification durationMs must be null or an integer between 0 and 86400000")


def _normalize_record(value: Any, *, legacy: bool = False) -> dict[str, Any]:
    expected = LEGACY_RECORD_FIELDS if legacy else RECORD_FIELDS
    if not isinstance(value, dict) or set(value) != expected:
        raise ProjectError("invalid progressive verification record fields")
    item = dict(value)
    if legacy:
        item.update({"scope": "project", "scopeSnapshot": item["repositorySnapshot"], "sessionId": None})
    if not isinstance(item.get("id"), str) or ID_PATTERN.fullmatch(item["id"]) is None:
        raise ProjectError("invalid progressive verification record id")
    if item.get("level") not in LEVELS or item.get("scope") not in SCOPES:
        raise ProjectError("invalid progressive verification level or scope")
    for field in ("commandSha256", "scopeSnapshot", "repositorySnapshot"):
        _validate_digest(item.get(field), field)
    _validate_work_item(item.get("workItemId"))
    if item.get("outcome") not in OUTCOMES or item.get("sourceTrust") != "host-asserted":
        raise ProjectError("invalid progressive verification outcome or sourceTrust")
    _validate_duration(item.get("durationMs"))
    _timestamp(item.get("recordedAt"), "timestamp")
    session_id = item.get("sessionId")
    if session_id is not None and (not isinstance(session_id, str) or SESSION_ID_PATTERN.fullmatch(session_id) is None):
        raise ProjectError("invalid progressive verification session id")
    return item


def _validate_session(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != SESSION_FIELDS:
        raise ProjectError("invalid verification session fields")
    if not isinstance(value.get("id"), str) or SESSION_ID_PATTERN.fullmatch(value["id"]) is None:
        raise ProjectError("invalid verification session id")
    if value.get("level") not in LEVELS or value.get("scope") not in SCOPES:
        raise ProjectError("invalid verification session level or scope")
    for field in ("commandSha256", "scopeSnapshot", "repositorySnapshot"):
        _validate_digest(value.get(field), field)
    _validate_work_item(value.get("workItemId"))
    _timestamp(value.get("createdAt"), "session createdAt")
    _timestamp(value.get("expiresAt"), "session expiresAt")
    if value.get("state") not in {"pending", "consumed"}:
        raise ProjectError("invalid verification session state")
    if value["state"] == "pending" and (value.get("consumedAt") is not None or value.get("outcome") is not None):
        raise ProjectError("pending verification session cannot have an outcome")
    if value["state"] == "consumed":
        _timestamp(value.get("consumedAt"), "session consumedAt")
        if value.get("outcome") not in OUTCOMES:
            raise ProjectError("consumed verification session must have an outcome")
    return value


def _load(root: Path) -> dict[str, Any]:
    load_config(root)
    path = ProjectPaths(root).verification_file
    if not path.exists():
        return {"schemaVersion": STORE_SCHEMA_VERSION, "records": [], "sessions": []}
    if path.is_symlink():
        raise ProjectError("refusing symlinked progressive verification store")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid progressive verification store: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ProjectError("invalid progressive verification store schema")
    if value.get("schemaVersion") == 1 and set(value) == {"schemaVersion", "records"}:
        records = [_normalize_record(item, legacy=True) for item in value["records"]]
        sessions: list[dict[str, Any]] = []
    elif value.get("schemaVersion") == STORE_SCHEMA_VERSION and set(value) == {"schemaVersion", "records", "sessions"} and isinstance(value.get("sessions"), list):
        records = [_normalize_record(item) for item in value["records"]]
        sessions = [_validate_session(item) for item in value["sessions"]]
    else:
        raise ProjectError("invalid progressive verification store schema")
    ids = [item["id"] for item in records]
    session_ids = [item["id"] for item in sessions]
    if len(ids) != len(set(ids)) or len(session_ids) != len(set(session_ids)) or len(records) > MAX_RECORDS or len(sessions) > MAX_SESSIONS:
        raise ProjectError("invalid progressive verification collection")
    return {"schemaVersion": STORE_SCHEMA_VERSION, "records": records, "sessions": sessions}


def _write(root: Path, store: dict[str, Any]) -> None:
    write_json(ProjectPaths(root).verification_file, store)


def _next_id(items: list[dict[str, Any]], prefix: str) -> str:
    highest = max((int(item["id"].removeprefix(prefix)) for item in items), default=0)
    return f"{prefix}{highest + 1:04d}"


def _identity(root: Path, command: str, scope: VerificationScope) -> dict[str, Any]:
    scoped = changesets.scope_identity(root, scope)
    return {"commandSha256": _digest(command), **scoped, "workItemId": _work_item_id(root)}


def _latest_exact(records: list[dict[str, Any]], identity: dict[str, Any], level: VerificationLevel) -> dict[str, Any] | None:
    fields = ("commandSha256", "scope", "scopeSnapshot", "workItemId")
    return next((item for item in reversed(records) if item["level"] == level and all(item[field] == identity[field] for field in fields)), None)


def _expires_at() -> str:
    value = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=SESSION_TTL_MINUTES)
    return value.isoformat().replace("+00:00", "Z")


def _expired(session: dict[str, Any]) -> bool:
    expires = datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) >= expires


def plan(root: Path, level: str, command: str, scope: str | None = None) -> dict[str, Any]:
    selected_level = _level(level)
    selected_command = _command(command)
    selected_scope = _scope(scope, selected_level)
    identity = _identity(root, selected_command, selected_scope)
    with locked_state(root, "verification"):
        store = _load(root)
        exact = _latest_exact(store["records"], identity, selected_level)
        base = {
            "schemaVersion": 2, "level": selected_level, "command": selected_command, **identity,
            "sourceTrust": "host-asserted", "testExecutionPerformed": False,
            "persistencePerformed": False, "trellisGateSatisfied": False,
        }
        if exact is not None and exact["outcome"] == "succeeded":
            return {**base, "state": "reused-success", "runRequired": False,
                    "reasonCode": "same-command-and-scope-snapshot-succeeded", "reusedRecordId": exact["id"],
                    "estimatedAvoidedDurationMs": exact["durationMs"]}
        if exact is not None:
            return {**base, "state": "blocked-unchanged-failure", "runRequired": False,
                    "reasonCode": "same-command-and-scope-snapshot-already-failed", "failedRecordId": exact["id"],
                    "next": "Change files in the verification scope or diagnose the environment before retrying."}
        pending = next(
            (
                item for item in reversed(store["sessions"])
                if item["state"] == "pending"
                and not _expired(item)
                and item["level"] == selected_level
                and all(item[field] == identity[field] for field in ("commandSha256", "scope", "scopeSnapshot", "workItemId"))
            ),
            None,
        )
        if pending is not None:
            continuation = ["do", "verify", "--session", pending["id"]]
            return {
                **base, "state": "run-required", "runRequired": True,
                "reasonCode": "verification-session-already-pending", "session": pending,
                "recordSucceededCommand": command_line(root, *continuation, "--outcome", "succeeded", "--duration-ms", "<milliseconds>"),
                "recordFailedCommand": command_line(root, *continuation, "--outcome", "failed", "--duration-ms", "<milliseconds>"),
            }
        if len(store["sessions"]) >= MAX_SESSIONS:
            raise ProjectError("progressive verification store reached its 500-session safety limit")
        session = {
            "id": _next_id(store["sessions"], "verification-session-"), "level": selected_level,
            "commandSha256": identity["commandSha256"], "scope": selected_scope,
            "scopeSnapshot": identity["scopeSnapshot"], "repositorySnapshot": identity["repositorySnapshot"],
            "workItemId": identity["workItemId"], "createdAt": utc_now(), "expiresAt": _expires_at(),
            "state": "pending", "consumedAt": None, "outcome": None,
        }
        _validate_session(session)
        store["sessions"].append(session)
        _write(root, store)
    continuation = ["do", "verify", "--session", session["id"]]
    return {
        **base, "state": "run-required", "runRequired": True,
        "reasonCode": "no-current-scoped-verification-evidence", "session": session,
        "persistencePerformed": True,
        "recordSucceededCommand": command_line(root, *continuation, "--outcome", "succeeded", "--duration-ms", "<milliseconds>"),
        "recordFailedCommand": command_line(root, *continuation, "--outcome", "failed", "--duration-ms", "<milliseconds>"),
    }


def inspect(root: Path, level: str, command: str, scope: str | None = None) -> dict[str, Any]:
    """Inspect exact reusable evidence without creating a verification session."""
    selected_level = _level(level)
    selected_command = _command(command)
    selected_scope = _scope(scope, selected_level)
    identity = _identity(root, selected_command, selected_scope)
    store = _load(root)
    base = {
        "schemaVersion": 1,
        "level": selected_level,
        "scope": selected_scope,
        "commandSha256": identity["commandSha256"],
        "scopeSnapshot": identity["scopeSnapshot"],
        "repositorySnapshot": identity["repositorySnapshot"],
        "workItemId": identity["workItemId"],
        "readOnly": True,
        "executionPerformed": False,
        "persistencePerformed": False,
        "rawCommandPersisted": False,
        "trellisGateSatisfied": False,
    }
    exact = _latest_exact(store["records"], identity, selected_level)
    if exact is not None and exact["outcome"] == "succeeded":
        return {
            **base,
            "state": "reused-success",
            "runRequired": False,
            "reasonCode": "same-command-and-scope-snapshot-succeeded",
            "reusedRecordId": exact["id"],
            "estimatedAvoidedDurationMs": exact["durationMs"],
        }
    if exact is not None:
        return {
            **base,
            "state": "blocked-unchanged-failure",
            "runRequired": False,
            "reasonCode": "same-command-and-scope-snapshot-already-failed",
            "failedRecordId": exact["id"],
            "estimatedAvoidedDurationMs": 0,
        }
    pending = next(
        (
            item for item in reversed(store["sessions"])
            if item["state"] == "pending"
            and not _expired(item)
            and item["level"] == selected_level
            and all(
                item[field] == identity[field]
                for field in ("commandSha256", "scope", "scopeSnapshot", "workItemId")
            )
        ),
        None,
    )
    if pending is not None:
        return {
            **base,
            "state": "pending",
            "runRequired": True,
            "reasonCode": "verification-session-already-pending",
            "sessionId": pending["id"],
            "estimatedAvoidedDurationMs": 0,
        }
    return {
        **base,
        "state": "missing",
        "runRequired": True,
        "reasonCode": "no-current-scoped-verification-evidence",
        "estimatedAvoidedDurationMs": 0,
    }


def _append_record(store: dict[str, Any], identity: dict[str, Any], level: VerificationLevel,
                   outcome: str, duration_ms: int | None, session_id: str | None) -> dict[str, Any]:
    if len(store["records"]) >= MAX_RECORDS:
        raise ProjectError("progressive verification store reached its 500-record safety limit")
    item = {
        "id": _next_id(store["records"], "verification-"), "level": level,
        "commandSha256": identity["commandSha256"], "scope": identity["scope"],
        "scopeSnapshot": identity["scopeSnapshot"], "repositorySnapshot": identity["repositorySnapshot"],
        "workItemId": identity["workItemId"], "outcome": outcome, "sourceTrust": "host-asserted",
        "durationMs": duration_ms, "recordedAt": utc_now(), "sessionId": session_id,
    }
    return _normalize_record(item)


def record(root: Path, level: str, command: str, expected_snapshot: str, outcome: str,
           duration_ms: int | None = None, scope: str | None = None) -> dict[str, Any]:
    selected_level = _level(level)
    selected_command = _command(command)
    selected_scope = _scope(scope, selected_level)
    _validate_digest(expected_snapshot, "snapshot")
    if outcome not in OUTCOMES:
        raise ProjectError("verification outcome must be succeeded or failed")
    _validate_duration(duration_ms)
    identity = _identity(root, selected_command, selected_scope)
    if identity["repositorySnapshot"] != expected_snapshot:
        raise ProjectError("repository changed after verification planning; replan and rerun the affected check")
    with locked_state(root, "verification"):
        store = _load(root)
        exact = _latest_exact(store["records"], identity, selected_level)
        if exact is not None:
            if exact["outcome"] == "succeeded" and outcome == "succeeded":
                return {"schemaVersion": 2, "state": "already-recorded", "record": exact,
                        "persistencePerformed": False, "testExecutionPerformed": False, "trellisGateSatisfied": False}
            if exact["outcome"] == "failed":
                raise ProjectError("unchanged failed verification cannot be recorded again; change inputs before retrying")
            raise ProjectError("refusing contradictory verification outcome for an unchanged successful check")
        pending = next(
            (
                session for session in reversed(store["sessions"])
                if session["state"] == "pending"
                and session["level"] == selected_level
                and all(session[field] == identity[field] for field in ("commandSha256", "scope", "scopeSnapshot", "workItemId"))
            ),
            None,
        )
        item = _append_record(
            store, identity, selected_level, outcome, duration_ms,
            pending["id"] if pending is not None else None,
        )
        store["records"].append(item)
        if pending is not None:
            pending.update({"state": "consumed", "consumedAt": utc_now(), "outcome": outcome})
        _write(root, store)
    return {"schemaVersion": 2, "state": "recorded", "record": item, "persistencePerformed": True,
            "testExecutionPerformed": False, "trellisGateSatisfied": False}


def record_session(root: Path, session_id: str, outcome: str, duration_ms: int | None = None) -> dict[str, Any]:
    if not isinstance(session_id, str) or SESSION_ID_PATTERN.fullmatch(session_id) is None:
        raise ProjectError("invalid verification session id")
    if outcome not in OUTCOMES:
        raise ProjectError("verification outcome must be succeeded or failed")
    _validate_duration(duration_ms)
    with locked_state(root, "verification"):
        store = _load(root)
        session = next((item for item in store["sessions"] if item["id"] == session_id), None)
        if session is None:
            raise ProjectError(f"verification session not found: {session_id}")
        if session["state"] != "pending":
            raise ProjectError("verification session has already been consumed; replay is refused")
        if _expired(session):
            raise ProjectError("verification session expired; plan and execute the check again")
        if session["workItemId"] != _work_item_id(root):
            raise ProjectError("current WorkItem changed after verification planning; plan and execute the check again")
        scoped = changesets.scope_identity(root, session["scope"])
        if scoped["scopeSnapshot"] != session["scopeSnapshot"]:
            raise ProjectError("verification scope changed after planning; plan and execute the check again")
        identity = {
            "commandSha256": session["commandSha256"], "scope": session["scope"],
            "scopeSnapshot": scoped["scopeSnapshot"], "repositorySnapshot": scoped["repositorySnapshot"],
            "workItemId": session["workItemId"],
        }
        exact = _latest_exact(store["records"], identity, cast(VerificationLevel, session["level"]))
        if exact is not None:
            raise ProjectError("verification evidence for this session identity already exists")
        item = _append_record(store, identity, cast(VerificationLevel, session["level"]), outcome, duration_ms, session_id)
        store["records"].append(item)
        session.update({"state": "consumed", "consumedAt": utc_now(), "outcome": outcome})
        _write(root, store)
    return {"schemaVersion": 2, "state": "recorded", "record": item, "session": session,
            "persistencePerformed": True, "testExecutionPerformed": False, "trellisGateSatisfied": False}


def summary(root: Path) -> dict[str, Any]:
    store = _load(root)
    work_item_id = _work_item_id(root)
    snapshots: dict[str, str] = {}
    if store["records"] or store["sessions"]:
        for scope in SCOPES:
            try:
                snapshots[scope] = changesets.scope_identity(root, scope)["scopeSnapshot"]
            except ProjectError:
                snapshots = {}
                break
    current_records = [item for item in store["records"] if item["workItemId"] == work_item_id and snapshots.get(item["scope"]) == item["scopeSnapshot"]]
    pending = [item for item in store["sessions"] if item["state"] == "pending" and not _expired(item)]
    expired = [item for item in store["sessions"] if item["state"] == "pending" and _expired(item)]
    return {
        "schemaVersion": 2,
        "state": "ready" if snapshots or not (store["records"] or store["sessions"]) else "scope-unavailable",
        "recordCount": len(store["records"]), "currentRecordCount": len(current_records),
        "reusableSuccessCount": sum(item["outcome"] == "succeeded" for item in current_records),
        "blockedFailureCount": sum(item["outcome"] == "failed" for item in current_records),
        "levels": {level: sum(item["level"] == level for item in current_records) for level in ("T0", "T1", "T2")},
        "scopes": {scope: sum(item["scope"] == scope for item in current_records) for scope in ("code", "docs", "project")},
        "pendingSessionCount": len(pending), "expiredSessionCount": len(expired),
        "pendingSession": pending[0] if pending else None,
        "estimatedAvoidedDurationMs": sum(item["durationMs"] or 0 for item in current_records if item["outcome"] == "succeeded"),
        "sourceTrust": "host-asserted", "rawCommandPersisted": False, "rawOutputPersisted": False,
        "trellisGateSatisfied": False,
    }


__all__ = ["inspect", "plan", "record", "record_session", "summary"]
