"""Verified, local-only evolution policy overlay for HelloDev 0.11."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import approval, receipts
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
LEDGER_ID = "evolution-policy-v1"
GENESIS = "GENESIS"
DEFAULT_POLICY = {
    "delegation.effectiveMaxAgents": 2,
    "retry.maxAttempts": 3,
}
HARD_MINIMUMS = {
    "delegation.effectiveMaxAgents": 1,
    "retry.maxAttempts": 1,
}
HARD_MAXIMUMS = {
    "delegation.effectiveMaxAgents": 4,
    "retry.maxAttempts": 10,
}
EVENT_TYPES = {"stage", "cancel-stage", "canary-start", "commit", "revert"}
AUTHORIZED_OPERATIONS = {
    "canary-start": "evolution.canary-start",
    "commit": "evolution.commit",
    "revert": "evolution.revert",
}
MAX_EVENTS = 10_000


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ProjectError(f"invalid {label} timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ProjectError(f"invalid {label} timestamp") from error
    return parsed.astimezone(timezone.utc)


def _policy(value: Any, label: str = "evolution policy") -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY):
        raise ProjectError(f"invalid {label} fields")
    normalized: dict[str, int] = {}
    for target in sorted(DEFAULT_POLICY):
        current = value[target]
        if type(current) is not int or not HARD_MINIMUMS[target] <= current <= HARD_MAXIMUMS[target]:
            raise ProjectError(f"invalid {label} value for {target}")
        normalized[target] = current
    return normalized


def _patches(value: Any, *, tightening: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= len(DEFAULT_POLICY):
        raise ProjectError("invalid evolution policy patches")
    targets: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for patch in value:
        fields = {"target", "operation", "valueType", "fromValue", "toValue", "constraintCode"}
        if not isinstance(patch, dict) or set(patch) != fields:
            raise ProjectError("invalid evolution policy patch fields")
        target = patch["target"]
        if target not in DEFAULT_POLICY or target in targets:
            raise ProjectError("invalid or duplicate evolution policy target")
        targets.add(target)
        if patch["operation"] != "replace" or patch["valueType"] != "integer":
            raise ProjectError("invalid evolution policy patch operation")
        before, after = patch["fromValue"], patch["toValue"]
        if type(before) is not int or type(after) is not int:
            raise ProjectError("evolution policy patch values must be integers")
        if not HARD_MINIMUMS[target] <= after <= HARD_MAXIMUMS[target]:
            raise ProjectError("evolution policy patch exceeds product limits")
        expected = "tighten-only" if tightening else "restore-previous-committed"
        if patch["constraintCode"] != expected:
            raise ProjectError("invalid evolution policy patch constraint")
        if tightening and after >= before:
            raise ProjectError("evolution policy proposals must strictly tighten")
        if not tightening and after <= before:
            raise ProjectError("evolution policy revert must restore a less restrictive prior value")
        normalized.append(dict(patch))
    return sorted(normalized, key=lambda item: item["target"])


def _apply(policy: dict[str, int], patches: list[dict[str, Any]], *, tightening: bool) -> dict[str, int]:
    result = dict(_policy(policy))
    for patch in _patches(patches, tightening=tightening):
        target = patch["target"]
        if result[target] != patch["fromValue"]:
            raise ProjectError(f"evolution policy base value is stale for {target}")
        result[target] = patch["toValue"]
    return _policy(result)


def _empty_store() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ledgerId": LEDGER_ID,
        "events": [],
        "head": {"sequence": 0, "eventSha256": GENESIS},
    }


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "eventSha256"}


def _authorization_payload(event: dict[str, Any]) -> dict[str, Any]:
    canary = event["canary"]
    canary_plan = None if canary is None else {
        "turnLimit": canary["turnLimit"],
        "ttlSeconds": canary["ttlSeconds"],
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "operation": AUTHORIZED_OPERATIONS[event["eventType"]],
        "proposalId": event["proposalId"],
        "previousEventSha256": event["previousEventSha256"],
        "basePolicyFingerprint": event["basePolicyFingerprint"],
        "beforePolicy": event["beforePolicy"],
        "afterPolicy": event["afterPolicy"],
        "patches": event["patches"],
        "canary": canary_plan,
        "evidenceHostCompletionIds": event["evidenceHostCompletionIds"],
    }


def _validate_authorization(root: Path, event: dict[str, Any]) -> None:
    if event["eventType"] in {"stage", "cancel-stage"}:
        if event["authorizationReceiptId"] is not None:
            raise ProjectError("stage events cannot carry authorization receipts")
        return
    receipt_id = event["authorizationReceiptId"]
    if not isinstance(receipt_id, str):
        raise ProjectError("evolution policy event requires an authorization receipt")
    receipt = receipts.get(root, receipt_id)
    if (
        receipt["kind"] != "policy"
        or receipt["adapter"] != "hellodev"
        or receipt["operation"] != AUTHORIZED_OPERATIONS[event["eventType"]]
        or receipt["outcome"] != "succeeded"
        or receipt["risk"] != "write"
        or receipt["requestSha256"] != receipts.payload_sha256(_authorization_payload(event))
    ):
        raise ProjectError("evolution policy authorization receipt does not match the event")


def _validate_event(root: Path, event: Any, expected_sequence: int, previous: str) -> dict[str, Any]:
    fields = {
        "schemaVersion", "sequence", "id", "eventType", "proposalId",
        "previousEventSha256", "basePolicyFingerprint", "beforePolicy", "afterPolicy",
        "patches", "canary", "authorizationReceiptId", "evidenceHostCompletionIds",
        "idempotencyKeySha256", "createdAt", "eventSha256",
    }
    if not isinstance(event, dict) or set(event) != fields or event["schemaVersion"] != SCHEMA_VERSION:
        raise ProjectError("invalid evolution policy event fields")
    if event["sequence"] != expected_sequence or event["id"] != f"policy-event-{expected_sequence:04d}":
        raise ProjectError("invalid evolution policy event sequence")
    if event["eventType"] not in EVENT_TYPES or event["previousEventSha256"] != previous:
        raise ProjectError("invalid evolution policy event chain")
    if not isinstance(event["proposalId"], str) or not event["proposalId"].startswith("evolution-"):
        raise ProjectError("invalid evolution proposal id in policy event")
    for field in ("basePolicyFingerprint", "idempotencyKeySha256", "eventSha256"):
        if not isinstance(event[field], str) or len(event[field]) != 64:
            raise ProjectError("invalid evolution policy event digest")
    before, after = _policy(event["beforePolicy"], "before policy"), _policy(event["afterPolicy"], "after policy")
    tightening = event["eventType"] != "revert"
    patches = _patches(event["patches"], tightening=tightening)
    if event["eventType"] == "stage":
        if before != after or event["canary"] is not None or event["evidenceHostCompletionIds"] != []:
            raise ProjectError("invalid staged evolution event")
        _apply(before, patches, tightening=True)
    elif event["eventType"] == "cancel-stage":
        if before != after or event["canary"] is not None or event["evidenceHostCompletionIds"] != []:
            raise ProjectError("invalid cancelled evolution stage")
        _apply(before, patches, tightening=True)
    elif event["eventType"] == "canary-start":
        if _apply(before, patches, tightening=True) != after:
            raise ProjectError("invalid canary policy projection")
        canary = event["canary"]
        if not isinstance(canary, dict) or set(canary) != {"turnLimit", "ttlSeconds", "startedAt", "expiresAt"}:
            raise ProjectError("invalid evolution canary fields")
        if type(canary["turnLimit"]) is not int or not 1 <= canary["turnLimit"] <= 20:
            raise ProjectError("invalid evolution canary turn limit")
        if type(canary["ttlSeconds"]) is not int or not 60 <= canary["ttlSeconds"] <= 86_400:
            raise ProjectError("invalid evolution canary ttl")
        started = _parse_utc(canary["startedAt"], "canary start")
        expires = _parse_utc(canary["expiresAt"], "canary expiry")
        if expires - started != timedelta(seconds=canary["ttlSeconds"]):
            raise ProjectError("evolution canary expiry does not match its ttl")
        if event["evidenceHostCompletionIds"] != []:
            raise ProjectError("canary start cannot contain completion evidence")
    elif event["eventType"] == "commit":
        if _apply(before, patches, tightening=True) != after or event["canary"] is not None:
            raise ProjectError("invalid committed evolution policy")
        evidence = event["evidenceHostCompletionIds"]
        if not isinstance(evidence, list) or not evidence or len(evidence) > 20 or len(evidence) != len(set(evidence)):
            raise ProjectError("committed evolution policy requires bounded unique host evidence")
        if not all(isinstance(item, str) and item.startswith("host-completion-") for item in evidence):
            raise ProjectError("invalid committed host completion evidence")
    else:
        if _apply(before, patches, tightening=False) != after or event["canary"] is not None or event["evidenceHostCompletionIds"] != []:
            raise ProjectError("invalid evolution policy revert")
    _parse_utc(event["createdAt"], "policy event")
    if _canonical_digest(_event_payload(event)) != event["eventSha256"]:
        raise ProjectError("evolution policy event hash mismatch")
    _validate_authorization(root, event)
    return event


def _load(root: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved = resolve_root(root)
    load_config(resolved)
    path = ProjectPaths(resolved).evolution_policy_file
    if not path.exists():
        return resolved, _empty_store()
    if path.is_symlink() or not path.is_file():
        raise ProjectError("refusing unsafe evolution policy ledger")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid evolution policy ledger: {error}") from error
    if not isinstance(store, dict) or set(store) != {"schemaVersion", "ledgerId", "events", "head"}:
        raise ProjectError("invalid evolution policy ledger fields")
    if store["schemaVersion"] != SCHEMA_VERSION or store["ledgerId"] != LEDGER_ID:
        raise ProjectError("unsupported evolution policy ledger schema")
    if not isinstance(store["events"], list) or len(store["events"]) > MAX_EVENTS:
        raise ProjectError("invalid evolution policy event list")
    previous = GENESIS
    for sequence, event in enumerate(store["events"], start=1):
        _validate_event(resolved, event, sequence, previous)
        previous = event["eventSha256"]
    authorization_receipts = [
        event["authorizationReceiptId"]
        for event in store["events"]
        if event["authorizationReceiptId"] is not None
    ]
    idempotency_keys = [event["idempotencyKeySha256"] for event in store["events"]]
    if len(authorization_receipts) != len(set(authorization_receipts)):
        raise ProjectError("evolution policy authorization receipt is reused")
    if len(idempotency_keys) != len(set(idempotency_keys)):
        raise ProjectError("duplicate evolution policy idempotency key")
    expected_head = {"sequence": len(store["events"]), "eventSha256": previous}
    if store["head"] != expected_head:
        raise ProjectError("evolution policy ledger head mismatch")
    return resolved, store


def _derive(store: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    committed = dict(DEFAULT_POLICY)
    previous_committed: dict[str, int] | None = None
    active_stage: dict[str, Any] | None = None
    active_canary: dict[str, Any] | None = None
    state = "default"
    for event in store["events"]:
        if event["eventType"] == "stage":
            active_stage, active_canary, state = event, None, "staged"
        elif event["eventType"] == "cancel-stage":
            active_stage = active_canary = None
            state = "stage-cancelled"
        elif event["eventType"] == "canary-start":
            active_canary, state = event, "canary-active"
        elif event["eventType"] == "commit":
            previous_committed = dict(committed)
            committed = dict(event["afterPolicy"])
            active_stage = active_canary = None
            state = "committed"
        else:
            committed = dict(event["afterPolicy"])
            active_stage = active_canary = None
            state = "reverted"
    current = now or datetime.now(timezone.utc)
    effective = dict(committed)
    canary_expired = False
    canary_exhausted = False
    observed_turns = 0
    if active_canary is not None:
        canary_expired = _parse_utc(active_canary["canary"]["expiresAt"], "canary expiry") <= current
        if canary_expired:
            state = "canary-expired"
        else:
            effective = dict(active_canary["afterPolicy"])
    return {
        "state": state,
        "committedPolicy": committed,
        "previousCommittedPolicy": previous_committed,
        "effectivePolicy": effective,
        "activeStage": active_stage,
        "activeCanary": active_canary,
        "canaryExpired": canary_expired,
        "canaryExhausted": canary_exhausted,
        "observedTurns": observed_turns,
    }


def _runtime_derive(root: Path, store: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Derive the effective overlay including its bounded completion scope."""
    from . import host_bridge

    derived = _derive(store, now)
    active_canary = derived["activeCanary"]
    if active_canary is None:
        return derived
    observed_raw = sum(
        1
        for item in host_bridge.list_completions(root)
        if item["policyLedgerHeadSha256"] == active_canary["eventSha256"] and not item["late"]
    )
    turn_limit = active_canary["canary"]["turnLimit"]
    exhausted = observed_raw >= turn_limit
    derived["observedTurns"] = min(observed_raw, turn_limit)
    derived["canaryExhausted"] = exhausted
    if exhausted and not derived["canaryExpired"]:
        derived["state"] = "canary-exhausted"
        derived["effectivePolicy"] = dict(derived["committedPolicy"])
    return derived


