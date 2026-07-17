# HelloDev Core open questions

Last refreshed: 2026-07-16
Scope: HelloDev 0.11.0 host bridge and verified tighten-only policy evolution on the released 0.10.1 baseline

Release status, artifact hashes, and immutable evidence belong in the root development ledger and the versioned release report. The checks below are the reusable gate for any source change; this orientation file does not duplicate mutable artifact hashes.

## Fixed 0.11 decisions

1. Daily work remains only `open -> next -> do`; recovery remains `resume` plus explicit repair commands. `host`, `policy`, and `drift` are advanced.
2. `host prepare` is read-only and emits a bounded, current-fingerprint-bound HostEnvelope. It grants neither execution nor evidence authority and carries no approval receipt.
3. An external host owns actual execution. `host complete` accepts only a sanitized result after checking the envelope/context hash and all current bindings; it stores no transcript, model output, or raw context.
4. Host-supplied token/subagent counts are `host-asserted`, envelope-bound, and not provider-verified. Missing fields remain unavailable, never zero. Late completion is retained but cannot become current canary evidence.
5. Host traces and optimization records cannot satisfy Trellis gate/test evidence or authorize any operation.
6. Policy defaults are `delegation.effectiveMaxAgents=2` and `retry.maxAttempts=3`. Only those integer targets are allowed, strictly tighten-only.
7. `policy stage` is non-effective and allows only one active staged/canary proposal. Stale proposals fail closed. `policy cancel` appends an idempotent, non-effective staged cancellation without approval; it cannot cancel an active canary.
8. Canary requires an exact one-time policy approval, 1–20 turns, and TTL 60–86400 seconds. It creates only a temporary tighter overlay.
9. Each non-late same-head HostCompletion consumes one canary turn until the limit. At exhaustion, effective policy returns to committed policy, public `observedTurns` is clamped, and evaluation remains fixed to the first N records; later same-head records do not extend canary evidence.
10. Evaluation is read-only and uses that bounded non-late sample. Full successful sample, policy/budget compliance, and unexpired canary are required; counts/usage remain host-asserted rather than provider-verified.
11. Commit requires clean drift, passed evaluation, bounded unique completion ids, and a new exact approval. It is the first step that changes committed policy.
12. Revert requires another exact approval and can only cancel the active canary or restore the most recent unresolved commit's immediate previous policy. An active stage must be cancelled first; later non-effective stage/cancel events do not erase that target. Arbitrary historical rollback is absent.
13. The receipt store is validated before an approval token is consumed. Tokens are never persisted. Receipt-based recovery is allowed only when the recorded receipt exactly matches the interrupted evolution action; replay after append returns the existing matching event.
14. Recommended `host complete --stdin` input is exactly `{envelope,result}`, limited to 512 KiB, and mutually exclusive with argv JSON. The compatibility argv form remains available.
15. The event hash chain detects invalid structure, broken links, partial changes, and mismatch with an external checkpoint. It cannot detect a fully rewritten internally consistent history+head without an independently retained checkpoint.
16. `drift status` is read-only and reports `clean|detected|unavailable|invalid`; it never repairs state.
17. Control Center schema v4 is copy-only/status-only. Its new command projection is limited to `hellodev host status`, `hellodev policy status`, and `hellodev drift status`; no execution endpoint exists.
18. No Bootstrap/global installer, system/shell/Cursor/Codex config mutation, UI execution, upstream patch, merged database, autonomous write, or Core model invocation is introduced.

## Preserved 0.10.1 and earlier decisions

1. The three-minute path is `open -> next -> do`; `next` has exactly one primary command and optional finished-work efficiency metadata never competes with safety/recovery.
2. `optimize status|plan|reflect|proposals` and the 0.10 schema remain compatible. There is still no `optimize apply` command.
3. `optimize reflect` alone persists bounded DecisionTrace/ReflectionReport records and optional EvolutionProposals. Proposal generation remains `applyAllowed=false`; 0.11 policy evolution is a separate verified workflow.
4. Standalone `usage record` remains `operator-report`/`asserted`/`externally-reported; not host-verified`. A convincing source label cannot create trust or exactness.
5. Deep reflection remains eligibility metadata for an external host, never a Core model call. It requires a deterministic anomaly and positive explicitly linked reported total, capped by `min(500,floor(total*0.05))`.
6. WorkItem stores a safe pointer/fingerprint, LessonProposal stores a lesson digest, and EvidenceLink verifies execution-time typed evidence. Native task/lesson/memory bodies remain upstream-owned.
7. Memory remains advisory; external and policy writes require explicit confirmation; Trellis gates do not automatically drive the HelloDev lifecycle.
8. Missing additive stores are not eagerly created by read-only inspection. Legacy 0.8/0.9/0.10.x project state remains nondestructively readable.

