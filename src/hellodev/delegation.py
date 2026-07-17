"""Deterministic delegation budgeting without executing or spawning agents.

The module accepts a deliberately small JSON-compatible contract.  It is a
planning boundary only: no project state, adapter, model, or agent runtime is
consulted.  Reported token budgets are caller-provided ceilings, not measured
or estimated model usage.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .project import ProjectError


SCHEMA_VERSION = 1
BYTES_PER_TOKEN_ENVELOPE = 1
MAX_CANDIDATES = 8
MAX_AGENTS = 4
MAX_SHARED_BYTES = 64_000
MAX_PER_AGENT_BYTES = 32_000
MAX_TOTAL_REPORTED_TOKEN_BUDGET = 100_000
MIN_PACK_TOKEN_BUDGET = 512
MAX_PACK_TOKEN_BUDGET = 12_000

_TOP_LEVEL_FIELDS = frozenset(
    {"task", "intent", "parallelizable", "sharedContext", "candidates", "limits"}
)
_CANDIDATE_FIELDS = frozenset({"role", "objective", "contextDelta"})
_LIMIT_FIELDS = frozenset(
    {"maxAgents", "sharedBytes", "perAgentBytes", "totalReportedTokenBudget"}
)
_SLUG = re.compile(r"[a-z][a-z0-9-]{0,63}")

# These operations are serialized because delegation cannot add independent
# parallel value or would split an authorization/evidence boundary.
_MAIN_ONLY_INTENTS = frozenset(
    {
        "status",
        "doctor",
        "lifecycle",
        "trellis-write",
        "nocturne-write",
        "saga",
        "remember",
        "profile-change",
        "authorization",
    }
)
_DELEGABLE_INTENTS = frozenset({"code", "research", "test", "review", "docs", "migration", "release"})


def _byte_count(value: str) -> int:
    return len(value.encode("utf-8"))


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectError(f"delegation {label} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise ProjectError(f"delegation {label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ProjectError(f"delegation {label} has unknown fields: {', '.join(unknown)}")


def _text(value: Any, label: str, *, max_bytes: int, single_line: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ProjectError(f"delegation {label} must be a non-blank trimmed string")
    if single_line and ("\n" in value or "\r" in value):
        raise ProjectError(f"delegation {label} must be a single line")
    if _byte_count(value) > max_bytes:
        raise ProjectError(f"delegation {label} exceeds {max_bytes} UTF-8 bytes")
    return value


def _positive_int(value: Any, label: str, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise ProjectError(f"delegation {label} must be an integer between 1 and {maximum}")
    return value


def _slug(value: Any, label: str) -> str:
    normalized = _text(value, label, max_bytes=64, single_line=True)
    if _SLUG.fullmatch(normalized) is None:
        raise ProjectError(f"delegation {label} must be a lowercase hyphenated identifier")
    return normalized


def _validated(payload: Any) -> dict[str, Any]:
    proposal = _object(payload, "proposal")
    _exact_fields(proposal, _TOP_LEVEL_FIELDS, "proposal")

    task = _text(proposal["task"], "task", max_bytes=1_024, single_line=True)
    intent = _slug(proposal["intent"], "intent")
    parallelizable = proposal["parallelizable"]
    if not isinstance(parallelizable, bool):
        raise ProjectError("delegation parallelizable must be a boolean")
    shared_context = _text(proposal["sharedContext"], "sharedContext", max_bytes=MAX_SHARED_BYTES)

    limits = _object(proposal["limits"], "limits")
    _exact_fields(limits, _LIMIT_FIELDS, "limits")
    normalized_limits = {
        "maxAgents": _positive_int(limits["maxAgents"], "limits.maxAgents", maximum=MAX_AGENTS),
        "sharedBytes": _positive_int(
            limits["sharedBytes"], "limits.sharedBytes", maximum=MAX_SHARED_BYTES
        ),
        "perAgentBytes": _positive_int(
            limits["perAgentBytes"], "limits.perAgentBytes", maximum=MAX_PER_AGENT_BYTES
        ),
        "totalReportedTokenBudget": _positive_int(
            limits["totalReportedTokenBudget"],
            "limits.totalReportedTokenBudget",
            maximum=MAX_TOTAL_REPORTED_TOKEN_BUDGET,
        ),
    }
    if _byte_count(shared_context) > normalized_limits["sharedBytes"]:
        raise ProjectError("delegation sharedContext exceeds limits.sharedBytes")

    candidates = proposal["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ProjectError("delegation candidates must be a non-empty array")
    if len(candidates) > MAX_CANDIDATES:
        raise ProjectError(f"delegation candidates cannot exceed {MAX_CANDIDATES}")

    normalized_candidates: list[dict[str, str]] = []
    roles: set[str] = set()
    for index, raw_candidate in enumerate(candidates):
        candidate = _object(raw_candidate, f"candidates[{index}]")
        _exact_fields(candidate, _CANDIDATE_FIELDS, f"candidates[{index}]")
        role = _slug(candidate["role"], f"candidates[{index}].role")
        if role in roles:
            raise ProjectError(f"delegation candidate roles must be unique: {role}")
        roles.add(role)
        objective = _text(
            candidate["objective"],
            f"candidates[{index}].objective",
            max_bytes=1_024,
            single_line=True,
        )
        context_delta = _text(
            candidate["contextDelta"],
            f"candidates[{index}].contextDelta",
            max_bytes=MAX_PER_AGENT_BYTES,
        )
        if _byte_count(context_delta) > normalized_limits["perAgentBytes"]:
            raise ProjectError(
                f"delegation candidates[{index}].contextDelta exceeds limits.perAgentBytes"
            )
        normalized_candidates.append(
            {"role": role, "objective": objective, "contextDelta": context_delta}
        )

    return {
        "task": task,
        "intent": intent,
        "parallelizable": parallelizable,
        "sharedContext": shared_context,
        "candidates": normalized_candidates,
        "limits": normalized_limits,
    }


def _shared_sha256(proposal: dict[str, Any]) -> str:
    return hashlib.sha256(proposal["sharedContext"].encode("utf-8")).hexdigest()


def _role_token_budgets(total: int, roles: list[str]) -> dict[str, int]:
    if not roles:
        return {}
    base, remainder = divmod(total, len(roles))
    return {role: base + (1 if index < remainder else 0) for index, role in enumerate(roles)}


def _decision(
    proposal: dict[str, Any], selected_roles: list[str], reason_codes: list[str]
) -> dict[str, Any]:
    limits = proposal["limits"]
    delegate = len(selected_roles) >= 2 and not reason_codes
    roles = selected_roles if delegate else []
    shared_bytes = _byte_count(proposal["sharedContext"])
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "decision": "delegate" if delegate else "main-only",
        "task": proposal["task"],
        "intent": proposal["intent"],
        "reasonCodes": reason_codes or ["independent-parallel-work", "bounded-delegation"],
        "selectedRoles": roles,
        "sharedEnvelope": {
            "sha256": _shared_sha256(proposal),
            "byteCount": shared_bytes,
            "contentIncluded": False,
        },
        "budgets": {
            "maxAgents": limits["maxAgents"],
            "selectedAgents": len(roles),
            "sharedBytes": limits["sharedBytes"],
            "perAgentBytes": limits["perAgentBytes"],
            "totalReportedTokenBudget": limits["totalReportedTokenBudget"],
            "roleReportedTokenBudgets": _role_token_budgets(
                limits["totalReportedTokenBudget"], roles
            ),
            "tokenBudgetSource": "caller-reported-ceiling",
        },
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }
    return result


def plan(payload: Any) -> dict[str, Any]:
    """Validate and deterministically approve or reject bounded delegation."""
    proposal = _validated(payload)
    candidate_count = len(proposal["candidates"])
    selected_count = min(candidate_count, proposal["limits"]["maxAgents"])
    selected = [item["role"] for item in proposal["candidates"][:selected_count]]
    reasons: list[str] = []
    if not proposal["parallelizable"]:
        reasons.append("task-not-parallelizable")
    if proposal["intent"] in _MAIN_ONLY_INTENTS:
        reasons.append("serialized-or-authority-sensitive-intent")
    elif proposal["intent"] not in _DELEGABLE_INTENTS:
        reasons.append("unknown-intent")
    if candidate_count < 2:
        reasons.append("insufficient-independent-candidates")
    if proposal["limits"]["maxAgents"] < 2:
        reasons.append("agent-limit-prevents-parallelism")
    if proposal["limits"]["totalReportedTokenBudget"] < selected_count * MIN_PACK_TOKEN_BUDGET:
        reasons.append("reported-token-budget-too-small")
    return _decision(proposal, selected, reasons)


def _truncate_utf8(value: str, byte_cap: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_cap:
        return value, False
    return encoded[:byte_cap].decode("utf-8", errors="ignore"), True


def _render_bounded_pack(
    proposal: dict[str, Any], candidate: dict[str, str], shared_sha256: str, byte_cap: int
) -> tuple[str, bool]:
    prefix = "\n".join(
        [
            "# HelloDev delegation context pack",
            f"Task: {proposal['task']}",
            f"Intent: {proposal['intent']}",
            f"Role: {candidate['role']}",
            f"Objective: {candidate['objective']}",
            f"Shared envelope SHA-256: {shared_sha256}",
            "",
            "## Shared context",
            "",
        ]
    )
    separator = "\n\n## Role context delta\n"
    suffix = "\n"
    fixed_bytes = _byte_count(prefix) + _byte_count(separator) + _byte_count(suffix)
    remaining = byte_cap - fixed_bytes
    if remaining < 2:
        raise ProjectError("delegation pack budget is too small for required metadata and context sections")

    shared_bytes = _byte_count(proposal["sharedContext"])
    delta_bytes = _byte_count(candidate["contextDelta"])
    shared_cap = max(1, remaining // 2)
    delta_cap = remaining - shared_cap
    if shared_bytes < shared_cap:
        delta_cap += shared_cap - shared_bytes
        shared_cap = shared_bytes
    if delta_bytes < delta_cap:
        shared_cap += delta_cap - delta_bytes
        delta_cap = delta_bytes
    shared, shared_truncated = _truncate_utf8(proposal["sharedContext"], shared_cap)
    delta, delta_truncated = _truncate_utf8(candidate["contextDelta"], delta_cap)
    return prefix + shared + separator + delta + suffix, shared_truncated or delta_truncated


def pack(payload: Any, role: str, token_budget: int) -> dict[str, Any]:
    """Render one bounded, model-neutral role pack from a delegable proposal.

    The shared material is included exactly once in the rendered document,
    followed by only the selected role's delta.  The token budget determines
    a conservative UTF-8 byte envelope and is never presented as exact usage.
    """
    proposal = _validated(payload)
    decision = plan(proposal)
    if decision["decision"] != "delegate":
        raise ProjectError("delegation context pack requires a delegate decision")
    canonical_role = _slug(role, "pack role")
    if canonical_role not in decision["selectedRoles"]:
        raise ProjectError("delegation pack role is not selected by the bounded plan")
    if (
        not isinstance(token_budget, int)
        or isinstance(token_budget, bool)
        or not MIN_PACK_TOKEN_BUDGET <= token_budget <= MAX_PACK_TOKEN_BUDGET
    ):
        raise ProjectError(
            f"delegation pack token budget must be between {MIN_PACK_TOKEN_BUDGET} and "
            f"{MAX_PACK_TOKEN_BUDGET}"
        )
    role_budget = decision["budgets"]["roleReportedTokenBudgets"][canonical_role]
    if token_budget > role_budget:
        raise ProjectError("delegation pack token budget exceeds the caller-reported role ceiling")

    candidate = next(item for item in proposal["candidates"] if item["role"] == canonical_role)
    shared_sha256 = decision["sharedEnvelope"]["sha256"]
    byte_cap = min(
        proposal["limits"]["perAgentBytes"], token_budget * BYTES_PER_TOKEN_ENVELOPE
    )
    bounded_text, truncated = _render_bounded_pack(
        proposal, candidate, shared_sha256, byte_cap
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "role": canonical_role,
        "sharedEnvelopeSha256": shared_sha256,
        "tokenBudget": token_budget,
        "reportedRoleTokenCeiling": role_budget,
        "byteCap": byte_cap,
        "byteCount": _byte_count(bounded_text),
        "budgetContract": (
            "hard UTF-8 byte ceiling; exact tokens depend on the receiving model"
        ),
        "truncated": truncated,
        "text": bounded_text,
        "executionPerformed": False,
        "persistencePerformed": False,
        "adapterCalls": [],
        "modelCalls": [],
    }
