# HelloDev 0.11.0 host and policy-evolution demo

This is the advanced acceptance path for HostEnvelope/HostCompletion, staged tighten-only policy canaries, explicit commit/revert, local hash-chain integrity, and read-only drift reporting. It supplements rather than replaces the daily `open -> next -> do` flow.

Use a disposable project. Do not point this demo at an irreplaceable Trellis repository, live Nocturne data, a user plugin cache, or global configuration.

## Prerequisites

- `hellodev --version` reports `0.11.0` from the candidate source or wheel.
- The project is a disposable copy or empty temporary directory.
- No Bootstrap/global install, Codex/Cursor configuration mutation, live memory write, or Dashboard execution is part of this demo.
- Capture JSON with `hellodev --json`; do not paste approval tokens into evidence files.

```powershell
$Project = Join-Path $env:TEMP "hellodev-v11-evolution-demo"
New-Item -ItemType Directory -Force -Path $Project | Out-Null
hellodev --root $Project open
hellodev --root $Project next
```

Expected: the normal path remains `open -> next -> do`. No host/policy store is required for daily use.

## Scenario A: read-only host preparation

Record the initial file set, then prepare an envelope:

```powershell
$Before = Get-ChildItem -Recurse -File (Join-Path $Project ".hellodev") | Select-Object -ExpandProperty FullName
$Envelope = hellodev --json --root $Project host prepare `
  --intent code `
  --level L1 `
  --total-token-ceiling 4000 `
  --subagent-token-ceiling 1500 `
  --max-subagents 2 `
  --ttl 3600 | ConvertFrom-Json
$After = Get-ChildItem -Recurse -File (Join-Path $Project ".hellodev") | Select-Object -ExpandProperty FullName
```

Verify:

- `$Before` and `$After` contain no new host/policy/optimization store caused by prepare.
- `authorization.grantsExecution=false`.
- `authorization.grantsEvidenceAuthority=false`.
- `authorization.approvalReceiptId` is null.
- The envelope contains bounded context/next/delegation projections, declared ceilings, root/capability/policy/ledger bindings, expiry, nonce hash, and envelope hash.
- The envelope includes no raw task body, memory body, transcript, model output, adapter output, or approval token.

Negative checks:

```powershell
hellodev --root $Project host prepare --intent code --ttl 59
hellodev --root $Project host prepare --intent remember --level L2
```

Expected: invalid TTL and L2 without `--allow-l2` fail closed.

## Scenario B: host completion trust and idempotency

Submit a sanitized result:

```powershell
$Result = @{
  outcome = "succeeded"
  retryCount = 0
  retrievalMode = "none"
  delegationMode = "none"
  totalTokens = 1200
  subagentTokens = 0
  subagentCount = 0
}
$CompletionInput = @{
  envelope = $Envelope
  result = $Result
} | ConvertTo-Json -Depth 30 -Compress

$First = $CompletionInput | hellodev --json --root $Project host complete --stdin | ConvertFrom-Json
$Second = $CompletionInput | hellodev --json --root $Project host complete --stdin | ConvertFrom-Json
hellodev --root $Project host status
```

Expected:

- First completion is recorded and produces a deterministic reflection trace.
- Exact replay returns the same completion instead of duplicating it.
- Usage trust is `host-asserted`, envelope-bound, and not provider-verified.
- No transcript/prompt/raw context/model output is stored.
- The completion cannot be linked as gate/test evidence.

Repeat with `totalTokens=null` and `subagentTokens=null` in a fresh envelope. Expected: usage stays `unavailable`; it is not recorded as zero.

Tamper one envelope field without recomputing its hash, or reuse the envelope with a different result. Expected: both fail closed. Change a bound capability/config input before completing a new envelope. Expected: stale bindings fail and a new envelope is required. Also reject stdin larger than 512 KiB, keys other than exactly `{envelope,result}`, and combining `--stdin` with `--envelope`/`--result`. The argv compatibility form remains supported but is not recommended for envelopes containing bounded context.

## Scenario C: generate and stage a proposal

Create three comparable deterministic reflection reports that yield a retry tightening:

```powershell
hellodev --root $Project optimize reflect --intent code --context-level L1 --outcome partial --retries 2
hellodev --root $Project optimize reflect --intent code --context-level L1 --outcome partial --retries 3
hellodev --root $Project optimize reflect --intent code --context-level L1 --outcome partial --retries 4
$Proposals = hellodev --json --root $Project optimize proposals | ConvertFrom-Json
$Proposal = $Proposals.proposals[0].id
$BeforePolicy = hellodev --json --root $Project policy status | ConvertFrom-Json
hellodev --root $Project policy stage --proposal $Proposal
$StagedPolicy = hellodev --json --root $Project policy status | ConvertFrom-Json
```

