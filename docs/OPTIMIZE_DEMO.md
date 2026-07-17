# HelloDev 0.11.0 advanced optimization compatibility demo

This is the advanced acceptance path for the preserved 0.10.0 optimization schema: usage availability, deterministic planning, privacy-preserving reflection, tighten-only proposals, and the read/copy-only Control Center. In 0.11.0 these commands remain available for diagnostics/automation but are not part of the normal `open -> next -> do` path. Progressive disclosure is tested in [DISCLOSURE_DEMO.md](DISCLOSURE_DEMO.md); the separate verified policy workflow is tested in [EVOLUTION_DEMO.md](EVOLUTION_DEMO.md).

The optimizer is advisory. It does not call a model or adapter, apply a proposal by itself, authorize execution, satisfy evidence, or write Trellis/Nocturne. A proposal may be staged in the separate 0.11 policy workflow, but stage is non-effective and canary/commit/revert remain explicit, independently approved operations.

## Prerequisites

- `hellodev --version` reports `0.11.0` from the candidate artifact.
- Use a temporary project or disposable copy. Do not use live Nocturne memory.
- Keep `--root` explicit in acceptance commands.
- Preserve an actual 0.9 `.hellodev/` copy for the compatibility scenario.

```powershell
$Project = "C:\path\to\temporary-hellodev-project"
hellodev --root $Project open
$OptimizationStore = Join-Path $Project ".hellodev\optimization.json"
```

## Scenario A: 0.9 state is read without eager migration

Against the disposable 0.9 state, confirm the optimization store is absent, then run:

```powershell
Test-Path $OptimizationStore
hellodev --root $Project optimize status
hellodev --root $Project optimize plan --intent code
hellodev --root $Project optimize proposals
hellodev --root $Project audit export
Test-Path $OptimizationStore
```

Expected:

- Both `Test-Path` results are false.
- Status is `insufficient-data`, usage is `unavailable`, counts are zero, and `latestUsageEnvelope`/`latestReflection` are null.
- Plan reports `executionPerformed=false`, `persistencePerformed=false`, empty adapter/model calls, deterministic context selection, and `main-agent-default` unless a nonzero subagent allowance was declared.
- Proposals are empty and `applyAllowed=false`.
- Existing 0.9 lifecycle, WorkItem, evidence, Saga, profile, receipt, and adapter state is unchanged.

## Scenario B: bounded planning is not measured usage

```powershell
hellodev --root $Project optimize plan `
  --intent code `
  --level L1 `
  --token-ceiling 8000 `
  --subagent-token-ceiling 3000 `
  --max-subagents 2
```

Optionally link an existing WorkItem with `--work work-0001`.

Expected:

- `context.level` is L1 and the returned ceilings equal the caller declarations.
- `usageEnvelope.actual` is null and `budgetState` is unavailable; planning does not fabricate actual usage.
- A nonzero `maxSubagents` reports that `delegate plan` remains required before host spawning.
- `reflection.plannedDeepReflectionCeiling` is a planning bound only and `reflection.eligibility` is `anomaly-and-reported-usage-required`. Neither field claims that deep reflection is already eligible. Plan does not trigger reflection, persist a trace, spawn agents, or call a model.

## Scenario C: missing usage is unavailable; recorded usage is asserted

Before recording anything:

```powershell
hellodev --root $Project usage status
```

Expected: `state=unavailable`; totals and latest record are null, not zero.

Record an operator assertion with a unique label:

```powershell
$UsageCanary = "PRIVATE-USAGE-SOURCE-CANARY"
hellodev --root $Project usage record `
  --total 10000 `
  --subagent 6000 `
  --subagents 2 `
  --source $UsageCanary `
  --scope "temporary-turn"
hellodev --root $Project usage status
```

Expected:

- The usage record is externally reported/operator supplied. It is not a trusted host receipt or tokenizer-exact measurement.
- Optimizer projection labels it `sourceKind=operator-report`, `sourceTrust=asserted`, and `accuracy=externally-reported; not host-verified`.
- The source/scope labels are owned by `usage.json`. Optimization traces, audit export, and Control Center projection must use hashes/sanitized numeric fields and must not copy `$UsageCanary`.
- Optimizer actual usage remains unavailable until `reflect` explicitly receives `--usage <id|latest>`.

## Scenario D: reflection is deterministic local recording

First record a successful trace without linked usage:

