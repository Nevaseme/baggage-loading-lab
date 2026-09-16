# Root Fair Search Report

## Files changed

- `simulator/agents/highscore/planner.py`
- `simulator/tests/test_highscore_planner.py`
- `docs/superpowers/plans/2026-08-13-root-fair-search-report.md`

## Behavioral change

`Planner.choose_online` now divides the remaining soft deadline across the
remaining ranked choices only at root depth. Each root call to
`_top_candidates` receives `now + max(0.0, deadline - now) / max(1,
remaining_choices)`. Deeper beam levels still receive the original global
deadline, whose existing checks remain the hard cutoff. Candidate generation,
validation, ranking, beam widths, and fallback behavior are unchanged.

## RED

Command:

```powershell
python -m unittest simulator.tests.test_highscore_planner.PlannerTests.test_online_planner_fairly_checks_all_ranked_root_items
```

Result (before the planner change):

```text
F
FAIL: test_online_planner_fairly_checks_all_ranked_root_items
AssertionError: 1 != 6
Ran 1 test in 0.001s
FAILED (failures=1)
```

The fake generator advanced the clock to its supplied deadline. The old code
gave the first root item the global deadline, so only one of six roots was
attempted.

## GREEN

Focused command:

```powershell
python -m unittest simulator.tests.test_highscore_planner.PlannerTests.test_online_planner_fairly_checks_all_ranked_root_items -v
```

Result:

```text
test_online_planner_fairly_checks_all_ranked_root_items (...) ... ok
Ran 1 test in 0.001s
OK
```

Full command:

```powershell
python -m unittest discover -s simulator/tests -p 'test_*.py' -v
```

Result:

```text
Ran 35 tests in 2.050s
OK
```

## Self-review

- Root allocation uses the plan's specified formula and the last available
  root allocation ends at the global deadline.
- Existing global deadline checks remain in place; deeper levels continue to
  pass the global deadline unchanged.
- The regression test observes all six real planner root attempts and the
  returned sixth attempt rather than only checking a mock call count.
- No Git initialization, commits, dependencies, public API, action contract,
  or safety constraints were changed.

## Concerns

None. Test commands required the approved elevated execution path because the
sandbox denied NumPy's compiled extension access; both recorded RED and GREEN
results were obtained successfully there.

## Revert after physical benchmark regression

The physical benchmark regressed from 20 safe placements / fill 20.233 to 18
safe placements / fill 17.660 under the same 5.750-second maximum. The root
per-item allocation left approximately 0.17 seconds per choice and produced
insufficient candidate sets.

Reverted only the fair root-deadline implementation from
`simulator/agents/highscore/planner.py`, plus its dedicated regression test
and the `patch`, `AABB`, and `Candidate` imports from
`simulator/tests/test_highscore_planner.py`. No other existing code was
modified.

Verification command:

```powershell
python -m unittest discover -s simulator/tests -p 'test_*.py' -v
```

Result after revert:

```text
Ran 34 tests in 2.187s
OK
```

The test command again required elevated execution because the filesystem
sandbox blocks NumPy's compiled extension from loading.
