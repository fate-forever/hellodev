"""Deterministic, non-persistent intent routing for HelloDev's unified face."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .project import ProjectError


INTENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TOP_LEVEL_INTENTS = ("plan", "work", "check", "finish", "task", "validate", "recall", "remember")
LOCAL_TASK_OPERATIONS = {"create", "list", "show"}
TRELLIS_TASK_OPERATIONS = {
    "create": ("task-create", "write"),
    "list": ("task-list", "read"),
    "current": ("task-current", "read"),
    "start": ("task-start", "write"),
    "validate": ("task-validate", "read"),
}
LIFECYCLE_TARGETS = {"plan": "planned", "work": "working", "check": "checking", "finish": "finished"}


def available_intents() -> list[str]:
    return [
        "plan [--note TEXT]",
        "work [--note TEXT]",
        "check [--note TEXT]",
        "finish [--note TEXT]",
        "task create --title TEXT",
        "task list",
        "task show --task TASK_ID (local projects only)",
        "task current|start|validate --task NATIVE_TASK (Trellis projects)",
        "validate --task NATIVE_TASK",
        "recall --query TEXT [narrow memory options]",
        "remember --lesson TEXT [--receipt RECEIPT_ID]",
    ]


def _intent(value: str) -> str:
    normalized = value.strip().lower()
    if not INTENT_PATTERN.fullmatch(normalized) or normalized not in TOP_LEVEL_INTENTS:
        raise ProjectError(f"unknown HelloDev intent: {value}; available intents: {', '.join(TOP_LEVEL_INTENTS)}")
    return normalized


def _trellis_present(root: Path) -> bool:
    marker = root / ".trellis"
    if marker.is_symlink():
        raise ProjectError("refusing symlinked .trellis for unified routing")
    return marker.is_dir()


def _single_line(value: Any, field: str, limit: int = 240) -> str:
    if not isinstance(value, str):
        raise ProjectError(f"{field} is required")
    normalized = value.strip()
    if not normalized or "\n" in normalized or "\r" in normalized or len(normalized) > limit:
        raise ProjectError(f"{field} must be a non-empty single line of {limit} characters or fewer")
    return normalized


def decide(root: Path, intent: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a stable route description without executing or authorizing it."""
    selected = _intent(intent)
    values = dict(arguments or {})
    base: dict[str, Any] = {
        "schemaVersion": 1,
        "intent": selected,
        "executionPerformed": False,
        "persistent": False,
    }
    if selected in LIFECYCLE_TARGETS:
        note = values.get("note")
        if note is not None:
            note = _single_line(note, "note")
        return {
            **base,
            "route": f"lifecycle.{selected}",
            "backend": "hellodev-local",
            "risk": "local-write",
            "contextIntent": "lifecycle",
            "arguments": {"target": LIFECYCLE_TARGETS[selected], "note": note},
            "reasonCode": "lifecycle-explicit",
        }
    if selected == "task":
        operation = _single_line(values.get("operation"), "task operation", 32).lower()
        has_trellis = _trellis_present(root)
        if has_trellis:
            mapping = TRELLIS_TASK_OPERATIONS.get(operation)
            if mapping is None:
                raise ProjectError(
                    f"task operation {operation} is not in the Trellis F1 allowlist; use a native HelloDev Trellis command"
                )
            native_intent, risk = mapping
            routed_arguments: dict[str, Any] = {}
            if operation == "create":
                routed_arguments["title"] = _single_line(values.get("title"), "title", 160)
            elif operation in {"start", "validate"}:
                routed_arguments["task"] = _single_line(values.get("task"), "task", 96)
            return {
                **base,
                "route": f"trellis.{native_intent}",
                "backend": "trellis",
                "risk": risk,
                "contextIntent": "trellis-write" if risk == "write" else "trellis-read",
                "arguments": {"nativeIntent": native_intent, **routed_arguments},
                "reasonCode": "trellis-project-detected",
            }
        if operation not in LOCAL_TASK_OPERATIONS:
            raise ProjectError(
                f"local task operation {operation} is unsupported without .trellis; available: create, list, show"
            )
        routed_arguments = {}
        if operation == "create":
            routed_arguments["title"] = _single_line(values.get("title"), "title", 160)
        elif operation == "show":
            routed_arguments["task"] = _single_line(values.get("task"), "task", 64)
        return {
            **base,
            "route": f"local-task.{operation}",
            "backend": "hellodev-local",
            "risk": "local-write" if operation == "create" else "read",
            "contextIntent": "local-task",
            "arguments": routed_arguments,
            "reasonCode": "trellis-project-absent",
        }
    if selected == "validate":
        if not _trellis_present(root):
            raise ProjectError("validate requires a Trellis project at the selected root")
        return decide(root, "task", {"operation": "validate", "task": values.get("task")}) | {
            "intent": "validate",
            "reasonCode": "validate-shortcut",
        }
    if selected == "recall":
        return {
            **base,
            "route": "knowledge.recall",
            "backend": "hellodev-knowledge",
            "risk": "external-read-possible",
            "contextIntent": "recall",
            "arguments": {"query": _single_line(values.get("query"), "query", 1000)},
            "reasonCode": "local-first-recall",
        }
    return {
        **base,
        "route": "knowledge.remember",
        "backend": "hellodev-knowledge",
        "risk": "external-write-plan",
        "contextIntent": "remember",
        "arguments": {
            "lesson": _single_line(values.get("lesson"), "lesson", 1000),
            "receipt": values.get("receipt"),
        },
        "reasonCode": "evidence-explicit-remember",
    }


def next_decision(root: Path) -> dict[str, Any]:
    """Compatibility entry delegated to the F2 resume engine."""
    from . import resume

    return resume.next_decision(root)
