"""Privacy-preserving Python override analysis used by guided acceptance."""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from typing import Any

from .context_runtime.contracts import RepositoryFile


ClassEntry = tuple[str, ast.ClassDef]


def _method(node: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            item
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
        ),
        None,
    )


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    values = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    return {item.arg for item in values if item.arg not in {"self", "cls"}}


def _loaded_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    }


def _index(
    files: tuple[RepositoryFile, ...],
) -> tuple[dict[str, list[ClassEntry]], dict[str, dict[str, str]], int]:
    classes: dict[str, list[ClassEntry]] = defaultdict(list)
    aliases_by_path: dict[str, dict[str, str]] = {}
    errors = 0
    for file in files:
        if not file.path.lower().endswith(".py"):
            continue
        try:
            tree = ast.parse(file.text, filename=file.path)
        except (SyntaxError, ValueError, TypeError, MemoryError):
            errors += 1
            continue
        aliases: dict[str, str] = {}
        for item in tree.body:
            if isinstance(item, ast.ClassDef):
                classes[item.name].append((file.path, item))
            elif (
                isinstance(item, ast.Assign)
                and len(item.targets) == 1
                and isinstance(item.targets[0], ast.Name)
                and isinstance(item.value, ast.Name)
            ):
                aliases[item.targets[0].id] = item.value.id
            elif isinstance(item, ast.ImportFrom):
                for imported in item.names:
                    aliases[imported.asname or imported.name] = imported.name
        aliases_by_path[file.path] = aliases
    return classes, aliases_by_path, errors


def _resolved(name: str, aliases: dict[str, str]) -> str:
    seen: set[str] = set()
    while name in aliases and name not in seen:
        seen.add(name)
        name = aliases[name]
    return name


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _resolve_base(
    name: str, path: str, classes: dict[str, list[ClassEntry]], aliases: dict[str, str]
) -> ClassEntry | None:
    target = _resolved(name, aliases)
    candidates = classes.get(target, [])
    local = [entry for entry in candidates if entry[0] == path]
    if len(local) == 1:
        return local[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _fingerprint(path: str, class_name: str, parameter: str) -> str:
    value = f"{path}\0{class_name}\0__init__\0{parameter}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def override_forwarding_analysis(
    repository_files: tuple[RepositoryFile, ...], candidate_files: tuple[RepositoryFile, ...]
) -> dict[str, Any]:
    classes, aliases_by_path, parse_errors = _index(repository_files)
    candidate_paths = {item.path for item in candidate_files if item.path.lower().endswith(".py")}
    issue_hashes: set[str] = set()
    for class_name, entries in classes.items():
        for current_path, current in entries:
            if current_path not in candidate_paths:
                continue
            child_init = _method(current, "__init__")
            if child_init is None or not any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "__init__"
                and isinstance(item.func.value, ast.Call)
                and isinstance(item.func.value.func, ast.Name)
                and item.func.value.func.id == "super"
                for item in ast.walk(child_init)
            ):
                continue
            child_parameters = _parameters(child_init)
            loaded = _loaded_names(child_init)
            aliases = aliases_by_path.get(current_path, {})
            for base in current.bases:
                name = _base_name(base)
                base_entry = None if name is None else _resolve_base(name, current_path, classes, aliases)
                base_init = None if base_entry is None else _method(base_entry[1], "__init__")
                if base_init is None:
                    continue
                for parameter in child_parameters & _parameters(base_init):
                    if parameter not in loaded:
                        issue_hashes.add(_fingerprint(current_path, class_name, parameter))
    return {
        "issueCount": len(issue_hashes),
        "issueHashes": sorted(issue_hashes),
        "parseErrorCount": parse_errors,
        "rawPathsExposed": False,
        "rawSymbolsExposed": False,
    }


__all__ = ["override_forwarding_analysis"]
