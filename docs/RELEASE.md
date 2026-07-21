# HelloDev Core 0.14.2 release checklist

0.14.2 is an Agent-first onboarding and documentation patch on the validated
0.14.1 runtime. It aligns package, schema, component lock, Dashboard, tests,
README and Quick Start without changing Host protocol, state schema, adapter,
approval, lifecycle or distribution behavior.

The source publication and a self-contained platform bundle are separate
deliverables. Pushing the Core source does not mean that an archive, GitHub
Release, PyPI package or bundled Trellis/Nocturne runtime exists.

## 1. Version and source boundary

Confirm `0.14.2` agrees in:

- `pyproject.toml` and `src/hellodev/__init__.py`;
- README, Quick Start and this checklist;
- `src/hellodev/distribution/component-lock-v1.json`;
- `src/hellodev/schemas/component-bundle-v1.schema.json`;
- Dashboard markup, release scripts and version tests.

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
- preserves `open -> next -> do` and `resume` as the default story.

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

## 4. Source/Core installation gate

From a clean checkout and fresh Python 3.10–3.12 environment:

```powershell
python -m pip install -e ".[mcp]"
hellodev --version
hellodev integrate show --host cursor
hellodev integrate check --host cursor
hellodev open
hellodev next
```

The documentation must not use `onboard` as the Core path: `onboard` is the
verified unified-distribution workflow. Core uses `open` plus `integrate
show/check`, and reuses separately installed adapters or degrades to local-only.

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
authorization. The 0.14.2 documentation/source push does not create the others.

## 7. Validation commands

Focused version/document/distribution tests:

```powershell
python -m unittest tests.test_v121_oss tests.test_v13_gateway tests.test_v14_distribution tests.test_f2_dashboard -v
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
outputs/hellodev-core-releases/0.14.2/
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
