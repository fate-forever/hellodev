"""Pointer-only F2 continuity contracts.

The stores in this module deliberately contain references and digests, never
task bodies, lesson text, verification text, or adapter output.  Trellis and
Nocturne remain the owners of their native data.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import capabilities, lifecycle, receipts, sagas
from .project import (
    ProjectError,
    ProjectPaths,
    load_config,
    resolve_root,
    show_task,
    utc_now,
    write_json,
)
from .state_lock import locked_state


STORE_SCHEMA_VERSION = 1
LESSON_STORE_SCHEMA_VERSION = 2
LESSON_PENDING_TTL_HOURS = 72
WORK_ITEM_ID_PATTERN = re.compile(r"^work-[0-9]{4,}$")
LESSON_PROPOSAL_ID_PATTERN = re.compile(r"^lesson-[0-9]{4,}$")
EVIDENCE_LINK_ID_PATTERN = re.compile(r"^evidence-[0-9]{4,}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_NATIVE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")

WORK_ITEM_BACKENDS = {"local", "trellis"}
LESSON_SCOPES = {"project", "cross-project"}
LESSON_DESTINATIONS = {"trellis", "nocturne"}
LESSON_STATES = {
    "proposed",
    "project-plan",
    "evidence-required",
    "evidence-invalid",
    "configuration-required",
    "ready",
    "saga-plan-ready",
    "saga-active",
    "verification-required",
    "completed",
    "partial",
}
LESSON_TRANSITIONS = {
    "proposed": LESSON_STATES,
    "project-plan": {"project-plan", "completed"},
    "evidence-required": {"evidence-required", "evidence-invalid", "configuration-required", "saga-plan-ready"},
    "evidence-invalid": {"evidence-invalid", "evidence-required", "configuration-required", "saga-plan-ready"},
    "configuration-required": {"configuration-required", "saga-plan-ready"},
    "ready": {"ready", "saga-plan-ready"},
    "saga-plan-ready": {"saga-plan-ready", "saga-active"},
    "saga-active": {"saga-active", "verification-required", "completed", "partial"},
    "verification-required": {"verification-required", "completed", "partial"},
    "completed": {"completed"},
    "partial": {"partial"},
}
LESSON_REVIEW_STATES = {"pending", "verified", "rejected", "expired", "superseded", "persisted"}
LESSON_REVIEW_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
LESSON_REVIEW_TRANSITIONS = {
    "pending": {"pending", "verified", "rejected", "expired", "superseded"},
    "verified": {"verified", "rejected", "superseded", "persisted"},
    "rejected": {"rejected", "pending"},
    "expired": {"expired", "pending"},
    "superseded": {"superseded"},
    "persisted": {"persisted", "superseded"},
}

WORK_ITEM_FIELDS = {
    "id",
    "backend",
    "nativeRef",
    "linkedPhase",
    "sourceFingerprint",
    "createdAt",
    "updatedAt",
}
LESSON_PROPOSAL_FIELDS_V1 = {
    "id",
    "lessonSha256",
    "scope",
    "destination",
    "evidenceReceiptId",
    "sagaId",
    "state",
    "createdAt",
    "updatedAt",
}
LESSON_PROPOSAL_FIELDS = LESSON_PROPOSAL_FIELDS_V1 | {
    "evidenceReceiptIds",
    "reviewState",
    "reviewReasonCode",
    "reviewedAt",
    "expiresAt",
    "supersededBy",
}
EVIDENCE_LINK_FIELDS = {
    "id",
    "workItemId",
    "receiptId",
    "evidenceKind",
    "sourceFingerprint",
    "createdAt",
}


def _paths(root: str | Path) -> tuple[Path, ProjectPaths]:
    resolved = resolve_root(root)
    load_config(resolved)
    paths = ProjectPaths(resolved)
    if paths.state_dir.is_symlink():
        raise ProjectError("refusing symlinked .hellodev directory")
    return resolved, paths


def _store_path(root: str | Path, name: str) -> tuple[Path, Path]:
    resolved, paths = _paths(root)
    path = paths.state_dir / name
    if path.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev {name} store")
    if path.exists() and not path.is_file():
        raise ProjectError(f"HelloDev {name} store is not a regular file")
    return resolved, path


def _read_store(root: str | Path, name: str, default: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    resolved, path = _store_path(root, name)
    if not path.exists():
        # Missing F2 stores are the normal, non-destructive 0.8 migration path.
        return resolved, path, default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev {name} store: {error}") from error
    if not isinstance(value, dict):
        raise ProjectError(f"invalid HelloDev {name} store schema")
    return resolved, path, value


def _write_store(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev {path.name} store")
    write_json(path, value)


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProjectError(f"{field} must be a UTC timestamp") from error
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ProjectError(f"{field} must be a UTC timestamp")


def _timestamp_after(value: str, *, hours: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(hours=hours)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"{field} must be a lowercase SHA-256 digest")


def _validate_id(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ProjectError(f"invalid {field}")
    return value


def _validate_unique_ids(records: list[dict[str, Any]], field: str) -> None:
    identifiers = [record["id"] for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ProjectError(f"duplicate {field} id")


def _next_id(records: list[dict[str, Any]], prefix: str) -> str:
    highest = max((int(record["id"].removeprefix(prefix)) for record in records), default=0)
    return f"{prefix}{highest + 1:04d}"


def _validate_native_ref(root: Path, backend: str, native_ref: Any) -> str:
    if (
        not isinstance(native_ref, str)
        or SAFE_NATIVE_REF_PATTERN.fullmatch(native_ref) is None
        or native_ref in {".", ".."}
    ):
        raise ProjectError("nativeRef must be one safe local task or Trellis task name")
    if backend == "local":
        show_task(root, native_ref)
        return native_ref

    trellis = root / ".trellis"
    tasks = trellis / "tasks"
    if trellis.is_symlink() or tasks.is_symlink():
        raise ProjectError("refusing symlinked Trellis task store")
    if not trellis.is_dir() or not tasks.is_dir():
        raise ProjectError("Trellis tasks are unavailable for this project")
    task = tasks / native_ref
    if task.is_symlink() or not task.is_dir():
        raise ProjectError(f"Trellis task not found or unsafe: {native_ref}")
    try:
        task.resolve().relative_to(tasks.resolve())
    except ValueError as error:
        raise ProjectError("Trellis task escapes the project task store") from error
    return native_ref


def list_trellis_tasks(root: str | Path) -> list[str]:
    """List safe active native task directory names; archive is not active."""
    resolved, _ = _paths(root)
    tasks = resolved / ".trellis" / "tasks"
    if not tasks.exists():
        return []
    if tasks.is_symlink() or not tasks.is_dir():
        raise ProjectError("refusing unsafe Trellis task store")
    values: list[str] = []
    for item in sorted(tasks.iterdir(), key=lambda entry: entry.name.casefold()):
        if item.name == "archive":
            continue
        if item.is_symlink() or not item.is_dir() or SAFE_NATIVE_REF_PATTERN.fullmatch(item.name) is None:
            continue
        try:
            item.resolve().relative_to(tasks.resolve())
        except ValueError as error:
            raise ProjectError("Trellis task escapes the project task store") from error
        values.append(item.name)
    return values


def validate_work_item_reference(root: str | Path, work_item: dict[str, Any] | str) -> dict[str, Any]:
    resolved, _ = _paths(root)
    record = get_work_item(resolved, work_item) if isinstance(work_item, str) else work_item
    _validate_work_item(record)
    _validate_native_ref(resolved, record["backend"], record["nativeRef"])
    return record


def _validate_work_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != WORK_ITEM_FIELDS:
        raise ProjectError("invalid WorkItem fields")
    _validate_id(value.get("id"), WORK_ITEM_ID_PATTERN, "WorkItem id")
    if value.get("backend") not in WORK_ITEM_BACKENDS:
        raise ProjectError("WorkItem backend must be local or trellis")
    native_ref = value.get("nativeRef")
    if not isinstance(native_ref, str) or SAFE_NATIVE_REF_PATTERN.fullmatch(native_ref) is None:
        raise ProjectError("invalid WorkItem nativeRef")
    if value.get("linkedPhase") not in lifecycle.PHASES:
        raise ProjectError("invalid WorkItem linkedPhase")
    _validate_digest(value.get("sourceFingerprint"), "WorkItem sourceFingerprint")
    _validate_timestamp(value.get("createdAt"), "WorkItem createdAt")
    _validate_timestamp(value.get("updatedAt"), "WorkItem updatedAt")
    if value["updatedAt"] < value["createdAt"]:
        raise ProjectError("WorkItem updatedAt precedes createdAt")
    return value


def _load_work_items(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved, path, store = _read_store(
        root,
        "work-items.json",
        {"schemaVersion": STORE_SCHEMA_VERSION, "currentWorkItemId": None, "workItems": []},
    )
    if set(store) != {"schemaVersion", "currentWorkItemId", "workItems"}:
        raise ProjectError("invalid WorkItem store fields")
    if type(store.get("schemaVersion")) is not int or store["schemaVersion"] != STORE_SCHEMA_VERSION:
        raise ProjectError("unsupported WorkItem store schema")
    raw = store.get("workItems")
    if not isinstance(raw, list):
        raise ProjectError("invalid WorkItem store entries")
    records = [_validate_work_item(item) for item in raw]
    _validate_unique_ids(records, "WorkItem")
    current = store.get("currentWorkItemId")
    if current is not None:
        _validate_id(current, WORK_ITEM_ID_PATTERN, "current WorkItem id")
        if current not in {record["id"] for record in records}:
            raise ProjectError("current WorkItem pointer does not exist")
    return resolved, path, store


def list_work_items(root: str | Path) -> list[dict[str, Any]]:
    return list(_load_work_items(root)[2]["workItems"])


def get_work_item(root: str | Path, work_item_id: str) -> dict[str, Any]:
    _validate_id(work_item_id, WORK_ITEM_ID_PATTERN, "WorkItem id")
    for record in list_work_items(root):
        if record["id"] == work_item_id:
            return record
    raise ProjectError(f"WorkItem not found: {work_item_id}")


def current_work_item(root: str | Path) -> dict[str, Any] | None:
    _, _, store = _load_work_items(root)
    current = store["currentWorkItemId"]
    return None if current is None else next(item for item in store["workItems"] if item["id"] == current)


def set_current_work_item(root: str | Path, work_item_id: str | None) -> dict[str, Any] | None:
    with locked_state(root, "work-items"):
        _, path, store = _load_work_items(root)
        if work_item_id is not None:
            record = next((item for item in store["workItems"] if item["id"] == work_item_id), None)
            if record is None:
                raise ProjectError(f"WorkItem not found: {work_item_id}")
            validate_work_item_reference(root, record)
        else:
            record = None
        store["currentWorkItemId"] = work_item_id
        _write_store(path, store)
        return record


def create_work_item(
    root: str | Path,
    backend: str,
    native_ref: str,
    *,
    make_current: bool = True,
) -> dict[str, Any]:
    with locked_state(root, "work-items"):
        resolved, path, store = _load_work_items(root)
        if backend not in WORK_ITEM_BACKENDS:
            raise ProjectError("WorkItem backend must be local or trellis")
        _validate_native_ref(resolved, backend, native_ref)
        existing = next(
            (item for item in store["workItems"] if item["backend"] == backend and item["nativeRef"] == native_ref),
            None,
        )
        if existing is not None:
            if make_current and store["currentWorkItemId"] != existing["id"]:
                store["currentWorkItemId"] = existing["id"]
                _write_store(path, store)
            return existing
        now = utc_now()
        record = {
            "id": _next_id(store["workItems"], "work-"),
            "backend": backend,
            "nativeRef": native_ref,
            "linkedPhase": lifecycle.status(resolved)["phase"],
            "sourceFingerprint": capabilities.fingerprint(resolved),
            "createdAt": now,
            "updatedAt": now,
        }
        _validate_work_item(record)
        store["workItems"].append(record)
        if make_current:
            store["currentWorkItemId"] = record["id"]
        _write_store(path, store)
        return record


def activate_trellis_task(root: str | Path, native_ref: str) -> dict[str, Any]:
    """Explicitly select one existing Trellis task and start a new local cycle.

    This is intentionally not automatic: a repository may have several active
    Trellis tasks, and selecting one changes HelloDev's current pointer.
    """
    with locked_state(root, "workflow-activation"):
        resolved, _ = _paths(root)
        if lifecycle.status(resolved)["phase"] != "finished":
            phase = lifecycle.status(resolved)["phase"]
            raise ProjectError(f"cannot activate a new Trellis task while lifecycle is {phase}; finish or resume it first")
        work_item = create_work_item(resolved, "trellis", native_ref, make_current=True)
        state = lifecycle.begin_cycle(resolved, work_item["id"])
        work_item = refresh_work_item(resolved, work_item["id"])
        return {"workItem": work_item, "lifecycle": state, "activated": True, "executionPerformed": True}


def refresh_work_item(root: str | Path, work_item_id: str | None = None) -> dict[str, Any]:
    with locked_state(root, "work-items"):
        resolved, path, store = _load_work_items(root)
        selected = work_item_id or store["currentWorkItemId"]
        if selected is None:
            raise ProjectError("no current WorkItem")
        _validate_id(selected, WORK_ITEM_ID_PATTERN, "WorkItem id")
        record = next((item for item in store["workItems"] if item["id"] == selected), None)
        if record is None:
            raise ProjectError(f"WorkItem not found: {selected}")
        _validate_native_ref(resolved, record["backend"], record["nativeRef"])
        record["linkedPhase"] = lifecycle.status(resolved)["phase"]
        record["sourceFingerprint"] = capabilities.fingerprint(resolved)
        record["updatedAt"] = utc_now()
        _validate_work_item(record)
        _write_store(path, store)
        return record


def update_work_item(root: str | Path, work_item_id: str | None = None) -> dict[str, Any]:
    """Refresh a WorkItem's lifecycle/fingerprint projection.

    Native references are immutable pointers.  Changing the native task means
    creating/selecting a different WorkItem, so the only supported update is
    an intentional projection refresh.
    """
    return refresh_work_item(root, work_item_id)


def _validate_lesson_proposal_v1(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != LESSON_PROPOSAL_FIELDS_V1:
        raise ProjectError("invalid legacy LessonProposal fields")
    _validate_id(value.get("id"), LESSON_PROPOSAL_ID_PATTERN, "LessonProposal id")
    _validate_digest(value.get("lessonSha256"), "LessonProposal lessonSha256")
    scope = value.get("scope")
    destination = value.get("destination")
    if scope not in LESSON_SCOPES:
        raise ProjectError("LessonProposal scope must be project or cross-project")
    if destination not in LESSON_DESTINATIONS:
        raise ProjectError("LessonProposal destination must be trellis or nocturne")
    if (scope, destination) not in {("project", "trellis"), ("cross-project", "nocturne")}:
        raise ProjectError("LessonProposal scope and destination are incompatible")
    evidence_id = value.get("evidenceReceiptId")
    if evidence_id is not None:
        _validate_id(evidence_id, receipts.RECEIPT_ID_PATTERN, "LessonProposal evidence receipt id")
    saga_id = value.get("sagaId")
    if saga_id is not None:
        _validate_id(saga_id, sagas.SAGA_ID_PATTERN, "LessonProposal saga id")
    if value.get("state") not in LESSON_STATES:
        raise ProjectError("invalid LessonProposal state")
    _validate_timestamp(value.get("createdAt"), "LessonProposal createdAt")
    _validate_timestamp(value.get("updatedAt"), "LessonProposal updatedAt")
    if value["updatedAt"] < value["createdAt"]:
        raise ProjectError("LessonProposal updatedAt precedes createdAt")
    return value


def _migrate_lesson_proposal(value: dict[str, Any]) -> dict[str, Any]:
    legacy = _validate_lesson_proposal_v1(value)
    if legacy["state"] == "completed":
        review_state, reason, reviewed_at = "persisted", "legacy-completed", legacy["updatedAt"]
    elif legacy["state"] == "partial":
        review_state, reason, reviewed_at = "rejected", "legacy-partial", legacy["updatedAt"]
    else:
        review_state, reason, reviewed_at = "pending", None, None
    evidence_ids = [] if legacy["evidenceReceiptId"] is None else [legacy["evidenceReceiptId"]]
    return {
        **legacy,
        "evidenceReceiptIds": evidence_ids,
        "reviewState": review_state,
        "reviewReasonCode": reason,
        "reviewedAt": reviewed_at,
        "expiresAt": _timestamp_after(legacy["createdAt"], hours=LESSON_PENDING_TTL_HOURS),
        "supersededBy": None,
    }


def _validate_lesson_proposal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != LESSON_PROPOSAL_FIELDS:
        raise ProjectError("invalid LessonProposal fields")
    legacy = {field: value[field] for field in LESSON_PROPOSAL_FIELDS_V1}
    _validate_lesson_proposal_v1(legacy)
    evidence_ids = value.get("evidenceReceiptIds")
    if not isinstance(evidence_ids, list) or len(evidence_ids) > 16 or len(evidence_ids) != len(set(evidence_ids)):
        raise ProjectError("LessonProposal evidenceReceiptIds must be a unique bounded list")
    for receipt_id in evidence_ids:
        _validate_id(receipt_id, receipts.RECEIPT_ID_PATTERN, "LessonProposal evidence receipt id")
    if value["evidenceReceiptId"] is not None and value["evidenceReceiptId"] not in evidence_ids:
        raise ProjectError("LessonProposal primary evidence must appear in evidenceReceiptIds")
    review_state = value.get("reviewState")
    if review_state not in LESSON_REVIEW_STATES:
        raise ProjectError("invalid LessonProposal review state")
    reason = value.get("reviewReasonCode")
    if reason is not None and (not isinstance(reason, str) or LESSON_REVIEW_REASON_PATTERN.fullmatch(reason) is None):
        raise ProjectError("LessonProposal reviewReasonCode must be one bounded reason code")
    reviewed_at = value.get("reviewedAt")
    if reviewed_at is not None:
        _validate_timestamp(reviewed_at, "LessonProposal reviewedAt")
        if reviewed_at < value["createdAt"]:
            raise ProjectError("LessonProposal reviewedAt precedes createdAt")
    if review_state == "pending" and reviewed_at is not None:
        raise ProjectError("pending LessonProposal cannot have reviewedAt")
    if review_state != "pending" and reviewed_at is None:
        raise ProjectError("reviewed LessonProposal requires reviewedAt")
    _validate_timestamp(value.get("expiresAt"), "LessonProposal expiresAt")
    if value["expiresAt"] <= value["createdAt"]:
        raise ProjectError("LessonProposal expiresAt must follow createdAt")
    replacement = value.get("supersededBy")
    if replacement is not None:
        _validate_id(replacement, LESSON_PROPOSAL_ID_PATTERN, "superseding LessonProposal id")
        if replacement == value["id"]:
            raise ProjectError("LessonProposal cannot supersede itself")
    if review_state == "superseded" and replacement is None:
        raise ProjectError("superseded LessonProposal requires a replacement")
    if review_state != "superseded" and replacement is not None:
        raise ProjectError("only a superseded LessonProposal may name a replacement")
    return value


def _load_lesson_proposals(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved, path, store = _read_store(
        root,
        "lesson-proposals.json",
        {"schemaVersion": LESSON_STORE_SCHEMA_VERSION, "lessonProposals": []},
    )
    if set(store) != {"schemaVersion", "lessonProposals"}:
        raise ProjectError("invalid LessonProposal store fields")
    version = store.get("schemaVersion")
    if type(version) is not int or version not in {1, LESSON_STORE_SCHEMA_VERSION}:
        raise ProjectError("unsupported LessonProposal store schema")
    raw = store.get("lessonProposals")
    if not isinstance(raw, list):
        raise ProjectError("invalid LessonProposal store entries")
    records = (
        [_migrate_lesson_proposal(item) for item in raw]
        if version == 1
        else [_validate_lesson_proposal(item) for item in raw]
    )
    _validate_unique_ids(records, "LessonProposal")
    saga_ids = [record["sagaId"] for record in records if record["sagaId"] is not None]
    if len(saga_ids) != len(set(saga_ids)):
        raise ProjectError("a Saga cannot belong to multiple LessonProposals")
    return resolved, path, {"schemaVersion": LESSON_STORE_SCHEMA_VERSION, "lessonProposals": records}


def _lesson_digest(lesson: str) -> str:
    if not isinstance(lesson, str):
        raise ProjectError("lesson must be text")
    normalized = lesson.strip()
    if not normalized or len(normalized) > 1_000:
        raise ProjectError("lesson must be non-empty and 1000 characters or fewer")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _verified_trellis_evidence(root: Path, receipt_id: str) -> dict[str, Any]:
    evidence = receipts.get(root, receipt_id)
    if (
        evidence["adapter"] != "trellis"
        or evidence["kind"] not in {"gate", "test"}
        or evidence["outcome"] != "succeeded"
    ):
        raise ProjectError("LessonProposal evidence must be a successful Trellis gate or test receipt")
    verification = next(
        (
            item
            for item in receipts.list_receipts(root)
            if item["kind"] == "verification"
            and item["outcome"] == "succeeded"
            and item["subjectReceiptId"] == receipt_id
        ),
        None,
    )
    if verification is None:
        raise ProjectError("LessonProposal evidence requires a matching verification receipt")
    return evidence


def list_lesson_proposals(root: str | Path) -> list[dict[str, Any]]:
    return list(_load_lesson_proposals(root)[2]["lessonProposals"])


def get_lesson_proposal(root: str | Path, proposal_id: str) -> dict[str, Any]:
    _validate_id(proposal_id, LESSON_PROPOSAL_ID_PATTERN, "LessonProposal id")
    for record in list_lesson_proposals(root):
        if record["id"] == proposal_id:
            return record
    raise ProjectError(f"LessonProposal not found: {proposal_id}")


def proposal_for_saga(root: str | Path, saga_id: str) -> dict[str, Any] | None:
    _validate_id(saga_id, sagas.SAGA_ID_PATTERN, "Saga id")
    return next((item for item in list_lesson_proposals(root) if item["sagaId"] == saga_id), None)


def create_lesson_proposal(
    root: str | Path,
    lesson: str,
    scope: str,
    destination: str,
    *,
    evidence_receipt_id: str | None = None,
    saga_id: str | None = None,
    state: str = "proposed",
) -> dict[str, Any]:
    with locked_state(root, "lesson-proposals"):
        resolved, path, store = _load_lesson_proposals(root)
        digest = _lesson_digest(lesson)
        if evidence_receipt_id is not None:
            _verified_trellis_evidence(resolved, evidence_receipt_id)
        existing = next(
            (
                item
                for item in store["lessonProposals"]
                if item["lessonSha256"] == digest
                and item["scope"] == scope
                and item["destination"] == destination
            ),
            None,
        )
        if existing is not None:
            if any(
                supplied is not None and existing[field] != supplied
                for field, supplied in (("evidenceReceiptId", evidence_receipt_id), ("sagaId", saga_id))
            ):
                raise ProjectError("matching LessonProposal already exists with different continuity links")
            return existing
        if saga_id is not None:
            sagas.status(resolved, saga_id)
            if proposal_for_saga(resolved, saga_id) is not None:
                raise ProjectError(f"Saga already has a LessonProposal: {saga_id}")
        now = utc_now()
        review_state = "persisted" if state == "completed" else "rejected" if state == "partial" else "pending"
        record = {
            "id": _next_id(store["lessonProposals"], "lesson-"),
            "lessonSha256": digest,
            "scope": scope,
            "destination": destination,
            "evidenceReceiptId": evidence_receipt_id,
            "evidenceReceiptIds": [] if evidence_receipt_id is None else [evidence_receipt_id],
            "sagaId": saga_id,
            "state": state,
            "reviewState": review_state,
            "reviewReasonCode": "operation-completed" if state == "completed" else "operation-partial" if state == "partial" else None,
            "reviewedAt": now if review_state != "pending" else None,
            "expiresAt": _timestamp_after(now, hours=LESSON_PENDING_TTL_HOURS),
            "supersededBy": None,
            "createdAt": now,
            "updatedAt": now,
        }
        _validate_lesson_proposal(record)
        store["lessonProposals"].append(record)
        _write_store(path, store)
        return record


def update_lesson_proposal(
    root: str | Path,
    proposal_id: str,
    *,
    evidence_receipt_id: str | None = None,
    saga_id: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    with locked_state(root, "lesson-proposals"):
        resolved, path, store = _load_lesson_proposals(root)
        _validate_id(proposal_id, LESSON_PROPOSAL_ID_PATTERN, "LessonProposal id")
        record = next((item for item in store["lessonProposals"] if item["id"] == proposal_id), None)
        if record is None:
            raise ProjectError(f"LessonProposal not found: {proposal_id}")
        if evidence_receipt_id is not None:
            _verified_trellis_evidence(resolved, evidence_receipt_id)
            if evidence_receipt_id not in record["evidenceReceiptIds"]:
                if len(record["evidenceReceiptIds"]) >= 16:
                    raise ProjectError("LessonProposal evidence receipt limit reached")
                record["evidenceReceiptIds"].append(evidence_receipt_id)
            if record["evidenceReceiptId"] is None:
                record["evidenceReceiptId"] = evidence_receipt_id
        if saga_id is not None:
            sagas.status(resolved, saga_id)
            if record["sagaId"] not in {None, saga_id}:
                raise ProjectError("LessonProposal Saga link is immutable")
            other = next(
                (item for item in store["lessonProposals"] if item["sagaId"] == saga_id and item["id"] != proposal_id),
                None,
            )
            if other is not None:
                raise ProjectError(f"Saga already has a LessonProposal: {saga_id}")
            record["sagaId"] = saga_id
        if state is not None:
            allowed = LESSON_TRANSITIONS[record["state"]]
            if state not in allowed:
                raise ProjectError(f"LessonProposal cannot transition from {record['state']} to {state}")
            record["state"] = state
        now = utc_now()
        if state == "completed":
            record["reviewState"] = "persisted"
            record["reviewReasonCode"] = "operation-completed"
            record["reviewedAt"] = now
            record["supersededBy"] = None
        elif state == "partial" and record["reviewState"] not in {"persisted", "superseded"}:
            record["reviewState"] = "rejected"
            record["reviewReasonCode"] = "operation-partial"
            record["reviewedAt"] = now
            record["supersededBy"] = None
        record["updatedAt"] = now
        _validate_lesson_proposal(record)
        _write_store(path, store)
        return record


def lesson_review_projection(record: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    _validate_lesson_proposal(record)
    selected_now = now or utc_now()
    _validate_timestamp(selected_now, "LessonProposal projection time")
    expired = record["reviewState"] == "pending" and selected_now >= record["expiresAt"]
    effective = "expired" if expired else record["reviewState"]
    return {
        **record,
        "effectiveReviewState": effective,
        "expired": expired,
        "reviewRequired": record["reviewState"] == "pending",
        "reviewCommand": f"hellodev lesson show {record['id']}",
    }


def list_lesson_review_projections(root: str | Path) -> list[dict[str, Any]]:
    now = utc_now()
    return [lesson_review_projection(item, now=now) for item in list_lesson_proposals(root)]


def pending_lesson_review(root: str | Path) -> dict[str, Any] | None:
    candidates = [
        item
        for item in list_lesson_review_projections(root)
        if item["reviewRequired"]
    ]
    return min(candidates, key=lambda item: (item["createdAt"], item["id"]), default=None)


def review_lesson_proposal(
    root: str | Path,
    proposal_id: str,
    decision: str,
    *,
    evidence_receipt_id: str | None = None,
    reason_code: str | None = None,
    replacement_id: str | None = None,
) -> dict[str, Any]:
    if decision not in {"verify", "reject", "expire", "supersede", "reactivate"}:
        raise ProjectError("lesson review decision must be verify, reject, expire, supersede, or reactivate")
    if reason_code is not None and LESSON_REVIEW_REASON_PATTERN.fullmatch(reason_code) is None:
        raise ProjectError("lesson review reason code must be lowercase kebab-case")
    with locked_state(root, "lesson-proposals"):
        resolved, path, store = _load_lesson_proposals(root)
        _validate_id(proposal_id, LESSON_PROPOSAL_ID_PATTERN, "LessonProposal id")
        record = next((item for item in store["lessonProposals"] if item["id"] == proposal_id), None)
        if record is None:
            raise ProjectError(f"LessonProposal not found: {proposal_id}")
        now = utc_now()
        current = "expired" if record["reviewState"] == "pending" and now >= record["expiresAt"] else record["reviewState"]
        evidence_is_new = evidence_receipt_id is not None and evidence_receipt_id not in record["evidenceReceiptIds"]
        if evidence_receipt_id is not None:
            _verified_trellis_evidence(resolved, evidence_receipt_id)
            if evidence_receipt_id not in record["evidenceReceiptIds"]:
                if len(record["evidenceReceiptIds"]) >= 16:
                    raise ProjectError("LessonProposal evidence receipt limit reached")
                record["evidenceReceiptIds"].append(evidence_receipt_id)
            if record["evidenceReceiptId"] is None:
                record["evidenceReceiptId"] = evidence_receipt_id
        if decision == "reactivate":
            if current not in {"rejected", "expired"}:
                raise ProjectError(f"LessonProposal cannot reactivate from {current}")
            if evidence_receipt_id is None or not evidence_is_new:
                raise ProjectError("LessonProposal reactivation requires new verified evidence")
            target = "pending"
            record["expiresAt"] = _timestamp_after(now, hours=LESSON_PENDING_TTL_HOURS)
            record["reviewReasonCode"] = None
            record["reviewedAt"] = None
            record["supersededBy"] = None
        elif decision == "verify":
            if current == "expired":
                raise ProjectError("expired LessonProposal must be reactivated with new evidence before verification")
            target = "verified"
            if record["scope"] == "cross-project" and not record["evidenceReceiptIds"]:
                raise ProjectError("cross-project LessonProposal verification requires verified Trellis evidence")
            record["reviewReasonCode"] = reason_code or (
                "evidence-verified" if record["evidenceReceiptIds"] else "human-project-review"
            )
            record["reviewedAt"] = now
            record["supersededBy"] = None
        elif decision == "reject":
            if reason_code is None:
                raise ProjectError("LessonProposal rejection requires --reason-code")
            target = "rejected"
            record["reviewReasonCode"] = reason_code
            record["reviewedAt"] = now
            record["supersededBy"] = None
        elif decision == "expire":
            if current != "expired":
                raise ProjectError("LessonProposal is not past its pending TTL")
            target = "expired"
            record["reviewReasonCode"] = reason_code or "pending-ttl-expired"
            record["reviewedAt"] = now
            record["supersededBy"] = None
        else:
            if replacement_id is None:
                raise ProjectError("LessonProposal supersede requires --replacement")
            _validate_id(replacement_id, LESSON_PROPOSAL_ID_PATTERN, "replacement LessonProposal id")
            replacement = next((item for item in store["lessonProposals"] if item["id"] == replacement_id), None)
            if replacement is None:
                raise ProjectError(f"LessonProposal not found: {replacement_id}")
            if replacement["scope"] != record["scope"] or replacement["destination"] != record["destination"]:
                raise ProjectError("superseding LessonProposal must use the same scope and destination")
            if replacement["reviewState"] in {"rejected", "expired", "superseded"}:
                raise ProjectError("superseding LessonProposal is not actionable")
            target = "superseded"
            record["reviewReasonCode"] = reason_code or "newer-candidate"
            record["reviewedAt"] = now
            record["supersededBy"] = replacement_id
        allowed = LESSON_REVIEW_TRANSITIONS[current]
        if target not in allowed:
            raise ProjectError(f"LessonProposal review cannot transition from {current} to {target}")
        record["reviewState"] = target
        record["updatedAt"] = now
        _validate_lesson_proposal(record)
        _write_store(path, store)
        return lesson_review_projection(record, now=now)


def validate_lesson_digest(root: str | Path, proposal_id: str, lesson: str) -> bool:
    proposal = get_lesson_proposal(root, proposal_id)
    if proposal["lessonSha256"] != _lesson_digest(lesson):
        raise ProjectError("lesson does not match the LessonProposal digest")
    return True


def _validate_evidence_link(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != EVIDENCE_LINK_FIELDS:
        raise ProjectError("invalid EvidenceLink fields")
    _validate_id(value.get("id"), EVIDENCE_LINK_ID_PATTERN, "EvidenceLink id")
    _validate_id(value.get("workItemId"), WORK_ITEM_ID_PATTERN, "EvidenceLink WorkItem id")
    _validate_id(value.get("receiptId"), receipts.RECEIPT_ID_PATTERN, "EvidenceLink receipt id")
    if value.get("evidenceKind") not in {"gate", "test"}:
        raise ProjectError("EvidenceLink kind must be gate or test")
    _validate_digest(value.get("sourceFingerprint"), "EvidenceLink sourceFingerprint")
    _validate_timestamp(value.get("createdAt"), "EvidenceLink createdAt")
    return value


def _load_evidence_links(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved, path, store = _read_store(
        root,
        "evidence-links.json",
        {"schemaVersion": STORE_SCHEMA_VERSION, "evidenceLinks": []},
    )
    if set(store) != {"schemaVersion", "evidenceLinks"}:
        raise ProjectError("invalid EvidenceLink store fields")
    if type(store.get("schemaVersion")) is not int or store["schemaVersion"] != STORE_SCHEMA_VERSION:
        raise ProjectError("unsupported EvidenceLink store schema")
    raw = store.get("evidenceLinks")
    if not isinstance(raw, list):
        raise ProjectError("invalid EvidenceLink store entries")
    records = [_validate_evidence_link(item) for item in raw]
    _validate_unique_ids(records, "EvidenceLink")
    work_ids = {item["id"] for item in list_work_items(resolved)}
    if any(record["workItemId"] not in work_ids for record in records):
        raise ProjectError("EvidenceLink references an unknown WorkItem")
    return resolved, path, store


def list_evidence_links(root: str | Path, work_item_id: str | None = None) -> list[dict[str, Any]]:
    records = list(_load_evidence_links(root)[2]["evidenceLinks"])
    if work_item_id is None:
        return records
    _validate_id(work_item_id, WORK_ITEM_ID_PATTERN, "WorkItem id")
    get_work_item(root, work_item_id)
    return [record for record in records if record["workItemId"] == work_item_id]


def _evidence_receipt_is_current(root: Path, link: dict[str, Any], fingerprint: str) -> bool:
    if link["sourceFingerprint"] != fingerprint:
        return False
    try:
        evidence = receipts.get(root, link["receiptId"])
    except ProjectError:
        return False
    return (
        evidence["adapter"] == "trellis"
        and evidence["kind"] == link["evidenceKind"]
        and evidence["kind"] in {"gate", "test"}
        and evidence["outcome"] == "succeeded"
    )


def current_valid_evidence_links(
    root: str | Path,
    work_item_id: str | None = None,
) -> list[dict[str, Any]]:
    resolved, _ = _paths(root)
    if work_item_id is None:
        current = current_work_item(resolved)
        if current is None:
            return []
        work_item = current
        work_item_id = current["id"]
    else:
        work_item = get_work_item(resolved, work_item_id)
    current_fingerprint = capabilities.fingerprint(resolved)
    if work_item_id is not None and work_item["sourceFingerprint"] != current_fingerprint:
        return []
    return [
        link
        for link in list_evidence_links(resolved, work_item_id)
        if _evidence_receipt_is_current(resolved, link, current_fingerprint)
    ]


def evidence_binding(root: str | Path, work_item_id: str | None = None) -> dict[str, Any]:
    """Build the execution-time WorkItem binding for a typed gate/test receipt."""
    resolved, _ = _paths(root)
    work_item = current_work_item(resolved) if work_item_id is None else get_work_item(resolved, work_item_id)
    if work_item is None:
        raise ProjectError("gate evidence binding requires a current WorkItem")
    validate_work_item_reference(resolved, work_item)
    if work_item["backend"] != "trellis":
        raise ProjectError("gate evidence binding requires a Trellis WorkItem")
    current_fingerprint = capabilities.fingerprint(resolved)
    if work_item["sourceFingerprint"] != current_fingerprint:
        raise ProjectError("WorkItem fingerprint is stale; refresh it before running validation")
    return {
        "schemaVersion": 1,
        "workItemId": work_item["id"],
        "backend": work_item["backend"],
        "nativeRef": work_item["nativeRef"],
        "sourceFingerprint": current_fingerprint,
    }


def reconcile_evidence(
    root: str | Path,
    receipt_id: str,
    work_item_id: str | None = None,
) -> dict[str, Any]:
    with locked_state(root, "evidence-links"):
        resolved, path, store = _load_evidence_links(root)
        work_item = current_work_item(resolved) if work_item_id is None else get_work_item(resolved, work_item_id)
        if work_item is None:
            raise ProjectError("evidence reconciliation requires a current WorkItem")
        validate_work_item_reference(resolved, work_item)
        current_fingerprint = capabilities.fingerprint(resolved)
        if work_item["sourceFingerprint"] != current_fingerprint:
            raise ProjectError("WorkItem fingerprint is stale; refresh it before reconciling evidence")
        evidence = receipts.get(resolved, receipt_id)
        if (
            evidence["adapter"] != "trellis"
            or evidence["kind"] not in {"gate", "test"}
            or evidence["outcome"] != "succeeded"
        ):
            raise ProjectError("EvidenceLink requires a successful Trellis gate or test receipt")
        expected_binding = evidence_binding(resolved, work_item["id"])
        if evidence.get("evidenceBindingSha256") != receipts.payload_sha256(expected_binding):
            raise ProjectError(
                "receipt is not bound to this WorkItem and fingerprint; rerun validation after selecting current work"
            )
        existing = next(
            (
                item
                for item in store["evidenceLinks"]
                if item["workItemId"] == work_item["id"]
                and item["receiptId"] == receipt_id
                and item["sourceFingerprint"] == current_fingerprint
            ),
            None,
        )
        if existing is not None:
            return existing
        link = {
            "id": _next_id(store["evidenceLinks"], "evidence-"),
            "workItemId": work_item["id"],
            "receiptId": receipt_id,
            "evidenceKind": evidence["kind"],
            "sourceFingerprint": current_fingerprint,
            "createdAt": utc_now(),
        }
        _validate_evidence_link(link)
        store["evidenceLinks"].append(link)
        _write_store(path, store)
        return link
