# HelloDev Core 0.14.1 release checklist

0.14.1 adds task-continuity and truthful Control Center projections on the
manifest-checked unified distribution introduced in 0.14.0. A platform bundle
may carry Trellis and Nocturne, but they remain separate processes and data
planes; recovery remains `resume`, and external or policy writes still require
exact approval. The first release target is Windows x86_64 only.

## 1. Version and source boundary

Confirm `0.14.1` agrees in:

- `pyproject.toml`;
- `src/hellodev/__init__.py`;
- README and Quick Start;
- `src/hellodev/distribution/component-lock-v1.json` and the component schema;
- release artifact names and the exact `v0.14.1` tag.

The editable source remains `packages/hellodev-core`. Preserve all earlier
release directories. Do not install from, link to, or mutate the development
tree when producing the release snapshot.

## 2. Unified component and bundle gate

The portable Core wheel contains only the resolver, lock, builder, notices and
schema. It must remain a truthful `py3-none-any` artifact. Platform runtimes
and upstream payloads belong in separate archives.

For every declared platform archive, verify all of the following against the
exact candidate artifact:

- manifest paths are relative, case-unique, regular, non-link files;
- Trellis/Nocturne version, revision, repository and SPDX license match the
  packaged lock;
- every controlled byte has exact size and lowercase SHA-256;
- no `.git`, venv/cache, live `config.json`, database, WAL/SHM, backup, log,
  secret, existing memory, or developer absolute path is present;
- Trellis includes exact corresponding source and build inputs required by
  its AGPL-3.0-only distribution terms;
- Nocturne includes its MIT license, and runtime/npm/Python dependencies have
  an SBOM and notices;
- `components verify`, `setup`, and `onboard` are idempotent in a clean HOME;
- a poisoned/empty PATH cannot override a valid bundle, and a corrupt bundle
  never falls back to PATH;
- Nocturne configuration/SQLite is created only in its separate data root;
- no user-level host config, PATH, registry, shell profile, or existing DB is
  inspected or changed.

The source gate uses deterministic fake components. A release claim that users
need no separate Trellis/Nocturne installation additionally requires an exact,
offline, per-platform archive smoke. Component hashes are not signatures or a
remote provenance witness. Matching SPDX identifiers, notices, source material,
and manifest hashes is also not a legal opinion or final compliance review.

For 0.14.1, only a Windows x86_64 archive may be listed as supported. Linux and
macOS remain pending until their own exact archives pass the same offline gate;
portable source/fixture tests are not sufficient evidence.

## 3. Shared application facade gate

Verify:

- `ProjectClient` binds one canonical root at construction;
- `open`, `next`, `resume`, `status`, `context`, and `do` preserve CLI result
  shapes and `ProjectError` behavior;
- the client has no cross-call capability, executable, profile, lease, or
  approval cache;
- per-intent input allowlists reject unknown or cross-intent fields;
- finish still checks the gate before lifecycle transition;
- Trellis and Nocturne execution still use the existing exact preparation,
  identity binding, receipt, evidence, lease, and Saga paths;
- remember writes remain token-required under every authorization profile.

Run during development:

```powershell
python -m unittest tests.test_v13_gateway tests.test_f1_cli tests.test_f1_security -v
```

## 4. Optional official MCP SDK gate

The base wheel must have no unconditional dependency and must import
`hellodev`, `ProjectClient`, CLI, and Host SDK without importing `mcp`.
`hellodev mcp serve` without the extra must fail cleanly with:

```text
Install MCP support with: pipx install "hellodev-core[mcp]"
```

This is the runtime help contract, not evidence that 0.14.1 is currently
available from PyPI. Local release validation must install the exact candidate
wheel plus pinned `mcp==1.28.1` from a controlled wheelhouse. Public-index
installation may be documented only after the separately authorized upload and
an independent install check succeed.

The optional extra is pinned to the verified `mcp==1.28.1`. In an isolated extra-enabled
environment, start the exact wheel over stdio with the official client and
verify initialize, `tools/list`, and calls to exactly these tools:

```text
hellodev_open
hellodev_next
hellodev_resume
hellodev_status
hellodev_context
hellodev_do
```

No tool accepts a root, cwd, executable, argv, arbitrary adapter, environment,
policy operation, Dashboard operation, HostEnvelope operation, or generic
native command. Read tools do not mutate `.hellodev/`; `open` and `do` are
serialized in-process. Request/result limits and exact approval semantics must
fail closed.

## 5. Integration and progressive disclosure gate

Verify:

```powershell
hellodev integrate show --host codex
hellodev integrate show --host cursor
hellodev integrate check --host codex
hellodev --help
hellodev --help-all
```

`integrate` may render and validate a project-scoped snippet, executable, root,
SDK availability, and server construction. It must not read or modify global or
project Codex/Cursor configuration. Default help exposes the thin daily/setup
surface; `--help-all` discloses advanced governance and native adapters.

## 6. CI and Trusted Publishing readiness

The ordinary CI workflow remains non-publishing and has only `contents: read`.
It verifies the dependency-free matrix, full gate, wheel candidate, and an
official MCP-extra job.

The separate `publish.yml` must:

- trigger only from a published GitHub Release;
- reject tags not matching exact `vMAJOR.MINOR.PATCH` or package metadata;
- run the full gate and build wheel + sdist once;
- upload and later download the exact tested artifacts;
- use the protected `pypi` environment;
- grant `id-token: write` only to the publish job;
- use PyPI Trusted Publishing with no API token and no manual-dispatch bypass.

Creating the tag/release, configuring the GitHub/PyPI environment, or uploading
to PyPI remains a separately authorized external action.

## 7. Full local release gate

After all source and documentation changes:

```powershell
python scripts\verify.py --scope full
python -m pip wheel . --no-deps --no-cache-dir --no-build-isolation --wheel-dir dist
```

From fresh environments, verify the exact base wheel with `--no-index
--no-deps`, then the exact wheel plus the official MCP SDK extra. Run the
zero-upstream Demo, Host SDK example, version/help/integration commands, stdio
initialize/list/call smoke, Python compile, Dashboard JavaScript syntax, and
source privacy/boundary scans.

The full gate must preserve all 0.12.1 reliability contracts, the 0.13
ProjectClient/MCP contracts, and the 0.14 distribution, approval identity,
data-isolation, privacy, and copy-only Dashboard contracts.

## 8. Independent release artifact

Only after every gate passes, create a new real directory:

```text
outputs/hellodev-core-releases/0.14.1/
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

Include a clean source snapshot, exact wheel, and release report. Record:

```text
Version: 0.14.1
Focused suites: <result>
Full suite: <result>
Base wheel smoke: <result>
Official MCP stdio smoke: <result>
Integration/progressive-help checks: <result>
Fixture bundle build/verify/security: <result>
Exact platform bundle offline smoke: <result or explicitly not released>
Source files: <count>
Source aggregate SHA-256: <sha256>
Wheel: hellodev_core-0.14.1-py3-none-any.whl
Wheel bytes: <bytes>
Wheel SHA-256: <sha256>
Independent release directory: outputs/hellodev-core-releases/0.14.1/
```

GitHub push/release, PyPI upload, global installation, live user-memory access,
Codex plugin changes, upstream modification, legal sign-off, code signing, and
user-level configuration mutation are not part of this local release build.
