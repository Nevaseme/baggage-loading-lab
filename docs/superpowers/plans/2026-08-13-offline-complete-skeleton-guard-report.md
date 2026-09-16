# Offline Complete Skeleton Guard Report

## Changed files

- `simulator/agents/highscore/agent.py`
- `simulator/tests/test_highscore_planner.py`
- `docs/superpowers/plans/2026-08-13-offline-complete-skeleton-guard-report.md`

## RED

Before the production change, the focused test was run with:

```text
python -m unittest simulator.tests.test_highscore_planner.AgentContractTests.test_optimize_rejects_complete_order_when_skeleton_is_incomplete
```

It failed as expected because the old implementation accepted the valid
permutation even though its skeleton contained only two candidates:

```text
FAIL: test_optimize_rejects_complete_order_when_skeleton_is_incomplete
AssertionError: Lists differ: [13, 5, 8] != [5, 8, 13]
```

## Implementation and behavior

`Agent.optimize` now accepts the planner's order only when both conditions
hold:

1. `order` is a complete permutation of the input indices.
2. `skeleton` has exactly one candidate per input item.

For an invalid order, an incomplete skeleton, or a planner exception, it
clears `offline_skeleton` and returns the exact original input index order.
The online policy and candidate geometry/safety behavior were not changed.

Two contract tests use a fake planner response:

- A non-original complete order with an incomplete skeleton is rejected and
  clears a previously stored skeleton.
- The same order with a full-length skeleton is accepted and stored.

## GREEN

Focused contract tests:

```text
python -m unittest simulator.tests.test_highscore_planner.AgentContractTests
Ran 4 tests in 0.889s
OK
```

Full suite:

```text
python -m unittest discover -s simulator/tests -p 'test_*.py'
Ran 36 tests in 2.007s
OK
```

## Self-review

- The new condition checks the required skeleton length in addition to the
  pre-existing complete-permutation guard.
- Every fallback path clears `offline_skeleton` before returning the original
  order, including the non-exception incomplete-skeleton path.
- The acceptance test protects the intended full-skeleton success case, so the
  new guard does not reject valid optimized output.
- No dependencies, public API/return types, geometry, safety constraints, or
  online policy behavior were changed. No Git initialization or commit was
  performed.

## Concerns

The filesystem-sandboxed Python process could not load NumPy's DLLs
(`_multiarray_umath`: access denied). The same focused and full unittest
commands completed successfully outside that sandbox.

## Adoption benchmark

Scenario: the same `task000` with 25 items and a 30-second optimization limit.

| Version | Safe placements | Completed steps | Fill | Optimized order |
| --- | ---: | ---: | ---: | --- |
| Before guard | 12 | 13 | 6.7525984683 | Non-original |
| With guard | 17 | 18 | 11.3377270041 | Original order `0..24` |

With the guard, the maximum policy time was `2.506675436` seconds and the
optimization time was `30.002974272` seconds.
