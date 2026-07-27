# HelloDev Core open questions

Last refreshed: 2026-07-27
Scope: HelloDev 0.19.6 adaptive Trellis execution

Release status, artifact hashes, and immutable evidence belong in the root development ledger and the versioned release report. The checks below are the reusable gate for any source change; this orientation file does not duplicate mutable artifact hashes.

## 0.19.6 decisions and open boundaries

- `quick/standard/strict` is a deterministic safety policy, not a learned risk model. P0/P1, deletion, more than ten changed files, high-risk declared scope, and invalid metadata select strict; docs-only bounded changes select quick; other work selects standard.
- Command discovery is advisory and structured: project `scripts/verify.py` wins, then a Python test shape, then a declared package-manager test script. HelloDev does not execute the command or infer success from stdout.
- Exact success reuse is bound to command hash, scope snapshot, WorkItem, and verification level. It remains host-asserted intermediate evidence and cannot satisfy a Trellis gate.
- The first version does not parse PRD/spec prose, dependency graphs, changed raw paths, flaky-test history, or CI configuration. These are relevant but non-blocking evaluation areas; adding them must preserve privacy and deterministic behavior.
- Real-project time saved by the adaptive policy remains unmeasured. The product may report exact avoided duration from a reused host receipt, but it must not claim a universal efficiency percentage.

## 0.19.5 decisions and open boundaries

- Trellis task/spec/gate remains repository authority. HelloDev owns the daily command facade and pointer/projection state; it does not duplicate Trellis documents or auto-drive both state machines.
- Cursor/Antigravity rules and MCP instructions prohibit routine direct Trellis use. Direct native access remains available only as an advanced compatibility escape hatch when HelloDev reports an unsupported operation.
- `trellis-continue` is not a second recovery path in HelloDev guidance; `hellodev resume` is canonical. Existing upstream commands are not removed or patched.
- Escape-hatch counts include only generic Trellis commands executed through HelloDev and represented by typed receipts. External shell/IDE Trellis calls cannot be observed by local Core and remain explicitly unavailable.
- The facade is guidance plus deterministic HelloDev routing, not host sandbox enforcement. A host can still ignore project rules; stronger enforcement would require host-native policy support and separate evaluation.

## 0.19.4 decisions and open boundaries

- Package focus is explicit: a full normalized package identity may focus a query; cwd, descriptions and ordinary substrings may not. Dependency-graph and semantic ownership inference remain out of scope.
- Request snapshot reuse is synchronous and read-only. Write intents deliberately start outside the session so post-mutation state cannot reuse stale inventory.
- Empty ChangeSet/verification state may skip repository inventory. Once a baseline or evidence record exists, current-snapshot validation remains mandatory and fail-closed.
- Automatic usage synchronization batches persistence but does not weaken receipt validation. The selected turns are parsed before one atomic append; a store conflict rejects the append rather than partially committing it.
- The context budget is a conservative byte envelope over the complete MCP response. It is not a precise host-model token cap, and Agents should not mechanically exhaust continuations.
- Real cross-host latency/token savings remain an evaluation question. 0.19.4 claims bounded local work and tested recall/call-count properties, not a universal percentage speedup.

## 0.19.3 decisions and open boundaries

- Antigravity uses the documented workspace `.agents/mcp_config.json` contract and Markdown rules under `.agents/rules/`. HelloDev does not mutate global `~/.gemini` configuration or invent undocumented rule frontmatter.
- Antigravity onboarding records the selected host so automatic `open`/`do` synchronization cannot import an unrelated Codex rollout. Without a trusted Host SDK usage receipt, Antigravity token and subagent telemetry is `unavailable`, never estimated.
- Trellis has no verified Antigravity-specific initialization flag in the current integration contract. HelloDev therefore uses host-neutral `trellis init --yes` and does not claim deeper native integration.
- Rule activation remains a host UI/workspace setting. HelloDev writes guidance and reports that review/reload is required; it does not automate the Antigravity UI.

## 0.19.2 decisions and open boundaries

