"""Fail closed unless a release tag exactly matches both package version sources."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def verify(tag: str) -> dict[str, str]:
    if re.fullmatch(r"v\d+\.\d+\.\d+", tag) is None:
        raise ValueError("release tag must have exact vMAJOR.MINOR.PATCH form")
    expected = tag[1:]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if project_match is None:
        raise ValueError("project.version literal is missing")
    project_version = project_match.group(1)
    init_text = (ROOT / "src" / "hellodev" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE)
    if match is None:
        raise ValueError("hellodev.__version__ literal is missing")
    module_version = match.group(1)
    lock_path = ROOT / "src" / "hellodev" / "distribution" / "component-lock-v1.json"
    try:
        lock_version = json.loads(lock_path.read_text(encoding="utf-8"))["distributionVersion"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"component lock version is unavailable: {error}") from error
    if expected != project_version or expected != module_version or expected != lock_version:
        raise ValueError(
            f"release version mismatch: tag={expected}, pyproject={project_version}, module={module_version}, componentLock={lock_version}"
        )
    return {"tag": tag, "version": expected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    args = parser.parse_args(argv)
    try:
        value = verify(args.tag)
    except ValueError as error:
        print(f"release-version: {error}", file=sys.stderr)
        return 2
    print(f"release-version: {value['tag']} matches {value['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
