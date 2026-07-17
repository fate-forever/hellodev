# HelloDev Core 0.11.0 release checklist

This checklist releases the advanced host bridge and verified, tighten-only policy-evolution loop on top of the immutable 0.10.1 baseline. The daily contract remains `open -> next -> do`; `resume` remains the recovery entry. `host`, `policy`, and `drift` are advanced automation/governance surfaces.

Do not install from the development directory. Build a new wheel and publish a separate real release directory only after every gate passes. Never replace or mutate the preserved 0.8.0, 0.9.0, 0.10.0, or 0.10.1 artifacts.

## 1. Version and source-of-truth gate

1. Confirm `0.11.0` agrees in:

   - `pyproject.toml`
   - `src/hellodev/__init__.py`
   - `README.md`
   - Control Center product label
   - release evidence and wheel filename
   - Nocturne MCP client metadata

2. Confirm the editable source is only `packages/hellodev-core`. `outputs/hellodev`, historical snapshots, release copies, Marketplace trials, and installed caches are evidence, not source.
3. Confirm no root `.trellis/` appeared. If it exists, stop and follow its workflow/task state before continuing.
4. Update `HELLODEV_DEVELOPMENT_PROGRESS.md` before and after validation.

## 2. Daily, F1, F2, optimization, and disclosure regression

Run:

```powershell
python scripts\verify.py --scope fast
python scripts\verify.py --scope full
```

The full gate must preserve:

- Daily: `open -> next -> do task list -> do plan/work/check -> do validate -> do finish`.
- Recovery: `resume` prioritizes stale capabilities, incomplete Saga, stale WorkItem, then lifecycle/gate progress.
- F1: deterministic routing/context levels, exact one-time approvals, profile TTL/fingerprint invalidation, local-first narrow recall, and evidence-gated remember.
- F2: pointer-only WorkItems, hash-only LessonProposals, typed evidence links, gate reconciliation, Saga recovery/close rules, delegate plan/pack ceilings, and privacy-preserving audit.
- Optimization: schema compatibility, deterministic plans/reflections, operator-asserted usage, deep-reflection eligibility only, stale-aware proposals, and no `optimize apply` command.
- Disclosure: active/safety/recovery states suppress optional efficiency hints; finished hints remain bounded and advisory; malformed advisory state is omitted from daily projection but fails closed in explicit diagnostics.
- No Trellis/Nocturne authority widening, no autonomous memory write, no upstream patch, no merged database, no worktree implementation, and no model call inside Core.

Run the documented acceptance paths:

```text
docs/F1_DEMO.md
docs/F2_DEMO.md
docs/OPTIMIZE_DEMO.md
docs/DISCLOSURE_DEMO.md
docs/EVOLUTION_DEMO.md
```

## 3. Host bridge gate

Verify `host prepare`:

- Is read-only and does not create host, policy, usage, or optimization stores.
- Emits a bounded context pack, one next projection, delegation plan/digest, token/subagent/retry ceilings, root/capability/WorkItem/optimization/policy/ledger bindings, expiry, nonce, and whole-envelope hash.
- Always reports `grantsExecution=false`, `grantsEvidenceAuthority=false`, and `approvalReceiptId=null`.
- Enforces TTL 60–86400 seconds and explicit L2 opt-in.
- Applies the current committed/canary policy only as a tightening of subagent/retry ceilings.

Verify `host complete`:

- Recommends strict `--stdin` input with exactly `{envelope,result}`, capped at 512 KiB, so bounded context need not enter process arguments; rejects mixing stdin with argv JSON.
- Rejects tampered envelope/result, stale bindings, conflicting reuse, and invalid schemas/enums/counts.
- Records declared budget/retry/subagent violations in the sanitized completion/reflection so drift/evaluation can reject them as canary evidence; it must not silently report them as compliant.
- Reuses an identical envelope/result idempotently.
- Persists only a sanitized HostCompletion and deterministic optimization reflection; no transcript, prompt, raw context, model/adapter output, task body, memory body, or approval token.
- Marks expired completion `late=true`; late records cannot satisfy current canary evidence.
- Never converts a Host trace into gate/test evidence.
- Labels supplied usage `host-asserted`, envelope-bound, and not provider-verified; missing token fields stay unavailable rather than zero.

## 4. Policy evolution and approval matrix

Only these integer targets are valid:

| Target | Baseline | Constraint |
|---|---:|---|
| `delegation.effectiveMaxAgents` | 2 | tighten-only |
| `retry.maxAttempts` | 3 | tighten-only |

Verify the lifecycle:

1. `policy stage --proposal <id>` validates a current proposal and appends a stage event without changing effective policy.
2. A second staged/active proposal is rejected; stale proposals are rejected.
3. `policy cancel --proposal <id>` appends an idempotent, non-effective `cancel-stage` event without approval and frees only a staged proposal. It cannot cancel an active canary.
4. `policy canary` requires its own exact one-time approval, turn limit 1–20, and TTL 60–86400 seconds.
5. The canary overlay becomes effective only after the approved canary event is appended.
6. After the turn limit of same-head, non-late HostCompletions is reached, state is `canary-exhausted`, effective policy returns to committed policy, public `observedTurns` stays capped at turnLimit, and evaluation remains fixed to the first N records. Later same-head completions must not extend the overlay/evidence sample.
   - Prove the completion lock enforces the final turn under process concurrency: with turnLimit=1, two concurrent completions yield one success, one stale failure, and one stored completion.
