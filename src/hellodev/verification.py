"""Scoped, hash-only planning and sessions for host-executed verification."""

from __future__ import annotations

import hashlib
import json
import os
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
_WINDOWS_NPM_WRAPPER = re.compile(
    r"^(?:(?:cmd(?:\.exe)?\s+/c\s+))?npm(?:\.cmd)?(?P<arguments>\s+[^&|<>^\r\n]+)$",
    re.IGNORECASE,
)
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


def canonical_command(value: str) -> str:
    """Canonicalize only explicitly supported npm launcher aliases.

    This is deliberately not shell equivalence.  It covers the three forms
    observed on Windows hosts while refusing metacharacters and leaving every
    other command byte-for-byte significant after outer whitespace trimming.
    """

    selected = _command(value)
    matched = _WINDOWS_NPM_WRAPPER.fullmatch(selected)
    if matched is None:
        return selected
    arguments = re.sub(r"\s+", " ", matched.group("arguments").strip())
    return f"npm {arguments}"


def executable_command(value: str) -> str:
    """Render the canonical npm command for the current host shell."""

    selected = canonical_command(value)
    if os.name == "nt" and selected.startswith("npm "):
        return f"npm.cmd {selected[4:]}"
    return selected


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
    return {"commandSha256": _digest(canonical_command(command)), **scoped, "workItemId": _work_item_id(root)}


def _latest_exact(records: list[dict[str, Any]], identity: dict[str, Any], level: VerificationLevel) -> dict[str, Any] | None:
    fields = ("commandSha256", "scope", "scopeSnapshot", "workItemId")
    return next((item for item in reversed(records) if item["level"] == level and all(item[field] == identity[field] for field in fields)), None)


