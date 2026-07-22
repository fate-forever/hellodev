"""Tamper-evident, authority-free continuation cursors."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from ..project import ProjectError


CURSOR_SCHEMA_VERSION = 1
MAX_CURSOR_BYTES = 4096


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def root_digest(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()


def encode(*, root: Path, snapshot: str, query: str, scope: str, offset: int) -> str:
    payload = {
        "schemaVersion": CURSOR_SCHEMA_VERSION,
        "rootSha256": root_digest(root),
        "snapshot": snapshot,
        "query": query,
        "scope": scope,
        "offset": offset,
    }
    payload["checksum"] = hashlib.sha256(_canonical(payload)).hexdigest()
    raw = _canonical(payload)
    if len(raw) > MAX_CURSOR_BYTES:
        raise ProjectError("context cursor exceeds its bounded payload")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode(root: Path, token: str) -> dict[str, Any]:
    if not isinstance(token, str) or not token or len(token.encode("utf-8")) > MAX_CURSOR_BYTES * 2:
        raise ProjectError("invalid context cursor")
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error) as error:
        raise ProjectError("invalid context cursor") from error
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "rootSha256", "snapshot", "query", "scope", "offset", "checksum"
    }:
        raise ProjectError("invalid context cursor schema")
    checksum = value.pop("checksum")
    expected = hashlib.sha256(_canonical(value)).hexdigest()
    if not isinstance(checksum, str) or checksum != expected:
        raise ProjectError("context cursor checksum mismatch")
    if value.get("schemaVersion") != CURSOR_SCHEMA_VERSION:
        raise ProjectError("unsupported context cursor version")
    if value.get("rootSha256") != root_digest(root):
        raise ProjectError("context cursor belongs to another project")
    if not isinstance(value.get("snapshot"), str) or len(value["snapshot"]) != 64:
        raise ProjectError("invalid context cursor snapshot")
    if not isinstance(value.get("query"), str) or not 1 <= len(value["query"]) <= 512:
        raise ProjectError("invalid context cursor query")
    if value.get("scope") not in {"project", "code", "docs"}:
        raise ProjectError("invalid context cursor scope")
    if type(value.get("offset")) is not int or value["offset"] < 0:
        raise ProjectError("invalid context cursor offset")
    return value


__all__ = ["decode", "encode", "root_digest"]
