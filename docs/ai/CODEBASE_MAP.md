# HelloDev Core codebase map

Last refreshed: 2026-08-04
Scope: HelloDev 0.21.3 project-discoverable Agent Skill

## 0.21.3 implementation map

- `skill_bundle/hellodev/SKILL.md` teaches the short governed path; `references/recovery.md` is loaded only after repeated identical failure; `agents/openai.yaml` supplies UI metadata.
- `agent_skill.py` owns bundled-resource validation, host-specific project destinations, conflict/reparse preflight, atomic writes and hash-based managed upgrades.
- `onboarding.py` preflights the Skill before any project mutation and installs it after the existing host plan. Its result exposes bounded Skill state without performing a global install.
- `pyproject.toml` includes Skill markdown/YAML as wheel package data. `test_v213_project_skill.py` covers content, Cursor/Codex/Antigravity destinations, idempotence, managed upgrade, conflict refusal and `host=none`.

## 0.21.2 implementation map

- `closure_transactions.py`: bounded closure journal, native-completion recovery and unambiguous legacy adoption.
- `application.py`: checking-before-mutation finish precondition, transaction state advancement and bare-verify validation.
- `changesets.py`, `acceptance.py`: code-verification identity excludes mutable Trellis task/gate state; context evidence follows a verified completion digest transition.
- `resume.py`, `response_chain.py`: closure recovery takes routing priority and confirmation/repair/diagnostic guidance is disclosed only when needed.
- `onboarding.py`, `mcp_gateway.py`: project and MCP instructions forbid command guessing, token reuse, state editing and native bypass; repeated reason codes escalate to the user.

## 0.21.1 implementation map

- `acceptance_planning.py` projects an integrity-checked exact requirements source into bounded criterion summaries and the existing manifest-first verification plan. It is read-only and creates no evidence.
- `trellis_preflight.py` inspects safe local planning artifacts and context manifests for the bound Trellis task. It rejects links, traversal and malformed entries and never satisfies native or quality gates.
- `response_chain.py` attaches one normalized non-executing `nextAction`, preferring an exact approval resume command over generic routing.
- `capabilities.py` stores schema-v2 fingerprint material and permits auto-refresh only for isolated project-context drift; all authority/runtime/config drift remains explicit.
- `application.py` adds gate/preflight projections, constrained refresh and non-persistent monotonic operation timing to successful `do` responses. `cli.py` chains executable-acceptance responses without adding an MCP tool.
- `acceptance.py` exposes integrity-revalidated exact requirements text. `trellis_execution.py` retains package-script order across test, integration, typecheck, build and e2e gates.

## 0.21.0 implementation map

- `executable_acceptance.py` owns bounded proposal/review state. Proposals bind cycle, WorkItem, requirements digest, target baseline, canonical command digest and repository snapshot; review never writes tests or creates verification evidence.
- `dynamic_escalation.py` owns hash-only diagnostic escalation state derived from current WorkItem, canonical command digest, repository snapshot, verification failures/retries and invalid finish attempts.
- `resume.py` exposes proposal/review and strict diagnosis as the unique next action before the ordinary lifecycle path.
- `application.py` gates exact-requirements implementation on proposal approval and projects host verification outcomes into escalation events.
- `verification.py` records an unchanged retry signal when an already-failed identity is planned again. Host execution remains external and host-asserted.
- `cli.py` exposes `acceptance status|propose|review` and `escalation status|diagnose`; the six MCP tool registry remains unchanged.

## 0.20.9 implementation map

- `acceptance.py` owns the schema-v2 AcceptanceContract and bounded exact
  requirements-source store. It validates project-relative UTF-8 regular files,
  immutable content identity and wide strict closure coverage.
- `project.py` defines the additive `.hellodev/acceptance-sources.json` path.
- `application.py` carries `requirements_file` through begin/approval recovery,
  exposes source integrity in the closure plan and enforces the managed Trellis
  completion invariant before lifecycle finish.
- `lifecycle.py` rejects public low-level `finished` transitions for a bound
  WorkItem unless called by the verified managed closure path.
- `cli.py`, `resume.py`, `onboarding.py` and `facade.py` expose the exact-source
  input without adding a new daily step or MCP tool.
- `dashboard.py` and `dashboard_assets/app.js` expose only sanitized source
  integrity counts/state; path, digest and raw requirements are excluded.

## 0.20.8 implementation map

- `adapters/trellis.py` aligns prepared and executed task-set identity by
  filtering to valid non-symlink task directories.
- `verification.py` owns bounded npm launcher canonicalization, executable
  host rendering and atomic current-snapshot result batches.
- `application.py` exposes the conservative closure plan at begin and refreshes
  the WorkItem after explicit current-snapshot evidence.
- `trellis_bridge.py` projects mergeable, hash-only HelloDev quality evidence
  without taking ownership of Trellis/user gate files.
- `cli.py` accepts repeated `--result-json` and PowerShell-safe structured
  `--result` fields; Core still never executes the returned host commands.

## 0.20.7 implementation map

- [Implemented] `resume.py` owns the single structured `begin-work` recovery action. An unbound or acceptance-missing active cycle cannot fall through to the legacy lifecycle `do plan/work/check/finish` mapping.
- [Implemented] `application.py` enforces WorkItem identity on `plan` and WorkItem plus AcceptanceContract identity on `work`, `verify`, `check`, and `finish`. `do begin` can repair a legacy unbound active cycle without rewinding it.
- [Implemented] `gates.py` treats WorkItem, AcceptanceContract, and satisfied acceptance as non-negotiable closure identity. `finishPolicy=suggest` applies only to supplemental gate policy.
- [Implemented] `trellis_bridge.py` and the Trellis adapter expose recoverably idempotent `task-begin`; `application.py` performs bounded unique alignment or returns exact candidate actions, then persists the WorkItem, contract, and binding.
- [Implemented] `dashboard.py` schema 23 / Control Center 3.3 exposes sanitized binding and closure booleans plus the compact unique next action. It remains read-only and copy-only.
- [Preserved] Manifest-first ordered host verification, host-asserted trust, six MCP tools, six-field default `open`, one-time authorization, and independent Trellis/Nocturne authority remain unchanged.

## Historical 0.20.6 orientation map

- [High confidence, source read] `trellis_execution.py` owns runtime command discovery and currently checks a generic `tests/` directory before `package.json`; this is the reproduced TypeScript-to-pytest misclassification surface.
- [High confidence, source read] `acceptance.py` currently models one host command and always constructs its action before inspecting a blocked failure. It is the primary surface for an ordered current-snapshot verification plan and fail-closed action projection.
- [High confidence, source read] `verification.py` already provides exact command/scope/snapshot identities and atomic host-asserted receipts. 0.20.6 can reuse this store without a new executable authority or raw output persistence.
- [High confidence, source read] `resume.py` copies `hostTest.action` into the unique next decision. It must only do so when the selected plan step is runnable; top-level command and action must remain coherent.
- [Preserved boundary] Trellis task/context validation remains authoritative context evidence but is not host-test quality evidence. HelloDev emits one command at a time and never shell-chains or executes it.
- [Validation boundary] Unit tests must cover TS-only `tests/`, Python compatibility, ordered test/typecheck progress, snapshot invalidation, mixed-repo ambiguity, and unchanged-failure routing. Real retained Trellis validation must start from a clean fixture clone.

