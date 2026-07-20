"""Render continuation commands for wheel and self-contained runtimes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from . import components


_COMMAND = re.compile(r"^hellodev(?=\s|$)")
_COMMAND_FIELDS = {
    "abandonCommand",
    "command",
    "commands",
    "discoveryCommand",
    "genericEscapeHatch",
    "inspectionCommand",
    "next",
    "nextCommand",
    "recoveryCommand",
    "repairCommand",
    "resumeCommand",
    "warningCommand",
}


def launcher() -> str:
    """Return the executable users can invoke in the current distribution."""

    root = components.bundle_root()
    if root is None:
        return "hellodev"
    selected = root / "bin" / ("hellodev.cmd" if components.current_target()["os"] == "windows" else "hellodev")
    if not selected.is_file() or components._is_link_or_reparse(selected):
        raise components.ComponentError("verified HelloDev bundle launcher is missing or unsafe")
    return str(selected.resolve())


def command_line(root: Path, *arguments: str) -> str:
    """Render an exact root-bound command that survives a clean PATH."""

    return subprocess.list2cmdline([launcher(), "--root", str(root), *arguments])


def rewrite_text(value: str) -> str:
    """Replace a command token without altering ordinary HelloDev prose."""

    selected = launcher()
    if selected == "hellodev":
        return value
    rendered = subprocess.list2cmdline([selected])
    return _COMMAND.sub(lambda _match: rendered, value)


def rewrite_commands(value: Any, *, _command_context: bool = False) -> Any:
    """Recursively make returned commands executable from a portable bundle."""

    if isinstance(value, str):
        return rewrite_text(value) if _command_context else value
    if isinstance(value, list):
        return [rewrite_commands(item, _command_context=_command_context) for item in value]
    if isinstance(value, tuple):
        return tuple(rewrite_commands(item, _command_context=_command_context) for item in value)
    if isinstance(value, dict):
        return {
            key: rewrite_commands(item, _command_context=key in _COMMAND_FIELDS)
            for key, item in value.items()
        }
    return value


__all__ = ["command_line", "launcher", "rewrite_commands", "rewrite_text"]
