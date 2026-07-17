# HelloDev 0.9.0 F2 continuity demo

This is the release acceptance path for WorkItem, EvidenceLink, LessonProposal, cross-session resume, gate policy, Saga recovery, delegation budgets, and privacy-preserving audit. Use a disposable copy of a real Trellis repository. Never run the mutation steps against an irreplaceable working tree or live user-memory database.

## Prerequisites

- `hellodev --version` reports `0.9.0` from the candidate wheel or source under test.
- The selected project is a disposable copy containing a real `.trellis/`, `.trellis/workflow.md`, and at least one native task directory under `.trellis/tasks/`.
- The Trellis CLI/scripts used by the project are available exactly as they are for normal development.
- Optional remember execution uses a disposable public Nocturne stdio MCP process only. Do not connect to live user memory, private REST, or a database directly.
- Run the 0.8 behavior regression in [F1_DEMO.md](F1_DEMO.md) separately.

Set explicit values:

```powershell
$Project = "C:\path\to\disposable-trellis-project"
$TrellisTask = "<existing-native-task-directory>"
hellodev --root $Project --version
Test-Path (Join-Path $Project ".trellis\workflow.md")
Test-Path (Join-Path $Project ".trellis\tasks\$TrellisTask")
```

All commands keep `--root` explicit so project selection and approval binding are visible.

## Scenario A: non-destructive 0.8 upgrade

Start with a disposable copy of an actual 0.8 `.hellodev/` directory. Before running a mutating F2 command, record whether the three F2 stores exist:

```powershell
$F2Stores = @("work-items.json", "lesson-proposals.json", "evidence-links.json")
$F2Stores | ForEach-Object {
  [pscustomobject]@{ Name = $_; Exists = Test-Path (Join-Path $Project ".hellodev\$_") }
}

hellodev --root $Project status
hellodev --root $Project resume
hellodev --root $Project work list
hellodev --root $Project lesson list
hellodev --root $Project gate status
```

Expected:

- Existing lifecycle, task, brief, receipt, Saga, profile, usage, and capability state still loads.
- Missing F2 stores behave as empty state; read-only commands do not create them.
- Existing authorization defaults remain `strict`; no adapter or migration write runs merely because 0.9 reads the project.

If testing a fresh project instead, initialize it once:

```powershell
hellodev --root $Project open
```

## Scenario B: pointer-only work and stable cross-process resume

Set the strict local finish policy before creating the WorkItem. The policy is fingerprinted configuration, so refresh capabilities afterward:

```powershell
hellodev --root $Project gate policy set require-current-gate
# Paste the complete returned resumeCommand unchanged.
hellodev --root $Project capabilities refresh
hellodev --root $Project work link --trellis-task $TrellisTask
hellodev --root $Project work current
```

Inspect `.hellodev\work-items.json`. It may contain ids, `backend`, `nativeRef`, linked phase, source fingerprint, and timestamps. It must not contain the Trellis task body, PRD, journal, task history, or files copied from `.trellis/tasks/$TrellisTask`.

Every CLI call below is a new process. With no state change between calls, compare the two recovery decisions:

```powershell
$First = hellodev --root $Project --json resume | ConvertFrom-Json
$Second = hellodev --root $Project --json resume | ConvertFrom-Json

[pscustomobject]@{
  SameCommand = $First.next.command -eq $Second.next.command
  SameReason = $First.next.reasonCode -eq $Second.next.reasonCode
  FirstCommand = $First.next.command
  FirstReason = $First.next.reasonCode
}

hellodev --root $Project resume --context --token-budget 256
hellodev --root $Project context pack --resume --token-budget 256
```

Expected: both comparisons are true. Resume makes no adapter/model call. Each context result is at most 1,024 UTF-8 bytes and reports its conservative budget rather than measured model tokens.

Also verify native reference validation fails closed:

```powershell
hellodev --root $Project work link --trellis-task does-not-exist
hellodev --root $Project work show work-9999
```

Both commands must fail without changing the current pointer.

## Scenario C: strict finish guard and automatic gate reconciliation

Move to checking:

```powershell
hellodev --root $Project do plan --note "F2 acceptance planned"
hellodev --root $Project do work --note "F2 acceptance running"
hellodev --root $Project do check --note "Ready for native gate"
hellodev --root $Project gate status
hellodev --root $Project do finish
```

Before validation, `gate status` is `evidence-missing`, and `do finish` must fail closed under `require-current-gate` without changing the lifecycle from `checking`.