## 0.20.5 orientation map

- [High confidence, implemented] `verification.py` supports explicit atomic current-snapshot host attestation. Daily `next.action` returns the host command plus exact success/failure receipt commands; legacy session and copied-snapshot paths remain compatible, and all evidence remains `host-asserted`.
- [High confidence, implemented] `resume.py` returns a typed host-command/record-success/record-failure action and onboarding rules set `helpOrStatusProbeRequired=false`, so a compliant host does not need preliminary help, status, gate or receipt probes.
- [High confidence, implemented] `knowledge_flows` defaults technical Nocturne recall to `core`, enriches one bounded query with detected runtime terms, exposes zero accepted results and performs no automatic retry. The project namespace remains audit-only because upstream `search_memory` has no verified namespace argument.
- [High confidence, implemented] default six-field `open` and ordinary `do` do not scan the in-flight Codex rollout. `open --verbose` and explicit `usage sync` retain exact completed-turn collection; unsupported hosts remain `unavailable`.
- [Fact, audited runtime evidence] The valid full-capability sample passed runtime, hidden and TypeScript checks but used 136 shell calls; 100 were classified as HelloDev/Trellis coordination. Nocturne executed successfully but returned no accepted item for a seed found by direct pre-run search.
- [Fact, validation boundary] Focused, fast/full and isolated base-wheel gates cover the 0.20.5 behavior. Repeated sequential Direct Agent A/B measurement remains separate and no performance percentage is claimed from implementation tests.

## 0.20.4 aligned fast-path map

- [High confidence, implemented] `task_alignment.py` reads at most 64 KiB of `task.json`, consumes only bounded identity/title/description/scope/package fields, and requires meaningful goal-token overlap before the sole active Trellis task may be selected automatically. Explicit selection and newly created tasks are recorded in a hash-only `.hellodev/task-bindings.json` attestation.
- [High confidence, implemented] `application.py` creates a new approved Trellis task when the sole existing task is unrelated. `finish` refuses to complete a legacy Trellis binding that has neither a binding attestation nor current goal alignment.
- [High confidence, implemented] `verification.coverage()` can reuse same-WorkItem, same-scope-snapshot, equal-or-stronger successful host evidence for at most five-file `standard` work. It never claims command equivalence; `strict` work retains exact T2/project evidence.
- [High confidence, implemented] `typescript_impact.py` provides bounded exported-declaration/reference counts for changed `.ts`/`.tsx` files. It can only escalate adaptive risk and exposes no symbol or path.
- [High confidence, implemented] `repository_tools.py` labels the native provider as language-aware and FastCtx as `available-not-active`; discovery never proves activation. Dashboard schema 20 / Control Center 3.0 displays the resulting projections read-only.

## 0.20.3 guided acceptance map

- `guided_acceptance.py` derives `lite`, `guided`, or `strict` from the AcceptanceContract, ChangeSet and bounded semantic impact. It blocks explicit feature work with no code change and projects count-only quality evidence.
- `python_impact.py` performs dependency-free Python AST analysis for newly introduced override constructor parameters that are accepted but not loaded or forwarded to a base constructor. It returns only counts and SHA-256 fingerprints.
- `changesets.py` schema 2 captures a hash-only quality baseline at `begin`, so pre-existing findings do not block unrelated work. Schema 1 remains readable and exposes the missing baseline as advisory.
- `acceptance.py` composes guided quality separately from the 0.20.2 host/Trellis coverage ratio. `resume.py` routes quality failures as `guided-acceptance-blocked`; `check` and `finish` both use the same fail-closed acceptance gate.
- `verification.py` reports command, snapshot and repeat diversity over the current WorkItem while preserving current-snapshot reuse counts and `host-asserted` trust.
- `application.py` keeps the exact six-field default `open` contract while exposing mode, quality and blocker reason codes. `dashboard.py` and Control Center 2.9/schema 19 add the same filtered read-only projection.

## 0.20.2 native component map

- `component_protocol.py` defines `hellodev.component/v1`, component identities, canonical hashes and legacy MCP text-error recognition.
- `trellis_bridge.py` and `trellis_bridge_runner.py` implement the isolated structured `hellodev@trellis` task/gate bridge with operation replay and digest checks.
- `nocturne_protocol.py` stores project-bound namespace hashes, read receipts, expected versions and mutation replay hashes without memory content.
- Both adapters select enhanced bundled behavior while retaining compatibility mode for explicit upstream installations.

## 0.19.7 semantic context implementation map

- `context_runtime/semantic.py` provides dependency-free Python AST definition retrieval and count-only cross-file impact analysis. Explicit symbol-shaped queries opt in; all other queries retain lexical retrieval. _Implemented with bounded snippets and cache limits._
- `context_runtime/planner.py` runs semantic retrieval inside the existing root-bound snapshot, pagination and byte-budget contract. Context state schema 2 persists strategy/counts only. _Implemented without raw query, symbol, path or source persistence._
- `repository_tools.py` discovers Serena as an optional host-managed capability without inspecting MCP configuration or claiming connectivity. Native Python AST remains active and Serena write tools inherit no workflow, memory or verification authority. _Implemented read-only discovery._
- `trellis_execution.py` consumes count-only semantic impact as an escalation-only signal. Wide cross-file references may raise T1 to T2; no semantic result can reduce a gate or satisfy final validation. _Implemented conservatively._

## Source and runtime boundaries

| Location | Role | Authority |
|---|---|---|
| `packages/hellodev-core/` | Canonical standalone Python source | Editable product source. |
| A selected project's `.hellodev/` | Per-project config, lifecycle, caches, tasks, receipts, Sagas, leases | Runtime state created by explicit HelloDev commands. |
| A selected project's `.trellis/` | Upstream project workflow and memory | Repository authority; HelloDev reads/calls it through bounded adapters. |
| Configured Nocturne stdio MCP | Cross-project advisory memory | External, fallible context; never repository authority. |
| Extracted 0.14 platform bundle | Immutable component/runtime payload | Manifest-checked local bytes; not a signature, provenance witness, or legal conclusion. |
| Selected HelloDev home | Runtime marker and Nocturne writable data | User-writable data plane, separate from the bundle payload and project state. |
| `outputs/hellodev` | Legacy Codex-plugin reference | Frozen evidence, never an active build source. |
| Versioned release copies | Immutable source/wheel evidence | Must remain separate from source and installed caches. |

## 0.19.6 adaptive Trellis execution map

