"""Trellis discovery and confirmed structured-command execution."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import re
from pathlib import Path
from typing import Any

from ..approval import consume, prepare
from .. import components
from ..project import ProjectError


READ_PREFIXES = {
    ("--help",),
    ("help",),
    ("--version",),
    ("version",),
    ("status",),
    ("task", "list"),
    ("task", "show"),
    ("context", "show"),
    ("packages", "list"),
}

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
_SCOPES = {"project", "global"}
_INTENT_CATALOG = {
    "task-list": {
        "category": "task",
        "risk": "read",
        "description": "List Trellis task records through its native task script.",
    },
    "task-current": {
        "category": "task",
        "risk": "read",
        "description": "Show the native Trellis current-task pointer and source.",
    },
    "task-create": {
        "category": "task",
        "risk": "write",
        "description": "Create a native Trellis task directory.",
    },
    "task-start": {
        "category": "task",
        "risk": "write",
        "description": "Start a native Trellis task after its own planning gate is satisfied.",
    },
    "task-validate": {
        "category": "gate",
        "risk": "read",
        "description": "Run Trellis task validation as a planning/gate check.",
    },
    "channel-list": {
        "category": "channel",
        "risk": "read",
        "description": "List Trellis collaboration channels in a bounded scope.",
    },
    "channel-thread-rename": {
        "category": "channel",
        "risk": "write",
        "description": "Rename a Trellis forum thread with its required actor and scope.",
    },
    "worktree": {
        "category": "worktree",
        "risk": "unsupported",
        "description": "No native Trellis worktree command was found in the validated 0.6.x command surface.",
        "availability": "unsupported",
    },
}


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _find_trellis_root(root: Path) -> tuple[Path | None, str | None]:
    """Inspect only the selected root, never an ambient parent project."""
    trellis_dir = root / ".trellis"
    if not trellis_dir.exists():
        return None, None
    if not trellis_dir.is_dir():
        return None, f".trellis is not a directory at {root}"
    if not _is_inside(trellis_dir, root):
        return None, f"refusing .trellis symlink outside project at {root}"
    return root, None


def _require_trellis_root(root: Path) -> Path:
    project_root, error = _find_trellis_root(root)
    if error:
        raise ProjectError(error)
    if project_root is None:
        raise ProjectError("Trellis intent commands require .trellis at the selected project root")
    return project_root


def executable() -> str | None:
    try:
        if components.bundle_root() is not None:
            return components.resolve("trellis").command
    except components.ComponentError:
        return None
    for candidate in ("trellis.cmd", "trellis"):
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve())
    return None


def _launch() -> dict[str, Any] | None:
    try:
        selected_bundle = components.bundle_root()
    except components.ComponentError as error:
        raise ProjectError(f"bundled Trellis is invalid: {error}") from error
    if selected_bundle is not None:
        try:
            resolved = components.resolve("trellis", selected_bundle)
        except components.ComponentError as error:
            raise ProjectError(f"bundled Trellis is invalid: {error}") from error
        return {
            "source": "bundled",
            "version": resolved.version,
            "revision": resolved.revision,
            "prefix": resolved.argv,
            "environment": dict(resolved.environment),
            "executionIdentity": [dict(item) for item in resolved.execution_identity],
            "manifestSha256": resolved.manifest_sha256,
        }
    command = executable()
    if command is None:
        return None
    return {
        "source": "external-path",
        "version": None,
        "revision": None,
        "prefix": [command],
        "environment": {},
        "executionIdentity": [_file_identity(Path(command))],
        "manifestSha256": None,
    }


def binding_identity() -> dict[str, Any]:
    try:
        launch = _launch()
    except ProjectError as error:
        return {"state": "invalid", "reason": str(error)}
    if launch is None:
        return {"state": "absent"}
    return {
        "state": "present",
        "source": launch["source"],
        "version": launch["version"],
        "revision": launch["revision"],
        "manifestSha256": launch["manifestSha256"],
        "environment": launch["environment"],
        "files": launch["executionIdentity"],
    }


def discover(root: Path) -> dict[str, Any]:
    """Return metadata only; no command is executed during discovery."""
    project_root, error = _find_trellis_root(root)
    try:
        selected_bundle = components.bundle_root()
        if selected_bundle is not None:
            described = components.describe("trellis", selected_bundle)
            launch = {
                "source": "bundled",
                "version": described["version"],
                "revision": described["revision"],
                "prefix": [described["command"]],
                "verificationMode": described["verificationMode"],
            }
        else:
            launch = _launch()
    except (ProjectError, components.ComponentError) as launch_error:
        return {
            "state": "unsafe",
            "mode": "confirmed-command",
            "reason": str(launch_error),
            "runtime": {"state": "invalid"},
            "executable": None,
        }
    command = launch["prefix"][0] if launch is not None else None
    runtime = (
        {
            "state": "ready",
            "source": launch["source"],
            "version": launch["version"],
            "revision": launch["revision"],
            "verificationMode": launch.get("verificationMode", "external-path"),
        }
        if launch is not None
        else {"state": "unavailable"}
    )
    if error:
        return {"state": "unsafe", "mode": "confirmed-command", "reason": error, "runtime": runtime, "executable": command}
    if project_root is None:
        return {
            "state": "absent",
            "mode": "confirmed-command",
            "reason": "no .trellis directory found at the selected project root",
            "runtime": runtime,
            "executable": command,
        }

    trellis_dir = project_root / ".trellis"
    tasks_dir = trellis_dir / "tasks"
    task_count = 0
    if tasks_dir.is_dir() and _is_inside(tasks_dir, trellis_dir):
        # Native Trellis tasks are directories; lightweight fixtures may use
        # task files. Archive is a container, not an active task.
        task_count = sum(
            1
            for item in tasks_dir.iterdir()
            if not item.is_symlink() and item.name != "archive" and (item.is_file() or item.is_dir())
        )

    return {
        "state": "detected",
        "mode": "confirmed-command",
        "projectRoot": str(project_root),
        "workflow": (trellis_dir / "workflow.md").is_file(),
        "context": (trellis_dir / "spec" / "context" / "CONTEXT.md").is_file(),
        "taskCount": task_count,
        "runtime": runtime,
        "executable": command,
        "execution": "requires-one-time-approval",
    }


def _arguments(values: list[str]) -> list[str]:
    normalized = list(values)
    if normalized and normalized[0] == "--":
        normalized.pop(0)
    if not normalized:
        raise ProjectError("provide a Trellis command after '--'")
    if any("\x00" in value for value in normalized):
        raise ProjectError("Trellis arguments cannot contain a null byte")
    return normalized


def _risk(arguments: list[str]) -> str:
    return "read" if tuple(arguments[:2]) in READ_PREFIXES or tuple(arguments[:1]) in READ_PREFIXES else "write"


def risk_for(values: list[str]) -> str:
    return _risk(_arguments(values))


def _payload(root: Path, arguments: list[str]) -> dict[str, Any]:
    launch = _launch()
    if launch is None:
        raise ProjectError("Trellis CLI is not available on PATH; install it before running adapter commands")
    return {
        "adapter": "trellis",
        "cwd": str(root),
        "argv": [*launch["prefix"], *arguments],
        "executionIdentity": launch["executionIdentity"],
        "runtimeSource": launch["source"],
        "runtimeVersion": launch["version"],
        "manifestSha256": launch["manifestSha256"],
        "environment": launch["environment"],
    }


def _file_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProjectError(f"Trellis execution dependency is missing or unsafe: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "size": path.stat().st_size}


def _intent_value(value: str | None, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ProjectError(f"Trellis intent {field} must use letters, digits, dots, underscores, or hyphens")
    return value


def _intent_title(value: str | None) -> str:
    if not isinstance(value, str):
        raise ProjectError("Trellis task-create intent requires --title")
    title = value.strip()
    if not title or "\n" in title or "\r" in title or len(title) > 160:
        raise ProjectError("Trellis intent title must be a non-empty single line of 160 characters or fewer")
    return title


def _intent_scope(value: str | None) -> str:
    scope = value or "project"
    if scope not in _SCOPES:
        raise ProjectError("Trellis intent scope must be project or global")
    return scope


def intent_catalog() -> dict[str, Any]:
    """Expose the supported subset and explicit compatibility gaps.

    The catalog is deliberately smaller than generic passthrough.  It gives
    stable HelloDev intent names to daily workflows while the native adapter
    remains the escape hatch for newer Trellis releases and uncommon actions.
    """
    intents = [{"name": name, **details} for name, details in _INTENT_CATALOG.items()]
    return {
        "intents": intents,
        "genericEscapeHatch": "hellodev trellis prepare -- <native Trellis arguments>",
        "compatibility": "Intent shapes are validated against the local Trellis 0.6.x source; use native passthrough for commands outside this catalog.",
    }


def _intent_payload(
    root: Path,
    name: str,
    *,
    title: str | None = None,
    task: str | None = None,
    channel: str | None = None,
    old_thread: str | None = None,
    new_thread: str | None = None,
    agent: str | None = None,
    scope: str | None = None,
) -> tuple[dict[str, Any], str]:
    project_root = _require_trellis_root(root)
    if name not in _INTENT_CATALOG:
        raise ProjectError(f"unknown Trellis intent: {name}")
    details = _INTENT_CATALOG[name]
    if details.get("availability") == "unsupported":
        raise ProjectError(f"Trellis intent {name} is unsupported: {details['description']}")

    task_script = project_root / ".trellis" / "scripts" / "task.py"
    if name.startswith("task-"):
        if not task_script.is_file() or task_script.is_symlink() or not _is_inside(task_script, project_root):
            raise ProjectError("Trellis native task script is missing or unsafe")
        executable_path = str(Path(sys.executable).resolve())
        runner_script = Path(__file__).resolve().parents[1] / "trellis_script_runner.py"
        if not runner_script.is_file() or runner_script.is_symlink():
            raise ProjectError("HelloDev Trellis script runner is missing or unsafe")
        prefix = [executable_path, "-X", "utf8", "-B", "-I", str(runner_script), str(task_script)]
        if name == "task-list":
            argv = [*prefix, "list"]
        elif name == "task-current":
            argv = [*prefix, "current", "--source"]
        elif name == "task-create":
            argv = [*prefix, "create", _intent_title(title)]
        elif name == "task-start":
            argv = [*prefix, "start", _intent_value(task, "task")]
        else:
            argv = [*prefix, "validate", _intent_value(task, "task")]
    else:
        launch = _launch()
        if launch is None:
            raise ProjectError("Trellis CLI is not available on PATH; install it before running adapter commands")
        selected_scope = _intent_scope(scope)
        if name == "channel-list":
            argv = [*launch["prefix"], "channel", "list", "--scope", selected_scope]
        else:
            argv = [
                *launch["prefix"],
                "channel",
                "thread",
                "rename",
                _intent_value(channel, "channel"),
                _intent_value(old_thread, "old-thread"),
                _intent_value(new_thread, "new-thread"),
                "--as",
                _intent_value(agent, "agent"),
                "--scope",
                selected_scope,
            ]
    execution_identity = launch["executionIdentity"] if not name.startswith("task-") else [_file_identity(Path(argv[0]))]
    if name.startswith("task-"):
        execution_identity.append(_file_identity(runner_script))
        execution_identity.append(_file_identity(task_script))
    return {
        "adapter": "trellis",
        "intent": name,
        "cwd": str(project_root),
        "argv": argv,
        "executionIdentity": execution_identity,
        "environment": (
            launch["environment"]
            if not name.startswith("task-")
            else {
                "PYTHONHOME": "",
                "PYTHONPATH": "",
                "PYTHONUSERBASE": "",
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        ),
    }, str(details["risk"])


def prepare_intent(root: Path, name: str, **values: str | None) -> dict[str, Any]:
    payload, risk = _intent_payload(root, name, **values)
    plan = prepare(root, payload, risk)
    return {**plan, "adapter": "trellis", "intent": name, "argv": payload["argv"]}


def _run_payload(payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            payload["argv"],
            cwd=payload["cwd"],
            env={**os.environ, **payload.get("environment", {})},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ProjectError(f"Trellis command timed out after {timeout_seconds} seconds") from error
    return {
        "adapter": "trellis",
        "argv": payload["argv"],
        "exitCode": completed.returncode,
        "stdout": completed.stdout[:65536],
        "stderr": completed.stderr[:65536],
    }


def run_intent(root: Path, name: str, approval: str, timeout_seconds: int, **values: str | None) -> dict[str, Any]:
    if not 1 <= timeout_seconds <= 300:
        raise ProjectError("Trellis timeout must be between 1 and 300 seconds")
    payload, risk = _intent_payload(root, name, **values)
    consume(root, payload, approval, risk)
    return _run_payload(payload, timeout_seconds)


def prepare_run(root: Path, values: list[str]) -> dict[str, Any]:
    arguments = _arguments(values)
    payload = _payload(root, arguments)
    plan = prepare(root, payload, _risk(arguments))
    return {**plan, "adapter": "trellis", "argv": payload["argv"]}


def run(root: Path, values: list[str], approval: str, timeout_seconds: int) -> dict[str, Any]:
    if not 1 <= timeout_seconds <= 300:
        raise ProjectError("Trellis timeout must be between 1 and 300 seconds")
    arguments = _arguments(values)
    payload = _payload(root, arguments)
    consume(root, payload, approval, _risk(arguments))
    return _run_payload(payload, timeout_seconds)
