#!/usr/bin/env python
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path


def run(command: list[str], cwd: Path) -> dict[str, object]:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, shell=False)
    return {
        "command": command,
        "exitCode": result.returncode,
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
        "stdoutTail": result.stdout[-3000:],
        "stderrTail": result.stderr[-3000:],
    }


def changed_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]


def source_text(root: Path, paths: list[str]) -> str:
    parts: list[str] = []
    for relative in paths:
        path = root / relative
        if path.is_file() and path.suffix.lower() in {".ts", ".tsx", ".sql", ".md"}:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def has_all(text: str, patterns: list[str]) -> bool:
    return all(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: judge.py <candidate-dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    paths = changed_paths(root)
    text = source_text(root, paths)
    gates = [
        run(["npm.cmd", "test"], root),
        run(["npm.cmd", "run", "test:integration"], root),
        run(["npm.cmd", "run", "typecheck"], root),
        run(["npm.cmd", "run", "build"], root),
    ]
    signals = {
        "weeklyGoalModel": has_all(text, [r"weekly.?goal|周目标", r"subject|科目", r"target|目标量", r"deadline|截止", r"importance|重要"]),
        "confirmation": has_all(text, [r"confirm|确认|preview|预览", r"goal|目标"]),
        "overloadEvidence": has_all(text, [r"overload|排多", r"energy|精力", r"actual|实际"]),
        "weeklyReview": has_all(text, [r"planned|计划", r"actual|实际", r"completed|完成", r"defer|延期"]),
        "explicitNextWeek": has_all(text, [r"next.?week|下周", r"confirm|确认|preview|预览", r"reschedul|调整|顺延"]),
        "supporterAggregate": has_all(text, [r"support|支持者", r"progress|进度", r"actual|实际"]),
        "threeSuggestionKinds": has_all(text, [r"reduce|减少", r"delay|延后", r"split|拆小"]),
        "gentleResponses": "收到，我陪你" in text and "今天先休息" in text,
        "milestoneReaction": has_all(text, [r"milestone|stage|阶段", r"reaction|回应|support|支持"]),
        "privacyBoundary": has_all(text, [r"consent|authoriz|sharing|授权|共享", r"aggregate|汇总|整体进度"]),
    }
    payload = {
        "schemaVersion": 1,
        "candidate": str(root),
        "changedPaths": paths,
        "gates": gates,
        "mandatoryGatesPassed": all(gate["exitCode"] == 0 for gate in gates),
        "staticDiscoverySignals": signals,
        "staticSignalCount": sum(signals.values()),
        "note": "Signals aid blind review; score must be assigned from physical behavior/source evidence using RUBRIC.md.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["mandatoryGatesPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
