"""Reviewable executable-acceptance proposals bound to current work.

Proposals describe tests or invariants. HelloDev never writes the target file,
executes the command, or treats review as verification evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from . import acceptance, acceptance_planning, contracts, lifecycle, verification
from .command_rendering import command_line
from .context_runtime.native import snapshot as repository_snapshot
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


SCHEMA_VERSION = 1
MAX_PROPOSALS = 100
PROPOSAL_ID = re.compile(r"^acceptance-proposal-[0-9]{4,}$")
DECISIONS = {"approve", "reject"}
MODES = {"red", "characterization", "invariant"}


def _path(root: Path) -> Path:
    load_config(root)
    path = ProjectPaths(root).state_dir / "executable-acceptance.json"
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ProjectError("executable acceptance store is unsafe")
    return path


def _load(root: Path) -> dict[str, Any]:
    path = _path(root)
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "proposals": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid executable acceptance store: {error}") from error
    proposals = value.get("proposals") if isinstance(value, dict) and value.get("schemaVersion") == SCHEMA_VERSION else None
    if not isinstance(proposals, list) or len(proposals) > MAX_PROPOSALS:
        raise ProjectError("invalid executable acceptance store schema")
    for item in proposals:
        required = {
            "id", "cycleId", "workItemId", "requirementsSha256", "mode", "targetPath",
            "targetBaselineSha256", "command", "commandSha256", "repositorySnapshot",
            "summary", "state", "reviewReason", "createdAt", "reviewedAt", "proposalSha256",
        }
        if not isinstance(item, dict) or set(item) != required or PROPOSAL_ID.fullmatch(str(item.get("id"))) is None:
            raise ProjectError("invalid executable acceptance proposal")
        if item.get("mode") not in MODES or item.get("state") not in {"proposed", "approved", "rejected"}:
            raise ProjectError("invalid executable acceptance proposal state")
        for field in ("requirementsSha256", "commandSha256", "repositorySnapshot", "proposalSha256"):
            if not isinstance(item.get(field), str) or re.fullmatch(r"[0-9a-f]{64}", item[field]) is None:
                raise ProjectError("invalid executable acceptance proposal digest")
        if not all(isinstance(item.get(field), str) and item[field] for field in ("cycleId", "workItemId", "targetPath", "command", "summary", "createdAt")):
            raise ProjectError("invalid executable acceptance proposal identity")
        if item["targetBaselineSha256"] is not None and re.fullmatch(r"[0-9a-f]{64}", str(item["targetBaselineSha256"])) is None:
            raise ProjectError("invalid executable acceptance target baseline")
        if item["state"] == "proposed" and item["reviewedAt"] is not None:
            raise ProjectError("invalid executable acceptance review state")
        if item["state"] != "proposed" and not isinstance(item["reviewedAt"], str):
            raise ProjectError("invalid executable acceptance review state")
    return {"schemaVersion": SCHEMA_VERSION, "proposals": proposals}


def _single_line(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ProjectError(f"{label} must be a string")
    selected = value.strip()
    if not selected or len(selected) > maximum or any(char in selected for char in "\r\n\x00"):
        raise ProjectError(f"{label} must be one non-empty line of at most {maximum} characters")
    return selected


def _relative_target(root: Path, value: str) -> tuple[str, str | None]:
    selected = _single_line(value.replace("\\", "/"), "acceptance target path", 240)
    pure = PurePosixPath(selected)
    if pure.is_absolute() or selected.startswith("/") or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProjectError("acceptance target path must be a safe project-relative path")
    target = root.joinpath(*pure.parts)
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as error:
        raise ProjectError("acceptance target path escapes the project") from error
    if target.is_symlink() or target.exists() and not target.is_file():
        raise ProjectError("acceptance target path is unsafe")
    if not target.exists():
        return pure.as_posix(), None
    raw = target.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ProjectError("acceptance target file exceeds the 1 MiB proposal limit")
    return pure.as_posix(), hashlib.sha256(raw).hexdigest()


def _requirements_sha(contract: dict[str, Any]) -> str:
    source = contract["requirementsSource"]
    return source["sha256"]


def required(root: str | Path) -> bool:
    resolved = resolve_root(root)
    contract = acceptance.current(resolved)
    return contract is not None and contract["requirementsSource"]["state"] == "bound"


def propose(root: str | Path, mode: str, target_path: str, command: str, summary: str) -> dict[str, Any]:
    resolved = resolve_root(root)
    contract = acceptance.current(resolved)
    work = contracts.current_work_item(resolved)
    if contract is None or work is None:
        raise ProjectError("executable acceptance requires a current WorkItem and AcceptanceContract")
    selected_mode = mode.lower() if isinstance(mode, str) else ""
    if selected_mode not in MODES:
        raise ProjectError("executable acceptance mode must be red, characterization, or invariant")
    target, baseline = _relative_target(resolved, target_path)
    selected_command = verification.canonical_command(command)
    selected_summary = _single_line(summary, "acceptance proposal summary", 500)
    base = {
        "cycleId": lifecycle.status(resolved)["cycleId"],
        "workItemId": work["id"],
        "requirementsSha256": _requirements_sha(contract),
        "mode": selected_mode,
        "targetPath": target,
        "targetBaselineSha256": baseline,
        "command": selected_command,
        "commandSha256": hashlib.sha256(selected_command.encode("utf-8")).hexdigest(),
        "repositorySnapshot": repository_snapshot(resolved).snapshot_id,
        "summary": selected_summary,
    }
    proposal_sha = hashlib.sha256(
        json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with locked_state(resolved, "executable-acceptance"):
        store = _load(resolved)
        existing = next(
            (item for item in reversed(store["proposals"]) if item["proposalSha256"] == proposal_sha), None
        )
        if existing is not None:
            return {"schemaVersion": 1, "state": existing["state"], "proposal": existing, "idempotent": True}
        highest = max((int(item["id"].removeprefix("acceptance-proposal-")) for item in store["proposals"]), default=0)
        item = {
            "id": f"acceptance-proposal-{highest + 1:04d}",
            **base,
            "state": "proposed",
            "reviewReason": None,
            "createdAt": utc_now(),
            "reviewedAt": None,
            "proposalSha256": proposal_sha,
        }
        store["proposals"].append(item)
        store["proposals"] = store["proposals"][-MAX_PROPOSALS:]
        write_json(_path(resolved), store)
    return {
        "schemaVersion": 1,
        "state": "proposed",
        "proposal": item,
        "reviewCommand": command_line(resolved, "acceptance", "review", item["id"], "--decision", "approve"),
        "executionPerformed": False,
        "testFileWritten": False,
        "hostCommandExecuted": False,
        "gatePlan": acceptance_planning.build(resolved),
    }


def review(root: str | Path, proposal_id: str, decision: str, reason: str | None = None) -> dict[str, Any]:
    resolved = resolve_root(root)
    if PROPOSAL_ID.fullmatch(proposal_id or "") is None or decision not in DECISIONS:
        raise ProjectError("invalid executable acceptance review")
    selected_reason = None if reason is None else _single_line(reason, "review reason", 500)
    with locked_state(resolved, "executable-acceptance"):
        store = _load(resolved)
        item = next((value for value in store["proposals"] if value["id"] == proposal_id), None)
        if item is None:
            raise ProjectError(f"executable acceptance proposal not found: {proposal_id}")
        current_contract = acceptance.current(resolved)
        current_work = contracts.current_work_item(resolved)
        if current_contract is None or current_work is None or item["cycleId"] != lifecycle.status(resolved)["cycleId"]:
            raise ProjectError("executable acceptance proposal is not bound to the current cycle")
        if item["workItemId"] != current_work["id"] or item["requirementsSha256"] != _requirements_sha(current_contract):
            raise ProjectError("executable acceptance proposal is stale for current work")
        if item["state"] != "proposed":
            if item["state"] == ("approved" if decision == "approve" else "rejected"):
                return {"schemaVersion": 1, "state": item["state"], "proposal": item, "idempotent": True}
            raise ProjectError("executable acceptance proposal has already been reviewed")
        _, current_baseline = _relative_target(resolved, item["targetPath"])
        if current_baseline != item["targetBaselineSha256"]:
            raise ProjectError("executable acceptance target changed before review; submit a new proposal")
        item["state"] = "approved" if decision == "approve" else "rejected"
        item["reviewReason"] = selected_reason
        item["reviewedAt"] = utc_now()
        write_json(_path(resolved), store)
    return {
        "schemaVersion": 1,
        "state": item["state"],
        "proposal": item,
        "executionPerformed": False,
        "verificationEvidenceCreated": False,
        "gatePlan": acceptance_planning.build(resolved),
    }


def status(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    contract = acceptance.current(resolved)
    work = contracts.current_work_item(resolved)
    if contract is None or work is None:
        return {"schemaVersion": 1, "state": "not-bound", "required": False, "satisfied": True, "proposal": None}
    proposals = [
        item for item in _load(resolved)["proposals"]
        if item["cycleId"] == lifecycle.status(resolved)["cycleId"]
        and item["workItemId"] == work["id"]
        and item["requirementsSha256"] == _requirements_sha(contract)
    ]
    latest = proposals[-1] if proposals else None
    is_required = required(resolved)
    approved = next((item for item in reversed(proposals) if item["state"] == "approved"), None)
    if approved is not None:
        state, next_command = "approved", None
    elif latest is not None and latest["state"] == "proposed":
        state = "review-required"
        next_command = command_line(resolved, "acceptance", "review", latest["id"], "--decision", "approve")
    else:
        state = "proposal-required" if is_required else "optional"
        next_command = command_line(
            resolved, "acceptance", "propose", "--mode", "<red|characterization|invariant>",
            "--path", "<project-relative-test-or-invariant-file>", "--command", "<host-test-command>",
            "--summary", "<expected-behavior>",
        ) if is_required else None
    return {
        "schemaVersion": 1,
        "state": state,
        "required": is_required,
        "satisfied": not is_required or approved is not None,
        "proposal": approved or latest,
        "next": next_command,
        "reviewIsVerification": False,
        "hostCommandExecuted": False,
        "testFileWritten": False,
        "gatePlan": acceptance_planning.build(resolved),
    }


def require_approved(root: str | Path, intent: str) -> None:
    value = status(root)
    if value["required"] and not value["satisfied"]:
        raise ProjectError(f"{intent} blocked: executable acceptance is {value['state']}. Next: {value['next']}")


__all__ = ["propose", "required", "require_approved", "review", "status"]
