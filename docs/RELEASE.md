# HelloDev Core 0.20.9 release checklist

0.20.9 adds lossless acceptance-source binding and managed atomic closure while preserving the 0.20.8 overhead repairs, Trellis authority, one-time authorization, six MCP tools, the six-field default `open`, host-asserted trust labels, and a non-executing Core.

## Required checks

1. Version `0.20.9` agrees in package metadata, `__version__`, component lock/schema, bundle metadata, Dashboard, README and tests.
2. A Trellis task set containing `README.md` or `.gitkeep` does not conflict between prepare and run.
3. `do begin` discloses a conservative closure plan, including host command, level and scope.
4. Windows npm launcher aliases share an evidence hash only for explicitly supported, metacharacter-free forms.
5. Repeated `--result-json` or PowerShell-safe `--result` records 1-16 current-snapshot results atomically and refreshes the WorkItem projection.
6. Trellis completion writes mergeable, hash-only `.gates/hellodev-quality.json` without overwriting a user gate.
7. Fresh/unbound `open` returns exactly one structured `begin-work` action and never recommends `do plan`.
8. Daily lifecycle and verification operations fail closed without the required WorkItem/AcceptanceContract identity.
9. `finishPolicy=suggest` never permits missing identity or unsatisfied acceptance.
10. Trellis `task-begin` is one-approval, recoverably idempotent and binds task, WorkItem and AcceptanceContract without native fallback.
11. Multiple Trellis tasks select only one uniquely aligned candidate; ambiguity returns bounded exact actions.
12. Manifest-first ordered verification, snapshot invalidation and unchanged-failure diagnostics remain intact.
13. Dashboard schema 23 exposes only sanitized binding/closure integrity and a compact next action.
14. A project-relative UTF-8 `--requirements-file` is copied exactly with a stable digest; unsafe, missing or changed sources fail closed.
15. A strict change spanning more than ten files cannot close from a summary-only contract.
16. WorkItem-backed low-level lifecycle completion is rejected; managed finish requires active Trellis state, task-complete receipt, mergeable quality evidence and a refreshed finished WorkItem.
17. Focused, compatibility, fast/full, compile and Dashboard syntax gates pass.
18. A clean isolated wheel reports the expected version, six MCP tools and six-field default `open`.

## Publication boundary

Building `dist/hellodev_core-0.20.9-py3-none-any.whl` is local validation only. Git push, tag, GitHub Release, PyPI upload, release snapshot, bundle publication, global installation and user configuration changes require separate user authorization.
