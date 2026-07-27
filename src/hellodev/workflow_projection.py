"""Read-only authority projection for local and Trellis-backed projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import contracts, lifecycle
from .project import ProjectError, project_initialized


def status(root: Path) -> dict[str, Any]:
    marker = root / ".trellis"
    if marker.is_symlink():
        raise ProjectError("refusing symlinked .trellis for authority projection")
    trellis_present = marker.is_dir()
    if not trellis_present:
        return {
            "schemaVersion": 1,
            "mode": "local",
            "authoritativeSystem": "hellodev",
            "lifecycleAuthority": "hellodev",
            "projectionOnly": False,
            "reasonCode": "trellis-absent",
        }
    tasks = contracts.list_trellis_tasks(root)
    try:
        current = contracts.current_work_item(root) if project_initialized(root) else None
    except ProjectError:
        return {
            "schemaVersion": 1,
            "mode": "hybrid-recovery",
            "authoritativeSystem": "trellis",
            "lifecycleAuthority": "trellis-task-spec-gate",
            "projectionOnly": True,
            "reasonCode": "work-item-store-invalid",
            "trellisTaskCount": len(tasks),
            "nativeTask": None,
            "helloDevPhase": None,
        }
    if current is not None and current.get("backend") == "trellis" and current.get("nativeRef") in tasks:
        return {
            "schemaVersion": 1,
            "mode": "trellis-native",
            "authoritativeSystem": "trellis",
            "lifecycleAuthority": "trellis-task-spec-gate",
            "projectionOnly": True,
            "reasonCode": "valid-current-trellis-work-item",
            "nativeTask": current["nativeRef"],
            "helloDevPhase": lifecycle.status(root)["phase"],
        }
    reason = "trellis-work-item-missing"
    if current is not None and current.get("backend") != "trellis":
        reason = "current-work-item-is-local"
    elif current is not None:
        reason = "trellis-work-item-target-missing"
    elif len(tasks) > 1:
        reason = "multiple-unbound-trellis-tasks"
    return {
        "schemaVersion": 1,
        "mode": "hybrid-recovery",
        "authoritativeSystem": "trellis",
        "lifecycleAuthority": "trellis-task-spec-gate",
        "projectionOnly": True,
        "reasonCode": reason,
        "trellisTaskCount": len(tasks),
        "nativeTask": current.get("nativeRef") if current is not None and current.get("backend") == "trellis" else None,
        "helloDevPhase": lifecycle.status(root)["phase"] if project_initialized(root) else None,
    }


__all__ = ["status"]
