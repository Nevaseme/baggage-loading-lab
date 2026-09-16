# Task 2 report — historical pre-action snapshots and predicate recall

Date: 2026-08-24  
Scope: `run_historical_conservative_extreme_point_physics.py`, the new
historical predicate replay diagnostic, its focused tests, and the requested
diagnostic artifacts only.

## TDD evidence

Before writing each test, the test comment names the production mutation it
catches and uses hand-derived literals. The focused tests use the real
`save_observation_snapshot`/`load_observation_snapshot` serialization boundary
and only fake the small agent/environment lifecycle boundary.

RED was observed before implementation. The exact requested Windows runtime
command could not import NumPy from the supplied `.signate_venv`, so the first
attempt stopped at its environment dependency (`ModuleNotFoundError: numpy`).
Using the available Codex Python runtime, the same focused suite then produced
the expected feature failures:

```text
TypeError: run_historical_episode() got an unexpected keyword argument 'capture_all_snapshots'
AttributeError: 'Namespace' object has no attribute 'capture_all_snapshots'
AssertionError: replay API is missing: No module named 'tests.replay_historical_predicates'
Ran 5 tests ... FAILED (failures=2, errors=3)
```

After the minimum implementation, the focused command passed:

```text
simulator.tests.test_replay_historical_predicates ...
Ran 5 tests in 0.191s
OK
```

Regression coverage also passed:

```text
simulator.tests.test_run_historical_conservative_extreme_point_physics
simulator.tests.test_run_support_extreme_fusion_physics
Ran 41 tests in 4.042s
OK
```

`py_compile` passed for all three Task 2 Python files.

## Physical run

Command (run from `simulator/`):

```powershell
.\.signate_venv\Scripts\python.exe -m tests.run_historical_conservative_extreme_point_physics --task 000 --items 41 --seed 42 --output results/portal_reserved_scaffold/historical-task000-captured.json --snapshot-on-failure results/portal_reserved_scaffold/historical-task000-failure.npz --capture-all-snapshots results/portal_reserved_scaffold/historical-task000-snapshots
```

The supplied Windows Signate environment lacked NumPy. The same command was
then run with the project-local WSL runtime and completed with the expected
known physical failure. The runner result is unchanged at the physical
boundary:

| field | value |
| --- | ---: |
| outcome | `physical_failure` |
| requested/effective items | 41 / 41 |
| attempted/completed actions | 26 / 26 |
| safe placements | 25 |
| first failure step/predicate | 25 / `is_valid` |
| first failure status | included=true, valid=false, placed_safe=false |
| final packed count | 25 |
| terminated/truncated | true / false |
| fill score | 33.94392679167531 |
| evaluation `num_placed_items` | 0.6097560975609756 |
| optimize seconds | 17.23654783999973 |
| policy count/p50/p95/p99/max seconds | 26 / 0.30109999600017545 / 0.9684842534995823 / 1.152763812999865 / 1.2109318650000205 |

Capture materialized exactly 26 ordered snapshots (`step-000.npz` through
`step-025.npz`) and an atomic `manifest.json`. The historical artifact
manifest was unchanged:

```text
before_manifest_sha256 = E0C136ADE443B6610F1944509FBD007F793CEFC9F61E3D8201E41259143D3B6C
after_manifest_sha256  = E0C136ADE443B6610F1944509FBD007F793CEFC9F61E3D8201E41259143D3B6C
```

## Replay run

Command (run from `simulator/`):

```powershell
python -m tests.replay_historical_predicates --manifest results/portal_reserved_scaffold/historical-task000-snapshots/manifest.json --episode-result results/portal_reserved_scaffold/historical-task000-captured.json --output results/portal_reserved_scaffold/historical-task000-predicate-recall.json
```

It was executed with the same project-local WSL runtime because the supplied
Windows Signate runtime lacks NumPy. The output contains 26 ordered rows and
the current `SearchSettings` profile digest
`dc121cf564ab793b809b83ba1687593b51735b8b0792ffec99b6b0a63bc3d160`.

Recall and rejection counts:

```text
known_safe_exact_mask_recall: 4 / 25
failed_action_acceptance:     0 / 1
first_reject_reason_counts:
  accepted:                4
  collision_or_clearance:  6
  plane_inclusion:         5
  protection:              4
  support_ratio:           6
  transport:               1
```

`known_safe` is derived only from each snapshot's observed official status.
The independent predicate fields are diagnostic duplication; the replay does
not authorize or return an online action. Geometry/state construction and
strict-mask private helpers are reused, with remaining per-predicate reporting
duplication confined to `replay_historical_predicates.py`.

