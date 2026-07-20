"""Build a deterministic HelloDev platform bundle from a prepared staging tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hellodev.bundle_builder import build


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(args.staging), Path(args.spec), Path(args.output)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