- Focus selection is deterministic and fail-closed: nested package/worktree first, then exactly one query-matching package marker, otherwise project root. Dependency-graph and semantic ownership inference remain out of scope.
- Result sessions are process-local accelerators, not durable truth. TTL/count/result/byte eviction or process restart reconstructs from the cursor's root-bound focus and snapshot contract.
- Continuation reuse validates cached file/directory metadata without rescanning/reranking. This preserves stale detection for existing files and directory membership changes; it does not claim filesystem transactions or immunity to adversarial same-metadata rewrites.
- The 1200-token option remains a conservative four-UTF-8-byte envelope unless the outer MCP result meter has a compatible tokenizer. Context Plane does not claim an exact model-token cap.
- Agents should consume the first bounded page and switch to native precise reads when sufficient. Automatically exhausting every continuation remains intentionally unsupported behavior.

## 0.19.0 decisions and open boundaries

- Trellis-native gate completion performed outside HelloDev has no verified stable artifact contract. `unlinkedDetection` is therefore `unavailable`; arbitrary logs and task text are not evidence.
- T0/T1 default to conservative `code` scope; T2 defaults to `project`. Semantic command equivalence and dependency-graph impact analysis remain future work.
- Context Plane bounded scans cannot establish reusable scoped evidence and fail closed.
- Verification sessions are the default continuation, while the 0.18 `--snapshot` path remains a compatibility surface.

Final 0.19 acceptance completed with 216 fast and 256 full tests, two expected environment skips, Python compilation, Dashboard JavaScript syntax and an isolated wheel smoke covering begin, scoped verification session, record/reuse, Dashboard schema 15 and six MCP tools. No publication or installation was performed.

## 0.18.0 historical decisions

1. **Resolved:** gate/test evidence now includes the current native repository snapshot, and current projection recomputes the receipt binding. Source mutation invalidates old evidence without deleting history. _Implemented and regression-tested._
2. `do verify` records host-asserted outcomes and durations only after the host actually runs the command. It does not execute arbitrary commands, capture stdout/stderr, or claim runtime attestation. _Fixed security decision._
3. Reuse requires exact level, command SHA-256, repository snapshot, WorkItem, successful outcome and valid store schema. A failed exact tuple returns `blocked-unchanged-failure`. Semantic command equivalence is outside deterministic Core scope, so differently spelled equivalent commands are intentionally not deduplicated. _Fixed initial contract plus relevant limitation._
4. T0/T1/T2 are verification-planning levels, not Trellis authority levels. A host-asserted T2 record cannot replace a typed Trellis gate/test receipt or weaken `require-current-gate`. _Fixed authority decision._
5. The first version uses the full bounded repository snapshot for conservative invalidation. Targeted dependency graphs and per-package impact mapping are relevant but non-blocking follow-ups after real canary data. _Fixed MVP scope._
6. **Relevant but non-blocking:** flaky retry policy, test-command semantic normalization, path-level impact maps and independently measured time savings require real-project data. Core will report truthful reuse/saved-duration counters without claiming a percentage improvement.
7. **Relevant follow-up:** a plan is non-persistent and recording accepts the exact repository snapshot returned by it. Switching WorkItems between host execution and recording is not independently attested; records remain advisory and cannot satisfy Trellis gates. A future plan-binding nonce may tighten this without storing raw commands.
8. **Background:** executing tests inside HelloDev, arbitrary shell allowlists, autonomous CI control, Dashboard action endpoints and external result ingestion remain out of scope.

Local acceptance completed with 209 fast and 249 full tests, two expected environment skips, Python compilation, Dashboard JavaScript syntax, and an isolated offline wheel smoke covering progressive verification, mutation invalidation and Dashboard schema 14. No push, tag, release snapshot, bundle, PyPI upload, global installation, plugin action or upstream modification was performed.

## 0.17.0 implemented decisions and open boundaries

1. `do begin` is a deterministic convenience workflow, not a second task database or workflow engine. It creates/selects a native task, stores only a WorkItem pointer, advances the existing lifecycle, and returns one Context Plan. _Fixed compatibility decision._
2. Existing `task`, `work activate`, lifecycle, Trellis escape-hatch and six MCP tools remain supported. `currentTask` is an additive projection; internal local/Trellis/WorkItem counts remain available for diagnostics. _Fixed migration decision._
3. Trellis task creation remains a write requiring the existing one-time approval. Multiple active Trellis tasks require explicit selection. Memory cannot choose or authorize a task. _Fixed safety decision._
4. Core and bundle share `onboard`, but Core does not imply bundled components. It may write project-scoped host files after conflict preflight and may only preserve an already configured external Nocturne command. _Fixed distribution decision._
5. Control Center 2.3 remains copy-only. Executable Dashboard actions, approval input, raw memory/source display and global configuration remain out of scope. _Fixed UI boundary._
6. **Relevant but non-blocking:** independently measured task-start latency/token reduction, richer acceptance criteria structure, and a signed multi-platform 0.17 bundle remain later work. No claim is made before evidence exists.

