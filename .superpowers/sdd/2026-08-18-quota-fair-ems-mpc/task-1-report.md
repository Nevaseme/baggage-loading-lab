# Task 1 — Phase-0 Diagnostic Core and Fixed Manifest

## Status

GREEN for the focused diagnostic/manifest/CLI suite, related catalog/EMS/MCTS
regressions, and compile checks. No production files, Git state, dependencies,
or submission artifacts were modified.

## TDD evidence

The manifest test first failed with the absent hand-recorded digest:

```text
AssertionError: '251d613dcd464f557a209923272c41d83656c0373dd88d18d747364dde213bef' != '__DIGEST__'
```

The CLI test first failed with the expected absent-module import error:

```text
ModuleNotFoundError: No module named 'tests.run_quota_fair_phase0'
```

After the minimal manifest digest and CLI implementation, the focused suite
passed.

## Verification

Runtime:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Commands and counts:

```text
python.exe -m unittest tests.test_quota_fair_starvation_diagnostics -q
Ran 33 tests in 0.083s — OK

python.exe -m unittest tests.test_highscore_catalog tests.test_highscore_ems tests.test_highscore_mcts -q
Ran 54 tests in 0.283s — OK

python.exe -m compileall -q tests/quota_fair_starvation_diagnostics.py tests/quota_fair_case_manifest.py tests/run_quota_fair_phase0.py
success

python.exe tests/run_quota_fair_phase0.py --help
success; deferred PyBullet/Gymnasium imports were not loaded
```

Direct CLI aggregate smoke with an empty raw input also exited `0` and wrote
the declared schema atomically.

## Manifest

- Literal template count: `16`
- SHA-256: `251d613dcd464f557a209923272c41d83656c0373dd88d18d747364dde213bef`
- Serialization: `json.dumps(tuple(cases), sort_keys=True, separators=(",", ":"))`
- Materialization is deterministic for seed/template, JSON serializable, and
  applies lookahead, two-container, shelf, attribute, ordering, and repeated
  dimension transformations.

## Scope review

Changed files:

- `simulator/tests/quota_fair_starvation_diagnostics.py`
- `simulator/tests/test_quota_fair_starvation_diagnostics.py`
- `simulator/tests/quota_fair_case_manifest.py`
- `simulator/tests/run_quota_fair_phase0.py`
- `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-1-report.md`

Historical highscore production files were not touched; the final SHA-256
scope check is:

```text
agents/highscore/catalog.py DDC1CD1D32BC573D2A0BAC0012A03DF1CDCE5DB347F7070C60BF7A4B77101CE4
agents/highscore/ems.py     049C1AE81583E08689776D2A05FDD4148A202BE587E106E9CE6612FC51DD22DA
agents/highscore/mcts.py    114E3D8ACC57895A5EFB578B62D80C89AE3F2AC20FB1FFEEFE279AE712E95A2E
agents/highscore/agent.py   F7ACF36AC9C2B2D39CA609C0E1CFDAD8400CC7A408D21DABC4C507D2209130B5
```

## Concerns

Historical note: before the Task 1D follow-up, the Phase-0 CLI physics warm-up
and saved-snapshot execution were deferred to Task 2. The current Task 1
runner is implemented and supports deterministic materialized manifest inputs,
atomic writes, explicit raw-file aggregation, and injectable diagnosis; no
WSL/PyBullet physical execution was performed. Physical execution remains a
Task 2 concern.

## Task 1C review follow-up

The initial Sol-high review rejected the first Task 1 package. Its findings
were addressed in the four Task 1 files only:

- `diagnose_observation` now sorts all visible positions by
  `(-urgency, item.index, pool_index)`, probes every position with fresh
  independent measurements using the full observed catalog budget on every
  probe, allocates classification fair shares by remaining-budget recurrence,
  consumes remaining budget by `min(measured_elapsed, fair_share)`, and stores baseline reason, measurement, fair share, and
  eligibility. Eligibility requires zero baseline roots, causal
  `global_cap`/`catalog_deadline`, and a true immutable classification.
- Aggregation requires every explicit raw input to carry the expected
  lowercase 64-hex manifest digest, rejects hash conflicts and non-identical
  duplicate observation IDs, and recomputes recoverability from trace/probe
  evidence rather than a raw boolean.
- Materialization now updates `camera.num_containers`, uses descending
  `(volume, index)` ordering for large-to-small ties, records separate
  `initial_state`/`density`/`warmup_target_steps` metadata, alternates the
  two-container priority designation, and exposes a canonical materialized
  case hash helper without adding metadata keys to the GroundHandlingEnv
  config.

The original Task 1 implementation did not record an absent-behavior RED for
the diagnostic core before implementation; that TDD deviation is recorded
explicitly here. The review follow-up added literal collaborator RED tests for
full-pool urgency order, remaining-budget recurrence, eligibility mutation,
manifest/hash conflicts, duplicate-row conflicts, metadata/camera/priority
alternation, and canonical hashing; the focused suite is GREEN afterward.

Historical note: at this review checkpoint Task 1D physical warm-up had not
yet been implemented or run. The subsequent Task 1D follow-up implemented the
lazy runner; physical execution is still pending Task 2.

The follow-up RED specifically caught passing the fair-share slice as the
probe budget and over-consuming remaining budget when a probe exceeded its
slice; both tests are now GREEN.

The final runner RED caught environment leaks when Agent construction raised
before the prior try block; both warm-up and task-episode construction now
enter the close-owning try block immediately after environment creation. A
direct-mutation restoration test (without an outer mock context) verifies that
normal and exceptional tracer calls restore the temporary catalog
`propose_actions`, `apply_action`, and `time` references before the test's
manual `finally` restoration.

## Task 1D runner follow-up

The lazy runner was then added without importing PyBullet/Gymnasium on module
import: `--help` works under the Windows bundled runtime. Real task episodes
use the highscore `Agent` with `use_mpc_mcts_ems=True`, attach the shared depth
map, diagnose every pre-action observation, abort immediately on false status,
and close the environment in `finally`. Saved snapshots are loaded through the
existing non-pickle loader. Manifest warm-up supports empty/preloaded cases,
target steps `0/8/16`, packed-pose serialization and stream-index removal,
fresh reinitialization, canonical hashes, and materialized-case aggregate
validation. The runner implementation is complete; physical execution is
pending Task 2.

Additional fake-runner tests cover each pre-action diagnosis, false-status
abort/close, snapshot source preservation, preloaded pose/removal/fresh reset,
task/items injection, materialized aggregate output, lookahead_k 20/40
denominator handling, exact action identity/restoration after an external
catalog exception, and depth-map attachment on every warm-up return path.
Agent-construction close ownership is also covered for both warm-up and task
episode runners.

Final Task 1 status: runner implemented; physical WSL/PyBullet execution
pending Task 2.