Verify:

- The proposal targets only `retry.maxAttempts` or `delegation.effectiveMaxAgents` with an integer tighten-only patch.
- Stage succeeds without approval.
- `committedPolicy` and `effectivePolicy` are unchanged after stage.
- The ledger head advances and an active stage is visible.
- Staging another proposal or a stale proposal fails.

Exercise the non-effective escape hatch, then restage for the canary:

```powershell
hellodev --root $Project policy cancel --proposal $Proposal
hellodev --root $Project policy cancel --proposal $Proposal
hellodev --root $Project policy stage --proposal $Proposal
```

Expected: the first cancel appends `cancel-stage`, the identical second cancel is idempotent, and effective/committed policy never changes. A wrong proposal fails. `policy cancel` cannot cancel an active canary; that requires separately approved revert.

## Scenario D: independently approved canary

Prepare the canary action:

```powershell
$CanaryPrepare = hellodev --json --root $Project policy canary `
  --proposal $Proposal --turns 2 --ttl 3600 | ConvertFrom-Json
```

Expected: `state=awaiting-confirmation` and `resumeCommand` contains the same proposal/turn/TTL plus one exact approval. Effective policy has not changed yet.

Execute the exact returned command, or equivalently in the disposable shell:

```powershell
$Canary = hellodev --json --root $Project policy canary `
  --proposal $Proposal --turns 2 --ttl 3600 `
  --approve $CanaryPrepare.approval | ConvertFrom-Json
