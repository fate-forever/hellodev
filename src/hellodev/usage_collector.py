"""Privacy-preserving collection of completed-turn Codex runtime usage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from . import governance
from .project import ProjectError, resolve_root


COLLECTOR_SCHEMA_VERSION = 1
MAX_SESSION_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_SUBAGENT_THREADS = 32
MAX_COLLECTOR_BYTES = 1024 * 1024 * 1024
MAX_COLLECTOR_LINES = 5_000_000
MAX_COLLECTOR_EVENTS = 2_000_000
MAX_SESSION_FILES = 100_000
MAX_DISCOVERY_ENTRIES = 500_000
THREAD_ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
USAGE_FIELDS = ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens")
ZERO_USAGE = {field: 0 for field in USAGE_FIELDS}
JSON_STRING = r'"(?:\\.|[^"\\])*"'
SESSION_META_PATTERN = re.compile(
    rf'^\{{"timestamp":(?P<outer>{JSON_STRING}),"type":"session_meta","payload":\{{'
    rf'(?:"session_id":{JSON_STRING},)?"id":(?P<thread>{JSON_STRING}),(?P<identity>.{{0,4096}}?)'
    rf'"timestamp":(?P<payload>{JSON_STRING}),(?P<metadata>.{{0,4096}}?)"cwd":(?P<cwd>{JSON_STRING})(?:,|\}})'
)
TURN_EVENT_PATTERN = re.compile(
    rf'^\{{"timestamp":(?P<timestamp>{JSON_STRING}),"type":"event_msg","payload":\{{'
    rf'"type":"(?P<event>task_started|task_complete)","turn_id":(?P<turn>{JSON_STRING})(?:,|\}})'
)
SUBAGENT_EVENT_PATTERN = re.compile(
    rf'^\{{"timestamp":(?P<timestamp>{JSON_STRING}),"type":"event_msg","payload":\{{'
    rf'"type":"sub_agent_activity",(?P<metadata>.{{0,4096}}?)"agent_thread_id":(?P<thread>{JSON_STRING})(?:,|\}})'
)
TOKEN_EVENT_PATTERN = re.compile(
    rf'^\{{"timestamp":(?P<timestamp>{JSON_STRING}),"type":"event_msg","payload":\{{'
    rf'"type":"token_count",'
)
TOKEN_NULL_PATTERN = re.compile(
    rf'^\{{"timestamp":(?P<timestamp>{JSON_STRING}),"type":"event_msg","payload":\{{'
    rf'"type":"token_count","info":null(?:,|\}})'
)
TOKEN_USAGE_PATTERN = re.compile(
    rf'^\{{"timestamp":(?P<timestamp>{JSON_STRING}),"type":"event_msg","payload":\{{'
    rf'"type":"token_count","info":\{{"total_token_usage":\{{'
    rf'"input_tokens":(?P<input>-?\d+),'
    rf'"cached_input_tokens":(?P<cached>-?\d+),'
    rf'"output_tokens":(?P<output>-?\d+),'
    rf'"reasoning_output_tokens":(?P<reasoning>-?\d+),'
    rf'"total_tokens":(?P<total>-?\d+)\}}(?:,|\}})'
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_string(value: str, label: str) -> str:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ProjectError(f"invalid Codex {label}") from error
    if not isinstance(decoded, str):
        raise ProjectError(f"invalid Codex {label}")
    return decoded


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _record_event(scan: dict[str, Any]) -> None:
    scan["events"] += 1
    if scan["events"] > MAX_COLLECTOR_EVENTS:
        raise ProjectError("Codex collector event budget exceeded")


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ProjectError(f"invalid Codex {label} timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProjectError(f"invalid Codex {label} timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProjectError(f"invalid Codex {label} timestamp")
    return result


def _thread_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or THREAD_ID_PATTERN.fullmatch(value) is None:
        raise ProjectError(f"invalid Codex {label} id")
    return value


def _breakdown(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ProjectError(f"invalid Codex {label} usage")
    source_fields = {
        "input_tokens": "inputTokens",
        "cached_input_tokens": "cachedInputTokens",
        "output_tokens": "outputTokens",
        "reasoning_output_tokens": "reasoningOutputTokens",
        "total_tokens": "totalTokens",
    }
    if set(value) != set(source_fields):
        raise ProjectError(f"invalid Codex {label} usage fields")
    result = {target: value[source] for source, target in source_fields.items()}
    if any(type(item) is not int or item < 0 or item > governance.MAX_USAGE_TOKENS for item in result.values()):
        raise ProjectError(f"invalid Codex {label} usage counts")
    if result["cachedInputTokens"] > result["inputTokens"]:
        raise ProjectError(f"invalid Codex {label} cached input usage")
    if result["reasoningOutputTokens"] > result["outputTokens"]:
        raise ProjectError(f"invalid Codex {label} reasoning usage")
    if result["inputTokens"] + result["outputTokens"] != result["totalTokens"]:
        raise ProjectError(f"invalid Codex {label} total usage")
    return result


def _add(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {field: left[field] + right[field] for field in USAGE_FIELDS}


def _subtract(final: dict[str, int], baseline: dict[str, int], label: str) -> dict[str, int]:
    result = {field: final[field] - baseline[field] for field in USAGE_FIELDS}
    if any(value < 0 for value in result.values()):
        raise ProjectError(f"Codex cumulative usage moved backwards for {label}")
    if result["cachedInputTokens"] > result["inputTokens"]:
        raise ProjectError(f"Codex cumulative cached usage is inconsistent for {label}")
    if result["reasoningOutputTokens"] > result["outputTokens"]:
        raise ProjectError(f"Codex cumulative reasoning usage is inconsistent for {label}")
    if result["inputTokens"] + result["outputTokens"] != result["totalTokens"]:
        raise ProjectError(f"Codex cumulative total usage is inconsistent for {label}")
    return result


def _safe_session_file(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = candidate.resolve()
    if not candidate.exists() or not candidate.is_file():
        raise ProjectError("Codex session file does not exist")
    if _is_reparse(candidate):
        raise ProjectError("refusing symlinked Codex session file")
    if candidate.suffix.casefold() != ".jsonl":
        raise ProjectError("Codex session file must be JSONL")
    current = candidate.parent
    while current != Path(current.anchor):
        if _is_reparse(current):
            raise ProjectError("refusing Codex session path through a reparse point")
        current = current.parent
    size = candidate.stat().st_size
    if size <= 0 or size > MAX_SESSION_BYTES:
        raise ProjectError("Codex session file size is outside the collector limit")
    return candidate.resolve()


def _codex_home(value: str | Path | None) -> Path:
    configured = value if value is not None else os.environ.get("CODEX_HOME")
    candidate = Path(configured).expanduser() if configured else Path.home() / ".codex"
    if not candidate.exists() or not candidate.is_dir() or _is_reparse(candidate):
        raise ProjectError("Codex home is unavailable or unsafe")
    return candidate.resolve()


def _bounded_session_files(directory: Path):
    stack = [directory]
    entries_seen = 0
    files_seen = 0
    while stack:
        current = stack.pop()
        if current != directory and _is_reparse(current):
            continue
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > MAX_DISCOVERY_ENTRIES:
                        raise ProjectError("Codex session discovery entry limit reached")
                    candidate = Path(entry.path)
                    if entry.is_symlink() or _is_reparse(candidate):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(candidate)
                    elif entry.is_file(follow_symlinks=False):
                        files_seen += 1
                        if files_seen > MAX_SESSION_FILES:
                            raise ProjectError("Codex session file discovery limit reached")
                        yield candidate
        except OSError as error:
            raise ProjectError(f"Codex session discovery failed: {error}") from error


def _find_session(thread: str, home: Path) -> Path:
    identifier = _thread_id(thread, "thread")
    matches: list[Path] = []
    for directory_name in ("sessions", "archived_sessions"):
        directory = home / directory_name
        if not directory.exists() or not directory.is_dir() or _is_reparse(directory):
            continue
        for candidate in _bounded_session_files(directory):
            if candidate.name.endswith(f"-{identifier}.jsonl"):
                safe = _safe_session_file(candidate)
                try:
                    safe.relative_to(directory.resolve())
                except ValueError as error:
                    raise ProjectError("Codex session path escapes the session root") from error
                matches.append(safe)
    unique = sorted(set(matches))
    if not unique:
        raise ProjectError("Codex session file was not found for the selected thread")
    if len(unique) != 1:
        raise ProjectError("multiple Codex session files match the selected thread")
    return unique[0]


def _parse_session(
    path: Path,
    expected_thread: str | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scan = budget if budget is not None else {"paths": set(), "bytes": 0, "lines": 0, "events": 0}
    path_key = str(path)
    if path_key in scan["paths"]:
        raise ProjectError("Codex session was selected more than once")
    scan["paths"].add(path_key)
    session_id: str | None = None
    session_started_at: datetime | None = None
    session_cwd: str | None = None
    tasks: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    before = path.stat()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
            raise ProjectError("Codex session changed before collection")
        line_number = 0
        while True:
            raw_bytes = handle.readline(MAX_LINE_BYTES + 1)
            if not raw_bytes:
                break
            line_number += 1
            scan["bytes"] += len(raw_bytes)
            scan["lines"] += 1
            if len(raw_bytes) > MAX_LINE_BYTES:
                raise ProjectError("Codex session line exceeds the collector limit")
            if scan["bytes"] > MAX_COLLECTOR_BYTES or scan["lines"] > MAX_COLLECTOR_LINES:
                raise ProjectError("Codex collector scan budget exceeded")
            try:
                raw_line = raw_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ProjectError(f"invalid Codex session encoding at line {line_number}") from error
            match = SESSION_META_PATTERN.match(raw_line)
            if match is not None:
                _record_event(scan)
                session_id = _thread_id(_json_string(match.group("thread"), "session id"), "session")
                session_started_at = _timestamp(
                    _json_string(match.group("payload"), "session timestamp"),
                    "session",
                )
                session_cwd = _json_string(match.group("cwd"), "session cwd")
                continue
            turn_match = TURN_EVENT_PATTERN.match(raw_line)
            if turn_match is not None:
                _record_event(scan)
                observed_at = _timestamp(_json_string(turn_match.group("timestamp"), "event timestamp"), "event")
                event_type = turn_match.group("event")
                turn_id = _thread_id(_json_string(turn_match.group("turn"), "turn id"), "turn")
                if event_type == "task_started":
                    if turn_id in tasks:
                        raise ProjectError("duplicate Codex task_started event")
                    tasks[turn_id] = {
                        "turnId": turn_id,
                        "startedAt": observed_at,
                        "startedAtText": _json_string(turn_match.group("timestamp"), "event timestamp"),
                        "startedLine": line_number,
                    }
                else:
                    if turn_id not in tasks:
                        # Forked rollouts can replay a parent completion without
                        # its matching start. It is not a child task interval and
                        # is deliberately ignored.
                        continue
                    if "completedLine" in tasks[turn_id]:
                        raise ProjectError("duplicate Codex task_complete event")
                    if observed_at < tasks[turn_id]["startedAt"]:
                        raise ProjectError("Codex task completion precedes task start")
                    item = {
                        **tasks[turn_id],
                        "completedAt": observed_at,
                        "completedAtText": _json_string(turn_match.group("timestamp"), "event timestamp"),
                        "completedLine": line_number,
                    }
                    tasks[turn_id] = item
                    completed.append(item)
                continue
            subagent_match = SUBAGENT_EVENT_PATTERN.match(raw_line)
            if subagent_match is not None:
                _record_event(scan)
                observed_at = _timestamp(
                    _json_string(subagent_match.group("timestamp"), "event timestamp"),
                    "event",
                )
                child_id = _thread_id(
                    _json_string(subagent_match.group("thread"), "subagent thread id"),
                    "subagent thread",
                )
                activities.append({"observedAt": observed_at, "lineNumber": line_number, "threadId": child_id})
                continue
            if TOKEN_EVENT_PATTERN.match(raw_line) is not None:
                _record_event(scan)
                if TOKEN_NULL_PATTERN.match(raw_line) is not None:
                    continue
                token_match = TOKEN_USAGE_PATTERN.match(raw_line)
                if token_match is None:
                    raise ProjectError(f"unsupported Codex token metadata at line {line_number}")
                observed_at = _timestamp(_json_string(token_match.group("timestamp"), "event timestamp"), "event")
                usage = _breakdown(
                    {
                        "input_tokens": int(token_match.group("input")),
                        "cached_input_tokens": int(token_match.group("cached")),
                        "output_tokens": int(token_match.group("output")),
                        "reasoning_output_tokens": int(token_match.group("reasoning")),
                        "total_tokens": int(token_match.group("total")),
                    },
                    "cumulative",
                )
                if snapshots:
                    previous = snapshots[-1]["usage"]
                    if any(usage[field] < previous[field] for field in USAGE_FIELDS):
                        raise ProjectError("Codex cumulative usage moved backwards")
                    if usage["totalTokens"] == previous["totalTokens"] and usage != previous:
                        raise ProjectError("Codex repeated cumulative usage is inconsistent")
                snapshots.append({"observedAt": observed_at, "lineNumber": line_number, "usage": usage})
                continue
        after = os.fstat(handle.fileno())
        if (after.st_dev, after.st_ino, after.st_size) != (opened.st_dev, opened.st_ino, opened.st_size):
            raise ProjectError("Codex session changed during collection")
    if session_id is None:
        raise ProjectError("Codex session metadata was not found")
    if session_started_at is None:
        raise ProjectError("Codex session start timestamp was not found")
    if session_cwd is None:
        raise ProjectError("Codex session cwd was not found")
    if expected_thread is not None and session_id != _thread_id(expected_thread, "thread"):
        raise ProjectError("Codex session metadata does not match the selected thread")
    return {
        "threadId": session_id,
        "sessionStartedAt": session_started_at,
        "sessionCwd": session_cwd,
        "taskStarts": list(tasks.values()),
        "completed": completed,
        "snapshots": snapshots,
        "activities": activities,
    }


def _interval_usage(data: dict[str, Any], started_line: int, completed_line: int, label: str) -> dict[str, int]:
    baseline = ZERO_USAGE
    final = ZERO_USAGE
    observed_in_interval = False
    baseline_found = False
    for snapshot in data["snapshots"]:
        line_number = snapshot["lineNumber"]
        if line_number < started_line:
            baseline = snapshot["usage"]
            baseline_found = True
        if started_line < line_number <= completed_line:
            final = snapshot["usage"]
            observed_in_interval = True
    if not observed_in_interval:
        raise ProjectError(f"Codex token metadata is unavailable for {label}")
    prior_tasks = [item for item in data["taskStarts"] if item["startedLine"] < started_line]
    if prior_tasks and not baseline_found:
        raise ProjectError(f"Codex cumulative baseline is unavailable for {label}")
    return _subtract(final, baseline, label)


def _session_index(home: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for directory_name in ("sessions", "archived_sessions"):
        directory = home / directory_name
        if not directory.exists() or not directory.is_dir() or _is_reparse(directory):
            continue
        for candidate in _bounded_session_files(directory):
            if not candidate.name.startswith("rollout-"):
                continue
            match = re.search(r"-([0-9a-f-]{36})\.jsonl$", candidate.name)
            if match is None or THREAD_ID_PATTERN.fullmatch(match.group(1)) is None:
                continue
            identifier = match.group(1)
            safe = _safe_session_file(candidate)
            try:
                safe.relative_to(directory.resolve())
            except ValueError as error:
                raise ProjectError("Codex session path escapes the session root") from error
            if identifier in result and result[identifier] != safe:
                raise ProjectError("duplicate Codex session thread id")
            result[identifier] = safe
    return result


def _collect_descendants(
    data: dict[str, Any],
    started_line: int,
    completed_line: int,
    started_at: datetime,
    completed_at: datetime,
    index: dict[str, Path],
    visited: set[str],
    budget: dict[str, Any],
    cache: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], set[str]]:
    child_activity: dict[str, datetime] = {}
    for item in data["activities"]:
        if started_line < item["lineNumber"] <= completed_line:
            current = child_activity.get(item["threadId"])
            if current is None or item["observedAt"] < current:
                child_activity[item["threadId"]] = item["observedAt"]
    child_ids = sorted(child_activity)
    total = dict(ZERO_USAGE)
    descendants: set[str] = set()
    for child_id in child_ids:
        if child_id in visited or child_id in descendants:
            continue
        if len(visited) + len(descendants) >= MAX_SUBAGENT_THREADS:
            raise ProjectError("Codex subagent collector limit reached")
        child_path = index.get(child_id)
        if child_path is None:
            raise ProjectError("Codex subagent session file is missing; exact total is unavailable")
        child_data = cache.get(child_id)
        if child_data is None:
            child_data = _parse_session(child_path, child_id, budget)
            cache[child_id] = child_data
        candidate_tasks = [
            item
            for item in child_data["taskStarts"]
            if item["startedAt"] >= child_data["sessionStartedAt"]
            and started_at <= item["startedAt"] <= completed_at
        ]
        if not candidate_tasks:
            raise ProjectError("Codex subagent task start is missing; exact total is unavailable")
        if any("completedLine" not in item or item["completedAt"] > completed_at for item in candidate_tasks):
            raise ProjectError("Codex subagent task is incomplete; exact total is unavailable")
        child_usage = dict(ZERO_USAGE)
        for item in candidate_tasks:
            child_usage = _add(
                child_usage,
                _interval_usage(child_data, item["startedLine"], item["completedLine"], f"subagent {child_id}"),
            )
        child_started = min(candidate_tasks, key=lambda item: item["startedLine"])
        child_completed = max(candidate_tasks, key=lambda item: item["completedLine"])
        nested_usage, nested_ids = _collect_descendants(
            child_data,
            child_started["startedLine"],
            child_completed["completedLine"],
            child_started["startedAt"],
            child_completed["completedAt"],
            index,
            visited | descendants | {child_id},
            budget,
            cache,
        )
        total = _add(total, _add(child_usage, nested_usage))
        descendants.add(child_id)
        descendants.update(nested_ids)
    return total, descendants


def _load_collection_context(
    root: str | Path,
    *,
    session_file: str | Path | None = None,
    thread_id: str | None = None,
    codex_home: str | Path | None = None,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any], bool]:
    resolved_root = resolve_root(root)
    home = _codex_home(codex_home)
    selected_thread = thread_id or os.environ.get("CODEX_THREAD_ID")
    implicit_runtime_selection = session_file is None and thread_id is None and codex_home is None
    if session_file is None:
        if selected_thread is None:
            raise ProjectError("CODEX_THREAD_ID is unavailable; pass --thread-id or --session")
        session_path = _find_session(selected_thread, home)
    else:
        session_path = _safe_session_file(Path(session_file))
    budget: dict[str, Any] = {"paths": set(), "bytes": 0, "lines": 0, "events": 0}
    data = _parse_session(session_path, selected_thread, budget)
    if implicit_runtime_selection:
        cwd = Path(data["sessionCwd"]).expanduser()
        if not cwd.is_absolute():
            raise ProjectError("Codex session cwd is not absolute")
        resolved_cwd = cwd.resolve()
        try:
            resolved_root.relative_to(resolved_cwd)
        except ValueError:
            try:
                resolved_cwd.relative_to(resolved_root)
            except ValueError as error:
                raise ProjectError("Codex session cwd does not match the HelloDev project") from error
    return resolved_root, home, data, budget, implicit_runtime_selection


def _scope_sha256(data: dict[str, Any], turn: dict[str, Any]) -> str:
    return _sha256(f"codex-turn:{data['threadId']}:{turn['turnId']}")


def _collect_turn(
    resolved_root: Path,
    data: dict[str, Any],
    turn: dict[str, Any],
    index: dict[str, Path],
    budget: dict[str, Any],
    cache: dict[str, dict[str, Any]],
    implicit_runtime_selection: bool,
) -> dict[str, Any]:
    root_usage = _interval_usage(data, turn["startedLine"], turn["completedLine"], "root turn")
    subagent_usage, subagent_ids = _collect_descendants(
        data,
        turn["startedLine"],
        turn["completedLine"],
        turn["startedAt"],
        turn["completedAt"],
        index,
        {data["threadId"]},
        budget,
        cache,
    )
    aggregate = _add(root_usage, subagent_usage)
    source_kind = "codex-runtime" if implicit_runtime_selection else "codex-runtime-import"
    source_trust = "runtime-observed" if implicit_runtime_selection else "asserted-runtime"
    stored = governance.record_runtime_usage(
        resolved_root,
        input_tokens=aggregate["inputTokens"],
        cached_input_tokens=aggregate["cachedInputTokens"],
        output_tokens=aggregate["outputTokens"],
        reasoning_output_tokens=aggregate["reasoningOutputTokens"],
        subagent_tokens=subagent_usage["totalTokens"],
        subagent_count=len(subagent_ids),
        completed_at=turn["completedAtText"],
        source_sha256=_sha256(f"codex-rollout:{resolved_root}:{data['threadId']}"),
        scope_sha256=_scope_sha256(data, turn),
        source_kind=source_kind,
        source_trust=source_trust,
    )
    record = stored["record"]
    return {
        "schemaVersion": COLLECTOR_SCHEMA_VERSION,
        "state": stored["state"],
        "reasonCode": "previous-completed-codex-turn",
        "usageRecordId": record["id"],
        "completedAt": record["completedAt"],
        "totalTokens": record["totalTokens"],
        "rootTokens": record["totalTokens"] - record["subagentTokens"],
        "subagentTokens": record["subagentTokens"],
        "subagentCount": record["subagentCount"],
        "breakdown": governance.usage_breakdown_projection(record),
        "sourceKind": record["sourceKind"],
        "sourceTrust": record["sourceTrust"],
        "accuracy": record["accuracy"],
        "measurement": record["measurement"],
        "attestation": record["attestation"],
        "receiptSha256": record["receiptSha256"],
        "persistencePerformed": stored["state"] == "recorded",
        "transcriptContentPersisted": False,
        "rawEventPersisted": False,
        "estimated": False,
    }


def collect_previous_codex_turn(
    root: str | Path,
    *,
    session_file: str | Path | None = None,
    thread_id: str | None = None,
    codex_home: str | Path | None = None,
) -> dict[str, Any]:
    resolved_root, home, data, budget, implicit_runtime_selection = _load_collection_context(
        root,
        session_file=session_file,
        thread_id=thread_id,
        codex_home=codex_home,
    )
    if not data["completed"]:
        return {
            "schemaVersion": COLLECTOR_SCHEMA_VERSION,
            "state": "unavailable",
            "reasonCode": "no-completed-turn",
            "persistencePerformed": False,
            "transcriptContentPersisted": False,
            "rawEventPersisted": False,
            "estimated": False,
        }
    turn = data["completed"][-1]
    has_subagents = any(turn["startedLine"] < item["lineNumber"] <= turn["completedLine"] for item in data["activities"])
    index = _session_index(home) if has_subagents else {}
    value = _collect_turn(
        resolved_root, data, turn, index, budget, {}, implicit_runtime_selection
    )
    if implicit_runtime_selection:
        from . import efficiency_cycles

        value["reflectionCycle"] = efficiency_cycles.reconcile(resolved_root)
    return value


def sync_codex_usage(
    root: str | Path,
    *,
    session_file: str | Path | None = None,
    thread_id: str | None = None,
    codex_home: str | Path | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ProjectError("usage sync limit must be between 1 and 500")
    resolved_root, home, data, budget, implicit_runtime_selection = _load_collection_context(
        root,
        session_file=session_file,
        thread_id=thread_id,
        codex_home=codex_home,
    )
    existing_scopes = {item["scopeSha256"] for item in governance.list_runtime_usage_records(resolved_root)}
    unrecorded = [turn for turn in data["completed"] if _scope_sha256(data, turn) not in existing_scopes]
    selected = unrecorded[:limit]
    has_subagents = any(
        turn["startedLine"] < item["lineNumber"] <= turn["completedLine"]
        for turn in selected
        for item in data["activities"]
    )
    index = _session_index(home) if has_subagents else {}
    cache: dict[str, dict[str, Any]] = {}
    recorded = 0
    existing = 0
    skipped = 0
    latest: dict[str, Any] | None = None
    for turn in selected:
        try:
            latest = _collect_turn(
                resolved_root, data, turn, index, budget, cache, implicit_runtime_selection
            )
        except ProjectError:
            skipped += 1
            continue
        if latest["state"] == "recorded":
            recorded += 1
        else:
            existing += 1
    from . import efficiency_cycles

    reflection = efficiency_cycles.reconcile(resolved_root)
    remaining = max(0, len(unrecorded) - len(selected)) + skipped
    return {
        "schemaVersion": COLLECTOR_SCHEMA_VERSION,
        "state": "partial" if skipped else "synced" if recorded else "current",
        "sourceTrust": "runtime-observed" if implicit_runtime_selection else "asserted-runtime",
        "completedTurnCount": len(data["completed"]),
        "selectedCount": len(selected),
        "recordedCount": recorded,
        "existingCount": existing,
        "skippedCount": skipped,
        "remainingUnrecordedCount": remaining,
        "latest": latest,
        "reflectionCycle": reflection,
        "persistencePerformed": bool(recorded or reflection["persistencePerformed"]),
        "transcriptContentPersisted": False,
        "rawEventPersisted": False,
        "estimated": False,
    }
