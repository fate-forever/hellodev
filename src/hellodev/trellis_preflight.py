"""Bounded local Trellis planning/context preflight with no adapter execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import acceptance, contracts
from .project import ProjectError, resolve_root


def _regular(path: Path, maximum: int = 256 * 1024) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum
    except OSError:
        return False


def _manifest(path: Path, root: Path) -> dict[str, Any]:
    if not _regular(path):
        return {"state": "missing", "entryCount": 0}
    entries = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict) or set(item) != {"file", "reason"}:
                return {"state": "invalid", "entryCount": entries}
            if not isinstance(item["file"], str) or not isinstance(item["reason"], str) or not item["reason"].strip():
                return {"state": "invalid", "entryCount": entries}
            if item["file"] == "_example":
                continue
            candidate = root / item["file"]
            try:
                candidate.resolve(strict=False).relative_to(root.resolve())
            except (OSError, ValueError):
                return {"state": "invalid", "entryCount": entries}
            entries += 1
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"state": "invalid", "entryCount": entries}
    return {"state": "ready" if entries else "seed-only", "entryCount": entries}


def status(root: str | Path) -> dict[str, Any]:
    resolved = resolve_root(root)
    work = contracts.current_work_item(resolved)
    if work is None or work.get("backend") != "trellis":
        return {"schemaVersion": 1, "state": "not-applicable", "required": False, "executionPerformed": False}
    task_root = resolved / ".trellis" / "tasks" / work["nativeRef"]
    try:
        task_root.resolve(strict=True).relative_to((resolved / ".trellis" / "tasks").resolve())
    except (OSError, ValueError) as error:
        raise ProjectError("Trellis preflight task path is missing or unsafe") from error
    if task_root.is_symlink() or not task_root.is_dir():
        raise ProjectError("Trellis preflight task path is missing or unsafe")
    contract = acceptance.current(resolved)
    source = contract.get("requirementsSource") if contract is not None else None
    complex_task = isinstance(source, dict) and source.get("state") == "bound" and int(source.get("lineCount", 0)) >= 5
    artifact_names = ["prd.md", *( ["design.md", "implement.md"] if complex_task else [])]
    artifacts = {name: "ready" if _regular(task_root / name) else "missing" for name in artifact_names}
    manifests = {
        name: _manifest(task_root / name, resolved)
        for name in ("implement.jsonl", "check.jsonl")
    }
    missing = [name for name, state in artifacts.items() if state != "ready"]
    if complex_task:
        missing.extend(name for name, state in manifests.items() if state["state"] not in {"ready"})
    state = "ready" if not missing else "planning-required"
    return {
        "schemaVersion": 1,
        "state": state,
        "required": complex_task,
        "complexTask": complex_task,
        "task": work["nativeRef"],
        "artifacts": artifacts,
        "contextManifests": manifests,
        "missing": missing,
        "action": None if not missing else {
            "kind": "prepare-trellis-task",
            "requiredFiles": missing,
            "then": "follow the chained next action; final native validation remains authoritative",
        },
        "nativeValidationSatisfied": False,
        "qualityGateSatisfied": False,
        "executionPerformed": False,
        "persistencePerformed": False,
    }


__all__ = ["status"]