- `trellis_execution.py` bounds the complete current `task.json` read to 64 KiB, consumes only `priority`, `scope`, and `status` after parsing, combines them with hash-only ChangeSet counts, and selects `quick`, `standard`, or `strict`. Unsafe, malformed, or oversized metadata fails closed to strict. _Fact - full source read._
- `verification.inspect()` provides a non-persistent exact command/scope/snapshot lookup. `resume.next_decision()` recommends one host-run verification before `do check`, reuses unchanged success, and refuses blind reruns of unchanged failure. _Fact - full source read and focused behavior test._
- `application.py`, `resume.py`, `dashboard.py`, and `facade.py` expose the bounded policy projection without adding an MCP tool or daily command family. Compact status omits the full projection and remains bounded. _Fact - full source read and focused contract test._
- The layer does not execute tests, write `.trellis/`, copy task/PRD/spec bodies, create Trellis gate evidence, or weaken approval and final native validation. _Fact - implementation boundary and negative tests._

## 0.19.5 unified facade implementation map

- `facade.py` derives a read-only daily namespace and counts routed Trellis intent receipts versus HelloDev-observed generic Trellis escape-hatch receipts. External direct CLI use remains explicitly unavailable rather than inferred. _Implemented privacy/observability boundary._
- `resume.py` re-enters one finished native task through `do begin`; `gates.py` sends a Trellis-backed strict gate recovery through `do validate`. Internal WorkItem and gate-status commands remain advanced compatibility surfaces. _Implemented daily-command convergence._
- `onboarding.py` and `mcp_gateway.py` instruct Cursor, Antigravity and MCP hosts to keep task/lifecycle/validation/recovery behind HelloDev, replace `trellis-continue` with `hellodev resume`, and use direct Trellis only as a disclosed unsupported-operation escape hatch. _Implemented host guidance._
- `application.py`, `resume.py`, `dashboard.py` and Control Center 2.6 project the facade without executing adapters or exposing native argv. _Implemented additive diagnostics._

## 0.19.4 end-to-end efficiency implementation map

- `context_runtime/planner.py` permits subpackage focus only for an explicit full package identity. Cross-package natural-language queries remain rooted at the project and rank declarations/executable code above repetitive comments. _Implemented and cross-package recall-tested._
- `context_runtime/native.py` provides a request-scoped immutable snapshot session; `application.py` shares it across synchronous read projections while write intents retain fresh snapshots. _Implemented and call-count tested._
- `changesets.py` and `verification.py` avoid repository inventory for absent baselines/records. Existing baseline and verification evidence retain strict current-snapshot validation. _Implemented lazy empty-state path._
- `governance.py` appends Codex runtime usage receipts through one lock/load/atomic write per sync batch; `usage_collector.py` still parses each completed turn independently and preserves fail-closed collection, idempotency and twenty-turn reflection. _Implemented and batch-write tested._
- `briefs.py`, `mcp_gateway.py`, and `bounded_results.py` budget the complete serialized MCP response envelope and retain one structured continuation. _Implemented and full-payload byte-tested._

## 0.19.3 Antigravity host adaptation map

- `integrations.py` renders the official project-level `.agents/mcp_config.json` stdio shape with exact current-Python command, arguments and cwd. `onboarding.py` merges that config and writes a bounded Markdown rule under `.agents/rules/hellodev.md`; conflicts fail before HelloDev project initialization. _Implemented and idempotency-tested._
- `project.py` persists the explicitly selected host as backward-compatible config metadata. `application.py` and `cli.py` automatically collect Codex rollout usage only for Codex or legacy projects; Cursor/Antigravity/none return truthful unavailable telemetry unless a separate trusted Host SDK path supplies it. _Implemented and no-Codex-attribution tested._
- `repository_tools.py`, CLI integration choices and Dashboard host diagnostics include Antigravity while preserving exactly six MCP tools. Trellis initialization remains `trellis init --yes` because no upstream Antigravity flag is assumed. _Implemented compatibility boundary._
- No user-level `~/.gemini` configuration, plugin state, global installation, upstream source or data plane is modified. _Fixed scope boundary._

## 0.19.2 Context Plane efficiency implementation map

- `context_runtime/planner.py` selects a root-bound focus from the current nested package/worktree or one unique query-matching package marker. Ambiguous/no match falls back to the selected project root. Result paths remain project-relative. _Implemented and focus-tested._
- Partial first pages create bounded process-memory ranked result sessions. Version-2 cursors bind the project, focus, snapshot, query, scope, offset and session; version-1 cursors remain readable. Continuation hits validate cached metadata and avoid `snapshot()` plus `_rank()` entirely. _Implemented and call-count tested._
- `context_runtime/native.py` caches safe file/directory metadata markers. A hot unchanged snapshot no longer reruns `_candidates()`; mutation, deletion, symlink replacement or directory identity change invalidates reuse. _Implemented with stale regression preserved._
- Sessions enforce TTL, count, per-session result/byte and aggregate byte bounds. Cache loss or process restart reconstructs strictly; raw query/path/source/session data remains process-local and is not persisted under `.hellodev/`. _Implemented privacy boundary._

Validation: focused compatibility passed 50 tests; fast passed 226 tests and full passed 266 tests with two expected environment skips. Python compilation and Dashboard JavaScript syntax passed. Local package continuation measured about 13 ms; forced broad-root continuation measured about 422 ms; adaptive broad-root-to-package continuation measured about 16 ms. A final disposable 245,191-byte wheel installed offline, reported 0.19.2, opened a clean project and exposed six tool names; SHA-256 was `140c516413db912ea2a92fde52e086e9023a81c315e462e5aed79c8262fb6782`. The optional MCP SDK was unavailable in the current interpreter, so real stdio smoke remained an expected environment skip. _Local acceptance fact, not a cross-host performance claim._

## 0.19.1 trusted Codex telemetry implementation map

- `usage_collector.py` now selects an automatic runtime by `CODEX_THREAD_ID` when available, otherwise by the most-recent safe rollout whose recorded cwd overlaps the selected HelloDev root. Explicit thread/session/home selection remains an asserted import. _Implemented and project-binding tested._
- Token events are parsed as structured JSON and validate the required cumulative counters while tolerating additive host metadata such as `cache_write_input_tokens`. Count regressions, inconsistent totals, unsafe paths and incomplete descendant sessions still fail closed. _Implemented against current real Codex Desktop metadata and fixtures._
- `open` and daily `do` backfill completed turns idempotently; `next/status/resume` remain read-only. Automatic results expose `selectionMode`, trust, exactness, recorded/skipped counts and `remainingUntilNextCycle`; unavailable hosts remain explicit and are never estimated. _Implemented and compatibility-tested._
- The existing fixed twenty-turn ReflectionCycle remains deterministic, non-effective and advisory. Only automatic `runtime-observed + exact` receipts enter it; no transcript, runtime path, thread/turn/subagent id or raw event is persisted. _Preserved privacy and policy boundary._

