"""Command-line interface for the standalone HelloDev core."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .application import ProjectClient
from .adapters import nocturne, trellis
from . import (
    approval,
    audit,
    briefs,
    capabilities,
    components,
    checkpoints,
    context_runtime,
    context_policy,
    contracts,
    dashboard,
    delegation,
    gates,
    governance,
    host_bridge,
    host_sdk,
    intelligence,
    integrations,
    knowledge_flows,
    lifecycle,
    optimization,
    policy_evolution,
    profiles,
    receipts,
    repository_tools,
    resume,
    routing,
    sagas,
    transactions,
    drift,
    efficiency_cycles,
    usage_collector,
    mcp_gateway,
    onboarding,
)
from .command_rendering import command_line as render_command_line, rewrite_commands
from .project import (
    ProjectError,
    configure_nocturne,
    create_task,
    init_project,
    list_tasks,
    load_config,
    nocturne_config,
    project_initialized,
    resolve_root,
    show_task,
)
from .snapshot import default_snapshot_path, verify as verify_snapshot


def _parser(show_all: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hellodev",
        description="Standalone HelloDev development workflow CLI.",
        epilog=(
            "Progressive disclosure: daily = open -> next -> do; "
            "recovery = resume; setup = setup -> onboard -> integrate; advanced = host, policy, drift, optimize, usage, delegate, audit, "
            "MCP transport, and native commands. Use --help-all to disclose every command family."
        ),
    )
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument("--version", action="version", version=f"hellodev {__version__}")
    parser.add_argument("--help-all", action="store_true", help="show daily, setup, recovery, and advanced commands")
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar=(
            "COMMAND"
            if show_all
            else "{open,next,do,status,resume,setup,onboard,components,integrate,doctor}"
        ),
    )
    commands.add_parser("init", help="create project-local .hellodev state")
    open_parser = commands.add_parser("open", help="initialize or resume the unified daily workflow")
    open_parser.add_argument("--verbose", action="store_true", help="include full start and capability details")
    commands.add_parser("next", help="show exactly one read-only suggested next command")
    resume_parser = commands.add_parser("resume", help="reconstruct bounded cross-session recovery state")
    resume_parser.add_argument("--context", action="store_true", help="include a bounded resume context pack")
    resume_parser.add_argument("--token-budget", type=int, default=256, help="resume context budget, 32-4096")
    start_parser = commands.add_parser("start", help="start the local lifecycle and refresh the capability cache")
    start_parser.add_argument("--verbose", action="store_true", help="include the full capability cache")
    status_parser = commands.add_parser("status", help="show compact local status")
    status_parser.add_argument("--verbose", action="store_true", help="include the full capability cache")

    setup_parser = commands.add_parser("setup", help="verify the unified bundle and initialize its private data root")
    setup_parser.add_argument("--home", default=None, help="HelloDev home selected by the same HELLODEV_HOME value")
    onboard_parser = commands.add_parser("onboard", help="connect this project to the verified unified distribution")
    onboard_parser.add_argument("--host", choices=("cursor", "codex", "none"), default="cursor")
    onboard_parser.add_argument("--without-memory", action="store_true", help="leave bundled Nocturne disabled")
    onboard_parser.add_argument("--with-trellis", action="store_true", help="prepare a confirmed Trellis project initialization when absent")
    component_parser = commands.add_parser("components", help="inspect or verify bundled Trellis and Nocturne")
    component_commands = component_parser.add_subparsers(dest="component_command", required=True)
    component_commands.add_parser("status", help="show bundle and component availability")
    component_verify = component_commands.add_parser("verify", help="verify manifest-bound component bytes")
    component_verify.add_argument("--component", choices=("trellis", "nocturne"), default=None)

    integrate_parser = commands.add_parser("integrate", help="render or validate project-scoped Agent host setup")
    integrate_commands = integrate_parser.add_subparsers(dest="integrate_command", required=True)
    for name, help_text in (
        ("show", "render a Codex or Cursor MCP snippet without writing it"),
        ("check", "validate the bounded local MCP integration without reading host config"),
    ):
        command = integrate_commands.add_parser(name, help=help_text)
        command.add_argument("--host", choices=("codex", "cursor"), required=True)

    mcp_parser = commands.add_parser("mcp", help="optional official-SDK root-bound MCP transport")
    mcp_commands = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_commands.add_parser("serve", help="serve the bounded daily ProjectClient API over stdio")
    mcp_serve.add_argument("--root", dest="mcp_root", default=None, help="project root bound for the server lifetime")

    lifecycle_parser = commands.add_parser("lifecycle", help="advance or inspect the unified workflow lifecycle")
    lifecycle_commands = lifecycle_parser.add_subparsers(dest="lifecycle_command", required=True)
    lifecycle_commands.add_parser("status", help="show lifecycle state")
    for command_name, help_text in (
        ("plan", "move lifecycle to planned"),
        ("work", "move lifecycle to working"),
        ("check", "move lifecycle to checking"),
        ("finish", "move lifecycle to finished"),
        ("block", "move lifecycle to blocked"),
        ("resume", "resume the previous lifecycle phase"),
    ):
        command = lifecycle_commands.add_parser(command_name, help=help_text)
        command.add_argument("--note", default=None, help="optional one-line transition note")

    capability_parser = commands.add_parser("capabilities", help="cache adapter capability discovery")
    capability_commands = capability_parser.add_subparsers(dest="capability_command", required=True)
    capability_commands.add_parser("status", help="show whether the capability cache is fresh")
    capability_commands.add_parser("refresh", help="refresh the project-local capability cache")

    brief_parser = commands.add_parser("brief", help="build bounded L0/L1/L2 context briefs")
    brief_commands = brief_parser.add_subparsers(dest="brief_command", required=True)
    brief_build = brief_commands.add_parser("build", help="build or reuse a bounded brief cache")
    brief_build.add_argument("--level", choices=("L0", "L1", "L2"), default=None)
    brief_build.add_argument("--intent", choices=tuple(context_policy.INTENT_LEVELS), default=None)
    brief_build.add_argument("--task", default=None, help="optional HelloDev task id")
    brief_build.add_argument("--allow-l2", action="store_true", help="explicitly allow the larger L2 local-context budget")
    brief_show = brief_commands.add_parser("show", help="show a fresh cached brief")
    brief_show.add_argument("--level", choices=("L0", "L1", "L2"), default="L0")
    brief_show.add_argument("--task", default=None, help="optional HelloDev task id")

    context_parser = commands.add_parser("context", help="render a bounded handoff context pack")
    context_commands = context_parser.add_subparsers(dest="context_command", required=True)
    context_suggest = context_commands.add_parser("suggest", help="suggest a deterministic context level for an intent")
    context_suggest.add_argument("--intent", choices=tuple(context_policy.INTENT_LEVELS), required=True)
    context_suggest.add_argument("--level", choices=("L0", "L1", "L2"), default=None)
    context_pack = context_commands.add_parser("pack", help="build a model-neutral bounded handoff text")
    context_pack.add_argument("--level", choices=("L0", "L1", "L2"), default=None)
    context_pack.add_argument("--intent", choices=tuple(context_policy.INTENT_LEVELS), default=None)
    context_pack.add_argument("--task", default=None, help="optional HelloDev task id")
    context_pack.add_argument("--allow-l2", action="store_true", help="explicitly allow the larger L2 local-context budget")
    context_pack.add_argument("--token-budget", type=int, default=1_200, help="conservative token envelope, 128-12000")
    context_pack.add_argument("--resume", action="store_true", help="render the bounded F2 resume projection")
    context_pack.add_argument("--query", default=None, help="specific repository symbol, path, or topic for Context Plane")
    context_pack.add_argument("--scope", choices=("project", "code", "docs"), default="project")
    context_pack.add_argument("--cursor", default=None, help="stable continuation cursor returned by a prior context page")

    smart_parser = commands.add_parser("smart", help="prepare-only lesson routing and narrow retrieval planning")
    smart_commands = smart_parser.add_subparsers(dest="smart_command", required=True)
    smart_classify = smart_commands.add_parser("classify", help="classify a lesson as project or cross-project knowledge")
    smart_classify.add_argument("--lesson", required=True)
    smart_classify.add_argument("--scope", choices=("auto", "project", "cross-project"), default="auto")
    smart_retrieve = smart_commands.add_parser("retrieve", help="create a narrow retrieval plan without querying Nocturne")
    smart_retrieve.add_argument("--scope", choices=("project", "cross-project"), required=True)
    smart_retrieve.add_argument("--query", required=True)
    smart_retrieve.add_argument("--level", choices=("L0", "L1", "L2"), default="L0")
    smart_retrieve.add_argument("--domain", default=None, help="required narrow Nocturne search domain for cross-project retrieval")
    smart_retrieve.add_argument("--limit", type=int, default=None, help="required bounded result limit (1-20) for cross-project retrieval")
    smart_retrieve.add_argument("--namespace-scope", default=None, help="required declared Nocturne namespace scope; never sent as a tool argument")
    smart_retrieve.add_argument("--approve", default=None, help="approval token; omit to prepare a narrow Nocturne search")
    smart_retrieve.add_argument("--timeout", type=int, default=30, help="timeout in seconds (1-120)")
    smart_persist = smart_commands.add_parser("persist", help="create an evidence-gated persistence plan")
    smart_persist.add_argument("--destination", choices=("trellis", "nocturne"), required=True)
    smart_persist.add_argument("--receipt", default=None)

    delegate_parser = commands.add_parser("delegate", help="audit whether a subagent delegation is justified")
    delegate_commands = delegate_parser.add_subparsers(dest="delegate_command", required=True)
    delegate_audit = delegate_commands.add_parser("audit", help="audit a JSON delegation proposal without spawning")
    delegate_audit.add_argument("--payload", required=True, help="JSON proposal with context and bounded candidates")
    delegate_plan = delegate_commands.add_parser("plan", help="produce a deterministic bounded delegation plan")
    delegate_plan.add_argument("--payload", required=True, help="strict F2 delegation proposal JSON")
    delegate_pack = delegate_commands.add_parser("pack", help="render one selected role's shared-plus-delta context")
    delegate_pack.add_argument("--payload", required=True, help="strict F2 delegation proposal JSON")
    delegate_pack.add_argument("--role", required=True)
    delegate_pack.add_argument("--token-budget", type=int, default=1_200)

    usage_parser = commands.add_parser("usage", help="collect or record source-labelled usage receipts")
    usage_commands = usage_parser.add_subparsers(dest="usage_command", required=True)
    usage_commands.add_parser("status", help="show recorded usage totals")
    usage_record = usage_commands.add_parser("record", help="record externally reported usage counts")
    usage_record.add_argument("--total", type=int, required=True)
    usage_record.add_argument("--subagent", type=int, default=0)
    usage_record.add_argument("--subagents", type=int, default=0)
    usage_record.add_argument("--source", required=True)
    usage_record.add_argument("--scope", default="turn")
    usage_collect = usage_commands.add_parser("collect", help="collect the previous completed Codex turn from runtime metadata")
    usage_collect.add_argument("--session", default=None, help="explicit Codex rollout JSONL path; defaults to CODEX_THREAD_ID discovery")
    usage_collect.add_argument("--thread-id", default=None, help="explicit Codex thread id; defaults to CODEX_THREAD_ID")
    usage_collect.add_argument("--codex-home", default=None, help="Codex home containing sessions/; defaults to CODEX_HOME or ~/.codex")
    usage_sync = usage_commands.add_parser("sync", help="backfill unrecorded completed Codex turns and reconcile 20-turn reflection cycles")
    usage_sync.add_argument("--session", default=None, help="explicit Codex rollout JSONL path; defaults to CODEX_THREAD_ID discovery")
    usage_sync.add_argument("--thread-id", default=None, help="explicit Codex thread id; defaults to CODEX_THREAD_ID")
    usage_sync.add_argument("--codex-home", default=None, help="Codex home containing sessions/; defaults to CODEX_HOME or ~/.codex")
    usage_sync.add_argument("--limit", type=int, default=100, help="maximum new completed turns to inspect (1-500)")

    optimize_parser = commands.add_parser("optimize", help="plan and inspect bounded optimization advice")
    optimize_commands = optimize_parser.add_subparsers(dest="optimize_command", required=True)
    optimize_commands.add_parser("status", help="show read-only optimization state")
    optimize_plan = optimize_commands.add_parser("plan", help="produce a deterministic context and usage preflight")
    optimize_plan.add_argument("--intent", choices=tuple(context_policy.INTENT_LEVELS), required=True)
    optimize_plan.add_argument("--level", choices=("L0", "L1", "L2"), default=None)
    optimize_plan.add_argument("--token-ceiling", type=int, default=None)
    optimize_plan.add_argument("--subagent-token-ceiling", type=int, default=None)
    optimize_plan.add_argument("--max-subagents", type=int, default=0)
    optimize_plan.add_argument("--work", default=None)
    optimize_reflect = optimize_commands.add_parser("reflect", help="record one privacy-preserving decision trace")
    optimize_reflect.add_argument("--intent", choices=tuple(context_policy.INTENT_LEVELS), required=True)
    optimize_reflect.add_argument("--context-level", choices=("L0", "L1", "L2"), required=True)
    optimize_reflect.add_argument("--outcome", choices=tuple(sorted(optimization.OUTCOMES)), required=True)
    optimize_reflect.add_argument("--usage", default=None, help="usage id or 'latest'; omit when unavailable")
    optimize_reflect.add_argument("--work", default=None)
    optimize_reflect.add_argument("--token-ceiling", type=int, default=None)
    optimize_reflect.add_argument("--subagent-token-ceiling", type=int, default=None)
    optimize_reflect.add_argument("--max-subagents", type=int, default=0)
    optimize_reflect.add_argument("--retrieval", choices=tuple(sorted(optimization.RETRIEVAL_MODES)), default="none")
    optimize_reflect.add_argument("--delegation", choices=tuple(sorted(optimization.DELEGATION_MODES)), default="none")
    optimize_reflect.add_argument("--retries", type=int, default=0)
    optimize_commands.add_parser("proposals", help="list non-applicable evidence-backed evolution proposals")

    host_parser = commands.add_parser("host", help="prepare and complete a host-neutral Agent execution envelope")
    host_commands = host_parser.add_subparsers(dest="host_command", required=True)
    host_commands.add_parser("status", help="show sanitized host completion state")
    host_protocol = host_commands.add_parser("protocol", help="negotiate a compatible Host protocol version")
    host_protocol.add_argument("--version", action="append", default=[], help="host-supported version; repeat as needed")
    host_commands.add_parser("sdk", help="show typed Python Host SDK and bundled JSON Schema metadata")
    host_pending = host_commands.add_parser("pending", help="inspect one sanitized pending HostEnvelope")
    host_pending.add_argument("envelope_id")
    host_abandon = host_commands.add_parser("abandon", help="close one pending or expired HostEnvelope without execution")
    host_abandon.add_argument("envelope_id")
    host_prepare = host_commands.add_parser("prepare", help="build a bounded, fingerprint-bound HostEnvelope")
    host_prepare.add_argument("--intent", choices=tuple(context_policy.INTENT_LEVELS), required=True)
    host_prepare.add_argument("--level", choices=("L0", "L1", "L2"), default=None)
    host_prepare.add_argument("--total-token-ceiling", type=int, default=None)
    host_prepare.add_argument("--subagent-token-ceiling", type=int, default=None)
    host_prepare.add_argument("--max-subagents", type=int, default=0)
    host_prepare.add_argument("--work", default=None)
    host_prepare.add_argument("--delegation-payload", default=None, help="optional strict delegation JSON")
    host_prepare.add_argument("--ttl", type=int, default=3_600, help="HostEnvelope ttl in seconds")
    host_prepare.add_argument("--allow-l2", action="store_true")
    host_complete = host_commands.add_parser("complete", help="record one sanitized HostEnvelope result")
    host_complete.add_argument("--envelope", default=None, help="exact HostEnvelope JSON returned by prepare")
    host_complete.add_argument("--result", default=None, help="strict outcome/count JSON; no transcript or model output")
    host_complete.add_argument(
        "--stdin",
        action="store_true",
        help="recommended: read one strict {envelope,result} JSON object from stdin",
    )

    policy_parser = commands.add_parser("policy", help="stage and verify the local optimization policy overlay")
    policy_commands = policy_parser.add_subparsers(dest="policy_command", required=True)
    policy_commands.add_parser("status", help="show effective/committed policy and ledger integrity")
    policy_stage = policy_commands.add_parser("stage", help="stage one current tighten-only EvolutionProposal")
    policy_stage.add_argument("--proposal", required=True)
    policy_cancel = policy_commands.add_parser("cancel", help="append-only cancellation of one staged proposal")
    policy_cancel.add_argument("--proposal", required=True)
    policy_canary = policy_commands.add_parser("canary", help="start an approved bounded canary for a staged proposal")
    policy_canary.add_argument("--proposal", required=True)
    policy_canary.add_argument("--turns", type=int, default=3)
    policy_canary.add_argument("--ttl", type=int, default=3_600)
    policy_canary.add_argument("--approve", default=None)
    policy_canary.add_argument("--receipt", default=None, help="recover append after an already-recorded exact policy receipt")
    policy_evaluate = policy_commands.add_parser("evaluate", help="evaluate current-head HostEnvelope canary evidence")
    policy_evaluate.add_argument("--proposal", required=True)
    policy_commit = policy_commands.add_parser("commit", help="commit a passed canary with a new exact approval")
    policy_commit.add_argument("--proposal", required=True)
    policy_commit.add_argument("--approve", default=None)
    policy_commit.add_argument("--receipt", default=None)
    policy_revert = policy_commands.add_parser("revert", help="restore the immediate prior committed policy with approval")
    policy_revert.add_argument("--approve", default=None)
    policy_revert.add_argument("--receipt", default=None)
    policy_checkpoint = policy_commands.add_parser("checkpoint", help="export, save, or verify a portable policy head checkpoint")
    checkpoint_commands = policy_checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_commands.add_parser("export", help="emit the current portable checkpoint without writing")
    checkpoint_commands.add_parser("save", help="save the current checkpoint for Git/CI tracking")
    checkpoint_commands.add_parser("status", help="compare the saved checkpoint with the current ledger")
    checkpoint_verify = checkpoint_commands.add_parser("verify", help="verify an external checkpoint JSON")
    checkpoint_input = checkpoint_verify.add_mutually_exclusive_group(required=True)
    checkpoint_input.add_argument("--checkpoint", default=None, help="checkpoint JSON object")
    checkpoint_input.add_argument("--file", default=None, help="UTF-8 checkpoint JSON file")
    checkpoint_verify.add_argument(
        "--require-match",
        action="store_true",
        help="return exit code 2 after emitting the verification when the ledger head differs",
    )

    transaction_parser = commands.add_parser("transaction", help="inspect or recover authorized policy transactions")
    transaction_commands = transaction_parser.add_subparsers(dest="transaction_command", required=True)
    transaction_commands.add_parser("status", help="show pending transaction recovery state")
    transaction_show = transaction_commands.add_parser("show", help="show one transaction")
    transaction_show.add_argument("transaction_id")
    transaction_recover = transaction_commands.add_parser("recover", help="idempotently finish a transaction without reauthorization")
    transaction_recover.add_argument("transaction_id")

    drift_parser = commands.add_parser("drift", help="audit local policy integrity and trust-aware host compliance")
    drift_commands = drift_parser.add_subparsers(dest="drift_command", required=True)
    drift_status = drift_commands.add_parser("status", help="show read-only policy/host drift findings")
    drift_status.add_argument("--expected-head", default=None, help="optional external ledger checkpoint digest")

    profile_parser = commands.add_parser("profile", help="inspect or change the bounded authorization profile")
    profile_commands = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("show", help="show the active project authorization policy")
    profile_set = profile_commands.add_parser("set", help="prepare or apply an exact authorization policy change")
    profile_set.add_argument("name", choices=("strict", "trusted-local", "autopilot-read"))
    profile_set.add_argument("--lease-ttl", type=int, default=300, help="trusted-local lease TTL in seconds")
    profile_set.add_argument("--memory-domain", action="append", default=[], help="autopilot memory domain; repeat as needed")
    profile_set.add_argument("--memory-limit", type=int, default=0, help="autopilot maximum results per search")
    profile_set.add_argument("--expires-at", default=None, help="autopilot expiry as a UTC timestamp")
    profile_set.add_argument("--approve", default=None, help="exact policy approval token; omit to prepare")

    dashboard_parser = commands.add_parser("dashboard", help="manage the standalone read-only Control Center")
    dashboard_commands = dashboard_parser.add_subparsers(dest="dashboard_command", required=True)
    dashboard_start = dashboard_commands.add_parser("start", help="start the loopback Control Center")
    dashboard_start.add_argument("--port", type=int, default=8242)
    dashboard_commands.add_parser("status", help="show Control Center status")
    dashboard_commands.add_parser("stop", help="stop the verified Control Center instance")

    task_parser = commands.add_parser("task", help="manage local Markdown tasks")
    task_commands = task_parser.add_subparsers(dest="task_command", required=True)
    task_create = task_commands.add_parser("create", help="create a task")
    task_create.add_argument("title")
    task_list = task_commands.add_parser("list", help="list tasks")
    task_list.add_argument("--status", choices=("open", "completed", "blocked"))
    task_show = task_commands.add_parser("show", help="show one task")
    task_show.add_argument("task_id")

    work_parser = commands.add_parser("work", help="manage pointer-only F2 WorkItems")
    work_commands = work_parser.add_subparsers(dest="work_command", required=True)
    work_commands.add_parser("current", help="show the current WorkItem pointer")
    work_commands.add_parser("list", help="list WorkItem pointers")
    work_show = work_commands.add_parser("show", help="show one WorkItem pointer")
    work_show.add_argument("work_item_id")
    work_link = work_commands.add_parser("link", help="link a local or native Trellis task without copying its body")
    link_group = work_link.add_mutually_exclusive_group(required=True)
    link_group.add_argument("--local-task", default=None)
    link_group.add_argument("--trellis-task", default=None)
    work_activate = work_commands.add_parser("activate", help="select an existing Trellis task and begin one new lifecycle cycle")
    work_activate.add_argument("--trellis-task", required=True)
    work_select = work_commands.add_parser("select", help="select an existing WorkItem as current")
    work_select.add_argument("work_item_id")
    work_commands.add_parser("clear", help="clear the current WorkItem pointer")
    work_refresh = work_commands.add_parser("refresh", help="refresh a WorkItem phase and source fingerprint")
    work_refresh.add_argument("work_item_id", nargs="?", default=None)

    lesson_parser = commands.add_parser("lesson", help="inspect and review hash-only LessonProposals")
    lesson_commands = lesson_parser.add_subparsers(dest="lesson_command", required=True)
    lesson_list = lesson_commands.add_parser("list", help="list LessonProposals and effective review state")
    lesson_list.add_argument("--review-state", choices=("pending", "verified", "rejected", "expired", "superseded", "persisted"))
    lesson_show = lesson_commands.add_parser("show", help="show one LessonProposal")
    lesson_show.add_argument("proposal_id")
    lesson_review = lesson_commands.add_parser("review", help="apply one deterministic local review decision")
    lesson_review.add_argument("proposal_id")
    lesson_review.add_argument("--decision", required=True, choices=("verify", "reject", "expire", "supersede", "reactivate"))
    lesson_review.add_argument("--receipt", default=None, help="verified Trellis gate/test receipt")
    lesson_review.add_argument("--reason-code", default=None, help="bounded lowercase kebab-case reason")
    lesson_review.add_argument("--replacement", default=None, help="replacement LessonProposal for supersede")

    gate_parser = commands.add_parser("gate", help="project current gate evidence without mutating Trellis")
    gate_commands = gate_parser.add_subparsers(dest="gate_command", required=True)
    gate_commands.add_parser("status", help="show current WorkItem gate alignment")
    gate_reconcile = gate_commands.add_parser("reconcile", help="link a typed receipt to current WorkItem/fingerprint")
    gate_reconcile.add_argument("receipt_id")
    gate_reconcile.add_argument("--work-item", default=None)
    gate_policy = gate_commands.add_parser("policy", help="show or set the local finish policy")
    gate_policy_commands = gate_policy.add_subparsers(dest="gate_policy_command", required=True)
    gate_policy_commands.add_parser("show", help="show finish policy")
    gate_policy_set = gate_policy_commands.add_parser("set", help="set finish policy")
    gate_policy_set.add_argument("value", choices=("suggest", "require-current-gate"))
    gate_policy_set.add_argument("--approve", default=None, help="exact policy approval token; omit to prepare")

    def add_recall_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--query", required=True)
        command.add_argument("--domain", default=None)
        command.add_argument("--limit", type=int, default=None)
        command.add_argument("--namespace-scope", default=None)
        command.add_argument("--also-memory", action="store_true")
        command.add_argument("--approve", default=None)
        command.add_argument("--timeout", type=int, default=30)

    def add_remember_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--lesson", required=True)
        command.add_argument("--scope", choices=("auto", "project", "cross-project"), default="auto")
        command.add_argument("--receipt", default=None)
        command.add_argument("--saga", default=None)
        command.add_argument("--proposal", default=None, help="existing hash-only LessonProposal id")
        command.add_argument("--approve", default=None)
        command.add_argument("--timeout", type=int, default=30)

    recall_parser = commands.add_parser("recall", help="recall local facts before a narrow optional memory search")
    add_recall_options(recall_parser)
    remember_parser = commands.add_parser("remember", help="prepare an evidence-gated project or long-term lesson")
    add_remember_options(remember_parser)

    do_parser = commands.add_parser("do", help="run one deterministic HelloDev intent")
    do_commands = do_parser.add_subparsers(dest="do_intent", required=True)
    for intent in ("plan", "work", "check", "finish"):
        lifecycle_intent = do_commands.add_parser(intent, help=f"run the {intent} lifecycle intent")
        lifecycle_intent.add_argument("--note", default=None)
    do_task = do_commands.add_parser("task", help="route a task operation to Trellis or local tasks")
    do_task.add_argument("operation", choices=("create", "list", "show", "current", "start", "validate"))
    do_task.add_argument("--title", default=None)
    do_task.add_argument("--task", default=None)
    do_task.add_argument("--approve", default=None)
    do_task.add_argument("--timeout", type=int, default=60)
    do_validate = do_commands.add_parser("validate", help="run the native Trellis task validation intent")
    do_validate.add_argument("--task", required=True)
    do_validate.add_argument("--approve", default=None)
    do_validate.add_argument("--timeout", type=int, default=60)
    do_recall = do_commands.add_parser("recall", help="run the local-first recall intent")
    add_recall_options(do_recall)
    do_remember = do_commands.add_parser("remember", help="run the evidence-gated remember intent")
    add_remember_options(do_remember)

    trellis_parser = commands.add_parser("trellis", help="Trellis adapter")
    trellis_commands = trellis_parser.add_subparsers(dest="trellis_command", required=True)
    trellis_commands.add_parser("status", help="detect Trellis metadata and CLI availability")
    trellis_commands.add_parser("intents", help="list HelloDev's validated common Trellis intent mappings")
    trellis_intent = trellis_commands.add_parser("intent", help="prepare or run a validated common Trellis intent")
    trellis_intent.add_argument("name", help="intent name; run 'hellodev trellis intents' to list names")
    trellis_intent.add_argument("--title", default=None, help="task title for task-create")
    trellis_intent.add_argument("--task", default=None, help="native Trellis task directory name for task-start/task-validate")
    trellis_intent.add_argument("--channel", default=None, help="channel name for channel-thread-rename")
    trellis_intent.add_argument("--old-thread", default=None, help="existing thread key for channel-thread-rename")
    trellis_intent.add_argument("--new-thread", default=None, help="replacement thread key for channel-thread-rename")
    trellis_intent.add_argument("--as", dest="agent", default=None, help="required Trellis channel actor for channel-thread-rename")
    trellis_intent.add_argument("--scope", choices=("project", "global"), default="project", help="Trellis channel scope")
    trellis_intent.add_argument("--approve", default=None, help="approval token; omit to prepare")
    trellis_intent.add_argument("--timeout", type=int, default=60, help="timeout in seconds (1-300)")
    trellis_intent.add_argument("--saga", default=None, help="optional Saga id for a Trellis write intent")
    trellis_prepare = trellis_commands.add_parser("prepare", help="prepare a one-time confirmed Trellis command")
    trellis_prepare.add_argument("arguments", nargs=argparse.REMAINDER, help="Trellis arguments, after --")
    trellis_run = trellis_commands.add_parser("run", help="run a prepared Trellis command")
    trellis_run.add_argument("--approve", required=True, help="exact approval token returned by prepare")
    trellis_run.add_argument("--timeout", type=int, default=60, help="timeout in seconds (1-300)")
    trellis_run.add_argument("--saga", default=None, help="optional Saga id for a Trellis write")
    trellis_run.add_argument("arguments", nargs=argparse.REMAINDER, help="Trellis arguments, after --")

    nocturne_parser = commands.add_parser("nocturne", help="Nocturne public MCP adapter")
    nocturne_commands = nocturne_parser.add_subparsers(dest="nocturne_command", required=True)
    nocturne_commands.add_parser("status", help="show Nocturne adapter configuration")
    nocturne_configure = nocturne_commands.add_parser("configure", help="configure a project-local stdio MCP command")
    nocturne_configure.add_argument(
        "--command", dest="nocturne_command_path", required=True, help="absolute path to the Nocturne process executable"
    )
    nocturne_configure.add_argument("--arg", action="append", default=[], help="one process argument; repeat as needed")
    nocturne_configure.add_argument("--cwd", default=None, help="working directory for the Nocturne process")
    nocturne_tools = nocturne_commands.add_parser("tools", help="list public Nocturne MCP tools")
    nocturne_tools.add_argument("--approve", default=None, help="approval token; omit to prepare")
    nocturne_tools.add_argument("--timeout", type=int, default=30, help="timeout in seconds (1-120)")
    nocturne_call = nocturne_commands.add_parser("call", help="call any public Nocturne MCP tool")
    nocturne_call.add_argument("tool", help="public MCP tool name")
    nocturne_call.add_argument("--params", required=True, help="JSON object passed as MCP tool arguments")
    nocturne_call.add_argument("--approve", default=None, help="approval token; omit to prepare")
    nocturne_call.add_argument("--timeout", type=int, default=30, help="timeout in seconds (1-120)")
    nocturne_call.add_argument("--saga", default=None, help="optional Saga id for a Nocturne write")

    receipt_parser = commands.add_parser("receipt", help="inspect privacy-preserving adapter receipts")
    receipt_commands = receipt_parser.add_subparsers(dest="receipt_command", required=True)
    receipt_commands.add_parser("list", help="list execution receipts")
    receipt_show = receipt_commands.add_parser("show", help="show one execution receipt")
    receipt_show.add_argument("receipt_id")

    saga_parser = commands.add_parser("saga", help="coordinate verified Trellis then Nocturne writes")
    saga_commands = saga_parser.add_subparsers(dest="saga_command", required=True)
    saga_create = saga_commands.add_parser("create", help="create a cross-adapter Saga")
    saga_create.add_argument("title")
    saga_status = saga_commands.add_parser("status", help="show Saga state")
    saga_status.add_argument("saga_id")
    saga_attach = saga_commands.add_parser("attach", help="attach a receipt to the current Saga step")
    saga_attach.add_argument("saga_id")
    saga_attach.add_argument("receipt_id")
    saga_verify = saga_commands.add_parser("verify", help="verify the current Saga receipt with evidence")
    saga_verify.add_argument("saga_id")
    saga_verify.add_argument("receipt_id")
    saga_verify.add_argument("--evidence", required=True, help="verification evidence; stored only as a SHA-256 digest")
    saga_next = saga_commands.add_parser("next", help="show the next safe recovery action")
    saga_next.add_argument("saga_id")
    saga_close = saga_commands.add_parser("close", help="close a recoverable or partial Saga")
    saga_close.add_argument("saga_id")
    doctor_parser = commands.add_parser("doctor", help="check project state and adapter boundaries")
    doctor_parser.add_argument("--fix-hints", action="store_true", help="include deterministic recovery commands")
    audit_parser = commands.add_parser("audit", help="export privacy-preserving local audit state")
    audit_commands = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_commands.add_parser("export", help="emit a read-only hash/pointer audit report")
    snapshot_parser = commands.add_parser("snapshot", help="read-only source snapshot verification")
    snapshot_commands = snapshot_parser.add_subparsers(dest="snapshot_command", required=True)
    snapshot_verify = snapshot_commands.add_parser("verify", help="hash a source tree")
    snapshot_verify.add_argument("--path", default=None, help="source tree to hash (default: this package)")
    if not show_all:
        visible = {"open", "next", "do", "status", "resume", "setup", "onboard", "components", "integrate", "doctor"}
        commands._choices_actions[:] = [
            action for action in commands._choices_actions if action.dest in visible
        ]
    return parser


def _status(root: Path) -> dict[str, Any]:
    initialized = project_initialized(root)
    task_count = 0
    config: dict[str, Any] | None = None
    capability_cache: dict[str, Any] | None = None
    lifecycle_state: dict[str, Any] | None = None
    trellis_state: dict[str, Any]
    nocturne_state: dict[str, Any]
    if initialized:
        config = load_config(root)
        task_count = len(list_tasks(root))
        capability_cache = capabilities.status(root)
        lifecycle_state = lifecycle.status(root)
        cached_adapters = capability_cache.get("capabilities") if capability_cache["state"] == "fresh" else None
        trellis_state = cached_adapters["trellis"] if isinstance(cached_adapters, dict) else {"state": "cache-missing-or-stale"}
        nocturne_state = cached_adapters["nocturne"] if isinstance(cached_adapters, dict) else {"state": "cache-missing-or-stale"}
        repository_tool_state = (
            cached_adapters["repositoryTools"]
            if isinstance(cached_adapters, dict) and isinstance(cached_adapters.get("repositoryTools"), dict)
            else {"state": "cache-missing-or-stale", "activeProvider": "native", "suggestedProvider": "native"}
        )
        context_plane_state = context_runtime.status(root)
    else:
        trellis_state = trellis.discover(root)
        nocturne_state = nocturne.status(root)
        repository_tool_state = repository_tools.discover()
        context_plane_state = context_runtime.status(root)
    return {
        "version": __version__,
        "root": str(root),
        "initialized": initialized,
        "project": config,
        "taskCount": task_count,
        "lifecycle": lifecycle_state,
        "capabilities": capability_cache,
        "trellis": trellis_state,
        "nocturne": nocturne_state,
        "repositoryTools": repository_tool_state,
        "contextPlane": context_plane_state,
        "distribution": components.availability(),
    }


def _doctor(root: Path, include_fix_hints: bool = False) -> dict[str, Any]:
    state = _status(root)
    try:
        sdk = host_sdk.sdk_info()
        sdk_check = {"name": "host-sdk", "state": "ok", "detail": sdk["protocol"]["selectedVersion"]}
    except (ProjectError, OSError, json.JSONDecodeError) as error:
        sdk_check = {"name": "host-sdk", "state": "incompatible", "detail": str(error)}
    try:
        transaction_state = transactions.status(root) if state["initialized"] else {"pendingCount": 0}
        transaction_check = {
            "name": "transaction-recovery",
            "state": "action-required" if transaction_state["pendingCount"] else "ok",
            "detail": f"pending={transaction_state['pendingCount']}",
        }
    except ProjectError as error:
        transaction_check = {"name": "transaction-recovery", "state": "invalid", "detail": str(error)}
    trellis_compatible = state["trellis"]["state"] != "unsafe"
    nocturne_compatible = state["nocturne"]["state"] not in {"unsafe", "invalid"}
    distribution_state = state["distribution"]
    repository_tool_state = state["repositoryTools"]
    context_plane_state = state["contextPlane"]
    checks = [
        {"name": "python", "state": "ok", "detail": platform.python_version()},
        {
            "name": "unified-distribution",
            "state": "ok" if distribution_state["state"] == "ready" else distribution_state["state"],
            "detail": distribution_state.get("reason", distribution_state["state"]),
        },
        {
            "name": "project-state",
            "state": "ok" if state["initialized"] else "action-required",
            "detail": "initialized" if state["initialized"] else "run 'hellodev init' to create .hellodev",
        },
        {
            "name": "trellis-adapter",
            "state": state["trellis"]["state"],
            "detail": state["trellis"].get("reason", state["trellis"].get("execution", "unknown")),
        },
        {
            "name": "trellis-compatibility",
            "state": "ok" if trellis_compatible else "incompatible",
            "detail": "bounded intent registry available" if trellis_compatible else "adapter state is incompatible",
        },
        {
            "name": "nocturne-adapter",
            "state": state["nocturne"]["state"],
            "detail": state["nocturne"].get("reason", state["nocturne"].get("execution", "unknown")),
        },
        {
            "name": "nocturne-compatibility",
            "state": "ok" if nocturne_compatible else "incompatible",
            "detail": "public stdio configuration is optional and bounded" if nocturne_compatible else "configured adapter is unsafe or invalid",
        },
        {
            "name": "repository-tool-provider",
            "state": "ok" if repository_tool_state.get("state") == "ready" else "incompatible",
            "detail": (
                f"active={repository_tool_state.get('activeProvider', 'native')}; "
                f"suggested={repository_tool_state.get('suggestedProvider', 'native')}; "
                f"activation={repository_tool_state.get('activationState', 'native-context-plane')}"
            ),
        },
        {
            "name": "context-plane",
            "state": "ok" if context_plane_state.get("state") == "ready" else "incompatible",
            "detail": (
                f"backend={context_plane_state.get('backend', 'native')}; "
                f"lastQuery={'available' if isinstance(context_plane_state.get('lastQuery'), dict) else 'none'}; "
                "rawContentPersisted=false"
            ),
        },
        sdk_check,
        transaction_check,
    ]
    value: dict[str, Any] = {"root": str(root), "checks": checks}
    if include_fix_hints:
        value["fixHints"] = (
            audit.fix_hints(root)
            if state["initialized"]
            else {
                "state": "actionable",
                "commands": [_command_line(root, "open")],
                "executionPerformed": False,
            }
        )
    return value


def _human(value: Any, heading: str = "HelloDev") -> str:
    if isinstance(value, dict):
        lines = [heading]
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{key}: {json.dumps(item, ensure_ascii=False, sort_keys=True)}")
            else:
                lines.append(f"{key}: {item}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value)
    return str(value)


def _emit(value: Any, json_output: bool, heading: str = "HelloDev") -> None:
    value = rewrite_commands(value)
    if json_output:
        # ASCII JSON keeps exact Unicode paths portable across Windows cmd.exe,
        # Windows PowerShell, Cursor, and redirected agent subprocess pipes.
        print(json.dumps(value, ensure_ascii=True, sort_keys=True))
    else:
        print(_human(value, heading))


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProjectError(f"Nocturne --params must be valid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise ProjectError("Nocturne --params must be a JSON object")
    return value


def _json_value(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProjectError(f"{label} must be valid JSON: {error.msg}") from error


def _host_completion_from_stdin() -> tuple[Any, Any]:
    maximum = 512 * 1024
    raw = sys.stdin.read(maximum + 1)
    if len(raw.encode("utf-8")) > maximum:
        raise ProjectError("host complete stdin JSON exceeds 512 KiB")
    value = _json_value(raw, "host complete --stdin")
    if not isinstance(value, dict) or set(value) != {"envelope", "result"}:
        raise ProjectError("host complete --stdin requires exactly {envelope,result}")
    return value["envelope"], value["result"]


def _command_line(root: Path, *arguments: str) -> str:
    return render_command_line(root, *arguments)


def _selected_level(intent: str | None, explicit_level: str | None, legacy_default: str) -> str:
    if intent is None:
        return explicit_level or legacy_default
    return context_policy.select_level(intent, explicit_level)


def _next_context_intent(command: str) -> str:
    if "saga " in command:
        return "saga"
    if "do " in command or command.endswith(" open") or command == "hellodev open":
        return "lifecycle"
    return "status"


def _file_identity(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"state": "absent"}
    selected = Path(path)
    if not selected.is_file() or selected.is_symlink():
        return {"state": "unavailable", "path": str(selected)}
    digest = hashlib.sha256()
    with selected.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return {"state": "present", "path": str(selected.resolve()), "sha256": digest.hexdigest()}


def _trellis_binding(root: Path) -> dict[str, Any]:
    return {
        "capability_fingerprint": capabilities.fingerprint(root),
        "executable_identity": {
            "trellis": trellis.binding_identity(),
            "python": _file_identity(sys.executable),
            "taskScript": _file_identity(root / ".trellis" / "scripts" / "task.py"),
        },
        "intent_registry": trellis.intent_catalog(),
    }


def _nocturne_binding(root: Path) -> dict[str, Any]:
    configuration = nocturne_config(root)
    if configuration is None:
        raise ProjectError("Nocturne is not configured for this project")
    return {
        "capability_fingerprint": capabilities.fingerprint(root),
        "executable_identity": {
            "command": _file_identity(configuration["command"]),
            "mode": configuration["mode"],
            "source": configuration.get("source", "external"),
            "componentFiles": configuration.get("executionIdentity", []),
            "manifestSha256": configuration.get("manifestSha256"),
        },
        "intent_registry": {"search_memory": {"risk": "read", "scope": "narrow"}},
    }


def _authorization_for_explicit_token(root: Path) -> dict[str, Any]:
    return {
        "decision": "token-required",
        "authorizationMode": "token-required",
        "profileUsed": profiles.current_policy(root)["authorizationProfile"],
        "reason": "an exact one-time token was supplied",
    }


def _open(root: Path, verbose: bool) -> dict[str, Any]:
    created: dict[str, Any] | None = None
    if not project_initialized(root):
        created = init_project(root)
    state = lifecycle.status(root)
    if state["phase"] == "new":
        started = _start(root)
        usage_sync = _auto_usage_sync(root)
        result: dict[str, Any] = {"state": "opened", "created": bool(created and created["created"])}
        if verbose:
            result["start"] = started
        else:
            result.update(_compact_status(_status(root)))
        result["next"] = routing.next_decision(root)
        result["resume"] = resume.build(root)
        result["usageSync"] = usage_sync
        return result
    usage_sync = _auto_usage_sync(root)
    decision = routing.next_decision(root)
    return {
        "state": "resumed",
        "created": False,
        **(_status(root) if verbose else _compact_status(_status(root))),
        "next": decision,
        "resume": resume.build(root),
        "usageSync": usage_sync,
    }


def _roots_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        try:
            right.relative_to(left)
            return True
        except ValueError:
            return False


def _auto_usage_sync(root: Path) -> dict[str, Any]:
    if os.environ.get("CODEX_THREAD_ID") is None:
        return {"state": "unavailable", "reasonCode": "codex-thread-id-unavailable", "persistencePerformed": False}
    if not _roots_overlap(root.resolve(), Path.cwd().resolve()):
        return {"state": "skipped", "reasonCode": "selected-root-not-current-cwd", "persistencePerformed": False}
    try:
        value = usage_collector.sync_codex_usage(root)
    except ProjectError:
        return {"state": "unavailable", "reasonCode": "codex-runtime-sync-unavailable", "persistencePerformed": False}
    return {
        "state": value["state"],
        "recordedCount": value["recordedCount"],
        "skippedCount": value["skippedCount"],
        "remainingUnrecordedCount": value["remainingUnrecordedCount"],
        "cycleCount": value["reflectionCycle"]["cycleCount"],
        "pendingReceiptCount": value["reflectionCycle"]["pendingReceiptCount"],
        "persistencePerformed": value["persistencePerformed"],
    }


def _start(root: Path) -> dict[str, Any]:
    if not project_initialized(root):
        return {"state": "uninitialized", "status": _status(root), "action": "run hellodev init first"}
    return {"state": "started", "lifecycle": lifecycle.start(root), "capabilities": capabilities.refresh(root)}


def _blockers_and_next(state: dict[str, Any]) -> tuple[list[str], str]:
    if not state["initialized"]:
        return ["HelloDev is not initialized"], "hellodev init"
    lifecycle_state = state.get("lifecycle") or {}
    phase = lifecycle_state.get("phase", "unknown")
    blockers: list[str] = []
    if phase == "blocked":
        history = lifecycle_state.get("history", [])
        note = history[-1].get("note") if history and isinstance(history[-1], dict) else None
        blockers.append(note or "lifecycle is blocked")
        return blockers, "hellodev lifecycle resume"
    if state.get("capabilities", {}).get("state") != "fresh":
        blockers.append("capability cache is missing or stale")
    if state.get("trellis", {}).get("state") == "unsafe":
        blockers.append("Trellis metadata is unsafe")
    next_commands = {
        "new": "hellodev start",
        "started": "hellodev lifecycle plan",
        "planned": "hellodev lifecycle work",
        "working": "hellodev lifecycle check",
        "checking": "hellodev lifecycle finish",
        "finished": "hellodev status --verbose",
    }
    return blockers, next_commands.get(phase, "hellodev status --verbose")


def _compact_status(state: dict[str, Any]) -> dict[str, Any]:
    blockers, _ = _blockers_and_next(state)
    lifecycle_state = state.get("lifecycle") or {}
    if state["initialized"]:
        next_step = routing.next_decision(Path(state["root"]))
        next_command = next_step["command"]
    else:
        next_command = "hellodev open"
    value = {
        "version": state["version"],
        "root": state["root"],
        "initialized": state["initialized"],
        "phase": lifecycle_state.get("phase"),
        "blockers": blockers,
        "next": next_command,
        "suggestedLevel": next_step.get("suggestedLevel", context_policy.suggested_level(_next_context_intent(next_command)))
        if state["initialized"]
        else "L0",
        "repositoryTools": {
            "state": state["repositoryTools"].get("state", "unknown"),
            "activeProvider": state["repositoryTools"].get("activeProvider", "native"),
            "suggestedProvider": state["repositoryTools"].get("suggestedProvider", "native"),
            "activationState": state["repositoryTools"].get("activationState", "native-context-plane"),
        },
    }
    if state["initialized"]:
        try:
            cycle = efficiency_cycles.status(Path(state["root"]))
        except ProjectError:
            cycle = None
        if cycle is not None:
            value["reflectionCycle"] = {
                "state": cycle["state"],
                "cycleCount": cycle["cycleCount"],
                "pendingReceiptCount": cycle["pendingReceiptCount"],
                "remainingUntilNextCycle": cycle["remainingUntilNextCycle"],
            }
        if "efficiency" in next_step:
            value["efficiency"] = next_step["efficiency"]
    return value


def _start_output(root: Path, verbose: bool) -> dict[str, Any]:
    raw = _start(root)
    if verbose:
        return raw
    state = _status(root)
    return {"state": raw["state"], **_compact_status(state)}


def _record_execution(
    root: Path,
    adapter: str,
    operation: str,
    risk: str,
    request: Any,
    result: dict[str, Any],
    succeeded: bool,
    saga_id: str | None = None,
    receipt_kind: str = "command",
    authorization: dict[str, Any] | None = None,
    evidence_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit_arguments: dict[str, Any] = {}
    if authorization is not None:
        audit_arguments = {
            "profile_used": authorization["profileUsed"],
            "authorization_mode": authorization["authorizationMode"],
            "lease_sha256": authorization.get("leaseSha256"),
        }
    receipt = receipts.record(
        root,
        adapter,
        operation,
        risk,
        request,
        result,
        succeeded,
        kind=receipt_kind,
        evidence_binding=evidence_binding,
        **audit_arguments,
    )
    response: dict[str, Any] = {**result, "receipt": receipt}
    if saga_id is not None:
        response["saga"] = sagas.attach(root, saga_id, receipt["id"])
    return response


def _apply_trellis_continuity(
    root: Path,
    native_intent: str,
    task: str | None,
    execution: dict[str, Any],
) -> dict[str, Any]:
    if execution.get("exitCode") != 0 or not isinstance(task, str):
        return execution
    if native_intent == "task-start":
        execution["workItem"] = contracts.create_work_item(root, "trellis", task)
    elif native_intent == "task-validate":
        current = contracts.current_work_item(root)
        if current is not None and current["backend"] == "trellis" and current["nativeRef"] == task:
            execution["gateReconciliation"] = gates.reconcile(root, execution["receipt"]["id"])
        else:
            execution["gateReconciliation"] = {
                "state": "not-linked",
                "reason": (
                    "Validation succeeded without a matching current Trellis WorkItem, so the receipt is not "
                    "eligible for later gate reconciliation. Select the work item and rerun validation."
                ),
                "next": _command_line(root, "work", "link", "--trellis-task", task),
                "then": _command_line(root, "do", "validate", "--task", task),
            }
    return execution


def _trellis_evidence_binding(
    root: Path,
    native_intent: str,
    task: str | None,
) -> dict[str, Any] | None:
    if native_intent != "task-validate" or not isinstance(task, str):
        return None
    current = contracts.current_work_item(root)
    if current is None or current["backend"] != "trellis" or current["nativeRef"] != task:
        return None
    return contracts.evidence_binding(root, current["id"])


def _gate_policy_payload(root: Path, value: str) -> dict[str, Any]:
    return {
        "operation": "finish-policy.change",
        "currentFinishPolicy": gates.policy_show(root)["finishPolicy"],
        "proposedFinishPolicy": value,
    }


def _set_gate_policy(root: Path, value: str, approve_token: str | None) -> dict[str, Any]:
    payload = _gate_policy_payload(root, value)
    if approve_token is None:
        prepared = approval.prepare(root, payload, "policy")
        return {
            **prepared,
            "finishPolicy": value,
            "resumeCommand": _command_line(
                root, "gate", "policy", "set", value, "--approve", prepared["approval"]
            ),
        }
    current_profile = profiles.current_policy(root)["authorizationProfile"]
    receipts.list_receipts(root)
    approval.consume(root, payload, approve_token, "policy")
    result = gates.policy_set(root, value)
    receipt = receipts.record(
        root,
        "hellodev",
        "finish-policy.change",
        "write",
        payload,
        result,
        True,
        kind="policy",
        profile_used=current_profile,
        authorization_mode="token-required",
    )
    return {
        **result,
        "receipt": receipt,
        "next": _command_line(root, "capabilities", "refresh"),
    }


def _trellis_intent_values(decision: dict[str, Any]) -> dict[str, Any]:
    arguments = decision["arguments"]
    return {
        "title": arguments.get("title"),
        "task": arguments.get("task"),
        "channel": None,
        "old_thread": None,
        "new_thread": None,
        "agent": None,
        "scope": "project",
    }


def _run_unified_trellis(
    root: Path,
    decision: dict[str, Any],
    approve_token: str | None,
    timeout: int,
    resume_arguments: list[str],
) -> dict[str, Any]:
    native_intent = decision["arguments"]["nativeIntent"]
    risk = decision["risk"]
    values = _trellis_intent_values(decision)
    binding = _trellis_binding(root)
    if approve_token is not None:
        authorization = _authorization_for_explicit_token(root)
        token = approve_token
    else:
        authorization = profiles.authorization_decision(
            root,
            adapter="trellis",
            risk=risk,
            read_class="trellis-read" if risk == "read" else "trellis-write",
            **binding,
        )
        prepared = trellis.prepare_intent(root, native_intent, **values)
        if authorization["decision"] == "token-required":
            return {
                **decision,
                **prepared,
                "authorization": authorization,
                "context": context_policy.suggest(decision["contextIntent"]),
                "resumeCommand": _command_line(root, *resume_arguments, "--approve", prepared["approval"]),
            }
        token = prepared["approval"]
    evidence_binding = _trellis_evidence_binding(root, native_intent, values.get("task"))
    result = trellis.run_intent(root, native_intent, token, timeout, **values)
    response = _record_execution(
        root,
        "trellis",
        f"intent/{native_intent}",
        risk,
        {"intent": native_intent, "argv": result["argv"]},
        result,
        result["exitCode"] == 0,
        receipt_kind="gate" if native_intent == "task-validate" else "command",
        authorization=authorization,
        evidence_binding=evidence_binding,
    )
    response = _apply_trellis_continuity(root, native_intent, values.get("task"), response)
    if (
        result["exitCode"] == 0
        and authorization["authorizationMode"] == "token-required"
        and authorization["profileUsed"] == "trusted-local"
        and risk == "read"
    ):
        response["lease"] = profiles.grant_read_lease(root, **binding)
    return {
        **decision,
        "executionPerformed": True,
        "authorization": authorization,
        "context": context_policy.suggest(decision["contextIntent"]),
        "result": response,
    }


def _recall_resume_arguments(prefix: list[str], args: argparse.Namespace) -> list[str]:
    values = [*prefix, "--query", args.query]
    if args.domain is not None:
        values.extend(("--domain", args.domain))
    if args.limit is not None:
        values.extend(("--limit", str(args.limit)))
    if args.namespace_scope is not None:
        values.extend(("--namespace-scope", args.namespace_scope))
    if args.also_memory:
        values.append("--also-memory")
    values.extend(("--timeout", str(args.timeout)))
    return values


def _run_recall(root: Path, args: argparse.Namespace, prefix: list[str]) -> dict[str, Any]:
    route = routing.decide(root, "recall", {"query": args.query})
    plan = knowledge_flows.recall_plan(
        root,
        args.query,
        args.domain,
        args.limit,
        args.namespace_scope,
        also_memory=args.also_memory,
    )
    if plan["state"] != "memory-plan-required":
        return {**route, "context": context_policy.suggest("recall"), **plan}
    parameters = plan["nocturne"]["parameters"]
    binding = _nocturne_binding(root)
    if args.approve is not None:
        authorization = _authorization_for_explicit_token(root)
        token = args.approve
    else:
        authorization = profiles.authorization_decision(
            root,
            adapter="nocturne",
            risk="read",
            read_class="nocturne-search",
            memory_domain=args.domain,
            memory_limit=args.limit,
            **binding,
        )
        prepared = nocturne.prepare_call(root, "search_memory", parameters)
        if authorization["decision"] == "token-required":
            return {
                **route,
                **plan,
                **prepared,
                "state": "awaiting-confirmation",
                "authorization": authorization,
                "context": context_policy.suggest("recall"),
                "resumeCommand": _command_line(
                    root, *_recall_resume_arguments(prefix, args), "--approve", prepared["approval"]
                ),
            }
        token = prepared["approval"]
    result = nocturne.call(root, "search_memory", parameters, token, args.timeout)
    succeeded = nocturne.call_succeeded(result)
    recorded = _record_execution(
        root,
        "nocturne",
        "search_memory",
        "read",
        {"tool": "search_memory", "parameters": parameters, "namespaceScope": plan["nocturne"]["namespaceScope"]},
        result,
        succeeded,
        authorization=authorization,
    )
    memory_projection = knowledge_flows.project_memory_result(result, plan["local"], args.limit)
    return {
        **route,
        "state": "memory-result" if succeeded else "memory-error",
        "executionPerformed": True,
        "local": plan["local"],
        "memory": {**memory_projection, "receipt": recorded["receipt"]},
        "authorization": authorization,
        "context": context_policy.suggest("recall"),
    }


def _remember_resume_arguments(
    prefix: list[str], args: argparse.Namespace, saga_id: str, proposal_id: str | None
) -> list[str]:
    values = [*prefix, "--lesson", args.lesson, "--scope", args.scope]
    if args.receipt is not None:
        values.extend(("--receipt", args.receipt))
    if proposal_id is not None:
        values.extend(("--proposal", proposal_id))
    values.extend(("--saga", saga_id, "--timeout", str(args.timeout)))
    return values


def _run_remember(root: Path, args: argparse.Namespace, prefix: list[str]) -> dict[str, Any]:
    route = routing.decide(root, "remember", {"lesson": args.lesson, "receipt": args.receipt})
    proposal = None
    effective_scope = args.scope
    if args.proposal is not None:
        contracts.validate_lesson_digest(root, args.proposal, args.lesson)
        proposal = contracts.get_lesson_proposal(root, args.proposal)
        if effective_scope != "auto" and effective_scope != proposal["scope"]:
            raise ProjectError("remember scope does not match the LessonProposal")
        effective_scope = proposal["scope"]
    plan = knowledge_flows.remember_plan(root, args.lesson, args.receipt, effective_scope)
    destination = plan.get("destination")
    if proposal is None and destination in {"trellis", "nocturne"}:
        proposal = contracts.create_lesson_proposal(
            root,
            args.lesson,
            "project" if destination == "trellis" else "cross-project",
            destination,
            state=plan["state"],
        )
    if proposal is not None:
        review = contracts.lesson_review_projection(proposal)
        if review["effectiveReviewState"] in {"rejected", "expired", "superseded"}:
            next_command = _command_line(root, "lesson", "show", proposal["id"])
            if review["effectiveReviewState"] in {"rejected", "expired"} and args.receipt is not None:
                next_command = _command_line(
                    root, "lesson", "review", proposal["id"], "--decision", "reactivate", "--receipt", args.receipt
                )
            return {
                **route,
                "state": "lesson-review-required",
                "executionPerformed": False,
                "lessonProposal": review,
                "context": context_policy.suggest("remember"),
                "next": next_command,
            }
    if proposal is not None and proposal["state"] in {"completed", "partial", "verification-required"}:
        next_command = (
            _command_line(root, "saga", "next", proposal["sagaId"])
            if proposal["sagaId"] is not None
            else _command_line(root, "lesson", "show", proposal["id"])
        )
        return {
            **route,
            "state": proposal["state"],
            "executionPerformed": False,
            "lessonProposal": proposal,
            "context": context_policy.suggest("remember"),
            "next": next_command,
        }
    if proposal is not None:
        update_arguments: dict[str, Any] = {}
        if proposal["state"] not in {"saga-active", "verification-required", "completed", "partial"}:
            update_arguments["state"] = plan["state"]
        if args.receipt is not None and plan["state"] in {"saga-plan-ready", "configuration-required"}:
            update_arguments["evidence_receipt_id"] = args.receipt
        if update_arguments:
            proposal = contracts.update_lesson_proposal(root, proposal["id"], **update_arguments)
    if plan["state"] != "saga-plan-ready":
        return {**route, "context": context_policy.suggest("remember"), **plan, "lessonProposal": proposal}
    if args.receipt is None:
        raise ProjectError("remember requires an explicit verified evidence receipt before creating a Saga")
    if proposal is None:
        raise ProjectError("remember continuity requires a LessonProposal")
    selected_saga_id = args.saga or proposal["sagaId"]
    if args.saga is not None and proposal["sagaId"] not in {None, args.saga}:
        raise ProjectError("remember Saga does not match the immutable LessonProposal link")
    if selected_saga_id is None:
        saga = sagas.create(root, "Preserve verified cross-project lesson")
        saga = sagas.attach_verified_evidence(root, saga["id"], args.receipt)
    else:
        saga = sagas.status(root, selected_saga_id)
        evidence = saga.get("trellisEvidence", {})
        if evidence.get("receiptId") != args.receipt:
            raise ProjectError("remember Saga is not ready for this exact verified evidence receipt")
        if saga["phase"] == "nocturne-executed":
            proposal = contracts.update_lesson_proposal(root, proposal["id"], state="verification-required")
            return {
                **route,
                "state": "verification-required",
                "executionPerformed": False,
                "saga": saga,
                "lessonProposal": proposal,
                "context": context_policy.suggest("remember"),
                "next": _command_line(root, "saga", "next", saga["id"]),
            }
        if saga["phase"] == "completed":
            proposal = contracts.update_lesson_proposal(root, proposal["id"], state="completed")
            return {
                **route,
                "state": "completed",
                "executionPerformed": False,
                "saga": saga,
                "lessonProposal": proposal,
                "context": context_policy.suggest("remember"),
            }
        if saga["phase"] in {"partial", "closed"}:
            proposal = contracts.update_lesson_proposal(root, proposal["id"], state="partial")
            return {
                **route,
                "state": "partial",
                "executionPerformed": False,
                "saga": saga,
                "lessonProposal": proposal,
                "context": context_policy.suggest("remember"),
                "next": _command_line(root, "saga", "next", saga["id"]),
            }
        if saga["phase"] != "trellis-verified":
            raise ProjectError("remember Saga is not ready for a Nocturne write")
    saga_id = saga["id"]
    proposal = contracts.update_lesson_proposal(
        root, proposal["id"], evidence_receipt_id=args.receipt, saga_id=saga_id, state="saga-active"
    )
    sagas.require_nocturne_write(root, saga_id)
    write = plan["writeParameters"]
    assert isinstance(write, dict)
    parameters = write["arguments"]
    authorization = profiles.authorization_decision(
        root,
        adapter="nocturne",
        risk="write",
        read_class="nocturne-write",
    )
    if args.approve is None:
        prepared = nocturne.prepare_call(root, write["tool"], parameters)
        return {
            **route,
            **plan,
            **prepared,
            "state": "awaiting-confirmation",
            "saga": saga,
            "lessonProposal": proposal,
            "authorization": authorization,
            "context": context_policy.suggest("remember"),
            "resumeCommand": _command_line(
                root,
                *_remember_resume_arguments(prefix, args, saga_id, proposal["id"]),
                "--approve",
                prepared["approval"],
            ),
        }
    review = contracts.lesson_review_projection(proposal)
    if review["effectiveReviewState"] == "pending":
        proposal = contracts.review_lesson_proposal(
            root, proposal["id"], "verify", evidence_receipt_id=args.receipt, reason_code="confirmed-memory-write"
        )
    elif review["effectiveReviewState"] != "verified":
        raise ProjectError(f"LessonProposal is not eligible for memory write: {review['effectiveReviewState']}")
    authorization = _authorization_for_explicit_token(root)
    result = nocturne.call(root, write["tool"], parameters, args.approve, args.timeout)
    succeeded = nocturne.call_succeeded(result)
    recorded = _record_execution(
        root,
        "nocturne",
        "tools/call",
        "write",
        {"tool": write["tool"], "parameters": parameters},
        result,
        succeeded,
        saga_id,
        authorization=authorization,
    )
    receipt_id = recorded["receipt"]["id"]
    if not succeeded:
        proposal = contracts.update_lesson_proposal(root, proposal["id"], state="partial")
        return {
            **route,
            "state": "partial",
            "executionPerformed": True,
            "result": recorded,
            "lessonProposal": proposal,
            "authorization": authorization,
            "context": context_policy.suggest("remember"),
            "next": _command_line(root, "saga", "next", saga_id),
        }
    proposal = contracts.update_lesson_proposal(root, proposal["id"], state="verification-required")
    return {
        **route,
        "state": "verification-required",
        "executionPerformed": True,
        "result": recorded,
        "lessonProposal": proposal,
        "authorization": authorization,
        "context": context_policy.suggest("remember"),
        "next": _command_line(root, "saga", "verify", saga_id, receipt_id, "--evidence", "<verification-evidence>"),
    }


def _run_do(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    intent = args.do_intent
    if intent in {"plan", "work", "check", "finish"}:
        decision = routing.decide(root, intent, {"note": args.note})
        gate_decision = gates.finish_decision(root) if intent == "finish" else None
        if gate_decision is not None and not gate_decision["allowed"]:
            raise ProjectError(f"finish blocked: {gate_decision['reason']} Next: {gate_decision['nextCommand']}")
        state = lifecycle.transition(root, decision["arguments"]["target"], decision["arguments"]["note"])
        current_work = contracts.current_work_item(root)
        if current_work is not None:
            current_work = contracts.refresh_work_item(root, current_work["id"])
        value: dict[str, Any] = {
            **decision,
            "executionPerformed": True,
            "lifecycle": state,
            "context": context_policy.suggest(decision["contextIntent"]),
            "next": routing.next_decision(root),
            "workItem": current_work,
        }
        if intent in {"check", "finish"}:
            value["gate"] = gates.status(root)
        if gate_decision is not None:
            value["finishDecision"] = gate_decision
        if intent == "finish":
            value["rememberSuggestion"] = {
                "state": "suggested-only",
                "command": _command_line(
                    root,
                    "do",
                    "remember",
                    "--lesson",
                    "<verified reusable lesson>",
                    "--receipt",
                    "<verified gate-or-test receipt>",
                ),
                "writePerformed": False,
            }
        return value
    if intent in {"recall", "remember"}:
        return _run_recall(root, args, ["do", "recall"]) if intent == "recall" else _run_remember(
            root, args, ["do", "remember"]
        )
    if intent == "validate":
        decision = routing.decide(root, "validate", {"task": args.task})
        return _run_unified_trellis(
            root,
            decision,
            args.approve,
            args.timeout,
            ["do", "validate", "--task", args.task, "--timeout", str(args.timeout)],
        )
    decision = routing.decide(
        root,
        "task",
        {"operation": args.operation, "title": args.title, "task": args.task},
    )
    if decision["backend"] == "trellis":
        resume = ["do", "task", args.operation]
        if args.title is not None:
            resume.extend(("--title", args.title))
        if args.task is not None:
            resume.extend(("--task", args.task))
        resume.extend(("--timeout", str(args.timeout)))
        return _run_unified_trellis(root, decision, args.approve, args.timeout, resume)
    operation = args.operation
    if operation == "create":
        result = create_task(root, decision["arguments"]["title"])
        work_item = contracts.create_work_item(root, "local", result["id"])
    elif operation == "list":
        result = {"tasks": list_tasks(root)}
    else:
        result = show_task(root, decision["arguments"]["task"])
    return {
        **decision,
        "executionPerformed": True,
        "context": context_policy.suggest(decision["contextIntent"]),
        "result": result,
        **({"workItem": work_item} if operation == "create" else {}),
    }


def _profile_policy(args: argparse.Namespace) -> dict[str, Any]:
    return profiles.build_policy(
        args.name,
        lease_ttl_seconds=args.lease_ttl,
        memory_domains=args.memory_domain,
        memory_limit_ceiling=args.memory_limit,
        expires_at=args.expires_at,
    )


def _profile_resume_arguments(args: argparse.Namespace) -> list[str]:
    values = ["profile", "set", args.name, "--lease-ttl", str(args.lease_ttl)]
    for domain in args.memory_domain:
        values.extend(("--memory-domain", domain))
    if args.memory_limit:
        values.extend(("--memory-limit", str(args.memory_limit)))
    if args.expires_at is not None:
        values.extend(("--expires-at", args.expires_at))
    return values


def _project_client_do_arguments(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, tuple[str, ...]] = {
        "plan": ("note",),
        "work": ("note",),
        "check": ("note",),
        "finish": ("note",),
        "task": ("operation", "title", "task", "approve", "timeout"),
        "validate": ("task", "approve", "timeout"),
        "recall": ("query", "domain", "limit", "namespace_scope", "also_memory", "approve", "timeout"),
        "remember": ("lesson", "scope", "receipt", "saga", "proposal", "approve", "timeout"),
    }
    return {name: getattr(args, name) for name in fields[args.do_intent]}


def _main(argv: list[str] | None = None) -> int:
    selected_argv = list(sys.argv[1:] if argv is None else argv)
    if "--help-all" in selected_argv:
        print(_parser(show_all=True).format_help())
        return 0
    args = _parser().parse_args(selected_argv)
    exit_code = 0
    try:
        root = resolve_root(args.mcp_root or args.root) if args.command == "mcp" else resolve_root(args.root)
        project_client = ProjectClient(root)
        handlers: dict[str, Callable[[], tuple[Any, str]]] = {
            "init": lambda: (init_project(root), "HelloDev initialized"),
            "open": lambda: (project_client.open(verbose=args.verbose), "HelloDev opened"),
            "next": lambda: (project_client.next(), "HelloDev next"),
            "start": lambda: (_start_output(root, args.verbose), "HelloDev started"),
            "status": lambda: (project_client.status(verbose=args.verbose), "HelloDev status"),
            "doctor": lambda: (_doctor(root, args.fix_hints), "HelloDev doctor"),
        }
        if args.command == "mcp":
            mcp_gateway.serve(root)
            return 0
        if args.command == "setup":
            value, heading = components.setup(args.home), "HelloDev unified distribution configured"
        elif args.command == "onboard":
            value, heading = onboarding.onboard(
                root,
                host=args.host,
                enable_memory=not args.without_memory,
                prepare_trellis=args.with_trellis,
            ), "HelloDev project onboarded"
        elif args.command == "components":
            if args.component_command == "status":
                value, heading = components.availability(), "HelloDev components"
            elif args.component is None:
                value, heading = components.verify_all(), "HelloDev components verified"
            else:
                value, heading = components.verify_component(args.component), "HelloDev component verified"
        elif args.command == "integrate":
            operation = integrations.show if args.integrate_command == "show" else integrations.check
            value, heading = operation(root, args.host), "HelloDev integration"
        elif args.command == "resume":
            projection = project_client.resume(include_context=args.context, token_budget=args.token_budget)
            value, heading = projection, "HelloDev resume"
        elif args.command == "do":
            value, heading = project_client.do(args.do_intent, _project_client_do_arguments(args)), "HelloDev intent"
        elif args.command == "recall":
            value, heading = _run_recall(root, args, ["recall"]), "HelloDev recall"
        elif args.command == "remember":
            value, heading = _run_remember(root, args, ["remember"]), "HelloDev remember"
        elif args.command == "profile":
            if args.profile_command == "show":
                value, heading = profiles.current_policy(root), "HelloDev authorization profile"
            else:
                policy = _profile_policy(args)
                if args.approve is None:
                    prepared = approval.prepare_policy_change(root, policy)
                    value, heading = {
                        **prepared,
                        "policy": policy,
                        "resumeCommand": _command_line(
                            root, *_profile_resume_arguments(args), "--approve", prepared["approval"]
                        ),
                    }, "HelloDev profile change prepared"
                else:
                    value, heading = approval.consume_policy_change(root, policy, args.approve), "HelloDev profile changed"
        elif args.command == "task":
            if args.task_command == "create":
                task = create_task(root, args.title)
                value, heading = {
                    **task,
                    "workItem": contracts.create_work_item(root, "local", task["id"]),
                }, "HelloDev task created"
            elif args.task_command == "list":
                value, heading = {"tasks": list_tasks(root, args.status)}, "HelloDev tasks"
            else:
                value, heading = show_task(root, args.task_id), "HelloDev task"
        elif args.command == "lifecycle":
            if args.lifecycle_command == "status":
                value, heading = lifecycle.status(root), "HelloDev lifecycle"
            elif args.lifecycle_command == "resume":
                state = lifecycle.resume(root, args.note)
                current_work = contracts.current_work_item(root)
                value, heading = {
                    **state,
                    "workItem": contracts.refresh_work_item(root, current_work["id"])
                    if current_work is not None
                    else None,
                }, "HelloDev lifecycle resumed"
            else:
                targets = {"plan": "planned", "work": "working", "check": "checking", "finish": "finished", "block": "blocked"}
                finish = gates.finish_decision(root) if args.lifecycle_command == "finish" else None
                if finish is not None and not finish["allowed"]:
                    raise ProjectError(f"finish blocked: {finish['reason']} Next: {finish['nextCommand']}")
                state = lifecycle.transition(root, targets[args.lifecycle_command], args.note)
                current_work = contracts.current_work_item(root)
                value = {
                    **state,
                    "workItem": contracts.refresh_work_item(root, current_work["id"])
                    if current_work is not None
                    else None,
                }
                if args.lifecycle_command in {"check", "finish"}:
                    value["gate"] = gates.status(root)
                if finish is not None:
                    value["finishDecision"] = finish
                heading = "HelloDev lifecycle updated"
        elif args.command == "capabilities":
            if args.capability_command == "status":
                value, heading = capabilities.status(root), "HelloDev capabilities"
            else:
                value, heading = capabilities.refresh(root), "HelloDev capabilities refreshed"
        elif args.command == "brief":
            if args.brief_command == "build":
                selected_level = _selected_level(args.intent, args.level, "L0")
                value, heading = {
                    **briefs.build(root, selected_level, args.task, args.allow_l2),
                    "selection": context_policy.suggest(args.intent, args.level) if args.intent else {
                        "level": selected_level,
                        "selectionSource": "legacy-default" if args.level is None else "explicit",
                    },
                }, "HelloDev brief"
            else:
                value, heading = briefs.show(root, args.level, args.task), "HelloDev brief"
        elif args.command == "context":
            if args.context_command == "suggest":
                value, heading = context_policy.suggest(args.intent, args.level), "HelloDev context suggestion"
            else:
                value = project_client.context(
                    intent=args.intent,
                    level=args.level,
                    task=args.task,
                    allow_l2=args.allow_l2,
                    token_budget=args.token_budget,
                    resume_context=args.resume,
                    query=args.query,
                    scope=args.scope,
                    cursor=args.cursor,
                )
                heading = "HelloDev resume context pack" if args.resume else "HelloDev context pack"
        elif args.command == "smart":
            if args.smart_command == "classify":
                value, heading = intelligence.classify(args.lesson, args.scope), "HelloDev smart routing"
            elif args.smart_command == "retrieve":
                plan = intelligence.retrieval_plan(
                    root,
                    args.scope,
                    args.query,
                    args.level,
                    args.domain,
                    args.limit,
                    args.namespace_scope,
                )
                if args.scope == "project":
                    value, heading = plan, "HelloDev smart retrieval"
                elif args.approve is None:
                    if nocturne.status(root)["state"] != "configured":
                        value, heading = {
                            **plan,
                            "state": "configuration-required",
                            "next": "Configure the independent Nocturne stdio adapter before preparing this narrow search.",
                        }, "HelloDev smart retrieval"
                    else:
                        prepared = nocturne.prepare_call(root, "search_memory", plan["nocturne"]["parameters"])
                        value, heading = {**plan, "state": "awaiting-confirmation", "approval": prepared["approval"]}, "HelloDev smart retrieval"
                else:
                    parameters = plan["nocturne"]["parameters"]
                    result = nocturne.call(root, "search_memory", parameters, args.approve, args.timeout)
                    succeeded = nocturne.call_succeeded(result)
                    value, heading = _record_execution(
                        root,
                        "nocturne",
                        "search_memory",
                        "read",
                        {"tool": "search_memory", "parameters": parameters, "namespaceScope": plan["nocturne"]["namespaceScope"]},
                        result,
                        succeeded,
                    ), "HelloDev smart retrieval result"
            else:
                value, heading = intelligence.persistence_plan(root, args.destination, args.receipt), "HelloDev smart persistence"
        elif args.command == "delegate":
            payload = _json_value(args.payload, "delegate --payload")
            if args.delegate_command == "audit":
                value, heading = governance.audit_delegation(payload), "HelloDev delegation audit"
            elif args.delegate_command == "plan":
                value, heading = delegation.plan(payload), "HelloDev delegation plan"
            else:
                value, heading = delegation.pack(payload, args.role, args.token_budget), "HelloDev delegation context"
        elif args.command == "usage":
            if args.usage_command == "status":
                value, heading = {
                    **governance.usage_status(root),
                    "reflectionCycle": efficiency_cycles.status(root),
                }, "HelloDev usage"
            elif args.usage_command == "record":
                value, heading = governance.record_usage(root, args.total, args.subagent, args.subagents, args.source, args.scope), "HelloDev usage recorded"
            elif args.usage_command == "collect":
                value, heading = usage_collector.collect_previous_codex_turn(
                    root,
                    session_file=args.session,
                    thread_id=args.thread_id,
                    codex_home=args.codex_home,
                ), "HelloDev Codex usage collected"
            else:
                value, heading = usage_collector.sync_codex_usage(
                    root,
                    session_file=args.session,
                    thread_id=args.thread_id,
                    codex_home=args.codex_home,
                    limit=args.limit,
                ), "HelloDev Codex usage synchronized"
        elif args.command == "optimize":
            if args.optimize_command == "status":
                value, heading = optimization.status(root), "HelloDev optimization"
            elif args.optimize_command == "plan":
                value, heading = optimization.plan(
                    root,
                    args.intent,
                    args.level,
                    args.token_ceiling,
                    args.subagent_token_ceiling,
                    args.max_subagents,
                    args.work,
                ), "HelloDev optimization plan"
            elif args.optimize_command == "reflect":
                value, heading = optimization.reflect(
                    root,
                    args.intent,
                    args.context_level,
                    args.outcome,
                    args.usage,
                    args.work,
                    args.token_ceiling,
                    args.subagent_token_ceiling,
                    args.max_subagents,
                    args.retrieval,
                    args.delegation,
                    args.retries,
                ), "HelloDev optimization reflection"
            else:
                value, heading = optimization.list_proposals(root), "HelloDev evolution proposals"
        elif args.command == "host":
            if args.host_command == "status":
                value, heading = {
                    **host_bridge.status(root),
                    "protocol": host_bridge.protocol_info(),
                }, "HelloDev host bridge"
            elif args.host_command == "protocol":
                versions = args.version or list(host_bridge.SUPPORTED_PROTOCOL_VERSIONS)
                value, heading = host_bridge.protocol_info(versions), "HelloDev Host protocol"
            elif args.host_command == "sdk":
                value, heading = host_sdk.sdk_info(), "HelloDev Host SDK"
            elif args.host_command == "pending":
                value, heading = host_bridge.envelope_status(root, args.envelope_id), "HelloDev pending HostEnvelope"
            elif args.host_command == "abandon":
                value, heading = host_bridge.abandon(root, args.envelope_id), "HelloDev HostEnvelope abandoned"
            elif args.host_command == "prepare":
                delegation_payload = (
                    None
                    if args.delegation_payload is None
                    else _json_value(args.delegation_payload, "host prepare --delegation-payload")
                )
                value, heading = host_bridge.prepare(
                    root,
                    args.intent,
                    args.level,
                    args.total_token_ceiling,
                    args.subagent_token_ceiling,
                    args.max_subagents,
                    args.work,
                    delegation_payload,
                    args.ttl,
                    args.allow_l2,
                ), "HelloDev HostEnvelope"
            else:
                if args.stdin:
                    if args.envelope is not None or args.result is not None:
                        raise ProjectError("host complete --stdin cannot be combined with --envelope or --result")
                    envelope_value, result_value = _host_completion_from_stdin()
                else:
                    if args.envelope is None or args.result is None:
                        raise ProjectError("host complete requires --stdin or both --envelope and --result")
                    envelope_value = _json_value(args.envelope, "host complete --envelope")
                    result_value = _json_value(args.result, "host complete --result")
                value, heading = host_bridge.complete(
                    root,
                    envelope_value,
                    result_value,
                ), "HelloDev host completion"
        elif args.command == "policy":
            if args.policy_command == "status":
                value, heading = policy_evolution.status(root), "HelloDev evolution policy"
            elif args.policy_command == "stage":
                value, heading = policy_evolution.stage(root, args.proposal), "HelloDev evolution policy staged"
            elif args.policy_command == "cancel":
                value, heading = policy_evolution.cancel_stage(root, args.proposal), "HelloDev evolution policy stage cancelled"
            elif args.policy_command == "evaluate":
                value, heading = policy_evolution.evaluate(root, args.proposal), "HelloDev evolution canary evaluation"
            elif args.policy_command == "checkpoint":
                if args.checkpoint_command == "export":
                    value, heading = checkpoints.export(root), "HelloDev policy checkpoint"
                elif args.checkpoint_command == "save":
                    value, heading = checkpoints.save(root), "HelloDev policy checkpoint saved"
                elif args.checkpoint_command == "status":
                    value, heading = checkpoints.status(root), "HelloDev policy checkpoint status"
                else:
                    if args.file is not None:
                        checkpoint_value = checkpoints.load_file(args.file)
                    else:
                        checkpoint_value = _json_value(args.checkpoint, "policy checkpoint verify --checkpoint")
                    value, heading = checkpoints.verify(root, checkpoint_value), "HelloDev policy checkpoint verification"
                    if args.require_match and not value["matched"]:
                        exit_code = 2
            else:
                if args.approve is not None and args.receipt is not None:
                    raise ProjectError("provide either --approve or --receipt, not both")
                if args.policy_command == "canary":
                    resume_arguments = ("policy", "canary", "--proposal", args.proposal, "--turns", str(args.turns), "--ttl", str(args.ttl))
                    build_action = lambda: policy_evolution.canary_action(root, args.proposal, args.turns, args.ttl)
                    apply_action = lambda receipt_id: policy_evolution.start_canary(root, args.proposal, args.turns, args.ttl, receipt_id)
                    heading = "HelloDev evolution canary"
                elif args.policy_command == "commit":
                    resume_arguments = ("policy", "commit", "--proposal", args.proposal)
                    build_action = lambda: policy_evolution.commit_action(root, args.proposal)
                    apply_action = lambda receipt_id: policy_evolution.commit(root, args.proposal, receipt_id)
                    heading = "HelloDev evolution policy committed"
                else:
                    resume_arguments = ("policy", "revert")
                    build_action = lambda: policy_evolution.revert_action(root)
                    apply_action = lambda receipt_id: policy_evolution.revert(root, receipt_id)
                    heading = "HelloDev evolution policy reverted"
                if args.receipt is not None:
                    value = apply_action(args.receipt)
                else:
                    action = build_action()
                if args.approve is None and args.receipt is None:
                    prepared = policy_evolution.prepare_authorization(root, action)
                    value = {
                        **prepared,
                        "action": action,
                        "resumeCommand": _command_line(root, *resume_arguments, "--approve", prepared["approval"]),
                    }
                elif args.approve is not None:
                    receipt_id = policy_evolution.authorize(root, action, args.approve)["id"]
                    value = apply_action(receipt_id)
        elif args.command == "transaction":
            if args.transaction_command == "status":
                value, heading = transactions.status(root), "HelloDev policy transactions"
            elif args.transaction_command == "show":
                value, heading = transactions.get(root, args.transaction_id), "HelloDev policy transaction"
            else:
                value, heading = policy_evolution.recover_transaction(root, args.transaction_id), "HelloDev policy transaction recovered"
        elif args.command == "drift":
            value, heading = drift.status(root, args.expected_head), "HelloDev drift audit"
        elif args.command == "dashboard":
            if args.dashboard_command == "start":
                value, heading = dashboard.start_dashboard(root, args.port), "HelloDev Control Center"
            elif args.dashboard_command == "status":
                value, heading = dashboard.dashboard_status(root), "HelloDev Control Center"
            else:
                value, heading = dashboard.stop_dashboard(root), "HelloDev Control Center"
        elif args.command == "receipt":
            if args.receipt_command == "list":
                value, heading = {"receipts": receipts.list_receipts(root)}, "HelloDev receipts"
            else:
                value, heading = receipts.get(root, args.receipt_id), "HelloDev receipt"
        elif args.command == "work":
            if args.work_command == "current":
                value, heading = {"workItem": contracts.current_work_item(root)}, "HelloDev current work"
            elif args.work_command == "list":
                value, heading = {"workItems": contracts.list_work_items(root)}, "HelloDev work items"
            elif args.work_command == "show":
                value, heading = contracts.get_work_item(root, args.work_item_id), "HelloDev work item"
            elif args.work_command == "link":
                backend = "local" if args.local_task is not None else "trellis"
                native_ref = args.local_task if args.local_task is not None else args.trellis_task
                value, heading = contracts.create_work_item(root, backend, native_ref), "HelloDev work linked"
            elif args.work_command == "activate":
                value, heading = contracts.activate_trellis_task(root, args.trellis_task), "HelloDev Trellis work activated"
            elif args.work_command == "select":
                value, heading = contracts.set_current_work_item(root, args.work_item_id), "HelloDev work selected"
            elif args.work_command == "clear":
                contracts.set_current_work_item(root, None)
                value, heading = {"currentWorkItem": None, "cleared": True}, "HelloDev work cleared"
            else:
                value, heading = contracts.refresh_work_item(root, args.work_item_id), "HelloDev work refreshed"
        elif args.command == "lesson":
            if args.lesson_command == "list":
                proposals = contracts.list_lesson_review_projections(root)
                if args.review_state is not None:
                    proposals = [item for item in proposals if item["effectiveReviewState"] == args.review_state]
                value, heading = {"lessonProposals": proposals}, "HelloDev lesson proposals"
            elif args.lesson_command == "show":
                value = contracts.lesson_review_projection(contracts.get_lesson_proposal(root, args.proposal_id))
                heading = "HelloDev lesson proposal"
            else:
                value = contracts.review_lesson_proposal(
                    root,
                    args.proposal_id,
                    args.decision,
                    evidence_receipt_id=args.receipt,
                    reason_code=args.reason_code,
                    replacement_id=args.replacement,
                )
                heading = "HelloDev lesson proposal reviewed"
        elif args.command == "gate":
            if args.gate_command == "status":
                value, heading = gates.status(root), "HelloDev gate projection"
            elif args.gate_command == "reconcile":
                value, heading = gates.reconcile(root, args.receipt_id, args.work_item), "HelloDev gate reconciled"
            elif args.gate_policy_command == "show":
                value, heading = gates.policy_show(root), "HelloDev finish policy"
            else:
                value, heading = _set_gate_policy(root, args.value, args.approve), "HelloDev finish policy"
        elif args.command == "audit":
            value, heading = audit.export(root), "HelloDev audit export"
        elif args.command == "saga":
            if args.saga_command == "create":
                value, heading = sagas.create(root, args.title), "HelloDev Saga created"
            elif args.saga_command == "status":
                value, heading = sagas.status(root, args.saga_id), "HelloDev Saga"
            elif args.saga_command == "attach":
                value, heading = sagas.attach(root, args.saga_id, args.receipt_id), "HelloDev Saga updated"
            elif args.saga_command == "next":
                value, heading = sagas.next_step(root, args.saga_id), "HelloDev Saga next"
            elif args.saga_command == "close":
                state = sagas.close(root, args.saga_id)
                proposal = contracts.proposal_for_saga(root, args.saga_id)
                if proposal is not None and proposal["state"] not in {"completed", "partial"}:
                    proposal = contracts.update_lesson_proposal(root, proposal["id"], state="partial")
                value, heading = {**state, "lessonProposal": proposal}, "HelloDev Saga closed"
            else:
                state = sagas.verify(root, args.saga_id, args.receipt_id, args.evidence)
                proposal = contracts.proposal_for_saga(root, args.saga_id)
                if state["phase"] == "completed" and proposal is not None:
                    proposal = contracts.update_lesson_proposal(root, proposal["id"], state="completed")
                value, heading = {
                    **state,
                    "lessonProposal": proposal,
                }, "HelloDev Saga verified"
        elif args.command == "trellis":
            if args.trellis_command == "status":
                value, heading = trellis.discover(root), "HelloDev Trellis adapter"
            elif args.trellis_command == "intents":
                value, heading = trellis.intent_catalog(), "HelloDev Trellis intents"
            elif args.trellis_command == "intent":
                intent_values = {
                    "title": args.title,
                    "task": args.task,
                    "channel": args.channel,
                    "old_thread": args.old_thread,
                    "new_thread": args.new_thread,
                    "agent": args.agent,
                    "scope": args.scope,
                }
                if args.approve is None:
                    value, heading = trellis.prepare_intent(root, args.name, **intent_values), "HelloDev Trellis intent prepared"
                else:
                    planned_risk = trellis.intent_catalog()["intents"]
                    intent_risk = next((item["risk"] for item in planned_risk if item["name"] == args.name), None)
                    if args.saga is not None:
                        if intent_risk != "write":
                            raise ProjectError("only a Trellis write intent can be attached to a Saga")
                        sagas.require_trellis_write(root, args.saga)
                    evidence_binding = _trellis_evidence_binding(root, args.name, args.task)
                    result = trellis.run_intent(root, args.name, args.approve, args.timeout, **intent_values)
                    value = _record_execution(
                        root,
                        "trellis",
                        f"intent/{args.name}",
                        intent_risk or "write",
                        {"intent": args.name, "argv": result["argv"]},
                        result,
                        result["exitCode"] == 0,
                        args.saga,
                        "gate" if args.name == "task-validate" else "command",
                        evidence_binding=evidence_binding,
                    )
                    value = _apply_trellis_continuity(root, args.name, args.task, value)
                    heading = "HelloDev Trellis intent result"
            elif args.trellis_command == "prepare":
                value, heading = trellis.prepare_run(root, args.arguments), "HelloDev Trellis prepared"
            else:
                risk = trellis.risk_for(args.arguments)
                if args.saga is not None:
                    if risk != "write":
                        raise ProjectError("only a Trellis write can be attached to a Saga")
                    sagas.require_trellis_write(root, args.saga)
                result = trellis.run(root, args.arguments, args.approve, args.timeout)
                value, heading = _record_execution(
                    root, "trellis", "command", risk, {"argv": result["argv"]}, result, result["exitCode"] == 0, args.saga
                ), "HelloDev Trellis result"
        elif args.command == "nocturne":
            if args.nocturne_command == "status":
                value, heading = nocturne.status(root), "HelloDev Nocturne adapter"
            elif args.nocturne_command == "configure":
                value, heading = (
                    configure_nocturne(root, args.nocturne_command_path, args.arg, args.cwd),
                    "HelloDev Nocturne configured",
                )
            elif args.nocturne_command == "tools":
                if args.approve is None:
                    value, heading = nocturne.prepare_tools(root), "HelloDev Nocturne prepared"
                else:
                    result = nocturne.list_tools(root, args.approve, args.timeout)
                    value, heading = _record_execution(root, "nocturne", "tools/list", "read", {}, result, True), "HelloDev Nocturne tools"
            else:
                parameters = _json_object(args.params)
                if args.approve is None:
                    value, heading = nocturne.prepare_call(root, args.tool, parameters), "HelloDev Nocturne prepared"
                else:
                    risk = nocturne.risk_for_tool(args.tool)
                    if args.saga is not None:
                        if risk != "write":
                            raise ProjectError("only a Nocturne write can be attached to a Saga")
                        sagas.require_nocturne_write(root, args.saga)
                    result = nocturne.call(root, args.tool, parameters, args.approve, args.timeout)
                    succeeded = nocturne.call_succeeded(result)
                    value, heading = _record_execution(
                        root,
                        "nocturne",
                        "tools/call",
                        risk,
                        {"tool": args.tool, "parameters": parameters},
                        result,
                        succeeded,
                        args.saga,
                    ), "HelloDev Nocturne result"
        elif args.command == "snapshot":
            value, heading = verify_snapshot(Path(args.path) if args.path else default_snapshot_path()), "HelloDev snapshot verification"
        else:
            value, heading = handlers[args.command]()
        _emit(value, args.json, heading)
        return exit_code
    except (ProjectError, ValueError) as error:
        print(f"hellodev: {error}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    with components.verification_session():
        return _main(argv)