Local acceptance completed with 203 fast and 243 full tests, two expected environment skips, compile/JavaScript checks, and an isolated offline wheel smoke covering Core onboarding, unified begin, currentTask and Dashboard schema 13. No 0.17.0 source push, tag, GitHub Release, release snapshot, platform bundle, PyPI upload, global installation, plugin action or upstream modification has been performed.

## 0.16.0 implemented decisions and open boundaries

1. Native repository context is a HelloDev Core capability, not a mandatory external MCP. It must work on a clean installation with no FastCtx, ripgrep or Git dependency. _Fixed implementation decision._
2. The daily and MCP face remains `open`, `next`, `resume`, `status`, `context`, and `do`. Repository read/search/discovery are internal Context Plane operations rather than new public tools. _Fixed compatibility decision._
3. P0 is read-only. Replace, shell, background jobs, PDF rendering, self-update, TUI and global host configuration are outside 0.16.0. Existing approval/transaction/receipt paths are not widened. _Fixed safety decision._
4. Context output is selected under a budget before rendering, attaches path/line/hash provenance, and uses a stable repository-snapshot cursor. Mutation makes a cursor stale; a continuation cannot silently restart or repeat page one. _Fixed contract decision._
5. Durable state may retain bounded metrics, fingerprints and cursor metadata but no raw source text. Trellis remains workflow authority and Nocturne remains advisory memory. _Fixed privacy/authority decision._
6. FastCtx may remain discoverable as an optional future accelerator, but 0.16.0 completion and acceptance do not depend on executing it. Its absence is not degraded product functionality. _Fixed distribution decision._
7. **Relevant but non-blocking:** precise `.gitignore` parity without an external parser, semantic/AST ranking, PDF/image extraction, and independently measured cross-host token savings remain later evaluation work. Safe deterministic fallbacks are sufficient for 0.16.0.
8. **Background:** shell/job orchestration, write automation and external provider self-management remain deliberately deferred.

Local acceptance completed with 196 fast and 236 full tests, two expected environment skips, compile/JavaScript checks, and a disposable offline wheel smoke covering `open/status` plus cursor pagination without overlap. The HelloDev-only source was pushed to GitHub and the corrective Windows CI run passed at commit `5efc24db182b1afa471defb93ccfc97dd1a7a00a`. No 0.16.0 release snapshot, platform bundle, PyPI upload, global installation or host configuration change has been performed. Six CI annotations about actions targeting deprecated Node.js 20 are **Relevant but non-blocking** maintenance work; update the action majors before GitHub removes compatibility.

## 0.14.1 implemented decisions and release result

1. The user-facing product is packaged as one HelloDev platform bundle, but Trellis and Nocturne remain separately launched components with independent `.trellis/` and Nocturne data ownership. No database or source-of-truth merge is permitted. _Implemented decision._
2. Bundled components are selected only from a strict relative-path manifest and checked before launch. The manifest includes upstream version/revision/source/license plus size/SHA-256 for controlled files. Full local replacement of both manifest and payload remains outside this integrity claim. _Implemented decision; not a signature or provenance witness._
3. Existing 0.13 project configuration remains readable. Bundled Nocturne becomes active only through explicit onboarding, so an upgrade cannot silently introduce memory reads/writes. _Implemented compatibility decision._
4. Nocturne payload, writable config, and SQLite state are separate. Existing user databases are neither scanned nor migrated automatically. _Implemented privacy decision._
5. The Core wheel remains portable and MIT-licensed; self-contained runtimes and separately licensed upstream payloads belong to platform archives. Windows x86_64 passed the exact offline artifact gate. Linux/macOS support remains **Relevant but non-blocking** until exact archives pass the same smoke. _Released packaging decision._
6. Third-party notice/source-offer mechanics are release gates, but manifest matching is not final legal review or code signing. Those conclusions remain **Relevant but non-blocking** and require independent review.
7. The exact Windows archive proved offline launch of bundled Trellis and Nocturne with a clean/poisoned environment and disposable data. Source/unit completion alone remains insufficient for any future platform archive. _Release gate completed for Windows x86_64._

## Fixed 0.13 Agent-native decisions