Validation for 0.19.1: focused telemetry/version/dashboard regressions passed 63 tests. Fast passed 219 tests and final full passed 259 tests with two expected environment skips; Python compilation and Dashboard JavaScript syntax passed. The parser read the current local Codex rollout with additive metadata and found 164 completed turns, 5,640 usage snapshots and 169 subagent activity events. A disposable 241,681-byte wheel installed offline without dependencies, reported 0.19.1, opened a clean project with truthful unavailable usage, and exposed exactly six MCP tools; SHA-256 was `111ba44eb195ea3e3dc3ecfc7230261742daab301d1f345b4b3bef09ce71c71d`. Temporary artifacts were removed. _Historical local acceptance fact._

## 0.19.0 adaptive-orchestration implementation map

- `workflow_projection.py` derives `local`, `trellis-native`, or `hybrid-recovery`. A valid Trellis WorkItem makes native task/spec/gate authoritative; HelloDev lifecycle remains a labelled projection and never mutates Trellis from status. _Implemented and mode-tested._
- `changesets.py` reuses the native Context Plane inventory and persists path/content hashes plus code/docs classification only. `do begin` captures the baseline; status/check/finish/resume expose bounded counts without raw paths or source. _Implemented and privacy-tested._
- `verification.py` schema 2 keeps schema-1 read compatibility, adds code/docs/project scope identities and persistent one-hour sessions, and rejects stale scope, WorkItem switching, expiry, replay and contradictory evidence. T0/T1 default to code; T2 defaults to project. _Implemented and compatibility-tested._
- Host-asserted intermediate verification remains advisory. It must not create Trellis gate evidence, authorize actions, or bypass `finishPolicy`; typed Trellis gate/test receipts remain the final authority. _Fixed safety boundary._
- Existing daily commands, exactly six MCP tools, stores, profiles, Saga/WAL/policy, Context Plane and upstream adapters remain compatible. `next/resume` surface one pending verification session before ordinary lifecycle advice. Dashboard schema 15 / Control Center 2.5 remains GET/copy-only. _Implemented compatibility boundary._

Validation: fast passed 216 tests and full passed 256 tests with two expected environment skips; Python compilation and Dashboard JavaScript syntax passed. A disposable wheel installed in a fresh venv, reported 0.19.0, exercised begin/scoped-session/record/reuse, Dashboard schema 15 and exactly six MCP tools, then was removed. No publication, release artifact, global installation or upstream modification was performed. _Local acceptance fact._

## 0.17.0 usability-convergence implementation map

- `experience.py` owns the daily `currentTask` projection and the deterministic 1200-token Context Plan. It reads pointer/count state but does not read repository source or persist the goal. _Implemented and verified._
- `routing.py`, `application.py`, and `cli.py` add `do begin`: local projects create one Markdown task; Trellis projects select one active task or use the existing prepare/approve task-create path; ambiguous selection fails closed. Existing lifecycle/task/work commands remain available. _Implemented; focused tests passed._
- `onboarding.py` now supports Core and bundle through one project-scoped command. Core reuses an existing external Nocturne configuration or reports `configuration-required`; it never invents an executable or modifies global host configuration. _Implemented; focused tests passed._
- `dashboard.py` schema 13 and Control Center 2.3 show one current task by default while retaining internal L/T/W counts under environment diagnostics. The server remains loopback, token-bound, GET/copy-only. _Implemented and verified._
- Package/runtime metadata is aligned to 0.17.0. No release snapshot, bundle, PyPI upload, tag, GitHub push, global install or upstream-source change is part of local completion. _Boundary._

Validation: the focused compatibility matrix passed 42 tests; fast passed 203 tests and full passed 243 tests with two expected environment skips; Python compilation and Dashboard JavaScript syntax passed. A disposable 229,209-byte wheel installed offline without dependencies, reported 0.17.0, completed Core `onboard -> open -> do begin -> status`, and returned Dashboard schema 13 with `readOnly=true`. Its SHA-256 was `ca669002f4c3a5666aa85e8a981de384dbcf691805c6b6f060d822b59e67f80d`; temporary artifacts were removed. _Local acceptance fact._

## 0.16.0 Context Plane implementation map

- `context_runtime/contracts.py`, `native.py`, `planner.py`, and `cursor.py` own dependency-free, root-bound repository discovery, deterministic query/CJK-bigram ranking, budget-before-render composition, path/line/hash provenance and snapshot-bound continuation. Scans skip symlinks, sensitive files, dependency/build directories and enforce hard file/byte limits. _Implemented and verified._
- `briefs.py` preserves L0/L1/L2 while using task/query selection for `--query`; fixed Trellis sources reserve budget and repository snippets consume only the remainder. Preview does not persist; normal CLI context writes metrics/hash only. _Implemented and verified._
- `mcp_gateway.py` still exposes exactly six root-bound tools. `hellodev_context` accepts optional `query`, `scope`, and `cursor`; partial results continue through the same tool and cursor rather than adding a raw repository tool namespace. _Implemented and verified._
- `application.py`, `capabilities.py`, `audit.py`, `dashboard.py`, CLI doctor/status and Control Center schema 12 project filtered Context Plane state. Query, path and source text are excluded from durable/audit/UI state. _Implemented and tamper-tested._
- `repository_tools.py` is compatibility/diagnostic only. Native Context Plane is complete without FastCtx; a discovered FastCtx command is marked an optional, non-required, non-recommended accelerator and receives no workflow, memory, write or shell authority. _Implemented boundary._
- `bounded_results.py` continues to measure HelloDev MCP payloads. Context completeness is decided before annotation by the Context Plane cursor contract. _Implemented integration._

Validation: fast 196 tests and full 236 tests passed with two expected environment skips; Python compilation and Dashboard JavaScript syntax passed. A disposable 225,263-byte wheel installed offline without dependencies, reported 0.16.0, completed empty-project `open/status`, and paged a five-file Context Plane query as 3 + 2 items with zero overlap. The temporary wheel SHA-256 was `2b130e8ac1b9e86def255167c4154956769ba48715360bcd16131c8d2208027e`; it was removed after validation and is not a release artifact. The HelloDev-only GitHub mirror is now at corrective commit `5efc24db182b1afa471defb93ccfc97dd1a7a00a`; GitHub Actions run `29899673960` passed the Windows/Ubuntu fast matrix, full gate and official MCP SDK job after the zero-TTL Dashboard cache boundary was made deterministic. _Fact - independently verified from source/config, local gates and the public CI run._

## 0.13.0 retained baseline

0.13.0 established the typed, root-bound `ProjectClient`, the exact six-tool optional stdio MCP gateway, and read-only `integrate show/check`. CLI and MCP share the same daily application path; no tool accepts a replacement root, arbitrary executable/argv, generic adapter, policy operation, Dashboard action, or HostEnvelope operation. This baseline remains the application contract underneath 0.14. _Fact — independently verified from source/config and inherited 0.13 release evidence._

