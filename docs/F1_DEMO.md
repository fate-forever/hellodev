# HelloDev 0.8.0 F1 demo

This is the runnable acceptance path for the unified F1 experience. Use a disposable copy of a real project. Never point the demo at a live user-memory database or an irreplaceable working tree.

## Prerequisites

- `hellodev --version` reports `0.8.0`.
- The selected project is a disposable copy.
- For Trellis scenarios, the copy contains a real `.trellis/` directory and its normal scripts.
- For optional memory scenarios, configure a disposable public Nocturne stdio MCP process. Do not use private REST or direct database access.

Set the project once:

```powershell
$Project = "C:\path\to\disposable-trellis-project"
hellodev --root $Project --version
```

All examples keep `--root` explicit so an approval is visibly bound to the intended project.

## Scenario A: foolproof daily flow

```powershell
hellodev --root $Project open
hellodev --root $Project next
hellodev --root $Project do plan --note "Acceptance scope agreed"
hellodev --root $Project do task list
```

Under the default `strict` profile, the Trellis read returns `state: awaiting-confirmation`. Copy the complete `resumeCommand` from the output and paste it unchanged. It will still be a `hellodev ... do task list ... --approve ...` command.

Continue:

```powershell
hellodev --root $Project do work --note "Implementation started"
hellodev --root $Project next
hellodev --root $Project do check --note "Focused checks complete"
```

Expected properties:

- Re-running `open` does not reset the progressed phase.
- `next` performs no adapter call and returns exactly one command.
- Compact `status` and `next` each include `suggestedLevel`.
- Local lifecycle writes do not need an external approval token.

## Scenario B: deterministic context selection

```powershell
hellodev --root $Project context suggest --intent status
hellodev --root $Project context suggest --intent code
hellodev --root $Project context suggest --intent remember
hellodev --root $Project brief build --intent code
hellodev --root $Project context pack --intent code --token-budget 1200
```

Expected levels are L0, L1, and L2 respectively. `context suggest` reports no adapter calls. Test an explicit override:

```powershell
hellodev --root $Project context pack --intent code --level L0
```

An L2 brief/pack remains explicit:

```powershell
hellodev --root $Project context pack --intent remember --level L2 --allow-l2
```

## Scenario C: strict and same-command approval

```powershell
hellodev --root $Project profile show
hellodev --root $Project do task list
```

Confirm the profile is `strict`, then copy the exact returned `resumeCommand`. After execution:

```powershell
hellodev --root $Project receipt list
```

The command receipt must show `profileUsed: strict` and `authorizationMode: token-required`; it must not contain raw command output or the approval token.

## Scenario D: trusted-local lease

Prepare the policy change:

```powershell
hellodev --root $Project profile set trusted-local --lease-ttl 300
```

Paste the returned same-command `resumeCommand`, then refresh the content fingerprint:

```powershell
hellodev --root $Project capabilities refresh
```

Run one Trellis read:

```powershell
hellodev --root $Project do task list
```

Paste this read's returned `resumeCommand`. The successful result should include a granted lease. Run the same read again:

```powershell
hellodev --root $Project do task list
```

The second matching read should execute with `authorizationMode: lease-allowed`. Change a fingerprinted input such as the disposable project's `.trellis/workflow.md`, or wait for expiry, and verify the next read again asks for exact confirmation. Restore the file before subsequent checks.

This profile check must use the unified `do` command. Low-level native adapter commands remain explicitly approved escape hatches and are not the profile-aware daily path.

## Scenario E: local-first recall without Nocturne

Use an unconfigured disposable project or inspect configuration first:

```powershell
hellodev --root $Project nocturne status
hellodev --root $Project recall --query "a phrase that is unavailable locally"
```

Expected: `state: local-only`, labelled local/inference output, no adapter execution, and no raw query copied into receipts/state.

For a known repository phrase:

```powershell
hellodev --root $Project do recall --query "Use gates"
```

