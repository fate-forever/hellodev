"""Append-only WAL for authorized policy receipt and ledger recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import receipts
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
LEDGER_ID = "policy-transactions-v1"
GENESIS = "GENESIS"
MAX_EVENTS = 100_000
EVENT_ORDER = ("authorized", "token-consumed", "receipt-recorded", "ledger-applied")
OPERATIONS = {"evolution.canary-start", "evolution.commit", "evolution.revert"}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "eventSha256"}


def _empty() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ledgerId": LEDGER_ID,
        "events": [],
        "head": {"sequence": 0, "eventSha256": GENESIS},
    }


def _validate_event(event: Any, sequence: int, previous: str) -> dict[str, Any]:
    fields = {
        "schemaVersion", "sequence", "id", "transactionId", "eventType", "operation",
        "action", "actionSha256", "approvalPlanId", "receiptId", "ledgerEventId",
        "createdAt", "previousEventSha256", "eventSha256",
    }
    if not isinstance(event, dict) or set(event) != fields or event.get("schemaVersion") != SCHEMA_VERSION:
        raise ProjectError("invalid policy transaction event fields")
    if event.get("sequence") != sequence or event.get("id") != f"transaction-event-{sequence:04d}":
        raise ProjectError("invalid policy transaction event sequence")
    if event.get("eventType") not in EVENT_ORDER or event.get("previousEventSha256") != previous:
        raise ProjectError("invalid policy transaction event chain")
    if not isinstance(event.get("transactionId"), str) or not event["transactionId"].startswith("transaction-"):
        raise ProjectError("invalid policy transaction id")
    if event.get("operation") not in OPERATIONS or not isinstance(event.get("action"), dict):
        raise ProjectError("invalid policy transaction action")
    if not _valid_digest(event.get("actionSha256")) or event["actionSha256"] != _digest(event["action"]):
        raise ProjectError("policy transaction action digest mismatch")
    if not isinstance(event.get("approvalPlanId"), str) or not event["approvalPlanId"].startswith("approval-plan-"):
        raise ProjectError("invalid policy transaction approval plan")
    index = EVENT_ORDER.index(event["eventType"])
    receipt_id, ledger_id = event.get("receiptId"), event.get("ledgerEventId")
    if index < 2 and (receipt_id is not None or ledger_id is not None):
        raise ProjectError("invalid pre-receipt policy transaction event")
    if index == 2 and (not isinstance(receipt_id, str) or not receipt_id.startswith("receipt-") or ledger_id is not None):
        raise ProjectError("invalid receipt-recorded transaction event")
    if index == 3 and (
        not isinstance(receipt_id, str) or not receipt_id.startswith("receipt-")
        or not isinstance(ledger_id, str) or not ledger_id.startswith("policy-event-")
    ):
        raise ProjectError("invalid ledger-applied transaction event")
    if not isinstance(event.get("createdAt"), str) or not event["createdAt"]:
        raise ProjectError("invalid policy transaction timestamp")
    if not _valid_digest(event.get("eventSha256")) or event["eventSha256"] != _digest(_event_payload(event)):
        raise ProjectError("policy transaction event digest mismatch")
    return event


def _load(root: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved = resolve_root(root)
    load_config(resolved)
    path = ProjectPaths(resolved).transactions_file
    if not path.exists():
        return resolved, _empty()
    if path.is_symlink() or not path.is_file():
        raise ProjectError("refusing unsafe policy transaction journal")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid policy transaction journal: {error}") from error
    if not isinstance(store, dict) or set(store) != {"schemaVersion", "ledgerId", "events", "head"}:
        raise ProjectError("invalid policy transaction journal fields")
    if store.get("schemaVersion") != SCHEMA_VERSION or store.get("ledgerId") != LEDGER_ID:
        raise ProjectError("unsupported policy transaction journal schema")
    if not isinstance(store.get("events"), list) or len(store["events"]) > MAX_EVENTS:
        raise ProjectError("invalid policy transaction journal events")
    previous = GENESIS
    phases: dict[str, int] = {}
    bindings: dict[str, tuple[Any, ...]] = {}
    for sequence, raw in enumerate(store["events"], start=1):
        event = _validate_event(raw, sequence, previous)
        previous = event["eventSha256"]
        txid = event["transactionId"]
        phase = EVENT_ORDER.index(event["eventType"])
        if phase != phases.get(txid, -1) + 1:
            raise ProjectError("invalid policy transaction phase ordering")
        phases[txid] = phase
        binding = (event["operation"], event["actionSha256"], event["approvalPlanId"])
        if txid in bindings and bindings[txid] != binding:
            raise ProjectError("policy transaction binding changed")
        bindings[txid] = binding
    if store.get("head") != {"sequence": len(store["events"]), "eventSha256": previous}:
        raise ProjectError("policy transaction journal head mismatch")
    return resolved, store


def _append(root: Path, transaction_id: str, event_type: str, operation: str, action: dict[str, Any], approval_plan_id: str, receipt_id: str | None = None, ledger_event_id: str | None = None) -> dict[str, Any]:
    with locked_state(root, "transactions"):
        _, store = _load(root)
        events = [item for item in store["events"] if item["transactionId"] == transaction_id]
        requested_phase = EVENT_ORDER.index(event_type)
        if events:
            latest = events[-1]
            latest_phase = EVENT_ORDER.index(latest["eventType"])
            if latest_phase >= requested_phase:
                matching = next((item for item in events if item["eventType"] == event_type), None)
                if matching is None:
                    raise ProjectError("policy transaction phase conflict")
                return matching
            if latest_phase + 1 != requested_phase:
                raise ProjectError("policy transaction phase cannot be skipped")
            if latest["operation"] != operation or latest["actionSha256"] != _digest(action) or latest["approvalPlanId"] != approval_plan_id:
                raise ProjectError("policy transaction binding conflict")
        elif event_type != "authorized":
            raise ProjectError("policy transaction must begin with authorization")
        sequence = len(store["events"]) + 1
        event = {
            "schemaVersion": SCHEMA_VERSION,
            "sequence": sequence,
            "id": f"transaction-event-{sequence:04d}",
            "transactionId": transaction_id,
            "eventType": event_type,
            "operation": operation,
            "action": action,
            "actionSha256": _digest(action),
            "approvalPlanId": approval_plan_id,
            "receiptId": receipt_id,
            "ledgerEventId": ledger_event_id,
            "createdAt": utc_now(),
            "previousEventSha256": store["head"]["eventSha256"],
            "eventSha256": "",
        }
        event["eventSha256"] = _digest(_event_payload(event))
        _validate_event(event, sequence, store["head"]["eventSha256"])
        store["events"].append(event)
        store["head"] = {"sequence": sequence, "eventSha256": event["eventSha256"]}
        write_json(ProjectPaths(root).transactions_file, store)
        return event


def begin(root: str | Path, action: dict[str, Any], approval_plan_id: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    operation = action.get("operation")
    if operation not in OPERATIONS:
        raise ProjectError("unsupported transactional policy operation")
    transaction_id = f"transaction-{_digest({'plan': approval_plan_id, 'action': action})[:20]}"
    _append(resolved, transaction_id, "authorized", operation, action, approval_plan_id)
    return get(resolved, transaction_id)


def mark_token_consumed(root: str | Path, transaction_id: str) -> dict[str, Any]:
    tx = get(root, transaction_id)
    _append(resolve_root(root), transaction_id, "token-consumed", tx["operation"], tx["action"], tx["approvalPlanId"])
    return get(root, transaction_id)


def authorization_result(transaction_id: str) -> dict[str, Any]:
    return {"authorized": True, "ledgerMutationPending": True, "transactionId": transaction_id}


def find_authorization_receipt(root: str | Path, transaction_id: str) -> dict[str, Any] | None:
    tx = get(root, transaction_id)
    request_sha = receipts.payload_sha256(tx["action"])
    result_sha = receipts.payload_sha256(authorization_result(transaction_id))
    matches = [
        item for item in receipts.list_receipts(resolve_root(root))
        if item["kind"] == "policy" and item["adapter"] == "hellodev"
        and item["operation"] == tx["operation"] and item["outcome"] == "succeeded"
        and item["requestSha256"] == request_sha and item["resultSha256"] == result_sha
    ]
    if len(matches) > 1:
        raise ProjectError("duplicate policy transaction authorization receipts")
    return matches[0] if matches else None


def record_authorization_receipt(root: str | Path, transaction_id: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    tx = get(resolved, transaction_id)
    if EVENT_ORDER.index(tx["state"]) < EVENT_ORDER.index("token-consumed"):
        raise ProjectError("policy transaction token has not been consumed")
    receipt = find_authorization_receipt(resolved, transaction_id)
    if receipt is None:
        receipt = receipts.record(
            resolved, "hellodev", tx["operation"], "write", tx["action"],
            authorization_result(transaction_id), True, kind="policy", authorization_mode="token-required",
        )
    _append(resolved, transaction_id, "receipt-recorded", tx["operation"], tx["action"], tx["approvalPlanId"], receipt_id=receipt["id"])
    return receipt


def mark_ledger_applied(root: str | Path, transaction_id: str, ledger_event_id: str) -> dict[str, Any]:
    tx = get(root, transaction_id)
    if tx["receiptId"] is None:
        raise ProjectError("policy transaction has no authorization receipt")
    _append(resolve_root(root), transaction_id, "ledger-applied", tx["operation"], tx["action"], tx["approvalPlanId"], receipt_id=tx["receiptId"], ledger_event_id=ledger_event_id)
    return get(root, transaction_id)


def transaction_for_receipt(root: str | Path, receipt_id: str) -> dict[str, Any] | None:
    return next((item for item in list_transactions(root) if item["receiptId"] == receipt_id), None)


def list_transactions(root: str | Path) -> list[dict[str, Any]]:
    _, store = _load(root)
    derived: dict[str, dict[str, Any]] = {}
    for event in store["events"]:
        derived[event["transactionId"]] = {
            "schemaVersion": SCHEMA_VERSION,
            "id": event["transactionId"],
            "state": event["eventType"],
            "operation": event["operation"],
            "action": event["action"],
            "actionSha256": event["actionSha256"],
            "approvalPlanId": event["approvalPlanId"],
            "receiptId": event["receiptId"],
            "ledgerEventId": event["ledgerEventId"],
            "updatedAt": event["createdAt"],
            "recoveryCommand": None if event["eventType"] == "ledger-applied" else f"hellodev transaction recover {event['transactionId']}",
        }
    return list(derived.values())


def get(root: str | Path, transaction_id: str) -> dict[str, Any]:
    if not isinstance(transaction_id, str) or not transaction_id.startswith("transaction-"):
        raise ProjectError("invalid policy transaction id")
    for tx in list_transactions(root):
        if tx["id"] == transaction_id:
            return tx
    raise ProjectError(f"policy transaction not found: {transaction_id}")


def status(root: str | Path) -> dict[str, Any]:
    all_transactions = list_transactions(root)
    pending = [item for item in all_transactions if item["state"] != "ledger-applied"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "recovery-required" if pending else "clean",
        "transactionCount": len(all_transactions),
        "pendingCount": len(pending),
        "pending": [
            {key: item[key] for key in ("id", "state", "operation", "receiptId", "updatedAt", "recoveryCommand")}
            for item in pending
        ],
        "nextRecoveryCommand": pending[0]["recoveryCommand"] if pending else None,
        "rawTokenPersisted": False,
        "executionPerformed": False,
        "persistencePerformed": False,
    }
