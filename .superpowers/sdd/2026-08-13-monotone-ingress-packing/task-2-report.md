# Task 2 report: Make monotone base-layer candidates primary

## Status

Complete. Continuous-X ingress skyline candidates are integrated ahead of the
legacy Cartesian extreme points under the immutable
`SearchSettings.use_monotone_ingress` A/B flag. Existing hard validation is
still the sole authority for accepting candidates.

## Exact changed files

- `simulator/agents/highscore/settings.py`
  - Added exactly `use_monotone_ingress: bool = True` to `SearchSettings`.
- `simulator/agents/highscore/candidates.py`
  - Imported Task 1's `build_frontier` and `candidate_x_intervals`.
  - Added exactly the requested `_monotone_base_positions(...)` method.
  - Integrated floor, static-obstacle/small-shelf, and main-shelf base bottoms.
  - Validates monotone proposals first and suppresses legacy base positions only
    after one monotone proposal validates for that orientation/support level.
  - Preserves placed-item-top legacy positions; for coincident base/stack
    heights, only positions intersecting the matching placed support retain
    stack provenance.
- `simulator/tests/test_highscore_candidates.py`
  - Added the four mandatory real-generator regression tests.
  - Added one review-driven regression test for coincident base/stack heights.
- `.superpowers/sdd/2026-08-13-monotone-ingress-packing/task-2-report.md`
  - This report.

No other file was edited. In particular, `simulator/src`,
`simulator/agents/highscore/ingress.py`, simulator configuration, public Agent
API, thresholds, beam settings, item ranking, scoring, and deadline limits were
not changed.

## RED evidence

Before either production file was changed, the four mandatory tests were added
and the focused command was run:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_candidates -v'
```

Result: `FAILED (errors=4)`; the 14 pre-existing tests passed and each new test
errored for the expected missing feature:

```text
TypeError: SearchSettings.__init__() got an unexpected keyword argument 'use_monotone_ingress'
Ran 18 tests in 0.549s
```

After independent review identified a coincident base/stack provenance issue,
the focused regression test was added before its production fix and run alone:

```text
test_coincident_stack_height_does_not_restore_unrelated_legacy_base_positions ... FAIL
AssertionError: False is not true
Ran 1 test in 0.083s
FAILED (failures=1)
```

This demonstrated that unrelated legacy shelf positions were restored when a
placed-item top happened to equal that base support height.

## GREEN evidence

Initial focused GREEN after the requested implementation:

```text
Ran 18 tests in 0.453s
OK
```

After strengthening the wide-item test to exercise `generate()` rather than
the helper directly:

```text
Ran 18 tests in 0.590s
OK
```

After the review-driven coincident-height fix:

```text
test_coincident_stack_height_does_not_restore_unrelated_legacy_base_positions ... ok
Ran 1 test in 0.043s
OK

Ran 19 tests in 0.612s
OK
```

The focused suite includes existing shelf, protection, grid recovery, and
candidate cap coverage.

## Full-suite evidence

Final fresh brief-mandated command after all production and test edits:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest discover -s simulator/tests -p "test_*.py" -v'
```

Result:

```text
Ran 51 tests in 2.717s
OK
```

## Candidate-count and runtime observations

An empty-container fixture was generated 100 times for each immutable flag
setting in the same WSL/Python environment:

```text
monotone=False candidates=48..48 mean_ms=6.314
monotone=True  candidates=18..18 mean_ms=5.069
```

This is a small fixture microbenchmark, not a simulator performance claim. It
shows deterministic counts in the sample and no local candidate explosion.

## Self-review

- `_monotone_base_positions` uses the same physical wall bounds as the current
  generator before converting interval starts to centres.
- It calls `build_frontier(container, bottom_z, bottom_z + 2*half[2], ...)`,
  computes Y using the specified clearance/margin formula, rejects all four
  horizontal footprint bound violations, rounds/deduplicates at `1e-6`, and
  orders deepest Y, low Z, then centre-nearest X with deterministic X tie-break.
- Monotone proposals are passed unchanged through the existing
  `_validate_position`; that method and all hard-check implementations remain
  untouched.
- Legacy output/order is behind an early `use_monotone_ingress` branch and the
  disabled-path regression asserts the existing first back-floor coordinate
  `(-0.689, 0.489, 0.168)`.
- Legacy base suppression is conditioned on a validated monotone candidate for
  the same orientation and rounded support bottom. Stack-only levels remain in
  the legacy loop. When stack and base heights coincide, footprint intersection
  with a matching placed top distinguishes stack provenance rather than
  restoring the entire Cartesian layer.
- The candidate-per-orientation cap counts monotone and retained legacy
  candidates together; recovery fallback remains unchanged and reachable when
  hard validation rejects all normal proposals.
- No mocks are used in the added tests. The hard-check test calls real plane
  inclusion, support, and transport functions for every generated candidate.

## Concerns

No unresolved correctness concern from Task 2 or independent review. Runtime
data above covers a controlled unit fixture only; simulator-level packing
quality and throughput remain work for later tasks/evaluation.
