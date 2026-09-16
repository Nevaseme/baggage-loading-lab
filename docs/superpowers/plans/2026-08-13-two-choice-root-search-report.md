# Two-Choice Root Search Report

## Changes

- Added `SearchSettings.online_root_item_choices = 2` and changed
  `policy_soft_limit_seconds` from `1.0` to `1.8`; the hard limit remains
  `5.75` seconds.
- Updated `Planner.choose_online` so that only beam depth zero ranks two
  root items. Each root generation receives an equal share of the time
  remaining for the untried root items. Deeper expansion retains its prior
  six-item limit and the global deadline.
- Added a fake-clock regression test. Its first candidate generation spends
  its supplied deadline; the test proves the second ranked root item is
  still generated and returned, with deadlines of `0.9` then `1.8`.

## RED evidence

Command:

```powershell
python -m unittest simulator.tests.test_highscore_planner.PlannerTests.test_online_root_search_tries_two_items_when_first_uses_its_budget -v
```

Before the implementation, the test failed as expected:

```text
AssertionError: [(0, 1.8)] != [(0, 0.9), (1, 1.8)]
```

This showed the original planner passed the whole deadline to the first root
item and therefore tried only that item.

## GREEN evidence

Focused test after implementation:

```text
Ran 1 test in 0.007s
OK
```

Full suite:

```powershell
python -m unittest discover -s simulator/tests -p 'test_*.py' -v
```

```text
Ran 35 tests in 2.061s
OK
```

## Self-review

- `choose_online`'s public signature and returned action shape are unchanged.
- Candidate validation, safety thresholds, candidate scoring, and the
  `policy_hard_limit_seconds = 5.75` setting are unchanged.
- The root comparison count is exactly two for pools with at least two
  items; single-item pools continue to use one choice.
- The per-choice allocation is restricted to depth zero. Deeper beam
  expansion continues to use the global deadline.
- No dependencies, Git initialization, or commits were added.

## Concerns

The required 30-item `task001` benchmark comparison against the accepted
20-safe-placement baseline was not run as part of this unit-test-only task,
so the experiment's keep-or-revert decision remains unverified.

## Benchmark decision and revert

The subsequent acceptance benchmark recorded 10 safe placements
(`completed_steps = 11`), fill `10.324`, and a maximum policy duration of
`5.750` seconds. This does not exceed the accepted 20-safe-placement
baseline, so the experiment has been reverted as required.

Reverted only the two-choice experiment changes:

- Removed `online_root_item_choices`.
- Restored `policy_soft_limit_seconds` to `1.0`.
- Restored the original six-item online ranking and global-deadline search
  path at every beam depth.
- Removed the experiment-specific fake-clock regression test and its test
  import.

Post-revert verification:

```powershell
python -m unittest discover -s simulator/tests -p 'test_*.py' -v
```

```text
Ran 34 tests in 2.143s
OK
```
