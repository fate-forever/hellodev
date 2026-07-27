# HelloDev Core 0.19.6 release checklist

0.19.6 keeps Trellis authoritative underneath while enforcing HelloDev as the
daily task, lifecycle, validation and recovery facade. Host rules and MCP
instructions classify direct Trellis use as an advanced escape hatch; finished
native work re-enters through `do begin`, strict gate recovery prefers
`do validate`, and read-only facade diagnostics disclose only HelloDev-observed
generic escape receipts. It keeps six MCP tools and Dashboard schema v15 /
Control Center 2.6. Its adaptive Trellis execution projection selects one
quick/standard/strict host check, reuses exact successful evidence, and refuses
blind retries of unchanged failures without executing tests or mutating Trellis.

The source publication and a self-contained platform bundle are separate
deliverables. Pushing the Core source does not mean that an archive, GitHub
Release, PyPI package or bundled Trellis/Nocturne runtime exists.

## 1. Version and source boundary

Confirm `0.19.6` agrees in:

- `pyproject.toml` and `src/hellodev/__init__.py`;
- README, Quick Start and this checklist;
- `src/hellodev/distribution/component-lock-v1.json`;
- `src/hellodev/schemas/component-bundle-v1.schema.json`;
- Dashboard markup, release scripts and version tests.

Confirm the Core source contains no FastCtx source/binary/Pdfium payload. The
native Context Plane must remain complete without FastCtx. Any compatibility
snippet must be project-scoped, marked non-required/non-recommended, and never
reported as an active MCP connection or a second daily interface.

Confirm Antigravity onboarding writes only project-level `.agents/` files,
preserves unrelated MCP servers, refuses conflicting `hellodev` entries and
never writes `~/.gemini`. Verify the exact six MCP tools after onboarding and
verify `open` reports unavailable usage without invoking Codex collection.

The editable source is `packages/hellodev-core`. GitHub publication must use an
independent real working copy. Preserve all existing `outputs/` snapshots,
installed caches and tags; never link them to the editable source.

## 2. Agent-first documentation gate

README and Quick Start must begin with a copyable Codex/Cursor protocol before
manual commands. Verify that the protocol:

- lets the Agent install, integrate and run ordinary commands;
- requires reading `AGENTS.md` and any existing Trellis workflow/task state;
- prefers an exact verified bundle only when that asset really exists;
- states that `git clone` contains only HelloDev Core;
- never claims the source checkout carries Trellis, Nocturne, Python or Node;
- never documents a nonexistent bootstrap script or an unpublished PyPI path;
- limits host changes to project configuration and preserves conflicting data;
- keeps approval, external writes and product choices human-confirmed;
- leads with `onboard -> open -> do begin -> next -> do` and keeps `resume` as recovery;
- states that Core onboarding reuses existing external components and never invents a Nocturne command;
- states that `begin` preserves Trellis approval and fails closed on ambiguous task selection.
- tells the host to execute planned checks, record the exact snapshot outcome,
  and keep final Trellis validation authoritative.

Run the Markdown link/fence regression in `tests.test_v121_oss` and inspect the
rendered first screen before publication.

## 3. Core application and MCP gate

Verify:

- `ProjectClient` binds one canonical root and has no cross-call approval cache;
- `open`, `next`, `resume`, `status`, `context` and `do` preserve result shapes;
- per-intent allowlists reject unknown fields;
- finish still checks gate policy;
- Trellis and Nocturne use existing prepare/approve/receipt/Saga paths;
- every profile continues to require confirmation for writes;
- the base wheel has no unconditional dependencies or `mcp` import;
- `hellodev-core[mcp]` remains pinned to `mcp==1.28.1`;
- the stdio gateway exposes exactly six root-bound tools:

```text
hellodev_open
hellodev_next
hellodev_resume
hellodev_status
hellodev_context
hellodev_do
```

No MCP tool accepts arbitrary root, cwd, executable, argv, environment, adapter,
policy, Dashboard, HostEnvelope or native commands.

## 3b. Context Plane gate

Verify all of the following:

- repository discovery is root-bound, skips symlinks, sensitive files,
  dependency/build directories and applies hard file/count/byte limits;
- `project`, `code` and `docs` scopes are deterministic and query planning makes
  no adapter/model call;
- CJK queries use deterministic terms/bigrams and broad queries fail closed;
- budget is applied before rendering and each returned item includes relative
  path, start/end line, file SHA-256 and snippet SHA-256;
- cursor values bind the canonical project root, repository snapshot, query,
  scope, offset and checksum; mutation makes old cursors stale;
- preview performs no write; ordinary CLI context persists only exact-schema
  metrics/hash state without query, path or source text;
- tampered Context Plane state fails closed and cannot smuggle repository text
  through status, audit or Dashboard;
- MCP continuation uses the cursor without adding a seventh tool;
- Dashboard schema is 15 / Control Center 2.6 and remains GET/copy-only;
- no Context Plane path executes shell, writes code, authorizes an adapter, or
  changes Trellis/Nocturne authority.

## 3c. Progressive verification gate

Verify all of the following:

- `do verify` plans but never executes a command;
- successful evidence is reused only for an exact command hash, WorkItem and
  repository snapshot;
- an unchanged failed check is blocked until repository inputs change;
- recording rejects stale snapshots and contradictory outcomes;
- the store contains no raw command or output and fails closed on malformed or
  symlinked state;
