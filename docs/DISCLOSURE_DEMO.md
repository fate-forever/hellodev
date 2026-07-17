# HelloDev 0.11.0 progressive-disclosure regression demo

This acceptance path verifies that daily work remains `open -> next -> do`, recovery keeps its existing priorities, and advanced efficiency advice appears only after finished work with an actionable existing optimization state. It supplements the unchanged F1/F2 and 0.10 optimization demos. The new `host`, `policy`, and `drift` groups are advanced surfaces and must not appear as required daily or recovery steps.

## Prerequisites

- `hellodev --version` reports `0.11.0` from the candidate artifact.
- Use temporary/disposable projects only.
- Keep an immutable 0.10.0 project copy with optimization history for compatibility checks.
- Do not use live Nocturne memory or install globally.

```powershell
$Project = "C:\path\to\temporary-disclosure-project"
hellodev --root $Project open
```

## Scenario A: daily flow stays small

Run only the normal loop:

```powershell
hellodev --root $Project next
hellodev --root $Project do plan
hellodev --root $Project next
hellodev --root $Project do task create --title "Disclosure acceptance"
hellodev --root $Project do work
hellodev --root $Project next
hellodev --root $Project do check
hellodev --root $Project next
hellodev --root $Project do finish
```

Expected:

- The primary workflow remains `open -> next -> do`.
- No optimize command is inserted as a required daily step.
- Each `next` result has exactly one primary `command`.
- Active lifecycle phases do not include an `efficiency` block, even if advanced optimization history already exists.

## Scenario B: finished and missing stays quiet without creating files

Use a fresh temporary project, finish its lifecycle, and confirm no optimization store exists:

```powershell
$QuietProject = "C:\path\to\temporary-quiet-project"
hellodev --root $QuietProject open
hellodev --root $QuietProject do plan
hellodev --root $QuietProject do work
hellodev --root $QuietProject do check
hellodev --root $QuietProject do finish

$OptimizationStore = Join-Path $QuietProject ".hellodev\optimization.json"
Test-Path $OptimizationStore
$Quiet = hellodev --root $QuietProject --json next | ConvertFrom-Json
Test-Path $OptimizationStore
```

Expected:

- Both `Test-Path` results are false.
- `$Quiet.command` is `hellodev receipt list`.
- `$Quiet` has no `efficiency` property.
- Reading `next`, `open`, `resume`, status, audit, or the Control Center projection does not create optimization state.

## Scenario C: existing ready state also stays quiet

Record a successful, non-anomalous advanced reflection:

```powershell
hellodev --root $QuietProject optimize reflect `
  --intent status `
  --context-level L0 `
  --outcome succeeded

hellodev --root $QuietProject optimize status
$Ready = hellodev --root $QuietProject --json next | ConvertFrom-Json
```

Expected: optimization status is `ready`, the primary command remains `hellodev receipt list`, and no `efficiency` block is present. A completed reflection alone is not a reason to interrupt the normal closeout.

## Scenario D: attention discloses one advanced hint

Create an anomalous trace after work is already finished:

```powershell
hellodev --root $QuietProject optimize reflect `
  --intent code `
  --context-level L1 `
  --outcome partial `
  --retries 2

