# Task 4 brief — Scaffold slot and future portal DAG

Source plan: `docs/superpowers/plans/2026-08-24-portal-reserved-scaffold-portfolio.md`

## Purpose

Extend the reviewed `portal_reserved_scaffold_dag` package from a calibrated
historical proposal shield into a score-improving Mode-A planner. Preserve the
historical low-column advantage while representing support dependencies and
future official Y-then-X ingress conflicts explicitly. This is the first
layout-quality factor after the Task 3 safety cross.

## Files

- Create: `simulator/agents/portal_reserved_scaffold_dag/scaffold.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/portal.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/planner.py`
- Modify: `simulator/agents/portal_reserved_scaffold_dag/agent.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_dag.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_planner.py`
- Create/update a paired physical runner/result only under
  `simulator/tests/` and `simulator/results/portal_reserved_scaffold/`.
- Report: `.superpowers/sdd/2026-08-24-portal-reserved-scaffold-portfolio/task-4-report.md`

## Required interfaces

Produce `ScaffoldSlot`, `SupportEdge`, `PortalEdge`,
`build_plan(items, containers, deadline)`, and
`repair_plan(observation, plan, deadline)`.

All planned, repaired, and emergency candidates remain proposal-only. The
reviewed Task 3 `authorize_current` / fresh receipt / formatter path is the
only action boundary. Do not weaken or bypass it.

## Required behavior and TDD order

1. Read `superpowers:test-driven-development/writing-good-tests.md`. Before
   each test body, name the production mutation that the test catches.
2. Write and run RED tests for:
   - back-before-front portal precedence under official Y-then-X motion;
   - supporter-before-child ordering;
   - priority-container capacity and eligibility;
   - soft/priority-compatible top slots;
   - deterministic plan/action hashes;
   - every planner route requiring the Task 3 authorizer;
   - deadline-retained partial plans instead of all-or-nothing discard.
3. Implement floor, shelf, and settled/planned item-top scaffold slots. A slot
   records support rectangle/height, admissible footprints, cumulative load,
   headroom, protection tags, and an ingress portal.
4. Construct support DAG edges and portal precedence edges from official
   Y-then-X swept conflicts. A placement that blocks a future deeper/wider
   sweep must be delayed behind that future intent.
5. Implement Mode-A beam repair. Ranking is lexicographic: authorized placed
   count, placed volume, protection feasibility, low mass-weighted CoG,
   remaining wide/deep portal capacity, then deterministic tie breakers.
   Retain the best completed partial child when the deadline expires.
6. Add one flag that changes only future portal reservation. With the flag
   disabled, reproduce the Task 3 historical shield control. With it enabled,
   preserve the same authorizer and compare the paired trajectory.

## Fixed paired experiment and promotion gate

Primary paired condition: official PyBullet/Gymnasium task000, 41 items,
seed42, Mode A, identical config and lifecycle for flag off/on.

Baseline evidence: 25 safe placements, fill `33.9439267916753`, failure/reject
at step 25, invalid/unsafe returned actions `0/0`.

Promote portal reservation only when either:

- it returns at least 30 physically safe placements; or
- it returns at least 28 physically safe placements **and** improves local
  fill by at least 3.0 absolute points over the paired control.

In both cases it must move or delay the entrance blocker, return no
invalid/unsafe action, preserve exact public action types, keep policy maximum
below 6 seconds, and keep optimization below 180 seconds. Otherwise reject
the factor and report why; do not disguise a failed gate by combining another
algorithmic factor.

## Global constraints

- Preserve the public `Agent` interface and exact action dictionary.
- Every returned action passes the reviewed current-state authorizer.
- No unchecked fallback; no candidate-zero lineage may be packaged.
- Historical submissions, Task 2 evidence, Task 3 evidence, and `submit/` are
  read-only.
- New names remain descriptive; no generic `best`, `final`, `highscore`, or
  unverified score in names.
- Official component weights are unknown; CoG, protection, support,
  displacement, and rotation are explicitly local proxies.
- Use project-local runtimes only. Do not initialize Git or commit.
- Do not spawn subagents. One writer owns these shared files.

## Report contract

Record RED and GREEN commands/output, changed files, deterministic hashes,
paired flag-off/on action divergence, first physical failure/rejection,
safe count, local fill, CoG/protection/support proxies when available, policy
p50/p95/p99/max, optimize time, fallback/replan rates, adopted/rejected
hypotheses, and remaining concerns. Return only status, changed files, a
one-line test/physical summary, and concerns to the controller.
