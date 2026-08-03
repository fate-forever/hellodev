"""Deterministic local-first recall and evidence-explicit remember planning."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility without a runtime dependency.
    tomllib = None  # type: ignore[assignment]

from . import intelligence, receipts
from .adapters import nocturne
from .project import ProjectError, ProjectPaths, load_config


MAX_FILES = 24
MAX_FILE_BYTES = 16_000
MAX_TOTAL_BYTES = 64_000
MAX_RESULTS = 5
MAX_EXCERPT_CHARS = 320
MAX_MEMORY_ITEMS = 5
MAX_MEMORY_ITEM_CHARS = 1_200
DEFAULT_TECHNICAL_MEMORY_DOMAIN = "core"
RUNTIME_RECALL_TERMS = (
    "vitest", "tsc", "typescript", "pytest", "pyright", "mypy", "ruff",
    "jest", "playwright", "eslint", "vite", "react",
)
QUERY_TOKEN = re.compile(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]")
MEMORY_INJECTION_PATTERN = re.compile(
    r"ignore\s+(all\s+)?previous|system\s+prompt|developer\s+message|"
    r"execute\s+(this\s+)?command|resumecommand|approve-[a-z0-9:-]+|"
    r"忽略.{0,12}(指令|提示)|系统提示|执行.{0,12}命令",
    re.IGNORECASE,
)
PROJECT_SCOPE_TOKEN = re.compile(r"[^A-Za-z0-9._/-]+")
TOML_SECTION = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")
TOML_BASIC_NAME = re.compile(r'^\s*name\s*=\s*"([^"\\]*)"\s*(?:#.*)?$')
TOML_LITERAL_NAME = re.compile(r"^\s*name\s*=\s*'([^']*)'\s*(?:#.*)?$")


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


def _project_recall_scope(root: Path) -> dict[str, Any]:
    name: str | None = None
    source = "directory"
    pyproject = root / "pyproject.toml"
    package_json = root / "package.json"
    if pyproject.is_file() and not pyproject.is_symlink() and pyproject.stat().st_size <= 64 * 1024:
        try:
            text = pyproject.read_text(encoding="utf-8")
            if tomllib is not None:
                value = tomllib.loads(text)
                candidate = value.get("project", {}).get("name") if isinstance(value, dict) else None
            else:
                candidate = _python_310_project_name(text)
            if isinstance(candidate, str):
                name, source = candidate, "pyproject"
        except (OSError, UnicodeError, ValueError):
            pass
    if name is None and package_json.is_file() and not package_json.is_symlink() and package_json.stat().st_size <= 64 * 1024:
        try:
            value = json.loads(package_json.read_text(encoding="utf-8"))
            candidate = value.get("name") if isinstance(value, dict) else None
            if isinstance(candidate, str):
                name, source = candidate, "package-json"
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    normalized = PROJECT_SCOPE_TOKEN.sub("-", (name or root.name).strip()).strip("-./").casefold()
    if not normalized or normalized in {"all", "boot", "default", "global"}:
        normalized = "project-" + hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
        source = "root-hash"
    project_slug = normalized[:56].rstrip("-./")
    namespace = ("project-" + project_slug)[:64].rstrip("-./")
    return {
        "domain": DEFAULT_TECHNICAL_MEMORY_DOMAIN,
        "namespaceScope": namespace,
        "limit": 3,
        "source": source,
        "domainSource": "technical-memory-default",
        "namespaceEnforcement": "audit-only-upstream-contract-unavailable",
    }


def _python_310_project_name(text: str) -> str | None:
    """Read only a simple PEP 621 project name when tomllib is unavailable."""
    section: str | None = None
    for line in text.splitlines():
        section_match = TOML_SECTION.fullmatch(line)
        if section_match:
            section = section_match.group(1).strip()
            continue
        if section != "project":
            continue
        for pattern in (TOML_BASIC_NAME, TOML_LITERAL_NAME):
            match = pattern.fullmatch(line)
            if match:
                return match.group(1)
    return None


def _runtime_recall_terms(root: Path, query: str) -> list[str]:
    text = ""
    for candidate in (root / "package.json", root / "pyproject.toml"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size > 64 * 1024:
                continue
            text += "\n" + candidate.read_text(encoding="utf-8").casefold()
        except (OSError, UnicodeError):
            continue
    folded_query = query.casefold()
    return [term for term in RUNTIME_RECALL_TERMS if term in text and term not in folded_query][:4]


def _memory_query(root: Path, query: str) -> tuple[str, list[str]]:
    terms = _runtime_recall_terms(root, query)
    selected = query
    for term in terms:
        candidate = f"{selected} {term}"
        if len(candidate) > 1_000:
            break
        selected = candidate
    return selected, terms


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
    derived = _project_recall_scope(root)
    selected_domain = domain if domain is not None else derived["domain"]
    selected_limit = limit if limit is not None else derived["limit"]
    selected_namespace = namespace_scope if namespace_scope is not None else derived["namespaceScope"]
    memory_query, enrichment_terms = _memory_query(root, _query(query))
    plan = intelligence.retrieval_plan(
        root,
        "cross-project",
        memory_query,
        "L0",
        selected_domain,
        selected_limit,
        selected_namespace,
    )
    return {
        "state": "memory-plan-required",
        "local": local,
        "nocturne": plan["nocturne"],
        "scopeDerivation": {
            "state": "derived" if domain is None or limit is None or namespace_scope is None else "explicit",
            "source": derived["source"],
            "domainDerived": domain is None,
            "limitDerived": limit is None,
            "namespaceDerived": namespace_scope is None,
            "domainSource": "explicit" if domain is not None else derived["domainSource"],
            "namespaceEnforcement": derived["namespaceEnforcement"],
        },
        "queryEnrichment": {
            "state": "applied" if enrichment_terms else "not-needed",
            "terms": enrichment_terms,
            "source": "bounded-project-runtime-manifest",
            "automaticRetry": False,
        },
        "sourceLabel": "Long-term memory",
        "authority": "non-authoritative advisory context",
        "persisted": False,
    }


def project_memory_result(result: dict[str, Any], local: dict[str, Any], limit: int | None) -> dict[str, Any]:
    """Return bounded advisory memory text without exposing the raw MCP envelope.

    Receipts still bind the full raw result by SHA-256.  This projection is
    ephemeral and deliberately cannot grant authority or claim freshness.
    """
    if not isinstance(result, dict):
        raise ProjectError("Nocturne result must be an object")
    raw_digest = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload = result.get("result")
    blocks = payload.get("content", []) if isinstance(payload, dict) else []
    selected_limit = min(MAX_MEMORY_ITEMS, limit if type(limit) is int and limit > 0 else MAX_MEMORY_ITEMS)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
            continue
        normalized = block["text"].strip()
        if not normalized or normalized.casefold() in {"[]", "{}", "null", "no memories found", "no memories found."}:
            continue
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        injection = MEMORY_INJECTION_PATTERN.search(normalized) is not None
        truncated = len(normalized) > MAX_MEMORY_ITEM_CHARS
        item: dict[str, Any] = {
            "sourceLabel": "Long-term memory",
            "contentSha256": digest,
            "freshness": "unavailable",
            "authority": "advisory-only",
            "instructionAuthority": "none",
            "quarantined": injection,
            "reasonCodes": ["instruction-like-memory-quarantined"] if injection else [],
            "truncated": truncated,
        }
        if not injection:
            item["text"] = normalized[:MAX_MEMORY_ITEM_CHARS]
        items.append(item)
        if len(items) >= selected_limit:
            break
    quarantined = sum(1 for item in items if item["quarantined"])
    accepted = len(items) - quarantined
    return {
        "state": "accepted" if accepted else "zero-result",
        "reasonCodes": [] if accepted else ["nocturne-zero-accepted-items"],
        "sourceLabel": "Long-term memory",
        "authority": "non-authoritative advisory context",
        "instructionAuthority": "none",
        "rawResultSha256": raw_digest,
        "rawResultExposed": False,
        "items": items,
        "acceptedCount": accepted,
        "quarantinedCount": quarantined,
        "deduplicated": True,
        "freshnessPolicy": "unknown-is-not-current",
        "conflictPolicy": "repository-and-trellis-facts-win",
        "conflictState": "repository-authority-preferred" if local.get("results") else "no-local-evidence",
        "limits": {"items": selected_limit, "itemChars": MAX_MEMORY_ITEM_CHARS},
        "persisted": False,
        "automaticRetryPerformed": False,
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
