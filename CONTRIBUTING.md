# Contributing to HelloDev

HelloDev is a standalone Python CLI plus optional platform distribution.
Trellis and Nocturne source trees are not copied into the Core repository;
verified platform bundles may carry separately licensed payloads and runtimes.

## Development setup

Requirements:

- Python 3.10–3.12
- Node.js only for the optional Dashboard JavaScript syntax check

Run the fast suite while developing:

```powershell
python scripts\verify.py --scope fast
```

Run the full release gate before submitting a change:

```powershell
python scripts\verify.py --scope full
```

## Change rules

- Preserve the daily `open -> next -> do` contract.
- External writes and effective policy changes must remain explicitly approved.
- Memory, HostEnvelope, Dashboard, and optimization output cannot grant authority.
- Never persist approval tokens, task/memory bodies, HostEnvelope context, or raw transcripts.
- Keep Host usage `host-asserted` or `unavailable`; never call it provider-verified.
- Keep the Control Center read-only and copy-only.
- Do not copy Trellis/Nocturne source into Core or merge their data stores.
- Bundle manifests must be strict, path-safe, complete inventories; corrupt
  bundled components must never fall back to an ambient PATH executable.
- Never bundle a live Nocturne config/database, project `.trellis/`, cache,
  secret, developer path, or existing user state.
- Keep exact upstream licenses, component locks, notices, SBOM and Trellis
  corresponding source beside every platform archive.

Public behavior changes must update README, Quick Start, release documentation,
and the relevant `docs/ai/` orientation files. New state formats require
nondestructive compatibility tests against prior HelloDev projects.

## Pull requests

Include:

1. the user-visible outcome;
2. focused tests for the changed boundary;
3. privacy and fail-closed cases where applicable;
4. full-gate evidence for release-sensitive changes.

Distribution changes additionally need deterministic fake-bundle tests and an
offline smoke of every exact platform archive that will be advertised. Passing
source tests alone is not evidence that a platform bundle is self-contained.

Please do not commit build directories, wheels, virtual environments, runtime
`.hellodev/` state, credentials, private tasks, or memory content.
