"""Normalize one immediately usable next action on command responses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .command_rendering import command_line


def _guidance(root: Path, value: dict[str, Any]) -> dict[str, Any] | None:
    state = value.get("state")
    reason = str(value.get("reasonCode", ""))
    if state == "awaiting-confirmation":
        return {
            "schemaVersion": 1,
            "disclosureLevel": "confirmation",
            "instruction": "Explain the exact action, scope, and risk to the user; execute only the returned resumeCommand after explicit approval.",
            "doNot": ["guess another command", "reuse an approval token", "call the native Trellis CLI"],
        }
    if state == "check-required" or reason == "finish-requires-checking-phase":
        return {
            "schemaVersion": 1,
            "disclosureLevel": "repair",
            "instruction": "Finish is intentionally blocked before external mutation. Execute only nextAction, then continue from the next returned action.",
            "doNot": ["retry finish", "complete the Trellis task directly", "edit .hellodev state"],
        }
    diagnostic = (
        "recovery" in reason
        or "unchanged-failure" in reason
        or "strict" in reason
        or state in {"trellis-completion-failed", "recovery-required"}
    )
    if diagnostic:
        return {
            "schemaVersion": 1,
            "disclosureLevel": "diagnostic",
            "instruction": "Run nextAction once. If the same reasonCode remains after two attempts, stop changing state and show the user the diagnostic outputs.",
            "diagnosticCommands": [
                command_line(root, "next"),
                command_line(root, "resume"),
                command_line(root, "status", "--verbose"),
            ],
            "escalation": "Ask the user to review the task binding, lifecycle phase, and latest receipt; do not invent a bypass.",
        }
    return None


def attach(root: Path, value: dict[str, Any]) -> dict[str, Any]:
    if "nextAction" in value:
        guidance = _guidance(root, value)
        if guidance is not None:
            value["agentGuidance"] = guidance
        return value
    selected = value.get("resumeCommand") or value.get("next")
    if isinstance(selected, dict) and isinstance(selected.get("command"), str):
        action = selected
        source = "embedded-decision"
    elif isinstance(selected, str) and selected:
        action = {
            "schemaVersion": 1,
            "command": selected,
            "reasonCode": value.get("reasonCode", "response-continuation"),
            "suggestedLevel": "L1",
            "executionPerformed": False,
        }
        source = "embedded-command"
    else:
        action = {
            "schemaVersion": 1,
            "command": command_line(root, "next"),
            "reasonCode": "read-current-project-state",
            "suggestedLevel": "L0",
            "executionPerformed": False,
        }
        source = "explicit-next-hop"
    value["nextAction"] = {
        **action,
        "chainSource": source,
        "authoritative": True,
        "executionPerformed": False,
    }
    guidance = _guidance(root, value)
    if guidance is not None:
        value["agentGuidance"] = guidance
    return value


__all__ = ["attach"]
