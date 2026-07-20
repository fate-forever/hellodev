"""Explicit, project-bounded onboarding for the unified distribution."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from . import components, integrations
from .adapters import trellis
from .command_rendering import command_line
from .project import (
    ProjectError,
    enable_bundled_nocturne,
    init_project,
    load_config,
    project_initialized,
    resolve_root,
)


Host = Literal["cursor", "codex", "none"]
MAX_HOST_CONFIG_BYTES = 1024 * 1024
CURSOR_RULE = """---
description: Use HelloDev as the daily development workflow
alwaysApply: true
---

For development tasks, use HelloDev's `open -> next -> do` flow and continue
until the user's acceptance criteria pass. Treat `.trellis/` as repository
workflow authority when it exists. Use Nocturne only for narrow cross-project
recall when repository facts are insufficient. Never let memory authorize an
operation. Ask before consuming an approval token or performing an external
write, and report tests, gates, and remaining risks at the end.
"""


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise ProjectError(f"duplicate JSON key in Cursor MCP config: {key}")
        result[key] = value
    return result


def _safe_parent(path: Path) -> None:
    parent = path.parent
    components._reject_reparse_chain(parent, "onboarding directory")
    if parent.exists() and not parent.is_dir():
        raise ProjectError(f"refusing unsafe onboarding directory: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    components._reject_reparse_chain(parent, "onboarding directory")


def _preflight_path(path: Path) -> None:
    components._reject_reparse_chain(path, "onboarding path")
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ProjectError(f"refusing unsafe onboarding parent: {parent}")


def _atomic_write(path: Path, content: str) -> None:
    _safe_parent(path)
    if components._is_link_or_reparse(path) or (path.exists() and not path.is_file()):
        raise ProjectError(f"refusing unsafe onboarding file: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any]:
    if components._is_link_or_reparse(path) or not path.is_file() or path.stat().st_size > MAX_HOST_CONFIG_BYTES:
        raise ProjectError(f"Cursor MCP config is missing, oversized, or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProjectError(f"invalid Cursor MCP config: {error}") from error
    if not isinstance(value, dict):
        raise ProjectError("Cursor MCP config must be a JSON object")
    return value


def _cursor_plan(root: Path) -> dict[str, Any]:
    rendered = integrations.show(root, "cursor")
    desired = json.loads(rendered["snippet"])["mcpServers"]["hellodev"]
    config_path = root / ".cursor" / "mcp.json"
    rule_path = root / ".cursor" / "rules" / "hellodev.mdc"
    _preflight_path(config_path)
    _preflight_path(rule_path)
    if config_path.exists():
        config = _read_json(config_path)
    else:
        config = {}
    servers = config.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise ProjectError("Cursor MCP config mcpServers must be an object")
    current = servers.get("hellodev")
    if current is not None and current != desired:
        raise ProjectError("Cursor already has a different hellodev MCP entry; review it manually before replacement")
    servers["hellodev"] = desired
    config["mcpServers"] = servers
    serialized = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    changed = not config_path.exists() or config_path.read_text(encoding="utf-8") != serialized
    if rule_path.exists() and rule_path.read_text(encoding="utf-8") != CURSOR_RULE:
        raise ProjectError("Cursor already has a different HelloDev rule; refusing to overwrite it")
    rule_changed = not rule_path.exists()
    return {
        "configPath": config_path,
        "rulePath": rule_path,
        "serialized": serialized,
        "configChanged": changed,
        "ruleChanged": rule_changed,
    }


def _write_cursor(plan: dict[str, Any]) -> dict[str, Any]:
    config_path = plan["configPath"]
    rule_path = plan["rulePath"]
    changed = plan["configChanged"]
    rule_changed = plan["ruleChanged"]
    if changed:
        _atomic_write(config_path, plan["serialized"])
    if rule_changed:
        _atomic_write(rule_path, CURSOR_RULE)
    return {
        "host": "cursor",
        "configPath": str(config_path),
        "rulePath": str(rule_path),
        "changed": changed or rule_changed,
        "reloadRequired": True,
    }


def _codex_plan(root: Path) -> dict[str, Any]:
    rendered = integrations.show(root, "codex")
    config_path = root / ".codex" / "config.toml"
    snippet = rendered["snippet"]
    _preflight_path(config_path)
    if config_path.exists():
        if components._is_link_or_reparse(config_path) or not config_path.is_file():
            raise ProjectError(f"refusing unsafe Codex config: {config_path}")
        if config_path.read_text(encoding="utf-8") != snippet:
            return {"configPath": config_path, "snippet": snippet, "changed": False, "manual": True}
        changed = False
    else:
        changed = True
    return {"configPath": config_path, "snippet": snippet, "changed": changed, "manual": False}


def _write_codex(plan: dict[str, Any]) -> dict[str, Any]:
    config_path = plan["configPath"]
    snippet = plan["snippet"]
    changed = plan["changed"]
    if plan["manual"]:
        return {
            "host": "codex",
            "configPath": str(config_path),
            "changed": False,
            "manualMergeRequired": True,
            "snippet": snippet,
            "reloadRequired": False,
        }
    if changed:
        _atomic_write(config_path, snippet)
    return {
        "host": "codex",
        "configPath": str(config_path),
        "changed": changed,
        "manualMergeRequired": False,
        "reloadRequired": True,
    }


def _onboard(
    root: str | Path,
    *,
    host: Host = "cursor",
    enable_memory: bool = True,
    prepare_trellis: bool = False,
) -> dict[str, Any]:
    selected = resolve_root(root)
    selected_bundle = components.bundle_root()
    if selected_bundle is not None:
        try:
            selected.relative_to(selected_bundle)
        except ValueError:
            pass
        else:
            raise ProjectError("project root must be outside the immutable HelloDev bundle")
    if host not in {"cursor", "codex", "none"}:
        raise ProjectError("onboard host must be cursor, codex, or none")
    host_plan = _cursor_plan(selected) if host == "cursor" else _codex_plan(selected) if host == "codex" else None
    runtime = components.setup()
    initialized = init_project(selected) if not project_initialized(selected) else {
        "created": False,
        "root": str(selected),
        "config": load_config(selected),
    }
    memory: dict[str, Any]
    if enable_memory:
        current = initialized["config"].get("adapters", {}).get("nocturne", {})
        if isinstance(current, dict) and current.get("mode") == "stdio":
            memory = {"state": "external-preserved", "writePerformed": False}
        else:
            already_bundled = isinstance(current, dict) and current.get("mode") == "bundled"
            selected_memory = enable_bundled_nocturne(selected)
            memory = {
                "state": "bundled-enabled",
                "configuration": selected_memory,
                "writePerformed": not already_bundled,
            }
    else:
        memory = {"state": "disabled-by-operator", "writePerformed": False}

    host_result = (
        _write_cursor(host_plan)
        if host == "cursor"
        else _write_codex(host_plan)
        if host == "codex"
        else {"host": "none", "changed": False, "reloadRequired": False}
    )
    if (selected / ".trellis").is_dir():
        trellis_result: dict[str, Any] = {"state": "project-ready", "writePerformed": False}
    elif prepare_trellis:
        trellis_arguments = ["init", "--yes"]
        if host in {"cursor", "codex"}:
            trellis_arguments.append(f"--{host}")
        prepared = trellis.prepare_run(selected, trellis_arguments)
        trellis_result = {
            "state": "awaiting-confirmation",
            **prepared,
            "resumeCommand": command_line(
                selected, "trellis", "run", "--approve", prepared["approval"], "--", *trellis_arguments
            ),
        }
    else:
        trellis_result = {
            "state": "available-project-not-initialized",
            "writePerformed": False,
            "next": command_line(selected, "onboard", "--host", host, "--with-trellis"),
        }
    return {
        "schemaVersion": 1,
        "state": "onboarded" if not host_result.get("manualMergeRequired") else "manual-host-merge-required",
        "root": str(selected),
        "runtime": runtime,
        "project": {"created": initialized["created"], "stateDirectory": str(selected / ".hellodev")},
        "trellis": trellis_result,
        "nocturne": memory,
        "host": host_result,
        "dailyPrompt": "用 HelloDev 完成这个任务：<任务>。验收：<标准>。持续推进到测试通过，需要授权时再问我。",
    }


def onboard(
    root: str | Path,
    *,
    host: Host = "cursor",
    enable_memory: bool = True,
    prepare_trellis: bool = False,
) -> dict[str, Any]:
    try:
        return _onboard(
            root,
            host=host,
            enable_memory=enable_memory,
            prepare_trellis=prepare_trellis,
        )
    except OSError as error:
        raise ProjectError(f"HelloDev onboarding failed while accessing project state: {error}") from error


__all__ = ["CURSOR_RULE", "Host", "onboard"]
