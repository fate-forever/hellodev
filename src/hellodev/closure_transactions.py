"""Recoverable journal for Trellis-backed managed closure."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import lifecycle, receipts
from .component_protocol import canonical_sha256
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
STATES = ("prepared", "native-completed", "lifecycle-finished", "committed")
MAX_RECORDS = 100
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _empty() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "records": []}


def _validate(record: Any) -> dict[str, Any]:
    fields = {
        "id", "workItemId", "cycleId", "task", "state", "preparedAt", "updatedAt",
        "receiptId", "operationId", "previousTaskDigest", "completedTaskDigest",
        "legacyAdopted", "history",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise ProjectError("invalid closure transaction fields")
    if not isinstance(record.get("id"), str) or not record["id"].startswith("closure-"):
        raise ProjectError("invalid closure transaction id")
    if not isinstance(record.get("workItemId"), str) or not record["workItemId"].startswith("work-"):
        raise ProjectError("invalid closure transaction WorkItem")
    if not isinstance(record.get("cycleId"), str) or not record["cycleId"].startswith("cycle-"):
        raise ProjectError("invalid closure transaction cycle")
    if not isinstance(record.get("task"), str) or not record["task"] or len(record["task"]) > 96:
        raise ProjectError("invalid closure transaction task")
    if record.get("state") not in STATES:
        raise ProjectError("invalid closure transaction state")
    if not all(isinstance(record.get(name), str) and record[name] for name in ("preparedAt", "updatedAt")):
        raise ProjectError("invalid closure transaction timestamp")
    for name in ("previousTaskDigest", "completedTaskDigest"):
        value = record.get(name)
        if value is not None and (not isinstance(value, str) or _DIGEST.fullmatch(value) is None):
            raise ProjectError("invalid closure transaction task digest")
    if record.get("receiptId") is not None and not str(record["receiptId"]).startswith("receipt-"):
        raise ProjectError("invalid closure transaction receipt")
    if record.get("operationId") is not None and not str(record["operationId"]).startswith("hd-trellis-"):
        raise ProjectError("invalid closure transaction operation")
    if type(record.get("legacyAdopted")) is not bool:
        raise ProjectError("invalid closure transaction adoption state")
    history = record.get("history")
    if not isinstance(history, list) or not history or len(history) > len(STATES):
        raise ProjectError("invalid closure transaction history")
    expected = STATES[: STATES.index(record["state"]) + 1]
    if tuple(item.get("state") for item in history if isinstance(item, dict)) != expected:
        raise ProjectError("invalid closure transaction phase ordering")
    if any(set(item) != {"state", "at"} or not isinstance(item.get("at"), str) for item in history):
        raise ProjectError("invalid closure transaction history event")
    return record


def _load(root: Path) -> dict[str, Any]:
    load_config(root)
    path = ProjectPaths(root).closure_transactions_file
    if not path.exists():
        return _empty()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ProjectError("closure transaction journal is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid closure transaction journal: {error}") from error
    records = value.get("records") if isinstance(value, dict) and value.get("schemaVersion") == SCHEMA_VERSION else None
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ProjectError("invalid closure transaction journal")
    normalized = [_validate(item) for item in records]
    if len({item["id"] for item in normalized}) != len(normalized):
        raise ProjectError("duplicate closure transaction id")
    return {"schemaVersion": SCHEMA_VERSION, "records": normalized}


def _write(root: Path, store: dict[str, Any]) -> None:
    write_json(ProjectPaths(root).closure_transactions_file, store)


def _id(work_item: dict[str, Any], cycle_id: str) -> str:
    payload = {"workItemId": work_item["id"], "cycleId": cycle_id, "task": work_item["nativeRef"]}
    return "closure-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]


def _task_state(root: Path, task: str) -> dict[str, str]:
    path = root / ".trellis" / "tasks" / task / "task.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ProjectError("closure transaction Trellis task is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid closure transaction Trellis task: {error}") from error
    if not isinstance(value, dict) or value.get("status") not in {"planning", "in_progress", "completed", "archived"}:
        raise ProjectError("invalid closure transaction Trellis task")
    return {"status": value["status"], "digest": canonical_sha256(value)}


def current(root: str | Path, work_item: dict[str, Any] | None = None) -> dict[str, Any] | None:
    resolved = resolve_root(root)
    records = _load(resolved)["records"]
    if work_item is not None:
        return next((item for item in reversed(records) if item["workItemId"] == work_item["id"]), None)
    return next((item for item in reversed(records) if item["state"] != "committed"), None)


def prepare(root: str | Path, work_item: dict[str, Any]) -> dict[str, Any]:
    resolved = resolve_root(root)
    cycle_id = lifecycle.status(resolved)["cycleId"]
    transaction_id = _id(work_item, cycle_id)
    with locked_state(resolved, "closure-transactions"):
        store = _load(resolved)
        existing = next((item for item in store["records"] if item["id"] == transaction_id), None)
        if existing is not None:
            if existing["workItemId"] != work_item["id"] or existing["task"] != work_item["nativeRef"]:
                raise ProjectError("closure transaction binding conflict")
            return existing
        now = utc_now()
        task = _task_state(resolved, work_item["nativeRef"])
        record = {
            "id": transaction_id,
            "workItemId": work_item["id"],
            "cycleId": cycle_id,
            "task": work_item["nativeRef"],
            "state": "prepared",
            "preparedAt": now,
            "updatedAt": now,
            "receiptId": None,
            "operationId": None,
            "previousTaskDigest": task["digest"],
            "completedTaskDigest": task["digest"] if task["status"] == "completed" else None,
            "legacyAdopted": False,
            "history": [{"state": "prepared", "at": now}],
        }
        _validate(record)
        store["records"] = [*store["records"], record][-MAX_RECORDS:]
        _write(resolved, store)
        return record


def _advance(root: Path, transaction_id: str, state: str, **updates: Any) -> dict[str, Any]:
    if state not in STATES:
        raise ProjectError("invalid closure transaction target state")
    with locked_state(root, "closure-transactions"):
        store = _load(root)
        record = next((item for item in store["records"] if item["id"] == transaction_id), None)
        if record is None:
            raise ProjectError("closure transaction not found")
        current_index, target_index = STATES.index(record["state"]), STATES.index(state)
        if target_index <= current_index:
            return record
        if target_index != current_index + 1:
            raise ProjectError("closure transaction phase cannot be skipped")
        now = utc_now()
        record.update(updates)
        record["state"] = state
        record["updatedAt"] = now
        record["history"].append({"state": state, "at": now})
        _validate(record)
        _write(root, store)
        return record


def record_native_completion(
    root: str | Path,
    transaction_id: str,
    completion: dict[str, Any],
    *,
    legacy_adopted: bool = False,
) -> dict[str, Any]:
    resolved = resolve_root(root)
    result = completion.get("result")
    receipt = result.get("receipt") if isinstance(result, dict) else None
    component = result.get("componentResult") if isinstance(result, dict) else None
    data = component.get("data") if isinstance(component, dict) else None
    task = data.get("task") if isinstance(data, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("operation") != "intent/task-complete"
        or receipt.get("outcome") != "succeeded"
        or not isinstance(component, dict)
        or component.get("ok") is not True
        or component.get("action") != "task-complete"
        or not isinstance(data, dict)
        or not isinstance(task, dict)
        or task.get("status") != "completed"
        or _DIGEST.fullmatch(str(task.get("digest", ""))) is None
        or _DIGEST.fullmatch(str(data.get("previousDigest", ""))) is None
    ):
        raise ProjectError("invalid native completion for closure transaction")
    return _advance(
        resolved,
        transaction_id,
        "native-completed",
        receiptId=receipt["id"],
        operationId=component["operationId"],
        previousTaskDigest=data["previousDigest"],
        completedTaskDigest=task["digest"],
        legacyAdopted=legacy_adopted,
    )


def _component_result(root: Path, operation_id: str) -> dict[str, Any]:
    path = ProjectPaths(root).state_dir / "component-operations.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ProjectError("component operation ledger is missing or unsafe during closure recovery")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid component operation ledger during closure recovery: {error}") from error
    operations = store.get("operations") if isinstance(store, dict) else None
    entry = operations.get(operation_id) if isinstance(operations, dict) else None
    result = entry.get("result") if isinstance(entry, dict) else None
    if not isinstance(result, dict):
        raise ProjectError("closure recovery component result is missing")
    return result


def _receipt(root: Path, receipt_id: str) -> dict[str, Any]:
    matches = [item for item in receipts.list_receipts(root) if item["id"] == receipt_id]
    if len(matches) != 1:
        raise ProjectError("closure recovery receipt is missing or ambiguous")
    return matches[0]


def _discover(root: Path, transaction: dict[str, Any]) -> dict[str, Any] | None:
    task_state = _task_state(root, transaction["task"])
    if task_state["status"] != "completed":
        return None
    ledger_path = ProjectPaths(root).state_dir / "component-operations.json"
    if not ledger_path.is_file() or ledger_path.is_symlink() or ledger_path.stat().st_size > 1024 * 1024:
        return None
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid component operation ledger during closure discovery: {error}") from error
    operations = ledger.get("operations") if isinstance(ledger, dict) else None
    if not isinstance(operations, dict) or len(operations) > 256:
        raise ProjectError("invalid component operation ledger during closure discovery")
    candidates: list[tuple[str, dict[str, Any]]] = []
    for operation_id, entry in operations.items():
        result = entry.get("result") if isinstance(entry, dict) else None
        data = result.get("data") if isinstance(result, dict) else None
        task = data.get("task") if isinstance(data, dict) else None
        if (
            isinstance(result, dict)
            and result.get("ok") is True
            and result.get("action") == "task-complete"
            and isinstance(task, dict)
            and task.get("id") == transaction["task"]
            and task.get("status") == "completed"
            and task.get("digest") == task_state["digest"]
        ):
            candidates.append((operation_id, result))
    receipt_candidates = [
        item for item in receipts.list_receipts(root)
        if item["adapter"] == "trellis"
        and item["operation"] == "intent/task-complete"
        and item["outcome"] == "succeeded"
    ]
    # Legacy partial commits did not persist a transaction id that binds the two
    # ledgers. Adopt only an unambiguous pair; guessing the newest historical
    # receipt could falsely attest completion of another task.
    if len(candidates) != 1 or len(receipt_candidates) != 1:
        return None
    operation_id, component = candidates[0]
    return {
        "executionPerformed": False,
        "recovered": True,
        "result": {"exitCode": 0, "receipt": receipt_candidates[0], "componentResult": component},
    }


def completion(root: str | Path, work_item: dict[str, Any]) -> dict[str, Any] | None:
    resolved = resolve_root(root)
    transaction = current(resolved, work_item)
    if transaction is None:
        return None
    if transaction["state"] == "prepared":
        discovered = _discover(resolved, transaction)
        if discovered is None:
            return None
        transaction = record_native_completion(resolved, transaction["id"], discovered, legacy_adopted=True)
    if STATES.index(transaction["state"]) < STATES.index("native-completed"):
        return None
    return {
        "state": "native-completion-recovered",
        "executionPerformed": False,
        "recovered": True,
        "closureTransactionId": transaction["id"],
        "result": {
            "exitCode": 0,
            "receipt": _receipt(resolved, transaction["receiptId"]),
            "componentResult": _component_result(resolved, transaction["operationId"]),
        },
    }


def mark_lifecycle_finished(root: str | Path, transaction_id: str) -> dict[str, Any]:
    return _advance(resolve_root(root), transaction_id, "lifecycle-finished")


def commit(root: str | Path, transaction_id: str) -> dict[str, Any]:
    return _advance(resolve_root(root), transaction_id, "committed")


def status(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    transaction = current(resolved)
    phase = lifecycle.status(resolved)["phase"]
    if transaction is None:
        return {"schemaVersion": 1, "state": "clean", "recoveryRequired": False, "executionPerformed": False}
    command = "hellodev do check" if phase == "working" and transaction["state"] == "native-completed" else "hellodev do finish"
    return {
        "schemaVersion": 1,
        "state": transaction["state"],
        "recoveryRequired": True,
        "transactionId": transaction["id"],
        "workItemId": transaction["workItemId"],
        "task": transaction["task"],
        "nextCommand": command,
        "legacyAdopted": transaction["legacyAdopted"],
        "executionPerformed": False,
    }


__all__ = [
    "commit", "completion", "current", "mark_lifecycle_finished", "prepare",
    "record_native_completion", "status",
]
