# Task 4 Brief — Planner and Agent integration behind one flag

Implement only Task 4 from `docs/superpowers/plans/2026-08-13-mpc-mcts-ems-packing.md`.

## Files

- Modify `simulator/agents/highscore/settings.py`
- Modify `simulator/agents/highscore/planner.py`
- Modify `simulator/agents/highscore/agent.py`
- Modify `simulator/tests/test_highscore_planner.py`
- Modify `simulator/tests/run_physics_smoke.py`
- Write `.superpowers/sdd/2026-08-13-mpc-mcts-ems-packing/task-4-report.md`

No EMS/catalog/MCTS/candidates/simulator-core changes, Git, installs, packaging, submission, or physical benchmark runs in this task.

## Interfaces

- `SearchSettings.use_mpc_mcts_ems: bool = False`, placed beside the other experiment flags. Existing monotone/rescue defaults remain False.
- `Planner.choose_mpc(state, pool, *, deadline, seed) -> Candidate | None`.
- Harness `--mpc-mcts-ems {on,off}` default `off`, and JSON field `mpc_mcts_ems`.

## TDD sequence

1. RED planner contract with patched/fake catalog and MCTS. `choose_mpc` caps all work by `min(caller_deadline, start+5.40)`, allocates at most 1.35 sec to `build_root_catalog`, scores every exact root Candidate through the existing scorer before MCTS so the final secondary tie-break is meaningful, and passes remaining absolute deadline to `MCTSSearch.choose`. Empty/throwing catalog or MCTS returns None/preserves no invented action.
2. Implement `Planner.choose_mpc`. Stable seed is supplied by caller. Do not weaken exact root validation or call legacy planner inside this method.
3. RED Agent routing tests. ON calls only `choose_mpc`, never `choose_online`; OFF remains byte-for-behavior legacy `choose_online` plus depth-aware emergency/geometry-rescue branch. If ON returns None/raises, use the existing depth-aware emergency unless the independently default-off geometry rescue flag is explicitly ON. Never return a proxy action.
4. Agent ON deadline is exactly `started + mcts_policy_limit_seconds` (5.40 cap). Its fallback shares the pre-existing absolute hard deadline `started + policy_hard_limit_seconds` (5.75), leaving formatting overhead; no new 5.4 seconds after MCTS. OFF retains `policy_soft_limit_seconds` and identical legacy behavior.
5. Stable seed helper: derive a platform/process-stable integer from observation geometry, packed AABB coordinates and visible pool IDs/attributes using explicit integer mixing (e.g. FNV-1a over quantized numeric tuple/bytes). Never use Python `hash()`, `repr()` with unstable ordering, global RNG, wall clock, or secret state. Same observation -> same seed; a changed AABB/item index -> changed seed. It is okay for Agent or Planner to own the helper, but test it directly.
6. Preserve action formatting/clamping exactly. Candidate `container_index` is the public container identifier under current simulator assumptions; add a regression using sequential two containers. Pool-tail shrinking remains valid.
7. Harness RED/GREEN: help includes flag; immediately after Agent construction `replace` all three experiment flags (`use_monotone_ingress`, `use_geometry_rescue`, `use_mpc_mcts_ems`) and reconstruct Planner; JSON records selected mode. Defaults for all rejected experiments OFF.
8. Snapshot diagnostic tests use existing `task000_latest_failure.npz`, `task001_latest_failure.npz`/`task001_step23_failure.npz` if fixtures are compatible. ON must return either an exact root from a fresh catalog or the unchanged exact emergency fallback; never the known invalid last-resort action. Where deterministic proxy evidence supports it, assert chosen root's jointly packable visible count exceeds a legacy branch on at least one fixture; if that exact assertion cannot be made honestly, report the diagnostic evidence and leave physical gate authoritative rather than fabricating a test.
9. Deadline/exception tests patch clocks so catalog/MCTS consumes its slice; Agent returns before hard deadline with incumbent/fallback. Test ON one-item pool terminates promptly (MCTS terminal convergence).
10. Run focused planner+settings+CLI help, MCTS/catalog dependencies, snapshot tests, compileall, full `test_highscore_*.py`. Report commands/pass counts/timing/files/self-review/concerns. Do not claim physical success.

## Invariants

- Public Agent signatures and exact action dictionary unchanged.
- Every ON primary return came from exact `RootAction.candidate`; all fallback returns follow existing exact generator until final deterministic last resort.
- Rebuild `PackingState` from each settled observation.
- Standard library and NumPy only.
- Flag remains default False until Task 5 physical A/B gate.
