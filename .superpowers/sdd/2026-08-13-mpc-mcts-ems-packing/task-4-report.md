# Task 4 report — MPC-MCTS integration flag

## Scope

Modified only:

- `simulator/agents/highscore/settings.py`
- `simulator/agents/highscore/planner.py`
- `simulator/agents/highscore/agent.py`
- `simulator/tests/test_highscore_planner.py`
- `simulator/tests/run_physics_smoke.py`
- this report

No simulator core, EMS, catalog, MCTS, candidates, package, Git, install,
submission, or physical benchmark changes were made.

## RED then GREEN

RED tests were added first for the planner catalog/MCTS contract, stable seed,
MPC Agent route and hard-deadline fallback, and CLI help.  The bundled runtime
recorded the expected missing-implementation failures:

- `planner.build_root_catalog` was not imported;
- `Planner.stable_mpc_seed` was absent;
- `SearchSettings` rejected `use_mpc_mcts_ems`.

Command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_planner.PlannerTests.test_choose_mpc_scores_exact_catalog_roots_and_uses_shared_deadlines simulator.tests.test_highscore_planner.PlannerTests.test_stable_mpc_seed_changes_for_visible_item_and_packed_aabb simulator.tests.test_highscore_planner.AgentContractTests.test_policy_routes_mpc_flag_only_to_choose_mpc_and_preserves_container_identifier simulator.tests.test_highscore_planner.AgentContractTests.test_policy_mpc_failure_uses_existing_depth_emergency_hard_deadline simulator.tests.run_physics_smoke.PhysicsSmokeCliTests.test_help_exposes_algorithm_selection_flags -v
```

The initial default virtualenv could not collect any test because its NumPy
extension DLL was denied access.  The project-plan bundled runtime was used for
all evidence below.

After the minimal implementation, the focused planner/Agent tests were 5/5 in
0.111 s, and the CLI-help test was 1/1 in 0.357 s.

## Implementation

- `use_mpc_mcts_ems` is an experiment flag with default `False` beside the
  existing default-off flags.
- `Planner.choose_mpc` caps work at the earlier caller deadline or
  `start + mcts_policy_limit_seconds`, gives catalog construction no more than
  1.35 seconds, scores every exact catalog root before calling MCTS, and passes
  the remaining absolute deadline to `MCTSSearch.choose`.  In the initial Task
  4 implementation, empty or throwing catalog/MCTS work returned `None`; the
  review-fix below retains an already scored exact incumbent for MCTS failure.
- `Planner.stable_mpc_seed` uses explicit, quantized FNV-1a integer mixing of
  container geometry, packed/static AABBs, depth observations, and the ordered
  visible pool attributes.  It does not use Python `hash`, global RNG, clock,
  or `repr`.
- Agent ON routes only to `choose_mpc`; it uses `started + 5.40` for MPC and the
  pre-existing `started + 5.75` hard deadline for depth-aware emergency (or the
  independently enabled geometry rescue).  OFF retains the legacy branch.
  Action formatting and clamps are unchanged.
- The smoke harness adds `--mpc-mcts-ems {on,off}`, defaults all three rejected
  experiment CLI switches to off, reconstructs `Planner` after replacing all
  three flags, and emits `mpc_mcts_ems` in result JSON.  The environment import
  is deferred until after argument parsing so `--help` remains testable without
  PyBullet installed.

## Verification

```text
...python.exe -m unittest simulator.tests.test_highscore_planner -v
```

21/21 passed in 2.142 s.

```text
...python.exe -m unittest simulator.tests.test_highscore_catalog simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems simulator.tests.test_highscore_candidates -v
```

73/73 passed in 0.570 s.

```text
...python.exe -m unittest simulator.tests.test_highscore_settings simulator.tests.run_physics_smoke.PhysicsSmokeCliTests -v
```

3/3 passed in 0.854 s.

```text
...python.exe simulator/tests/run_physics_smoke.py --help
...python.exe -m compileall -q simulator/agents/highscore simulator/tests/test_highscore_planner.py simulator/tests/run_physics_smoke.py
```

CLI help includes `--mpc-mcts-ems`; compileall exited 0.

```text
...python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

120/120 passed in 6.473 s.

## Snapshot diagnostic (not a physical run)

Catalog-only replay at the normal 1.35-second allowance found 0 roots for
`task000_latest_failure.npz`, 48 roots for `task001_latest_failure.npz`, and
14 roots for `task001_step23_failure.npz`.  With the normal 5.40-second MPC
allowance, both task001 snapshots returned a non-last-resort action in 5.401 s.
With an intentionally short 0.20-second policy allowance (catalog 0.05 s), all
three snapshots instead reached the legacy last resort after the shared
emergency deadline: about 2.652 s for task000 and 5.75 s for each task001
snapshot.  Task000 has no compatible exact root/depth emergency in this saved
state, so no stronger assertion is fabricated.  No jointly-packable-count
improvement is claimed.  This is diagnostic evidence only; the planned
PyBullet physical gate remains authoritative and was not run.

## Self-review and concerns

Reviewed the changed routing: ON has no `choose_online` call, all primary MCTS
returns originate from the exact root catalog, and fallback shares the original
hard deadline rather than starting another 5.40-second budget.  The two
remaining concerns are the incompatible saved snapshots above and the default
virtualenv's local NumPy DLL permission failure; neither was changed in this
task.

## Review-fix round 1

The review identified that root scoring was all-or-nothing and did not observe
the remaining policy deadline; it also dropped an already exact-scored root
when MCTS construction/search raised or returned `None`.  This round changed
only Task 4 files.

New RED tests first demonstrated both failures: an A/B fake catalog where A
scored and B raised produced `None`, and a controlled score clock expiring just
after A produced `None`.  GREEN now checks the deadline before each score,
isolates individual score failures, passes only successfully scored roots to
MCTS, and retains a deterministic exact incumbent by violations, score,
support, clearance, top height, and stable IDs.  Empty/all-bad roots still
return `None`; MCTS construction/search exception or `None` returns the
incumbent.

Additional integration coverage includes a real one-item terminal MCTS root
through Agent ON (legacy `choose_online` is patched to fail; action is an exact
root and completes under 0.5 s), a deterministic 64x64 depth-seed smoke under
1.0 s, and the compatible `task001_step23_failure.npz`.  The latter builds a
fresh exact catalog and proves both Planner and Agent ON select a matching
exact root rather than `_deterministic_last_resort` with a bounded 0.50 s MPC
budget.  The harness now has pure `build_parser` and `configure_agent` helpers;
tests verify all experiment defaults off and that configuring on replaces all
three flags and rebuilds `Planner` without requiring PyBullet.

Review-fix verification:

```text
...python.exe -m unittest simulator.tests.test_highscore_planner simulator.tests.run_physics_smoke.PhysicsSmokeCliTests -v
```

28/28 passed in 6.614 s.

```text
...python.exe -m unittest simulator.tests.test_highscore_catalog simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems -v
```

54/54 passed in 0.717 s.

```text
...python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

125/125 passed in 7.753 s.  `compileall` and CLI help also exited 0.  No
physical benchmark was run.
