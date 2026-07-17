# HelloDev Core change surfaces

Last refreshed: 2026-07-16
Scope: HelloDev 0.11.0 host bridge and verified tighten-only policy evolution on the released 0.10.1 baseline

| Change goal | Primary source | Required tests | Documentation / real checks |
|---|---|---|---|
| Add/change `open`, `next`, or `do` grammar | `cli.py`, `routing.py` | `test_f1_cli.py`, `test_routing.py` | Three-minute guide stays `open -> next -> do`; next keeps one primary command. |
| Change progressive efficiency disclosure | `resume.py`, `optimization.py`, `routing.py` | routing finished/active/safety/quiet/invalid-state matrix | Only finished + `attention|review-due`; missing/quiet/invalid advisory no field/file mutation; one bounded read-only hint; <=1 KiB. |
| Change context intent or budget | `context_policy.py`, `briefs.py` | `test_context_policy.py`, F1 CLI context cases | README context table; L2 remains opt-in. |
| Change local recall candidates/scoring | `knowledge_flows.py` | `test_knowledge_flows.py` | Preserve bounded bytes/files, source labels, and no raw persistence. |
| Change Nocturne recall execution | `cli.py`, `knowledge_flows.py`, `adapters/nocturne.py` | F1 CLI recall + adapter tests | Test local-only, strict continuation, autopilot allowlist, and broad-scope rejection. |
| Change remember or Saga flow | `knowledge_flows.py`, `sagas.py`, `receipts.py`, `cli.py` | knowledge, receipt evidence, F1 CLI tests | Verify gate/test + human verification; writes never automatic. |
| Change profile semantics | `profiles.py`, `approval.py`, `project.py` | full `test_profiles.py` matrix | README matrix; real strict/trusted trial; check TTL/fingerprint invalidation. |
| Change approval continuation | `approval.py`, `cli.py`, adapters | F1 CLI, atomicity, identity-replacement, and adapter replay tests | All unified continuations remain the same `do` command with exact args; one token succeeds once. |
| Change receipts | `receipts.py` | `test_receipt_evidence.py`, `test_profiles.py` | Update migration contract; preserve hash-only fields and v1/v2 reads. |
| Change Trellis intent mappings | `adapters/trellis.py`, `routing.py` | `test_trellis_intents.py`, routing/F1 tests | Run disposable real-Trellis strict/trusted matrix; generic gateway is not typed evidence. |
| Change project config | `project.py`, `profiles.py`, `optimization.py` | CLI/profile/migration and proposal-staleness tests | Prove legacy projects load without destructive migration; config changes stale prior proposals. |
| Change dashboard/API | `dashboard.py`, `dashboard_assets/*` | dashboard regression/security/privacy tests | Keep loopback/token/Host/Origin controls, schema-v4 filtered advanced projection, status-command-only exposure, and read/copy-only API. |
| Change WorkItem/LessonProposal/EvidenceLink contracts | `contracts.py`, `project.py` | `test_contracts.py`, F2 CLI migration/privacy cases | Preserve pointer/hash-only stores, safe native references, and nondestructive 0.8 reads. |
| Change cross-session recovery | `resume.py`, `routing.py`, `cli.py`, `sagas.py` | `test_resume_gates.py`, F2 CLI cross-process cases | Preserve deterministic priority, one suggested command, no adapter calls, and bounded context. |
| Change gate projection/finish policy | `gates.py`, `contracts.py`, `cli.py`, `project.py` | gate unit + F2 CLI strict/suggest matrix | Keep Trellis mutation false; stale fingerprints must invalidate evidence. |
| Change delegation budgets or context envelopes | `delegation.py`, `cli.py` | `test_delegation.py`, F2 CLI malformed/budget cases | Do not spawn agents, persist context, estimate exact tokens, or authorize writes. |
| Change optimize grammar or planning | `cli.py`, `optimization.py`, `context_policy.py` | `test_optimization.py`, optimize CLI cases | Keep plan deterministic/read-only; ceilings are caller declarations, actual usage stays unavailable. |
| Change usage recording/projection | `governance.py`, `optimization.py`, `audit.py`, `dashboard.py` | usage CLI, optimization, dashboard privacy tests | Preserve `operator-report`/`asserted`/not-host-verified labels; never infer trust or exactness from `source`. |
| Change reflection findings/recommendations/trends | `optimization.py` | full `test_optimization.py`, malformed-store/tamper cases | Keep enums/commands allowlisted, reflection idempotent, trend counts internally consistent, raw content absent, adapter/model/apply false. |
| Change deep-reflection eligibility | `optimization.py` | anomaly/no-usage/zero/positive-total cap matrix | Require anomaly and positive linked reported total; cap exactly `min(500,floor(total*0.05))`; Core makes no model call. |
| Change EvolutionProposal rules | `optimization.py`, `project.py`, `policy_evolution.py` | repeated-evidence, stale-fingerprint, tamper and policy-stage tests | Only two tighten-only integer targets; three report evidence; human review; no direct optimize apply; separate stage remains non-effective. |
| Change HostEnvelope fields/bindings | `host_bridge.py`, `context_policy.py`, `delegation.py`, `optimization.py`, `policy_evolution.py` | `test_host_bridge.py`, `test_v11_cli.py` | Prepare must be read-only/bounded; bind root/capability/WorkItem/policies/ledger/expiry/hash; never grant execution/evidence authority. |
| Change host-result ingestion | `host_bridge.py`, `optimization.py`, `governance.py`, `cli.py` | host stdin/stale/tamper/conflict/idempotency/privacy/late/usage tests | Prefer strict 512-KiB `{envelope,result}` stdin; store sanitized result only; usage host-asserted/unavailable; no transcript/model/raw context; host traces never gate evidence. |
| Change evolution policy lifecycle | `policy_evolution.py`, `approval.py`, `receipts.py`, `cli.py` | `test_policy_evolution.py`, `test_v11_cli.py`, approval/receipt atomicity | Stage/cancel non-effective; canary exhausts; canary/commit/revert exact/independent; receipt preflight precedes token use; exact response-loss recovery. |
| Change policy ledger/hash chain | `policy_evolution.py`, `state_lock.py` | structural tamper, broken-link/head, replay, concurrency, external-checkpoint tests | Append-only event semantics; do not overclaim full-rewrite resistance; external checkpoint required for whole-chain replacement detection. |
| Change drift projection | `drift.py`, `host_bridge.py`, `policy_evolution.py`, `capabilities.py`, `contracts.py` | clean/detected/unavailable/invalid and bounded-window tests | Read-only; distinguish structural invalidity from runtime warnings; never auto-repair. |
| Change audit/doctor recovery hints | `audit.py`, `cli.py` | F2 audit/privacy and doctor cases | Export ids, pointers, hashes, states, and counts only; no raw task/lesson/adapter content. |
| Change project-local state mutation/locking | `state_lock.py`, `contracts.py`, `receipts.py`, `sagas.py`, `governance.py`, `optimization.py` | `test_f2_atomicity.py`, approval atomicity, full regression | Preserve per-store cross-process serialization, symlink refusal, unique ids, idempotency, and atomic replacement. |
| Change packaging/version | `pyproject.toml`, `__init__.py`, adapter client metadata, dashboard label | fast + full + wheel smoke | README/RELEASE version, no-cache build, hashes, separate release copy. |

