# Why HelloDev

HelloDev is a local orchestration and governance layer for AI-assisted software
development. It is not a chatbot application, model runtime, replacement for an
IDE agent, or a second knowledge database.

## The problem it addresses

When a development agent uses a repository workflow, long-term memory, external
tools, subagents, and token budgets together, the missing layer is often not
retrieval. It is deterministic coordination:

- Which system owns the current fact?
- What context should be loaded?
- Which operation needs explicit approval?
- How does an interrupted multi-step operation resume?
- Which evidence is allowed to influence policy or long-term memory?
- How are unavailable usage values represented honestly?

## Boundaries

- Trellis remains repository workflow authority.
- Nocturne remains optional advisory long-term memory.
- Codex, Cursor, or another host still performs real code execution.
- HelloDev owns only project-local orchestration, receipts, recovery, context
  policy, and bounded efficiency governance.

Unlike graph/orchestration libraries, HelloDev does not ask applications to
define a new model-execution graph. Unlike IDE agents, it does not own the model
session or editor. Unlike RAG systems, retrieval is only one optional input and
cannot authorize an operation.

## What 0.12 adds

- a crash-recoverable policy transaction WAL;
- a typed, version-negotiated Host SDK;
- bounded baseline/canary policy evaluation;
- portable policy-head checkpoints;
- a read-only Control Center projection.

These mechanisms are intentionally local and auditable. They do not make local
state tamper-proof, turn host assertions into provider evidence, or merge
Trellis and Nocturne into one authority.

## Current limitations

HelloDev does not provide remote checkpoint witnessing, provider-attested token
receipts, autonomous memory writes, executable Dashboard controls, worktree
orchestration, or automatic synchronization of upstream task/memory bodies.
