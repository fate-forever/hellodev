"""Deterministic query planning and budget-before-render composition."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..project import ProjectError, ProjectPaths, utc_now, write_json
from . import cursor as cursor_contract
from . import semantic
from .contracts import RepositoryFile, RepositoryMarker
from .native import EXCLUDED_DIRECTORIES, metadata_unchanged, snapshot


MIN_PAGE_BYTES = 256
MAX_PAGE_BYTES = 48_000
MAX_QUERY_CHARS = 512
MAX_SNIPPET_BYTES = 1200
MAX_RESULT_SESSIONS = 8
MAX_RESULT_SESSION_RESULTS = 2000
MAX_RESULT_SESSION_BYTES = 4 * 1024 * 1024
MAX_RESULT_SESSION_CACHE_BYTES = 8 * 1024 * 1024
RESULT_SESSION_TTL_SECONDS = 300.0
PACKAGE_MARKERS = {"pyproject.toml", "package.json", "cargo.toml", "go.mod"}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
STATE_SKIP_REASONS = {
    "binary-content", "encoding-or-read-error", "excluded-directory", "file-limit",
    "file-too-large", "gitignore", "non-regular", "non-text-or-sensitive",
    "scan-byte-limit", "symlink-directory", "symlink-file", "unsafe-path",
}
STOP_WORDS = {
    "about", "after", "before", "change", "code", "from", "into", "project", "task", "that", "the",
    "this", "with", "修改", "修复", "实现", "功能", "代码", "项目", "任务", "一个", "这个", "进行",
}


@dataclass(frozen=True, slots=True)
class _ResultSession:
    identifier: str
    created_at: float
    root_sha256: str
    focus_root: str
    snapshot: str
    snapshot_state: str
    scope: str
    query: str
    candidates: tuple[dict[str, Any], ...]
    markers: tuple[RepositoryMarker, ...]
    scanned_file_count: int
    scanned_bytes: int
    skipped: tuple[tuple[str, int], ...]
    retrieval: dict[str, Any]
    byte_size: int


_RESULT_SESSIONS: "OrderedDict[str, _ResultSession]" = OrderedDict()
_RESULT_SESSION_LOCK = threading.Lock()


def _session_bytes(candidates: tuple[dict[str, Any], ...], markers: tuple[RepositoryMarker, ...]) -> int:
    result_bytes = len(json.dumps(candidates, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    marker_bytes = sum(len(marker.path.encode("utf-8")) + 48 for marker in markers)
    return result_bytes + marker_bytes


def _prune_sessions(now: float) -> None:
    expired = [
        identifier
        for identifier, session in _RESULT_SESSIONS.items()
        if now - session.created_at > RESULT_SESSION_TTL_SECONDS
    ]
    for identifier in expired:
        _RESULT_SESSIONS.pop(identifier, None)
    while len(_RESULT_SESSIONS) > MAX_RESULT_SESSIONS:
        _RESULT_SESSIONS.popitem(last=False)
    while _RESULT_SESSIONS and sum(session.byte_size for session in _RESULT_SESSIONS.values()) > MAX_RESULT_SESSION_CACHE_BYTES:
        _RESULT_SESSIONS.popitem(last=False)


def _store_session(session: _ResultSession) -> bool:
    if len(session.candidates) > MAX_RESULT_SESSION_RESULTS or session.byte_size > MAX_RESULT_SESSION_BYTES:
        return False
    with _RESULT_SESSION_LOCK:
        _prune_sessions(time.monotonic())
        _RESULT_SESSIONS[session.identifier] = session
        _RESULT_SESSIONS.move_to_end(session.identifier)
        _prune_sessions(time.monotonic())
        return session.identifier in _RESULT_SESSIONS


def _load_session(
    *, identifier: str | None, root: Path, focus_root: Path, snapshot_id: str,
    query: str, scope: str,
) -> _ResultSession | None:
    if identifier is None:
        return None
    now = time.monotonic()
    with _RESULT_SESSION_LOCK:
        _prune_sessions(now)
        session = _RESULT_SESSIONS.get(identifier)
        if session is None:
            return None
        if (
            session.root_sha256 != cursor_contract.root_digest(root)
            or session.focus_root != _relative_focus(root, focus_root)
            or session.snapshot != snapshot_id
            or session.query != query
            or session.scope != scope
        ):
            _RESULT_SESSIONS.pop(identifier, None)
            return None
    if not metadata_unchanged(focus_root, session.markers):
        with _RESULT_SESSION_LOCK:
            _RESULT_SESSIONS.pop(identifier, None)
        return None
    with _RESULT_SESSION_LOCK:
        if identifier in _RESULT_SESSIONS:
            _RESULT_SESSIONS.move_to_end(identifier)
    return session


def clear_result_sessions() -> None:
    with _RESULT_SESSION_LOCK:
        _RESULT_SESSIONS.clear()


def _safe_nested(root: Path, candidate: Path) -> Path | None:
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
        relative = resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None
    return resolved if resolved.is_dir() else None


def _has_package_marker(path: Path) -> bool:
    for name in PACKAGE_MARKERS:
        marker = path / name
        if marker.is_file() and not marker.is_symlink():
            return True
    git = path / ".git"
    return git.exists() and not git.is_symlink()


def _relative_focus(root: Path, focus_root: Path) -> str:
    relative = focus_root.resolve().relative_to(root.resolve()).as_posix()
    return relative or "."


def _focus_from_cursor(root: Path, relative: str) -> Path:
    candidate = root if relative == "." else root / relative
    safe = _safe_nested(root, candidate)
    if safe is None:
        raise ProjectError("context cursor focus root is unsafe")
    return safe


def _package_identity(path: Path, marker_names: set[str]) -> set[str]:
    identities = {path.name.casefold().replace("-", "_")}
    patterns = (
        re.compile(r"(?m)^\s*name\s*=\s*['\"]([^'\"]+)['\"]\s*$"),
        re.compile(r'"name"\s*:\s*"([^"\\]+)"'),
    )
    for marker_name in sorted(marker_names):
        marker = path / marker_name
        try:
            if marker.is_symlink() or marker.stat().st_size > 64 * 1024:
                continue
            text = marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match is not None:
                identities.add(match.group(1).casefold().replace("-", "_"))
    return identities


def _marker_focus(root: Path, terms: tuple[str, ...]) -> Path | None:
    """Focus only when the query explicitly names one package identity."""
    matches: set[Path] = set()
    for directory, nested, names in os.walk(root, followlinks=False):
        base = Path(directory)
        kept: list[str] = []
        for name in sorted(nested):
            child = base / name
            if name not in EXCLUDED_DIRECTORIES and not child.is_symlink():
                kept.append(name)
        nested[:] = kept
        marker_names = {name.casefold(): name for name in names if name.casefold() in PACKAGE_MARKERS}
        if not marker_names or base == root:
            continue
        safe = _safe_nested(root, base)
        if safe is None:
            continue
        identities = _package_identity(safe, set(marker_names.values()))
        normalized_terms = {term.replace("-", "_") for term in terms}
        if identities & normalized_terms:
            matches.add(safe)
            if len(matches) > 1:
                return None
    return next(iter(matches)) if len(matches) == 1 else None


def _select_focus(root: Path, terms: tuple[str, ...]) -> tuple[Path, str]:
    resolved = root.resolve()
    query_focus = _marker_focus(resolved, terms)
    if query_focus is not None:
        return query_focus, "explicit-package"
    return resolved, "project-root"


def _project_path(focus_relative: str, path: str) -> str:
    return path if focus_relative == "." else f"{focus_relative}/{path}"


def _terms(query: str) -> tuple[str, ...]:
    values = re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{1,63}|[\u3400-\u9fff]{2,16}", query)
    result: list[str] = []
    for value in values:
        normalized = value.casefold()
        candidates = [normalized]
        if len(normalized) >= 8 and normalized.endswith(("ance", "ence")):
            candidates.append(normalized[:-4])
        if re.fullmatch(r"[\u3400-\u9fff]+", normalized) and len(normalized) > 2:
            candidates.extend(normalized[index:index + 2] for index in range(len(normalized) - 1))
        for candidate in candidates:
            if candidate not in STOP_WORDS and candidate not in result:
                result.append(candidate)
    return tuple(result[:16])


def _in_scope(file: RepositoryFile, scope: str) -> bool:
    suffix = Path(file.path).suffix.lower()
    is_doc = suffix in DOC_SUFFIXES or file.path.lower().startswith("docs/")
    if scope == "docs":
        return is_doc
    if scope == "code":
        return not is_doc and not file.path.startswith(".trellis/")
    return True


def _snippet(file: RepositoryFile, line_index: int) -> tuple[int, int, str] | None:
    if not file.lines:
        return None
    start = max(0, line_index - 1)
    end = min(len(file.lines), line_index + 2)
    while start < end:
        text = "\n".join(file.lines[start:end])
        if len(text.encode("utf-8")) <= MAX_SNIPPET_BYTES:
            return start + 1, end, text
        if end - start == 1:
            return None
        if end - line_index > line_index - start:
            end -= 1
        else:
            start += 1
    return None


def _rank(file: RepositoryFile, query: str, terms: tuple[str, ...]) -> dict[str, Any] | None:
    path_value = file.path.casefold()
    query_value = query.casefold()
    line_scores: list[tuple[int, int]] = []
    code_term_scores: dict[str, int] = {}
    commentary_term_scores: dict[str, int] = {}
    for index, line in enumerate(file.lines):
        lowered = line.casefold()
        counts = {term: lowered.count(term) for term in terms}
        stripped = lowered.lstrip()
        commentary = stripped.startswith(("#", "//", "/*", "*", "'''", '\"\"\"'))
        declaration = stripped.startswith(("def ", "async def ", "class "))
        weight = 1 if commentary else 12 if declaration else 4
        term_scores = commentary_term_scores if commentary else code_term_scores
        for term, count in counts.items():
            if count:
                term_scores[term] = term_scores.get(term, 0) + count * weight
        score = sum(counts.values()) * weight
        if query_value in lowered:
            score += 2 if commentary else 8
        if score:
            line_scores.append((score, index))
    path_hits = sum(1 for term in terms if term in path_value)
    if query_value in path_value:
        path_hits += 4
    if not line_scores and not path_hits:
        return None
    best_index = max(line_scores, default=(0, 0), key=lambda item: (item[0], -item[1]))[1]
    snippet = _snippet(file, best_index)
    if snippet is None:
        return None
    start, end, text = snippet
    snippet_bytes = text.encode("utf-8")
    return {
        "sourceType": "Repository fact",
        "authority": "repository",
        "path": file.path,
        "startLine": start,
        "endLine": end,
        "fileSha256": file.sha256,
        "snippetSha256": hashlib.sha256(snippet_bytes).hexdigest(),
        "score": (
            path_hits * 30
            + sum(min(score, 24) for score in code_term_scores.values())
            + sum(min(score, 3) for term, score in commentary_term_scores.items() if term not in code_term_scores)
        ),
        "text": text,
        "complete": True,
    }


def _state_path(root: Path) -> Path:
    return ProjectPaths(root).state_dir / "context-plane.json"


def _record(root: Path, result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    value = {
        "schemaVersion": 2,
        "updatedAt": utc_now(),
        "backend": result["backend"],
        "state": result["state"],
        "snapshot": result["snapshot"],
        "querySha256": result["querySha256"],
        "scope": result["scope"],
        "metrics": metrics,
        "retrieval": result["retrieval"],
        "continuationAvailable": result["continuation"] is not None,
        "rawContentPersisted": False,
    }
    write_json(_state_path(root), value)


def status(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {"state": "ready", "backend": "native", "lastQuery": None, "rawContentPersisted": False}
    if path.is_symlink() or not path.is_file():
        raise ProjectError("refusing unsafe Context Plane state")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid Context Plane state: {error}") from error
    allowed_v1 = {
        "schemaVersion", "updatedAt", "backend", "state", "snapshot", "querySha256", "scope",
        "metrics", "continuationAvailable", "rawContentPersisted",
    }
    allowed_v2 = allowed_v1 | {"retrieval"}
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") not in {1, 2}
        or set(value) != (allowed_v2 if value.get("schemaVersion") == 2 else allowed_v1)
    ):
        raise ProjectError("invalid Context Plane state schema")
    metrics = value.get("metrics")
    metric_keys = {
        "scannedFileCount", "scannedBytes", "matchedFileCount", "returnedItemCount",
        "returnedTextBytes", "cacheHit", "pageOffset", "pageSkippedItemCount", "skipCounts",
    }
    if not isinstance(metrics, dict) or set(metrics) != metric_keys:
        raise ProjectError("invalid Context Plane metrics schema")
    digest = re.compile(r"[0-9a-f]{64}")
    timestamp = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]{8,32}Z?")
    if (
        value.get("backend") != "native"
        or value.get("state") not in {"complete", "partial"}
        or not isinstance(value.get("updatedAt"), str)
        or timestamp.fullmatch(value["updatedAt"]) is None
        or not isinstance(value.get("snapshot"), str)
        or digest.fullmatch(value["snapshot"]) is None
        or not isinstance(value.get("querySha256"), str)
        or digest.fullmatch(value["querySha256"]) is None
        or value.get("scope") not in {"project", "code", "docs"}
        or type(value.get("continuationAvailable")) is not bool
        or value.get("rawContentPersisted") is not False
    ):
        raise ProjectError("invalid Context Plane privacy boundary")
    count_keys = metric_keys - {"cacheHit", "skipCounts"}
    if any(type(metrics.get(key)) is not int or not 0 <= metrics[key] <= 100_000_000 for key in count_keys):
        raise ProjectError("invalid Context Plane metrics values")
    if type(metrics.get("cacheHit")) is not bool:
        raise ProjectError("invalid Context Plane metrics values")
    skip_counts = metrics.get("skipCounts")
    if (
        not isinstance(skip_counts, dict)
        or any(
            key not in STATE_SKIP_REASONS or type(count) is not int or not 0 <= count <= 100_000_000
            for key, count in skip_counts.items()
        )
    ):
        raise ProjectError("invalid Context Plane metrics values")
    if value["schemaVersion"] == 2:
        retrieval = value.get("retrieval")
        retrieval_keys = {
            "strategy", "provider", "state", "reasonCode", "symbolMatchCount",
            "parsedFileCount", "parseErrorCount", "cacheHit",
        }
        if (
            not isinstance(retrieval, dict)
            or set(retrieval) != retrieval_keys
            or retrieval.get("strategy") not in {"lexical", "symbol"}
            or retrieval.get("provider") not in {"native-lexical", "native-python-ast"}
            or retrieval.get("state") not in {"matched", "fallback", "not-requested"}
            or not isinstance(retrieval.get("reasonCode"), str)
            or len(retrieval["reasonCode"]) > 64
            or any(
                type(retrieval.get(key)) is not int or not 0 <= retrieval[key] <= 100_000_000
                for key in ("symbolMatchCount", "parsedFileCount", "parseErrorCount")
            )
            or type(retrieval.get("cacheHit")) is not bool
        ):
            raise ProjectError("invalid Context Plane retrieval state")
    projection = {key: value[key] for key in (allowed_v2 if value["schemaVersion"] == 2 else allowed_v1)}
    return {"state": "ready", "backend": "native", "lastQuery": projection, "rawContentPersisted": False}


def build_context(
    root: Path,
    *,
    query: str | None,
    scope: str = "project",
    byte_budget: int,
    cursor: str | None = None,
    persist_metrics: bool = False,
) -> dict[str, Any]:
    if type(byte_budget) is not int or not MIN_PAGE_BYTES <= byte_budget <= MAX_PAGE_BYTES:
        raise ProjectError(f"Context Plane byte budget must be between {MIN_PAGE_BYTES} and {MAX_PAGE_BYTES}")
    cursor_value = cursor_contract.decode(root, cursor) if cursor is not None else None
    if cursor_value is not None:
        if query is not None and query != cursor_value["query"]:
            raise ProjectError("context cursor query mismatch")
        if scope != "project" and scope != cursor_value["scope"]:
            raise ProjectError("context cursor scope mismatch")
        query = cursor_value["query"]
        scope = cursor_value["scope"]
        offset = cursor_value["offset"]
    else:
        offset = 0
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ProjectError("Context Plane query must contain 1-512 characters")
    query = query.strip()
    if scope not in {"project", "code", "docs"}:
        raise ProjectError("Context Plane scope must be project, code, or docs")
    terms = _terms(query)
    if not terms:
        raise ProjectError("Context Plane query is too broad; include a symbol, path, or specific topic")
    if cursor_value is None:
        focus_root, focus_strategy = _select_focus(root, terms)
    else:
        focus_root = _focus_from_cursor(root, cursor_value["focusRoot"])
        focus_strategy = "cursor"
    focus_relative = _relative_focus(root, focus_root)

    session = None
    if cursor_value is not None:
        session = _load_session(
            identifier=cursor_value["resultSession"],
            root=root,
            focus_root=focus_root,
            snapshot_id=cursor_value["snapshot"],
            query=query,
            scope=scope,
        )
    session_hit = session is not None
    reconstructed = cursor_value is not None and session is None
    repository_cache_hit = False
    if session is not None:
        candidates = list(session.candidates)
        snapshot_id = session.snapshot
        snapshot_state = session.snapshot_state
        markers = session.markers
        scanned_file_count = session.scanned_file_count
        scanned_bytes = session.scanned_bytes
        skipped = session.skipped
        retrieval = dict(session.retrieval)
        result_session = session.identifier
    else:
        repository = snapshot(focus_root)
        if cursor_value is not None and cursor_value["snapshot"] != repository.snapshot_id:
            raise ProjectError("context cursor is stale because repository content changed")
        scoped_files = tuple(file for file in repository.files if _in_scope(file, scope))
        semantic_candidates, semantic_state = (
            semantic.find_definitions(scoped_files, query, focus_relative)
            if scope != "docs"
            else ([], {
                "state": "not-requested", "provider": "native-python-ast",
                "reasonCode": "docs-scope", "parsedFileCount": 0,
                "parseErrorCount": 0, "matchCount": 0, "cacheHit": False,
            })
        )
        if semantic_candidates:
            candidates = semantic_candidates
            retrieval = {
                "strategy": "symbol",
                "provider": semantic_state["provider"],
                "state": semantic_state["state"],
                "reasonCode": semantic_state["reasonCode"],
                "symbolMatchCount": semantic_state["matchCount"],
                "parsedFileCount": semantic_state["parsedFileCount"],
                "parseErrorCount": semantic_state["parseErrorCount"],
                "cacheHit": semantic_state["cacheHit"],
            }
        else:
            candidates = []
            for file in scoped_files:
                item = _rank(file, query, terms)
                if item is not None:
                    item["path"] = _project_path(focus_relative, item["path"])
                    candidates.append(item)
            retrieval = {
                "strategy": "lexical",
                "provider": "native-lexical",
                "state": semantic_state["state"],
                "reasonCode": semantic_state["reasonCode"],
                "symbolMatchCount": 0,
                "parsedFileCount": semantic_state["parsedFileCount"],
                "parseErrorCount": semantic_state["parseErrorCount"],
                "cacheHit": semantic_state["cacheHit"],
            }
        candidates.sort(key=lambda item: (-item["score"], item["path"], item["startLine"]))
        snapshot_id = repository.snapshot_id
        snapshot_state = repository.state
        markers = repository.markers
        scanned_file_count = len(repository.files)
        scanned_bytes = repository.scanned_bytes
        skipped = repository.skipped
        repository_cache_hit = repository.cache_hit
        result_session = cursor_value["resultSession"] if cursor_value is not None else secrets.token_hex(16)
    if offset > len(candidates):
        raise ProjectError("context cursor offset exceeds the current result set")

    items: list[dict[str, Any]] = []
    used_bytes = 0
    current = offset
    page_skips = 0
    while current < len(candidates):
        item = candidates[current]
        block = f"## {item['path']}:{item['startLine']}-{item['endLine']}\n{item['text']}\n"
        block_bytes = len(block.encode("utf-8"))
        if used_bytes + block_bytes > byte_budget:
            if items:
                break
            page_skips += 1
            current += 1
            continue
        items.append(item)
        used_bytes += block_bytes
        current += 1

    continuation = None
    state = "complete"
    session_cached = session_hit
    if current < len(candidates):
        state = "partial"
        if session is None:
            candidate_tuple = tuple(candidates)
            session_value = _ResultSession(
                identifier=result_session,
                created_at=time.monotonic(),
                root_sha256=cursor_contract.root_digest(root),
                focus_root=focus_relative,
                snapshot=snapshot_id,
                snapshot_state=snapshot_state,
                scope=scope,
                query=query,
                candidates=candidate_tuple,
                markers=markers,
                scanned_file_count=scanned_file_count,
                scanned_bytes=scanned_bytes,
                skipped=skipped,
                retrieval=dict(retrieval),
                byte_size=_session_bytes(candidate_tuple, markers),
            )
            session_cached = _store_session(session_value)
        continuation = {
            "cursor": cursor_contract.encode(
                root=root,
                snapshot=snapshot_id,
                query=query,
                scope=scope,
                offset=current,
                result_session=result_session,
                focus_root=focus_relative,
            ),
            "remainingEstimate": len(candidates) - current,
            "reasonCode": "context-page-budget-reached",
        }
    query_sha = hashlib.sha256(query.encode("utf-8")).hexdigest()
    result = {
        "schemaVersion": 1,
        "state": state,
        "backend": "native",
        "scope": scope,
        "querySha256": query_sha,
        "snapshot": snapshot_id,
        "snapshotState": snapshot_state,
        "focus": {
            "strategy": focus_strategy,
            "root": focus_relative,
            "projectRoot": focus_relative == ".",
        },
        "retrieval": retrieval,
        "continuationSession": {
            "hit": session_hit,
            "reconstructed": reconstructed,
            "cached": session_cached,
        },
        "items": items,
        "continuation": continuation,
        "metrics": {
            "scannedFileCount": scanned_file_count,
            "scannedBytes": scanned_bytes,
            "matchedFileCount": len(candidates),
            "returnedItemCount": len(items),
            "returnedTextBytes": used_bytes,
            "cacheHit": repository_cache_hit or session_hit,
            "pageOffset": offset,
            "pageSkippedItemCount": page_skips,
            "skipCounts": dict(skipped),
        },
        "readOnly": True,
        "executionPerformed": False,
        "persistencePerformed": persist_metrics,
        "rawContentPersisted": False,
    }
    if persist_metrics:
        _record(root, result)
    return result


__all__ = ["build_context", "clear_result_sessions", "status"]
