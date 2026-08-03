# HelloDev component protocol 0.20.9

## 0.20.9 acceptance and closure contract

- `requirementsSource` binds a project-relative, regular, non-symlink UTF-8
  file to an AcceptanceContract by exact bounded content and SHA-256.
- A bound source is immutable for the active contract; changing or removing
  the source invalidates acceptance integrity.
- Strict wide changes require a bound source before acceptance can close.
- A WorkItem-backed `finished` transition is internal to managed closure.
- Managed Trellis closure verifies task completion receipt, native completed
  state, WorkItem-bound quality evidence and the refreshed finished WorkItem.
- The ordered writes are recoverable and fail closed; they are not described
  as a cross-file ACID transaction.

## 0.20.8 measured-overhead contract

- Trellis task-set identity is derived only from valid, non-symlink task
  directories; ordinary files below `.trellis/tasks` are not tasks.
- A prepared task operation and its execution use the same bounded identity.
- Host verification may submit 1-16 result objects atomically. Trust remains
  `host-asserted`, commands are persisted by hash, and raw output is excluded.
- A higher-level project-scoped success covers a narrower same-command check
  only when WorkItem and full repository snapshot identities match. Exact
  failure evidence takes precedence.
- Only explicitly supported Windows npm launcher aliases are canonicalized;
  shell metacharacters prevent equivalence inference.
- HelloDev quality evidence is merged by verification id into the bounded
  `.gates/hellodev-quality.json` projection. It does not overwrite Trellis or
  user-owned `quality.json` evidence.

HelloDev recognizes `hellodev@trellis` and `hellodev@nocturne` as independently licensed, independently authoritative component identities. Core does not merge their databases or silently broaden their permissions.

## Trellis

- Trellis owns native task/spec/gate state.
- HelloDev binds WorkItems by safe reference and digest.
- Read/write component operations use the existing prepare, one-time approval and receipt/WAL contract.
- `task-validate` records context validation only: `qualityGateSatisfied=false`.
- Project tests and type checks are host-executed verification evidence, never inferred from Trellis context validation.

## Nocturne

- Recall is advisory and bounded.
- External reads/writes retain explicit authorization rules.
- HelloDev stores sanitized receipts and digests, not raw memory bodies.
- Missing provider usage or namespace guarantees remain unavailable rather than estimated.

## 0.20.7 bootstrap and closure contract

`task-begin` is the bounded create-or-select plus start operation used by the HelloDev daily facade. One exact approval covers one operation identity. The operation ledger makes replay idempotent; success is followed by a WorkItem, AcceptanceContract and task-binding record. Failure remains recoverable through the returned HelloDev command and does not authorize a native Trellis fallback. Multiple tasks are automatically selected only when exactly one bounded alignment is meaningful.

`plan` requires a current WorkItem. `work`, `verify`, `check` and `finish` require a current WorkItem and AcceptanceContract. `finish` additionally requires current acceptance evidence. A suggest policy may relax supplemental gates but never these identity invariants.

## 0.20.6 verification contract

Manifest-first discovery returns an ordered list of safe project commands. HelloDev exposes one host action at a time, never shell-chains commands, and binds each host assertion to command, WorkItem, scope and current snapshot. Failed unchanged evidence disables executable action projection until inputs change. Core does not execute commands or persist raw command output.
