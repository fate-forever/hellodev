"""Explicit cross-adapter Saga state; no claim of atomic rollback."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from . import receipts
from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json
from .state_lock import locked_state


SAGA_ID_PATTERN = re.compile(r"^saga-[0-9]{4,}$")
PHASES = {
    "trellis-pending",
    "trellis-executed",
    "trellis-verified",
    "nocturne-executed",
    "completed",
    "partial",
    "closed",
}
TRELLIS_EVIDENCE_KINDS = {"gate", "test"}


def _path(root: Path, saga_id: str) -> Path:
    if not SAGA_ID_PATTERN.fullmatch(saga_id):
        raise ProjectError("saga id must use the form saga-0001")
    return ProjectPaths(root).sagas_dir / f"{saga_id}.json"


def _load(root: Path, saga_id: str) -> dict[str, Any]:
    load_config(root)
    path = _path(root, saga_id)
    if not path.is_file() or path.is_symlink():
        raise ProjectError(f"saga not found: {saga_id}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev saga state: {error}") from error
    if (
        not isinstance(state, dict)
        or type(state.get("schemaVersion")) is not int
        or state["schemaVersion"] != 1
        or state.get("id") != saga_id
        or state.get("phase") not in PHASES
        or not isinstance(state.get("steps"), list)
    ):
        raise ProjectError("invalid HelloDev saga state schema")
    if "requiredTrellisEvidenceKinds" not in state:
        # Old Saga files remain readable, but their generic command history
        # cannot be promoted to trusted typed evidence.
        state = {
            **state,
            "requiredTrellisEvidenceKinds": ["gate", "test"],
            "legacyEvidenceContract": True,
        }
    if state.get("requiredTrellisEvidenceKinds") != ["gate", "test"]:
        raise ProjectError("invalid HelloDev saga evidence contract")
    return state


def _persist(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    state["updatedAt"] = utc_now()
    write_json(_path(root, state["id"]), state)
    return state


def _next_id(root: Path) -> str:
    paths = ProjectPaths(root)
    highest = 0
    for path in paths.sagas_dir.glob("saga-*.json"):
        if path.is_symlink():
            raise ProjectError(f"refusing symlink saga state: {path.name}")
        match = SAGA_ID_PATTERN.fullmatch(path.stem)
        if match:
            highest = max(highest, int(path.stem.removeprefix("saga-")))
    return f"saga-{highest + 1:04d}"


def create(root: Path, title: str) -> dict[str, Any]:
    normalized = title.strip()
    if not normalized or "\n" in normalized or "\r" in normalized or len(normalized) > 160:
        raise ProjectError("saga title must be a non-empty single line of 160 characters or fewer")
    with locked_state(root, "sagas"):
        load_config(root)
        paths = ProjectPaths(root)
        paths.sagas_dir.mkdir(exist_ok=True)
        saga_id = _next_id(root)
        now = utc_now()
        state = {
            "schemaVersion": 1,
            "id": saga_id,
            "title": normalized,
            "phase": "trellis-pending",
            "requiredTrellisEvidenceKinds": ["gate", "test"],
            "createdAt": now,
            "updatedAt": now,
            "steps": [],
        }
        write_json(_path(root, saga_id), state)
        return state


def status(root: Path, saga_id: str) -> dict[str, Any]:
    return _load(root, saga_id)


def list_sagas(root: Path) -> list[dict[str, Any]]:
    """Return Saga states in a stable newest-first order."""
    load_config(root)
    directory = ProjectPaths(root).sagas_dir
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ProjectError("refusing unsafe HelloDev Saga directory")
    states = [_load(root, path.stem) for path in sorted(directory.glob("saga-*.json"))]
    return sorted(
        states,
        key=lambda item: (str(item.get("updatedAt", "")), str(item["id"])),
        reverse=True,
    )


def _append_step(state: dict[str, Any], name: str, receipt_id: str) -> None:
    state["steps"] = [
        *state["steps"],
        {"name": name, "receiptId": receipt_id, "at": utc_now()},
    ]


def _require_trellis_evidence(receipt: dict[str, Any]) -> None:
    if receipt["adapter"] != "trellis" or receipt["kind"] not in TRELLIS_EVIDENCE_KINDS:
        raise ProjectError("a saga requires a typed Trellis gate or test receipt")


def _require_nocturne_command(receipt: dict[str, Any]) -> None:
    if (
        receipt["adapter"] != "nocturne"
        or receipt["kind"] != "command"
        or receipt["risk"] != "write"
    ):
        raise ProjectError("a saga requires a Nocturne write command receipt at this step")


def attach(root: Path, saga_id: str, receipt_id: str) -> dict[str, Any]:
    with locked_state(root, "sagas"):
        state = _load(root, saga_id)
        if state.get("legacyEvidenceContract"):
            raise ProjectError("legacy Saga cannot be continued under typed evidence rules; create a new Saga")
        receipt = receipts.get(root, receipt_id)
        if state["phase"] == "trellis-pending":
            _require_trellis_evidence(receipt)
            if receipt["outcome"] != "succeeded":
                state["phase"] = "partial"
                _append_step(state, "failed-trellis-evidence", receipt_id)
                return _persist(root, state)
            state["phase"] = "trellis-executed"
            state["trellisEvidence"] = {
                "kind": receipt["kind"],
                "receiptId": receipt_id,
            }
            _append_step(state, "trellis-evidence", receipt_id)
            return _persist(root, state)
        if state["phase"] == "trellis-verified":
            _require_nocturne_command(receipt)
            if receipt["outcome"] != "succeeded":
                state["phase"] = "partial"
                _append_step(state, "failed-nocturne-operation", receipt_id)
                return _persist(root, state)
            state["phase"] = "nocturne-executed"
            _append_step(state, "nocturne-executed", receipt_id)
            return _persist(root, state)
        raise ProjectError("receipt cannot be attached in the current saga phase")


def attach_verified_evidence(root: Path, saga_id: str, receipt_id: str) -> dict[str, Any]:
    """Attach evidence that already has a valid verification receipt.

    This avoids asking the user to re-enter verification text during the
    unified remember flow. It does not weaken the evidence contract: both the
    typed Trellis receipt and its separately stored verification link must
    already exist and match.
    """
    with locked_state(root, "sagas"):
        state = _load(root, saga_id)
        if state.get("legacyEvidenceContract"):
            raise ProjectError("legacy Saga cannot be continued under typed evidence rules; create a new Saga")
        if state["phase"] != "trellis-pending":
            raise ProjectError("saga is not ready for verified Trellis evidence")
        evidence = receipts.get(root, receipt_id)
        _require_trellis_evidence(evidence)
        if evidence["outcome"] != "succeeded":
            raise ProjectError("cannot attach failed Trellis evidence")
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
            raise ProjectError("verified Trellis evidence requires a matching verification receipt")
        state["trellisEvidence"] = {"kind": evidence["kind"], "receiptId": receipt_id}
        state["trellisVerification"] = {
            "evidenceKind": evidence["kind"],
            "subjectReceiptId": receipt_id,
            "verificationReceiptId": verification["id"],
            "evidenceSha256": verification["evidenceSha256"],
            "at": utc_now(),
        }
        state["phase"] = "trellis-verified"
        _append_step(state, "trellis-evidence", receipt_id)
        _append_step(state, "trellis-verified", verification["id"])
        return _persist(root, state)


def _verify_trellis_step(
    root: Path,
    state: dict[str, Any],
    receipt_id: str,
    evidence: str,
) -> dict[str, Any]:
    latest = state["steps"][-1] if state["steps"] else None
    if (
        not isinstance(latest, dict)
        or latest.get("name") != "trellis-evidence"
        or latest.get("receiptId") != receipt_id
    ):
        raise ProjectError("verification receipt does not match the current Trellis evidence step")
    receipt = receipts.get(root, receipt_id)
    _require_trellis_evidence(receipt)
    if receipt["outcome"] != "succeeded":
        raise ProjectError("cannot verify failed Trellis evidence")
    verification = receipts.record_verification(root, receipt_id, evidence)
    state["trellisVerification"] = {
        "evidenceKind": receipt["kind"],
        "subjectReceiptId": receipt_id,
        "verificationReceiptId": verification["id"],
        "evidenceSha256": verification["evidenceSha256"],
        "at": utc_now(),
    }
    state["phase"] = "trellis-verified"
    _append_step(state, "trellis-verified", verification["id"])
    return _persist(root, state)


def _verify_nocturne_step(
    root: Path,
    state: dict[str, Any],
    receipt_id: str,
    evidence: str,
) -> dict[str, Any]:
    latest = state["steps"][-1] if state["steps"] else None
    if (
        not isinstance(latest, dict)
        or latest.get("name") != "nocturne-executed"
        or latest.get("receiptId") != receipt_id
    ):
        raise ProjectError("verification receipt does not match the current Nocturne step")
    receipt = receipts.get(root, receipt_id)
    _require_nocturne_command(receipt)
    if receipt["outcome"] != "succeeded":
        raise ProjectError("cannot verify a failed Nocturne receipt")
    verification = receipts.record_verification(root, receipt_id, evidence)
    state["nocturneVerification"] = {
        "subjectReceiptId": receipt_id,
        "verificationReceiptId": verification["id"],
        "evidenceSha256": verification["evidenceSha256"],
        "at": utc_now(),
    }
    state["phase"] = "completed"
    _append_step(state, "nocturne-verified", verification["id"])
    return _persist(root, state)


def verify(root: Path, saga_id: str, receipt_id: str, evidence: str) -> dict[str, Any]:
    if not evidence.strip() or len(evidence) > 2_000:
        raise ProjectError("verification evidence must be non-empty and 2000 characters or fewer")
    with locked_state(root, "sagas"):
        state = _load(root, saga_id)
        if state.get("legacyEvidenceContract"):
            raise ProjectError("legacy Saga cannot be continued under typed evidence rules; create a new Saga")
        if state["phase"] == "trellis-executed":
            return _verify_trellis_step(root, state, receipt_id, evidence)
        if state["phase"] == "nocturne-executed":
            return _verify_nocturne_step(root, state, receipt_id, evidence)
        raise ProjectError("saga is not awaiting verification")


def close(root: Path, saga_id: str) -> dict[str, Any]:
    """Close a non-completed recovery chain that has no unverified external write."""
    with locked_state(root, "sagas"):
        state = _load(root, saga_id)
        if state["phase"] == "closed":
            return {**state, "idempotent": True}
        if state["phase"] in {"completed", "nocturne-executed"}:
            raise ProjectError("Saga cannot close after an unverified or completed Nocturne write")
        state["closedFrom"] = state["phase"]
        state["phase"] = "closed"
        return _persist(root, state)


def require_trellis_write(root: Path, saga_id: str) -> None:
    """Fail before executing a generic write that cannot satisfy typed evidence."""
    if _load(root, saga_id)["phase"] != "trellis-pending":
        raise ProjectError("saga is not ready for Trellis evidence")
    raise ProjectError(
        "a generic Trellis write cannot satisfy a Saga; attach a successful gate or test receipt"
    )


def _validated_trellis_verification(root: Path, state: dict[str, Any]) -> None:
    evidence_link = state.get("trellisEvidence")
    verification_link = state.get("trellisVerification")
    if not isinstance(evidence_link, dict) or not isinstance(verification_link, dict):
        raise ProjectError("saga is missing typed Trellis verification evidence")
    evidence_receipt = receipts.get(root, str(evidence_link.get("receiptId", "")))
    _require_trellis_evidence(evidence_receipt)
    if evidence_receipt["outcome"] != "succeeded":
        raise ProjectError("saga Trellis evidence did not succeed")
    if evidence_link.get("kind") != evidence_receipt["kind"]:
        raise ProjectError("saga Trellis evidence kind does not match its receipt")
    verification_receipt = receipts.get(
        root, str(verification_link.get("verificationReceiptId", ""))
    )
    if (
        verification_receipt["kind"] != "verification"
        or verification_receipt["outcome"] != "succeeded"
        or verification_receipt["subjectReceiptId"] != evidence_receipt["id"]
        or verification_receipt["evidenceSha256"] != verification_link.get("evidenceSha256")
        or verification_link.get("subjectReceiptId") != evidence_receipt["id"]
        or verification_link.get("evidenceKind") != evidence_receipt["kind"]
    ):
        raise ProjectError("saga Trellis verification receipt is invalid")


def require_nocturne_write(root: Path, saga_id: str) -> None:
    state = _load(root, saga_id)
    if state.get("legacyEvidenceContract"):
        raise ProjectError("legacy Saga cannot be continued under typed evidence rules; create a new Saga")
    if state["phase"] != "trellis-verified":
        raise ProjectError(
            "saga requires successful, verified Trellis gate or test evidence before a Nocturne write"
        )
    _validated_trellis_verification(root, state)


def _command(*arguments: str) -> str:
    return subprocess.list2cmdline(["hellodev", *arguments])


def _latest_step_receipt(state: dict[str, Any], name: str) -> str | None:
    for step in reversed(state["steps"]):
        if isinstance(step, dict) and step.get("name") == name and isinstance(step.get("receiptId"), str):
            return step["receiptId"]
    return None


def next_step(root: Path, saga_id: str) -> dict[str, Any]:
    """Return the next safe Saga recovery action without executing adapters."""
    from . import contracts

    state = _load(root, saga_id)
    phase = state["phase"]
    base = {
        "schemaVersion": 1,
        "sagaId": saga_id,
        "phase": phase,
        "executionPerformed": False,
        "requiresInput": False,
    }
    if state.get("legacyEvidenceContract"):
        return {
            **base,
            "command": _command("receipt", "list"),
            "reasonCode": "saga-legacy-replacement-required",
            "reason": "This legacy Saga is inspectable but cannot continue under typed evidence rules; review receipts before creating a replacement.",
            "requiresInput": True,
        }
    if phase == "trellis-pending":
        work_item = contracts.current_work_item(root)
        if work_item is not None and work_item.get("backend") == "trellis":
            native_ref = work_item.get("nativeRef")
            if isinstance(native_ref, str) and native_ref:
                return {
                    **base,
                    "command": _command("do", "validate", "--task", native_ref),
                    "reasonCode": "saga-needs-trellis-evidence",
                    "reason": "Run validation for the current Trellis work item, then attach and verify its receipt.",
                }
        return {
            **base,
            "command": _command("gate", "status"),
            "reasonCode": "saga-needs-trellis-evidence",
            "reason": "A successful Trellis gate or test receipt is required before this Saga can continue.",
        }
    if phase == "trellis-executed":
        receipt_id = _latest_step_receipt(state, "trellis-evidence")
        if receipt_id is None:
            raise ProjectError("Saga Trellis evidence phase has no receipt")
        return {
            **base,
            "command": _command("receipt", "show", receipt_id),
            "reasonCode": "saga-trellis-verification-required",
            "reason": "Inspect the evidence receipt, then verify it with operator-supplied evidence.",
            "requiresInput": True,
            "followUpTemplate": _command(
                "saga", "verify", saga_id, receipt_id, "--evidence", "<operator evidence>"
            ),
        }
    if phase == "trellis-verified":
        proposal = contracts.proposal_for_saga(root, saga_id)
        if proposal is not None:
            return {
                **base,
                "command": _command("lesson", "show", str(proposal["id"])),
                "reasonCode": "saga-lesson-text-required",
                "reason": "Review the hash-only lesson proposal, then re-supply the original lesson to continue remember.",
                "requiresInput": True,
                "lessonProposalId": proposal["id"],
            }
        return {
            **base,
            "command": _command("saga", "status", saga_id),
            "reasonCode": "saga-nocturne-write-required",
            "reason": "The verified Saga needs the original lesson text before a Nocturne write can be prepared.",
            "requiresInput": True,
        }
    if phase == "nocturne-executed":
        receipt_id = _latest_step_receipt(state, "nocturne-executed")
        if receipt_id is None:
            raise ProjectError("Saga Nocturne phase has no receipt")
        return {
            **base,
            "command": _command("receipt", "show", receipt_id),
            "reasonCode": "saga-nocturne-verification-required",
            "reason": "Inspect the Nocturne receipt, then verify it with operator-supplied evidence.",
            "requiresInput": True,
            "followUpTemplate": _command(
                "saga", "verify", saga_id, receipt_id, "--evidence", "<operator evidence>"
            ),
        }
    if phase == "partial":
        return {
            **base,
            "command": _command("saga", "close", saga_id),
            "reasonCode": "saga-partial-review-required",
            "reason": "This Saga cannot continue automatically; inspect its receipts, then close it before starting a replacement Saga.",
            "requiresInput": True,
            "reviewCommand": _command("receipt", "list"),
        }
    if phase == "closed":
        return {
            **base,
            "command": _command("receipt", "list"),
            "reasonCode": "saga-closed",
            "reason": "The Saga is closed and no longer participates in automatic resume.",
        }
    return {
        **base,
        "command": _command("receipt", "list"),
        "reasonCode": "saga-completed",
        "reason": "The Saga is complete; inspect the audit receipts if needed.",
    }
