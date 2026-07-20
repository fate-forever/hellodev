"""Project-local lifecycle transitions with append-only completed cycles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .project import ProjectError, ProjectPaths, load_config, utc_now, write_json


PHASES = {"new", "started", "planned", "working", "checking", "finished", "blocked"}
TRANSITIONS = {
    "new": {"started"}, "started": {"planned", "blocked"}, "planned": {"working", "blocked"},
    "working": {"checking", "blocked"}, "checking": {"working", "finished", "blocked"},
    "blocked": set(), "finished": set(),
}
MAX_HISTORY = 100
MAX_COMPLETED_CYCLES = 100
_CYCLE = re.compile(r"^cycle-[0-9]{4,}$")


def _new_state() -> dict[str, Any]:
    return {"schemaVersion": 2, "cycleId": "cycle-0001", "phase": "new", "updatedAt": utc_now(), "history": [], "completedCycles": []}


def _validate_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_HISTORY or not all(isinstance(item, dict) for item in value):
        raise ProjectError("invalid HelloDev lifecycle history")
    return value


def _validate_v2(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or set(state) - {"schemaVersion", "cycleId", "phase", "updatedAt", "history", "completedCycles", "resumePhase"}:
        raise ProjectError("invalid HelloDev lifecycle state schema")
    if state["schemaVersion"] != 2 or not isinstance(state["cycleId"], str) or _CYCLE.fullmatch(state["cycleId"]) is None:
        raise ProjectError("invalid HelloDev lifecycle cycle")
    if state["phase"] not in PHASES or not isinstance(state["updatedAt"], str):
        raise ProjectError("invalid HelloDev lifecycle state")
    if state["phase"] == "blocked":
        if state.get("resumePhase") not in {"started", "planned", "working", "checking"}: raise ProjectError("blocked lifecycle state has no valid resume phase")
    elif "resumePhase" in state: raise ProjectError("only blocked lifecycle state may have resumePhase")
    _validate_history(state["history"])
    cycles = state["completedCycles"]
    if not isinstance(cycles, list) or len(cycles) > MAX_COMPLETED_CYCLES:
        raise ProjectError("invalid HelloDev completed lifecycle cycles")
    seen: set[str] = set()
    for cycle in cycles:
        if not isinstance(cycle, dict) or set(cycle) != {"id", "phase", "updatedAt", "history"}:
            raise ProjectError("invalid completed lifecycle cycle")
        if not isinstance(cycle["id"], str) or _CYCLE.fullmatch(cycle["id"]) is None or cycle["id"] in seen:
            raise ProjectError("invalid completed lifecycle cycle id")
        if cycle["phase"] != "finished" or not isinstance(cycle["updatedAt"], str):
            raise ProjectError("invalid completed lifecycle cycle state")
        _validate_history(cycle["history"]); seen.add(cycle["id"])
    if state["cycleId"] in seen:
        raise ProjectError("active lifecycle cycle is already completed")
    return state


def _migrate_v1(state: dict[str, Any]) -> dict[str, Any]:
    if set(state) - {"schemaVersion", "phase", "updatedAt", "history", "resumePhase"} or state.get("schemaVersion") != 1:
        raise ProjectError("invalid HelloDev lifecycle state schema")
    if state.get("phase") not in PHASES or not isinstance(state.get("updatedAt"), str):
        raise ProjectError("invalid HelloDev lifecycle state")
    history = _validate_history(state.get("history"))
    # A v1 file is one current cycle. It is only persisted as v2 on a mutation.
    value = {"schemaVersion": 2, "cycleId": "cycle-0001", "phase": state["phase"], "updatedAt": state["updatedAt"], "history": history, "completedCycles": []}
    if state["phase"] == "blocked": value["resumePhase"] = state.get("resumePhase")
    return value


def _load(root: Path) -> dict[str, Any]:
    load_config(root); path = ProjectPaths(root).lifecycle_file
    if not path.exists(): return _new_state()
    if path.is_symlink(): raise ProjectError("refusing symlinked HelloDev lifecycle state")
    try: state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise ProjectError(f"invalid HelloDev lifecycle state: {error}") from error
    if isinstance(state, dict) and state.get("schemaVersion") == 1: return _migrate_v1(state)
    return _validate_v2(state)


def _persist(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    _validate_v2(state); write_json(ProjectPaths(root).lifecycle_file, state); return state


def status(root: Path) -> dict[str, Any]: return _load(root)


def start(root: Path, note: str | None = None) -> dict[str, Any]:
    state = _load(root)
    if state["phase"] == "new": return transition(root, "started", note)
    if state["phase"] == "started": return {**state, "idempotent": True}
    raise ProjectError(f"cannot start lifecycle from {state['phase']}; use lifecycle resume or an allowed transition")


def _note(note: str | None) -> str | None:
    if note is not None and ("\n" in note or "\r" in note or len(note) > 240): raise ProjectError("lifecycle note must be a single line of 240 characters or fewer")
    return note.strip() if note else None


def transition(root: Path, target: str, note: str | None = None) -> dict[str, Any]:
    if target not in PHASES - {"new"}: raise ProjectError(f"unsupported lifecycle target: {target}")
    state = _load(root); current = state["phase"]
    if target not in TRANSITIONS[current]: raise ProjectError(f"cannot transition lifecycle from {current} to {target}")
    event: dict[str, str] = {"from": current, "to": target, "at": utc_now()}; normalized = _note(note)
    if normalized: event["note"] = normalized
    state["phase"] = target; state["updatedAt"] = event["at"]; state["history"] = [*state["history"], event][-MAX_HISTORY:]
    if target == "blocked": state["resumePhase"] = current
    return _persist(root, state)


def begin_cycle(root: Path, work_item_id: str) -> dict[str, Any]:
    """Close an exactly finished cycle and start the next one without erasing it."""
    if not isinstance(work_item_id, str) or not re.fullmatch(r"work-[0-9]{4,}", work_item_id): raise ProjectError("invalid WorkItem id for lifecycle cycle")
    state = _load(root)
    if state["phase"] != "finished": raise ProjectError(f"cannot begin a new lifecycle cycle from {state['phase']}; finish or resume the current cycle first")
    completed = {"id": state["cycleId"], "phase": "finished", "updatedAt": state["updatedAt"], "history": state["history"]}
    highest = max([int(state["cycleId"].removeprefix("cycle-")), *(int(item["id"].removeprefix("cycle-")) for item in state["completedCycles"])])
    now = utc_now(); next_id = f"cycle-{highest + 1:04d}"
    next_state = {"schemaVersion": 2, "cycleId": next_id, "phase": "started", "updatedAt": now,
                  "history": [{"from": "new", "to": "started", "at": now, "note": f"new cycle for {work_item_id}"}],
                  "completedCycles": [*state["completedCycles"], completed][-MAX_COMPLETED_CYCLES:]}
    return _persist(root, next_state)


def resume(root: Path, note: str | None = None) -> dict[str, Any]:
    state = _load(root)
    if state["phase"] != "blocked": raise ProjectError("lifecycle can only resume from blocked")
    target = state.get("resumePhase")
    if target not in {"started", "planned", "working", "checking"}: raise ProjectError("blocked lifecycle state has no valid resume phase")
    event: dict[str, str] = {"from": "blocked", "to": target, "at": utc_now()}
    normalized = _note(note)
    if normalized: event["note"] = normalized
    state["phase"] = target; state["updatedAt"] = event["at"]; state["history"] = [*state["history"], event][-MAX_HISTORY:]; state.pop("resumePhase", None)
    return _persist(root, state)
