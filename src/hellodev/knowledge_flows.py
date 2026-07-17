"""Deterministic local-first recall and evidence-explicit remember planning."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import intelligence, receipts
from .adapters import nocturne
from .project import ProjectError, ProjectPaths, load_config


MAX_FILES = 24
MAX_FILE_BYTES = 16_000
MAX_TOTAL_BYTES = 64_000
MAX_RESULTS = 5
MAX_EXCERPT_CHARS = 320
QUERY_TOKEN = re.compile(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]")


def _query(value: str) -> str:
    normalized = value.strip()
    if not normalized or "\x00" in normalized or len(normalized) > 1_000:
        raise ProjectError("recall query must be non-empty and 1000 characters or fewer")
    return normalized


def _tokens(value: str) -> list[str]:
    return list(dict.fromkeys(token.casefold() for token in QUERY_TOKEN.findall(value)))


def _candidate_paths(root: Path) -> list[Path]:
    paths = ProjectPaths(root)
    trellis_candidates = [
        root / ".trellis" / "workflow.md",
        root / ".trellis" / "spec" / "context" / "CONTEXT.md",
    ]
    local_candidates: list[Path] = []
    for directory, pattern in ((paths.tasks_dir, "task-*.md"), (paths.briefs_dir, "*.json")):
        if directory.is_symlink():
            raise ProjectError(f"refusing symlinked recall source directory: {directory.name}")
        if directory.is_dir():
            local_candidates.extend(sorted(directory.glob(pattern)))
    reserved = min(len(trellis_candidates), MAX_FILES)
    return [*trellis_candidates[:reserved], *local_candidates[: MAX_FILES - reserved]]


def _safe_read(root: Path, path: Path, remaining: int) -> tuple[str, str] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProjectError(f"refusing unsafe recall source: {path.name}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ProjectError(f"recall source escapes project root: {path}") from error
    byte_limit = min(MAX_FILE_BYTES, remaining)
    with path.open("rb") as handle:
        selected = handle.read(byte_limit)
    if not selected:
        return None
    return selected.decode("utf-8", errors="replace"), hashlib.sha256(selected).hexdigest()


def _excerpt(text: str, query: str, tokens: list[str]) -> str:
    folded = text.casefold()
    position = folded.find(query.casefold())
    if position < 0:
        positions = [folded.find(token) for token in tokens if folded.find(token) >= 0]
        position = min(positions) if positions else 0
    start = max(0, position - 80)
    end = min(len(text), start + MAX_EXCERPT_CHARS)
    return " ".join(text[start:end].split())


def local_recall(root: Path, query: str) -> dict[str, Any]:
    """Search bounded local sources and return ephemeral labelled evidence."""
    load_config(root)
    normalized_query = _query(query)
    query_tokens = _tokens(normalized_query)
    if not query_tokens:
        raise ProjectError("recall query has no searchable terms")
    total = 0
    results: list[dict[str, Any]] = []
    for path in _candidate_paths(root):
        remaining = MAX_TOTAL_BYTES - total
        if remaining <= 0:
            break
        item = _safe_read(root, path, remaining)
        if item is None:
            continue
        text, digest = item
        total += min(len(text.encode("utf-8")), remaining)
        folded = text.casefold()
        exact = normalized_query.casefold() in folded
        all_terms = all(token in folded for token in query_tokens)
        any_terms = any(token in folded for token in query_tokens)
        if not any_terms:
            continue
        match = "strong" if exact or all_terms else "weak"
        results.append(
            {
                "sourceLabel": "Repository fact",
                "path": path.relative_to(root).as_posix(),
                "match": match,
                "contentSha256": digest,
                "excerpt": _excerpt(text, normalized_query, query_tokens),
            }
        )
    results.sort(key=lambda item: (0 if item["match"] == "strong" else 1, item["path"]))
    results = results[:MAX_RESULTS]
    strong = any(item["match"] == "strong" for item in results)
    weak = bool(results) and not strong
    state = "strong-hit" if strong else "weak-hit" if weak else "no-hit"
    response: dict[str, Any] = {
        "state": state,
        "localSufficient": strong,
        "sourceLabel": "Inference",
        "inference": "Local evidence is sufficient." if strong else "Long-term-memory fallback may be useful.",
        "results": results,
        "scannedBytes": total,
        "limits": {
            "files": MAX_FILES,
            "fileBytes": MAX_FILE_BYTES,
            "totalBytes": MAX_TOTAL_BYTES,
            "results": MAX_RESULTS,
        },
        "persisted": False,
    }
    response["resultSha256"] = hashlib.sha256(
        json.dumps(response, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return response


def recall_plan(
    root: Path,
    query: str,
    domain: str | None,
    limit: int | None,
    namespace_scope: str | None,
    *,
    also_memory: bool = False,
) -> dict[str, Any]:
    local = local_recall(root, query)
    if local["localSufficient"] and not also_memory:
        return {"state": "local-sufficient", "local": local, "nocturne": "not-planned", "persisted": False}
    if nocturne.status(root)["state"] != "configured":
        return {
            "state": "local-only",
            "local": local,
            "nocturne": "unconfigured",
            "next": "Configure Nocturne to enable narrow long-term-memory fallback.",
            "persisted": False,
        }
    plan = intelligence.retrieval_plan(
        root,
        "cross-project",
        _query(query),
        "L0",
        domain,
        limit,
        namespace_scope,
    )
    return {
        "state": "memory-plan-required",
        "local": local,
        "nocturne": plan["nocturne"],
        "sourceLabel": "Long-term memory",
        "authority": "non-authoritative advisory context",
        "persisted": False,
    }


def _verified_evidence(root: Path) -> list[dict[str, str]]:
    all_receipts = receipts.list_receipts(root)
    verifications = {
        receipt["subjectReceiptId"]: receipt
        for receipt in all_receipts
        if receipt["kind"] == "verification" and receipt["outcome"] == "succeeded"
    }
    return [
        {
            "receiptId": receipt["id"],
            "kind": receipt["kind"],
            "verificationReceiptId": verifications[receipt["id"]]["id"],
        }
        for receipt in all_receipts
        if receipt["adapter"] == "trellis"
        and receipt["kind"] in {"gate", "test"}
        and receipt["outcome"] == "succeeded"
        and receipt["id"] in verifications
    ]


def remember_plan(root: Path, lesson: str, receipt_id: str | None = None, scope: str = "auto") -> dict[str, Any]:
    """Return a non-persistent plan; Saga and adapter writes remain explicit."""
    load_config(root)
    normalized = lesson.strip()
    if not normalized or len(normalized) > 1_000:
        raise ProjectError("remember lesson must be non-empty and 1000 characters or fewer")
    classification = intelligence.classify(normalized, scope)
    lesson_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if classification["destination"] in {"trellis", "human-review"}:
        suggestions = [
            {"targetType": "task-note", "pathHint": ".trellis/tasks/<current>/"},
            {"targetType": "durable-spec", "pathHint": ".trellis/spec/<package>/<layer>/"},
            {"targetType": "architecture-decision", "pathHint": "project ADR location"},
        ]
        return {
            "state": "project-plan",
            "destination": classification["destination"],
            "classification": classification,
            "lessonSha256": lesson_digest,
            "suggestions": suggestions,
            "discoveryCommand": "hellodev trellis intent task-current" if (root / ".trellis").is_dir() else "hellodev task list",
            "writeCommand": None,
            "reason": "HelloDev does not invent a Trellis spec or ADR write command.",
            "persisted": False,
        }
    candidates = _verified_evidence(root)
    if receipt_id is None:
        return {
            "state": "evidence-required",
            "destination": "nocturne",
            "lessonSha256": lesson_digest,
            "evidenceCandidates": candidates,
            "next": "Run remember again with an explicit --receipt from the verified candidate list.",
            "persisted": False,
        }
    try:
        evidence_plan = intelligence.persistence_plan(root, "nocturne", receipt_id)
    except ProjectError as error:
        return {
            "state": "evidence-invalid",
            "destination": "nocturne",
            "lessonSha256": lesson_digest,
            "evidenceReceipt": receipt_id,
            "reason": str(error),
            "evidenceCandidates": candidates,
            "persisted": False,
        }
    configured = nocturne.status(root)["state"] == "configured"
    return {
        "state": "saga-plan-ready" if configured else "configuration-required",
        "destination": "nocturne",
        "lessonSha256": lesson_digest,
        "evidence": evidence_plan,
        "nocturneConfigured": configured,
        "sagaPlan": {
            "title": "Preserve verified cross-project lesson",
            "evidenceReceipt": receipt_id,
            "steps": ["create Saga", "attach evidence", "verify evidence", "prepare Nocturne write"],
        },
        "writeParameters": {"tool": "create_memory", "arguments": {"content": normalized}} if configured else None,
        "persisted": False,
    }
