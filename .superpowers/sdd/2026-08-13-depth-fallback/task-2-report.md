# Task 2 report — geometry rescue A/B gate plumbing

## Status

DONE — corrected physical A/B gate rejected geometry rescue.  The diagnostic
implementation remains available, but production defaults to
`use_geometry_rescue=False`.

## TDD evidence

RED was observed before production edits:

- `SearchSettings().use_geometry_rescue` raised `AttributeError`;
- `dataclasses.replace(..., use_geometry_rescue=False)` raised `TypeError`, so
  disabled policy behavior could not be selected;
- in the correct isolated simulator environment, CLI help exited successfully
  but did not contain `--geometry-rescue`.

An initial combined CLI attempt from the repository root failed earlier during
the pre-existing `pybullet_data` import and was not accepted as RED evidence.
The CLI RED was repeated from `simulator/` with
`PYTHONPATH=.:tests:.test_deps_linux`, where it failed only on the missing flag.

## Changes

- Added `SearchSettings.use_geometry_rescue`; its final default is `False`
  after the corrected physical gate rejected adoption.
- Gated the `Agent.policy` geometry rescue call on that setting without
  changing the primary planner, hard deadline, rescue validation, ranking, or
  deterministic fallback.
- Added `--geometry-rescue {on,off}` to the physics harness, defaulting to
  `on`.
- The harness applies monotone-ingress and geometry-rescue selections in one
  settings replacement and rebuilds `Planner` immediately afterward.
- Added `geometry_rescue` to the result JSON.
- Extended CLI help coverage and added settings-default and disabled-policy
  behavior tests.

## Verification

- Settings/default plus policy-disable focused tests: 2 passed in 0.009 s.
- CLI help focused test: 1 passed in 4.694 s.
- Complete unittest discovery: 61 passed in 2.761 s.

## Initial physical A/B run — invalidated for adoption

All four A/B runs used seed 42, optimization time 0, monotone ingress fixed
off, and did not use the older `--rescue-without-depth` harness override.
Every action before the first failure had all official safety statuses true.
The final action in every run was included but failed validity and placement
safety: `is_included=true`, `is_valid=false`, `is_placed_safe=false`.

| Task | Rescue | Safe placements | Fill | Ratio | Max policy seconds |
|---|---:|---:|---:|---:|---:|
| 000 | off | 16 | 10.031879 | 0.6400 | 1.000249914 |
| 000 | on | 17 | 11.337727 | 0.6800 | 2.826720892 |
| 001 | off | 17 | 18.917050 | 0.5667 | 1.00856 |
| 001 | on | 21 | 23.022578 | 0.7000 | 5.750316 |

Exact captured logs:

- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_off.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_off.stderr.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_on.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_on.stderr.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_off.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_off.stderr.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_on.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_on.stderr.txt`

These results met the absolute numeric gate, but the Task 2 review found that
the OFF branch skipped the pre-Task-1 depth-aware emergency loop instead of
restoring it.  Therefore these four runs are retained as diagnostic evidence
but are invalid as the one-factor adoption comparison.  The known earlier
local baselines were task000 17 and task001 20 safe placements; the public
submission baseline was `12.622949582873819`.

Decision from these logs: **NO ADOPTION RULING**.  They required the corrected
four-case rerun documented below.

## Self-review

- `use_monotone_ingress` remains default-off and its implementation was not
  changed.
- The older `--rescue-without-depth` diagnostic override remains available but
  was not invoked or changed.
- With rescue disabled, primary failure proceeds directly to the unchanged
  deterministic last resort; the generator is verified to receive zero calls.
- Removing the default field, flag condition, or CLI argument causes a distinct
  new test to fail.
- No dependency, network, Git, SIGNATE, or `simulator/src` change was made.

## Concerns

The initial task001 rescue-on maximum of 5.750316 seconds was below the
6-second gate but had only about 0.25 seconds of observed headroom.  The
corrected A/B rerun must recheck end-to-end timing.

The prior guarded submission ZIP remains immutable at
`simulator/submissions/highscore_guarded_20260813.zip`, SHA-256
`3789B037DA39BD2F38215D711C42AD9CF504503F44B94016517A675044CB4A54`.

## Review fix round 1 — restore the OFF control

The independent Task 2 review identified an Important experimental-control
defect.  Before Task 1, a primary-planner miss entered a depth-aware emergency
loop.  The initial OFF implementation bypassed both no-depth rescue and that
legacy loop, so OFF changed two factors and was not the baseline behavior.

TDD RED evidence:

- the disabled-setting test was changed to require generation from the same
  depth-aware state after a primary miss;
- it failed because the generator call list was empty;
- the strengthened test also fixes the old ranking and stopping contract:
  retain the depth map, use sorted emergency items and the common hard
  deadline, score every candidate from the first nonempty item, select by
  fewer violations then support, clearance, and lower height, and stop before
  later items.

Minimal production fix:

- extracted `_depth_aware_emergency` with the exact pre-Task-1 loop;
- when `use_geometry_rescue=True`, policy uses the Task 1 no-depth rescue;
- when `False`, policy uses the restored depth-aware emergency path;
- primary success and deterministic last-resort behavior remain unchanged.

Post-fix verification:

- branch-focused tests: 3 passed in 0.238 s;
- complete planner suite: 16 passed in 2.168 s;
- complete unittest discovery: 61 passed in 2.774 s.

No new code concern was found.  The required regenerated physical A/B results
are documented below.

## Corrected physical A/B gate and final decision

After restoring the true OFF control, the controller reran all four cases with
seed 42, optimization time 0, monotone ingress fixed off, and without the old
`--rescue-without-depth` override.  Every action before the first failure was
safe.  Each final failed action had `is_included=true`, `is_valid=false`, and
`is_placed_safe=false`.

| Task | Rescue | Safe placements | Fill | Ratio | Max policy seconds |
|---|---:|---:|---:|---:|---:|
| 000 | off | 17 | 11.337727 | 0.6800 | 2.8514 |
| 000 | on | 17 | 11.337727 | 0.6800 | 3.1301 |
| 001 | off | 20 | 19.133195 | 0.6667 | 5.750214 |
| 001 | on | 16 | 17.817178 | 0.5333 | 5.750498 |

Exact corrected logs:

- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_off_corrected.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_off_corrected.stderr.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_on_corrected.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task000_on_corrected.stderr.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_off_corrected.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_off_corrected.stderr.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_on_corrected.stdout.txt`
- `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/task001_on_corrected.stderr.txt`

The adoption gate failed: task001 rescue-on reached only 16 safe placements,
not strictly above 20, and regressed by four placements and 1.316017 fill
relative to the restored OFF control.  Task000 was unchanged in placement and
fill, with higher maximum policy time when rescue was on.

Final decision: **REJECT** geometry rescue as a production default.  TDD first
changed the settings expectation to disabled and observed it fail because the
default was still `True`; the minimal production change set the default to
`False`.  The existing explicit-ON policy test was then corrected to select
`use_geometry_rescue=True` rather than relying on the former default.

Final verification:

- default-OFF focused RED: failed as expected (`True is not false`);
- default-OFF focused GREEN: 1 passed;
- final default-OFF / explicit-ON / restored-OFF focused suite: 3 passed in
  0.255 s;
- final complete unittest discovery: 61 passed in 2.761 s.