def _latest_covering_success(
    records: list[dict[str, Any]], identity: dict[str, Any], level: VerificationLevel
) -> dict[str, Any] | None:
    """Find same-command evidence that is strictly at least as strong.

    A project-scoped receipt can cover code or docs only when its complete
    repository snapshot is still current.  This avoids treating unrelated
    scope hashes as interchangeable while allowing the conservative closure
    plan disclosed at begin to satisfy a later, narrower requirement.
    """

    level_rank = {"T0": 0, "T1": 1, "T2": 2}
    required_scope = identity["scope"]
    for item in reversed(records):
        if (
            item["outcome"] != "succeeded"
            or item["workItemId"] != identity["workItemId"]
            or item["commandSha256"] != identity["commandSha256"]
            or level_rank[item["level"]] < level_rank[level]
        ):
            continue
        if item["scope"] == required_scope and item["scopeSnapshot"] == identity["scopeSnapshot"]:
            return item
        if (
            item["scope"] == "project"
            and required_scope in {"code", "docs"}
            and item["repositorySnapshot"] == identity["repositorySnapshot"]
        ):
            return item
    return None


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
    covering = _latest_covering_success(store["records"], identity, selected_level)
    if covering is not None:
        return {
            **base,
            "state": "covered-success",
            "runRequired": False,
            "reasonCode": "same-command-current-snapshot-covered-by-stronger-evidence",
            "reusedRecordId": covering["id"],
            "evidenceLevel": covering["level"],
            "evidenceScope": covering["scope"],
            "estimatedAvoidedDurationMs": covering["durationMs"],
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


def coverage(root: Path, level: str, scope: str | None = None) -> dict[str, Any]:
    """Inspect same-snapshot host evidence at an equal or stronger declared level."""
    selected_level = _level(level)
    selected_scope = _scope(scope, selected_level)
    scoped = changesets.scope_identity(root, selected_scope)
    work_item_id = _work_item_id(root)
    store = _load(root)
    rank = {"T0": 0, "T1": 1, "T2": 2}
    matched = next(
        (
            item for item in reversed(store["records"])
            if item["workItemId"] == work_item_id
            and item["scope"] == selected_scope
            and item["scopeSnapshot"] == scoped["scopeSnapshot"]
            and item["outcome"] == "succeeded"
            and rank[item["level"]] >= rank[selected_level]
        ),
        None,
    )
    return {
        "schemaVersion": 1,
        "state": "covered-success" if matched is not None else "missing",
        "covered": matched is not None,
        "requiredLevel": selected_level,
        "scope": selected_scope,
        "scopeSnapshot": scoped["scopeSnapshot"],
        "workItemId": work_item_id,
        "reusedRecordId": None if matched is None else matched["id"],
        "evidenceLevel": None if matched is None else matched["level"],
        "sourceTrust": "host-asserted",
        "commandEquivalenceClaimed": False,
        "readOnly": True,
        "executionPerformed": False,
        "persistencePerformed": False,
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


def _record_identity(
    root: Path,
    identity: dict[str, Any],
    level: VerificationLevel,
    outcome: str,
    duration_ms: int | None,
) -> dict[str, Any]:
    with locked_state(root, "verification"):
        store = _load(root)
        exact = _latest_exact(store["records"], identity, level)
        if exact is not None:
            if exact["outcome"] == "succeeded" and outcome == "succeeded":
                return {"schemaVersion": 2, "state": "already-recorded", "record": exact,
                        "persistencePerformed": False, "testExecutionPerformed": False,
                        "trellisGateSatisfied": False}
            if exact["outcome"] == "failed":
                raise ProjectError("unchanged failed verification cannot be recorded again; change inputs before retrying")
            raise ProjectError("refusing contradictory verification outcome for an unchanged successful check")
        pending = next(
            (
                session for session in reversed(store["sessions"])
                if session["state"] == "pending"
                and session["level"] == level
                and all(session[field] == identity[field] for field in ("commandSha256", "scope", "scopeSnapshot", "workItemId"))
            ),
            None,
        )
        item = _append_record(
            store, identity, level, outcome, duration_ms,
            pending["id"] if pending is not None else None,
        )
        store["records"].append(item)
        if pending is not None:
            pending.update({"state": "consumed", "consumedAt": utc_now(), "outcome": outcome})
        _write(root, store)
    return {"schemaVersion": 2, "state": "recorded", "record": item, "persistencePerformed": True,
            "testExecutionPerformed": False, "trellisGateSatisfied": False}


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
    return _record_identity(root, identity, selected_level, outcome, duration_ms)


def record_current(root: Path, level: str, command: str, outcome: str,
                   duration_ms: int | None = None, scope: str | None = None) -> dict[str, Any]:
    """Record an explicit host assertion against the repository state observed now."""
    selected_level = _level(level)
    selected_command = _command(command)
    selected_scope = _scope(scope, selected_level)
    if outcome not in OUTCOMES:
        raise ProjectError("verification outcome must be succeeded or failed")
    _validate_duration(duration_ms)
    identity = _identity(root, selected_command, selected_scope)
    result = _record_identity(root, identity, selected_level, outcome, duration_ms)
    return {
        **result,
        "recordMode": "atomic-current-snapshot",
        "currentSnapshotAttested": True,
        "sourceTrust": "host-asserted",
    }


def record_current_batch(root: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Record 1..16 bounded host assertions in one application call."""

    if not isinstance(results, list) or not 1 <= len(results) <= 16:
        raise ProjectError("verification results batch must contain between 1 and 16 items")
    prepared: list[tuple[VerificationLevel, dict[str, Any], str, int | None]] = []
    for index, item in enumerate(results):
        if not isinstance(item, dict) or not set(item).issubset({"level", "command", "scope", "outcome", "durationMs"}):
            raise ProjectError(f"invalid verification results batch item {index}")
        if set(item) - {"durationMs"} != {"level", "command", "scope", "outcome"}:
            raise ProjectError(f"verification results batch item {index} requires level, command, scope, and outcome")
        level = _level(item["level"])
        command = _command(item["command"])
        scope = _scope(item["scope"], level)
        outcome = item["outcome"]
        if outcome not in OUTCOMES:
            raise ProjectError(f"invalid verification results batch outcome at item {index}")
        duration = item.get("durationMs")
        _validate_duration(duration)
        prepared.append((level, _identity(root, command, scope), outcome, duration))
    identities = [(level, identity["commandSha256"], identity["scope"], identity["scopeSnapshot"]) for level, identity, _, _ in prepared]
    if len(identities) != len(set(identities)):
        raise ProjectError("verification results batch contains duplicate command identities")

    recorded = []
    persistence_performed = False
    with locked_state(root, "verification"):
        store = _load(root)
        # Validate the entire batch before changing the in-memory store.
        for level, identity, outcome, _ in prepared:
            exact = _latest_exact(store["records"], identity, level)
            if exact is not None and not (exact["outcome"] == "succeeded" and outcome == "succeeded"):
                if exact["outcome"] == "failed":
                    raise ProjectError("unchanged failed verification cannot be recorded again; change inputs before retrying")
                raise ProjectError("refusing contradictory verification outcome for an unchanged successful check")
        for level, identity, outcome, duration in prepared:
            exact = _latest_exact(store["records"], identity, level)
            if exact is not None:
                recorded.append({
                    "schemaVersion": 2,
                    "state": "already-recorded",
                    "record": exact,
                    "persistencePerformed": False,
                    "testExecutionPerformed": False,
                    "trellisGateSatisfied": False,
                })
                continue
            pending = next(
                (
                    session for session in reversed(store["sessions"])
                    if session["state"] == "pending"
                    and session["level"] == level
                    and all(session[field] == identity[field] for field in ("commandSha256", "scope", "scopeSnapshot", "workItemId"))
                ),
                None,
            )
            item = _append_record(store, identity, level, outcome, duration, pending["id"] if pending else None)
            store["records"].append(item)
            if pending is not None:
                pending.update({"state": "consumed", "consumedAt": utc_now(), "outcome": outcome})
            persistence_performed = True
            recorded.append({
                "schemaVersion": 2,
                "state": "recorded",
                "record": item,
                "persistencePerformed": True,
                "testExecutionPerformed": False,
                "trellisGateSatisfied": False,
            })
        if persistence_performed:
            _write(root, store)
    return {
        "schemaVersion": 1,
        "state": "recorded",
        "recordMode": "bounded-batch-current-snapshot",
        "resultCount": len(recorded),
        "results": recorded,
        "persistencePerformed": persistence_performed,
        "sourceTrust": "host-asserted",
        "currentSnapshotAttested": True,
        "testExecutionPerformed": False,
        "rawOutputPersisted": False,
    }


def host_action(root: Path, level: str, command: str, scope: str | None = None) -> dict[str, Any]:
    """Return one compact host command plus exact atomic receipt continuations."""
    selected_level = _level(level)
    selected_command = _command(command)
    host_command = executable_command(selected_command)
    selected_scope = _scope(scope, selected_level)
    base = [
        "do", "verify", "--level", selected_level, "--command", selected_command,
        "--scope", selected_scope, "--current-snapshot",
    ]
    return {
        "schemaVersion": 1,
        "kind": "host-verification",
        "hostCommand": host_command,
        "recordSuccessCommand": command_line(root, *base, "--outcome", "succeeded", "--duration-ms", "<milliseconds>"),
        "recordFailureCommand": command_line(root, *base, "--outcome", "failed", "--duration-ms", "<milliseconds>"),
        "sourceTrust": "host-asserted",
        "currentSnapshotRequired": True,
        "testExecutionPerformed": False,
        "helpOrStatusProbeRequired": False,
        "canonicalCommand": canonical_command(selected_command),
        "launcherAliasPolicy": "bounded-npm-windows",
    }


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
    work_item_records = [item for item in store["records"] if item["workItemId"] == work_item_id]
    successful = [item for item in work_item_records if item["outcome"] == "succeeded"]
    distinct_commands = {item["commandSha256"] for item in successful}
    distinct_snapshots = {item["scopeSnapshot"] for item in successful}
    return {
        "schemaVersion": 2,
        "state": "ready" if snapshots or not (store["records"] or store["sessions"]) else "scope-unavailable",
        "recordCount": len(store["records"]), "currentRecordCount": len(current_records),
        "workItemRecordCount": len(work_item_records),
        "reusableSuccessCount": sum(item["outcome"] == "succeeded" for item in current_records),
        "blockedFailureCount": sum(item["outcome"] == "failed" for item in current_records),
        "distinctCommandCount": len(distinct_commands),
        "distinctSnapshotCount": len(distinct_snapshots),
        "repeatedCommandCount": max(0, len(successful) - len(distinct_commands)),
        "levels": {level: sum(item["level"] == level for item in current_records) for level in ("T0", "T1", "T2")},
        "scopes": {scope: sum(item["scope"] == scope for item in current_records) for scope in ("code", "docs", "project")},
        "pendingSessionCount": len(pending), "expiredSessionCount": len(expired),
        "pendingSession": pending[0] if pending else None,
        "estimatedAvoidedDurationMs": sum(item["durationMs"] or 0 for item in current_records if item["outcome"] == "succeeded"),
        "sourceTrust": "host-asserted", "rawCommandPersisted": False, "rawOutputPersisted": False,
        "trellisGateSatisfied": False,
    }


__all__ = [
    "canonical_command", "coverage", "executable_command", "host_action", "inspect", "plan",
    "record", "record_current", "record_current_batch", "record_session", "summary",
]
