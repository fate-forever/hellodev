"""Verify an exact HelloDev platform bundle archive."""

from __future__ import annotations

import argparse
import json

from hellodev.bundle_builder import verify_archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    args = parser.parse_args()
    print(json.dumps(verify_archive(args.archive), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
