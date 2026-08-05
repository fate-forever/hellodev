# HelloDev Recovery Reference

Load this reference only when an interruption, repeated `reasonCode`, lifecycle/task
drift, stale verification, approval problem, or blocked finish cannot be resolved by
the first returned `nextAction`.

## Recovery Order

1. Run the exact `nextAction` once.
2. After a process or session interruption, run `hellodev resume` or the root-bound
   equivalent returned by MCP.
3. If the same `reasonCode` remains twice, stop all mutations and collect:
   - `hellodev --json next`
   - `hellodev --json resume`
   - `hellodev --json status --verbose`
4. Show the bounded outputs to the user. Ask them to review task binding, lifecycle
   phase, latest receipt, and any external component state.

## Common States

| State or reason | Required response |
|---|---|
| `finish-requires-checking-phase` | Execute the returned check action. Do not retry finish. |
| `closure-transaction-recovery-required` | Follow resume/next; an existing native completion must not be executed again. |
| `verification-session-pending` | Run the host command, then record its real outcome using the returned command. |
| stale verification or snapshot mismatch | Rerun only the required gate against current source and record a new result. |
| `dynamic-escalation-diagnostic-required` | Record one bounded root cause and a genuinely different strategy before more edits. |
| awaiting confirmation | Explain action, scope, and risk; use the exact one-time resume command only after approval. |
| ambiguous legacy closure receipt | Stop and request manual audit; do not choose the newest receipt by guesswork. |

## Never Repair By

- Editing `.hellodev/`, `.trellis/` task status, receipt, gate, or transaction JSON.
- Reusing or reconstructing an approval token.
- Calling a native Trellis completion command to make the Dashboard look aligned.
- Reporting a proposed test, context validation, or approval as a successful test.
- Repeating an unchanged failing command after strict escalation.
