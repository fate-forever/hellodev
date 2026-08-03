"""Bounded, dependency-free TypeScript declaration impact hints."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .context_runtime.contracts import RepositoryFile


MAX_FILES = 800
MAX_BYTES = 8 * 1024 * 1024
_EXPORT = re.compile(
    r"\bexport\s+(?:declare\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)"
)


def change_impact(repository_files: Iterable[RepositoryFile], changed_files: Iterable[RepositoryFile]) -> dict[str, Any]:
    repository = tuple(item for item in repository_files if item.path.lower().endswith((".ts", ".tsx")))
    changed = tuple(item for item in changed_files if item.path.lower().endswith((".ts", ".tsx")))
    base = {
        "provider": "native-typescript-declaration-index",
        "changedTypeScriptFileCount": len(changed),
        "exportedDeclarationCount": 0,
        "referencingFileCount": 0,
        "crossFileReferenceCount": 0,
        "wideImpact": False,
        "rawSymbolsExposed": False,
        "rawPathsExposed": False,
    }
    if not changed:
        return {**base, "state": "not-applicable", "reasonCode": "no-changed-typescript-files"}
    if len(repository) > MAX_FILES or sum(item.size for item in repository) > MAX_BYTES:
        return {**base, "state": "bounded", "reasonCode": "typescript-index-budget-exceeded"}
    names = {match.group(1) for item in changed for match in _EXPORT.finditer(item.text)}
    changed_paths = {item.path for item in changed}
    referencing_files = 0
    cross_references = 0
    for item in repository:
        if item.path in changed_paths:
            continue
        matches = sum(len(re.findall(rf"\b{re.escape(name)}\b", item.text)) for name in names)
        if matches:
            referencing_files += 1
            cross_references += matches
    return {
        **base,
        "state": "ready",
        "reasonCode": "bounded-exported-declaration-impact",
        "exportedDeclarationCount": len(names),
        "referencingFileCount": referencing_files,
        "crossFileReferenceCount": cross_references,
        "wideImpact": referencing_files >= 4 or cross_references >= 12,
    }


__all__ = ["change_impact"]
