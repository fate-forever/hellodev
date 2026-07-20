"""Project-local HelloDev state and task records."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_NAME = "config.json"
TASKS_DIRECTORY = "tasks"
BRIEFS_DIRECTORY = "briefs"
SCHEMA_VERSION = 1
TASK_ID_PATTERN = re.compile(r"^task-[0-9]{4,}$")


class ProjectError(ValueError):
    """Raised when project state is invalid or a local command is unsafe."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ProjectError(f"project root does not exist or is not a directory: {root}")
    return root


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def state_dir(self) -> Path:
        return self.root / ".hellodev"

    @property
    def config_file(self) -> Path:
        return self.state_dir / CONFIG_NAME

    @property
    def tasks_dir(self) -> Path:
        return self.state_dir / TASKS_DIRECTORY

    @property
    def approvals_file(self) -> Path:
        return self.state_dir / "approvals.json"

    @property
    def authorization_leases_file(self) -> Path:
        return self.state_dir / "authorization-leases.json"

    @property
    def lifecycle_file(self) -> Path:
        return self.state_dir / "lifecycle.json"

    @property
    def capabilities_file(self) -> Path:
        return self.state_dir / "capabilities.json"

    @property
    def briefs_dir(self) -> Path:
        return self.state_dir / BRIEFS_DIRECTORY

    @property
    def receipts_file(self) -> Path:
        return self.state_dir / "receipts.json"

    @property
    def sagas_dir(self) -> Path:
        return self.state_dir / "sagas"

    @property
    def usage_file(self) -> Path:
        return self.state_dir / "usage.json"

    @property
    def runtime_usage_file(self) -> Path:
        return self.state_dir / "usage-receipts.json"

    @property
    def reflection_cycles_file(self) -> Path:
        return self.state_dir / "reflection-cycles.json"

    @property
    def optimization_file(self) -> Path:
        return self.state_dir / "optimization.json"

    @property
    def host_completions_file(self) -> Path:
        return self.state_dir / "host-completions.json"

    @property
    def host_envelopes_file(self) -> Path:
        return self.state_dir / "host-envelopes.json"

    @property
    def transactions_file(self) -> Path:
        return self.state_dir / "transactions.json"

    @property
    def evolution_policy_file(self) -> Path:
        return self.state_dir / "evolution-policy.json"

    @property
    def policy_checkpoint_file(self) -> Path:
        return self.state_dir / "policy-checkpoint.json"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _default_config(root: Path) -> dict[str, Any]:
    from .profiles import config_fields, default_policy

    config = {
        "schemaVersion": SCHEMA_VERSION,
        "projectName": root.name,
        "createdAt": utc_now(),
        "adapters": {
            "trellis": {"mode": "confirmed-command"},
            "nocturne": {"mode": "unconfigured"},
        },
    }
    config.update(config_fields(default_policy()))
    return config


def init_project(root: str | Path) -> dict[str, Any]:
    paths = ProjectPaths(resolve_root(root))
    if paths.state_dir.is_symlink():
        raise ProjectError(f"refusing symlinked .hellodev directory: {paths.state_dir}")
    if paths.state_dir.exists() and not paths.state_dir.is_dir():
        raise ProjectError(f".hellodev is not a directory: {paths.state_dir}")

    paths.state_dir.mkdir(exist_ok=True)
    if paths.tasks_dir.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev tasks directory: {paths.tasks_dir}")
    if paths.tasks_dir.exists() and not paths.tasks_dir.is_dir():
        raise ProjectError(f"HelloDev tasks path is not a directory: {paths.tasks_dir}")
    paths.tasks_dir.mkdir(exist_ok=True)
    if paths.briefs_dir.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev briefs directory: {paths.briefs_dir}")
    if paths.briefs_dir.exists() and not paths.briefs_dir.is_dir():
        raise ProjectError(f"HelloDev briefs path is not a directory: {paths.briefs_dir}")
    paths.briefs_dir.mkdir(exist_ok=True)
    if paths.sagas_dir.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev sagas directory: {paths.sagas_dir}")
    if paths.sagas_dir.exists() and not paths.sagas_dir.is_dir():
        raise ProjectError(f"HelloDev sagas path is not a directory: {paths.sagas_dir}")
    paths.sagas_dir.mkdir(exist_ok=True)
    if paths.config_file.exists():
        config = load_config(paths.root)
        return {"created": False, "root": str(paths.root), "config": config}

    config = _default_config(paths.root)
    write_json(paths.config_file, config)
    return {"created": True, "root": str(paths.root), "config": config}