## Hashes

```text
historical source SHA-256: ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82
config SHA-256:             f321c87bbd5c0b715e1f124e08620e50360634b274a2a38ee16b8be77dd19436
runner SHA-256:             45fd8af18235733761abf12ff2f5d3d08894118782244455dec85ffad6c2ccf4
action-sequence SHA-256:    7ee567f2de74d1462be66e51375e2755b57cf987c31b3a2ca009404ac1ed2327
snapshot manifest SHA-256:  f84737683cc2bbc28f6f24dea0e6fa3b4bd311638522cb6c370ce731c01f7bd1
```

## Changed files and artifacts

Code/tests/report:

- `simulator/tests/run_historical_conservative_extreme_point_physics.py`
- `simulator/tests/replay_historical_predicates.py`
- `simulator/tests/test_replay_historical_predicates.py`
- `.superpowers/sdd/2026-08-24-portal-reserved-scaffold-portfolio/task-2-report.md`

Generated by the required physical/replay commands:

- `simulator/results/portal_reserved_scaffold/historical-task000-captured.json`
- `simulator/results/portal_reserved_scaffold/historical-task000-failure.npz`
- `simulator/results/portal_reserved_scaffold/historical-task000-snapshots/manifest.json`
- `simulator/results/portal_reserved_scaffold/historical-task000-snapshots/step-000.npz` through `step-025.npz` (26 files)
- `simulator/results/portal_reserved_scaffold/historical-task000-predicate-recall.json`

The fix-round boundary was the parent-provided current baseline of **20 files
under `submit/`** with manifest SHA-256
`95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c`.
The post-fix inventory again contains 20 files; no write was issued to
`submit/`, `progress.md`, the physical environment, or production agents.
The complete Task-2-start-to-now submit history is not proven by this local
non-Git workspace, so no broader immutable claim is made here.

## Self-review

- Capture is opt-in; the disabled path retains the existing result shape and
  lifecycle.
- The parent diagnostic proxy retains only observation/action references while
  `policy` is measured. Deep copies, serialization, hashing, and all file
  writes happen after `run_episode` returns.
- No live validator/probe or fallback action was added.
- Snapshot serialization errors are structured as `snapshot_capture_error` and
  mark `diagnostic.promotable=false` without relabeling the physical outcome.
- Snapshot paths are workspace-relative where possible and all returned
  snapshot/manifest hashes are lowercase.
- The failed ingress action remains rejected by the current exact mask, while
  official safety remains status-derived.
- The only operational concern is runtime availability: the prescribed
  Windows `.signate_venv` is missing NumPy; physical/replay verification used
  the existing project-local WSL dependency set instead.

## Fix round 1 — Sol review findings

Date: 2026-08-24  
Scope: the three Task 2 Python files, Task 2 diagnostic outputs/logs, and this
report only. `submit/`, `progress.md`, production agents, and the shared
production runner remain outside the change scope.

### TDD RED → GREEN

The new regression tests were written before the fix implementation. The RED
run of the focused suite failed for the intended missing behavior (manifest
tamper was accepted, invalid actions produced a null reason, independent
diagnostic failure discarded the exact-mask result, and capture mismatches
were not structured). It reported 7 failures and 1 error across 12 tests.

The GREEN run was:

```text
python -m unittest simulator.tests.test_replay_historical_predicates -v
Ran 12 tests ... OK
```

The complete regression run, including the historical runner and support
runner modules, was:

```text
python -m unittest simulator.tests.test_replay_historical_predicates simulator.tests.test_run_historical_conservative_extreme_point_physics simulator.tests.test_run_support_extreme_fusion_physics -v
Ran 53 tests ... OK
```

`py_compile` also passed for the three Task 2 Python files. Raw outputs are
saved at `simulator/results/portal_reserved_scaffold/fix-round-1-focused.log`
and `fix-round-1-regression.log`.

### Findings addressed

1. `replay_manifest` is fail-closed before replay: it checks the episode's
   manifest SHA against the canonical atomic manifest bytes, every snapshot
   record SHA against the NPZ, all source/config/runner/action hashes across
   manifest, snapshot metadata, and episode, exact contiguous unique steps,
   manifest/episode action and status correspondence, and corrupt/missing NPZ
   rejection. The zero-hash manifest, metadata mismatch, episode mismatch,
   duplicate/gap, and corrupt/missing NPZ regressions are covered.
