# Task 1 report — depth-aware geometry rescue

## Status

DONE

## TDD evidence

RED was observed in the isolated WSL test environment before production code
was changed.  The three new tests failed for the intended missing behavior:

- policy returned the deterministic last-resort position instead of the
  no-depth candidate;
- both direct rescue tests raised `AttributeError` because
  `Agent._geometry_rescue` did not exist.

Command:

```text
PYTHONPATH=.:simulator:simulator/.test_deps_linux python3 -m unittest \
  simulator.tests.test_highscore_planner.AgentContractTests.test_policy_rebuilds_a_no_depth_state_only_after_primary_returns_none \
  simulator.tests.test_highscore_planner.AgentContractTests.test_geometry_rescue_collects_all_items_and_uses_the_documented_rank \
  simulator.tests.test_highscore_planner.AgentContractTests.test_geometry_rescue_fairly_slices_the_remaining_hard_deadline -v
```

After the minimal implementation, the same focused command passed 3/3.

## Changes

- `Agent.policy` retains the depth-aware planner as the primary path and calls
  geometry rescue only when it returns no candidate and hard-deadline time
  remains.
- `_geometry_rescue` rebuilds `PackingState` from the same `container_list`
  without a depth map.
- Visible items retain the existing deterministic emergency order.  Each item
  receives an equal share of the then-remaining hard-deadline budget.
- Candidates still come from the production `CandidateGenerator` with all
  unchanged geometry/support/path validators.  All candidates found within
  their slices are scored and the best is chosen lexicographically by fewer
  rule violations, score, support, clearance, and lower height.
- Exact public action formatting and deterministic final fallback are
  unchanged.

## Verification

- Focused planner suite: 11 tests passed in 2.236 s.
- Complete unittest discovery: 55 tests passed in 2.721 s.
- The controller independently confirmed focused 3/3 and full 55/55 GREEN.

The Windows default NumPy runtime failed to import its C extension with an
environment-level access-denied error, so it was not treated as product-test
evidence.  No dependency was installed or changed; all accepted evidence used
the repository's pre-existing isolated Linux test dependencies.

## Self-review

- Scope is limited to `simulator/agents/highscore/agent.py` and
  `simulator/tests/test_highscore_planner.py`, plus this required report.
- No simulator, dependency, network, Git, or public API changes were made.
- Mutation check: removing no-depth reconstruction breaks the policy test;
  returning the first item's candidate breaks the all-items ranking test; and
  handing the first item the hard deadline breaks the fair-slicing test.

## Concerns

None within Task 1.  Physical adoption and an on/off setting are intentionally
deferred to Task 2's one-factor gate.

## Review fix round 1

The independent task review identified that `generate()` receives an
item-scoped deadline, but the returned candidate scoring loop previously had
no hard-deadline check.  A slow scorer or a large returned candidate list could
therefore overrun the public policy limit.  The review also requested cheap
negative and exception-path coverage.

TDD RED evidence:

- the primary-success negative test already passed, confirming rescue was not
  called before a primary candidate failed;
- the slow-scorer test failed because a second candidate was scored after the
  fake clock reached the hard deadline;
- later candidate-generation and scoring exceptions escaped the helper rather
  than preserving its existing best candidate.

Minimal fix:

- check the absolute hard deadline before scoring every rescue candidate and
  immediately return the best candidate accumulated so far;
- isolate generator exceptions to the affected item and scorer exceptions to
  the affected candidate, retaining the existing best;
- retain the existing primary-success path unchanged.

Post-fix verification:

- review-focused tests: 4 passed in 0.256 s;
- complete planner suite: 15 passed in 2.133 s;
- complete unittest discovery: 59 passed in 2.728 s.

No new concern was found in self-review.  Removing the per-candidate clock
check causes the slow-scorer test to score the second candidate and generate a
later item; removing either exception boundary causes its corresponding
best-preservation test to error.