def fingerprint_material(root: str | Path) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    return {
        "committedPolicy": derived["committedPolicy"],
        "effectivePolicy": derived["effectivePolicy"],
    }


def effective_policy(root: str | Path) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": derived["state"],
        "committedPolicy": derived["committedPolicy"],
        "effectivePolicy": derived["effectivePolicy"],
        "ledgerHeadSha256": store["head"]["eventSha256"],
        "canaryExpired": derived["canaryExpired"],
        "canaryExhausted": derived["canaryExhausted"],
        "observedTurns": derived["observedTurns"],
        "persistencePerformed": False,
    }


def status(root: str | Path) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    active = derived["activeCanary"] or derived["activeStage"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": derived["state"],
        "committedPolicy": derived["committedPolicy"],
        "effectivePolicy": derived["effectivePolicy"],
        "eventCount": len(store["events"]),
        "ledgerHead": store["head"],
        "activeProposalId": active["proposalId"] if active else None,
        "activeCanary": None if derived["activeCanary"] is None else {
            "proposalId": derived["activeCanary"]["proposalId"],
            "turnLimit": derived["activeCanary"]["canary"]["turnLimit"],
            "startedAt": derived["activeCanary"]["canary"]["startedAt"],
            "expiresAt": derived["activeCanary"]["canary"]["expiresAt"],
            "expired": derived["canaryExpired"],
            "exhausted": derived["canaryExhausted"],
            "observedTurns": derived["observedTurns"],
        },
        "integrity": {
            "state": "structurally-valid",
            "guarantee": "local hash-chain only; full-history replacement requires an external checkpoint to detect",
        },
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }


