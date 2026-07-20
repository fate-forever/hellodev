"""Run a Trellis project script with its sibling modules importable.

The Windows embeddable Python distribution intentionally omits the executed
script directory from ``sys.path``. Trellis project scripts import their
``common`` package from that directory, so the portable distribution uses this
small runner instead of weakening Python's isolated-mode configuration.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main(arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values:
        print("Trellis script path is required", file=sys.stderr)
        return 2
    script = Path(values[0]).expanduser().resolve()
    if not script.is_file():
        print(f"Trellis script is missing: {script}", file=sys.stderr)
        return 2

    previous_argv = sys.argv[:]
    previous_path = sys.path[:]
    sys.argv = [str(script), *values[1:]]
    sys.path.insert(0, str(script.parent))
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = previous_argv
        sys.path[:] = previous_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
