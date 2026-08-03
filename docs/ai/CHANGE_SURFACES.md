# HelloDev Core change surfaces

Last refreshed: 2026-07-31
Scope: HelloDev 0.20.9 Acceptance Integrity and Atomic Closure

## 0.20.9 change surface

| Change goal | Primary source | Required tests | Preserved boundary |
|---|---|---|---|
| Bind original requirements | `acceptance.py`, `project.py`, `application.py`, `cli.py` | `test_v209_acceptance_integrity.py` | Explicit project-relative UTF-8 source only; no transcript scraping, symlinks, absolute paths or silent replacement. |
| Enforce wide strict completeness | `acceptance.py`, ChangeSet projection | v0.20.9 wide-change regression plus inherited guided acceptance tests | Threshold is conservative and affects closure, not small-task intake. |
| Make closure invariant uniform | `application.py`, `lifecycle.py`, Trellis bridge/receipts | v0.20.9 bypass regression plus v0.20.8 completion tests | Recoverably ordered fail-closed writes; no cross-file ACID claim and no native authority takeover. |
| Project sanitized integrity | `dashboard.py`, Dashboard assets, resume/onboarding | Dashboard/privacy and CLI regressions | Raw text, source path and digest stay out of UI; six MCP tools and six-field default open remain unchanged. |

## 0.20.8 change surface

| Change goal | Primary source | Required tests | Preserved boundary |
|---|---|---|---|
| Change task-set identity | `adapters/trellis.py`, component task operations | `test_v208_measured_overhead.py`, Trellis intent/component tests | Files and symlinks are not tasks; prepared and executed digests remain identical. |
| Change host command identity | `verification.py`, routing/action projections | v0.20.8 plus progressive verification/reuse tests | Canonicalization is allowlisted; shell syntax fails safe; evidence remains host-asserted. |
| Change closure disclosure or batches | `application.py`, `cli.py`, `verification.py` | v0.20.8 CLI/atomicity plus acceptance/resume tests | Plan may tighten; 1-16 results are all-or-nothing; Core does not execute or store output. |
| Change Trellis quality projection | `trellis_bridge.py` | v0.20.8 completion plus bridge/privacy tests | Merge by verification id; hashes only; never overwrite user/Trellis `quality.json`. |

## 0.20.7 change surface

- `resume.py`, `application.py`, and `gates.py`: authoritative intake action and daily/closure identity gates.
- `adapters/trellis.py`, `trellis_bridge.py`, and `application.py`: one-operation Trellis create/select/start/bind path with ledger replay and no native fallback.
- `facade.py`, `cli.py`, `mcp_gateway.py`, and `onboarding.py`: host instructions consume `open/next` actions directly and do not substitute `do plan` or native Trellis initialization.
- `dashboard.py` and `dashboard_assets/`: schema 23 / Control Center 3.3 sanitized integrity projection.
- Package/component metadata, public docs, release checklist, and regression tests: version and contract alignment.

The source changes do not add an MCP tool, execute project tests, authorize an adapter implicitly, persist raw task bodies, install a plugin, or modify user configuration.

## Historical 0.20.6 change surface

| Surface | Files | Intended invariant |
|---|---|---|
| Runtime discovery | `trellis_execution.py` | Valid package scripts outrank weak directory-name evidence; Python remains supported through explicit manifests/config or bounded Python tests; ambiguous mixed roots fail closed. |
| Ordered verification | `acceptance.py`, `verification.py` | Project a bounded ordered list, one runnable command at a time; require every current-snapshot step and invalidate coverage when the relevant snapshot changes. |
| Next routing | `resume.py` | Never attach an executable `action` when `runRequired=false` or an unchanged failure is blocked; `next.command` and action agree. |
| Compatibility | CLI/MCP/Dashboard/docs/version/tests | Preserve six MCP tools, six-field default `open`, old verification session/snapshot routes, Trellis authorization/authority, host-asserted labels and no raw output/token estimates. |

Product source changes start only after this orientation update and the root progress ledger records 0.20.6 as in progress.

## 0.20.5 change surface

