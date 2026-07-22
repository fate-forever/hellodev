"""Deterministic query planning and budget-before-render composition."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..project import ProjectError, ProjectPaths, utc_now, write_json
from . import cursor as cursor_contract
from .contracts import RepositoryFile
from .native import snapshot


MIN_PAGE_BYTES = 256
MAX_PAGE_BYTES = 48_000
MAX_QUERY_CHARS = 512
MAX_SNIPPET_BYTES = 1200
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


def _terms(query: str) -> tuple[str, ...]:
    values = re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{1,63}|[\u3400-\u9fff]{2,16}", query)
    result: list[str] = []
    for value in values:
        normalized = value.casefold()
        candidates = [normalized]
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
    occurrences = 0
    for index, line in enumerate(file.lines):
        lowered = line.casefold()
        score = sum(lowered.count(term) for term in terms)
        if query_value in lowered:
            score += 8
        if score:
            line_scores.append((score, index))
            occurrences += score
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
        "score": path_hits * 20 + min(occurrences, 40),
        "text": text,
        "complete": True,
    }


def _state_path(root: Path) -> Path:
    return ProjectPaths(root).state_dir / "context-plane.json"


def _record(root: Path, result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    value = {
        "schemaVersion": 1,
        "updatedAt": utc_now(),
        "backend": result["backend"],
        "state": result["state"],
        "snapshot": result["snapshot"],
        "querySha256": result["querySha256"],
        "scope": result["scope"],
        "metrics": metrics,
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
    allowed = {
        "schemaVersion", "updatedAt", "backend", "state", "snapshot", "querySha256", "scope",
        "metrics", "continuationAvailable", "rawContentPersisted",
    }
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or set(value) != allowed:
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
    projection = {key: value[key] for key in allowed}
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
    repository = snapshot(root)
    if cursor_value is not None and cursor_value["snapshot"] != repository.snapshot_id:
        raise ProjectError("context cursor is stale because repository content changed")

    candidates: list[dict[str, Any]] = []
    for file in repository.files:
        if not _in_scope(file, scope):
            continue
        item = _rank(file, query, terms)
        if item is not None:
            candidates.append(item)
    candidates.sort(key=lambda item: (-item["score"], item["path"], item["startLine"]))
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
    if current < len(candidates):
        state = "partial"
        continuation = {
            "cursor": cursor_contract.encode(
                root=root,
                snapshot=repository.snapshot_id,
                query=query,
                scope=scope,
                offset=current,
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
        "snapshot": repository.snapshot_id,
        "snapshotState": repository.state,
        "items": items,
        "continuation": continuation,
        "metrics": {
            "scannedFileCount": len(repository.files),
            "scannedBytes": repository.scanned_bytes,
            "matchedFileCount": len(candidates),
            "returnedItemCount": len(items),
            "returnedTextBytes": used_bytes,
            "cacheHit": repository.cache_hit,
            "pageOffset": offset,
            "pageSkippedItemCount": page_skips,
            "skipCounts": dict(repository.skipped),
        },
        "readOnly": True,
        "executionPerformed": False,
        "persistencePerformed": persist_metrics,
        "rawContentPersisted": False,
    }
    if persist_metrics:
        _record(root, result)
    return result


__all__ = ["build_context", "status"]