## Verified baseline evidence

| Baseline | Evidence |
|---|---|
| 0.9.0 F2 | 104/104 full tests, disposable real Trellis + fake public stdio MCP continuity matrix, isolated wheel and read-only Control Center smoke. |
| 0.10.0 optimization | 82/82 fast and 114/114 full; deterministic reflection/proposal/privacy matrix and disposable adapter path. |
| 0.10.1 disclosure | 87/87 fast and 119/119 full; daily/recovery/advanced disclosure matrix, authority-sensitive source comparison, isolated wheel and schema-v3 Control Center smoke. |

These are inherited release facts recorded in the root development ledger and preserved release directories. Every later source change still requires the current release gate.

## Release gate for source changes

| Question | Required resolution |
|---|---|
| Does the full regression pass after the 0.11 additions? | Run fast and full verification; record exact counts. |
| Does the closed loop hold in a disposable project? | Run `EVOLUTION_DEMO.md`, including stdin, cancel, exhaustion, negative/tamper/late/unavailable cases. |
| Are canary/commit/revert approvals truly independent and recoverable only by exact receipt? | Run action-hash, replay, mismatch, already-appended/interrupted-append, and cross-process tests. |
| Does the ledger claim match its real trust boundary? | Verify individual tamper and external checkpoint mismatch; retain the full-rewrite limitation in all docs/UI. |
| Is the UI still non-executable? | Run authenticated/unauthenticated schema-v4 smoke and assert exact `uiCapabilities` plus status-only commands. |
| Is the artifact reproducible and independent? | Snapshot verify, no-cache wheel, hashes, fresh venv, separate `outputs/hellodev-core-releases/0.11.0/`. |

## Relevant but non-blocking gaps

| Topic | Current boundary |
|---|---|
| Provider-verified usage | Core can bind a host assertion to an envelope, but cannot authenticate provider tokenizer receipts. Counts remain host-asserted or unavailable. |
| External checkpoint service | `--expected-head` accepts an operator/host-retained checkpoint; Core does not publish or witness heads remotely. |
| Complete-chain attacker | A writer able to replace the full event history and local head can create another internally valid chain absent the external checkpoint. |
| Nocturne namespace/domain portability | Public stable values remain installation-specific; explicit configuration and narrow allowlists continue. |
| Host runtime enforcement | Core emits ceilings and validates reported results; arbitrary external host scheduling/spawn enforcement remains the host's responsibility. |

## Deliberately deferred product work

| Topic | Why deferred |
|---|---|
| Bootstrap/global installation and host config editing | Would mutate user/system state and needs a separate installer/security contract. |
| Dashboard execution | Would expand approval, secret, adapter, and policy-write attack surfaces; Control Center remains copy-only. |
| Remote transparency/witness service | Requires infrastructure, identity, retention, and availability design beyond the local CLI. |
| Provider-attested token collection | Requires a provider-specific authenticated receipt contract; strings supplied by a caller are not evidence. |
| WorkItem/Lesson body synchronization | Pointer/digest ownership is deliberate; copying bodies would create a second truth store. |
| Trellis gate automatically driving lifecycle | Would couple two state machines and needs a reviewed reconciliation contract. |
| Worktree orchestration | Not in the validated common Trellis surface. |
| Autonomous Nocturne writes | Conflicts with explicit write confirmation and evidence requirements. |
| Multi-project executable dashboard | Large authority/UI surface without improving the core daily contract. |
| Codex plugin/Marketplace/hooks | Standalone CLI remains the active product source. |
| Trellis/Nocturne database merge | Conflicts with independent authority and upgrade boundaries. |

## Confidence and classification

- **Fact — full source read:** the HostEnvelope, completion, policy-ledger, and drift contracts above were checked in `host_bridge.py`, `policy_evolution.py`, `drift.py`, and `cli.py`.
- **Fact — behavior verified by existing tests:** primary paths and fail-closed behavior are represented in `test_host_bridge.py`, `test_policy_evolution.py`, `test_v11_cli.py`, atomicity tests, and dashboard tests. Artifact-specific results are recorded outside this orientation file.
- **Relevant but non-blocking:** provider verification, remote checkpointing, stable Nocturne namespaces, and host runtime enforcement.
- **Background/deferred:** executable UI, global bootstrap, worktree, database merge, and Codex plugin packaging.

No open question permits weakening authorization, evidence, privacy, source-of-truth, or standalone boundaries by assumption.
