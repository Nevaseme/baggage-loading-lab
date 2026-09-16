# Task 2 Report — Exact Root Feasibility Mask and Compressed Catalog

## Scope

- Modified `simulator/agents/highscore/candidates.py`: added the public
  `CandidateGenerator.validate_proposal` wrapper.  It resolves the requested
  container, preserves proxy pool index/orientation/AABB, computes existing
  state-derived inputs, and delegates all hard checks to `_validate_position`.
- Created `simulator/agents/highscore/catalog.py`: `RootAction` and bounded,
  fair, deterministic, exact-only root catalog construction.
- Modified `simulator/agents/highscore/settings.py`: added the four Task 2
  settings with the required defaults: 24, 6, 48, and 1.35 seconds.
- Created `simulator/tests/test_highscore_catalog.py`: validator equivalence,
  rejection, exact-only successor, fair-deadline, determinism, exception, and
  fake-clock deadline coverage.
- Did not edit the simulator core, Agent, Planner, MCTS, packaging, or submit
  artifacts.  `ems.py` changed independently during Task 1 support/path
  separation; Task 2 consumes its new optional support-level arguments and did
  not modify it.

## TDD evidence

### RED

Command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog.ValidateProposalTests -v
```

Result: 2 tests, 2 expected errors in approximately 1.8 seconds.  Both failed
with `AttributeError: 'CandidateGenerator' object has no attribute
'validate_proposal'`, proving the public wrapper was absent rather than a test
fixture error.

Catalog RED command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog.RootCatalogTests -v
```

Result: expected import error in approximately 2.0 seconds:
`ModuleNotFoundError: No module named 'agents.highscore.catalog'`.

### GREEN

Focused validator GREEN command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog.ValidateProposalTests -v
```

Result: 3/3 passed in 0.178 seconds.

Focused catalog GREEN command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog -v
```

Result: 8/8 passed in 0.249 seconds.

Required focused suites command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog simulator.tests.test_highscore_ems simulator.tests.test_highscore_candidates -v
```

Result: 47/47 passed in 0.661 seconds.

Full highscore discovery command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s simulator\tests -p 'test_highscore_*.py' -v
```

Result: 89/89 passed in 2.610 seconds.

## Review and concerns

Self-review confirmed the production scope is limited to Task 2 files above.
Every returned root couples a candidate returned by `validate_proposal` with a
non-None `apply_action` successor; proposal, validation, and assembly loops
check the absolute catalog deadline, and proposal/validation exceptions retain
roots already collected.  The catalog separates 18 mm horizontal/path
clearance from the 8 mm floor inset, 22 mm shelf drop, and zero placed-top gap
through Task 1's optional support parameters.

Known limitation: catalog candidates intentionally use the first (strictest)
existing generator margin/support target; it does not reproduce the legacy
generator's later relaxed/recovery search modes.  This is conservative and
keeps the root mask exact, but may reduce root breadth in tightly packed
states.  No unresolved test failure remains.

## Review fix round 1

The review found that proposal generation received a fair per-item deadline,
but the following exact-validation loop checked only the global deadline.  A
slow first item could therefore consume later items' catalog time.  A fake-clock
RED test observed validation pool indices `[0, 0, 1]` instead of `[0, 1]`:
the second pool-0 action was validated after its 0.50-second subdeadline.
`build_root_catalog` now checks both `item_deadline` and `catalog_deadline`
before every proposal validation, preserving already accepted roots and giving
later items their own proposal/validation opportunity.  The focused regression
then passed.

The validator now rejects orientations whose exact type is not `int` or whose
value is outside `0..5` before calling `oriented_dimensions`.  RED produced the
expected `IndexError` for `6` and `TypeError` for `"0"`; GREEN returns `None`
for `-1`, `6`, and `"0"` without aliasing or exceptions.

The swept-path fixture now places an obstacle 15 mm beyond the raw sweep.  Its
control assertion proves `transport_path_clear(..., clearance=0.0)` accepts the
path while the configured 18 mm clearance rejects it; `validate_proposal`
rejects the same placement.  A two-container catalog regression also proves a
blocker in container 0 does not remove exact roots in empty container 1,
successor `box_containers` records container 1, and the same local placement in
the blocked container remains invalid.

Review RED command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog.ValidateProposalTests.test_validate_proposal_rejects_non_integer_and_out_of_range_orientations simulator.tests.test_highscore_catalog.RootCatalogTests.test_item_validation_stops_at_fair_deadline_and_later_item_still_runs -v
```

Result: the invalid-orientation subcases errored as described above, and the
deadline case initially exhausted its mock clock; after giving the current
implementation a complete clock trace, the isolated deadline RED failed with
`[0, 0, 1] != [0, 1]` in 0.009 seconds.

Focused review GREEN command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog.RootCatalogTests.test_item_validation_stops_at_fair_deadline_and_later_item_still_runs simulator.tests.test_highscore_catalog.ValidateProposalTests.test_validate_proposal_rejects_non_integer_and_out_of_range_orientations simulator.tests.test_highscore_catalog.ValidateProposalTests.test_validate_proposal_rejects_unsupported_swept_path_and_depth_map_proposals -v
```

Result: 3/3 passed in 0.030 seconds.

Multi-container regression command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_catalog.RootCatalogTests.test_other_container_blocker_does_not_remove_empty_container_roots -v
```

Result: 1/1 passed in 0.008 seconds.

Final fresh post-review verification ran after the last test adjustment:
focused catalog 11/11 passed in 0.206 seconds; catalog, EMS, and candidate
suites 53/53 passed in 0.631 seconds; full `test_highscore_*.py` discovery
95/95 passed in 3.055 seconds.

Round-1 self-review found no Task 2 edits outside `catalog.py`,
`candidates.py`, `test_highscore_catalog.py`, and this report.  The concurrent
Task 1 `ems.py` changes were consumed but not authored here.  No unresolved
Task 2 finding remains; the conservative strict-root limitation above is
unchanged.