def _proposal(root: Path, proposal_id: str) -> dict[str, Any]:
    from . import optimization

    proposal = optimization.get_proposal(root, proposal_id)
    if proposal["stale"]:
        raise ProjectError("EvolutionProposal is stale against the current effective policy")
    patches = _patches(proposal["patches"], tightening=True)
    return {**proposal, "patches": patches}


def _append(root: Path, draft: dict[str, Any]) -> dict[str, Any]:
    with locked_state(root, "evolution-policy"):
        _, store = _load(root)
        for existing in store["events"]:
            if existing["idempotencyKeySha256"] == draft["idempotencyKeySha256"]:
                if any(existing.get(key) != value for key, value in draft.items()):
                    raise ProjectError("evolution policy idempotency key conflicts with an existing event")
                return existing
        if store["head"]["eventSha256"] != draft["previousEventSha256"]:
            raise ProjectError("evolution policy ledger changed; rebuild the exact action")
        sequence = len(store["events"]) + 1
        event = {
            "schemaVersion": SCHEMA_VERSION,
            "sequence": sequence,
            "id": f"policy-event-{sequence:04d}",
            **draft,
            "createdAt": utc_now(),
        }
        event["eventSha256"] = _canonical_digest(event)
        _validate_event(root, event, sequence, store["head"]["eventSha256"])
        store["events"].append(event)
        store["head"] = {"sequence": sequence, "eventSha256": event["eventSha256"]}
        write_json(ProjectPaths(root).evolution_policy_file, store)
        return event


