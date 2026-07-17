# Case study: a recoverable local documentation task

This is a reproducible local case, not a claim about an external production
deployment. It uses only HelloDev Core and a disposable repository.

## Task

Create and complete a small documentation task while preserving a resumable,
auditable project-local workflow.

## Flow

```text
hellodev open
hellodev do task create --title "Document the minimal HelloDev flow"
hellodev do plan
hellodev do work
hellodev do check
hellodev do finish
hellodev resume --context --token-budget 256
hellodev policy checkpoint export
```

Observed behavior:

- No `.trellis/` was required; task and lifecycle state remained local.
- `next` exposed one command at a time.
- `resume` reconstructed phase, WorkItem/Saga/gate state, pending Host/transaction
  state, checkpoint state, and one next command without calling an adapter.
- Checkpoint verification compared the local policy ledger head without
  claiming tamper-proof storage.
- No Nocturne memory, external write, model call, or subagent was required.

## Reliability evidence

The public demo does not fake a power failure. Transaction interruption is
covered by deterministic fault-injection and multi-process tests for:

- failure before WAL persistence;
- interruption after WAL authorization;
- interruption after token consumption;
- receipt persisted before the WAL receipt phase;
- policy ledger append before final WAL completion;
- concurrent idempotent recovery.

## Limitations

- The local hash chain needs an independently retained checkpoint to detect a
  complete internally consistent history rewrite.
- Host-reported usage is not provider-attested.
- Trellis and Nocturne integration require their own configured installations.
- Control Center remains read-only and cannot execute recovery or adapter calls.
