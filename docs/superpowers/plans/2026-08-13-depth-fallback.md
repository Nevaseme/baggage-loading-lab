# Depth-Aware Geometry Rescue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` and
> `superpowers:test-driven-development` task by task.

**Goal:** Replace invalid last-resort actions caused solely by conservative
depth rejection with candidates validated from settled AABB geometry.

**Tech stack:** Python 3.12, standard library, NumPy, unittest, existing
PyBullet integration harness.

## Task 1: Production rescue and unit tests

- Modify `simulator/agents/highscore/agent.py`.
- Modify `simulator/tests/test_highscore_planner.py`.
- Add a RED test proving the current policy does not rebuild a no-depth state
  after its primary planner returns no candidate.
- Implement a bounded `_geometry_rescue` helper which receives the observation,
  pool, and absolute hard deadline.
- Fairly allocate remaining time across the existing sorted emergency item
  order, collect validated candidates, and choose by the documented key.
- Preserve the exact action dictionary and deterministic final fallback.
- Run the focused test and complete unittest discovery.

## Task 2: One-factor physical gate

- Add `--geometry-rescue {on,off}` to `simulator/tests/run_physics_smoke.py`
  without changing environment behavior.
- RED/GREEN test its CLI exposure.
- Run task000/25 and task001/30, seed 42, optimize 0, rescue off/on, with
  monotone ingress fixed off and no harness `--rescue-without-depth` override.
- Save stdout/stderr under
  `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/`.
- Adopt only under the design gate; otherwise default the factor off.

## Task 3: Review and artifact decision

- Request independent spec and code-quality review.
- Run full unittest discovery, compileall, official four-item smoke, and final
  task000/task001 verification.
- Build a new submission ZIP only if the physical gate passes; otherwise keep
  `simulator/submissions/highscore_guarded_20260813.zip` immutable.
- Record the original SHA-256
  `3789B037DA39BD2F38215D711C42AD9CF504503F44B94016517A675044CB4A54`.
