"""Minimal typed Host SDK example with no Trellis or Nocturne dependency."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from hellodev import capabilities, checkpoints, lifecycle
from hellodev.host_sdk import HostClient, HostRequest, HostResult
from hellodev.project import init_project


def run(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    init_project(root)
    lifecycle.start(root)
    capabilities.refresh(root)

    client = HostClient(root, supported_versions=("1.0",))
    envelope = client.prepare(
        HostRequest(intent="code", total_token_ceiling=2_000, max_subagents=0)
    )

    # The external host owns real execution. This example reports no token
    # values rather than estimating them.
    completed = client.complete(
        envelope,
        HostResult(outcome="succeeded", total_tokens=None, subagent_tokens=None),
    )
    checkpoint = checkpoints.export(root)
    verified = checkpoints.verify(root, checkpoint)
    return {
        "protocolVersion": client.protocol_version,
        "envelopeId": envelope.id,
        "completionState": completed["state"],
        "usageTrust": completed["completion"]["usageTrust"],
        "checkpointMatched": verified["matched"],
        "pendingCount": len(client.pending()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None, help="optional disposable project path")
    args = parser.parse_args()
    if args.root is None:
        with tempfile.TemporaryDirectory(prefix="hellodev-host-sdk-") as directory:
            print(json.dumps(run(Path(directory)), sort_keys=True))
    else:
        print(json.dumps(run(Path(args.root).expanduser().resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
