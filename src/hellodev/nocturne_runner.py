"""Headless launcher that separates bundled Nocturne code from user data."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

from . import components


def _safe_directory(value: str, label: str, *, create: bool = False) -> Path:
    path = Path(os.path.abspath(os.fspath(Path(value).expanduser())))
    for candidate in (path, *path.parents):
        if components._is_link_or_reparse(candidate):
            raise ValueError(f"{label} contains a link or reparse point: {candidate}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label} is missing or unsafe: {path}")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return path


def _safe_data_file(path: Path, label: str) -> None:
    if components._is_link_or_reparse(path) or (path.exists() and not path.is_file()):
        raise ValueError(f"{label} is linked or unsafe: {path}")


def launch(component_root: str, data_root: str) -> None:
    component = _safe_directory(component_root, "Nocturne component root")
    data = _safe_directory(data_root, "Nocturne data root", create=True)
    backend = component / "backend"
    server = backend / "mcp_server.py"
    config_file = backend / "config.py"
    if (
        components._is_link_or_reparse(backend)
        or components._is_link_or_reparse(server)
        or components._is_link_or_reparse(config_file)
        or not server.is_file()
        or not config_file.is_file()
    ):
        raise ValueError("bundled Nocturne backend entry points are missing or unsafe")

    sys.path.insert(0, str(backend))
    os.environ["SKIP_FRONTEND_BUILD"] = "true"
    os.environ["_NOCTURNE_SSE_MODE"] = "1"
    import config  # type: ignore[import-not-found]

    config.ROOT_DIR = data
    config.CONFIG_PATH = data / "config.json"
    database = (data / "nocturne_data.db").resolve().as_posix()
    expected_database_url = f"sqlite+aiosqlite:///{database}"
    _safe_data_file(config.CONFIG_PATH, "Nocturne config")
    for suffix in ("", "-wal", "-shm"):
        _safe_data_file(data / f"nocturne_data.db{suffix}", "Nocturne database")
    config.DEFAULTS = {
        **config.DEFAULTS,
        "database_url": expected_database_url,
        "auto_open_browser": False,
        "host": "127.0.0.1",
    }
    if config.CONFIG_PATH.exists():
        try:
            existing = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Nocturne config is invalid: {error}") from error
        if not isinstance(existing, dict):
            raise ValueError("Nocturne config must be a JSON object")
        if existing.get("database_url") != expected_database_url:
            raise ValueError("bundled Nocturne database_url must remain inside its dedicated data root")
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".config.", suffix=".json", dir=data)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(config.DEFAULTS, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            _safe_data_file(config.CONFIG_PATH, "Nocturne config")
            os.replace(temporary, config.CONFIG_PATH)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    runpy.run_path(str(server), run_name="__main__")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component-root", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args(argv)
    launch(args.component_root, args.data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