```powershell
hellodev --root $Project optimize reflect `
  --intent status `
  --context-level L0 `
  --outcome succeeded
```

Expected: one DecisionTrace and one ReflectionReport are recorded. There is no anomaly, so deep reflection is `not-triggered`; actual usage remains unavailable.

The report also contains a deterministic trend scoped to the current WorkItem when linked, otherwise to the intent. Confirm `sampleSize`, `usageAvailableCount`, `reportedTotalTokens`, `averageReportedTokens`, `reportedSubagentTokens`, complete outcome/context-level count maps, `delegationExecutedCount`, and `narrowMemoryCount`. Distribution counts must sum to `sampleSize`; no raw text is aggregated.

Record an anomalous trace without linked usage:

```powershell
hellodev --root $Project optimize reflect `
  --intent code `
  --context-level L1 `
  --outcome partial `
  --retrieval local `
  --delegation rejected `
  --retries 2
```

Expected: anomaly is true but deep reflection is `unavailable` because no positive reported usage was linked. `metrics.totalTokens` remains null.

Run the exact same command again. Expected: `state=existing`, the trace/report ids are unchanged, no duplicate is written, and `persistencePerformed=false`.

For every report confirm:

```text
executionPerformed: false
applyPerformed: false
adapterCalls: []
modelCalls: []
```

## Scenario E: deep reflection is eligibility with both caps

Link the latest asserted record to an anomalous reflection:

```powershell
hellodev --root $Project optimize reflect `
  --intent doctor `
  --context-level L0 `
  --outcome failed `
  --usage latest `
  --token-ceiling 8000 `
  --subagent-token-ceiling 4000 `
  --max-subagents 2 `
  --delegation executed `
  --retries 2
```

The linked total is 10,000, so the eligibility ceiling is:

```text
min(500, floor(10000 * 0.05)) = 500
```

Record another asserted usage total of 2,000 and reflect an anomaly against its id:

```powershell
$Usage2 = hellodev --root $Project --json usage record `
  --total 2000 `
  --subagent 0 `
  --subagents 0 `
  --source "temporary-host-label-2" `
  --scope "temporary-turn-2" | ConvertFrom-Json

hellodev --root $Project optimize reflect `
  --intent lifecycle `
  --context-level L1 `
  --outcome blocked `
  --usage $Usage2.id `
  --token-ceiling 1000 `
  --retries 2
```

Expected ceiling: 100. Also verify these branches:

| Condition | Deep-reflection state |
|---|---|
| No deterministic anomaly | `not-triggered`, no token ceiling |
| Anomaly, no linked usage | `unavailable`, no token ceiling |
| Anomaly, linked total is zero | `unavailable`, no token ceiling |
| Anomaly, positive linked total | `eligible`, ceiling `min(500,floor(total*0.05))` |

Eligibility is metadata for a host. HelloDev Core does not invoke a model or spend the ceiling.

## Scenario F: proposals are evidence-backed, tighten-only, and not directly applicable

Generate three distinct comparable retry traces:

```powershell
hellodev --root $Project optimize reflect --intent local-task --context-level L1 --outcome partial --retries 2
hellodev --root $Project optimize reflect --intent local-task --context-level L1 --outcome partial --retries 3
hellodev --root $Project optimize reflect --intent local-task --context-level L1 --outcome partial --retries 4
hellodev --root $Project optimize proposals
```

Expected: one proposal targets `retry.maxAttempts`, replaces integer `3` with `2`, uses `constraintCode=tighten-only`, cites three ReflectionReports, requires human review, and has `applyAllowed=false`.

To exercise the delegation target, create a fresh asserted usage record with nonzero subagent tokens and three distinct unsuccessful reflections:

```powershell
$DelegationUsage = hellodev --root $Project --json usage record `
  --total 6000 `
  --subagent 4000 `
  --subagents 2 `
  --source "temporary-delegation-label" `
  --scope "temporary-delegation-turn" | ConvertFrom-Json

hellodev --root $Project optimize reflect --intent trellis-read --context-level L1 --outcome failed --usage $DelegationUsage.id --max-subagents 2 --delegation executed --retries 0
hellodev --root $Project optimize reflect --intent trellis-read --context-level L1 --outcome failed --usage $DelegationUsage.id --max-subagents 2 --delegation executed --retries 1
hellodev --root $Project optimize reflect --intent trellis-read --context-level L1 --outcome failed --usage $DelegationUsage.id --max-subagents 2 --delegation executed --retries 2
hellodev --root $Project optimize proposals
```