hellodev --root $Project policy status
```

Verify:

- `state=canary-active`.
- The tighter canary policy is now the effective overlay; committed policy is unchanged.
- The approval token is absent from the ledger and receipts.
- Replaying the approval, changing turns/TTL, or using it for commit/revert fails.
- `--approve` and `--receipt` together fail.

Receipt-recovery check: in a controlled fault-injection test, interrupt after the exact policy receipt is recorded but before the ledger append. Resume with `--receipt <that-receipt-id>` and the same action. If the event was already appended, the same receipt/action returns the existing event idempotently. A mismatched phase, proposal, turn/TTL scope, or action receipt must fail. Do not fabricate or edit a receipt file for this test.

Receipt-preflight check: in a disposable fault fixture, make the receipt store invalid/unsafe before submitting a fresh `--approve`. The command must fail before consuming the token. Repair the fixture through the controlled test harness, then the same token must remain usable for its exact action.

## Scenario E: canary HostCompletions and evaluation

Create exactly two fresh envelopes after canary activation and complete each successfully:

```powershell
1..2 | ForEach-Object {
  $E = hellodev --json --root $Project host prepare `
    --intent code --total-token-ceiling 2000 --max-subagents 0 | ConvertFrom-Json
  $R = @{
    outcome = "succeeded"
    retryCount = 1
    retrievalMode = "none"
    delegationMode = "none"
    totalTokens = 1000
    subagentTokens = 0
    subagentCount = 0
  }
  @{
    envelope = $E
    result = $R
  } | ConvertTo-Json -Depth 30 -Compress |
    hellodev --root $Project host complete --stdin
}

hellodev --root $Project policy evaluate --proposal $Proposal
hellodev --root $Project drift status
```

Expected:

- Before the second completion, evaluate is `pending` with insufficient completions.
- After both, evaluate is `passed` and binds exactly the two current-canary completion ids.
- After the second non-late same-head completion, policy status is `canary-exhausted`: effective policy has returned to committed policy while the first two records remain fixed for evaluation/commit and public `observedTurns` stays capped at 2.
- A two-process race for a one-turn canary accepts exactly one completion; the other fails stale and `completionCount` remains 1.
- Drift is `clean`.
- Completions from an older ledger head, late envelopes, or records beyond turnLimit are not selected and cannot extend the canary overlay. A fresh post-exhaustion completion may still be recorded under committed policy, but it does not grow the first-N evidence sample or public turn count.

Run disposable negative variants: failed/partial outcome, retry above effective limit, subagent count above effective limit, declared budget exceeded, or canary expiry. Expected: evaluate fails and commit preparation is unavailable.

## Scenario F: commit with a new approval

```powershell
$CommitPrepare = hellodev --json --root $Project policy commit `
  --proposal $Proposal | ConvertFrom-Json
$Commit = hellodev --json --root $Project policy commit `
  --proposal $Proposal --approve $CommitPrepare.approval | ConvertFrom-Json
hellodev --root $Project policy status
```

Verify:

- Commit preparation was unavailable until evaluate passed and drift was clean.
- The commit approval is different from and cannot reuse the canary approval/receipt.
- The commit event binds the bounded unique HostCompletion ids used by evaluation.
- Only now does committed policy change.

## Scenario G: separately approved bounded revert

```powershell
$RevertPrepare = hellodev --json --root $Project policy revert | ConvertFrom-Json
$Revert = hellodev --json --root $Project policy revert `
  --approve $RevertPrepare.approval | ConvertFrom-Json
hellodev --root $Project policy status
hellodev --root $Project policy revert
```

Verify:

- Revert uses a third independent exact approval.
- It restores only the immediate previous committed policy with `restore-previous-committed` patches.
- The final unapproved `policy revert` fails because no active canary or latest commit remains to revert.
- Arbitrary historical policy selection is not available.

Recovery edge: after commit, create and stage another current proposal. Commit rollback must be blocked while that stage is active. Cancel the staged proposal, then prepare revert. The later non-effective stage/cancel events must not erase the immediate commit rollback target; revert still restores the prior committed policy.

Also test reverting an active canary before commit. Expected: it returns to committed policy and does not pretend the proposal was committed.

## Scenario H: hash-chain and external checkpoint limits

Capture the current head from `policy status` outside the project state directory, then compare it:

```powershell
$Policy = hellodev --json --root $Project policy status | ConvertFrom-Json
$Checkpoint = $Policy.ledgerHead.eventSha256
hellodev --root $Project drift status --expected-head $Checkpoint
hellodev --root $Project drift status --expected-head GENESIS
```

Expected: the matching checkpoint is clean; the mismatched checkpoint is detected.

In disposable copies only, alter one event field, break a `previousEventSha256`, or alter only the stored head. `policy status`/`drift status` must report invalid/detected and must not repair the file.

Security statement to preserve in evidence: the project-local hash chain proves only internal structural continuity. An actor who can rewrite every event and the stored head can create a different valid local chain. Detection of that attack requires an independently retained checkpoint. This is not a transparency log, remote witness, tamper-proof ledger, or non-repudiation system.

## Scenario I: late and unavailable host results

Use a disposable test clock/fixture or a 60-second TTL to complete an envelope after expiry. Expected:

- Completion is retained with `late=true`.
- Drift may report the late completion as informational.
- It does not satisfy current canary evaluation.

Complete another fresh envelope with both token fields null. Expected:

- `usageTrust=unavailable`.
- No zero token total is invented.
- Policy evaluation still checks outcome/retry/subagent/budget state without claiming provider-verified usage.

## Scenario J: Control Center is schema-v4 copy-only

```powershell
hellodev --root $Project dashboard start
hellodev --root $Project dashboard status
hellodev --root $Project dashboard stop
```

Verify the authenticated status projection:

```json
{
  "schemaVersion": 4,
  "uiCapabilities": {
    "copyOnly": true,
    "applyAllowed": false,
    "commitAllowed": false,
    "revertAllowed": false,
    "actionApiAvailable": false
  }
}
```

The only new advanced commands it may expose are:

```text
hellodev host status
hellodev policy status
hellodev drift status
```

It must not expose or execute host complete, policy stage/cancel/canary/commit/revert, approvals/receipts, full envelopes, policy values, ledger hashes, raw findings, repair commands, adapters, models, or any project-state mutation.

## Acceptance record

```text
Candidate version/artifact: <0.11.0 source or wheel and hash>
Daily open->next->do unchanged: <pass/fail>
Host prepare read-only/bounded/non-authoritative: <pass/fail>
Host complete stale/tamper/conflict/idempotency: <pass/fail>
Host complete strict stdin/512-KiB/argv-exclusion: <pass/fail>
Host-asserted vs unavailable usage: <pass/fail>
Late completion excluded from canary: <pass/fail>
Stage does not change effective policy: <pass/fail>
Stage cancel append-only/idempotent/non-effective: <pass/fail>
Canary independent approval and tighter overlay: <pass/fail>
Canary turn exhaustion restores committed effective policy: <pass/fail>
Evaluate full bounded sample: <pass/fail>
Commit new approval + clean drift + evidence ids: <pass/fail>
Revert third approval + cancelled-stage recovery + second revert failure: <pass/fail>
Receipt recovery exact-action binding: <pass/fail>
Hash-chain tamper and external checkpoint: <pass/fail>
Hash-chain limitation stated accurately: <pass/fail>
Dashboard schema-v4 status-only/copy-only: <pass/fail>
No Bootstrap/global install/UI execution/upstream mutation: <pass/fail>
```
