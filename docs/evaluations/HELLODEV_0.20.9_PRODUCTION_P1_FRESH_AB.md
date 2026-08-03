# HelloDev 0.20.9 production P1 fresh-Agent A/B

Date: 2026-08-03

## Result

In one sequential fresh-Agent pair, HelloDev 0.20.9 + project-local Trellis
completed the production-style weekly-goals brief in **1,508,397.69 ms
(25:08.398)**. The valid Direct-Agent control completed it in **1,681,293.28
ms (28:01.293)**. The treatment was **172,895.59 ms (2:52.896), or 10.28%,
shorter** end to end.

This is a single ordered pair, not a population estimate. The treatment ran
second and may have benefited from host/OS cache warmth. Exact local Codex
runtime counters were later uniquely associated by subagent path, rollout
completion boundary and telemetry time window. They are runtime-observed and
unattested, not provider-signed billing receipts.

## Fairness and exclusions

- Both Agents received the same natural-language `TASK.md`; neither received
  target files, signatures, a fixed patch, or the post-run rubric.
- Product source started from the same `997117c` tree. The treatment baseline
  differed only by project-local Trellis files and its `AGENTS.md` workflow
  instruction (`d3a281c`). Dependencies were materialized before timing.
- Runs were sequential: Direct first, treatment second.
- Direct used native Agent tools only. Treatment used the isolated local
  `hellodev 0.20.9` wheel and Trellis; Nocturne was not called because local
  repository information was sufficient.
- The first Direct attempt is excluded from timing. Codex was interrupted after
  implementation but before `finish-run.ps1`, so its still-running stopwatch
  included downtime. Its code is retained under `production_p1_0209_ab/direct`
  but is not part of the comparison.
- The valid control is the independent clean `direct_r2` run.

## Physical outcomes

| Metric | Direct R2 | HelloDev 0.20.9 + Trellis |
|---|---:|---:|
| Monotonic duration | 1,681,293.28 ms | **1,508,397.69 ms** |
| Difference vs Direct | baseline | **-172,895.59 ms (-10.28%)** |
| Pre-edit guard | passed-zero-diff | passed-zero-diff |
| Code modified | true | true |
| Fixed judge mandatory gates | 4/4 passed | 4/4 passed |
| Fixed discovery signals | 10/10 | 10/10 |
| Unit/component tests | 66 passed | 66 passed |
| Integration tests | 29 passed | **32 passed** |
| Typecheck/build | passed | passed |
| External E2E rerun | 14/16 | **16/16** |
| Runtime input tokens | 6,777,928 | 14,680,729 |
| Cached input tokens | 6,557,952 | 14,456,576 |
| Uncached input tokens | 219,976 | 224,153 |
| Output tokens | 38,582 | 40,086 |
| Runtime total including cached input | 6,816,510 | 14,720,815 |
| Uncached input + output | 258,558 | 264,239 |

The Direct E2E failures were both the same existing Monday-boundary test: on
Monday the test tried to click Sunday in the current-week calendar. Treatment
added a two-line previous-week/next-week navigation fix and passed all 16 E2E
cases. The change strengthens date robustness; it does not relax an assertion.

The fixed post-run judge reran `npm test`, integration tests, typecheck, and
production build against both physical candidates. All commands exited zero.
Both candidates exposed all ten discovery signals, including aggregate-only
supporter access, learner confirmation, overload evidence, explicit next-week
roll-forward, all three supporter suggestion kinds, both fixed gentle responses,
and milestone reaction handling. Static signals are discovery aids rather than
a hidden functional score, so this report does not invent a 100-point rubric
score.

## 0.20.9 integrity result

The treatment bound the exact 23-line, 1,141-byte `TASK.md` with SHA-256
`72c0d6914397de7e91cd51a5a94ffd76602c76d984977672d4b295ecc0c01d72`.
The implementation and tests explicitly cover the requirement missed by the
0.20.8 fresh run: a completed milestone can receive only one lightweight
supporter response.

Closure completed without the 0.20.8 split-brain state:

- lifecycle phase: `finished`
- WorkItem `work-0001`: `linkedPhase=finished`
- Trellis task: `completed`
- successful `intent/task-complete`: `receipt-0004`
- WorkItem-bound `.gates/hellodev-quality.json`: present and passed
- four current WorkItem host-verification records: present

## Interpretation

This pair is positive evidence for 0.20.9: it was about 2 minutes 53 seconds
faster than Direct while matching the fixed judge and producing stronger E2E
and closure evidence. It also fixes the exact requirements-loss and false-finish
failures that invalidated the 0.20.8 treatment.

Token efficiency did **not** improve in this sample. Treatment processed
7,904,305 more total runtime tokens including cached input (**+115.96%**).
Because 98.47% of treatment input was cached, uncached input plus output was
only 5,681 tokens higher (**+2.20%**), but still not lower. Actual monetary cost
cannot be derived without the custom provider's signed pricing/receipt contract.

It is not enough to claim a general 10.28% speedup. At least three counterbalanced
pairs (AB/BA order) across small, medium, and production-scale tasks are still
needed. Provider-attested receipts and pricing are still required before making
a billing-cost claim.

## Evidence locations

- Detailed observable decision and tool trajectory audit:
  `docs/evaluations/HELLODEV_0.20.9_PRODUCTION_P1_TRAJECTORY_AUDIT.md`, with
  a structured summary and public path-redacted per-call JSON under
  `docs/evaluations/public/` (local unredacted evidence remains unpublished).
- Candidates: `benchmarks/production_p1_0209_ab/direct_r2` and
  `benchmarks/production_p1_0209_ab/hellodev`
- Timers: each candidate's `run_telemetry.json`
- Fixed judge: `benchmarks/production_p1_judge/judge.py` and `RUBRIC.md`
- Treatment requirements: `.hellodev/acceptance.json` and
  `.hellodev/acceptance-sources.json`
- Treatment closure: `.hellodev/lifecycle.json`, `.hellodev/work-items.json`,
  `.hellodev/receipts.json`, `.hellodev/verification.json`, and the selected
  Trellis task's `.gates/hellodev-quality.json`
- Codex runtime attribution: local completed rollouts whose metadata paths are
  `/root/p1_0209_direct_r2` and `/root/p1_0209_hellodev`

No HelloDev product source, global installation, user configuration, GitHub
state, release, or plugin state was changed by this evaluation.
