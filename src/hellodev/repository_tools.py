"""Read-only discovery for host-managed repository tool providers.

HelloDev owns orchestration, authorization, and recovery.  Repository tools
remain a separate host capability: discovering a FastCtx executable does not
prove that its MCP server is registered or connected, and never authorizes a
write or shell command.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


FASTCTX_TOOLS = (
    "read",
    "grep",
    "glob",
    "replace",
    "run",
    "run_background",
    "job_output",
    "job_kill",
    "job_list",
)
FASTCTX_WRITE_TOOLS = ("replace", "run", "run_background", "job_kill")
SERENA_READ_TOOLS = (
    "find_declaration",
    "find_implementations",
    "find_referencing_symbols",
    "find_symbol",
    "get_diagnostics_for_file",
    "get_diagnostics_for_symbol",
    "get_symbols_overview",
)
SERENA_WRITE_TOOLS = (
    "insert_after_symbol",
    "insert_before_symbol",
    "rename_symbol",
    "replace_symbol_body",
    "safe_delete_symbol",
)


def _candidate() -> tuple[Path | None, str]:
    explicit = os.environ.get("HELLODEV_FASTCTX_COMMAND")
    if explicit:
        return Path(explicit).expanduser(), "environment"
    name = "fastctx.exe" if os.name == "nt" else "fastctx"
    managed = Path.home() / ".fastctx" / "bin" / name
    if managed.is_file():
        return managed, "managed-home"
    resolved = shutil.which("fastctx")
    return (Path(resolved), "path") if resolved else (None, "not-found")


def _fastctx() -> dict[str, Any]:
    candidate, source = _candidate()
    if candidate is None:
        return {
            "state": "unavailable",
            "source": source,
            "command": None,
            "reasonCode": "fastctx-command-not-found",
            "mcpConnection": "not-inspected",
        }
    if not candidate.is_absolute():
        return {
            "state": "unsafe",
            "source": source,
            "command": str(candidate),
            "reasonCode": "fastctx-command-not-absolute",
            "mcpConnection": "not-inspected",
        }
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            return {
                "state": "unavailable",
                "source": source,
                "command": str(candidate),
                "reasonCode": "fastctx-command-not-regular-file",
                "mcpConnection": "not-inspected",
            }
        stat = resolved.stat()
    except OSError:
        return {
            "state": "unavailable",
            "source": source,
            "command": str(candidate),
            "reasonCode": "fastctx-command-inaccessible",
            "mcpConnection": "not-inspected",
        }
    return {
        "state": "available",
        "source": source,
        "command": str(resolved),
        "identity": {"size": stat.st_size, "modifiedNs": stat.st_mtime_ns},
        "linkResolved": candidate.is_symlink(),
        "reasonCode": "fastctx-command-discovered",
        "mcpConnection": "not-inspected",
    }


def _serena_candidate() -> tuple[Path | None, str]:
    explicit = os.environ.get("HELLODEV_SERENA_COMMAND")
    if explicit:
        return Path(explicit).expanduser(), "environment"
    resolved = shutil.which("serena")
    return (Path(resolved), "path") if resolved else (None, "not-found")


def _serena() -> dict[str, Any]:
    candidate, source = _serena_candidate()
    if candidate is None:
        return {
            "state": "unavailable",
            "source": source,
            "command": None,
            "reasonCode": "serena-command-not-found",
            "mcpConnection": "not-inspected",
        }
    if not candidate.is_absolute():
        return {
            "state": "unsafe",
            "source": source,
            "command": str(candidate),
            "reasonCode": "serena-command-not-absolute",
            "mcpConnection": "not-inspected",
        }
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            return {
                "state": "unavailable",
                "source": source,
                "command": str(candidate),
                "reasonCode": "serena-command-not-regular-file",
                "mcpConnection": "not-inspected",
            }
        stat = resolved.stat()
    except OSError:
        return {
            "state": "unavailable",
            "source": source,
            "command": str(candidate),
            "reasonCode": "serena-command-inaccessible",
            "mcpConnection": "not-inspected",
        }
    return {
        "state": "available",
        "source": source,
        "command": str(resolved),
        "identity": {"size": stat.st_size, "modifiedNs": stat.st_mtime_ns},
        "linkResolved": candidate.is_symlink(),
        "reasonCode": "serena-command-discovered",
        "mcpConnection": "not-inspected",
    }


def discover() -> dict[str, Any]:
    """Return an honest provider projection without executing external code."""
    fastctx = _fastctx()
    serena = _serena()
    return {
        "schemaVersion": 2,
        "state": "ready",
        "activeProvider": "native",
        "suggestedProvider": "native",
        "activationState": "native-context-plane",
        "role": "optional-accelerator",
        "required": False,
        "contextPlaneOwner": "hellodev",
        "acceleratorState": "available-not-active" if fastctx["state"] == "available" else "unavailable",
        "providers": {
            "native": {
                "state": "ready",
                "source": "hellodev-host",
                "reasonCode": "native-provider-always-available",
            },
            "fastctx": fastctx,
            "serena": serena,
        },
        "fastctxContract": {
            "namespace": "mcp__fastctx",
            "tools": list(FASTCTX_TOOLS),
            "writeOrShellTools": list(FASTCTX_WRITE_TOOLS),
            "writeApprovalRequired": True,
            "memoryAuthority": "none",
            "workflowAuthority": "none",
        },
        "semanticContext": {
            "activeProvider": "native-python-ast",
            "fallbackProvider": "native-lexical",
            "externalProvider": "serena",
            "externalProviderState": "available-not-connected" if serena["state"] == "available" else serena["state"],
            "connectionState": "not-inspected",
            "selectionPolicy": "explicit-symbol-query-only",
            "languageCoverage": ["python"],
            "readOnly": True,
            "required": False,
        },
        "serenaContract": {
            "namespace": "mcp__serena",
            "readTools": list(SERENA_READ_TOOLS),
            "writeTools": list(SERENA_WRITE_TOOLS),
            "writeApprovalRequired": True,
            "connectionAttested": False,
            "memoryAuthority": "none",
            "workflowAuthority": "none",
            "verificationAuthority": "advisory-only",
        },
        "executionPerformed": False,
        "configurationInspected": False,
        "configurationChanged": False,
    }


def fingerprint_material() -> dict[str, Any]:
    """Return only provider identity fields relevant to cache invalidation."""
    value = discover()
    fastctx = value["providers"]["fastctx"]
    serena = value["providers"]["serena"]
    return {
        "fastctxState": fastctx["state"],
        "fastctxSource": fastctx["source"],
        "fastctxCommand": fastctx["command"],
        "fastctxIdentity": fastctx.get("identity"),
        "serenaState": serena["state"],
        "serenaSource": serena["source"],
        "serenaCommand": serena["command"],
        "serenaIdentity": serena.get("identity"),
    }


def registration(host: str) -> dict[str, Any]:
    """Render an optional host entry; never read or write host configuration."""
    value = discover()
    fastctx = value["providers"]["fastctx"]
    if fastctx["state"] != "available":
        return {
            "state": "unavailable",
            "host": host,
            "reasonCode": fastctx["reasonCode"],
            "snippet": None,
            "writePerformed": False,
        }
    command = fastctx["command"]
    if host == "codex":
        import json

        snippet = (
            "[mcp_servers.fastctx]\n"
            f"command = {json.dumps(command, ensure_ascii=False)}\n"
            'args = ["serve"]\n'
            'default_tools_approval_mode = "writes"\n'
        )
    elif host in {"antigravity", "cursor"}:
        import json

        snippet = json.dumps(
            {"mcpServers": {"fastctx": {"command": command, "args": ["serve"]}}},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    else:
        raise ValueError("repository tool host must be antigravity, codex, or cursor")
    return {
        "state": "available",
        "host": host,
        "scope": "project",
        "snippet": snippet,
        "approvalMode": "writes",
        "warning": (
            "Optional accelerator only: HelloDev Context Plane is complete without this registration. Binary "
            "discovery does not prove that the MCP server is connected. Review before merging; replace and shell "
            "tools remain host-approved and never inherit memory authority."
        ),
        "required": False,
        "recommended": False,
        "role": "optional-accelerator",
        "writePerformed": False,
    }


__all__ = [
    "FASTCTX_TOOLS", "FASTCTX_WRITE_TOOLS", "SERENA_READ_TOOLS", "SERENA_WRITE_TOOLS",
    "discover", "fingerprint_material", "registration",
]