1. `ProjectClient` is the typed application facade for CLI and MCP daily operations. It binds one root and retains no cross-call capability, identity, lease, profile, or approval cache.
2. The optional stdio gateway uses verified official `mcp==1.28.1`; base Core remains dependency-free and does not import MCP. The exact pin protects the closed-schema enforcement until a later SDK version is separately tested.
3. MCP exposes exactly `open`, `next`, `resume`, `status`, `context`, and `do`. It exposes no root argument per tool, generic argv, native adapter, HostEnvelope, policy, usage, audit, or Dashboard action.
4. MCP approval annotations are advisory, not human-attestation. The exact existing token must still bind and authorize the same operation; memory and old conversation text never authorize.
5. `hellodev_context` uses the non-persistent preview path. MCP `open` and `do` are serialized in-process; state stores retain their existing cross-process protections.
6. `integrate show/check` renders or validates project-scoped Codex/Cursor snippets without reading or mutating host configuration.
7. Default help discloses the daily/setup path; `--help-all` exposes advanced governance and adapters without removing compatibility commands.
8. Ordinary CI remains non-publishing. A separate release-only workflow is OIDC-ready, but GitHub Release creation, protected-environment configuration, and actual PyPI upload remain separately authorized and unverified until performed.

## Fixed 0.12.1 polish decisions

1. 0.12.1 is a compatible patch: Host protocol 1.0, 0.12.0 state schemas, policy targets, canary decision rules, and `open -> next -> do` remain unchanged.
2. Recovery coverage includes receipt persistence before WAL receipt phase and multi-process recover convergence on one receipt and policy effect.
3. Checkpoint files are bounded regular files with strict lowercase SHA-256. `--require-match` returns code 2 after emitting structured mismatch output; default verify remains reporting-only.
4. The SDK ships `py.typed`, public typed errors, and pending/reconcile/abandon methods. Full HostEnvelope context remains host-owned and is never reconstructed from sanitized metadata.
5. A valid pending HostEnvelope routes to exact `host pending <id>`, which declares external-host continuation and a separate abandon command; expired pending state still routes directly to abandon.
6. Canary v2 adds `commitEligible` and missing baseline/canary counts without changing evaluation outcomes.
7. CI is bounded and non-publishing: Ubuntu/Windows Python 3.10/3.12 fast, Ubuntu 3.12 full, seven-day wheel candidate, no secrets or release upload. Dependency-free jobs do not enable `setup-python` pip caching; otherwise its post-job cache save fails when no cache directory was created.
8. Minimal Demo and SDK example require neither Trellis nor Nocturne and do not simulate crashes through product backdoors. Fault injection remains test evidence.
9. The standalone GitHub source mirror is published and CI-verified. Local source/release completion still does not imply PyPI availability; public-index upload requires explicit authorization and independent verification.

## Fixed 0.12 reliability decisions

1. Effective policy operations enter an append-only local transaction WAL before the one-time approval is marked consumed. The durable phases are `authorized`, `token-consumed`, `receipt-recorded`, and `ledger-applied`.
2. A failure before the first WAL write leaves the exact approval reusable. After WAL creation, `transaction recover` resumes from the last phase without persisting or requesting the raw token; replay is idempotent.
3. The public Python Host SDK owns `HostClient`, `HostRequest`, `HostEnvelope`, and `HostResult`. Protocol version `1.0` is negotiated explicitly and the package bundles strict JSON Schemas.
4. `host prepare` stores sanitized pending metadata so `next/resume` can detect incomplete work. It never stores HostEnvelope context text, task/memory bodies, or approval material in that pending store.
5. Canary Evaluation v2 requires equal bounded baseline and canary samples. Success rate, retries, subagent count, and budget-exceeded rate cannot regress; insufficient evidence blocks commit.
6. Token comparison is optional and only available when both samples are entirely host-asserted. The label is `host-asserted-not-provider-verified`; every other case is `unavailable`.
7. Recovery priority is transaction, capability safety, pending HostEnvelope, incomplete Saga, stale WorkItem, Canary evaluation, lifecycle/gate, then optional efficiency advice. Only one command is returned.
8. Portable checkpoints bind policy ledger id, sequence, head, and Host protocol. An independently retained copy detects divergence; neither a local saved copy nor the hash chain is a tamper-proof ledger or remote witness.
9. Doctor, gate consistency, audit schema v2, and Dashboard schema v7 are read-only projections. The Dashboard remains copy-only and has no adapter/policy action API.