## 0.14.1 implemented distribution surfaces

- `components.py` owns strict manifest parsing, component-lock checks, bundled-first resolution, request-scoped verification reuse, runtime identity, setup, and local integrity reporting. Selecting a bundle prevents fallback to ambient PATH when the bundle is invalid. _Fact — full source read._
- Bundled Trellis launches with an exact Node-plus-CLI prefix and binds Node, Trellis entry points, the manifest, and its verified Python dependency into approval identity. Existing external PATH mode remains available only when no bundle is selected. _Fact — full source read of `components.py` and `adapters/trellis.py`._
- Bundled Nocturne launches headlessly through `nocturne_runner.py`; payload code remains manifest-controlled while config and SQLite remain under the selected HelloDev home. Project config stores a symbolic bundled selection rather than an install path. _Fact — full source read of runner, project, and adapter code._
- Capability fingerprints include the component runtime fingerprint. Explicit `onboard` is the compatibility boundary, so 0.13 projects do not silently gain memory access. _Fact — full source read of `capabilities.py`, `project.py`, and `onboarding.py`._
- `onboarding.py` may explicitly write project-scoped Cursor/Codex configuration after conflict and path preflight. `integrations.py` itself remains read-only and renders/checks snippets only; neither surface writes user-level host configuration. _Fact — full source read._
- `bundle_builder.py` and the build/verify scripts produce deterministic strict archives with component locks, notices, licenses, source materials, SBOM, traversal/link/collision checks, and exact post-build verification. _Fact — full source read and exact Windows artifact smoke._
- The Core wheel remains `py3-none-any` and MIT-licensed. Platform runtimes and the separately licensed Trellis/Nocturne payloads belong only to platform archives. _Fact — independently verified from package metadata and distribution files._

The first 0.14 release target is Windows x86_64. Linux/macOS are not supported release claims until their own exact archives pass the same offline gate. Manifest and SHA-256 checks establish local byte consistency only; they are not signatures, remote provenance, tamper-proofing, or legal review.

## Package topology

```text
packages/hellodev-core/
  pyproject.toml
  README.md
  CONTRIBUTING.md                   contribution, privacy, and test contract
  .github/workflows/ci.yml          bounded non-publishing fast/full/MCP matrix
  .github/workflows/publish.yml     release-only OIDC Trusted Publishing path
  scripts/verify.py                 fast/full validation split
  scripts/build_unified_bundle.py   deterministic platform-archive builder entry
  scripts/verify_unified_bundle.py  exact archive verification entry
  scripts/demo.ps1                  zero-upstream daily-flow demo
  examples/                         minimal CLI and typed Host SDK examples
  docs/
    F1_DEMO.md                      seamless-flow regression matrix
    F2_DEMO.md                      continuity and cross-process acceptance
    OPTIMIZE_DEMO.md                0.10 advisory/reflection acceptance
    DISCLOSURE_DEMO.md              0.10.1 daily/recovery/advanced acceptance
    EVOLUTION_DEMO.md               0.11 HostEnvelope/policy/drift acceptance
    CASE_STUDY.md                    reproducible local case and recovery evidence
    WHY_HELLODEV.md                 product motivation, comparisons, limitations
    RELEASE.md                      build, smoke, migration gate
    ai/                             agent orientation documents
  src/hellodev/
    application.py                  typed, root-bound daily ProjectClient facade
    cli.py                          grammar, output formatting, advanced dispatch
    command_rendering.py            exact bundle launcher continuation rendering
    components.py                   manifest/lock verification, resolution, setup
    bundle_builder.py               deterministic strict platform archive builder
    onboarding.py                   explicit project-scoped host/component setup
    nocturne_runner.py              headless payload/data-separated Nocturne launch
    mcp_gateway.py                  optional official-SDK six-tool stdio transport
    integrations.py                 read-only Codex/Cursor snippet show/check
    routing.py                      deterministic open/next/do routes and bounded finished-work hint
    context_policy.py               pure L0/L1/L2 selection
    knowledge_flows.py              local-first recall, remember plans
    profiles.py                     strict/trusted/autopilot policy + leases
    approval.py                     atomic exact operation/policy tokens
    capabilities.py                 content-fingerprinted discovery cache
    briefs.py                       bounded brief/context-pack rendering
    context_runtime/                native discovery, ranking, provenance and cursor contracts
    lifecycle.py                    project-local lifecycle
    project.py                      safe project paths/config/tasks
    receipts.py                     schema-v3 hash-only audit records
    sagas.py                        non-atomic verified cross-system sequence
    contracts.py                    pointer/hash-only WorkItem, LessonProposal, EvidenceLink stores
    resume.py                       deterministic cross-session recovery and bounded handoff pack
    gates.py                        read-only gate projection and local finish policy
    delegation.py                   deterministic agent-count/context-budget contract
    optimization.py                 0.10 records/proposals plus read-only advanced next hint
    host_bridge.py                  bounded prepare/validated completion bridge for external hosts
    host_sdk.py                     typed Python HostClient and protocol negotiation
    py.typed                        PEP 561 typed-package marker
    schemas/*.json                  bundled HostEnvelope/HostResult/protocol schemas
    policy_evolution.py             stage/cancel/canary/commit/revert and local hash chain
    transactions.py                 append-only policy authorization/receipt/ledger WAL
    checkpoints.py                  portable policy ledger-head export and verification
    drift.py                        read-only structural/runtime policy-drift projection
    audit.py                        privacy-preserving local audit projection and fix hints
    state_lock.py                   shared cross-process locks for small project-local stores
    intelligence.py                 classification and narrow policy plans
    adapters/trellis.py             Trellis native gateway/intents
    adapters/nocturne.py            public stdio MCP client
    governance.py                   schema-v1 manual ledger plus additive runtime-receipt sidecar and trust-aware projections
    usage_collector.py              bounded previous-completed-turn collector plus oldest-first backfill
    efficiency_cycles.py            trusted non-overlapping 20-turn deterministic reflection sidecar
    dashboard.py + dashboard_assets read/copy-only loopback Control Center
    distribution/                   component lock and third-party notice source
    schemas/component-bundle-v1...  strict bundle-manifest schema
  tests/
    test_f1_cli.py                  unified flow and profile integration
    test_f1_security.py             MCP failure and execution-identity binding
    test_approval_atomicity.py      thread/process one-time-token enforcement
    test_context_policy.py          deterministic level rules
    test_routing.py                 fail-closed routes and next state
    test_knowledge_flows.py         bounded recall/remember planning
    test_profiles.py                policy, lease, migration matrix
    test_receipt_evidence.py        typed evidence/schema compatibility
    test_optimization.py            unavailable/asserted usage, reflection caps, proposals, tamper rejection
    test_host_bridge.py             envelope bindings, completion trust/privacy/idempotency
    test_policy_evolution.py        stage/cancel/canary/exhaust/evaluate/commit/revert/integrity matrix
    test_v11_cli.py                 public 0.11 grammar and closed-loop CLI path
    test_usage_collector.py         completed-turn/backfill/subagent/privacy/idempotency/fail-closed matrix
    test_efficiency_cycles.py       fixed-window/advice/tamper/disclosure/policy-boundary matrix
    test_v12_reliability.py         WAL recovery, SDK, Canary v2, checkpoint, doctor/audit matrix
    test_v121_polish.py             receipt/WAL gap, concurrent recovery, CI checkpoint, typed SDK matrix
    test_v121_oss.py                CI/package/docs/example consistency and runnable SDK example
    test_v13_gateway.py             ProjectClient/integration/progressive-help baseline
    test_v13_mcp.py                 official-SDK six-tool stdio contract
    test_v14_distribution.py        bundle, resolver, onboarding, data and path security
    test_v16_context_plane.py       native query, cursor, privacy, MCP and Dashboard matrix
```

