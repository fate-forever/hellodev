"""Split fast development checks from the full HelloDev release gate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAST_TESTS = (
    "tests.test_context_policy",
    "tests.test_routing",
    "tests.test_profiles",
    "tests.test_knowledge_flows",
    "tests.test_f1_cli",
    "tests.test_f1_security",
    "tests.test_approval_atomicity",
    "tests.test_contracts",
    "tests.test_resume_gates",
    "tests.test_delegation",
    "tests.test_f2_cli",
    "tests.test_f2_atomicity",
    "tests.test_f2_dashboard",
    "tests.test_optimization",
    "tests.test_host_bridge",
    "tests.test_policy_evolution",
    "tests.test_v11_cli",
)


def _run(name: str, argv: list[str]) -> dict[str, object]:
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return {"name": name, "exitCode": completed.returncode}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HelloDev development or release verification.")
    parser.add_argument("--scope", choices=("fast", "full"), default="fast")
    args = parser.parse_args(argv)
    steps = [_run("compile", [sys.executable, "-m", "compileall", "-q", "src"])]
    if args.scope == "fast":
        steps.append(_run("fast-tests", [sys.executable, "-m", "unittest", *FAST_TESTS, "-v"]))
    else:
        steps.append(_run("full-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]))
        node = shutil.which("node")
        if node:
            steps.append(_run("dashboard-js", [node, "--check", "src/hellodev/dashboard_assets/app.js"]))
        else:
            steps.append({"name": "dashboard-js", "exitCode": 0, "state": "skipped-node-unavailable"})
    succeeded = all(step["exitCode"] == 0 for step in steps)
    print(json.dumps({"schemaVersion": 1, "scope": args.scope, "succeeded": succeeded, "steps": steps}, sort_keys=True))
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
