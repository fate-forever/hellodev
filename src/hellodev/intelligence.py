"""Deterministic, prepare-only routing for HelloDev's intelligence layer."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from . import briefs, capabilities
from .project import ProjectError
from .receipts import get as get_receipt, list_receipts


PROJECT_SIGNALS = ("project", "repository", "repo", "task", "workflow", "test", "release", "package", "spec", "code")
CROSS_PROJECT_SIGNALS = (
    "always",
    "preference",
    "habit",
    "across projects",
    "my style",
    "我喜欢",
    "我的习惯",
    "我的偏好",
    "我的风格",
    "习惯",
    "偏好",
    "跨项目",
)


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 1_000:
        raise ProjectError(f"{field} must be non-empty and 1000 characters or fewer")
    return normalized


NARROW_VALUE = re.compile(r"^[A-Za-z0-9._/-]{1,64}$")
FORBIDDEN_RETRIEVAL_VALUES = {"*", "all", "boot", "global", "default"}


def _narrow_value(value: str | None, field: str) -> str:
    if not isinstance(value, str) or not NARROW_VALUE.fullmatch(value) or value.casefold() in FORBIDDEN_RETRIEVAL_VALUES:
        raise ProjectError(
            f"smart retrieve {field} must be an explicit narrow value; boot/global/default/all scopes are not allowed"
        )
    return value


def classify(lesson: str, scope: str) -> dict[str, Any]:
    text = _text(lesson, "lesson")
    if scope not in {"auto", "project", "cross-project"}:
        raise ProjectError("lesson scope must be auto, project, or cross-project")
    lowered = text.lower()
    project_score = sum(signal in lowered for signal in PROJECT_SIGNALS)
    cross_score = sum(signal in lowered for signal in CROSS_PROJECT_SIGNALS)
    if scope == "project":
        destination, confidence = "trellis", "declared"
    elif scope == "cross-project":
        destination, confidence = "nocturne", "declared"
    elif project_score > cross_score:
        destination, confidence = "trellis", "suggested"
    elif cross_score > project_score:
        destination, confidence = "nocturne", "suggested"
    else:
        destination, confidence = "human-review", "ambiguous"
    return {
        "destination": destination,
        "confidence": confidence,
        "signals": {"project": project_score, "crossProject": cross_score},
        "autonomy": "prepare-only",
        "policy": "Project facts remain in Trellis; durable cross-project preferences may be written to Nocturne only after explicit approval and evidence.",
    }


def retrieval_plan(
    root: Path,
    scope: str,
    query: str,
    level: str,
    domain: str | None = None,
    limit: int | None = None,
    namespace_scope: str | None = None,
) -> dict[str, Any]:
    _text(query, "query")
    if scope not in {"project", "cross-project"}:
        raise ProjectError("retrieval scope must be project or cross-project")
    if level not in {"L0", "L1", "L2"}:
        raise ProjectError("retrieval level must be L0, L1, or L2")
    if scope == "project":
        if domain is not None or limit is not None or namespace_scope is not None:
            raise ProjectError("project smart retrieval uses the local Trellis brief and does not accept Nocturne search scope")
        cache = capabilities.status(root)
        return {
            "destination": "trellis",
            "autonomy": "local-read-only",
            "capabilityCache": cache["state"],
            "plan": f"Build or show a {level} project brief, then use Trellis task/workflow context for the query.",
            "command": ["hellodev", "brief", "build", "--level", level],
            "nocturne": "not-queried",
        }
    selected_domain = _narrow_value(domain, "--domain")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ProjectError("smart retrieve --limit is required and must be between 1 and 20")
    selected_namespace = _narrow_value(namespace_scope, "--namespace-scope")
    parameters = {"query": _text(query, "query"), "domain": selected_domain, "limit": limit}
    return {
        "destination": "nocturne",
        "autonomy": "prepare-only",
        "plan": "Prepare a narrow public Nocturne search_memory call; HelloDev will not query long-term memory automatically.",
        "command": ["hellodev", "smart", "retrieve", "--scope", "cross-project", "--query", query, "--domain", selected_domain, "--limit", str(limit), "--namespace-scope", selected_namespace],
        "nocturne": {
            "tool": "search_memory",
            "parameters": parameters,
            "namespaceScope": selected_namespace,
            "namespaceContract": "declared operator scope only; Nocturne stdio selects its namespace and receives no namespace argument",
            "execution": "requires-one-time-approval",
        },
    }


def persistence_plan(root: Path, destination: str, receipt_id: str | None) -> dict[str, Any]:
    if destination not in {"trellis", "nocturne"}:
        raise ProjectError("persistence destination must be trellis or nocturne")
    if destination == "trellis":
        return {
            "destination": "trellis",
            "autonomy": "prepare-only",
            "plan": "Record the project fact in the applicable Trellis task, spec, journal, or ADR through the confirmed Trellis adapter.",
            "next": "Use hellodev trellis prepare and run with a one-time approval token.",
        }
    if receipt_id is None:
        return {
            "destination": "nocturne",
            "autonomy": "evidence-required",
            "plan": "A successful, verified project receipt is required before proposing a Nocturne write.",
            "next": "Provide --receipt receipt-0001 after verifying the Trellis result, preferably through a Saga.",
        }
    receipt = get_receipt(root, receipt_id)
    if (
        receipt["outcome"] != "succeeded"
        or receipt["adapter"] != "trellis"
        or receipt["kind"] not in {"gate", "test"}
    ):
        raise ProjectError(
            "Nocturne persistence requires a successful Trellis gate or test receipt"
        )
    verification = next(
        (
            candidate
            for candidate in list_receipts(root)
            if candidate["kind"] == "verification"
            and candidate["outcome"] == "succeeded"
            and candidate["subjectReceiptId"] == receipt_id
        ),
        None,
    )
    if verification is None:
        raise ProjectError("Nocturne persistence requires verified Trellis gate or test evidence")
    return {
        "destination": "nocturne",
        "autonomy": "evidence-required",
        "evidenceReceipt": receipt_id,
        "evidenceKind": receipt["kind"],
        "verificationReceipt": verification["id"],
        "plan": "Create a Saga, attach and verify the typed Trellis evidence receipt, then prepare a public Nocturne write.",
        "next": "Use hellodev saga verify before any Nocturne write.",
    }