def load_config(root: str | Path) -> dict[str, Any]:
    paths = ProjectPaths(resolve_root(root))
    if paths.state_dir.is_symlink():
        raise ProjectError(f"refusing symlinked .hellodev directory: {paths.state_dir}")
    if paths.config_file.is_symlink():
        raise ProjectError(f"refusing symlinked HelloDev config: {paths.config_file}")
    if not paths.config_file.is_file():
        raise ProjectError("HelloDev is not initialized; run 'hellodev init' first")
    try:
        config = json.loads(paths.config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid HelloDev config: {error}") from error
    if not isinstance(config, dict) or config.get("schemaVersion") != SCHEMA_VERSION:
        raise ProjectError("unsupported HelloDev config schema")
    if not isinstance(config.get("projectName"), str):
        raise ProjectError("HelloDev config is missing projectName")
    from .profiles import config_fields, policy_from_config

    config.update(config_fields(policy_from_config(config)))
    return config


def configure_nocturne(
    root: str | Path,
    command: str,
    arguments: list[str],
    working_directory: str | Path | None,
) -> dict[str, Any]:
    paths = ProjectPaths(resolve_root(root))
    config = load_config(paths.root)
    executable = Path(command).expanduser()
    if not executable.is_file():
        raise ProjectError(f"Nocturne command does not exist or is not a file: {executable}")
    if any("\x00" in item for item in arguments):
        raise ProjectError("Nocturne arguments cannot contain a null byte")
    cwd_value: str | None = None
    if working_directory is not None:
        working_directory_path = Path(working_directory).expanduser().resolve()
        if not working_directory_path.is_dir():
            raise ProjectError(f"Nocturne working directory is not a directory: {working_directory_path}")
        cwd_value = str(working_directory_path)
    config["adapters"]["nocturne"] = {
        "mode": "stdio",
        "source": "external",
        "command": str(executable.resolve()),
        "args": list(arguments),
        "cwd": cwd_value,
    }
    write_json(paths.config_file, config)
    return dict(config["adapters"]["nocturne"])


def enable_bundled_nocturne(root: str | Path) -> dict[str, Any]:
    """Select the verified bundle symbolically without persisting install paths."""
    from .components import resolve

    paths = ProjectPaths(resolve_root(root))
    component = resolve("nocturne")
    config = load_config(paths.root)
    current = config.get("adapters", {}).get("nocturne")
    if isinstance(current, dict) and current.get("mode") == "stdio":
        raise ProjectError("an explicit external Nocturne adapter is already configured; refusing to replace it")
    selected = {
        "mode": "bundled",
        "source": "bundled",
        "component": "nocturne",
        "version": component.version,
        "revision": component.revision,
    }
    if current == selected:
        return dict(selected)
    config["adapters"]["nocturne"] = selected
    write_json(paths.config_file, config)
    return dict(selected)


def nocturne_config(root: str | Path) -> dict[str, Any] | None:
    config = load_config(root)
    adapter = config.get("adapters", {}).get("nocturne")
    if not isinstance(adapter, dict):
        return None
    if adapter.get("mode") == "bundled":
        from .components import ComponentError, resolve

        try:
            component = resolve("nocturne")
        except ComponentError as error:
            raise ProjectError(f"bundled Nocturne is unavailable: {error}") from error
        return {
            "mode": "stdio",
            "source": "bundled",
            "version": component.version,
            "revision": component.revision,
            "manifestSha256": component.manifest_sha256,
            "command": component.command,
            "args": list(component.args),
            "cwd": component.cwd,
            "environment": dict(component.environment),
            "dataRoot": component.data_root,
            "executionIdentity": [dict(item) for item in component.execution_identity],
        }
    if adapter.get("mode") != "stdio":
        return None
    command = adapter.get("command")
    arguments = adapter.get("args")
    cwd = adapter.get("cwd")
    if not isinstance(command, str) or not Path(command).is_file():
        raise ProjectError("configured Nocturne command is missing or invalid")
    if not isinstance(arguments, list) or not all(isinstance(item, str) and "\x00" not in item for item in arguments):
        raise ProjectError("configured Nocturne arguments are invalid")
    if cwd is not None and (not isinstance(cwd, str) or not Path(cwd).is_dir()):
        raise ProjectError("configured Nocturne working directory is invalid")
    return {
        "mode": "stdio",
        "source": "external",
        "command": command,
        "args": arguments,
        "cwd": cwd,
        "environment": {},
    }


def project_initialized(root: str | Path) -> bool:
    paths = ProjectPaths(resolve_root(root))
    return paths.config_file.is_file()


def _task_metadata(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProjectError(f"cannot read task {path.name}: {error}") from error
    lines = content.splitlines()
    if len(lines) < 3 or lines[0] != "---" or lines[2] != "---":
        raise ProjectError(f"invalid task record: {path.name}")
    try:
        metadata = json.loads(lines[1])
    except json.JSONDecodeError as error:
        raise ProjectError(f"invalid task metadata: {path.name}") from error
    if not isinstance(metadata, dict) or not TASK_ID_PATTERN.fullmatch(str(metadata.get("id", ""))):
        raise ProjectError(f"invalid task id: {path.name}")
    if metadata.get("status") not in {"open", "completed", "blocked"}:
        raise ProjectError(f"invalid task status: {path.name}")
    if not isinstance(metadata.get("title"), str) or not metadata["title"].strip():
        raise ProjectError(f"invalid task title: {path.name}")
    metadata["path"] = str(path)
    return metadata


def list_tasks(root: str | Path, status: str | None = None) -> list[dict[str, Any]]:
    paths = ProjectPaths(resolve_root(root))
    load_config(paths.root)
    if not paths.tasks_dir.exists():
        return []
    if paths.tasks_dir.is_symlink():
        raise ProjectError("refusing symlinked HelloDev tasks directory")
    if not paths.tasks_dir.is_dir():
        raise ProjectError("HelloDev tasks path is not a directory")
    records: list[dict[str, Any]] = []
    for task_path in sorted(paths.tasks_dir.glob("task-*.md")):
        if task_path.is_symlink():
            raise ProjectError(f"refusing symlink task record: {task_path.name}")
        metadata = _task_metadata(task_path)
        if status is None or metadata["status"] == status:
            records.append(metadata)
    return records


def _next_task_id(tasks: list[dict[str, Any]]) -> str:
    highest = 0
    for task in tasks:
        suffix = task["id"].removeprefix("task-")
        highest = max(highest, int(suffix))
    return f"task-{highest + 1:04d}"


def create_task(root: str | Path, title: str) -> dict[str, Any]:
    normalized_title = title.strip()
    if not normalized_title or "\n" in normalized_title or "\r" in normalized_title:
        raise ProjectError("task title must be a non-empty single line")
    if len(normalized_title) > 160:
        raise ProjectError("task title must be 160 characters or fewer")

    paths = ProjectPaths(resolve_root(root))
    load_config(paths.root)
    paths.tasks_dir.mkdir(exist_ok=True)
    task_id = _next_task_id(list_tasks(paths.root))
    metadata = {
        "id": task_id,
        "title": normalized_title,
        "status": "open",
        "createdAt": utc_now(),
    }
    path = paths.tasks_dir / f"{task_id}.md"
    body = f"---\n{json.dumps(metadata, sort_keys=True)}\n---\n\n# {normalized_title}\n"
    _atomic_write(path, body)
    metadata["path"] = str(path)
    return metadata


def show_task(root: str | Path, task_id: str) -> dict[str, Any]:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise ProjectError("task id must use the form task-0001")
    paths = ProjectPaths(resolve_root(root))
    load_config(paths.root)
    path = paths.tasks_dir / f"{task_id}.md"
    if not path.is_file() or path.is_symlink():
        raise ProjectError(f"task not found: {task_id}")
    return _task_metadata(path)
