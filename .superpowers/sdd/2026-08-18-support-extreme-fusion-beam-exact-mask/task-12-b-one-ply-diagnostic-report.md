# Task 12: Mode-B One-Ply Diagnostic Route

## Scope

This is a runner-only diagnostic factor. Production Agent, proposal,
Catalog, ExactMask, Beam, transition, and feature modules are unchanged.

Changed files:

- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_run_support_extreme_fusion_physics.py`

## Design

The physics runner accepts:

```text
--b-planner beam|one-ply
```

The default is `beam`, preserving the existing physical runner path.

For explicit `--mode B --b-planner one-ply` only, a runner-local beam adapter
replaces `choose_b(state, pool, catalog, deadline)` with a direct call to the
same underlying Beam object's `choose_c(state, pool, catalog, deadline)`.
The wrapper forwards the original state, complete ordered pool, exact
depth-zero Catalog, and deadline objects without copying or truncation.

The adapter is installed after the real Agent has consumed the unchanged
mode-B initialization state. It does not change `Agent.mode`, lookahead,
resolved mode, observation pool, Catalog construction, ExactMask receipts, or
the final fresh formatter authorization. Mode A, mode C, `auto`, and the
default `beam` selection retain the original beam object.

Both normal episode JSON and minimal runner-failure JSON record the requested
`b_planner` value.

## TDD evidence

The first adapter test failed at module import because `_install_b_planner`
did not exist. The minimal runner-local adapter and CLI route made it pass.

Focused fixtures prove:

- CLI default `beam` and explicit `one-ply` parsing;
- a 40-occurrence pool reaches underlying `choose_c` by object identity and
  original `choose_b` is never invoked;
- state, pool, Catalog, and deadline arguments are unchanged;
- Agent mode remains B and B lookahead remains greater than one;
- one-ply episode JSON records both `b_planner=one-ply` and
  `resolved_mode=B`;
- C, A, auto, and default beam do not install the adapter;
- existing action-format, physical-status, exception, timing, atomic JSON,
  and failure-snapshot runner contracts remain covered.

## Verification

- Runner-focused suite: 14 tests, all pass, 0.086 s.
- Full package-aware discovery:
  `python -m unittest discover -t . -s simulator/tests -p 'test_*.py' -q`
  — 332 tests, all pass, 9.704 s.

Independent Sol review found no Critical or Important code/test issues. Its
only initial report finding was this verification section's stale placeholder;
the final verification counts above replace it. No PyBullet episode is run in
this implementation task; the parent evaluation task will execute the
beam/one-ply physical comparison.
