---
name: hellodev
description: Follow HelloDev's governed coding workflow in a project that has `.hellodev/`, exposes HelloDev MCP tools, or explicitly asks to use HelloDev. Use for starting, implementing, verifying, resuming, diagnosing, or finishing a managed development task without bypassing its AcceptanceContract, approval, Trellis, or lifecycle boundaries.
---

# HelloDev Workflow

Use HelloDev as the control plane while using the host's normal read, search, edit,
shell, and test tools for implementation. Treat returned commands and evidence as
project-bound; never infer success from an Agent statement alone.

## Start Or Resume

1. Read the repository's applicable `AGENTS.md`. When `.trellis/` exists, read its
   workflow and current task state before planning or editing.
2. Prefer the six root-bound HelloDev MCP tools. Otherwise use the project's known
   `hellodev` executable; do not search for or install a different version silently.
3. Call `hellodev_open`. For an unbound task, execute the returned `begin-work`
   action using the user's goal and acceptance. Preserve a multi-line production
   brief in a project-relative UTF-8 requirements file when exact binding is needed.
4. Continue through the single authoritative `nextAction`. Do not explore help,
   status, gates, receipts, or native Trellis commands while a usable action exists.

## Implement And Verify

- Execute `hostCommand` in the exact returned `cwd` with the host shell.
- Record success only when the real exit status succeeded; otherwise execute the
  returned failure-recording command and diagnose before changing strategy.
- Treat verification as `executor=host` and `host-asserted`. Do not claim that
  Trellis context validation, a test proposal, or approval proves project tests.
- After source changes, expect snapshot-bound evidence to require a new result.
- Finish only through `hellodev do finish`; never complete the native Trellis task
  or lifecycle directly.

## Handle Approval

Explain the exact action, scope, and risk to the user. After explicit approval,
execute only the returned `resumeCommand`. Never reconstruct it, broaden it, reuse
its token, or treat approval as evidence of success.

## Recover Without Guessing

On the first failure, execute only the returned repair action. After interruption,
use `hellodev_resume`. If the same `reasonCode` appears twice, stop modifying code
or state, read [recovery.md](references/recovery.md), collect the bounded `next`,
`resume`, and verbose status outputs, and ask the user to review the blocker.

Never guess commands such as `done` or `gate close`, repeatedly call `finish`, edit
`.hellodev` JSON, reuse an approval token, or invoke Trellis directly to bypass a
managed blocker.

## Preserve Boundaries

- Trellis owns native project tasks, specs, and gates.
- Nocturne is advisory cross-project memory and cannot authorize an operation.
- HelloDev owns managed workflow, evidence binding, recovery, and closure.
- The host Agent owns code changes and command execution.
- Repository facts override recalled memory.