$StoreBefore = (Get-FileHash -LiteralPath $OptimizationStore -Algorithm SHA256).Hash
$Attention = hellodev --root $QuietProject --json next | ConvertFrom-Json
$StoreAfter = (Get-FileHash -LiteralPath $OptimizationStore -Algorithm SHA256).Hash
$AttentionBytes = [Text.Encoding]::UTF8.GetByteCount(
  ($Attention | ConvertTo-Json -Depth 10 -Compress)
)
$AttentionBytes
```

Expected:

- Primary `command` is still `hellodev receipt list`.
- `efficiency.state` is `attention`.
- `efficiency.suggestion.command` is `hellodev optimize status`.
- There is exactly one efficiency suggestion.
- The block contains only bounded trend/signal counts and a reason/suggestion, with empty adapter/model calls and both execution/persistence false.
- `$StoreBefore -eq $StoreAfter`; disclosure does not mutate optimization history.
- UTF-8 JSON for the complete `next` result is at most 1,024 bytes.

`resume` must expose the identical primary/advisory projection:

```powershell
$Resume = hellodev --root $QuietProject --json resume | ConvertFrom-Json
$Resume.next
```

## Scenario E: review-due points to proposals

Generate three comparable retry-overhead reports for one intent:

```powershell
hellodev --root $QuietProject optimize reflect --intent local-task --context-level L1 --outcome partial --retries 2
hellodev --root $QuietProject optimize reflect --intent local-task --context-level L1 --outcome partial --retries 3
hellodev --root $QuietProject optimize reflect --intent local-task --context-level L1 --outcome partial --retries 4
$Review = hellodev --root $QuietProject --json next | ConvertFrom-Json
```

Expected:

- Primary `command` remains `hellodev receipt list`.
- `efficiency.state` is `review-due`.
- `efficiency.suggestion.command` is `hellodev optimize proposals`.
- Signal includes proposal and stale-proposal counts; the hint does not apply or acknowledge anything.

## Scenario F: active workflow suppresses the hint

Use another temporary project with actionable optimization history but an active lifecycle:

```powershell
$ActiveProject = "C:\path\to\temporary-active-project"
hellodev --root $ActiveProject open
hellodev --root $ActiveProject do plan
hellodev --root $ActiveProject optimize reflect --intent code --context-level L1 --outcome partial --retries 2
$Active = hellodev --root $ActiveProject --json next | ConvertFrom-Json
```

Expected: primary command is `hellodev do work`; there is no `efficiency` property.

## Scenario G: safety and recovery suppress the hint

Do this only in the disposable finished project with attention/review-due state:

```powershell
Set-Content -LiteralPath (Join-Path $QuietProject "AGENTS.md") -Value "disposable fingerprint change"
$Safety = hellodev --root $QuietProject --json next | ConvertFrom-Json
```

Expected: primary command is `hellodev capabilities refresh`, reason is `capability-cache-not-fresh`, and no `efficiency` block is present.

Repeat the principle for an incomplete Saga, stale WorkItem, or strict gate blocker. Existing recovery priority must win; efficiency is never a competing primary command.

## Scenario H: advanced compatibility is unchanged

Against a disposable 0.10.0 project with existing `.hellodev/optimization.json`:

```powershell
hellodev --root $Project optimize status
hellodev --root $Project optimize plan --intent code
hellodev --root $Project optimize proposals
```

Expected:

- The 0.10.0 optimization schema loads without migration or rewriting.
- `optimize status|plan|reflect|proposals`, usage semantics, deep-reflection eligibility, trends, tighten-only targets, proposal staleness, and absence of a direct `optimize apply` command remain compatible.
- The separate 0.11 policy-evolution workflow does not change the optimization schema and is never inserted into daily/recovery disclosure.
- `host status|prepare|complete`, `policy status|stage|cancel|canary|evaluate|commit|revert`, and `drift status` remain advanced; Core still makes no model or adapter call through daily disclosure.

## Scenario I: invalid advisory state cannot block closeout

Use a separate disposable finished project, then write an intentionally invalid advisory store:

```powershell
$InvalidProject = "C:\path\to\temporary-invalid-advisory-project"
hellodev --root $InvalidProject open
hellodev --root $InvalidProject do plan
hellodev --root $InvalidProject do work
hellodev --root $InvalidProject do check
hellodev --root $InvalidProject do finish

$InvalidOptimization = Join-Path $InvalidProject ".hellodev\optimization.json"
Set-Content -LiteralPath $InvalidOptimization -Value "{}"
$InvalidNext = hellodev --root $InvalidProject --json next | ConvertFrom-Json
$InvalidResume = hellodev --root $InvalidProject --json resume | ConvertFrom-Json
hellodev --root $InvalidProject optimize status
```

Expected:

- Next/resume succeed with primary `hellodev receipt list` and no `efficiency` block.
- The invalid file is neither repaired nor rewritten.
- Explicit `optimize status` fails closed with an optimization-store schema error.
- The same daily omission rule applies to corrupt/malformed/future-version advisory optimization or usage state. It does not apply to authoritative workflow, authorization, evidence, or recovery errors.

## Scenario J: Control Center remains copy-only

```powershell
hellodev --root $QuietProject dashboard start
hellodev --root $QuietProject dashboard status
hellodev --root $QuietProject dashboard stop
```

The schema-v4 Control Center may continue to project optimization summaries plus filtered host/policy/drift status and copy advanced status commands. It must not execute next hints, plan/reflect, host complete, policy stage/cancel/canary/commit/revert, consume approvals, call adapters/models, or write state. The only new evolution commands it may expose are `hellodev host status`, `hellodev policy status`, and `hellodev drift status`.

## Acceptance record

```text
Candidate version/artifact: <0.11.0 wheel/source and hash>
Daily open->next->do only: <pass/fail>
Active workflow hides efficiency: <pass/fail>
Finished missing state has no hint/file creation: <pass/fail>
Finished ready state stays quiet: <pass/fail>
Finished attention keeps primary + one optimize-status hint: <pass/fail>
Finished review-due keeps primary + one proposals hint: <pass/fail>
Resume next projection matches: <pass/fail>
Safety/recovery suppresses hint: <pass/fail>
Invalid/future advisory state omitted from next/resume: <pass/fail>
Explicit optimize status still fails closed: <pass/fail>
Next projection <=1024 bytes: <pass/fail>
Disclosure execution/persistence/adapter/model calls: 0
0.10.0 optimization schema/advanced command compatibility: <pass/fail>
Host/policy/drift remain advanced-only: <pass/fail>
Control Center schema-v4 status-only/copy-only: <pass/fail>
F1/F2/optimization regressions: <pass/fail>
Known gaps: <explicit list>
```
