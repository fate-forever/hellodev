# HelloDev Core change surfaces

Last refreshed: 2026-07-17
Scope: HelloDev 0.12.1 reliability hardening, typed SDK packaging, CI/Demo OSS surfaces, and Dashboard schema v7 on the released 0.12.0 baseline

| Change goal | Primary source | Required tests | Documentation / real checks |
|---|---|---|---|
| Add/change `open`, `next`, or `do` grammar | `cli.py`, `routing.py` | `test_f1_cli.py`, `test_routing.py` | Three-minute guide stays `open -> next -> do`; next keeps one primary command. |
| Change progressive efficiency disclosure | `resume.py`, `efficiency_cycles.py`, `optimization.py`, `routing.py` | routing finished/active/safety/quiet/invalid-state matrix | Safety/recovery first; only finished may show one bounded read-only cycle/optimization hint; no model/adapter/apply. |
| Change context intent or budget | `context_policy.py`, `briefs.py` | `test_context_policy.py`, F1 CLI context cases | README context table; L2 remains opt-in. |
| Change local recall candidates/scoring | `knowledge_flows.py` | `test_knowledge_flows.py` | Preserve bounded bytes/files, source labels, and no raw persistence. |
| Change Nocturne recall execution | `cli.py`, `knowledge_flows.py`, `adapters/nocturne.py` | F1 CLI recall + adapter tests | Test local-only, strict continuation, autopilot allowlist, and broad-scope rejection. |
| Change remember or Saga flow | `knowledge_flows.py`, `sagas.py`, `receipts.py`, `cli.py` | knowledge, receipt evidence, F1 CLI tests | Verify gate/test + human verification; writes never automatic. |
| Change profile semantics | `profiles.py`, `approval.py`, `project.py` | full `test_profiles.py` matrix | README matrix; real strict/trusted trial; check TTL/fingerprint invalidation. |
| Change approval continuation | `approval.py`, `cli.py`, adapters | F1 CLI, atomicity, identity-replacement, and adapter replay tests | All unified continuations remain the same `do` command with exact args; one token succeeds once. |
| Change policy transaction recovery | `transactions.py`, `approval.py`, `policy_evolution.py`, `project.py` | `test_v12_reliability.py`, `test_v121_polish.py`, policy/approval atomicity | WAL precedes consume; phases cannot skip; receipt/WAL response loss and concurrent recover converge without raw token or new approval. |
| Change receipts | `receipts.py` | `test_receipt_evidence.py`, `test_profiles.py` | Update migration contract; preserve hash-only fields and v1/v2 reads. |
| Change Trellis intent mappings | `adapters/trellis.py`, `routing.py` | `test_trellis_intents.py`, routing/F1 tests | Run disposable real-Trellis strict/trusted matrix; generic gateway is not typed evidence. |
| Change project config | `project.py`, `profiles.py`, `optimization.py` | CLI/profile/migration and proposal-staleness tests | Prove legacy projects load without destructive migration; config changes stale prior proposals. |
| Change dashboard/API | `dashboard.py`, `dashboard_assets/*` | dashboard regression/security/privacy tests | Keep loopback/token/Host/Origin controls, schema-v7 filtered recovery/experiment/usage projections, status-only commands, and read/copy-only API. |
| Change WorkItem/LessonProposal/EvidenceLink contracts | `contracts.py`, `project.py` | `test_contracts.py`, F2 CLI migration/privacy cases | Preserve pointer/hash-only stores, safe native references, and nondestructive 0.8 reads. |
| Change cross-session recovery | `resume.py`, `routing.py`, `cli.py`, `sagas.py` | `test_resume_gates.py`, F2 CLI cross-process cases | Preserve deterministic priority, one suggested command, no adapter calls, and bounded context. |
| Change gate projection/finish policy | `gates.py`, `contracts.py`, `cli.py`, `project.py` | gate unit + F2 CLI strict/suggest matrix | Keep Trellis mutation false; stale fingerprints must invalidate evidence. |
| Change delegation budgets or context envelopes | `delegation.py`, `cli.py` | `test_delegation.py`, F2 CLI malformed/budget cases | Do not spawn agents, persist context, estimate exact tokens, or authorize writes. |
| Change optimize grammar or planning | `cli.py`, `optimization.py`, `context_policy.py` | `test_optimization.py`, optimize CLI cases | Keep plan deterministic/read-only; ceilings are caller declarations; actual usage remains unavailable until an explicit trust-labelled record is linked. |
| Change usage recording/projection | `usage_collector.py`, `governance.py`, `efficiency_cycles.py`, `optimization.py`, `audit.py`, `dashboard.py`, `cli.py` | `test_usage_collector.py`, `test_efficiency_cycles.py`, usage CLI, routing, dashboard privacy tests | Keep manual records asserted and usage.json v1; only automatic runtime-observed exact receipts enter additive fixed windows; explicit selectors remain asserted-runtime. |
| Change twenty-turn window/advice | `efficiency_cycles.py`, `resume.py`, `cli.py` | 19/20/21/40, retry, trust exclusion, tamper, advice priority and disclosure tests | Fixed non-overlapping insertion-order windows; deterministic allowlist; additive hash-bound sidecar; policy apply/model/adapter all forbidden. |
| Change reflection findings/recommendations/trends | `optimization.py` | full `test_optimization.py`, malformed-store/tamper cases | Keep enums/commands allowlisted, reflection idempotent, trend counts internally consistent, raw content absent, adapter/model/apply false. |
| Change deep-reflection eligibility | `optimization.py` | anomaly/no-usage/zero/positive-total cap matrix | Require anomaly and positive linked reported total; cap exactly `min(500,floor(total*0.05))`; Core makes no model call. |
| Change EvolutionProposal rules | `optimization.py`, `project.py`, `policy_evolution.py` | repeated-evidence, stale-fingerprint, tamper and policy-stage tests | Only two tighten-only integer targets; three report evidence; human review; no direct optimize apply; separate stage remains non-effective. |
| Change HostEnvelope fields/bindings | `host_bridge.py`, `host_sdk.py`, `py.typed`, `schemas/*.json`, `context_policy.py`, `delegation.py`, `optimization.py`, `policy_evolution.py` | `test_host_bridge.py`, `test_v11_cli.py`, `test_v12_reliability.py`, `test_v121_polish.py` | Prepare must be bounded; pending state is sanitized; exact inspection/reconcile never reconstructs context; SDK/schema/protocol stay compatible. |
| Change host-result ingestion | `host_bridge.py`, `optimization.py`, `governance.py`, `cli.py` | host stdin/stale/tamper/conflict/idempotency/privacy/late/usage tests | Prefer strict 512-KiB `{envelope,result}` stdin; store sanitized result only; usage host-asserted/unavailable; no transcript/model/raw context; host traces never gate evidence. |
| Change evolution policy lifecycle | `policy_evolution.py`, `transactions.py`, `approval.py`, `receipts.py`, `cli.py` | `test_policy_evolution.py`, `test_v11_cli.py`, `test_v12_reliability.py` | Canary v2 requires equal bounded baseline/current samples; commit rejects insufficient/regressed evidence; transactional recovery remains exact. |
| Change policy ledger/hash chain or checkpoint | `policy_evolution.py`, `checkpoints.py`, `cli.py`, `state_lock.py` | structural tamper, broken-link/head, strict digest/file bound/CI mismatch tests | Append-only semantics; optional CI nonzero mismatch; do not overclaim full-rewrite resistance or local tamper-proofing. |
| Change drift projection | `drift.py`, `host_bridge.py`, `policy_evolution.py`, `capabilities.py`, `contracts.py` | clean/detected/unavailable/invalid and bounded-window tests | Read-only; distinguish structural invalidity from runtime warnings; never auto-repair. |
| Change audit/doctor recovery hints | `audit.py`, `cli.py` | F2 audit/privacy and doctor cases | Export ids, pointers, hashes, states, and counts only; no raw task/lesson/adapter content. |
| Change project-local state mutation/locking | `state_lock.py`, `contracts.py`, `receipts.py`, `sagas.py`, `governance.py`, `optimization.py` | `test_f2_atomicity.py`, approval atomicity, full regression | Preserve per-store cross-process serialization, symlink refusal, unique ids, idempotency, and atomic replacement. |
| Change packaging/version | `pyproject.toml`, `py.typed`, `__init__.py`, adapter client metadata, dashboard label | v121 OSS, fast + full + isolated wheel smoke | README/RELEASE version, marker/schema wheel contents, hashes, separate release copy. |
| Change CI/release automation | `.github/workflows/ci.yml`, `scripts/verify.py` | `test_v121_oss.py`, local fast/full parity | Preserve exact trigger/matrix/concurrency/retention semantics; no publish credentials or external mutation. |
| Change Demo/examples | `scripts/demo.ps1`, `examples/*`, `docs/CASE_STUDY.md` | `test_v121_oss.py`, isolated wheel demo smoke | Keep zero-upstream and network-free; do not fake crashes or claim unverified production results. |
| Change public OSS narrative | `README.md`, `docs/QUICK_START.md`, `docs/WHY_HELLODEV.md`, `CONTRIBUTING.md` | link/version/privacy scans | Do not advertise PyPI/GitHub release before external publication is verified. |

