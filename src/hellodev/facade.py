"""Read-only projection for HelloDev's daily facade and native escape hatches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import receipts, workflow_projection
from .project import project_initialized


ROUTED_TRELLIS_PREFIX = "intent/"
GENERIC_TRELLIS_OPERATION = "command"


def status(root: str | Path) -> dict[str, Any]:
    """Describe the facade without claiming visibility into external processes."""

    selected = Path(root)
    routed = 0
    escape_hatches = 0
    if project_initialized(selected):
        for receipt in receipts.list_receipts(selected):
            if receipt["adapter"] != "trellis":
                continue
            operation = receipt["operation"]
            if operation.startswith(ROUTED_TRELLIS_PREFIX):
                routed += 1
            elif operation == GENERIC_TRELLIS_OPERATION:
                escape_hatches += 1
        authority = workflow_projection.status(selected)
    else:
        authority = {
            "mode": "uninitialized",
            "authoritativeSystem": "unavailable",
            "projectionOnly": False,
        }
    return {
        "schemaVersion": 1,
        "state": "escape-hatch-observed" if escape_hatches else "unified",
        "dailyNamespace": "hellodev",
        "dailyFlow": "open -> do begin --goal/--acceptance [--requirements-file for multi-item work] -> next -> do; resume on interruption",
        "trellisRole": "authoritative-backend" if authority["authoritativeSystem"] == "trellis" else "not-active",
        "directTrellisPolicy": "advanced-escape-hatch-only",
        "trellisContinueReplacement": "hellodev resume",
        "trellisExecutionPolicy": "adaptive-quick-standard-strict",
        "verificationReuse": "exact-command-scope-snapshot",
        "routedTrellisReceiptCount": routed,
        "observableEscapeHatchCount": escape_hatches,
        "externalDirectTrellisVisibility": "unavailable",
        "reasonCode": "generic-trellis-receipt-observed" if escape_hatches else "hellodev-daily-facade-active",
        "readOnly": True,
        "executionPerformed": False,
        "persistencePerformed": False,
    }


__all__ = ["status"]
