# HelloDev Core codebase map

Last refreshed: 2026-07-16
Scope: HelloDev 0.11.0 host bridge and verified tighten-only policy evolution on the released 0.10.1 baseline

## Source and runtime boundaries

| Location | Role | Authority |
|---|---|---|
| `packages/hellodev-core/` | Canonical standalone Python source | Editable product source. |
| A selected project's `.hellodev/` | Per-project config, lifecycle, caches, tasks, receipts, Sagas, leases | Runtime state created by explicit HelloDev commands. |
| A selected project's `.trellis/` | Upstream project workflow and memory | Repository authority; HelloDev reads/calls it through bounded adapters. |
| Configured Nocturne stdio MCP | Cross-project advisory memory | External, fallible context; never repository authority. |
| `outputs/hellodev` | Legacy Codex-plugin reference | Frozen evidence, never an active build source. |
| Versioned release copies | Immutable source/wheel evidence | Must remain separate from source and installed caches. |

HelloDev does not patch Trellis/Nocturne, merge databases, read or edit Codex/Cursor configuration, require Codex Desktop, bootstrap a host, or install itself globally. These are product boundaries, not pending automatic setup behavior.

## Package topology

```text
packages/hellodev-core/
  pyproject.toml
  README.md
  scripts/verify.py                 fast/full validation split
  docs/
    F1_DEMO.md                      seamless-flow regression matrix
    F2_DEMO.md                      continuity and cross-process acceptance
    OPTIMIZE_DEMO.md                0.10 advisory/reflection acceptance
    DISCLOSURE_DEMO.md              0.10.1 daily/recovery/advanced acceptance
    EVOLUTION_DEMO.md               0.11 HostEnvelope/policy/drift acceptance
    RELEASE.md                      build, smoke, migration gate
    ai/                             agent orientation documents
  src/hellodev/
    cli.py                          grammar and orchestration
    routing.py                      deterministic open/next/do routes and bounded finished-work hint
    context_policy.py               pure L0/L1/L2 selection
    knowledge_flows.py              local-first recall, remember plans
    profiles.py                     strict/trusted/autopilot policy + leases
    approval.py                     atomic exact operation/policy tokens
    capabilities.py                 content-fingerprinted discovery cache
    briefs.py                       bounded brief/context-pack rendering
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
    policy_evolution.py             stage/cancel/canary/commit/revert and local hash chain
    drift.py                        read-only structural/runtime policy-drift projection
    audit.py                        privacy-preserving local audit projection and fix hints
    state_lock.py                   shared cross-process locks for small project-local stores
    intelligence.py                 classification and narrow policy plans
    adapters/trellis.py             Trellis native gateway/intents
    adapters/nocturne.py            public stdio MCP client
    governance.py                   delegation and asserted operator-usage records
    dashboard.py + dashboard_assets read/copy-only loopback Control Center
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

Unknown intents and unsupported task operations fail closed.

## Context policy

`context_policy.py` is deliberately adapter-free. The canonical intents are `status`, `doctor`, `lifecycle`, `local-task`, `code`, `trellis-read`, `trellis-write`, `saga`, `nocturne-write`, `cross-project-retrieve`, `recall`, and `remember`.

`brief build` and `context pack` accept `--intent`; an explicit `--level` wins. L2 still requires `--allow-l2`. Token budgets are bounded planning values, not host tokenizer receipts.

## Optimization policy

Optimization uses allowlisted structured values, not free-form model output. Outcomes are `succeeded|partial|failed|blocked`; retrieval is `none|local|narrow-memory`; delegation is `none|planned|rejected|executed`.

Actual usage is unavailable unless a record is explicitly linked. Existing usage records are operator assertions with hashed source/scope in optimizer projections. Missing usage is never coerced to zero or estimated.

Plan exposes only `reflection.plannedDeepReflectionCeiling` plus `eligibility=anomaly-and-reported-usage-required`; this is not an eligibility decision. A ReflectionReport's deep reflection is host eligibility metadata only. It requires a deterministic anomaly plus positive linked reported total, and its ceiling is `min(500,floor(reportedTotal*0.05))`. Core always reports `modelCalls=[]`.

Each ReflectionReport also aggregates a structured trend over the same WorkItem when linked, otherwise the same intent: sample and usage-available counts, asserted total/average/subagent tokens, complete outcome/context distributions, executed-delegation count, and narrow-memory count. This is arithmetic over bounded trace fields, not model summarization.

EvolutionProposal generation remains non-self-applicable inside `optimization.py`: the only targets are `retry.maxAttempts` (`3 -> 2`) and `delegation.effectiveMaxAgents` (`2 -> 1`), both `tighten-only`, backed by three ReflectionReports, human-review-required, and `applyAllowed=false`. Config, ruleset, allowlist, target, or context-policy changes make older proposals stale. In 0.11, `policy_evolution.py` may separately stage and verify an eligible current proposal before commit; optimization records still cannot authorize commands or satisfy receipt/evidence contracts.

## Authorization and evidence

`profiles.authorization_decision` is the central read/write decision. The only authorization modes written to receipts are:

- `token-required`: exact one-time token supplied.
- `lease-allowed`: matching trusted-local Trellis read lease.
- `profile-auto`: current autopilot-read policy covers the read.

Policy changes and all external writes are token-required. trusted-local leases bind root, content fingerprint, executable identity, intent registry, read class, and expiry. autopilot-read additionally requires a configured domain allowlist, result ceiling, and expiry at most 24 hours ahead.

Approval prepare/consume read-modify-write is serialized in-process and cross-process. Adapter payloads include current executable and file-backed script identities, so a dependency replacement after prepare invalidates the token. MCP tool results explicitly marked `isError` produce failed receipts; a failed Nocturne Saga step becomes partial.

Profile relaxation is an F1 unified-path contract (`do task`, `do validate`, and `recall`). Low-level adapter and legacy smart escape hatches intentionally retain their own explicit approval flow.

Receipts are schema v3 and hash-only. v1/v2 stores normalize to `strict`/`token-required`; they persist as v3 only on a later receipt write. New typed gate/test receipts may carry `evidenceBindingSha256`; only matching execution-bound evidence can reconcile to a WorkItem. Typed Trellis gate/test plus a separate verification receipt is required before Nocturne persistence.

## Dashboard boundary

The Control Center schema v4 is a read/copy-only projection. It may display F2 state, numeric/private optimization counts, asserted usage numbers, proposal staleness, reflection summaries, and filtered host/policy/drift counts/status. The only new advanced commands it may expose are `hellodev host status`, `hellodev policy status`, and `hellodev drift status`.

It does not expose full envelopes, policy values, receipts/hashes, raw findings, repair commands, or complete/stage/cancel/canary/commit/revert controls. `uiCapabilities` fixes `copyOnly=true`, `applyAllowed=false`, `commitAllowed=false`, `revertAllowed=false`, and `actionApiAvailable=false`. No dashboard execution API exists.

## Validation entrypoints

```powershell
python scripts\verify.py --scope fast
python scripts\verify.py --scope full
```

Full 0.11.0 release validation additionally requires unchanged F1/F2/0.10 optimization/0.10.1 disclosure regressions; HostEnvelope/completion stdin/trust/privacy checks; the stage/cancel/canary/exhaust/evaluate/commit/revert matrix; hash-chain/external-checkpoint and drift checks; source snapshot; no-cache wheel build; wheel hash; fresh isolated install; and schema-v4 read/copy-only dashboard smoke.

## Verification basis

- **Fact — full source read:** `cli.py`, `host_bridge.py`, `policy_evolution.py`, and `drift.py` define the public grammar and contracts summarized above.
- **Fact — behavior verified by tests:** `test_host_bridge.py`, `test_policy_evolution.py`, `test_v11_cli.py`, and dashboard regression tests cover the primary 0.11 paths and fail-closed boundaries.
- **Fact — inherited then verified:** the daily F1/F2/optimization/disclosure contracts originated in earlier release docs and remain exercised by the existing regression suites.
- **Release evidence boundary:** wheel/source hashes, isolated-install results, and independent release paths are versioned in the root development ledger and release report rather than duplicated in this architecture map.
