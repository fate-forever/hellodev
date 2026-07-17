"""Deterministic, side-effect-free context selection for HelloDev intents."""

from __future__ import annotations

from typing import Any

from .project import ProjectError


LEVEL_TOKEN_BUDGETS = {"L0": 500, "L1": 4_000, "L2": 12_000}

LEVEL_LOADING = {
    "L0": (
        "project-metadata",
        "lifecycle-state",
        "capability-cache",
    ),
    "L1": (
        "project-metadata",
        "lifecycle-state",
        "capability-cache",
        "selected-local-task",
        "trellis-workflow",
        "trellis-context",
        "relevant-code",
    ),
    "L2": (
        "project-metadata",
        "lifecycle-state",
        "capability-cache",
        "selected-local-task",
        "trellis-workflow",
        "trellis-context",
        "relevant-code",
        "operation-plan",
        "receipts",
        "saga-state",
    ),
}

INTENT_LEVELS = {
    "status": "L0",
    "doctor": "L0",
    "lifecycle": "L1",
    "local-task": "L1",
    "code": "L1",
    "trellis-read": "L1",
    "trellis-write": "L2",
    "saga": "L2",
    "nocturne-write": "L2",
    "cross-project-retrieve": "L0",
    "recall": "L1",
    "remember": "L2",
}

INTENT_REASON_CODES = {
    "status": "minimal-status-context",
    "doctor": "minimal-diagnostic-context",
    "lifecycle": "local-lifecycle-context",
    "local-task": "local-task-context",
    "code": "local-code-context",
    "trellis-read": "local-trellis-read-context",
    "trellis-write": "external-write-context",
    "saga": "saga-evidence-context",
    "nocturne-write": "nocturne-write-context",
    "cross-project-retrieve": "cross-project-retrieval-context",
    "recall": "local-first-recall-context",
    "remember": "evidence-gated-remember-context",
}

NARROW_RETRIEVAL_INTENTS = frozenset({"cross-project-retrieve"})


def validate_intent(intent: str) -> str:
    """Return a canonical intent or fail closed without normalization."""
    if not isinstance(intent, str) or intent not in INTENT_LEVELS:
        raise ProjectError("unknown context intent; use a canonical HelloDev intent name")
    return intent


def validate_level(level: str) -> str:
    """Return an exact context level or fail closed."""
    if not isinstance(level, str) or level not in LEVEL_TOKEN_BUDGETS:
        raise ProjectError("context level must be L0, L1, or L2")
    return level


def suggested_level(intent: str) -> str:
    """Return the policy level suggested by a canonical intent."""
    return INTENT_LEVELS[validate_intent(intent)]


def selection_source(explicit_level: str | None) -> str:
    """Identify whether selection came from policy or an explicit override."""
    if explicit_level is None:
        return "intent"
    validate_level(explicit_level)
    return "explicit"


def select_level(intent: str, explicit_level: str | None = None) -> str:
    """Select an exact level; a valid explicit level overrides the suggestion."""
    canonical_intent = validate_intent(intent)
    if explicit_level is not None:
        return validate_level(explicit_level)
    return INTENT_LEVELS[canonical_intent]


def decide(intent: str, explicit_level: str | None = None) -> dict[str, Any]:
    """Return a pure context decision without reading files or calling adapters."""
    canonical_intent = validate_intent(intent)
    source = selection_source(explicit_level)
    level = select_level(canonical_intent, explicit_level)
    narrow_retrieval = canonical_intent in NARROW_RETRIEVAL_INTENTS
    reason_codes = [
        INTENT_REASON_CODES[canonical_intent],
        "explicit-level-override" if source == "explicit" else "intent-level-selection",
    ]
    if narrow_retrieval:
        reason_codes.append("narrow-retrieval-required")
    return {
        "schemaVersion": 1,
        "intent": canonical_intent,
        "level": level,
        "loading": list(LEVEL_LOADING[level]),
        "tokenBudget": LEVEL_TOKEN_BUDGETS[level],
        "reasonCodes": reason_codes,
        "selectionSource": source,
        "narrowRetrieval": narrow_retrieval,
        "adapterCalls": [],
    }


def suggest(intent: str, explicit_level: str | None = None) -> dict[str, Any]:
    """CLI-facing alias for :func:`decide`."""
    return decide(intent, explicit_level)