2. Invalid action format, item occurrence/binding, and container ordinal rows
   are always `exact_mask_accepted=false` with an explicit non-null reason.
   Aggregation gates accepted counts on the boolean accepted flag, so a
   false+null row cannot become `accepted`.
3. `ExactMask.diagnose` now runs before the independent predicate projection.
   If the projection raises, its structured diagnostic error is retained while
   the authoritative result remains unchanged.
4. The replay tests cover manifest SHA, metadata hashes, episode
   correspondence, duplicate/missing steps, invalid-action reason
   aggregation, and corrupt NPZ handling.
5. Capture promotion now requires equal policy-call/official-record/status
   counts and exact step/action correspondence. Mismatches produce
   `HistoricalSnapshotCaptureError` details and leave the episode's physical
   outcome unchanged.
6. Provenance is saved in
   `simulator/results/portal_reserved_scaffold/fix-round-1-provenance.json`,
   including the exact WSL commands, runtime executable and `PYTHONPATH`,
   Python/NumPy/PyBullet facts, source hashes, and raw focused/regression/
   physical/replay log paths.

### Canonical WSL physical and replay runs

Physical command (exit 1 is the expected known physical failure):

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m tests.run_historical_conservative_extreme_point_physics --task 000 --items 41 --seed 42 --output results/portal_reserved_scaffold/historical-task000-captured.json --snapshot-on-failure results/portal_reserved_scaffold/historical-task000-failure.npz --capture-all-snapshots results/portal_reserved_scaffold/historical-task000-snapshots'
```

The result remains `physical_failure` at the existing ingress case: 26
attempts, 25 safe placements, first failure step 25 (`is_valid=false`), final
packed count 25, fill score `33.94392679167531`, and evaluation
`num_placed_items=0.6097560975609756`. Optimize time was
`19.939759782000692` seconds; policy timing was count 26, p50
`0.5326343115002601`, p95 `0.977410404500006`, p99
`1.03641305575047`, max `1.05214908100061`. Capture was promotable and
materialized all 26 ordered snapshots. Historical artifact integrity stayed:

```text
before_manifest_sha256 = E0C136ADE443B6610F1944509FBD007F793CEFC9F61E3D8201E41259143D3B6C
after_manifest_sha256  = E0C136ADE443B6610F1944509FBD007F793CEFC9F61E3D8201E41259143D3B6C
```

Replay command (exit 0):

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m tests.replay_historical_predicates --manifest results/portal_reserved_scaffold/historical-task000-snapshots/manifest.json --episode-result results/portal_reserved_scaffold/historical-task000-captured.json --output results/portal_reserved_scaffold/historical-task000-predicate-recall.json'
```

Replay validated the manifest and produced 26 rows: known-safe exact-mask
recall `4/25`, failed-action acceptance `0/1`, and accepted-action count 4.
Reason counts were `accepted=4`, `collision_or_clearance=6`,
`plane_inclusion=5`, `protection=4`, `support_ratio=6`, and `transport=1`.
Raw command outputs are saved at
`simulator/results/portal_reserved_scaffold/fix-round-1-physical.log` and
`fix-round-1-replay.log`.

### Fix-round hashes and concerns

```text
historical source SHA-256: ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82
config SHA-256:             f321c87bbd5c0b715e1f124e08620e50360634b274a2a38ee16b8be77dd19436
runner SHA-256:             9a21ca63619617552b8c45650da2e79d0862d5e1ac84899cd3f193d526f612d3
replay source SHA-256:      79a6c000d9caa2b8741128bf3e6f71331319b3f3bacd0eff9286ec01c638a309
action-sequence SHA-256:    7ee567f2de74d1462be66e51375e2755b57cf987c31b3a2ca009404ac1ed2327
snapshot manifest SHA-256:  ec47a1b1c5e2af001dbaabb5777e426d61cee34c9ad4bcd24fac72099ea356c2
```

The prescribed Windows Signate environment still lacks NumPy, so focused
tests and the physical/replay runs used the existing WSL runtime
`simulator/.venv_wsl/bin/python` with `PYTHONPATH=.:tests:.test_deps_linux`.
Canonical submit manifest recipe and independent post-fix recomputation:
enumerate regular files recursively under `submit/`, derive POSIX relative
paths, sort paths lexicographically by code point, emit one UTF-8 line per file
as `<relative_path> TAB <lowercase SHA-256(file bytes)> LF`, then SHA-256 the
complete UTF-8 manifest text. The recomputation is **20 files** with SHA-256
`95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c`, matching
the parent-provided fix-round-start baseline exactly. This proves the stated
baseline scope only; the complete Task-2-start-to-now submit history remains
outside the claim.

