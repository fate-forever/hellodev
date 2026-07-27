"""User-facing projections that hide internal task-store plumbing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import capabilities, contracts, lifecycle
from .command_rendering import command_line
from .project import ProjectError, list_tasks, show_task


def _single_line(value: str, field: str, limit: int) -> str:
    normalized = value.strip()
    if not normalized or "\n" in normalized or "\r" in normalized or len(normalized) > limit:
        raise ProjectError(f"{field} must be a non-empty single line of {limit} characters or fewer")
    return normalized


def context_plan(root: str | Path, goal: str, acceptance: str | None = None) -> dict[str, Any]:
    """Return an Agent-ready bounded context request without reading repository text."""

    selected = Path(root)
    normalized_goal = _single_line(goal, "goal", 512)
    normalized_acceptance = None if acceptance is None else _single_line(acceptance, "acceptance", 1000)
    return {
        "schemaVersion": 1,
        "state": "ready",
        "intent": "code",
        "level": "L1",
        "query": normalized_goal,
        "scope": "code",
        "tokenBudget": 1200,
        "command": command_line(
            selected,
            "context",
            "pack",
            "--intent",
            "code",
            "--query",
            normalized_goal,
            "--scope",
            "code",
            "--token-budget",
            "1200",
        ),
        "acceptanceProvided": normalized_acceptance is not None,
        "persistencePerformed": False,
        "repositoryReadPerformed": False,
    }


def current_task(root: str | Path) -> dict[str, Any]:
    """Resolve local task, Trellis task, and WorkItem into one daily projection."""

    selected = Path(root)
    local_tasks = list_tasks(selected)
    trellis_tasks = contracts.list_trellis_tasks(selected)
    work_items = contracts.list_work_items(selected)
    work_item = contracts.current_work_item(selected)
    counts = {
        "localTasks": len(local_tasks),
        "trellisTasks": len(trellis_tasks),
        "workItems": len(work_items),
    }
    if work_item is None:
        candidate = trellis_tasks[0] if len(trellis_tasks) == 1 else None
        return {
            "schemaVersion": 1,
            "state": "unbound",
            "id": None,
            "backend": None,
            "nativeRef": None,
            "title": None,
            "taskState": None,
            "lifecyclePhase": lifecycle.status(selected)["phase"],
            "candidate": candidate,
            "counts": counts,
        }

    contracts.validate_work_item_reference(selected, work_item)
    if work_item["backend"] == "local":
        task = show_task(selected, work_item["nativeRef"])
        title = task["title"]
        task_state = task["status"]
    else:
        title = work_item["nativeRef"]
        task_state = "active" if work_item["nativeRef"] in trellis_tasks else "missing"
    fingerprint_current = work_item["sourceFingerprint"] == capabilities.fingerprint(selected)
    return {
        "schemaVersion": 1,
        "state": "linked" if fingerprint_current and task_state != "missing" else "attention",
        "id": work_item["id"],
        "backend": work_item["backend"],
        "nativeRef": work_item["nativeRef"],
        "title": title,
        "taskState": task_state,
        "lifecyclePhase": lifecycle.status(selected)["phase"],
        "fingerprintCurrent": fingerprint_current,
        "counts": counts,
    }


__all__ = ["context_plan", "current_task"]
