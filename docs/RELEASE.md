# HelloDev Core 0.12.1 release checklist

0.12.1 is a compatible reliability and open-source polish release on the
0.12.0 architecture. It does not introduce a new Host protocol, state schema,
policy target, workflow engine, adapter authority, or executable Dashboard.

## 1. Version and source boundary

Confirm `0.12.1` agrees in:

- `pyproject.toml`
- `src/hellodev/__init__.py`
- Nocturne MCP client metadata
- Control Center product label
- README and Quick Start
- release artifact names

The editable source remains `packages/hellodev-core`. Preserve all earlier
release directories and do not install from the development tree.

## 2. Reliability patch gate

Verify:

- receipt persistence followed by WAL-phase failure recovers idempotently;
- multiple processes recovering one transaction create one receipt and one
  policy effect;
- checkpoint digests are strict lowercase SHA-256;
- checkpoint files are regular, non-symlinked, and at most 64 KiB;
- `checkpoint verify --require-match` emits JSON and returns code 2 on mismatch;
- valid pending HostEnvelopes produce `host pending <id>`, not generic status;
- Host SDK pending/reconcile/abandon methods preserve context privacy;
- Canary v2 diagnostic fields do not change the decision algorithm.

Run the focused suites during development:

```powershell
python -m unittest tests.test_v121_polish tests.test_v121_oss tests.test_v12_reliability -v
```

## 3. Typed SDK and wheel gate

The wheel must contain:

- `hellodev/py.typed`
- HostEnvelope, HostResult, and protocol JSON Schemas
- public Host SDK exception and recovery types

From a fresh `--no-index --no-deps` environment, import the SDK, negotiate
protocol 1.0, run `examples/host_sdk_minimal.py`, reject protocol 2.0, and prove
that unavailable token values remain unavailable.

## 4. CI and OSS gate

The GitHub Actions workflow must be bounded and non-publishing:

- triggers: push, pull request, manual dispatch;
- concurrency group: `hellodev-ci-${{ github.ref }}`;
- newer runs cancel in-progress runs for the same ref;
- matrix `fail-fast=false`;
- fast: Ubuntu/Windows × Python 3.10/3.12;
- full: Ubuntu Python 3.12 after fast succeeds;
- the declared `setuptools>=68` build backend is installed before the
  `--no-build-isolation` wheel build;
- wheel candidate retained for 7 days;
- no PyPI upload, GitHub release, secret, global install, or upstream mutation.

Run the zero-upstream Demo from an isolated wheel installation:

```powershell
pwsh -File scripts/demo.ps1
python examples/host_sdk_minimal.py
```

Confirm README, Quick Start, CONTRIBUTING, Case Study, Why HelloDev, and example
links resolve. Do not advertise public-index installation before it is actually
published and verified.

## 5. Full release gate

After all source and documentation changes:

```powershell
python scripts\verify.py --scope full
python -m pip wheel . --no-deps --no-cache-dir --no-build-isolation --wheel-dir dist
```

The full gate must preserve the daily `open -> next -> do` path, all F1/F2
authorization/evidence/privacy rules, completed-turn usage semantics, fixed
20-turn ReflectionCycle, transactional policy recovery, Canary v2, portable
checkpoints, and Control Center schema v7 copy-only behavior.

## 6. Publication artifact

Create a new real directory only after every gate passes:

```text
outputs/hellodev-core-releases/0.12.1/
```

Include a clean source snapshot, the wheel, and an exact release report. Record:

```text
Version: 0.12.1
Focused suites: <result>
Full suite: <result>
CI configuration audit: <result>
Minimal demo: <result>
Host SDK example: <result>
Isolated wheel smoke: <result>
Source files: <count>
Source aggregate SHA-256: <sha256>
Wheel: hellodev_core-0.12.1-py3-none-any.whl
Wheel bytes: <bytes>
Wheel SHA-256: <sha256>
Independent release directory: outputs/hellodev-core-releases/0.12.1/
```

PyPI upload, GitHub push/release, global installation, live Nocturne access,
Codex plugin changes, and user configuration mutation require separate explicit
authorization and are not part of this local release build.
