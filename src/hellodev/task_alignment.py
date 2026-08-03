"""Bounded, conservative alignment between an objective and a Trellis task."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

from .project import ProjectError, ProjectPaths, utc_now, write_json
from .state_lock import locked_state


MAX_TASK_METADATA_BYTES = 64 * 1024
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|[\u3400-\u9fff]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = {
    "add", "build", "change", "continue", "create", "do", "feature", "fix",
    "implement", "implementation", "mvp", "project", "support", "task", "the",
    "update", "work",
}


def _tokens(value: str) -> set[str]:
    normalized = _CAMEL.sub(" ", value.replace("_", " ").replace("-", " "))
    result: set[str] = set()
    for raw in _WORD.findall(normalized):
        token = raw.casefold()
        if token in _STOP or len(token) < 3:
            continue
        result.add(token)
        if re.fullmatch(r"[\u3400-\u9fff]{4,}", token):
            result.update(token[index:index + 2] for index in range(len(token) - 1))
    return result


def _metadata(root: Path, native_ref: str) -> tuple[dict[str, Any] | None, str]:
    task_dir = root / ".trellis" / "tasks" / native_ref
    task_file = task_dir / "task.json"
    if task_dir.is_symlink() or not task_dir.is_dir():
        return None, "task-directory-invalid"
    try:
        task_dir.resolve().relative_to((root / ".trellis" / "tasks").resolve())
    except ValueError:
        return None, "task-directory-escapes-store"
    if not task_file.exists():
        return {"id": native_ref, "name": native_ref, "title": native_ref}, "legacy-task-id-only"
    if task_file.is_symlink() or not task_file.is_file():
        return None, "task-metadata-unsafe"
    try:
        if task_file.stat().st_size > MAX_TASK_METADATA_BYTES:
            return None, "task-metadata-oversized"
        value = json.loads(task_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "task-metadata-invalid"
    if not isinstance(value, dict):
        return None, "task-metadata-invalid"
    bounded: dict[str, str] = {"id": native_ref}
    for field in ("name", "title", "description", "scope", "package"):
        item = value.get(field)
        if isinstance(item, str) and len(item) <= 512:
            bounded[field] = item
    return bounded, "task-metadata-ready"


def evaluate(root: Path, native_ref: str, goal: str) -> dict[str, Any]:
    """Return a content-free alignment decision; no PRD or source is read."""
    metadata, metadata_state = _metadata(root, native_ref)
    goal_tokens = _tokens(goal)
    task_tokens = set() if metadata is None else _tokens(" ".join(metadata.values()))
    overlap = goal_tokens & task_tokens
    aligned = bool(overlap)
    return {
        "schemaVersion": 1,
        "state": "aligned" if aligned else "not-aligned",
        "aligned": aligned,
        "reasonCode": "bounded-meaningful-token-overlap" if aligned else "no-bounded-meaningful-token-overlap",
        "metadataState": metadata_state,
        "goalTokenCount": len(goal_tokens),
        "taskTokenCount": len(task_tokens),
        "overlapCount": len(overlap),
        "rawGoalPersisted": False,
        "rawTaskMetadataExposed": False,
        "rawTaskBodyRead": False,
    }


def _binding_store(root: Path) -> dict[str, Any]:
    path = ProjectPaths(root).task_bindings_file
    if not path.exists():
        return {"schemaVersion": 1, "bindings": []}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ProjectError("HelloDev task binding store is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev task binding store: {error}") from error
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not isinstance(value.get("bindings"), list):
        raise ProjectError("invalid HelloDev task binding store")
    return value


def record_binding(root: Path, work_item_id: str, native_ref: str, goal: str, source: str,
                   alignment: dict[str, Any] | None) -> dict[str, Any]:
    if source not in {"explicit", "aligned", "created"}:
        raise ProjectError("invalid Trellis task binding source")
    item = {
        "workItemId": work_item_id,
        "nativeRef": native_ref,
        "goalSha256": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
        "source": source,
        "alignmentReasonCode": None if alignment is None else alignment.get("reasonCode"),
        "recordedAt": utc_now(),
    }
    with locked_state(root, "task-bindings"):
        store = _binding_store(root)
        existing = next((entry for entry in store["bindings"] if entry.get("workItemId") == work_item_id), None)
        if existing is not None:
            if existing != item:
                stable = {key: value for key, value in item.items() if key != "recordedAt"}
                prior = {key: value for key, value in existing.items() if key != "recordedAt"}
                if stable != prior:
                    raise ProjectError("active Trellis task binding cannot be replaced")
            return existing
        store["bindings"].append(item)
        store["bindings"] = store["bindings"][-100:]
        write_json(ProjectPaths(root).task_bindings_file, store)
    return item


def binding(root: Path, work_item_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in reversed(_binding_store(root)["bindings"]) if item.get("workItemId") == work_item_id),
        None,
    )


__all__ = ["binding", "evaluate", "record_binding"]
