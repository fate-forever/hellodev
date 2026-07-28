"""Dependency-free, read-only semantic hints for the native Context Plane."""

from __future__ import annotations

import ast
import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import RepositoryFile


MAX_SYMBOL_SNIPPET_BYTES = 1_600
MAX_INDEX_CACHE_ENTRIES = 8
MAX_IMPACT_FILES = 500
MAX_IMPACT_BYTES = 4 * 1024 * 1024
_EXPLICIT_PREFIXES = ("definition ", "find symbol ", "symbol ")
_QUERY_NOISE = {
    "class", "def", "definition", "find", "function", "implementation", "method", "of", "symbol", "the", "where",
}


@dataclass(frozen=True, slots=True)
class _Symbol:
    path: str
    file_sha256: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    text: str
    complete: bool


_INDEX_CACHE: "OrderedDict[str, tuple[tuple[_Symbol, ...], int, int]]" = OrderedDict()
_INDEX_LOCK = threading.Lock()


def clear_cache() -> None:
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


def _cache_key(files: Iterable[RepositoryFile]) -> str:
    material = "\n".join(f"{item.path}\0{item.sha256}" for item in files if item.path.lower().endswith(".py"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _query_candidates(query: str) -> tuple[str, ...]:
    lowered = query.casefold().strip()
    explicit = any(lowered.startswith(prefix) for prefix in _EXPLICIT_PREFIXES)
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]{0,127}", query)
    selected: list[str] = []
    for token in tokens:
        if token.casefold() in _QUERY_NOISE:
            continue
        symbol_like = explicit or "." in token or "_" in token or any(character.isupper() for character in token)
        if symbol_like and token not in selected:
            selected.append(token)
    return tuple(selected[:8])


def looks_like_symbol_query(query: str) -> bool:
    return bool(_query_candidates(query))


def _bounded_source(file: RepositoryFile, node: ast.AST) -> tuple[str, bool]:
    start = max(1, int(getattr(node, "lineno", 1)))
    end = max(start, int(getattr(node, "end_lineno", start)))
    lines = list(file.lines[start - 1:end])
    selected: list[str] = []
    used = 0
    for line in lines:
        encoded = (line + "\n").encode("utf-8")
        if selected and used + len(encoded) > MAX_SYMBOL_SNIPPET_BYTES:
            break
        if not selected and len(encoded) > MAX_SYMBOL_SNIPPET_BYTES:
            return "", False
        selected.append(line)
        used += len(encoded)
    return "\n".join(selected), len(selected) == len(lines)


def _symbols_for_file(file: RepositoryFile) -> tuple[tuple[_Symbol, ...], int]:
    if not file.path.lower().endswith(".py"):
        return (), 0
    try:
        tree = ast.parse(file.text, filename=file.path)
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return (), 1
    found: list[_Symbol] = []

    def visit(body: list[ast.stmt], parents: tuple[str, ...]) -> None:
        for node in body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            kind = "class" if isinstance(node, ast.ClassDef) else "async-function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            qualified = ".".join((*parents, node.name))
            text, complete = _bounded_source(file, node)
            if text:
                found.append(
                    _Symbol(
                        path=file.path,
                        file_sha256=file.sha256,
                        name=node.name,
                        qualified_name=qualified,
                        kind=kind,
                        start_line=int(node.lineno),
                        end_line=int(getattr(node, "end_lineno", node.lineno)),
                        text=text,
                        complete=complete,
                    )
                )
            visit(node.body, (*parents, node.name))

    visit(tree.body, ())
    return tuple(found), 0


def _index(files: tuple[RepositoryFile, ...]) -> tuple[tuple[_Symbol, ...], int, bool]:
    key = _cache_key(files)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None:
            _INDEX_CACHE.move_to_end(key)
            return cached[0], cached[1], True
    symbols: list[_Symbol] = []
    parse_errors = 0
    parsed_files = 0
    for file in files:
        if not file.path.lower().endswith(".py"):
            continue
        parsed_files += 1
        items, errors = _symbols_for_file(file)
        symbols.extend(items)
        parse_errors += errors
    value = (tuple(symbols), parse_errors, parsed_files)
    with _INDEX_LOCK:
        _INDEX_CACHE[key] = value
        _INDEX_CACHE.move_to_end(key)
        while len(_INDEX_CACHE) > MAX_INDEX_CACHE_ENTRIES:
            _INDEX_CACHE.popitem(last=False)
    return value[0], value[1], False


def find_definitions(files: tuple[RepositoryFile, ...], query: str, path_prefix: str = ".") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = _query_candidates(query)
    if not candidates:
        return [], {
            "state": "not-requested",
            "provider": "native-python-ast",
            "reasonCode": "query-not-symbol-shaped",
            "parsedFileCount": 0,
            "parseErrorCount": 0,
            "matchCount": 0,
            "cacheHit": False,
        }
    lowered = tuple(value.casefold() for value in candidates)
    terminal_names = {value.rsplit(".", 1)[-1] for value in lowered}
    candidate_files = tuple(
        file
        for file in files
        if file.path.lower().endswith(".py")
        and any(name in file.text.casefold() for name in terminal_names)
    )
    symbols, parse_errors, cache_hit = _index(candidate_files)
    matched: list[tuple[int, _Symbol]] = []
    for symbol in symbols:
        name = symbol.name.casefold()
        qualified = symbol.qualified_name.casefold()
        score = 0
        for value in lowered:
            if value == qualified:
                score = max(score, 240)
            elif value == name:
                score = max(score, 220)
            elif qualified.endswith("." + value):
                score = max(score, 200)
        if score:
            matched.append((score, symbol))
    matched.sort(key=lambda item: (-item[0], item[1].path, item[1].start_line, item[1].qualified_name))
    items: list[dict[str, Any]] = []
    for score, symbol in matched:
        path = symbol.path if path_prefix == "." else f"{path_prefix}/{symbol.path}"
        text_bytes = symbol.text.encode("utf-8")
        items.append(
            {
                "sourceType": "Repository symbol",
                "authority": "repository",
                "path": path,
                "startLine": symbol.start_line,
                "endLine": symbol.end_line,
                "fileSha256": symbol.file_sha256,
                "snippetSha256": hashlib.sha256(text_bytes).hexdigest(),
                "score": score,
                "text": symbol.text,
                "complete": symbol.complete,
                "symbol": {
                    "name": symbol.name,
                    "qualifiedName": symbol.qualified_name,
                    "kind": symbol.kind,
                    "provider": "native-python-ast",
                    "relation": "definition",
                },
            }
        )
    parsed_files = len(candidate_files)
    return items, {
        "state": "matched" if items else "fallback",
        "provider": "native-python-ast",
        "reasonCode": "symbol-definition-matched" if items else "symbol-not-found",
        "parsedFileCount": parsed_files,
        "parseErrorCount": parse_errors,
        "matchCount": len(items),
        "cacheHit": cache_hit,
    }


def change_impact(repository_files: tuple[RepositoryFile, ...], changed_files: tuple[RepositoryFile, ...]) -> dict[str, Any]:
    changed_python = tuple(item for item in changed_files if item.path.lower().endswith(".py"))
    if not changed_python:
        return {
            "state": "not-applicable",
            "provider": "native-python-ast",
            "changedPythonFileCount": 0,
            "definedSymbolCount": 0,
            "referencingFileCount": 0,
            "crossFileReferenceCount": 0,
            "parseErrorCount": 0,
            "wideImpact": False,
            "rawSymbolsExposed": False,
            "rawPathsExposed": False,
        }
    python_files = tuple(item for item in repository_files if item.path.lower().endswith(".py"))
    if len(python_files) > MAX_IMPACT_FILES or sum(item.size for item in python_files) > MAX_IMPACT_BYTES:
        return {
            "state": "bounded",
            "provider": "native-python-ast",
            "changedPythonFileCount": len(changed_python),
            "definedSymbolCount": 0,
            "referencingFileCount": 0,
            "crossFileReferenceCount": 0,
            "parseErrorCount": 0,
            "wideImpact": False,
            "rawSymbolsExposed": False,
            "rawPathsExposed": False,
        }
    changed_symbols, changed_errors, _ = _index(changed_python)
    names = {item.name for item in changed_symbols}
    changed_paths = {item.path for item in changed_python}
    reference_count = 0
    referencing_files = 0
    parse_errors = changed_errors
    if names:
        for file in repository_files:
            if file.path in changed_paths or not file.path.lower().endswith(".py"):
                continue
            try:
                tree = ast.parse(file.text, filename=file.path)
            except (SyntaxError, ValueError, TypeError, MemoryError):
                parse_errors += 1
                continue
            hits = sum(
                1
                for node in ast.walk(tree)
                if (isinstance(node, ast.Name) and node.id in names)
                or (isinstance(node, ast.Attribute) and node.attr in names)
            )
            if hits:
                referencing_files += 1
                reference_count += hits
    return {
        "state": "ready" if names else "no-definitions",
        "provider": "native-python-ast",
        "changedPythonFileCount": len(changed_python),
        "definedSymbolCount": len(names),
        "referencingFileCount": referencing_files,
        "crossFileReferenceCount": reference_count,
        "parseErrorCount": parse_errors,
        "wideImpact": referencing_files >= 4 or reference_count >= 12,
        "rawSymbolsExposed": False,
        "rawPathsExposed": False,
    }


__all__ = ["change_impact", "clear_cache", "find_definitions", "looks_like_symbol_query"]