## F1 request flow

```text
open
  -> initialize .hellodev if absent
  -> start only when phase=new
  -> refresh capability cache
  -> return next decision

next
  -> read local lifecycle/cache/recent Saga
  -> choose exactly one command
  -> attach deterministic suggestedLevel
  -> only when finished + attention/review-due, attach one optional efficiency hint
  -> no adapter call

do <intent>
  -> routing.decide (non-persistent)
  -> context_policy.suggest (pure)
  -> local action OR adapter prepare
  -> authorization decision
  -> same-command approval / lease / profile-auto
  -> adapter execution
  -> schema-v3 receipt
```

## F2 continuity flow

```text
task create/start/link
  -> WorkItem(pointer only)
  -> bind current lifecycle phase + capability fingerprint

validate or typed gate/test receipt
  -> receipt captures WorkItem/fingerprint binding digest at execution time
  -> EvidenceLink verifies that existing binding; it cannot grant one later
  -> gate status/reconcile remains read-only toward Trellis

remember
  -> LessonProposal(SHA-256 only; no lesson text)
  -> optional verified evidence + Saga pointer
  -> saga next / resume reconstruct one safe continuation

delegate plan
  -> deterministic main-only/delegate decision
  -> bounded shared digest + selected role budgets
  -> delegate pack emits shared context plus one role delta
```

Missing F2 stores are interpreted as an unmodified 0.8 project and are not created by read-only inspection. `resume`, `next`, gate projection, and delegation planning make no adapter or model calls. These claims are independently verified from source and by the final 104-test release matrix, real disposable Trellis run, and isolated wheel smoke.

## 0.10 optimization flow

```text
optimize plan
  -> deterministic context policy
  -> caller-declared token/subagent ceilings
  -> plannedDeepReflectionCeiling + anomaly-and-reported-usage-required eligibility label
  -> optional WorkItem pointer/fingerprints
  -> no actual usage, persistence, adapter, model, or spawn

usage record
  -> operator-supplied assertion only
  -> sourceKind=operator-report, sourceTrust=asserted
  -> never trusted, host-verified, or tokenizer-exact

optimize reflect
  -> optional explicit usage id/latest projection
  -> bounded DecisionTrace + deterministic ReflectionReport
  -> anomaly-gated deep-reflection eligibility
  -> optional allowlisted tighten-only EvolutionProposal after repeated evidence
  -> local atomic persistence; no adapter/model/apply

optimize status / proposals
  -> read-only counts, summaries, staleness, next advisory command
```

Missing `optimization.json` is an unchanged 0.9 project and remains absent under status/plan/proposals/dashboard/audit reads. `reflect` is the only optimize command that writes it. An identical trace payload is idempotent.

## 0.10.1 progressive disclosure preserved in 0.11

```text
daily:    open -> next -> do
recovery: resume / capability / WorkItem / Saga / gate / doctor commands
advanced: optimize / delegate / usage / audit / native adapters / host / policy / drift

next priority:
  uninitialized / stale capability / incomplete Saga / stale WorkItem / gate blocker
  -> active lifecycle primary command
  -> finished primary command: hellodev receipt list
  -> optional efficiency block only for existing attention|review-due state
```

The optional block never changes the primary command. `attention` suggests `hellodev optimize status`; `review-due` suggests `hellodev optimize proposals`. Missing, `insufficient-data`, and `ready` states are quiet. Active work and all safety/recovery decisions suppress it.

`optimization.next_hint` reads the existing store through `status`; it never creates a missing store, records an acknowledgement, or mutates optimization history. The block contains bounded trend/signal counts and one suggestion, reports execution/persistence false with empty adapter/model calls, and keeps the complete next projection within 1 KiB. `resume.build(...).next` uses the same decision.

Because optimization/usage is advisory, `next_hint` catches its `ProjectError` and returns no hint. Corrupt, malformed, or future advisory state therefore cannot block a finished daily next/resume command and is not repaired. Explicit `optimize status` still validates the same store strictly and fails closed. This fail-open boundary is limited to optional disclosure; workflow, recovery, authorization, and evidence errors remain authoritative.

## 0.11 host and verified-evolution flow

```text
host prepare (read-only)
  -> bounded context pack + next projection
  -> delegation decision/digest + token/subagent/retry ceilings
  -> root/capability/WorkItem/optimization/policy/ledger bindings
  -> expiry + nonce + whole-envelope hash
  -> grantsExecution=false; grantsEvidenceAuthority=false

external host
  -> performs its own separately authorized work
  -> returns only a bounded result assertion

host complete (strict --stdin recommended)
  -> verify envelope/context hashes and every current binding
  -> reject stale/tampered/conflicting results
  -> idempotently store sanitized HostCompletion
  -> call existing deterministic optimization reflection
  -> never store transcript/model output/raw context

EvolutionProposal
  -> policy stage (append-only, non-effective)
  -> optional policy cancel (append-only, non-effective staged escape)
  -> independently approved canary (temporary tighter overlay)
  -> bounded current-head HostCompletions; turn exhaustion restores committed effective policy
  -> read-only evaluate + drift clean
  -> independently approved commit (first committed-policy change)
  -> separately approved immediate revert when necessary
```

Host usage is either `host-asserted` and envelope-bound or `unavailable`; it is never provider-verified. Late completion is retained but excluded from current canary evidence. Host traces cannot satisfy gate/test evidence.

The committed policy defaults are `delegation.effectiveMaxAgents=2` and `retry.maxAttempts=3`. Only those integer targets are accepted, and only strictly tighter values can enter stage/canary/commit. Stage and staged cancel do not alter effective policy. Cancel requires no approval, is append-only/idempotent for the same staged proposal, and cannot cancel an active canary. Canary, commit, and revert use distinct exact action-bound approvals/receipts; the receipt store is validated before token consumption, tokens are not persisted, and exact response-loss replay returns the existing event.

