"""Structured task bridge used by the hellodev@trellis component profile."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .component_protocol import canonical_sha256, handshake, result_error, result_ok, validate_operation_id
from .project import ProjectPaths, write_json
from .state_lock import locked_state


MAX_TASK_BYTES = 64 * 1024
TASK_NAME = re.compile(r"^(?:00|(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))-[a-z0-9]+(?:-[a-z0-9]+)*$")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _task_dir(root: Path, name: str) -> Path:
    if TASK_NAME.fullmatch(name) is None:
        raise ValueError("invalid-task-id")
    path = root / ".trellis" / "tasks" / name
    if path.is_symlink() or not _inside(path, root):
        raise ValueError("unsafe-task-path")
    return path


def _load_record(path: Path) -> dict[str, Any]:
    record_file = path / "task.json"
    if record_file.is_symlink() or not record_file.is_file() or record_file.stat().st_size > MAX_TASK_BYTES:
        raise ValueError("invalid-task-record")
    value = json.loads(record_file.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        raise ValueError("invalid-task-record")
    return value


def _digest(record: dict[str, Any]) -> str:
    return canonical_sha256(record)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _public_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": path.name,
        "title": record.get("title", path.name),
        "status": record.get("status"),
        "priority": record.get("priority"),
        "scope": record.get("scope"),
        "digest": _digest(record),
    }


def _list(root: Path) -> dict[str, Any]:
    tasks = root / ".trellis" / "tasks"
    if not tasks.is_dir() or tasks.is_symlink():
        return {"tasks": []}
    records = []
    for path in sorted(tasks.iterdir(), key=lambda item: item.name):
        if path.name == "archive" or not path.is_dir() or path.is_symlink() or TASK_NAME.fullmatch(path.name) is None:
            continue
        records.append(_public_record(path, _load_record(path)))
    return {"tasks": records}


def _show(root: Path, task: str) -> dict[str, Any]:
    path = _task_dir(root, task)
    return {"task": _public_record(path, _load_record(path))}


def _validate(root: Path, task: str) -> dict[str, Any]:
    path = _task_dir(root, task)
    record = _load_record(path)
    missing = [name for name in ("prd.md",) if not (path / name).is_file()]
    return {
        "task": _public_record(path, record),
        "valid": not missing,
        "missing": missing,
        "evidenceClass": "context-validation",
        "qualityGateSatisfied": False,
    }


def _slug(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    return (value or "task")[:64].rstrip("-")


def _create(
    root: Path,
    title: str,
    acceptance: str | None = None,
    expected_task_set_digest: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    normalized = title.strip()
    if not normalized or "\n" in normalized or "\r" in normalized or len(normalized) > 160:
        raise ValueError("invalid-task-title")
    prefix = datetime.now(timezone.utc).strftime("%m-%d")
    base = f"{prefix}-{_slug(normalized)}"
    tasks = root / ".trellis" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    if operation_id is not None:
        for existing_path in sorted(tasks.iterdir(), key=lambda item: item.name):
            if existing_path.name == "archive" or not existing_path.is_dir() or existing_path.is_symlink():
                continue
            try:
                existing_record = _load_record(existing_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
            meta = existing_record.get("meta")
            if isinstance(meta, dict) and meta.get("beginOperationId") == operation_id:
                return {"task": _public_record(existing_path, existing_record), "idempotent": True}
    current_names = sorted(
        item.name for item in tasks.iterdir() if item.name != "archive" and item.is_dir() and not item.is_symlink()
    )
    current_digest = canonical_sha256(current_names)
    if expected_task_set_digest is not None and expected_task_set_digest != current_digest:
        raise RuntimeError("task-set-conflict")
    normalized_acceptance = None
    if acceptance is not None:
        normalized_acceptance = acceptance.strip()
        if (
            not normalized_acceptance
            or "\n" in normalized_acceptance
            or "\r" in normalized_acceptance
            or len(normalized_acceptance) > 1000
        ):
            raise ValueError("invalid-task-acceptance")
    name = base
    suffix = 2
    while (tasks / name).exists():
        name = f"{base[:88]}-{suffix}"
        suffix += 1
    path = _task_dir(root, name)
    path.mkdir()
    today = datetime.now(timezone.utc).date().isoformat()
    record = {
        "id": name,
        "name": _slug(normalized),
        "title": normalized,
        "description": "",
        "status": "planning",
        "dev_type": None,
        "scope": None,
        "package": None,
        "priority": "P2",
        "creator": "hellodev",
        "assignee": "",
        "createdAt": today,
        "completedAt": None,
        "branch": None,
        "base_branch": None,
        "worktree_path": None,
        "commit": None,
        "pr_url": None,
        "subtasks": [],
        "children": [],
        "parent": None,
        "relatedFiles": [],
        "notes": "",
        "meta": {
            "createdBy": "hellodev.component/v1",
            **({"beginOperationId": operation_id} if operation_id is not None else {}),
        },
    }
    _write_json(path / "task.json", record)
    criterion = normalized_acceptance or ""
    (path / "prd.md").write_text(
        f"# {normalized}\n\n## Requirements\n\n## Acceptance criteria\n\n{criterion}\n",
        encoding="utf-8",
    )
    (path / "implement.jsonl").write_text("", encoding="utf-8")
    (path / "check.jsonl").write_text("", encoding="utf-8")
    return {"task": _public_record(path, record)}


def _begin(root: Path, parameters: dict[str, Any], operation_id: str) -> dict[str, Any]:
    """Create-or-select and start one task without exposing native setup steps."""

    selected = parameters.get("task")
    created = False
    recovered = False
    if isinstance(selected, str):
        task = selected
        expected_digest = parameters.get("expectedDigest")
    else:
        created_result = _create(
            root,
            str(parameters.get("title", "")),
            parameters.get("acceptance"),
            parameters.get("expectedTaskSetDigest"),
            operation_id,
        )
        task_value = created_result.get("task")
        if not isinstance(task_value, dict) or not isinstance(task_value.get("id"), str):
            raise ValueError("invalid-created-task")
        task = task_value["id"]
        expected_digest = task_value.get("digest")
        created = not bool(created_result.get("idempotent"))
        recovered = bool(created_result.get("idempotent"))
    started = _start(root, task, expected_digest if isinstance(expected_digest, str) else None)
    return {
        **started,
        "created": created,
        "recovered": recovered,
        "operationId": operation_id,
    }


def _current(root: Path) -> dict[str, Any]:
    context_id = os.environ.get("TRELLIS_CONTEXT_ID")
    if not context_id or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", context_id) is None:
        return {"task": None, "source": "no-context-id"}
    pointer = root / ".trellis" / ".runtime" / "sessions" / f"{context_id}.json"
    if pointer.is_symlink() or not pointer.is_file() or pointer.stat().st_size > 16 * 1024:
        return {"task": None, "source": "session-missing"}
    value = json.loads(pointer.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid-session-pointer")
    task = value.get("task") or value.get("taskDir") or value.get("name")
    if not isinstance(task, str):
        return {"task": None, "source": "session-empty"}
    return {**_show(root, Path(task).name), "source": "TRELLIS_CONTEXT_ID"}


def _start(root: Path, task: str, expected_digest: str | None) -> dict[str, Any]:
    path = _task_dir(root, task)
    record = _load_record(path)
    before = _digest(record)
    if expected_digest is not None and expected_digest != before:
        raise RuntimeError("digest-conflict")
    validation = _validate(root, task)
    if not validation["valid"]:
        raise RuntimeError("planning-gate-failed")
    if record["status"] == "planning":
        record["status"] = "in_progress"
        _write_json(path / "task.json", record)
    elif record["status"] != "in_progress":
        raise RuntimeError("invalid-task-transition")
    return {"task": _public_record(path, record), "previousDigest": before}


def _merge_hellodev_quality_evidence(root: Path, task: str, task_path: Path) -> dict[str, Any]:
    """Project hash-only host evidence without racing Trellis' singleton gate."""

    paths = ProjectPaths(root)
    work_file = paths.state_dir / "work-items.json"
    verification_file = paths.verification_file
    if not work_file.is_file() or work_file.is_symlink() or not verification_file.is_file() or verification_file.is_symlink():
        return {"state": "unavailable", "recordCount": 0}
    if work_file.stat().st_size > 256 * 1024 or verification_file.stat().st_size > 1024 * 1024:
        raise ValueError("unsafe-hellodev-quality-source")
    work_store = json.loads(work_file.read_text(encoding="utf-8"))
    verification_store = json.loads(verification_file.read_text(encoding="utf-8"))
    current_id = work_store.get("currentWorkItemId") if isinstance(work_store, dict) else None
    work_items = work_store.get("workItems") if isinstance(work_store, dict) else None
    records = verification_store.get("records") if isinstance(verification_store, dict) else None
    if not isinstance(current_id, str) or not isinstance(work_items, list) or not isinstance(records, list):
        raise ValueError("invalid-hellodev-quality-source")
    current = next((item for item in work_items if isinstance(item, dict) and item.get("id") == current_id), None)
    if current is None or current.get("backend") != "trellis" or current.get("nativeRef") != task:
        raise ValueError("hellodev-quality-work-item-mismatch")
    projected = []
    for item in records:
        if not isinstance(item, dict) or item.get("workItemId") != current_id or item.get("outcome") != "succeeded":
            continue
        fields = ("id", "level", "commandSha256", "scope", "scopeSnapshot", "repositorySnapshot", "outcome", "durationMs")
        if not all(field in item for field in fields):
            raise ValueError("invalid-hellodev-quality-record")
        projected.append({field: item[field] for field in fields})
    gate = task_path / ".gates" / "hellodev-quality.json"
    existing_records: list[dict[str, Any]] = []
    if gate.is_file() and not gate.is_symlink():
        if gate.stat().st_size > 256 * 1024:
            raise ValueError("unsafe-hellodev-quality-gate")
        existing = json.loads(gate.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or existing.get("schemaVersion") != 1 or not isinstance(existing.get("records"), list):
            raise ValueError("invalid-hellodev-quality-gate")
        existing_records = [item for item in existing["records"] if isinstance(item, dict)]
    merged = {item.get("id"): item for item in [*existing_records, *projected] if isinstance(item.get("id"), str)}
    value = {
        "schemaVersion": 1,
        "source": "hellodev-host-asserted",
        "task": task,
        "workItemId": current_id,
        "state": "passed" if merged else "unavailable",
        "records": list(merged.values())[-64:],
        "rawCommandsPersisted": False,
        "rawOutputPersisted": False,
    }
    _write_json(gate, value)
    return {"state": value["state"], "recordCount": len(value["records"]), "path": ".gates/hellodev-quality.json"}


def _complete(root: Path, task: str, expected_digest: str | None) -> dict[str, Any]:
    path = _task_dir(root, task)
    record = _load_record(path)
    before = _digest(record)
    if expected_digest is not None and expected_digest != before:
        raise RuntimeError("digest-conflict")
    if record["status"] == "completed":
        quality = _merge_hellodev_quality_evidence(root, task, path)
        return {"task": _public_record(path, record), "previousDigest": before, "idempotent": True, "qualityEvidence": quality}
    if record["status"] != "in_progress":
        raise RuntimeError("invalid-task-transition")
    record["status"] = "completed"
    record["completedAt"] = datetime.now(timezone.utc).date().isoformat()
    _write_json(path / "task.json", record)
    quality = _merge_hellodev_quality_evidence(root, task, path)
    return {"task": _public_record(path, record), "previousDigest": before, "qualityEvidence": quality}


def _execute(root: Path, action: str, parameters: dict[str, Any], op_id: str) -> dict[str, Any]:
    validate_operation_id(op_id)
    if not (root / ".trellis").is_dir():
        return result_error("trellis", action, op_id, "trellis-not-initialized", ".trellis is missing")
    try:
        if action == "task-list":
            data = _list(root)
        elif action == "task-current":
            data = _current(root)
        elif action == "task-create":
            data = _create(
                root,
                str(parameters.get("title", "")),
                parameters.get("acceptance"),
                parameters.get("expectedTaskSetDigest"),
                op_id,
            )
        elif action == "task-begin":
            data = _begin(root, parameters, op_id)
        elif action == "task-show":
            data = _show(root, str(parameters.get("task", "")))
        elif action == "task-validate":
            data = _validate(root, str(parameters.get("task", "")))
        elif action == "task-start":
            data = _start(root, str(parameters.get("task", "")), parameters.get("expectedDigest"))
        elif action == "task-complete":
            data = _complete(root, str(parameters.get("task", "")), parameters.get("expectedDigest"))
        else:
            return result_error("trellis", action, op_id, "unsupported-action", "action is not supported by Component Protocol v1")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return result_error("trellis", action, op_id, "invalid-task-state", str(error))
    except RuntimeError as error:
        return result_error("trellis", action, op_id, str(error), str(error))
    return result_ok("trellis", action, op_id, data)


def execute(root: Path, action: str, parameters: dict[str, Any], op_id: str) -> dict[str, Any]:
    validate_operation_id(op_id)
    ledger_file = ProjectPaths(root).state_dir / "component-operations.json"
    request_digest = canonical_sha256({"component": "trellis", "action": action, "parameters": parameters})
    with locked_state(root, "component-operations"):
        if ledger_file.is_file() and not ledger_file.is_symlink():
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
        else:
            ledger = {"schemaVersion": 1, "operations": {}}
        operations = ledger.get("operations")
        if not isinstance(operations, dict):
            raise ValueError("invalid-component-operation-ledger")
        previous = operations.get(op_id)
        if isinstance(previous, dict):
            if previous.get("requestSha256") != request_digest:
                return result_error("trellis", action, op_id, "operation-conflict", "operationId was used for another request")
            cached = previous.get("result")
            if isinstance(cached, dict):
                return {**cached, "replayed": True}
        value = _execute(root, action, parameters, op_id)
        if value.get("ok"):
            operations[op_id] = {"requestSha256": request_digest, "result": value}
            if len(operations) > 256:
                for key in list(operations)[:-256]:
                    operations.pop(key, None)
            write_json(ledger_file, ledger)
        return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--parameters", default="{}")
    parser.add_argument("--capabilities", action="store_true")
    args = parser.parse_args(argv)
    if args.capabilities:
        value = handshake(
            "trellis",
            [
                "task.list",
                "task.current",
                "task.create",
                "task.begin",
                "task.show",
                "task.start",
                "task.complete",
                "context.validate",
                "operationId",
                "expectedDigest",
            ],
        )
    else:
        value = execute(Path(args.root).resolve(), args.action, json.loads(args.parameters), args.operation_id)
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return 0 if value.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
