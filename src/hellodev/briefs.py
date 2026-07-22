"""Bounded L0/L1/L2 context briefs cached inside a HelloDev project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import capabilities, context_runtime, lifecycle
from .project import TASK_ID_PATTERN, ProjectError, ProjectPaths, load_config, show_task, utc_now, write_json


LEVELS = {"L0": 2_000, "L1": 16_000, "L2": 48_000}
BYTES_PER_TOKEN_ENVELOPE = 4


def _context_capabilities(value: Any) -> Any:
    """Keep provider discovery useful without copying its tool catalog into briefs."""
    if not isinstance(value, dict):
        return value
    projected = dict(value)
    repository_tools = projected.get("repositoryTools")
    if isinstance(repository_tools, dict):
        projected["repositoryTools"] = {
            key: repository_tools.get(key)
            for key in ("state", "activeProvider", "suggestedProvider", "activationState")
        }
    return projected


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
        "capabilities": _context_capabilities(material["capabilities"]["capabilities"]),
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


def _context_plane_projection(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value[key] for key in (
            "schemaVersion", "state", "backend", "scope", "querySha256", "snapshot",
            "snapshotState", "continuation", "metrics", "readOnly", "persistencePerformed",
            "rawContentPersisted",
        )},
        "items": [
            {key: item[key] for key in (
                "sourceType", "authority", "path", "startLine", "endLine", "fileSha256",
                "snippetSha256", "score", "complete",
            )}
            for item in value["items"]
        ],
    }


def _query_context_pack(
    root: Path,
    payload: dict[str, Any],
    *,
    token_budget: int,
    query: str | None,
    scope: str,
    cursor: str | None,
    persist_metrics: bool,
) -> dict[str, Any]:
    byte_cap = token_budget * BYTES_PER_TOKEN_ENVELOPE
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
            f"Nocturne={adapters.get('nocturne', {}).get('state', 'unknown')}; "
            "ContextPlane=native"
        )
    lines.append("Nocturne policy: not queried automatically.")
    header = "\n".join(lines) + "\n"
    if len(header.encode("utf-8")) >= byte_cap:
        raise ProjectError("context token budget is too small for the Context Plane header")

    fixed_budget = min(4096, max(0, byte_cap // 3 - len(header.encode("utf-8"))))
    fixed_parts: list[str] = []
    fixed_used = 0
    fixed_truncated = False
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        title = f"\n## {source['path']}\n"
        selected: list[str] = []
        for line in str(source.get("text", "")).splitlines():
            candidate = title + "\n".join(selected + [line]) + "\n"
            if fixed_used + len(candidate.encode("utf-8")) > fixed_budget:
                fixed_truncated = True
                break
            selected.append(line)
        if selected:
            block = title + "\n".join(selected) + "\n"
            fixed_parts.append(block)
            fixed_used += len(block.encode("utf-8"))
        elif source.get("text"):
            fixed_truncated = True

    prefix = header + "".join(fixed_parts)
    remaining = byte_cap - len(prefix.encode("utf-8"))
    if remaining < 256:
        prefix = header
        remaining = byte_cap - len(prefix.encode("utf-8"))
        fixed_truncated = bool(payload.get("sources"))
    plane = context_runtime.build_context(
        root,
        query=query,
        scope=scope,
        byte_budget=min(48_000, remaining),
        cursor=cursor,
        persist_metrics=persist_metrics,
    )
    blocks = [
        f"\n## {item['path']}:{item['startLine']}-{item['endLine']}\n{item['text']}\n"
        for item in plane["items"]
    ]
    rendered = prefix + "".join(blocks)
    if len(rendered.encode("utf-8")) > byte_cap:
        raise ProjectError("Context Plane composition exceeded its preallocated budget")
    return {
        "text": rendered,
        "truncated": fixed_truncated or plane["state"] == "partial" or plane["snapshotState"] == "bounded",
        "contextPlane": _context_plane_projection(plane),
    }


def context_pack(
    root: Path,
    level: str,
    task_id: str | None,
    allow_l2: bool,
    token_budget: int,
    query: str | None = None,
    scope: str = "project",
    cursor: str | None = None,
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
    if query is not None or cursor is not None:
        composed = _query_context_pack(
            root,
            payload,
            token_budget=token_budget,
            query=query,
            scope=scope,
            cursor=cursor,
            persist_metrics=True,
        )
        return {
            "state": result["state"],
            "level": level,
            "taskId": task_id,
            "tokenBudget": token_budget,
            "byteCap": token_budget * BYTES_PER_TOKEN_ENVELOPE,
            "budgetContract": "conservative UTF-8 envelope; exact tokens depend on the receiving model",
            **composed,
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
    capabilities_payload = payload.get("capabilities")
    if isinstance(capabilities_payload, dict):
        trellis_state = capabilities_payload.get("trellis", {}).get("state", "unknown")
        nocturne_state = capabilities_payload.get("nocturne", {}).get("state", "unknown")
        repository_provider = capabilities_payload.get("repositoryTools", {}).get("suggestedProvider", "native")
        lines.append(
            f"Adapters: Trellis={trellis_state}; Nocturne={nocturne_state}; "
            f"RepositoryTools={repository_provider}"
        )
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
    query: str | None = None,
    scope: str = "project",
    cursor: str | None = None,
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
        "capabilities": _context_capabilities(material["capabilities"]["capabilities"]),
        "sources": material["sources"],
        "nocturnePolicy": "not-queried-automatically",
    }
    if query is not None or cursor is not None:
        composed = _query_context_pack(
            root,
            payload,
            token_budget=token_budget,
            query=query,
            scope=scope,
            cursor=cursor,
            persist_metrics=False,
        )
        return {
            "state": "preview",
            "level": level,
            "taskId": task_id,
            "sourceFingerprint": fingerprint,
            "tokenBudget": token_budget,
            "byteCap": token_budget * BYTES_PER_TOKEN_ENVELOPE,
            "budgetContract": "conservative UTF-8 envelope; exact tokens depend on the receiving model",
            **composed,
            "persistencePerformed": False,
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
            f"; RepositoryTools={adapters.get('repositoryTools', {}).get('suggestedProvider', 'native')}"
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