| Change | Primary files | Required proof |
|---|---|---|
| Atomic current-snapshot host attestation | `verification.py`, `application.py`, `routing.py`, `cli.py`, `resume.py` | One post-command call records host-asserted evidence without a session; stale/contradictory evidence still fails; session and legacy snapshot paths remain compatible; HelloDev never executes the command. |
| Compact Agent action contract | `resume.py`, `application.py`, onboarding/quick-start guidance | Missing verification returns one bounded action with host command and exact success/failure receipt commands; ordinary lifecycle decisions discourage help/status probing; default `open` retains exactly six top-level fields. |
| Deferred automatic usage sync | `application.py`, `usage_collector.py`, usage tests | Default `open` and ordinary `do` never parse an in-flight rollout; verbose open and explicit sync still collect completed turns exactly; unsupported hosts stay unavailable and no token estimate is introduced. |
| Nocturne technical-memory recall | `knowledge_flows.py`, `intelligence.py`, application/CLI recall execution | Default domain is a valid bounded technical domain; package/runtime terms enrich one query without persisting it; explicit domain/query remains supported; zero accepted items disclose a bounded reason without automatic retries. |
| Version and compatibility | metadata, Dashboard/docs/tests | Version 0.20.5; exactly six MCP tools; current stores migrate nondestructively; focused, fast/full and isolated-wheel gates pass. |

## 0.20.4 change surface

| Change | Primary files | Required proof |
|---|---|---|
| Trellis auto-selection or completion | `task_alignment.py`, `application.py`, `project.py` | Unrelated sole task is not bound; explicit/aligned/created binding is attested; unattested legacy mismatch cannot complete. |
| Small-task verification reuse | `verification.py`, `trellis_execution.py`, `acceptance.py`, `resume.py` | Same snapshot/equal-or-stronger evidence suppresses one redundant standard check; changed snapshot and strict work remain missing. |
| TypeScript impact | `typescript_impact.py`, `guided_acceptance.py`, `trellis_execution.py` | Count-only exported declaration references; bounded repositories fail advisory; wide impact only escalates. |
| Accelerator/provider claims | `repository_tools.py`, Dashboard | Installed command remains `available-not-active`; no MCP connection or execution claim. |
| Version/UI schema | package metadata, component lock/schema, Dashboard, docs/tests | Version 0.20.4, Dashboard schema 20, Control Center 3.0, exact six MCP tools. |

## 0.20.3 guided acceptance surface

- Guided-mode or blocker changes require `test_v203_guided_acceptance.py` plus 0.20.1/0.20.2 acceptance continuity, progressive verification, Dashboard and six-field `open` regressions.
- Python impact changes must preserve bounded repository snapshots, baseline subtraction, import/assignment alias handling, parse-failure disclosure and the no-path/no-symbol/no-source output boundary.
- ChangeSet schema changes must keep schema-1 reads non-destructive, validate bounded SHA-256 lists, refuse symlinks and use the existing atomic state write.
- Verification diversity is diagnostic over the active WorkItem; it must not change exact current-snapshot reuse, execute tests, or upgrade host assertions to provider-signed evidence.

| Change goal | Primary source | Required tests | Documentation / real checks |
|---|---|---|---|
| Change guided acceptance routing | `guided_acceptance.py`, `acceptance.py`, `resume.py`, `application.py` | `test_v203_guided_acceptance.py`, v0.20.1/v0.20.2 flow and default-open shape | `lite/guided/strict` remains deterministic; quality is separate from acceptance coverage; both `check` and `finish` fail closed on active blockers. |
| Change Python override impact | `python_impact.py`, `changesets.py` | Bottle-like same-file and imported-alias cases, pre-existing issue, legacy baseline and privacy regressions | Analyze in memory only; persist hashes/counts only; do not claim an LSP, full type graph or cross-language coverage. |
| Change evidence diversity | `verification.py`, `dashboard.py`, Dashboard assets | multi-snapshot repeat test plus Dashboard schema/privacy tests | Aggregate completed WorkItem history while current reuse remains snapshot-bound; retain `sourceTrust=host-asserted`. |

## 0.20.2 component protocol surface

- Protocol changes require adapter, distribution, recovery and privacy tests.
- Trellis bridge writes must preserve canonical task fields, atomicity, digest guards and upstream workflow authority.
- Nocturne receipt changes must preserve read-before-write, namespace isolation, idempotent replay and content-free state.
- Identity changes require synchronized lock, bundle schema, notices and corresponding source.

0.19.7 preserves Trellis authority and the six-tool MCP surface while adding bounded Python symbol retrieval, optional Serena discovery, and escalation-only semantic impact.