Run the validated native Trellis gate:

```powershell
hellodev --root $Project do validate --task $TrellisTask
```

Under `strict`, paste the complete returned `resumeCommand` unchanged. On successful validation, note the typed gate receipt id:

```powershell
$GateReceipt = "receipt-0001" # replace with the observed id
hellodev --root $Project receipt show $GateReceipt
hellodev --root $Project gate status
hellodev --root $Project work current
```

Expected:

- The receipt is a successful typed Trellis `gate` receipt, not a generic command receipt.
- Because the current WorkItem points to the same Trellis task, the command creates an EvidenceLink automatically.
- `gate status` is `aligned`; its evidence and WorkItem fingerprints match the current capability fingerprint.
- No human verification receipt is needed for finish alignment. Cross-project lesson persistence still requires separate verification.

Finish can now proceed:

```powershell
hellodev --root $Project do finish --note "Current native gate passed"
hellodev --root $Project resume
```

To test explicit reconciliation, use the successful typed receipt produced while that same WorkItem/fingerprint was current:

```powershell
hellodev --root $Project gate reconcile $GateReceipt
```

Reconciliation is idempotent for the same execution-bound work/receipt/fingerprint link and never runs or mutates Trellis. A generic receipt, unbound typed receipt, different-task receipt, failed receipt, unknown id, or stale WorkItem must fail closed. Automatic reconciliation is attempted only when `do validate --task` matches the selected Trellis WorkItem; explicit `gate reconcile` verifies an existing receipt binding and cannot create authority retroactively.

## Scenario D: stale fingerprints invalidate evidence

Do this only in the disposable copy. Change a fingerprinted input such as `.trellis/workflow.md` or the root `AGENTS.md`, then inspect without finishing:

```powershell
Add-Content -LiteralPath (Join-Path $Project ".trellis\workflow.md") -Value "`n<!-- disposable F2 fingerprint check -->"
hellodev --root $Project capabilities status
hellodev --root $Project gate status
hellodev --root $Project resume
```

Expected: capabilities are stale, the old EvidenceLink cannot satisfy current finish, and resume recommends `hellodev capabilities refresh` first. Restore the disposable file or keep the intentional change, then rebuild current bindings:

```powershell
hellodev --root $Project capabilities refresh
hellodev --root $Project work refresh
hellodev --root $Project gate status
```

The earlier link remains auditable but stale. Run current validation again and paste its exact approval continuation to create new current evidence. Do not treat an old generic receipt or old link as proof for changed project content.

## Scenario E: hash-only LessonProposal and Saga recovery

Project-scoped lessons produce a Trellis placement plan and a hash-only proposal; HelloDev does not invent or execute a repository write:

```powershell
$ProjectLesson = "This disposable repository requires its native integration gate before release"
hellodev --root $Project do remember --lesson $ProjectLesson --scope project
hellodev --root $Project lesson list
hellodev --root $Project lesson show lesson-0001
```

Inspect all `.hellodev/` files and confirm `$ProjectLesson` is absent. The proposal contains `lessonSha256`, destination/scope, state, ids, and timestamps only.

For the optional cross-project path, first verify a successful gate receipt as human-reviewed evidence:

```powershell
$GateReceipt = "<current-successful-gate-receipt>"
hellodev --root $Project saga create "F2 cross-session lesson acceptance"
$Saga = "<observed-saga-id>"
hellodev --root $Project saga attach $Saga $GateReceipt
hellodev --root $Project saga verify $Saga $GateReceipt --evidence "Disposable gate result reviewed"
hellodev --root $Project saga next $Saga
```

With a disposable public Nocturne MCP configured, prepare remember:

```powershell
$Lesson = "Always keep cross-project handoffs compact"
hellodev --root $Project do remember `
  --lesson $Lesson `
  --scope cross-project `
  --receipt $GateReceipt `
  --saga $Saga