- host-asserted intermediate evidence never satisfies a Trellis gate;
- Trellis gate/test evidence binding includes repository snapshot, so source
  mutation invalidates old evidence links;
- status, audit and Dashboard expose only bounded aggregate counts.

## 3a. Knowledge lifecycle gate

Verify all of the following:

- schema-one LessonProposal files migrate on read without a write and upgrade
  to schema two only on a requested mutation;
- proposal stores remain hash/pointer metadata and never contain lesson or
  evidence text;
- pending TTL is 72 hours and read projection distinguishes effective expiry
  from a materialized terminal decision;
- cross-project verification and reactivation require verified Trellis
  gate/test receipts; reactivation requires genuinely new evidence;
- rejection requires a bounded reason code and supersede requires a compatible
  replacement without cycles or self-reference;
- completed remember/Saga flow marks the proposal persisted, while any external
  write still uses exact approval;
- `next` returns at most one read-only `lesson show` suggestion after higher
  priority recovery and active work;
- raw Nocturne MCP envelopes are receipt-hashed but not returned to the Agent;
- recall output is deduplicated, bounded, source/authority/freshness labelled,
  repository-first on conflict, and instruction-like memory is quarantined;
- CLI, typed `ProjectClient` and read-only Dashboard expose the same review
  semantics without storing raw memory.

## 4. Source/Core installation gate

From a clean checkout and fresh Python 3.10–3.12 environment:

```powershell
python -m pip install -e ".[mcp]"
hellodev --version
hellodev onboard --host cursor
hellodev integrate check --host cursor
hellodev open
hellodev do begin --goal "release smoke" --acceptance "status reports one currentTask"
```

The documentation must use project-scoped `onboard` for both Core and bundle.
Core onboarding must not call bundle setup, modify global host configuration,
invent a Nocturne command, or claim that external components are bundled.

## 5. Unified component and bundle gate

The Core wheel contains the resolver, lock, builder, notices and schema, not
upstream payloads. A platform archive is a separately built artifact. For every
declared archive verify:

- paths are relative, case-unique, regular and non-link;
- component version, revision, repository and SPDX metadata match the lock;
- every controlled byte has exact size and lowercase SHA-256;
- no `.git`, venv/cache, live config/database/WAL/log, secret, memory or
  developer absolute path is included;
- Trellis includes corresponding source/build inputs required by its license;
- Nocturne and all runtimes/dependencies include licenses, notices and SBOM;
- `components verify`, `setup` and `onboard` are idempotent in a clean HOME;
- poisoned/empty PATH cannot override a valid bundle;
- corrupt bundled bytes never fall back to PATH;
- Nocturne writable state stays outside the immutable bundle;
- no global host config, PATH, registry, shell profile or existing DB changes.

For 0.14.x, Windows x86_64 is the only implemented archive target. It becomes
publicly supported for a specific version only after its exact final ZIP passes
offline smoke and the matching SHA-256 is published with the asset. Fixture
tests and a local unpublished archive are insufficient.

Manifest hashes establish local byte consistency. They are not signatures,
remote provenance, tamper-proofing, legal advice or final compliance approval.

## 6. CI and publishing boundary

Ordinary CI remains non-publishing with `contents: read`. It runs the Python
3.10/3.12 Ubuntu/Windows fast matrix plus the Ubuntu full/wheel/MCP job.

The separate PyPI workflow must:

- trigger only from a published GitHub Release;
- require an exact `vMAJOR.MINOR.PATCH` matching package metadata;
- run the full gate and test the exact built artifacts;
- use the protected `pypi` environment and Trusted Publishing;
- grant `id-token: write` only to the publish job;
- have no API token or manual-dispatch bypass.

Source push, tag, Release, asset upload, PyPI publication and user-level install
are distinct externally visible actions and require the corresponding user
authorization. The 0.19.6 source push does not create the others.

## 7. Validation commands

Focused version/document/distribution tests:

```powershell
python -m unittest tests.test_v16_context_plane tests.test_v121_oss tests.test_v13_gateway tests.test_v14_distribution tests.test_f2_dashboard -v
```

Full release gate:

```powershell
python scripts\verify.py --scope fast
python scripts\verify.py --scope full
python -m pip wheel . --no-deps --no-cache-dir --no-build-isolation --wheel-dir dist
```

From fresh environments, smoke the exact base wheel with `--no-index --no-deps`
and the exact wheel plus official MCP SDK. Also run the zero-upstream Demo, Host
SDK example, version/help/integration commands, stdio initialize/list/call,
Python compile, Dashboard JavaScript syntax and source boundary/privacy scans.

The gate must preserve all 0.12 reliability contracts, 0.13 ProjectClient/MCP
contracts and 0.14 distribution, task-continuity, approval identity, data
isolation and copy-only Dashboard contracts.

## 8. Optional independent release artifact

Only after every release gate passes may maintainers create a new real directory:

```text
outputs/hellodev-core-releases/0.19.6/
├─ source/
├─ python/
├─ bundles/
├─ sources/
├─ LICENSES/
├─ release-manifest.json
├─ SHA256SUMS
├─ SBOM.spdx.json
├─ THIRD_PARTY_NOTICES.md
└─ RELEASE.md
```

Record exact suite results, source aggregate, wheel name/size/SHA-256 and each
platform archive's offline smoke. If no archive was built or published, say so
explicitly; do not leave a placeholder that users can mistake for a release.

GitHub source publication alone must exclude upstream source trees, private
state, databases, archives, wheels, build/cache output, local machine paths and
the private development progress ledger.