7. `policy evaluate` is read-only and selects only that bounded current-head, non-late HostCompletion sample.
8. Evaluation passes only with the full sample, all successful outcomes, no declared-budget excess, no retry/subagent policy violation, and no expiry. Completion counts/usage remain host-asserted, not provider-verified.
9. `policy commit` is unavailable until evaluation passed and drift is clean.
10. Commit requires a new exact approval and binds unique bounded HostCompletion ids.
11. `policy revert` requires a third exact approval and can only cancel the active canary or restore the most recent unresolved commit's immediate previous policy.
12. A later staged proposal blocks commit rollback until cancelled; its non-effective stage/cancel events must not erase that commit target.
13. A second revert with no valid target fails; arbitrary historical rollback is absent.

Approval safety matrix:

| Operation | Approval | Reuse allowed | Effective-policy effect |
|---|---|---|---|
| `stage` | none | n/a | none |
| `cancel` (staged only) | none | idempotent same proposal | none |
| `canary` | exact one-time policy approval | no | temporary tighter overlay |
| `evaluate` | none | n/a | none |
| `commit` | new exact one-time approval | no | changes committed policy |
| `revert` | another exact one-time approval | no | restores immediate prior policy |

`--approve` and `--receipt` are mutually exclusive. Before token consumption, the receipt store must pass read/safety validation; a corrupt/unsafe store must fail without burning the token. Test receipt recovery: after an approval receipt exists but ledger append is interrupted, the matching `--receipt` can finish that exact action; after append, the same exact receipt returns the existing event. It cannot authorize another event type, action, proposal, or canary scope. Approval tokens are never persisted.

## 5. Integrity and drift gate

Verify every policy event includes a valid `previousEventSha256` and `eventSha256`, and that structural changes to an event, link, or stored head produce `invalid`/`detected` rather than silent recovery.

Verify `drift status` is read-only and distinguishes:

- `clean`
- `detected`
- `unavailable`
- `invalid`

The projection covers capability/WorkItem staleness, expired canary, optional external checkpoint mismatch, current-head HostCompletions, retry/subagent violations, declared-budget excess, and informational late completion. Invalid policy/host state must produce an explicit invalid projection without rewriting files.

Run `drift status --expected-head <SHA256|GENESIS>` against a separately retained head and prove mismatch detection. Document the limit precisely: the local hash chain detects broken/partial edits, but a complete history+head rewrite is not detectable without an external checkpoint. Do not call it a transparency log, remote witness, tamper-proof ledger, or non-repudiation mechanism.

## 6. Control Center schema-v4 gate

Start a disposable loopback instance and confirm:

```powershell
hellodev dashboard start
hellodev dashboard status
hellodev dashboard stop
```

- Per-launch browser token, authenticated status, unauthenticated 401, Host/Origin checks, and clean stop still work.
- `schemaVersion=4`.
- `uiCapabilities` is exactly read/copy-only: `copyOnly=true`, `applyAllowed=false`, `commitAllowed=false`, `revertAllowed=false`, `actionApiAvailable=false`.
- Advanced projection exposes only filtered status/count fields and copy commands for:

  ```text
  hellodev host status
  hellodev policy status
  hellodev drift status
  ```

- The UI does not expose full envelopes, policy values, receipt/hash material, raw findings, repair commands, or complete/stage/cancel/canary/commit/revert controls.
- No action/adapter/model/approval/profile/policy/reconcile/delegate endpoint exists.

## 7. Privacy and authority scan

Scan source, state fixtures, dashboard responses, and audit projections. Reject the candidate if any durable store or UI projection includes raw task/lesson/query/memory text, prompt/transcript/model output, adapter output, approval token, plaintext project root, or usage source/scope label.

Confirm:

- Memory remains advisory and cannot authorize execution.
- HostEnvelope grants no execution/evidence authority.
- HostCompletion never satisfies a Trellis gate.
- Policy changes cannot widen adapter authorization, evidence rules, context hard limits, memory scope, schemas, or upstream capabilities.
- Bootstrap/global install/config mutation, Codex plugin work, live user-memory access, and Dashboard execution are absent.

## 8. Snapshot, wheel, and isolated smoke

After all code/tests/docs are final:

```powershell
python -m hellodev snapshot verify
Remove-Item -LiteralPath .\dist -Recurse -Force
python -m pip wheel . --no-deps --no-cache-dir --wheel-dir dist
Get-FileHash .\dist\hellodev_core-0.11.0-py3-none-any.whl -Algorithm SHA256
```

Install the wheel into a fresh isolated virtual environment and smoke:

```text
hellodev --version
hellodev --help
hellodev open
hellodev next
hellodev host status
hellodev host prepare --intent code
hellodev policy status
hellodev drift status
hellodev dashboard start/status/stop
```

Run the mutation-heavy evolution path only in a disposable project. Do not touch live Nocturne data or an irreplaceable Trellis repository.

Publish source snapshot and wheel into `outputs/hellodev-core-releases/0.11.0/` as a new separate real directory. Never use a symlink, junction, Marketplace entry, development tree, or installed cache as the release artifact.

## 9. Release evidence template

```text
Version: 0.11.0
Fast tests: <passed/total>
Full tests: <passed/total>
F1/F2 regression: <result>
Optimization/disclosure regression: <result>
Host envelope/complete matrix: <result>
Policy stage/cancel/canary/exhaust/evaluate/commit/revert matrix: <result>
Independent approval/receipt recovery matrix: <result>
Drift/hash-chain/external-checkpoint matrix: <result>
Host-asserted/late/unavailable usage matrix: <result>
Privacy/authority scan: <result>
Control Center schema-v4 copy-only smoke: <result>
Source files / aggregate SHA-256: <count / hash>
Wheel: hellodev_core-0.11.0-py3-none-any.whl
Wheel SHA-256: <hash>
Fresh isolated install: <result>
Independent release directory: outputs/hellodev-core-releases/0.11.0/
Known gaps: provider-verified usage, external checkpoint service, bootstrap/global install, UI execution, upstream patches, worktree, autonomous writes
```