def stage(root: str | Path, proposal_id: str) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    active = derived["activeCanary"] or derived["activeStage"]
    if active is not None:
        if active["proposalId"] == proposal_id and derived["state"] == "staged":
            return {"schemaVersion": SCHEMA_VERSION, "state": "existing", "event": active}
        raise ProjectError("another EvolutionProposal is already staged or in canary")
    proposal = _proposal(resolved, proposal_id)
    before = derived["effectivePolicy"]
    _apply(before, proposal["patches"], tightening=True)
    key_payload = {"eventType": "stage", "proposalId": proposal_id, "head": store["head"], "patches": proposal["patches"]}
    event = _append(resolved, {
        "eventType": "stage",
        "proposalId": proposal_id,
        "previousEventSha256": store["head"]["eventSha256"],
        "basePolicyFingerprint": proposal["basePolicyFingerprint"],
        "beforePolicy": before,
        "afterPolicy": before,
        "patches": proposal["patches"],
        "canary": None,
        "authorizationReceiptId": None,
        "evidenceHostCompletionIds": [],
        "idempotencyKeySha256": _canonical_digest(key_payload),
    })
    return {"schemaVersion": SCHEMA_VERSION, "state": "staged", "event": event}


def cancel_stage(root: str | Path, proposal_id: str) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    if derived["activeCanary"] is not None:
        raise ProjectError("an active canary cannot be cancelled as a staged proposal")
    stage_event = derived["activeStage"]
    if stage_event is None:
        latest = store["events"][-1] if store["events"] else None
        if latest is not None and latest["eventType"] == "cancel-stage" and latest["proposalId"] == proposal_id:
            return {"schemaVersion": SCHEMA_VERSION, "state": "existing", "event": latest}
        raise ProjectError("the selected EvolutionProposal is not staged")
    if stage_event["proposalId"] != proposal_id:
        raise ProjectError("another EvolutionProposal is currently staged")
    key_payload = {
        "eventType": "cancel-stage",
        "proposalId": proposal_id,
        "head": store["head"],
        "patches": stage_event["patches"],
    }
    event = _append(resolved, {
        "eventType": "cancel-stage",
        "proposalId": proposal_id,
        "previousEventSha256": store["head"]["eventSha256"],
        "basePolicyFingerprint": stage_event["basePolicyFingerprint"],
        "beforePolicy": derived["committedPolicy"],
        "afterPolicy": derived["committedPolicy"],
        "patches": stage_event["patches"],
        "canary": None,
        "authorizationReceiptId": None,
        "evidenceHostCompletionIds": [],
        "idempotencyKeySha256": _canonical_digest(key_payload),
    })
    return {"schemaVersion": SCHEMA_VERSION, "state": "stage-cancelled", "event": event}


