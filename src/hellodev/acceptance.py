"""Persistent acceptance contracts and host-verification projection."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

from . import contracts, guided_acceptance, lifecycle, trellis_execution, verification, workflow_projection
from .command_rendering import command_line
from .component_protocol import canonical_sha256
from .project import ProjectError, ProjectPaths, load_config, resolve_root, utc_now, write_json
from .state_lock import locked_state


STORE_SCHEMA_VERSION = 2
MAX_CONTRACTS = 100
MAX_REQUIREMENT_SOURCE_BYTES = 32 * 1024
MAX_REQUIREMENT_SOURCES = 100
MAX_COMPONENT_LEDGER_BYTES = 4 * 1024 * 1024
_CYCLE = re.compile(r"^cycle-[0-9]{4,}$")
_WORK_ITEM = re.compile(r"^work-[0-9]{4,}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_STATES = {"summary-only", "bound"}


def _single_line(value: str, field: str, limit: int) -> str:
    normalized = value.strip()
    if not normalized or "\n" in normalized or "\r" in normalized or len(normalized) > limit:
        raise ProjectError(f"{field} must be a non-empty single line of {limit} characters or fewer")
    return normalized


def _path(root: Path) -> Path:
    load_config(root)
    path = ProjectPaths(root).acceptance_file
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev acceptance store")
    return path


def _validate_source_metadata(value: Any) -> dict[str, Any]:
    fields = {"state", "kind", "sha256", "byteCount", "lineCount", "path"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ProjectError("invalid AcceptanceContract requirements source fields")
    if value.get("state") not in _SOURCE_STATES:
        raise ProjectError("invalid AcceptanceContract requirements source state")
    expected_kind = "project-file" if value["state"] == "bound" else "acceptance-only"
    if value.get("kind") != expected_kind:
        raise ProjectError("invalid AcceptanceContract requirements source kind")
    if not isinstance(value.get("sha256"), str) or _DIGEST.fullmatch(value["sha256"]) is None:
        raise ProjectError("invalid AcceptanceContract requirements source digest")
    if type(value.get("byteCount")) is not int or not 1 <= value["byteCount"] <= MAX_REQUIREMENT_SOURCE_BYTES:
        raise ProjectError("invalid AcceptanceContract requirements source byte count")
    if type(value.get("lineCount")) is not int or not 1 <= value["lineCount"] <= 2048:
        raise ProjectError("invalid AcceptanceContract requirements source line count")
    if value["state"] == "bound":
        if not isinstance(value.get("path"), str) or not value["path"] or len(value["path"]) > 512:
            raise ProjectError("invalid AcceptanceContract requirements source path")
    elif value.get("path") is not None:
        raise ProjectError("summary-only AcceptanceContract cannot have a requirements source path")
    return value


def _summary_source(criterion: str) -> dict[str, Any]:
    encoded = criterion.encode("utf-8")
    return {
        "state": "summary-only",
        "kind": "acceptance-only",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byteCount": len(encoded),
        "lineCount": 1,
        "path": None,
    }


def _validate(item: Any) -> dict[str, Any]:
    fields = {"cycleId", "workItemId", "goal", "acceptance", "requirementsSource", "createdAt"}
    if not isinstance(item, dict) or set(item) != fields:
        raise ProjectError("invalid AcceptanceContract fields")
    if not isinstance(item.get("cycleId"), str) or _CYCLE.fullmatch(item["cycleId"]) is None:
        raise ProjectError("invalid AcceptanceContract cycleId")
    if not isinstance(item.get("workItemId"), str) or _WORK_ITEM.fullmatch(item["workItemId"]) is None:
        raise ProjectError("invalid AcceptanceContract workItemId")
    _single_line(item.get("goal", ""), "acceptance goal", 512)
    _single_line(item.get("acceptance", ""), "acceptance criterion", 1000)
    _validate_source_metadata(item.get("requirementsSource"))
    if not isinstance(item.get("createdAt"), str):
        raise ProjectError("invalid AcceptanceContract createdAt")
    return item


def _load(root: Path) -> dict[str, Any]:
    path = _path(root)
    if not path.exists():
        return {"schemaVersion": STORE_SCHEMA_VERSION, "contracts": []}
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ProjectError("HelloDev acceptance store is unsafe")
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev acceptance store: {error}") from error
    if (
        not isinstance(store, dict)
        or set(store) != {"schemaVersion", "contracts"}
        or store.get("schemaVersion") not in {1, STORE_SCHEMA_VERSION}
        or not isinstance(store.get("contracts"), list)
        or len(store["contracts"]) > MAX_CONTRACTS
    ):
        raise ProjectError("invalid HelloDev acceptance store schema")
    if store["schemaVersion"] == 1:
        legacy_fields = {"cycleId", "workItemId", "goal", "acceptance", "createdAt"}
        migrated = []
        for item in store["contracts"]:
            if not isinstance(item, dict) or set(item) != legacy_fields:
                raise ProjectError("invalid legacy AcceptanceContract fields")
            migrated.append({**item, "requirementsSource": _summary_source(item.get("acceptance", ""))})
        contracts_value = [_validate(item) for item in migrated]
    else:
        contracts_value = [_validate(item) for item in store["contracts"]]
    identities = [(item["cycleId"], item["workItemId"]) for item in contracts_value]
    if len(identities) != len(set(identities)):
        raise ProjectError("duplicate AcceptanceContract identity")
    return {"schemaVersion": STORE_SCHEMA_VERSION, "contracts": contracts_value}


def _source_store(root: Path) -> dict[str, Any]:
    path = ProjectPaths(root).acceptance_sources_file
    if not path.exists():
        return {"schemaVersion": 1, "sources": []}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ProjectError("HelloDev acceptance source store is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev acceptance source store: {error}") from error
    sources = value.get("sources") if isinstance(value, dict) and value.get("schemaVersion") == 1 else None
    if not isinstance(sources, list) or len(sources) > MAX_REQUIREMENT_SOURCES:
        raise ProjectError("invalid HelloDev acceptance source store")
    for item in sources:
        if (
            not isinstance(item, dict)
            or set(item) != {"sha256", "text", "byteCount", "lineCount", "createdAt"}
            or not isinstance(item.get("sha256"), str)
            or _DIGEST.fullmatch(item["sha256"]) is None
            or not isinstance(item.get("text"), str)
            or len(item["text"].encode("utf-8")) != item.get("byteCount")
            or hashlib.sha256(item["text"].encode("utf-8")).hexdigest() != item["sha256"]
            or type(item.get("lineCount")) is not int
            or not isinstance(item.get("createdAt"), str)
        ):
            raise ProjectError("invalid HelloDev acceptance source entry")
    return {"schemaVersion": 1, "sources": sources}


def _read_requirement_source(root: Path, supplied: str) -> tuple[dict[str, Any], str]:
    if not isinstance(supplied, str) or not supplied.strip() or len(supplied) > 512:
        raise ProjectError("requirements file must be one project-relative path")
    relative = Path(supplied)
    if relative.is_absolute():
        raise ProjectError("requirements file must be project-relative")
    candidate = root.joinpath(relative)
    try:
        resolved = candidate.resolve(strict=True)
        normalized = resolved.relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise ProjectError("requirements file must be an existing project-relative file") from error
    cursor = root.resolve()
    for part in normalized.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ProjectError("refusing symlinked requirements file")
    if not resolved.is_file() or resolved.stat().st_size > MAX_REQUIREMENT_SOURCE_BYTES:
        raise ProjectError(f"requirements file must be UTF-8 and at most {MAX_REQUIREMENT_SOURCE_BYTES} bytes")
    raw = resolved.read_bytes()
    if not raw or b"\x00" in raw:
        raise ProjectError("requirements file must be non-empty UTF-8 text")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError("requirements file must be UTF-8 text") from error
    line_count = len(text.splitlines()) or 1
    metadata = {
        "state": "bound",
        "kind": "project-file",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byteCount": len(raw),
        "lineCount": line_count,
        "path": normalized.as_posix(),
    }
    return _validate_source_metadata(metadata), text


def _persist_requirement_source(root: Path, metadata: dict[str, Any], text: str) -> None:
    with locked_state(root, "acceptance-sources"):
        store = _source_store(root)
        existing = next((item for item in store["sources"] if item["sha256"] == metadata["sha256"]), None)
        if existing is None:
            store["sources"].append(
                {
                    "sha256": metadata["sha256"],
                    "text": text,
                    "byteCount": metadata["byteCount"],
                    "lineCount": metadata["lineCount"],
                    "createdAt": utc_now(),
                }
            )
            store["sources"] = store["sources"][-MAX_REQUIREMENT_SOURCES:]
            write_json(ProjectPaths(root).acceptance_sources_file, store)


def record(
    root: Path,
    work_item_id: str,
    goal: str,
    criterion: str | None,
    requirements_file: str | None = None,
) -> dict[str, Any] | None:
    if criterion is None:
        return None
    normalized_goal = _single_line(goal, "acceptance goal", 512)
    normalized_criterion = _single_line(criterion, "acceptance criterion", 1000)
    if requirements_file is None:
        source_metadata = _summary_source(normalized_criterion)
        source_text = None
    else:
        source_metadata, source_text = _read_requirement_source(root, requirements_file)
        _persist_requirement_source(root, source_metadata, source_text)
    cycle_id = lifecycle.status(root)["cycleId"]
    contracts.get_work_item(root, work_item_id)
    with locked_state(root, "acceptance"):
        store = _load(root)
        existing = next(
            (
                item
                for item in store["contracts"]
                if item["cycleId"] == cycle_id and item["workItemId"] == work_item_id
            ),
            None,
        )
        if existing is not None:
            if existing["goal"] != normalized_goal or existing["acceptance"] != normalized_criterion:
                raise ProjectError("active AcceptanceContract cannot be replaced; finish the cycle first")
            if source_metadata["state"] == "bound":
                current_source = existing["requirementsSource"]
                if current_source["state"] == "bound" and current_source != source_metadata:
                    raise ProjectError("active AcceptanceContract requirements source cannot be replaced; finish the cycle first")
                if current_source["state"] == "summary-only":
                    existing["requirementsSource"] = source_metadata
                    write_json(_path(root), store)
                    return {**existing, "upgraded": True}
            return {**existing, "idempotent": True}
        if len(store["contracts"]) >= MAX_CONTRACTS:
            store["contracts"] = store["contracts"][-(MAX_CONTRACTS - 1) :]
        item = {
            "cycleId": cycle_id,
            "workItemId": work_item_id,
            "goal": normalized_goal,
            "acceptance": normalized_criterion,
            "requirementsSource": source_metadata,
            "createdAt": utc_now(),
        }
        _validate(item)
        store["contracts"].append(item)
        write_json(_path(root), store)
        return item


def _requirements_integrity(root: Path, contract: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    source = contract["requirementsSource"]
    if source["state"] == "summary-only":
        return {
            "state": "source-required" if strict else "summary-only",
            "required": strict,
            "satisfied": not strict,
            "source": source,
            "exactSourcePersisted": False,
            "next": "hellodev do begin --requirements-file <project-relative-user-requirements-file>" if strict else None,
        }
    store = _source_store(root)
    persisted = next((item for item in store["sources"] if item["sha256"] == source["sha256"]), None)
    if persisted is None:
        return {"state": "source-store-missing", "required": True, "satisfied": False, "source": source, "exactSourcePersisted": False, "next": "hellodev status --verbose"}
    try:
        current, _ = _read_requirement_source(root, source["path"])
    except ProjectError:
        return {"state": "source-missing", "required": True, "satisfied": False, "source": source, "exactSourcePersisted": True, "next": "hellodev status --verbose"}
    if current["sha256"] != source["sha256"]:
        return {"state": "source-changed", "required": True, "satisfied": False, "source": source, "exactSourcePersisted": True, "next": "hellodev status --verbose"}
    return {"state": "bound", "required": True, "satisfied": True, "source": source, "exactSourcePersisted": True, "next": None}


def current(root: Path) -> dict[str, Any] | None:
    work_item = contracts.current_work_item(root)
    if work_item is None:
        return None
    cycle_id = lifecycle.status(root)["cycleId"]
    return next(
        (
            item
            for item in reversed(_load(root)["contracts"])
            if item["cycleId"] == cycle_id and item["workItemId"] == work_item["id"]
        ),
        None,
    )


def requirements_text(root: Path) -> str:
    """Return the current exact requirements after revalidating every binding."""

    contract = current(root)
    if contract is None or contract["requirementsSource"]["state"] != "bound":
        raise ProjectError("current AcceptanceContract has no exact requirements source")
    integrity = _requirements_integrity(root, contract, strict=True)
    if not integrity["satisfied"]:
        raise ProjectError(f"exact requirements source is not current: {integrity['state']}")
    source = contract["requirementsSource"]
    persisted = next(
        (item for item in _source_store(root)["sources"] if item["sha256"] == source["sha256"]),
        None,
    )
    if persisted is None:
        raise ProjectError("exact requirements source is missing from the bound source store")
    return persisted["text"]


def _context_evidence_store(root: Path) -> dict[str, Any]:
    path = ProjectPaths(root).acceptance_evidence_file
    if not path.exists():
        return {"schemaVersion": 1, "records": []}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ProjectError("HelloDev acceptance evidence store is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid acceptance evidence store: {error}") from error
    records = value.get("records") if isinstance(value, dict) and value.get("schemaVersion") == 1 else None
    if not isinstance(records, list) or len(records) > 100:
        raise ProjectError("invalid acceptance evidence store")
    for item in records:
        if (
            not isinstance(item, dict)
            or set(item) != {"task", "taskDigest", "valid", "source", "recordedAt"}
            or not isinstance(item.get("task"), str)
            or not isinstance(item.get("taskDigest"), str)
            or _DIGEST.fullmatch(item["taskDigest"]) is None
            or type(item.get("valid")) is not bool
            or item.get("source") not in {"component-protocol", "legacy-task-script"}
            or not isinstance(item.get("recordedAt"), str)
        ):
            raise ProjectError("invalid acceptance context evidence record")
    return {"schemaVersion": 1, "records": records}


def record_context_validation(root: Path, task: str, task_digest: str, valid: bool, source: str) -> dict[str, Any]:
    selected_task = _single_line(task, "Trellis context task", 96)
    if _DIGEST.fullmatch(task_digest) is None or type(valid) is not bool:
        raise ProjectError("invalid Trellis context validation evidence")
    if source not in {"component-protocol", "legacy-task-script"}:
        raise ProjectError("invalid Trellis context validation source")
    item = {
        "task": selected_task,
        "taskDigest": task_digest,
        "valid": valid,
        "source": source,
        "recordedAt": utc_now(),
    }
    with locked_state(root, "acceptance-evidence"):
        store = _context_evidence_store(root)
        store["records"] = [record for record in store["records"] if record["task"] != selected_task]
        store["records"].append(item)
        store["records"] = store["records"][-100:]
        write_json(ProjectPaths(root).acceptance_evidence_file, store)
    return item


def status(root: Path) -> dict[str, Any]:
    contract = current(root)
    base = {
        "schemaVersion": 1,
        "contract": contract,
        "sourceTrust": "host-asserted",
        "testExecutionPerformed": False,
        "rawOutputPersisted": False,
    }
    if contract is None:
        return {**base, "state": "not-declared", "required": False, "satisfied": False, "next": None}

    mode = workflow_projection.status(root)
    adaptive = trellis_execution.status(root, project_mode=mode) if mode.get("mode") == "trellis-native" else None
    profile = adaptive.get("profile") if isinstance(adaptive, dict) and adaptive.get("profile") else "standard"
    plan = trellis_execution.verification_plan(root, profile, contract["acceptance"])
    steps = plan["steps"]
    command = steps[0]["command"] if steps else None
    level = steps[0]["level"] if steps else (adaptive.get("requiredLevel") if adaptive else "T1") or "T1"
    scope = steps[0]["scope"] if steps else (adaptive.get("scope") if adaptive else "code") or "code"
    executor = "host"
    runtime = {
        "executor": executor,
        "cwd": str(root),
        "environmentHint": "project-runtime",
        "command": command,
        "level": level,
        "scope": scope,
    }
    if command is None:
        return {
            **base,
            "state": "command-required",
            "required": True,
            "satisfied": False,
            "runtime": runtime,
            "verificationPlan": {**plan, "currentStep": None, "satisfiedSteps": 0, "requiredSteps": 0},
            "next": command_line(
                root,
                "do",
                "verify",
                "--level",
                level,
                "--command",
                "<project acceptance command>",
                "--scope",
                scope,
            ),
        }
    projected_steps = []
    selected_step = None
    for index, step in enumerate(steps):
        evidence = verification.inspect(root, step["level"], step["command"], step["scope"])
        if len(steps) == 1 and adaptive is not None and adaptive.get("verificationState") == "covered-success":
            evidence = {
                **evidence,
                "state": "covered-success",
                "runRequired": False,
                "reasonCode": "single-step-small-change-covered-by-equal-or-stronger-host-evidence",
                "reusedRecordId": adaptive.get("reusedRecordId"),
                "commandEquivalenceClaimed": False,
            }
        projected = {**step, "index": index, "verification": evidence, "satisfied": evidence["state"] in {"reused-success", "covered-success"}}
        projected_steps.append(projected)
        if selected_step is None and not projected["satisfied"]:
            selected_step = projected
    if selected_step is None:
        selected_step = projected_steps[-1]
        evidence = selected_step["verification"]
        state = "satisfied"
    else:
        evidence = selected_step["verification"]
        state = {
            "blocked-unchanged-failure": "failed",
            "pending": "pending",
            "missing": "verification-required",
        }.get(evidence["state"], "verification-required")
    command, level, scope = selected_step["command"], selected_step["level"], selected_step["scope"]
    runtime = {**runtime, "command": command, "level": level, "scope": scope}
    action = verification.host_action(root, level, command, scope) if evidence.get("runRequired") is True else None
    return {
        **base,
        "state": state,
        "required": True,
        "satisfied": state == "satisfied",
        "runtime": runtime,
        **({"action": action} if action is not None else {}),
        "verification": evidence,
        "verificationPlan": {
            **plan,
            "steps": projected_steps,
            "currentStep": None if state == "satisfied" else selected_step["index"],
            "satisfiedSteps": sum(1 for step in projected_steps if step["satisfied"]),
            "requiredSteps": len(projected_steps),
            "allCurrentSnapshotRequired": True,
            "shellChainingPerformed": False,
        },
        "next": (
            "hellodev do check"
            if state == "satisfied"
            else command_line(root, "status", "--verbose")
            if state == "failed"
            else action["hostCommand"] if action is not None
            else command_line(root, "status", "--verbose")
        ),
    }


def _trellis_context_gate(root: Path) -> dict[str, Any]:
    work_item = contracts.current_work_item(root)
    if work_item is None or work_item.get("backend") != "trellis":
        return {
            "state": "not-applicable",
            "required": False,
            "satisfied": True,
            "evidenceClass": "context-validation",
            "qualityGateSatisfied": False,
            "next": None,
        }
    task = work_item["nativeRef"]
    task_record = root / ".trellis" / "tasks" / task / "task.json"
    if task_record.is_symlink():
        raise ProjectError("refusing symlinked Trellis task record for acceptance evidence")
    if not task_record.is_file() and task_record.parent.is_dir() and not task_record.parent.is_symlink():
        return {
            "state": "legacy-unavailable",
            "required": False,
            "satisfied": True,
            "evidenceClass": "context-validation",
            "qualityGateSatisfied": False,
            "task": task,
            "next": None,
        }
    if not task_record.is_file():
        return {
            "state": "native-task-missing",
            "required": True,
            "satisfied": False,
            "evidenceClass": "context-validation",
            "qualityGateSatisfied": False,
            "task": task,
            "next": "hellodev status --verbose",
        }
    if task_record.stat().st_size > 64 * 1024:
        raise ProjectError("Trellis task record is too large for acceptance evidence")
    try:
        record = json.loads(task_record.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid Trellis task record for acceptance evidence: {error}") from error
    if not isinstance(record, dict):
        raise ProjectError("invalid Trellis task record for acceptance evidence")
    current_digest = canonical_sha256(record)
    context_records = _context_evidence_store(root)["records"]
    recorded = next(
        (
            item
            for item in reversed(context_records)
            if item["task"] == task and item["taskDigest"] == current_digest
        ),
        None,
    )
    validated_before_completion = next(
        (item for item in reversed(context_records) if item["task"] == task and item["valid"] is True),
        None,
    )
    ledger_path = ProjectPaths(root).state_dir / "component-operations.json"
    matching: dict[str, Any] | None = None
    completion_transition: dict[str, Any] | None = None
    if ledger_path.exists():
        if ledger_path.is_symlink() or not ledger_path.is_file() or ledger_path.stat().st_size > MAX_COMPONENT_LEDGER_BYTES:
            raise ProjectError("HelloDev component operation ledger is unsafe")
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProjectError(f"invalid component operation ledger: {error}") from error
        operations = ledger.get("operations") if isinstance(ledger, dict) else None
        if not isinstance(operations, dict) or len(operations) > 256:
            raise ProjectError("invalid component operation ledger")
        for operation in reversed(list(operations.values())):
            result = operation.get("result") if isinstance(operation, dict) else None
            data = result.get("data") if isinstance(result, dict) else None
            result_task = data.get("task") if isinstance(data, dict) else None
            if (
                completion_transition is None
                and isinstance(result, dict)
                and result.get("ok") is True
                and result.get("action") == "task-complete"
                and isinstance(result_task, dict)
                and result_task.get("id") == task
                and result_task.get("status") == "completed"
                and result_task.get("digest") == current_digest
                and validated_before_completion is not None
                and data.get("previousDigest") == validated_before_completion["taskDigest"]
            ):
                completion_transition = result
            if (
                isinstance(result, dict)
                and result.get("ok") is True
                and result.get("action") == "task-validate"
                and isinstance(result_task, dict)
                and result_task.get("id") == task
                and result_task.get("digest") == current_digest
            ):
                matching = result
                break
    next_command = command_line(root, "do", "validate", "--task", task)
    if recorded is not None:
        satisfied = recorded["valid"]
        state = "satisfied" if satisfied else "failed"
        missing = []
        operation_id = None
        source = recorded["source"]
    elif completion_transition is not None:
        state, satisfied = "satisfied-by-completion-transition", True
        missing = []
        operation_id = completion_transition.get("operationId")
        source = "component-protocol-completion-transition"
    elif matching is None:
        state, satisfied = "validation-required", False
        missing: list[str] = []
        operation_id = None
        source = "none"
    else:
        data = matching["data"]
        satisfied = data.get("valid") is True
        state = "satisfied" if satisfied else "failed"
        missing = data.get("missing", []) if isinstance(data.get("missing"), list) else []
        operation_id = matching.get("operationId")
        source = "component-ledger-migration"
    return {
        "state": state,
        "required": True,
        "satisfied": satisfied,
        "evidenceClass": "context-validation",
        "qualityGateSatisfied": False,
        "task": task,
        "taskDigest": current_digest,
        "operationId": operation_id,
        "source": source,
        "missing": missing,
        "next": None if satisfied else next_command,
    }


def evidence(root: Path, *, include_finish: bool = True) -> dict[str, Any]:
    """Unify acceptance-related evidence without executing a host or Trellis command."""
    root = resolve_root(root)
    from . import executable_acceptance

    host_test = status(root)
    executable = executable_acceptance.status(root)
    context_gate = _trellis_context_gate(root)
    guided = guided_acceptance.evaluate(root, host_test["contract"])
    requirements = (
        _requirements_integrity(
            root,
            host_test["contract"],
            strict=guided["mode"] == "strict" and "wide-changeset" in guided["reasonCodes"],
        )
        if host_test["contract"] is not None
        else {
            "state": "not-applicable",
            "required": False,
            "satisfied": True,
            "source": None,
            "exactSourcePersisted": False,
            "next": None,
        }
    )
    required = host_test["required"]
    host_plan = host_test.get("verificationPlan") or {}
    host_required = int(host_plan.get("requiredSteps", 0)) if required else 0
    if required and host_required == 0:
        host_required = 1
    host_satisfied = int(host_plan.get("satisfiedSteps", 0)) if required else 0
    if required and host_test["satisfied"] and host_required == 1:
        host_satisfied = 1
    context_required = 1 if required and context_gate["required"] else 0
    context_satisfied = 1 if context_required and context_gate["satisfied"] else 0
    requirements_required = 1 if required and requirements["required"] else 0
    requirements_satisfied = 1 if requirements_required and requirements["satisfied"] else 0
    executable_required = 1 if required and executable["required"] else 0
    executable_satisfied = 1 if executable_required and executable["satisfied"] else 0
    satisfied_count = host_satisfied + context_satisfied + requirements_satisfied + executable_satisfied
    required_count = host_required + context_required + requirements_required + executable_required
    evidence_satisfied = required and required_count > 0 and satisfied_count == required_count
    satisfied = evidence_satisfied and guided["satisfied"]
    if not required:
        state = "not-declared"
        next_command = None
    elif not requirements["satisfied"]:
        state = "requirements-" + requirements["state"]
        next_command = requirements["next"]
    elif executable["required"] and not executable["satisfied"]:
        state = "executable-acceptance-" + executable["state"]
        next_command = executable["next"]
    elif not guided["satisfied"]:
        state = "guided-" + guided["state"]
        next_command = guided["next"]
    elif not host_test["satisfied"]:
        state = host_test["state"]
        next_command = host_test["next"]
    elif not context_gate["satisfied"]:
        state = "context-" + context_gate["state"]
        next_command = context_gate["next"]
    else:
        state = "satisfied"
        phase = lifecycle.status(root)["phase"]
        next_command = "hellodev do check" if phase == "working" else "hellodev do finish"
    projection: dict[str, Any] = {
        "schemaVersion": 1,
        "state": state,
        "required": required,
        "satisfied": satisfied,
        "contract": host_test["contract"],
        "requirementsIntegrity": requirements,
        "hostTest": host_test,
        "trellisContextGate": context_gate,
        "guidedAcceptance": guided,
        "executableAcceptance": executable,
        "coverage": {
            "satisfied": satisfied_count,
            "required": required_count,
            "ratio": 1.0 if required_count == 0 else satisfied_count / required_count,
        },
        "qualityCoverage": {
            "mode": guided["mode"],
            "state": guided["state"],
            "satisfied": guided["satisfied"],
            "blockerCount": len(guided["blockers"]),
        },
        "next": next_command,
        "sourceTrust": "host-asserted-and-local-observed",
        "testExecutionPerformed": False,
        "trellisExecutionPerformed": False,
        "rawOutputPersisted": False,
    }
    if include_finish:
        from . import gates

        projection["finishDecision"] = gates.finish_decision(root)
    return projection


def require_satisfied(root: Path, transition: str) -> dict[str, Any]:
    projection = evidence(root, include_finish=False)
    if projection["required"] and not projection["satisfied"]:
        detail = (
            "requirements source is not integrity-bound"
            if projection["state"].startswith("requirements-")
            else f"declared acceptance is {projection['state']}"
        )
        raise ProjectError(
            f"{transition} blocked: {detail}. Next: {projection['next']}"
        )
    return projection


__all__ = ["current", "evidence", "record", "record_context_validation", "require_satisfied", "status"]
