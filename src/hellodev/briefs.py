"""Bounded L0/L1/L2 context briefs cached inside a HelloDev project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import capabilities, lifecycle
from .project import TASK_ID_PATTERN, ProjectError, ProjectPaths, load_config, show_task, utc_now, write_json


LEVELS = {"L0": 2_000, "L1": 16_000, "L2": 48_000}
BYTES_PER_TOKEN_ENVELOPE = 4


def _brief_path(root: Path, level: str, task_id: str | None) -> Path:
    if task_id is not None and not TASK_ID_PATTERN.fullmatch(task_id):
        raise ProjectError("brief task id must use the form task-0001")
    key = task_id or "project"
    return ProjectPaths(root).briefs_dir / f"{key.lower()}-{level.lower()}.json"


def _safe_text(root: Path, relative: Path, max_bytes: int) -> dict[str, Any] | None:
    path = root / relative
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProjectError(f"refusing non-regular brief source: {relative.as_posix()}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ProjectError(f"brief source escapes project root: {relative.as_posix()}") from error
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    selected = data[:max_bytes]
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "text": selected.decode("utf-8", errors="replace"),
        "truncated": truncated,
    }


def _sources(root: Path, level: str, task_id: str | None) -> list[dict[str, Any]]:
    if level == "L0":
        return []
    per_file = 4_000 if level == "L1" else 12_000
    relative_paths = [Path(".trellis/workflow.md"), Path(".trellis/spec/context/CONTEXT.md")]
    if task_id:
        relative_paths.insert(0, Path(".hellodev/tasks") / f"{task_id}.md")
    source_items: list[dict[str, Any]] = []
    for relative in relative_paths:
        item = _safe_text(root, relative, per_file)
        if item is not None:
            source_items.append(item)
    return source_items


def _input(root: Path, level: str, task_id: str | None) -> tuple[str, dict[str, Any]]:
    if level not in LEVELS:
        raise ProjectError("brief level must be L0, L1, or L2")
    config = load_config(root)
    task = show_task(root, task_id) if task_id else None
    capability_state = capabilities.status(root)
    state = lifecycle.status(root)
    source_items = _sources(root, level, task_id)
    source_identity = [{key: value for key, value in item.items() if key != "text"} for item in source_items]
    identity = {
        "level": level,
        "task": task,
        "project": {"name": config["projectName"], "schemaVersion": config["schemaVersion"]},
        "lifecycle": {"phase": state["phase"], "updatedAt": state["updatedAt"]},
        "capabilityFingerprint": capability_state["fingerprint"],
        "capabilityState": capability_state["state"],
        "sources": source_identity,
    }
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return fingerprint, {"identity": identity, "sources": source_items, "capabilities": capability_state}


def build(root: Path, level: str, task_id: str | None, allow_l2: bool) -> dict[str, Any]:
    if level == "L2" and not allow_l2:
        raise ProjectError("L2 brief requires --allow-l2 because it can include more local project context")
    if capabilities.status(root)["state"] != "fresh":
        capabilities.refresh(root)
    fingerprint, material = _input(root, level, task_id)
    path = _brief_path(root, level, task_id)
    if path.is_file() and not path.is_symlink():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectError(f"invalid HelloDev brief cache: {error}") from error
        if isinstance(existing, dict) and existing.get("schemaVersion") == 1 and existing.get("sourceFingerprint") == fingerprint:
            return {"state": "fresh", "cached": True, "sourceFingerprint": fingerprint, "payload": existing.get("payload")}
    identity = material["identity"]
    payload = {
        "level": level,
        "budgetBytes": LEVELS[level],
        "project": identity["project"],
        "lifecycle": identity["lifecycle"],
        "task": identity["task"],
        "capabilities": material["capabilities"]["capabilities"],
        "sources": material["sources"],
        "nocturnePolicy": "not-queried-automatically",
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > LEVELS[level]:
        raise ProjectError(f"{level} brief exceeds its {LEVELS[level]} byte budget; narrow the selected context")
    cache = {
        "schemaVersion": 1,
        "sourceFingerprint": fingerprint,
        "builtAt": utc_now(),
        "level": level,
        "taskId": task_id,
        "payload": payload,
    }
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev brief cache")
    write_json(path, cache)
    return {"state": "built", "cached": False, "sourceFingerprint": fingerprint, "payload": payload}


def show(root: Path, level: str, task_id: str | None) -> dict[str, Any]:
    path = _brief_path(root, level, task_id)
    if not path.is_file() or path.is_symlink():
        raise ProjectError("brief cache is missing; run 'hellodev brief build' first")
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev brief cache: {error}") from error
    if not isinstance(cache, dict) or cache.get("schemaVersion") != 1:
        raise ProjectError("invalid HelloDev brief cache schema")
    fingerprint, _ = _input(root, level, task_id)
    if cache.get("sourceFingerprint") != fingerprint:
        return {"state": "stale", "cached": True, "sourceFingerprint": fingerprint, "action": "run hellodev brief build"}
    return {"state": "fresh", "cached": True, "sourceFingerprint": fingerprint, "payload": cache.get("payload")}


def _truncate_utf8(text: str, byte_cap: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_cap:
        return text, False
    return encoded[:byte_cap].decode("utf-8", errors="ignore"), True


def context_pack(
    root: Path,
    level: str,
    task_id: str | None,
    allow_l2: bool,
    token_budget: int,
) -> dict[str, Any]:
    """Render a bounded, model-neutral handoff from the existing brief.

    Tokenizers differ between Codex hosts, so the requested token budget is a
    conservative envelope (four UTF-8 bytes per token), never an asserted
    exact token count.  This preserves a stable size contract without taking
    a dependency on a model-specific tokenizer.
    """
    if not 128 <= token_budget <= 12_000:
        raise ProjectError("context token budget must be between 128 and 12000")
    result = build(root, level, task_id, allow_l2)
    payload = result["payload"]
    lines = [
        "# HelloDev context pack",
        f"Project: {payload['project']['name']}",
        f"Lifecycle: {payload['lifecycle']['phase']}",
        f"Brief level: {payload['level']}",
    ]
    task = payload.get("task")
    if isinstance(task, dict):
        lines.append(f"Task: {task['id']} — {task['title']} ({task['status']})")
    capabilities_payload = payload.get("capabilities")
    if isinstance(capabilities_payload, dict):
        trellis_state = capabilities_payload.get("trellis", {}).get("state", "unknown")
        nocturne_state = capabilities_payload.get("nocturne", {}).get("state", "unknown")
        lines.append(f"Adapters: Trellis={trellis_state}; Nocturne={nocturne_state}")
    lines.append("Nocturne policy: not queried automatically.")
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        lines.extend(("", f"## {source['path']}", str(source.get("text", ""))))
    text, truncated = _truncate_utf8("\n".join(lines) + "\n", token_budget * BYTES_PER_TOKEN_ENVELOPE)
    return {
        "state": result["state"],
        "level": level,
        "taskId": task_id,
        "tokenBudget": token_budget,
        "byteCap": token_budget * BYTES_PER_TOKEN_ENVELOPE,
        "budgetContract": "conservative UTF-8 envelope; exact tokens depend on the receiving model",
        "truncated": truncated,
        "text": text,
    }


def preview_context_pack(
    root: Path,
    level: str,
    task_id: str | None,
    allow_l2: bool,
    token_budget: int,
) -> dict[str, Any]:
    """Render the context pack without refreshing capabilities or writing a cache."""
    if level == "L2" and not allow_l2:
        raise ProjectError("L2 brief requires explicit allowance because it can include more local project context")
    if not 128 <= token_budget <= 12_000:
        raise ProjectError("context token budget must be between 128 and 12000")
    capability_state = capabilities.status(root)
    if capability_state["state"] != "fresh":
        raise ProjectError("host context preview requires fresh capabilities; run 'hellodev capabilities refresh'")
    fingerprint, material = _input(root, level, task_id)
    identity = material["identity"]
    payload = {
        "level": level,
        "budgetBytes": LEVELS[level],
        "project": identity["project"],
        "lifecycle": identity["lifecycle"],
        "task": identity["task"],
        "capabilities": material["capabilities"]["capabilities"],
        "sources": material["sources"],
        "nocturnePolicy": "not-queried-automatically",
    }
    lines = [
        "# HelloDev context pack",
        f"Project: {payload['project']['name']}",
        f"Lifecycle: {payload['lifecycle']['phase']}",
        f"Brief level: {payload['level']}",
    ]
    task = payload.get("task")
    if isinstance(task, dict):
        lines.append(f"Task: {task['id']} - {task['title']} ({task['status']})")
    adapters = payload.get("capabilities")
    if isinstance(adapters, dict):
        lines.append(
            "Adapters: Trellis="
            f"{adapters.get('trellis', {}).get('state', 'unknown')}; "
            f"Nocturne={adapters.get('nocturne', {}).get('state', 'unknown')}"
        )
    lines.append("Nocturne policy: not queried automatically.")
    for source in payload["sources"]:
        lines.extend(("", f"## {source['path']}", str(source.get("text", ""))))
    rendered, truncated = _truncate_utf8("\n".join(lines) + "\n", token_budget * BYTES_PER_TOKEN_ENVELOPE)
    return {
        "state": "preview",
        "level": level,
        "taskId": task_id,
        "sourceFingerprint": fingerprint,
        "tokenBudget": token_budget,
        "byteCap": token_budget * BYTES_PER_TOKEN_ENVELOPE,
        "budgetContract": "conservative UTF-8 envelope; exact tokens depend on the receiving model",
        "truncated": truncated,
        "text": rendered,
        "persistencePerformed": False,
    }