## Fix round 2 — Sol residuals

Date: 2026-08-24  
Scope: replay/capture Task 2 files, Task 2 tests, diagnostic logs/provenance,
and this report only. Production agents, `progress.md`, `submit/`, and the
shared production runner were not changed.

### TDD RED → GREEN

New tests were written before implementation. The Windows-runtime-equivalent
RED focused run reported 14 failures across 16 tests: every manifest/episode/
snapshot identity boundary mismatch was accepted, and negative/boolean/NumPy
action values were coerced instead of receiving explicit reasons. The
capture-disabled boundary and measured-interval tests passed against the
existing behavior.

Canonical WSL GREEN focused run:

```text
PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_replay_historical_predicates -v
Ran 16 tests ... OK
```

Canonical WSL complete regression run:

```text
PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_replay_historical_predicates tests.test_run_historical_conservative_extreme_point_physics tests.test_run_support_extreme_fusion_physics -v
Ran 57 tests ... OK
```

Canonical WSL `py_compile` passed for all three Task 2 Python files. Raw test
logs are `fix-round-2-focused.log`, `fix-round-2-regression.log`, and
`fix-round-2-compile.log` under
`simulator/results/portal_reserved_scaffold/`; the timeout probe is recorded
in `fix-round-2-timeout-probe.log`, and the existing physical run is preserved
at `fix-round-1-physical.log`.

### Findings addressed

1. Replay now requires exact, type-sensitive equality for `task`, `seed`,
   `requested_mode`, and `resolved_mode` across manifest, episode, and every
   snapshot metadata record. Bool/int values are not normalized. The
   table-driven test includes manifest `task=999` with the episode manifest
   SHA updated to the tampered manifest, plus episode and snapshot boundaries.
2. Replay action fields require built-in exact `int` values; bool and NumPy
   integer scalars are rejected. Negative `item_idx` yields
   `item_binding`, negative `container_idx` yields `container_ordinal`, and
   negative/out-of-range orientation yields `action_format`; all are
   non-accepted with non-null reasons.
3. Capture-disabled runs are compared for equality under deterministic fake
   lifecycle/timing and assert that all capture-only keys are absent.
4. A phase/spies regression test proves policy calls retain references only:
   no deepcopy, save, hash, or materialization/probe call occurs while the
   policy interval is active; materialization follows policy exit.

### Artifact replay and invariance

Because Fix round 2 changed replay validation/tests only, the physical runner
was not rerun. The existing physical artifacts were replayed with the final
canonical WSL code and passed identity/hash validation unchanged:

```text
snapshot_manifest_sha256: ec47a1b1c5e2af001dbaabb5777e426d61cee34c9ad4bcd24fac72099ea356c2
historical artifact before/after: E0C136ADE443B6610F1944509FBD007F793CEFC9F61E3D8201E41259143D3B6C / E0C136ADE443B6610F1944509FBD007F793CEFC9F61E3D8201E41259143D3B6C
replay rows: 26
known-safe exact-mask recall: 4/25
failed-action acceptance: 0/1
```

Replay raw output is `fix-round-2-replay.log`; structured runtime, command,
source-hash, artifact-invariance, and submit-manifest evidence is in
`fix-round-2-provenance.json`.

### Fix-round 2 hashes and concerns

```text
replay_historical_predicates.py:       b96c74cc094f349d0929222da0075e3fb0306e561650ea273a583f2e0b78bc3d
run_historical_conservative_extreme_point_physics.py: 9a21ca63619617552b8c45650da2e79d0862d5e1ac84899cd3f193d526f612d3
test_replay_historical_predicates.py:  dda77550da3dcd59dbb561092344536a82743804ecf203cf44c3ab43edc26412
submit manifest: 20 files / 95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c
```

The canonical submit recipe is the exact tab-separated UTF-8 line recipe
recorded in Fix round 1; its independent post-fix recomputation matches the
parent baseline. One initial full-WSL attempt hit the pre-existing historical
worker test's 2.0-second timing boundary at 2.089 seconds; an immediate
rerun passed all 57 tests. A fresh-process probe of that unchanged test alone
then produced one pass at 1.081 seconds and two failures at 2.5643100539982697
and 2.0873972459994548 seconds. The test and threshold were not changed; this
is a reproducible timing-boundary concern rather than a claim that the green
rerun eliminates it. Full probe output is saved at
`simulator/results/portal_reserved_scaffold/fix-round-2-timeout-probe.log`.
The Windows Signate runtime still lacks NumPy, so canonical WSL remains the
execution environment.