## Fixed 0.11.2 efficiency-cycle decisions

1. `open` and daily `do` opportunistically sync completed Codex turns. An environment thread must own the selected root; without one, HelloDev discovers the most-recent safe rollout whose recorded cwd overlaps the root. Failures are compact/unavailable and do not block daily work; `next/status/resume` remain read-only.
2. `usage sync` backfills oldest unrecorded completed turns, is bounded to 1–500 per call, skips unavailable individual turns without inventing values, and never includes the current incomplete turn.
3. A cycle is exactly 20 `runtime-observed + exact` receipts in stable insertion order. Windows do not overlap or roll. Explicit `asserted-runtime` imports and operator reports never count.
4. ReflectionCycle is an additive, locked, hash-bound sidecar. Existing windows are rebound to their receipt hashes on every reconcile; tamper/history replacement fails closed.
5. Analysis is deterministic: average token cost, cached-input share, subagent share/count, fixed signals, and one allowlisted saving command. Core performs no model or adapter call.
6. Cycle advice is non-effective: `applyAllowed=false`, human review required, tighten-only boundary. It cannot authorize a command, satisfy evidence, write memory, or mutate policy.
7. Recovery/safety routing remains higher priority. Only a finished lifecycle may disclose the cycle hint through the existing `next/status` surface.
8. Control Center schema v6 stays read/copy-only and filters all source/scope/receipt/window/cycle hashes.

## Fixed 0.11.1 usage decisions

1. `usage collect` reads a bounded local Codex rollout. Automatic Desktop selection uses `CODEX_THREAD_ID` when available and root-matching, otherwise project-bound recent-rollout discovery in the canonical Codex home. Explicit `--thread-id` / `--codex-home` / `--session` are caller-selected imports.
2. It reports only the latest already-completed turn. The response currently being generated has no final `task_complete` boundary and cannot be assigned a truthful final value until a later turn collects it.
3. Automatic Desktop success is `codex-runtime` / `runtime-observed`; explicit selection is `codex-runtime-import` / `asserted-runtime`. Both use `measurement=exact`, `attestation=none`, and `estimated=false`; neither is provider-signed, provider-attested, or provider-verified.
4. Root usage is a cumulative line-bounded interval delta; subagent usage includes only recursively discoverable descendants with matching start/complete intervals, bounded to 32 threads.
5. Durable state contains counts, completion time, trust fields, and digests only. Prompt/response text, raw events, thread/turn/subagent ids, Codex/session paths, and transcript bodies never persist.
6. No completed turn returns unavailable without persistence. Missing/incomplete descendants, absent interval snapshots, unsafe paths, malformed shapes, count regression, or conflicts fail closed without partial records. Identical collection is idempotent.
7. `usage record` remains caller-asserted. Runtime receipts live in additive `usage-receipts.json`, preserving the 0.11.0 schema-v1 ledger and optimization rollback path. They are display-only in 0.11.1 and never authorize commands or satisfy gate/test evidence.
8. Control Center schema v5 remains copy-only/status-only and labels the preferred previous-completed runtime receipt with `completedAt`, measurement, trust, attestation, and bounded breakdown. It never labels that value as the current reply.

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
17. The 0.11 Control Center command projection remains limited to `hellodev host status`, `hellodev policy status`, and `hellodev drift status`; schema v5 adds only filtered usage metadata, not an execution endpoint.
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
| 0.11.0 evolution | 113 fast and 145 full tests, zero failures and one platform-conditional skip in each scope; HostEnvelope/policy/drift/privacy matrix, isolated wheel, and schema-v4 Control Center smoke. |
| 0.12.0 reliability | 181 full tests passed with one conditional symlink skip; WAL recovery, typed Host SDK, Canary v2, checkpoint, audit privacy and schema-v7 Dashboard smoke. |
| 0.12.1 OSS polish | 191 full tests passed with one conditional symlink skip; exact wheel, typed package data, local Demo, Host recovery and checkpoint exit-code smoke. |
| 0.13.0 Agent-native | 167 fast and 199 full tests passed with two expected skips; exact six-tool official-SDK stdio smoke, base/MCP wheel checks and release snapshot. |

These are inherited release facts recorded in the root development ledger and preserved release directories. Every later source change still requires the current release gate.

## Release gate for source changes