A strong local hit should stop without Nocturne. `--also-memory` is required to request an additional memory plan when local evidence is already sufficient.

## Scenario F: optional narrow Nocturne recall

Configure only a disposable public stdio MCP process:

```powershell
hellodev --root $Project nocturne configure `
  --command "C:\path\to\python.exe" `
  --arg "C:\path\to\nocturne_memory\backend\mcp_server.py" `
  --cwd "C:\path\to\nocturne_memory"
hellodev --root $Project capabilities refresh
```

Under strict or trusted-local:

```powershell
hellodev --root $Project do recall `
  --query "handoff preference unavailable locally" `
  --domain preferences `
  --limit 3 `
  --namespace-scope shared
```

Paste the returned `resumeCommand`. Verify the result is labelled `Long-term memory` and `non-authoritative advisory context`.

To test autopilot-read, compute an expiry no more than 24 hours ahead:

```powershell
$Expiry = (Get-Date).ToUniversalTime().AddHours(1).ToString("yyyy-MM-ddTHH:mm:ssZ")
hellodev --root $Project profile set autopilot-read `
  --memory-domain preferences `
  --memory-limit 3 `
  --expires-at $Expiry
```

Paste the profile's exact `resumeCommand`, refresh capabilities, then repeat the narrow recall:

```powershell
hellodev --root $Project capabilities refresh
hellodev --root $Project do recall `
  --query "handoff preference unavailable locally" `
  --domain preferences `
  --limit 3 `
  --namespace-scope shared
```

Expected: `authorizationMode: profile-auto`. A different domain, limit above 3, expired policy, or stale fingerprint must return to token confirmation. None of these cases permits a write.

## Scenario G: validate, verify, remember

Choose a real native Trellis task directory from the disposable project:

```powershell
$TrellisTask = "<native-trellis-task-directory>"
hellodev --root $Project do validate --task $TrellisTask
```

Under strict, paste the returned `resumeCommand`. A successful validation records a typed `gate` receipt. Note its receipt id, then create and verify a Saga evidence step:

```powershell
$GateReceipt = "receipt-0001"
hellodev --root $Project saga create "Preserve verified cross-project lesson"
$Saga = "saga-0001"
hellodev --root $Project saga attach $Saga $GateReceipt
hellodev --root $Project saga verify $Saga $GateReceipt --evidence "Targeted validation passed"
```

Verification text is stored only as a SHA-256 digest. With the disposable Nocturne adapter configured, prepare remember:

```powershell
hellodev --root $Project do remember `
  --lesson "Always keep cross-project handoffs compact" `
  --scope cross-project `
  --receipt $GateReceipt `
  --saga $Saga
```

Even under `autopilot-read`, this returns an `APPROVE-WRITE` same-command continuation. Paste it exactly. The result is `verification-required`; execute the returned Saga verification command with real evidence.

For a project-only lesson, verify that HelloDev produces a placement suggestion rather than writing an invented spec/ADR path:

```powershell
hellodev --root $Project do remember `
  --lesson "This repository requires its integration gate before release" `
  --scope project
```

Finish only suggests remember:

```powershell
hellodev --root $Project do finish
```

Confirm `rememberSuggestion.writePerformed` is false.

## Scenario H: Control Center is copy-only

```powershell
hellodev --root $Project dashboard start
hellodev --root $Project dashboard status
hellodev --root $Project dashboard stop
```

The browser may display `next` and build/copy commands. It must not execute an adapter, consume an approval, change a profile, or write a task/lesson. Those actions remain CLI-only in 0.8.0.

## Acceptance record

Record facts, not assumptions:

```text
Project source: <disposable-copy path/provenance>
Trellis version/surface: <observed>
Strict flow: <pass/fail and receipt ids>
Trusted-local flow: <pass/fail and lease receipt id>
Nocturne flow: <pass/fail/not-run and why>
Writes automatically executed: 0
Raw token/query/lesson/memory content found in state: 0
Known compatibility gaps: <list>
```