`host complete --stdin` accepts exactly one `{envelope,result}` JSON object up to 512 KiB and cannot be combined with argv JSON; this is recommended to keep bounded context out of process arguments. The explicit `--envelope` + `--result` compatibility form remains available.

Each non-late HostCompletion bound to the active canary head consumes one declared turn until the limit. At exhaustion the overlay stops and effective policy returns to committed policy; public `observedTurns` is clamped to turnLimit and evaluation uses the first N records. Later same-head completions may exist under committed policy but do not extend canary evidence. Counts/usage remain host assertions, not provider-verified evidence.

Host completion and canary turn accounting share the project-local host-completion lock. Concurrent attempts cannot overshoot the remaining sample: the winner appends, while a later contender rechecks bindings and fails stale.

Revert targets the active canary first; otherwise it can restore only the most recent unresolved committed transition and only when no stage is active. A later stage must be cancelled first, but its non-effective stage/cancel ledger events do not erase the immediate commit rollback target. A prior revert closes that target, preventing arbitrary history traversal.

Every policy event carries `previousEventSha256` and `eventSha256`. This detects malformed records, broken links, partial edits, and a mismatch with an externally retained head. It does not detect a complete internally consistent history+head rewrite without that external checkpoint and is not a transparency log, remote witness, or non-repudiation mechanism.

`drift.status` is read-only and returns `clean|detected|unavailable|invalid`. It aggregates bounded capability/WorkItem freshness, canary expiry, optional checkpoint mismatch, current-head completions, declared budget/retry/subagent violations, and informational late completion. Invalid stores are projected explicitly and not repaired.

## 0.11.2 completed-turn usage and efficiency-cycle flow

```text
new Codex turn
  -> usage collect
  -> CODEX_THREAD_ID automatic selection, project-bound recent-rollout discovery, or caller-selected import
  -> parse only bounded session_meta/task_started/task_complete/token_count/sub_agent_activity events
  -> select the latest already-completed root turn
  -> cumulative root-interval delta
  -> recursively add complete descendant subagent intervals (max 32)
  -> persist additive usage-receipts.json with hashes/counts only; preserve usage.json schema v1
  -> usage sync backfills oldest unrecorded completed turns
  -> every 20 runtime-observed exact receipts create one hash-bound ReflectionCycle
  -> next/status / current Dashboard schema v7 expose one advisory efficiency hint
  -> usage display still prefers runtime-observed, then asserted-runtime, then asserted
```

The collector cannot finalize the response currently being generated because its `task_complete` boundary does not yet exist. It is intentionally a next-turn operation. Automatic Desktop selection uses an environment thread when it owns the selected root, otherwise a recent safe rollout whose recorded cwd overlaps that root. It yields `sourceKind=codex-runtime`, `sourceTrust=runtime-observed`, `measurement=exact`, `attestation=none`, and `estimated=false`; explicit thread/home/session selection is instead `codex-runtime-import` / `asserted-runtime`. “Exact” is limited to deterministic deltas over completed Codex event metadata; it is not provider-signed, provider-attested, or provider-verified.

The stored usage record contains token counts, `completedAt`, trust metadata, and source/scope/receipt SHA-256 values. It never stores rollout text, prompt/response content, raw events, thread/turn/subagent ids, or session paths. No completed turn returns `unavailable` without writing. Missing or incomplete descendant sessions, missing interval snapshots, unsafe paths, invalid shapes, count regression, or same-turn conflicts fail closed without persisting partial usage. Repeated collection and sync are idempotent. Manual `usage record` remains `operator-report/asserted`; explicit runtime selection remains `asserted-runtime`. Neither can enter ReflectionCycle. Runtime receipts and cycles remain outside the 0.11.0 optimization schema for rollback compatibility.

ReflectionCycle uses stable receipt insertion order and fixed, non-overlapping windows. Its additive sidecar stores only aggregate metrics, deterministic signal codes, one allowlisted command, and a strict non-effective policy boundary. It calls no model or adapter, and safety/recovery routing preempts its finished-phase disclosure.

## 0.12 reliability and host-contract flow

```text
policy approval validated
  -> transactions.json authorized event (no raw token)
  -> approval plan marked consumed and transaction-bound
  -> token-consumed event
  -> hash-only authorization receipt
  -> receipt-recorded event
  -> idempotent policy ledger append
  -> ledger-applied event

HostClient.prepare(HostRequest)
  -> protocol negotiation + bounded HostEnvelope
  -> sanitized pending metadata only
  -> external host execution
  -> HostClient.complete(HostResult)
  -> sanitized HostCompletion + host-asserted/unavailable trust
  -> bounded baseline/canary Evaluation v2
```

`next/resume` checks pending transactions before every other branch, then stale capabilities, pending HostEnvelopes, incomplete Sagas, stale WorkItems, Canary evaluation, lifecycle/gate progress, and optional efficiency advice. It returns one command only. Portable checkpoints bind the policy ledger sequence/head and protocol version; only an independently retained copy can detect a complete local-history rewrite.

## Unified intent ownership

| Intent | Normal route | Write boundary |
|---|---|---|
| `plan/work/check/finish` | Local lifecycle | Explicit invocation authorizes local state only. |
| `task` | Trellis if `.trellis/` exists; otherwise bounded local tasks | Trellis writes always require a token. |
| `validate` | Trellis `task-validate` | Read-class adapter action; successful result records `gate`. |
| `recall` | Bounded local search, then optional Nocturne search | External search follows active read profile. |
| `remember` | Classify -> project suggestion or verified Saga plan | Trellis/Nocturne writes never automatic. |
| `optimize` (explicit command family) | Local deterministic planning/reflection/proposal projection | Only `reflect` writes bounded local optimization state; no adapter/model/direct-apply authority. |
| `host` (advanced command family) | Read-only envelope preparation and validated external result ingestion | Prepare grants no authority; complete stores only a sanitized host assertion. |
| `policy` (advanced command family) | Local stage/cancel/canary/evaluate/commit/revert governance | Stage/cancel are non-effective, evaluate is read-only, and canary/commit/revert require separate exact approvals. |
| `drift` (advanced command family) | Read-only integrity/runtime projection | No repair or policy mutation. |
| `usage collect` (advanced observability) | Previous completed Codex rollout turn | Local read plus hash/count-only usage receipt; no current-turn, provider-attestation, authorization, or evidence authority. |

Unknown intents and unsupported task operations fail closed.

## Context policy

`context_policy.py` is deliberately adapter-free. The canonical intents are `status`, `doctor`, `lifecycle`, `local-task`, `code`, `trellis-read`, `trellis-write`, `saga`, `nocturne-write`, `cross-project-retrieve`, `recall`, and `remember`.

`brief build` and `context pack` accept `--intent`; an explicit `--level` wins. L2 still requires `--allow-l2`. Token budgets are bounded planning values, not host tokenizer receipts.