## Cross-cutting invariants

- Root `.trellis/`, when present, is project workflow authority. HelloDev state remains under `.hellodev/`.
- `routing.decide` and `context_policy.suggest` are deterministic and do not execute adapters.
- A local strong recall hit stops external search unless `--also-memory` is explicit.
- Memory output is advisory; it cannot authorize execution or overwrite repository facts.
- Profile relaxation covers reads only. Every Trellis/Nocturne external write and every effective policy transition requires exact confirmation; non-effective policy stage/cancel remains the documented exception.
- Approval tokens, raw output, raw query/lesson/memory content, and verification text do not enter receipts.
- Optimization records cannot authorize execution, satisfy evidence, change profiles/lifecycle/Sagas, or write Trellis/Nocturne.
- `usage record` is always an operator assertion. Automatic Desktop collect/sync may emit `runtime-observed`; explicit selectors emit `asserted-runtime`. Both require a fully bounded completed Codex turn and use `measurement=exact` + `attestation=none`; only runtime-observed enters ReflectionCycle, and neither authorizes operations.
- The collector never claims a final value for the reply currently being generated, never calls runtime-observed provider-verified, and never persists prompt/response/raw event/thread/turn/session-path content.
- Missing/incomplete descendant rollout, absent interval snapshot, unsafe path, malformed event, cumulative regression, or same-turn conflict fails closed without partial persistence; repeated identical collection is idempotent.
- `optimize status|plan|proposals` are read-only. `reflect` may persist only bounded local traces/reports/non-self-applicable proposals and reports empty adapter/model calls.
- Evolution targets are limited to `retry.maxAttempts` and `delegation.effectiveMaxAgents`, tighten-only, and stale on policy/rule/config changes. Optimization never applies them directly; only the separate staged/approved/verified 0.11 policy workflow can commit one.
- Host preparation is read-only and grants no execution/evidence authority. Completion validates every current binding and stores no transcript/model/raw context.
- Host-completion usage is `host-asserted` or `unavailable`, never provider-verified or inferred as zero. Late completion is not current canary evidence.
- Stage/cancel do not change effective policy; cancel is append-only and staged-only. Canary, commit, and revert each require an exact action-bound approval/receipt; approvals cannot be reused across phases.
- Canary tightening stops when its bounded non-late same-head turn sample is exhausted; effective policy returns to committed, public observedTurns is clamped, and evaluation uses the first N records. Completion locking prevents concurrent pre-exhaustion overshoot; later records do not extend evidence.
- The local policy hash chain detects broken/partial edits, not an internally consistent full rewrite without an external checkpoint.
- Drift inspection is bounded/read-only and never repairs invalid stores.
- Daily, recovery, and advanced surfaces stay distinct: optimization is never a required daily step.
- Efficiency disclosure never changes the primary next command and is suppressed by active work plus every safety/recovery priority.
- Missing, insufficient, or ready optimization state is quiet and must not create optimization/acknowledgement state during next/open/resume reads.
- Corrupt/malformed/future advisory optimization or usage state is omitted only from optional finished next/resume disclosure; explicit advanced diagnostics remain fail-closed.
- Development source, release copies, and installed runtime caches remain separate real directories.
- The standalone Control Center schema v7 uses a trust-dependent usage display basis, exposes only bounded usage/cycle/recovery/experiment/checkpoint fields, and keeps filtered host/policy/drift status copy-only. It exposes no raw context, approval token, policy patch, cycle hashes, complete/stage/cancel/canary/commit/revert or action API.
- Bootstrap/global installation, Codex/Cursor config mutation, and UI execution remain outside the product.