def canary_action(root: str | Path, proposal_id: str, turns: int, ttl_seconds: int) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    stage_event = derived["activeStage"]
    if stage_event is None or stage_event["proposalId"] != proposal_id or derived["activeCanary"] is not None:
        raise ProjectError("stage the selected EvolutionProposal before starting its canary")
    if type(turns) is not int or not 1 <= turns <= 20 or type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86_400:
        raise ProjectError("canary requires 1-20 turns and a ttl of 60-86400 seconds")
    after = _apply(derived["committedPolicy"], stage_event["patches"], tightening=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "operation": AUTHORIZED_OPERATIONS["canary-start"],
        "proposalId": proposal_id,
        "previousEventSha256": store["head"]["eventSha256"],
        "basePolicyFingerprint": stage_event["basePolicyFingerprint"],
        "beforePolicy": derived["committedPolicy"],
        "afterPolicy": after,
        "patches": stage_event["patches"],
        "canary": {"turnLimit": turns, "ttlSeconds": ttl_seconds},
        "evidenceHostCompletionIds": [],
    }


def _authorized_receipt(root: Path, action: dict[str, Any], token: str) -> dict[str, Any]:
    # Refuse a broken/unsafe receipt store before consuming the one-time token.
    receipts.list_receipts(root)
    approval.consume(root, action, token, "policy")
    return receipts.record(
        root,
        "hellodev",
        action["operation"],
        "write",
        action,
        {"authorized": True, "ledgerMutationPending": True},
        True,
        kind="policy",
        authorization_mode="token-required",
    )


def prepare_authorization(root: str | Path, action: dict[str, Any]) -> dict[str, Any]:
    return approval.prepare(resolve_root(root), action, "policy")


def authorize(root: str | Path, action: dict[str, Any], token: str) -> dict[str, Any]:
    return _authorized_receipt(resolve_root(root), action, token)


def _receipt_for_action(root: Path, action: dict[str, Any], receipt_id: str) -> dict[str, Any]:
    receipt = receipts.get(root, receipt_id)
    if (
        receipt["kind"] != "policy"
        or receipt["adapter"] != "hellodev"
        or receipt["operation"] != action["operation"]
        or receipt["outcome"] != "succeeded"
        or receipt["requestSha256"] != receipts.payload_sha256(action)
    ):
        raise ProjectError("policy receipt does not authorize this exact evolution action")
    return receipt