## Optimization policy

Optimization uses allowlisted structured values, not free-form model output. Outcomes are `succeeded|partial|failed|blocked`; retrieval is `none|local|narrow-memory`; delegation is `none|planned|rejected|executed`.

Actual optimization usage is unavailable unless a compatible operator/host record is explicitly linked. `usage record` creates an operator assertion. `usage collect` creates a display-only completed-turn receipt: runtime-observed under automatic Desktop discovery or asserted-runtime under explicit selection. Missing usage is never coerced to zero or estimated, and runtime receipts are not written into the preserved 0.11.0 DecisionTrace schema.

Plan exposes only `reflection.plannedDeepReflectionCeiling` plus `eligibility=anomaly-and-reported-usage-required`; this is not an eligibility decision. A ReflectionReport's deep reflection is host eligibility metadata only. It requires a deterministic anomaly plus positive linked reported total, and its ceiling is `min(500,floor(reportedTotal*0.05))`. Core always reports `modelCalls=[]`.

Each ReflectionReport also aggregates a structured trend over the same WorkItem when linked, otherwise the same intent: sample and usage-available counts, asserted total/average/subagent tokens, complete outcome/context distributions, executed-delegation count, and narrow-memory count. This is arithmetic over bounded trace fields, not model summarization.

EvolutionProposal generation remains non-self-applicable inside `optimization.py`: the only targets are `retry.maxAttempts` (`3 -> 2`) and `delegation.effectiveMaxAgents` (`2 -> 1`), both `tighten-only`, backed by three ReflectionReports, human-review-required, and `applyAllowed=false`. Config, ruleset, allowlist, target, or context-policy changes make older proposals stale. In 0.11, `policy_evolution.py` may separately stage and verify an eligible current proposal before commit; optimization records still cannot authorize commands or satisfy receipt/evidence contracts.

## Authorization and evidence

`profiles.authorization_decision` is the central read/write decision. The only authorization modes written to receipts are:

- `token-required`: exact one-time token supplied.
- `lease-allowed`: matching trusted-local Trellis read lease.
- `profile-auto`: current autopilot-read policy covers the read.

Profile/gate-policy changes, canary/commit/revert, and all external writes are token-required. Non-effective evolution stage/cancel is the documented local-ledger exception. trusted-local leases bind root, content fingerprint, executable identity, intent registry, read class, and expiry. autopilot-read additionally requires a configured domain allowlist, result ceiling, and expiry at most 24 hours ahead.

Approval prepare/consume read-modify-write is serialized in-process and cross-process. Adapter payloads include current executable and file-backed script identities, so a dependency replacement after prepare invalidates the token. MCP tool results explicitly marked `isError` produce failed receipts; a failed Nocturne Saga step becomes partial.

Profile relaxation is an F1 unified-path contract (`do task`, `do validate`, and `recall`). Low-level adapter and legacy smart escape hatches intentionally retain their own explicit approval flow.

Receipts are schema v3 and hash-only. v1/v2 stores normalize to `strict`/`token-required`; they persist as v3 only on a later receipt write. New typed gate/test receipts may carry `evidenceBindingSha256`; only matching execution-bound evidence can reconcile to a WorkItem. Typed Trellis gate/test plus a separate verification receipt is required before Nocturne persistence.

## 0.12.1 reliability and OSS polish

0.12.1 keeps Host protocol 1.0 and every 0.12.0 state schema. The additional transaction tests cover a receipt that persisted before the WAL receipt phase and multiple processes recovering the same transaction; the existing `policy-transaction` lock makes all workers converge on one receipt and one policy effect. Checkpoint validation now requires lowercase SHA-256 and bounded regular files, while `--require-match` preserves structured output and returns exit code 2 for CI mismatch.

The Host SDK is a PEP 561 package (`py.typed`) with public typed errors and pending/reconcile/abandon surfaces. Core still stores no HostEnvelope context: a valid pending record routes to exact `host pending <id>`, which declares whether the external host must continue and provides a separate abandon command. Canary v2 adds missing-evidence and commit-eligibility diagnostics without changing its pass/fail rules.

The GitHub Actions workflow is non-publishing: push/PR/manual triggers; concurrency group `hellodev-ci-${{ github.ref }}` with newer same-ref runs cancelling in-progress runs; `fail-fast=false`; Ubuntu/Windows × Python 3.10/3.12 fast; Ubuntu 3.12 full after fast; wheel artifact retained seven days. Dependency-free jobs deliberately omit pip caching because no cache directory is created. The standalone GitHub source mirror is published and this matrix is green; PyPI upload and GitHub Release creation remain external actions requiring separate authorization. The minimal Demo and Host SDK example use no Trellis/Nocturne installation.

## Dashboard boundary

The Control Center schema v7 is a read/copy-only projection. It may display F2 state, numeric/private optimization counts, trust-labelled usage, filtered ReflectionCycle progress/metrics/recommendation, pending transactions/HostEnvelopes, Canary v2 comparison, checkpoint state, Host protocol, proposal staleness, and filtered host/policy/drift status. It never exposes cycle/receipt/window hashes or an execution endpoint. Usage display must not claim it belongs to the response currently being generated.

It does not expose full envelopes, policy values, receipts/hashes, raw findings, repair commands, or complete/stage/cancel/canary/commit/revert controls. `uiCapabilities` fixes `copyOnly=true`, `applyAllowed=false`, `commitAllowed=false`, `revertAllowed=false`, and `actionApiAvailable=false`. No dashboard execution API exists.

## Validation entrypoints

```powershell
python scripts\verify.py --scope fast
python scripts\verify.py --scope full
```

Full 0.12.0 release validation adds WAL crash/recovery phases, typed SDK/schema/protocol negotiation, bounded baseline/canary comparison, checkpoint divergence/tamper, one-command recovery priority, compatibility diagnostics, audit privacy, and schema-v7 copy-only Dashboard smoke to all immutable 0.11.2 regressions. Historical release evidence remains unchanged.

## Verification basis

- **Fact — full source read:** the current application, component resolver, bundle builder, onboarding, integrations, adapters, package metadata, release workflow, and distribution schema define the 0.13 baseline and 0.14 source contracts summarized above.
- **Fact — inferred from tests then checked against implementation:** `test_v13_gateway.py`, `test_v13_mcp.py`, `test_v14_distribution.py`, and inherited security/reliability suites cover source-level compatibility and fail-closed behavior.
- **Fact — inherited then verified:** the daily F1/F2/optimization/disclosure contracts originated in earlier release docs and remain exercised by the existing regression suites.
- **Release evidence boundary:** 0.14.1 source-level gates record their exact fast/full results in the root development ledger. A Windows x86_64 platform claim requires a separately frozen archive, exact offline smoke, an isolated wheel smoke, and a versioned release report with checksums; source fixtures alone are insufficient. Exact hashes remain release-report evidence rather than signatures, provenance, or legal review.