## Cross-cutting invariants

- Root `.trellis/`, when present, is project workflow authority. HelloDev state remains under `.hellodev/`.
- `routing.decide` and `context_policy.suggest` are deterministic and do not execute adapters.
- A local strong recall hit stops external search unless `--also-memory` is explicit.
- Memory output is advisory; it cannot authorize execution or overwrite repository facts.
- Profile relaxation covers reads only. Every Trellis/Nocturne/policy write requires exact confirmation.
- Approval tokens, raw output, raw query/lesson/memory content, and verification text do not enter receipts.
- Optimization records cannot authorize execution, satisfy evidence, change profiles/lifecycle/Sagas, or write Trellis/Nocturne.
- Usage CLI data is an operator assertion, never trusted or exact telemetry; missing/unlinked usage remains unavailable.
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
- The standalone Control Center schema v4 projects numeric/private summaries and filtered host/policy/drift status only. It copies commands but exposes no complete/stage/cancel/canary/commit/revert or action API.
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
10. For delegation/audit changes, prove no execution, persistence of context, raw content, or exact-token claim occurs.
11. For optimization reads, prove a missing 0.9 optimization store remains absent and usage remains unavailable rather than zero.
12. For reflection changes, test every enum, idempotency, raw-label privacy, atomic concurrency, anomaly gating, and both deep-reflection caps.
13. For proposal changes, prove three-report evidence, allowlisted tighten-only targets, stale fingerprinting, tamper rejection, and `applyAllowed=false` with no `optimize apply` grammar.
14. Compare Trellis/Nocturne, authorization, evidence, receipt, Saga, and write-confirmation behavior with the immutable 0.9 release; optimization must not evolve those surfaces.
15. For disclosure changes, test finished missing, insufficient, ready, attention, review-due, corrupt, and future-schema states; active lifecycle; every higher-priority recovery branch; resume parity; no file mutation; explicit-diagnostic fail-closed; and the 1 KiB bound.
16. Compare the optimization store/schema and all advanced commands with immutable 0.10.0; disclosure must not create a second plan/policy/acknowledgement system.
17. For HostEnvelope changes, verify whole-envelope/context hashes, all current bindings, TTL/L2/ceiling bounds, grants false, and no prepare-time store creation.
18. For completion changes, test strict stdin shape/size/argv exclusion, tamper, stale binding, conflicting replay, exact idempotency, late handling, unavailable tokens, host-asserted labels, privacy, and zero gate authority.
19. For evolution changes, test stage non-effect, staged cancel/idempotency, single active proposal, canary sample/TTL/exhaustion, current-head selection, policy violations, clean-drift commit gate, independent approvals, receipt-store preflight before token consumption, exact response-loss recovery, cancelled-stage preservation of the immediate commit rollback target, and rejection of a second/arbitrary revert.
20. For ledger/drift changes, test individual event/link/head tamper plus external checkpoint mismatch; state the full-history-rewrite limitation explicitly.
21. For dashboard changes, assert schema v4, exact `uiCapabilities`, status-only advanced commands, filtered fields, and absence of any action endpoint.

## Verification basis

- **Fact — independently verified from source/config:** primary files and contracts were mapped from the current 0.11 modules and CLI grammar.
- **Fact — inferred from tests then checked against implementation:** fail-closed/idempotency/privacy cases map to the named test suites and source validators.
- **Relevant but non-blocking:** exact provider-token trust and an external checkpoint service remain host/deployment concerns rather than Core change surfaces.