Expected proposal: `delegation.effectiveMaxAgents`, `2 -> 1`, tighten-only.

No other target, operation, or widening value is valid. Confirm the optimizer itself still has no apply surface:

```powershell
hellodev --root $Project optimize apply
```

Expected: parser exit code 2; no state changes. In 0.11, only `policy stage|cancel|canary|evaluate|commit|revert` can move or resolve an eligible proposal through the separately verified workflow. Merely listing, staging, or cancelling a staged proposal does not change effective policy.

Change a policy-fingerprinted input in the disposable project, for example the exact-confirmed local finish policy:

```powershell
hellodev --root $Project gate policy set require-current-gate
# Paste the complete returned resumeCommand.
hellodev --root $Project optimize proposals
```

Expected: existing proposals are retained for audit but marked `stale=true`. Project config, optimization rules/allowlist/targets, and context-policy changes all invalidate the old proposal fingerprint rather than rewriting history.

## Scenario G: optimization cannot become authority

Use an observed trace id as if it were gate evidence:

```powershell
hellodev --root $Project gate reconcile trace-0001
```

Expected: failure. DecisionTrace, ReflectionReport, and EvolutionProposal ids are not receipts and cannot authorize or satisfy evidence.

Inspect privacy projections:

```powershell
hellodev --root $Project optimize status
hellodev --root $Project audit export
```

Expected:

- Audit includes optimization counts and latest ids, not trace/report/proposal bodies.
- Optimization state contains structured enums/counts/fingerprints/hashes, not raw task, prompt, model, adapter, memory, or usage source/scope content.
- Tampered commands, targets, ids, schemas, or unknown fields fail closed.
- Trellis/Nocturne adapter behavior, profiles, approvals, receipts, EvidenceLinks, gate/Saga rules, and write confirmation are unchanged from 0.9.

## Scenario H: Control Center remains read/copy-only

```powershell
hellodev --root $Project dashboard start
hellodev --root $Project dashboard status
hellodev --root $Project dashboard stop
```

The schema-v4 browser projection may show counts, numeric usage envelope fields, proposal staleness, reflection finding/recommendation counts, anomaly, eligibility ceiling, and copyable optimize/status commands. Its 0.11 evolution projection is limited to `hellodev host status`, `hellodev policy status`, and `hellodev drift status`. It must not expose raw optimization/host/policy records, usage labels, full envelopes, policy values, receipts/hashes, raw findings, or invoke plan/reflect/complete/stage/cancel/canary/commit/revert, adapters/models, approvals, or any state write.

## Acceptance record

The verified 0.10.0 baseline run passed fast 82/82 and full 114/114. Its disposable real Trellis plus fake public stdio MCP path observed: strict finish blocked before evidence, fingerprint refresh, successful native validation and gate reconciliation, successful finish, usage initially unavailable, successful reflection with deep reflection `not-triggered`, successful Nocturne tools receipt, and zero raw usage-label copies in optimization state. Re-run and record fresh evidence for the 0.11.0 candidate.

```text
Candidate version/artifact: <0.11.0 wheel/source and hash>
0.9 state loaded without optimization store creation: <pass/fail>
Status/plan/proposals read-only: <pass/fail>
Usage missing is unavailable: <pass/fail>
Usage projection is operator-report/asserted/not-host-verified: <pass/fail>
Reflection idempotent and privacy bounded: <pass/fail>
Reflection trend sample/usage/token/distribution aggregates: <pass/fail>
Deep reflection anomaly gate: <pass/fail>
Deep reflection min(500,floor(total*0.05)): <pass/fail>
Retry proposal 3->2 tighten-only/no-direct-optimize-apply: <pass/fail>
Delegation proposal 2->1 tighten-only/no-direct-optimize-apply: <pass/fail>
Proposal stale after policy/rule/config change: <pass/fail>
Optimizer rejected as evidence/authority: <pass/fail>
Core adapter calls: 0
Core model calls: 0
Direct optimizer proposal applications: 0
Separate policy workflow documented/tested in EVOLUTION_DEMO: <pass/fail>
Control Center schema-v4 read/copy-only: <pass/fail>
F1/F2 regression: <pass/fail and evidence>
Known gaps: <explicit list>
```