| Change goal | Primary source | Required tests | Documentation / real checks |
|---|---|---|---|
| Change semantic Context Plane retrieval | `context_runtime/semantic.py`, `planner.py`, `briefs.py`, `repository_tools.py` | `test_v197_semantic_context.py` plus v0.16/v0.19.2 budget, cursor, privacy and efficiency regressions | AST parsing runs only for explicit symbol-shaped queries; lexical fallback remains complete; no query, symbol, path or source is persisted; Serena discovery never claims MCP connectivity or executes external code. |
| Change semantic verification impact | `changesets.py`, `context_runtime/semantic.py`, `trellis_execution.py` | v0.19.7 wide-impact escalation plus v0.19.6 adaptive routing and verification reuse regressions | Semantic impact is advisory and escalation-only; parse failure cannot lower a level; output exposes counts only and never satisfies a Trellis gate. |
| Change adaptive Trellis risk or command selection | `trellis_execution.py`, `verification.py`, `resume.py`, `application.py`, `dashboard.py`, host guidance | `test_v196_adaptive_trellis_execution.py` plus progressive-verification, facade, status-size, Dashboard and MCP regressions | Read only bounded safe task metadata; invalid metadata fails closed; recommend exactly one host check; exact success reuses, unchanged failure does not loop; never execute tests, write `.trellis/`, expose task bodies, satisfy a native gate, or add an MCP tool. |
| Change unified facade or native escape disclosure | `facade.py`, `resume.py`, `gates.py`, `application.py`, `dashboard.py`, onboarding/MCP guidance | `test_v195_unified_facade.py` plus task continuity, gate, host-rule and Dashboard regressions | Daily next/recovery stays in HelloDev; Trellis remains authoritative; generic escape count covers only HelloDev receipts; external direct CLI visibility stays unavailable; no adapter call during projection. |
| Change request-level repository reuse or lazy status | `context_runtime/native.py`, `application.py`, `changesets.py`, `verification.py` | `test_v194_end_to_end_efficiency.py` plus ChangeSet/verification stale-evidence suites | Reuse only immutable snapshots inside one synchronous read request; never span write intents; absent state may skip inventory but existing evidence must remain current-bound. |
| Change runtime usage batch persistence | `governance.py`, `usage_collector.py`, `efficiency_cycles.py` | usage collector/reflection suites plus v0.19.4 one-load/one-write regression | One lock/load/atomic write per selected batch; validate all candidates before mutation; preserve identical-receipt idempotency, same-scope conflict rejection, stable ids and twenty-turn reconciliation. |
| Add/change progressive verification | `verification.py`, `application.py`, `routing.py`, `cli.py`, `project.py` | v0.18 plan/record/reuse/failure/tamper/privacy matrix plus daily CLI/MCP regression | Command is hashed, repository snapshot is content-bound, unchanged success alone is reusable, unchanged failure is blocked, record path is host-asserted/advisory and never executes shell or satisfies Trellis gate. |
| Change repository-bound gate evidence | `contracts.py`, `context_runtime/native.py`, `gates.py`, `receipts.py` | gate current/stale tests with source mutation, old receipt compatibility, Trellis validate/reconcile regression | Receipt binding must include repository snapshot; current validation recomputes the binding; source mutation invalidates evidence without deleting history or mutating Trellis. |
| Change unified task kickoff or current-task projection | `experience.py`, `application.py`, `routing.py`, `cli.py`, `contracts.py` | `test_v17_usability.py` plus lifecycle/WorkItem/Trellis approval regressions | Preserve legacy commands and state stores; one active goal is idempotent; ambiguous Trellis tasks fail closed; Trellis creation keeps prepare/approve and same-command continuation. |
| Change automatic Context Plan | `experience.py`, `context_policy.py`, `context_runtime/` | v0.17 bounded-plan tests plus v0.16 context budget/privacy matrix | Plan before repository read, fixed bounded budget, no goal/source persistence, no adapter/model call, and an exact copyable command. |
| Add/change native Context Plane contracts | `context_runtime/contracts.py`, `native.py`, `planner.py`, `cursor.py` | v0.16 root/symlink/encoding/search/ranking/budget/cursor tests | Keep Core dependency-free, read-only and root-bound; stable ordering, bounded scans, no raw-content persistence, deterministic stale-cursor failure. |
| Change Context Plane focus/session cache | `context_runtime/contracts.py`, `native.py`, `planner.py`, `cursor.py`, `briefs.py` | `test_v192_context_efficiency.py`, `test_v194_end_to_end_efficiency.py` plus v0.16 cursor/privacy regression | Focus requires explicit full package identity and never escapes the project root; ordinary domain terms stay project-wide; continuation hit performs no snapshot/rank; cache loss reconstructs; TTL/count/result/per-session and aggregate bytes remain bounded. |
| Change Context Plane integration | `briefs.py`, `application.py`, `mcp_gateway.py`, `capabilities.py`, `audit.py`, `dashboard.py` | v0.16 integration plus inherited context/MCP/Dashboard/privacy suites | Preserve six tools and `open -> next -> do`; source items carry path/line/hash/completeness; Dashboard remains read-only and filters code text. |
| Change optional repository accelerator | `repository_tools.py`, Context Plane backend registry, `integrations.py` | native-only and external-unavailable conformance tests | Native is complete without FastCtx. Discovery is not connectivity or authorization; never auto-install, execute, register or mutate host config. |
| Add/change component manifest or resolver | `components.py`, packaged manifest/notices, `capabilities.py` | v0.14 manifest/runtime negatives plus cache-staleness tests | Reject traversal, absolute paths, symlinks/reparse points, case collisions, unknown fields, missing/extra controlled files, size/hash/version/license/platform mismatch before spawn. |
| Change Core/bundle licensing metadata | `pyproject.toml`, `LICENSE`, component lock, `THIRD_PARTY_NOTICES.md`, bundle `LICENSES`/SBOM/source materials | package-data checks, manifest/license lock checks, release-boundary scan | Core MIT applies only to Core source/wheel; Trellis AGPL-3.0-only, Nocturne MIT, runtimes and dependencies retain their own terms. Hash matching is not legal sign-off. |
| Change bundled Trellis launch | `components.py`, `adapters/trellis.py`, application/CLI binding helpers | v0.14 component tests, Trellis intents, approval identity tests | Bundle command prefix and every file-backed entry point are execution-bound; project `.trellis/` remains the workflow authority and is never merged into `.hellodev/`. |
| Change bundled Nocturne launch/data placement | `components.py`, `nocturne_runner.py`, `adapters/nocturne.py`, `project.py` | v0.14 stdio/config/data isolation tests plus knowledge/Saga security regression | Immutable payload and writable data root stay separate; no live DB/config/snapshot enters the bundle; memory remains advisory and all writes remain confirmed. |
| Change setup/onboard | `components.py`, `onboarding.py`, `command_rendering.py`, `project.py`, `integrations.py`, `cli.py` | idempotency, Core/bundle mode, preflight/conflict, path/reparse, legacy-project and project-boundary tests | Explicit command may write only the selected HelloDev home and project-scoped host paths; Core must not call bundle setup or invent Nocturne; never modify user-level host config, PATH, registry, shell profile, or an existing upstream data store. |
| Change platform bundle build/release | `bundle_builder.py`, `scripts/build_unified_bundle.py`, `scripts/verify_unified_bundle.py`, CI, release docs | reproducible fixture archive plus exact offline archive smoke | 0.14 release claim is Windows x86_64 only; verify exact archive after build, include source/notices/licenses/SBOM, and do not publish from ordinary CI. |
| Change daily application behavior | `application.py`, `routing.py`, domain modules | `test_v13_gateway.py`, F1/security/full regression | CLI and MCP call the same root-bound client; no cross-call authorization/identity cache; exact result shapes remain compatible. |
| Change MCP tools or SDK range | `mcp_gateway.py`, `pyproject.toml`, `ci.yml` | `test_v13_mcp.py`, base/no-extra import and isolated stdio smoke | Exactly six tools; one root; verified official `mcp==1.28.1`; no generic adapter/policy/argv surface. |
| Change Codex/Cursor/Antigravity snippet rendering/checking | `integrations.py`, CLI parser | v13 integration plus `test_v193_antigravity.py` | `show/check` remain read-only and do not inspect or mutate host config; preserve exact current-environment launch and approval warning. |
| Change project host onboarding | `onboarding.py`, `command_rendering.py`, `integrations.py`, `project.py` | v14 conflict/preflight/idempotency, clean-PATH continuation and v0.19.3 Antigravity tests | `onboard` may explicitly merge project-level Cursor/Antigravity config and rules or create project Codex config; it must never write user-level host configuration, `~/.gemini`, or overwrite a conflicting entry. Selected host metadata controls truthful automatic usage attribution. |
| Change PyPI publication | `publish.yml`, `verify_release_version.py` | static workflow tests plus exact artifact smoke | Release-only, protected `pypi` environment, publish-job-only OIDC, no rebuild or API token. |
| Add/change `open`, `next`, or `do` grammar | `cli.py`, `routing.py`, `application.py` | `test_f1_cli.py`, `test_routing.py`, current-version intent tests | Three-minute guide stays `open -> begin -> next -> do`; next keeps one primary command; additive intents remain inside the six-tool MCP face and unknown fields fail closed. |
| Change progressive efficiency disclosure | `resume.py`, `efficiency_cycles.py`, `optimization.py`, `routing.py` | routing finished/active/safety/quiet/invalid-state matrix | Safety/recovery first; only finished may show one bounded read-only cycle/optimization hint; no model/adapter/apply. |
| Change context intent or budget | `context_policy.py`, `briefs.py`, `context_runtime/` | `test_context_policy.py`, F1 CLI context cases, v0.16 budget/cursor matrix | README context table; L2 remains opt-in; allocate before rendering and never split a source item or invent token exactness. |
| Change local recall candidates/scoring | `knowledge_flows.py` | `test_knowledge_flows.py` | Preserve bounded bytes/files, source labels, and no raw persistence. |
| Change Nocturne recall execution | `cli.py`, `knowledge_flows.py`, `adapters/nocturne.py` | F1 CLI recall + adapter tests | Test local-only, strict continuation, autopilot allowlist, and broad-scope rejection. |
| Change remember or Saga flow | `knowledge_flows.py`, `sagas.py`, `receipts.py`, `cli.py` | knowledge, receipt evidence, F1 CLI tests | Verify gate/test + human verification; writes never automatic. |
| Change profile semantics | `profiles.py`, `approval.py`, `project.py` | full `test_profiles.py` matrix | README matrix; real strict/trusted trial; check TTL/fingerprint invalidation. |
| Change approval continuation | `approval.py`, `cli.py`, adapters | F1 CLI, atomicity, identity-replacement, and adapter replay tests | All unified continuations remain the same `do` command with exact args; one token succeeds once. |
| Change policy transaction recovery | `transactions.py`, `approval.py`, `policy_evolution.py`, `project.py` | `test_v12_reliability.py`, `test_v121_polish.py`, policy/approval atomicity | WAL precedes consume; phases cannot skip; receipt/WAL response loss and concurrent recover converge without raw token or new approval. |
| Change receipts | `receipts.py` | `test_receipt_evidence.py`, `test_profiles.py` | Update migration contract; preserve hash-only fields and v1/v2 reads. |
| Change Trellis intent mappings | `adapters/trellis.py`, `routing.py` | `test_trellis_intents.py`, routing/F1 tests | Run disposable real-Trellis strict/trusted matrix; generic gateway is not typed evidence. |
| Change project config | `project.py`, `profiles.py`, `optimization.py` | CLI/profile/migration and proposal-staleness tests | Prove legacy projects load without destructive migration; config changes stale prior proposals. |
| Change dashboard/API | `dashboard.py`, `dashboard_assets/*` | dashboard regression/security/privacy tests | Keep loopback/token/Host/Origin controls, schema-v14 currentTask/recovery/experiment/usage/Context Plane/progressive-verification projections, internal task counts in environment details, status-only commands, and read/copy-only API. |
| Change WorkItem/LessonProposal/EvidenceLink contracts | `contracts.py`, `project.py` | `test_contracts.py`, F2 CLI migration/privacy cases | Preserve pointer/hash-only stores, safe native references, and nondestructive 0.8 reads. |
| Change cross-session recovery | `resume.py`, `routing.py`, `cli.py`, `sagas.py` | `test_resume_gates.py`, F2 CLI cross-process cases | Preserve deterministic priority, one suggested command, no adapter calls, and bounded context. |
| Change gate projection/finish policy | `gates.py`, `contracts.py`, `cli.py`, `project.py` | gate unit + F2 CLI strict/suggest matrix | Keep Trellis mutation false; stale fingerprints must invalidate evidence. |
| Change delegation budgets or context envelopes | `delegation.py`, `cli.py` | `test_delegation.py`, F2 CLI malformed/budget cases | Do not spawn agents, persist context, estimate exact tokens, or authorize writes. |
| Change optimize grammar or planning | `cli.py`, `optimization.py`, `context_policy.py` | `test_optimization.py`, optimize CLI cases | Keep plan deterministic/read-only; ceilings are caller declarations; actual usage remains unavailable until an explicit trust-labelled record is linked. |
| Change usage recording/projection | `usage_collector.py`, `governance.py`, `efficiency_cycles.py`, `optimization.py`, `audit.py`, `dashboard.py`, `application.py`, `cli.py` | `test_usage_collector.py`, `test_efficiency_cycles.py`, usage CLI, routing, dashboard privacy tests, current real-rollout parser smoke | Keep manual records asserted and usage.json v1; automatic discovery must bind rollout cwd to the selected root; only runtime-observed exact receipts enter additive fixed windows; explicit selectors remain asserted-runtime; tolerate additive host metadata without relaxing required counter validation. |
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
| Change packaging/version | `pyproject.toml`, `py.typed`, `__init__.py`, component lock/schema, adapter client metadata, dashboard label | v121/v13/v14 package tests, fast + full + isolated base/MCP wheel smoke | README/Quick Start/RELEASE version, Core-only MIT metadata, marker/schema/MCP contents, hashes, separate release copy. |
| Change CI/release automation | `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `scripts/verify.py` | v121/v13/v14 static tests, local fast/full parity | Ordinary CI stays read-only; dependency-free jobs have no pip cache; publish authority exists only in the protected release workflow. |
| Change Demo/examples | `scripts/demo.ps1`, `examples/*`, `docs/CASE_STUDY.md` | `test_v121_oss.py`, isolated wheel demo smoke | Keep zero-upstream and network-free; do not fake crashes or claim unverified production results. |
| Change public OSS narrative | `README.md`, `docs/QUICK_START.md`, `docs/WHY_HELLODEV.md`, `CONTRIBUTING.md` | link/version/privacy scans | GitHub source is published; do not advertise PyPI availability or a GitHub Release before each external publication is independently verified. |

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
- The standalone Control Center schema v12 uses a trust-dependent usage display basis, exposes only bounded usage/cycle/recovery/experiment/checkpoint/Context Plane metrics, and keeps filtered host/policy/drift status copy-only. It exposes no query, repository path, source text, raw context, approval token, policy patch, cycle hashes, complete/stage/cancel/canary/commit/revert or action API.
- Explicit 0.14 bundle setup verifies the prepackaged runtime and creates only the selected HelloDev home data/marker state. Unattended global installation, PATH/registry/shell changes, user-level Codex/Cursor config mutation, and UI execution remain outside the product.

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
21. For dashboard changes, assert schema v12, trust-dependent display basis, filtered cycle/usage/recovery/experiment/Context Plane fields, exact `uiCapabilities`, status-only commands, absence of query/path/source text, and absence of any action endpoint.
22. For collector changes, test automatic-vs-explicit trust, project cwd binding, previous-vs-current turn semantics, line-bounded cumulative deltas, complete recursive subagent aggregation, thread/file/line/event/byte bounds, symlink/reparse refusal, missing/incomplete-child no-partial behavior, malformed/regressing/conflicting input, idempotency, additive-store rollback, and forbidden-value scans.
23. For transaction changes, inject failure before WAL write and after every durable phase; prove the same authorization is reusable before WAL or recoverable without raw token after WAL.
24. For Host SDK changes, test protocol negotiation, source/wheel schema loading, pending-metadata privacy, idempotent completion, and unavailable token handling.
25. For checkpoint changes, test matching/divergent/tampered values and preserve the explicit not-tamper-proof wording in CLI, audit, Dashboard, and docs.

## Verification basis

- **Fact — independently verified from source/config:** primary files and contracts were mapped from the current 0.14 component/onboarding implementation, the retained 0.13 application/MCP baseline, package metadata, CI workflow, CLI grammar, and examples.
- **Fact — inferred from tests then checked against implementation:** fail-closed/idempotency/privacy cases map to the named test suites and source validators.
- **Relevant but non-blocking:** provider attestation, external checkpoint service, Linux/macOS platform archives, and public PyPI publication remain host/release concerns rather than completed 0.14 evidence.