def _existing_event_for_receipt(
    root: Path,
    receipt_id: str,
    event_type: str,
    *,
    proposal_id: str | None = None,
    turns: int | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any] | None:
    _, store = _load(root)
    existing = next(
        (event for event in store["events"] if event["authorizationReceiptId"] == receipt_id),
        None,
    )
    if existing is None:
        return None
    if existing["eventType"] != event_type:
        raise ProjectError("policy receipt already belongs to a different evolution event")
    if proposal_id is not None and existing["proposalId"] != proposal_id:
        raise ProjectError("policy receipt already belongs to a different EvolutionProposal")
    if event_type == "canary-start" and (
        existing["canary"]["turnLimit"] != turns
        or existing["canary"]["ttlSeconds"] != ttl_seconds
    ):
        raise ProjectError("policy receipt already belongs to a different canary scope")
    return existing


def start_canary(root: str | Path, proposal_id: str, turns: int, ttl_seconds: int, receipt_id: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    existing = _existing_event_for_receipt(
        resolved,
        receipt_id,
        "canary-start",
        proposal_id=proposal_id,
        turns=turns,
        ttl_seconds=ttl_seconds,
    )
    if existing is not None:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "existing",
            "event": existing,
            "receipt": receipts.get(resolved, receipt_id),
        }
    action = canary_action(resolved, proposal_id, turns, ttl_seconds)
    receipt = _receipt_for_action(resolved, action, receipt_id)
    started = datetime.now(timezone.utc).replace(microsecond=0)
    canary = {
        "turnLimit": turns,
        "ttlSeconds": ttl_seconds,
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "expiresAt": (started + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
    }
    key_payload = {**action, "authorizationReceiptId": receipt["id"]}
    event = _append(resolved, {
        "eventType": "canary-start",
        "proposalId": proposal_id,
        "previousEventSha256": action["previousEventSha256"],
        "basePolicyFingerprint": action["basePolicyFingerprint"],
        "beforePolicy": action["beforePolicy"],
        "afterPolicy": action["afterPolicy"],
        "patches": action["patches"],
        "canary": canary,
        "authorizationReceiptId": receipt["id"],
        "evidenceHostCompletionIds": [],
        "idempotencyKeySha256": _canonical_digest(key_payload),
    })
    return {"schemaVersion": SCHEMA_VERSION, "state": "canary-active", "event": event, "receipt": receipt}


def evaluate(root: str | Path, proposal_id: str) -> dict[str, Any]:
    from . import host_bridge

    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    canary = derived["activeCanary"]
    if canary is None or canary["proposalId"] != proposal_id:
        raise ProjectError("the selected EvolutionProposal has no active canary")
    completions = [
        item for item in host_bridge.list_completions(resolved)
        if item["policyLedgerHeadSha256"] == canary["eventSha256"] and not item["late"]
    ]
    selected = completions[: canary["canary"]["turnLimit"]]
    violations: list[dict[str, Any]] = []
    for completion in selected:
        if completion["outcome"] != "succeeded":
            violations.append({"completionId": completion["id"], "reasonCode": "outcome-incomplete"})
        if completion["budgetState"] == "exceeded":
            violations.append({"completionId": completion["id"], "reasonCode": "budget-exceeded"})
        if completion["retryCount"] > canary["afterPolicy"]["retry.maxAttempts"]:
            violations.append({"completionId": completion["id"], "reasonCode": "retry-policy-exceeded"})
        if completion["subagentCount"] > canary["afterPolicy"]["delegation.effectiveMaxAgents"]:
            violations.append({"completionId": completion["id"], "reasonCode": "delegation-policy-exceeded"})
    if derived["canaryExpired"]:
        state, reason = "failed", "canary-expired"
    elif violations:
        state, reason = "failed", "canary-policy-violation"
    elif len(selected) < canary["canary"]["turnLimit"]:
        state, reason = "pending", "insufficient-host-completions"
    else:
        state, reason = "passed", "bounded-canary-completed"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": state,
        "reasonCode": reason,
        "proposalId": proposal_id,
        "requiredCompletions": canary["canary"]["turnLimit"],
        "observedCompletions": len(selected),
        "completionIds": [item["id"] for item in selected],
        "violations": violations,
        "usageTrust": sorted(set(item["usageTrust"] for item in selected)) or ["unavailable"],
        "executionPerformed": False,
        "persistencePerformed": False,
    }