```

Expected: the command creates/reuses a hash-only LessonProposal and returns an `APPROVE-WRITE` same-command continuation containing `--proposal <id>`. Start a new terminal/process and paste the complete `resumeCommand` unchanged. The original lesson is re-supplied on the command line for digest validation; it is not recovered from state.

After a successful disposable Nocturne write:

```powershell
hellodev --root $Project saga next $Saga
```

Use the returned verification command with real evidence. Final successful verification completes the linked LessonProposal. At each intermediate phase, `saga next` must return one phase-correct action. Repeating prepare must reuse the same proposal/Saga. A failed partial chain may be reviewed and terminally removed from automatic resume with `hellodev saga close <id>`; a chain with an unverified Nocturne write cannot be closed. Supplying a different lesson with the same `--proposal`, or a proposal/Saga/evidence id from a different flow, must fail closed.

If disposable Nocturne is unavailable, record this branch as not run. `do remember` must report configuration/evidence requirements without writing memory; the WorkItem/gate/resume acceptance remains mandatory.

## Scenario F: deterministic delegation budgets

Create one truly parallel proposal:

```powershell
$Parallel = @{
  task = "Review independent F2 release surfaces"
  intent = "review"
  parallelizable = $true
  sharedContext = "HelloDev 0.9.0; no upstream patches; report findings only."
  candidates = @(
    @{ role = "tests"; objective = "Review regression coverage"; contextDelta = "Inspect F2 contract and CLI tests." },
    @{ role = "docs"; objective = "Review user documentation"; contextDelta = "Inspect upgrade and safety claims." }
  )
  limits = @{ maxAgents = 2; sharedBytes = 4096; perAgentBytes = 4096; totalReportedTokenBudget = 4000 }
} | ConvertTo-Json -Depth 6 -Compress

hellodev --root $Project delegate plan --payload $Parallel
hellodev --root $Project delegate pack --payload $Parallel --role tests --token-budget 1200
```

Expected: `decision: delegate`; at most two selected roles; the pack contains shared context once and only the `tests` delta; byte count is within the hard UTF-8 ceiling (pack budget minimum 512); `executionPerformed`, `persistencePerformed`, adapter calls, and model calls remain empty/false.

Authority-sensitive work must stay with the main agent:

```powershell
$Serialized = $Parallel | ConvertFrom-Json
$Serialized.intent = "remember"
$Serialized = $Serialized | ConvertTo-Json -Depth 6 -Compress
hellodev --root $Project delegate plan --payload $Serialized
```

Expected: `decision: main-only` with `serialized-or-authority-sensitive-intent`. The caller-provided token numbers are ceilings, not measured usage, and the proposal/pack is not persisted.

## Scenario G: privacy-preserving audit and recovery hints

```powershell
hellodev --root $Project audit export
hellodev --root $Project doctor --fix-hints
```

Expected:

- Both are read-only and make no adapter/model call.
- Audit reports a SHA-256 of the selected root, not the plaintext root.
- WorkItems remain pointers; LessonProposals remain hashes; Sagas are summaries.
- No task body/PRD, raw query, lesson, memory body, verification text, adapter output, approval token, delegation context, or exact host token estimate appears.
- `persisted: false`; running the commands does not create a report file.
- Fix hints contain deterministic commands only and do not execute them.

For a targeted privacy scan, choose unique canary strings in the disposable task/lesson/verification inputs, then search `.hellodev/`. Expected matches for raw private canaries: zero. Digest/id metadata is expected.

## Scenario H: Control Center remains read-only

```powershell
hellodev --root $Project dashboard start
hellodev --root $Project dashboard status
hellodev --root $Project dashboard stop
```

The browser may display F2 resume, WorkItem, gate, and LessonProposal summaries and may build/copy CLI commands. It must not execute an adapter, consume approval, change a profile/policy, reconcile evidence, spawn/delegate an agent, advance a Saga, or write a task/lesson. There is no dashboard execution API in 0.9.0.

## Acceptance record

Record observed facts rather than prepared plans:

```text
Candidate version/artifact: <0.9.0 wheel or source and hash>
Disposable project provenance: <path/source, no live data>
Trellis version/surface: <observed>
0.8 state loaded without eager F2 stores: <pass/fail>
WorkItem pointer-only inspection: <pass/fail, id/nativeRef>
Cross-process resume stability: <pass/fail, command/reason>
Strict finish before current gate: <blocked/pass/fail>
Typed gate + automatic EvidenceLink: <pass/fail, receipt/link ids>
Stale fingerprint invalidation: <pass/fail>
LessonProposal raw-text scan: <pass/fail, proposal id>
Saga next/completion: <pass/fail/not-run and why>
Delegation plan/pack budgets: <pass/fail>
Audit/fix-hints privacy and read-only behavior: <pass/fail>
Control Center read-only F2 projection: <pass/fail>
External writes automatically executed: 0
Exact token usage invented by HelloDev: 0
Known compatibility gaps: <explicit list>
```
