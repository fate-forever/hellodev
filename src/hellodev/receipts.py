"""Strict, privacy-preserving receipts for operations, evidence, and policy."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json
from .state_lock import locked_state


ReceiptKind = Literal["command", "test", "gate", "verification", "policy"]
AuthorizationProfile = Literal["strict", "trusted-local", "autopilot-read"]
AuthorizationMode = Literal["token-required", "lease-allowed", "profile-auto"]

STORE_SCHEMA_VERSION = 3
RECEIPT_ID_PATTERN = re.compile(r"^receipt-[0-9]{4,}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RECEIPT_KINDS = {"command", "test", "gate", "verification", "policy"}
PROFILES = {"strict", "trusted-local", "autopilot-read"}
AUTHORIZATION_MODES = {"token-required", "lease-allowed", "profile-auto"}
ADAPTERS_BY_KIND = {
    "command": {"trellis", "nocturne"},
    "test": {"trellis"},
    "gate": {"trellis"},
    "verification": {"hellodev"},
    "policy": {"hellodev"},
}
V2_COMMON_FIELDS = {
    "id",
    "kind",
    "adapter",
    "operation",
    "risk",
    "outcome",
    "requestSha256",
    "resultSha256",
    "recordedAt",
}
AUDIT_FIELDS = {"profileUsed", "authorizationMode"}
COMMON_FIELDS = V2_COMMON_FIELDS | AUDIT_FIELDS
VERIFICATION_FIELDS = {"subjectReceiptId", "evidenceSha256"}
EVIDENCE_BINDING_FIELD = "evidenceBindingSha256"
LEGACY_V1_FIELDS = V2_COMMON_FIELDS - {"kind"}


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def payload_sha256(value: Any) -> str:
    """Return the canonical digest used by privacy-preserving receipt fields."""
    return _digest(value)


def _validate_operation(operation: Any) -> None:
    if (
        not isinstance(operation, str)
        or not operation
        or len(operation) > 80
        or any(character in operation for character in "\r\n\x00")
    ):
        raise ProjectError("receipt operation is invalid")


def _validate_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ProjectError("invalid HelloDev receipt entry")
    kind = receipt.get("kind")
    if not isinstance(kind, str) or kind not in RECEIPT_KINDS:
        raise ProjectError("receipt kind must be command, test, gate, verification, or policy")
    expected_fields = COMMON_FIELDS | (VERIFICATION_FIELDS if kind == "verification" else set())
    if "leaseSha256" in receipt:
        expected_fields = expected_fields | {"leaseSha256"}
    if EVIDENCE_BINDING_FIELD in receipt:
        expected_fields = expected_fields | {EVIDENCE_BINDING_FIELD}
    if set(receipt) != expected_fields:
        raise ProjectError("invalid HelloDev receipt fields")
    receipt_id = receipt.get("id")
    if not isinstance(receipt_id, str) or RECEIPT_ID_PATTERN.fullmatch(receipt_id) is None:
        raise ProjectError("receipt id must use the form receipt-0001")
    adapter = receipt.get("adapter")
    if not isinstance(adapter, str) or adapter not in ADAPTERS_BY_KIND[kind]:
        raise ProjectError(f"receipt adapter is incompatible with kind {kind}")
    _validate_operation(receipt.get("operation"))
    risk = receipt.get("risk")
    if not isinstance(risk, str) or risk not in {"read", "write"}:
        raise ProjectError("receipt risk must be read or write")
    if kind == "verification" and risk != "read":
        raise ProjectError("verification receipts must use read risk")
    if kind == "policy" and risk != "write":
        raise ProjectError("policy receipts must use write risk")
    outcome = receipt.get("outcome")
    if not isinstance(outcome, str) or outcome not in {"succeeded", "failed"}:
        raise ProjectError("receipt outcome must be succeeded or failed")
    for field in ("requestSha256", "resultSha256"):
        digest = receipt.get(field)
        if not isinstance(digest, str) or DIGEST_PATTERN.fullmatch(digest) is None:
            raise ProjectError(f"receipt {field} must be a lowercase SHA-256 digest")
    recorded_at = receipt.get("recordedAt")
    if not isinstance(recorded_at, str) or TIMESTAMP_PATTERN.fullmatch(recorded_at) is None:
        raise ProjectError("receipt recordedAt must be a UTC timestamp")
    try:
        parsed_timestamp = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProjectError("receipt recordedAt must be a UTC timestamp") from error
    if parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp):
        raise ProjectError("receipt recordedAt must be a UTC timestamp")
    profile = receipt.get("profileUsed")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ProjectError("receipt profileUsed is invalid")
    mode = receipt.get("authorizationMode")
    if not isinstance(mode, str) or mode not in AUTHORIZATION_MODES:
        raise ProjectError("receipt authorizationMode is invalid")
    lease_sha256 = receipt.get("leaseSha256")
    if mode == "lease-allowed":
        if profile != "trusted-local":
            raise ProjectError("lease-authorized receipts must use trusted-local")
        if not isinstance(lease_sha256, str) or DIGEST_PATTERN.fullmatch(lease_sha256) is None:
            raise ProjectError("lease-authorized receipts require leaseSha256")
    elif lease_sha256 is not None:
        raise ProjectError("leaseSha256 is allowed only for lease-authorized receipts")
    if mode == "profile-auto" and profile != "autopilot-read":
        raise ProjectError("profile-auto receipts must use autopilot-read")
    if kind == "policy" and mode != "token-required":
        raise ProjectError("policy receipts must use token-required authorization")
    if kind == "verification":
        subject = receipt.get("subjectReceiptId")
        if not isinstance(subject, str) or RECEIPT_ID_PATTERN.fullmatch(subject) is None:
            raise ProjectError("verification subject receipt id is invalid")
        evidence_digest = receipt.get("evidenceSha256")
        if not isinstance(evidence_digest, str) or DIGEST_PATTERN.fullmatch(evidence_digest) is None:
            raise ProjectError("verification evidence must be a lowercase SHA-256 digest")
    binding_digest = receipt.get(EVIDENCE_BINDING_FIELD)
    if binding_digest is not None:
        if kind not in {"gate", "test"}:
            raise ProjectError("only gate or test receipts can bind WorkItem evidence")
        if not isinstance(binding_digest, str) or DIGEST_PATTERN.fullmatch(binding_digest) is None:
            raise ProjectError("receipt evidenceBindingSha256 must be a lowercase SHA-256 digest")
    return receipt


def _validate_store_root(store: dict[str, Any], schema_version: int) -> list[Any]:
    raw_receipts = store.get("receipts")
    if (
        set(store) != {"schemaVersion", "receipts"}
        or type(store.get("schemaVersion")) is not int
        or store["schemaVersion"] != schema_version
        or not isinstance(raw_receipts, list)
    ):
        raise ProjectError("invalid HelloDev receipt store schema")
    return raw_receipts


def _normalize_v1_store(store: dict[str, Any]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for raw in _validate_store_root(store, 1):
        if not isinstance(raw, dict) or set(raw) != LEGACY_V1_FIELDS:
            raise ProjectError("invalid legacy HelloDev receipt fields")
        normalized.append(
            _validate_receipt(
                {
                    **raw,
                    "kind": "command",
                    "profileUsed": "strict",
                    "authorizationMode": "token-required",
                }
            )
        )
    return {"schemaVersion": STORE_SCHEMA_VERSION, "receipts": normalized}


def _normalize_v2_store(store: dict[str, Any]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for raw in _validate_store_root(store, 2):
        if not isinstance(raw, dict):
            raise ProjectError("invalid schema-v2 HelloDev receipt entry")
        kind = raw.get("kind")
        expected = V2_COMMON_FIELDS | (VERIFICATION_FIELDS if kind == "verification" else set())
        if set(raw) != expected:
            raise ProjectError("invalid schema-v2 HelloDev receipt fields")
        normalized.append(
            _validate_receipt(
                {
                    **raw,
                    "profileUsed": "strict",
                    "authorizationMode": "token-required",
                }
            )
        )
    return {"schemaVersion": STORE_SCHEMA_VERSION, "receipts": normalized}


def _load(root: Path) -> dict[str, Any]:
    load_config(root)
    path = ProjectPaths(root).receipts_file
    if not path.exists():
        return {"schemaVersion": STORE_SCHEMA_VERSION, "receipts": []}
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev receipt store")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev receipt store: {error}") from error
    if not isinstance(store, dict) or type(store.get("schemaVersion")) is not int:
        raise ProjectError("invalid HelloDev receipt store schema")
    schema_version = store["schemaVersion"]
    if schema_version == 1:
        store = _normalize_v1_store(store)
    elif schema_version == 2:
        store = _normalize_v2_store(store)
    elif schema_version != STORE_SCHEMA_VERSION:
        raise ProjectError("invalid HelloDev receipt store schema")
    raw_receipts = _validate_store_root(store, STORE_SCHEMA_VERSION)
    validated = [_validate_receipt(receipt) for receipt in raw_receipts]
    ids = [receipt["id"] for receipt in validated]
    if len(ids) != len(set(ids)):
        raise ProjectError("duplicate receipt id in HelloDev receipt store")
    return {"schemaVersion": STORE_SCHEMA_VERSION, "receipts": validated}


def _next_id(receipt_list: list[dict[str, Any]]) -> str:
    highest = max(
        (int(receipt["id"].removeprefix("receipt-")) for receipt in receipt_list),
        default=0,
    )
    return f"receipt-{highest + 1:04d}"


def record(
    root: Path,
    adapter: str,
    operation: str,
    risk: str,
    request: Any,
    result: Any,
    succeeded: bool,
    *,
    kind: ReceiptKind = "command",
    subject_receipt_id: str | None = None,
    evidence_sha256: str | None = None,
    profile_used: AuthorizationProfile | None = None,
    authorization_mode: AuthorizationMode = "token-required",
    lease_sha256: str | None = None,
    evidence_binding: Any | None = None,
) -> dict[str, Any]:
    if not isinstance(succeeded, bool):
        raise ProjectError("receipt succeeded must be a boolean")
    _validate_operation(operation)
    if not isinstance(kind, str) or kind not in RECEIPT_KINDS:
        raise ProjectError("receipt kind must be command, test, gate, verification, or policy")
    if not isinstance(adapter, str) or adapter not in ADAPTERS_BY_KIND[kind]:
        raise ProjectError(f"receipt adapter is incompatible with kind {kind}")
    if not isinstance(risk, str) or risk not in {"read", "write"}:
        raise ProjectError("receipt risk must be read or write")
    if kind == "verification":
        if risk != "read":
            raise ProjectError("verification receipts must use read risk")
        if subject_receipt_id is None or RECEIPT_ID_PATTERN.fullmatch(subject_receipt_id) is None:
            raise ProjectError("verification subject receipt id is invalid")
        if evidence_sha256 is None or DIGEST_PATTERN.fullmatch(evidence_sha256) is None:
            raise ProjectError("verification evidence must be a lowercase SHA-256 digest")
    elif subject_receipt_id is not None or evidence_sha256 is not None:
        raise ProjectError("only verification receipts can bind a subject or evidence digest")
    if evidence_binding is not None and kind not in {"gate", "test"}:
        raise ProjectError("only gate or test receipts can bind WorkItem evidence")
    with locked_state(root, "receipts"):
        store = _load(root)
        if profile_used is None:
            configured_profile = load_config(root).get("authorizationProfile", "strict")
            profile_used = configured_profile if isinstance(configured_profile, str) else "strict"
        receipt: dict[str, Any] = {
            "id": _next_id(store["receipts"]),
            "kind": kind,
            "adapter": adapter,
            "operation": operation,
            "risk": risk,
            "outcome": "succeeded" if succeeded else "failed",
            "requestSha256": _digest(request),
            "resultSha256": _digest(result),
            "recordedAt": utc_now(),
            "profileUsed": profile_used,
            "authorizationMode": authorization_mode,
        }
        if kind == "verification":
            receipt["subjectReceiptId"] = subject_receipt_id
            receipt["evidenceSha256"] = evidence_sha256
        if lease_sha256 is not None:
            receipt["leaseSha256"] = lease_sha256
        if evidence_binding is not None:
            receipt[EVIDENCE_BINDING_FIELD] = _digest(evidence_binding)
        _validate_receipt(receipt)
        store["receipts"].append(receipt)
        write_json(ProjectPaths(root).receipts_file, store)
        return receipt


def record_verification(
    root: Path,
    subject_receipt_id: str,
    evidence: str,
) -> dict[str, Any]:
    normalized = evidence.strip()
    if not normalized or len(evidence) > 2_000:
        raise ProjectError("verification evidence must be non-empty and 2000 characters or fewer")
    subject = get(root, subject_receipt_id)
    if subject["outcome"] != "succeeded":
        raise ProjectError("cannot verify a failed receipt")
    if subject["kind"] == "verification":
        raise ProjectError("a verification receipt cannot verify another verification receipt")
    evidence_sha256 = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    return record(
        root,
        "hellodev",
        "receipt.verify",
        "read",
        {"subjectReceiptId": subject_receipt_id, "evidenceSha256": evidence_sha256},
        {"subjectOutcome": subject["outcome"], "verified": True},
        True,
        kind="verification",
        subject_receipt_id=subject_receipt_id,
        evidence_sha256=evidence_sha256,
        profile_used=subject["profileUsed"],
        authorization_mode=subject["authorizationMode"],
        lease_sha256=subject.get("leaseSha256"),
    )


def get(root: Path, receipt_id: str) -> dict[str, Any]:
    if not isinstance(receipt_id, str) or RECEIPT_ID_PATTERN.fullmatch(receipt_id) is None:
        raise ProjectError("receipt id must use the form receipt-0001")
    for receipt in _load(root)["receipts"]:
        if receipt["id"] == receipt_id:
            return receipt
    raise ProjectError(f"receipt not found: {receipt_id}")


def list_receipts(root: Path) -> list[dict[str, Any]]:
    return list(_load(root)["receipts"])