## Review checklist for an F1/F2/optimization/disclosure/evolution change

1. Identify whether the change affects local state, an external read, or an external/policy write.
2. Confirm its deterministic route and canonical context intent.
3. Exercise strict mode first.
4. If a read may be relaxed, test trusted-local and autopilot fail-closed boundaries.
5. Verify the receipt's `profileUsed`, `authorizationMode`, and optional lease digest.
6. Search project state for forbidden raw values used by the test.
7. Run `python scripts/verify.py --scope fast`; run full verification before release.
8. Update README, demo, release contract, and this map when the public surface changes.
9. For continuity changes, test a fresh 0.8 state, a restarted process, a stale fingerprint, and an unknown/mismatched id.
10. For delegation/audit changes, prove no execution, persistence of context, raw content, or token-exactness claim outside the explicit `usage collect` receipt contract occurs.
11. For optimization reads, prove a missing 0.9 optimization store remains absent and usage remains unavailable rather than zero.
12. For reflection changes, test every enum, idempotency, raw-label privacy, atomic concurrency, anomaly gating, and both deep-reflection caps.
13. For proposal changes, prove three-report evidence, allowlisted tighten-only targets, stale fingerprinting, tamper rejection, and `applyAllowed=false` with no `optimize apply` grammar.
14. Compare Trellis/Nocturne, authorization, evidence, receipt, Saga, and write-confirmation behavior with the immutable 0.9 release; optimization must not evolve those surfaces.
15. For disclosure changes, test finished missing, insufficient, ready, attention, review-due, corrupt, and future-schema states; active lifecycle; every higher-priority recovery branch; resume parity; no file mutation; explicit-diagnostic fail-closed; and the 1 KiB bound.
16. Compare the optimization store/schema and all advanced commands with immutable 0.10.0; disclosure must not create a second plan/policy/acknowledgement system.
17. For HostEnvelope changes, verify whole-envelope/context hashes, all current bindings, TTL/L2/ceiling bounds, grants false, and sanitized pending metadata with no context/body persistence.
18. For completion changes, test strict stdin shape/size/argv exclusion, tamper, stale binding, conflicting replay, exact idempotency, late handling, unavailable tokens, host-asserted labels, privacy, and zero gate authority.
19. For evolution changes, test stage non-effect, staged cancel/idempotency, single active proposal, equal bounded baseline/canary samples, all v2 comparison dimensions, policy violations, clean-drift commit gate, independent approvals, receipt-store preflight, WAL phase recovery, and rejection of a second/arbitrary revert.
20. For ledger/drift changes, test individual event/link/head tamper plus portable checkpoint mismatch; state the full-history-rewrite and local-checkpoint limitations explicitly.
21. For dashboard changes, assert schema v7, trust-dependent display basis, filtered cycle/usage/recovery/experiment fields, exact `uiCapabilities`, status-only commands, and absence of any action endpoint.
22. For collector changes, test automatic-vs-explicit trust, project cwd binding, previous-vs-current turn semantics, line-bounded cumulative deltas, complete recursive subagent aggregation, thread/file/line/event/byte bounds, symlink/reparse refusal, missing/incomplete-child no-partial behavior, malformed/regressing/conflicting input, idempotency, additive-store rollback, and forbidden-value scans.
23. For transaction changes, inject failure before WAL write and after every durable phase; prove the same authorization is reusable before WAL or recoverable without raw token after WAL.
24. For Host SDK changes, test protocol negotiation, source/wheel schema loading, pending-metadata privacy, idempotent completion, and unavailable token handling.
25. For checkpoint changes, test matching/divergent/tampered values and preserve the explicit not-tamper-proof wording in CLI, audit, Dashboard, and docs.

## Verification basis

- **Fact — independently verified from source/config:** primary files and contracts were mapped from the current 0.12.1 modules, package metadata, CI workflow, CLI grammar, and examples.
- **Fact — inferred from tests then checked against implementation:** fail-closed/idempotency/privacy cases map to the named test suites and source validators.
- **Relevant but non-blocking:** provider attestation for token receipts and an external checkpoint service remain host/deployment concerns rather than Core change surfaces; runtime-observed exact completed-turn measurement does not solve attestation.