def commit_action(root: str | Path, proposal_id: str) -> dict[str, Any]:
    from . import drift

    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    canary = derived["activeCanary"]
    if canary is None or canary["proposalId"] != proposal_id:
        raise ProjectError("the selected EvolutionProposal has no active canary")
    evaluation = evaluate(resolved, proposal_id)
    if evaluation["state"] != "passed":
        raise ProjectError(f"canary is not ready to commit: {evaluation['reasonCode']}")
    drift_value = drift.status(resolved)
    if drift_value["state"] != "clean":
        raise ProjectError(f"canary drift is not clean: {drift_value['reasonCode']}")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "operation": AUTHORIZED_OPERATIONS["commit"],
        "proposalId": proposal_id,
        "previousEventSha256": store["head"]["eventSha256"],
        "basePolicyFingerprint": canary["basePolicyFingerprint"],
        "beforePolicy": derived["committedPolicy"],
        "afterPolicy": canary["afterPolicy"],
        "patches": canary["patches"],
        "canary": None,
        "evidenceHostCompletionIds": evaluation["completionIds"],
    }


def commit(root: str | Path, proposal_id: str, receipt_id: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    existing = _existing_event_for_receipt(
        resolved,
        receipt_id,
        "commit",
        proposal_id=proposal_id,
    )
    if existing is not None:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "existing",
            "event": existing,
            "receipt": receipts.get(resolved, receipt_id),
        }
    action = commit_action(resolved, proposal_id)
    receipt = _receipt_for_action(resolved, action, receipt_id)
    event = _append(resolved, {
        "eventType": "commit",
        "proposalId": proposal_id,
        "previousEventSha256": action["previousEventSha256"],
        "basePolicyFingerprint": action["basePolicyFingerprint"],
        "beforePolicy": action["beforePolicy"],
        "afterPolicy": action["afterPolicy"],
        "patches": action["patches"],
        "canary": None,
        "authorizationReceiptId": receipt["id"],
        "evidenceHostCompletionIds": action["evidenceHostCompletionIds"],
        "idempotencyKeySha256": _canonical_digest({**action, "authorizationReceiptId": receipt["id"]}),
    })
    return {"schemaVersion": SCHEMA_VERSION, "state": "committed", "event": event, "receipt": receipt}


def revert_action(root: str | Path) -> dict[str, Any]:
    resolved, store = _load(root)
    derived = _runtime_derive(resolved, store)
    latest_transition = next(
        (event for event in reversed(store["events"]) if event["eventType"] in {"commit", "revert"}),
        None,
    )
    if derived["activeCanary"] is not None:
        source = derived["activeCanary"]
        before, after = source["afterPolicy"], derived["committedPolicy"]
        proposal_id = source["proposalId"]
    elif derived["activeStage"] is None and latest_transition is not None and latest_transition["eventType"] == "commit":
        before, after = latest_transition["afterPolicy"], latest_transition["beforePolicy"]
        proposal_id = latest_transition["proposalId"]
    else:
        raise ProjectError("there is no active canary or immediately previous committed policy to revert")
    patches = [
        {
            "target": target,
            "operation": "replace",
            "valueType": "integer",
            "fromValue": before[target],
            "toValue": after[target],
            "constraintCode": "restore-previous-committed",
        }
        for target in sorted(DEFAULT_POLICY)
        if before[target] != after[target]
    ]
    _patches(patches, tightening=False)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "operation": AUTHORIZED_OPERATIONS["revert"],
        "proposalId": proposal_id,
        "previousEventSha256": store["head"]["eventSha256"],
        "basePolicyFingerprint": _canonical_digest(fingerprint_material(resolved)),
        "beforePolicy": before,
        "afterPolicy": after,
        "patches": patches,
        "canary": None,
        "evidenceHostCompletionIds": [],
    }


def revert(root: str | Path, receipt_id: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    existing = _existing_event_for_receipt(resolved, receipt_id, "revert")
    if existing is not None:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "existing",
            "event": existing,
            "receipt": receipts.get(resolved, receipt_id),
        }
    action = revert_action(resolved)
    receipt = _receipt_for_action(resolved, action, receipt_id)
    event = _append(resolved, {
        "eventType": "revert",
        "proposalId": action["proposalId"],
        "previousEventSha256": action["previousEventSha256"],
        "basePolicyFingerprint": action["basePolicyFingerprint"],
        "beforePolicy": action["beforePolicy"],
        "afterPolicy": action["afterPolicy"],
        "patches": action["patches"],
        "canary": None,
        "authorizationReceiptId": receipt["id"],
        "evidenceHostCompletionIds": [],
        "idempotencyKeySha256": _canonical_digest({**action, "authorizationReceiptId": receipt["id"]}),
    })
    return {"schemaVersion": SCHEMA_VERSION, "state": "reverted", "event": event, "receipt": receipt}