| Question | Required resolution |
|---|---|
| Does the full regression pass after the 0.14 additions? | Run focused v0.14 distribution/security tests and one final full verification; record exact counts only in the completed release report. |
| Does crash recovery preserve authorization semantics? | Inject failure before WAL and after each phase; prove reusable-before-WAL or no-new-authorization recovery after WAL. |
| Is the Host SDK a real compatibility surface? | Import public types, negotiate versions, load schemas from source/wheel, and reject incompatible or manually malformed envelopes. |
| Does Canary v2 reject weak evidence? | Require equal bounded samples, test every comparison dimension, and preserve host-asserted/unavailable token labels. |
| Does the closed loop hold in a disposable project? | Run `EVOLUTION_DEMO.md`, including stdin, cancel, exhaustion, negative/tamper/late/unavailable cases. |
| Are canary/commit/revert approvals truly independent and recoverable only by exact receipt? | Run action-hash, replay, mismatch, already-appended/interrupted-append, and cross-process tests. |
| Does the ledger claim match its real trust boundary? | Verify individual tamper and external checkpoint mismatch; retain the full-rewrite limitation in all docs/UI. |
| Does usage refer only to a previous completed turn? | Exercise a completed turn followed by a started-but-incomplete turn; collect the former and never claim a current-response total. |
| Is runtime usage exact but honestly unattested? | Assert automatic-vs-explicit `sourceTrust`, exact measurement/attestation, cumulative breakdown, subagent total, and absence of provider-verified wording. |
| Does collection fail closed and preserve privacy? | Exercise missing child, malformed/regressing/conflicting input, unsafe path, idempotency, forbidden-value scan, and no-partial persistence. |
| Is the UI still non-executable? | Run authenticated/unauthenticated schema-v12 smoke and assert exact `uiCapabilities`, filtered recovery/experiment/usage/Context Plane projections, no repository text, and status-only commands. |
| Is the artifact reproducible and independent? | Snapshot verify, no-cache wheel, hashes, fresh venv, Demo/SDK smoke, exact Windows x86_64 archive smoke, then create a separate `outputs/hellodev-core-releases/0.14.1/`; preserve all prior releases unchanged. |

## Relevant but non-blocking gaps

| Topic | Current boundary |
|---|---|
| Provider-attested usage | Core can now measure a completed local Codex runtime turn exactly; explicit imports remain asserted-runtime, and neither path authenticates a provider-signed tokenizer receipt. |
| Current in-progress turn | A reply has no final completion boundary while it is being generated. Collection deliberately happens in a later turn. |
| Non-Codex runtimes | Cursor/other hosts can run the command only when a compatible Codex rollout is available; otherwise usage remains unavailable or manually asserted. |
| External checkpoint service | `--expected-head` accepts an operator/host-retained checkpoint; Core does not publish or witness heads remotely. |
| Complete-chain attacker | A writer able to replace the full event history and local head can create another internally valid chain absent the external checkpoint. |
| Nocturne namespace/domain portability | Public stable values remain installation-specific; explicit configuration and narrow allowlists continue. |
| Host runtime enforcement | Core emits ceilings and validates reported results; arbitrary external host scheduling/spawn enforcement remains the host's responsibility. |
| Public package publication | The GitHub source mirror is synchronized and CI-verified; PyPI availability is still unproven, and upload remains separately authorized. |

## Deliberately deferred product work

| Topic | Why deferred |
|---|---|
| Unattended global installation and host config editing | Explicit bundle setup is now in 0.14 scope, but silent PATH/registry/shell/user-level Codex/Cursor mutation remains outside the security contract. |
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

- **Fact — full source read:** the current 0.14 resolver, builder, onboarding, runner, adapter, package and documentation contracts were checked with the retained 0.13 ProjectClient/MCP baseline.
- **Fact — behavior represented by focused tests:** `test_v14_distribution.py`, v13 gateway/MCP suites, and inherited reliability/security suites cover source-level behavior. Exact archive evidence remains outside this orientation file until the release gate completes.
- **Relevant but non-blocking:** provider attestation, remote checkpointing, stable Nocturne namespaces, non-Codex runtime collection, host runtime enforcement, Linux/macOS archives, legal sign-off, code signing, and PyPI upload.
- **Background/deferred:** executable UI, unattended global installation, worktree, database merge, and Codex plugin packaging.

No open question permits weakening authorization, evidence, privacy, source-of-truth, or standalone boundaries by assumption.
