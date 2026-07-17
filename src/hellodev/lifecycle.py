"""Project-local lifecycle transitions for HelloDev orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json


PHASES = {"new", "started", "planned", "working", "checking", "finished", "blocked"}
TRANSITIONS = {
    "new": {"started"},
    "started": {"planned", "blocked"},
    "planned": {"working", "blocked"},
    "working": {"checking", "blocked"},
    "checking": {"working", "finished", "blocked"},
    "blocked": set(),
    "finished": set(),
}
MAX_HISTORY = 100


def _new_state() -> dict[str, Any]:
    return {"schemaVersion": 1, "phase": "new", "updatedAt": utc_now(), "history": []}


def _load(root: Path) -> dict[str, Any]:
    load_config(root)
    path = ProjectPaths(root).lifecycle_file
    if not path.exists():
        return _new_state()
    if path.is_symlink():
        raise ProjectError("refusing symlinked HelloDev lifecycle state")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev lifecycle state: {error}") from error
    if not isinstance(state, dict) or state.get("schemaVersion") != 1:
        raise ProjectError("invalid HelloDev lifecycle state schema")
    if state.get("phase") not in PHASES or not isinstance(state.get("history"), list):
        raise ProjectError("invalid HelloDev lifecycle state")
    return state


def _persist(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    write_json(ProjectPaths(root).lifecycle_file, state)
    return state


def status(root: Path) -> dict[str, Any]:
    return _load(root)


def start(root: Path, note: str | None = None) -> dict[str, Any]:
    state = _load(root)
    if state["phase"] == "new":
        return transition(root, "started", note)
    if state["phase"] == "started":
        return {**state, "idempotent": True}
    raise ProjectError(f"cannot start lifecycle from {state['phase']}; use lifecycle resume or an allowed transition")


def transition(root: Path, target: str, note: str | None = None) -> dict[str, Any]:
    if target not in PHASES - {"new"}:
        raise ProjectError(f"unsupported lifecycle target: {target}")
    if note is not None and ("\n" in note or "\r" in note or len(note) > 240):
        raise ProjectError("lifecycle note must be a single line of 240 characters or fewer")
    state = _load(root)
    current = state["phase"]
    if target not in TRANSITIONS[current]:
        raise ProjectError(f"cannot transition lifecycle from {current} to {target}")
    event: dict[str, str] = {"from": current, "to": target, "at": utc_now()}
    if note:
        event["note"] = note.strip()
    if target == "blocked":
        state["resumePhase"] = current
    state["phase"] = target
    state["updatedAt"] = event["at"]
    state["history"] = [*state["history"], event][-MAX_HISTORY:]
    return _persist(root, state)


def resume(root: Path, note: str | None = None) -> dict[str, Any]:
    state = _load(root)
    if state["phase"] != "blocked":
        raise ProjectError("lifecycle can only resume from blocked")
    target = state.get("resumePhase")
    if target not in {"started", "planned", "working", "checking"}:
        raise ProjectError("blocked lifecycle state has no valid resume phase")
    if note is not None and ("\n" in note or "\r" in note or len(note) > 240):
        raise ProjectError("lifecycle note must be a single line of 240 characters or fewer")
    event: dict[str, str] = {"from": "blocked", "to": target, "at": utc_now()}
    if note:
        event["note"] = note.strip()
    state["phase"] = target
    state["updatedAt"] = event["at"]
    state["history"] = [*state["history"], event][-MAX_HISTORY:]
    state.pop("resumePhase", None)
    return _persist(root, state)
