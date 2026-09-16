# Task 18c — MaxRects Regret Runner Adapter

## Outcome

Added a diagnostic-only `maxrects-regret` mode-B route to the official
Gymnasium/PyBullet runner.  No production Agent, selector, exact validator, or
simulator file changed.

CLI selection:

```text
--b-planner maxrects-regret
```

The default remains `beam`.

## Routing boundary

The adapter is installed only when both the requested and resolved modes are
explicitly B.  A, C, `auto`, `beam`, `one-ply`, and `fixed-two-ply` retain
their previous objects and dispatch.

Installation requires the Agent-owned beam, scanner, exact mask, and settings.
It constructs `RegretProxySelector(agent.exact_mask,
settings=agent.settings)`.  For every `choose_b` invocation it:

1. receives the unchanged settled `PackingState`, full ordered visible pool,
   current strict `RootCatalog`, and Agent deadline;
2. builds `SimState.from_current(state, pool)`;
3. calls `selector.select(sim, catalog, "B", deadline)`;
4. returns the first ranked original root, or `None` when the tuple is empty.

The adapter cannot format an action.  The selected root continues through the
existing Agent catalog-identity check and mandatory fresh ExactMask formatter.
The original beam remains available for `choose_c`.

## Trace lifetime

Each successful selector invocation publishes its matching immutable
`SelectionTrace` to the runner diagnostic record.  Revision tracking is tied
to one `choose_b` call:

- a planner skip produces no trace;
- a successful selector call followed by a formatter/policy exception retains
  that call's trace;
- a selector exception clears the invocation slot and cannot relabel a prior
  step's trace;
- an empty ranked tuple still records the successfully completed selector
  trace before Agent fail-closed handling.

The serialized trace is stored in the existing
`diagnostic.b_search_traces` list and remains JSON-safe through `asdict`.

## TDD evidence

The initial RED run produced the expected parser, factory, and unsupported
planner failures.  GREEN regressions cover:

- CLI choice and unchanged default;
- explicit-B-only installation;
- Agent exact component ownership;
- full 40-occurrence pool identity;
- unchanged Catalog and deadline identity;
- `SimState.from_current` conversion;
- ranked original-root identity and no action-dictionary return;
- SelectionTrace serialization after policy success;
- successful selection followed by normal final action/physics flow;
- stale trace clearing after a selector exception;
- A/C/auto, one-ply, fixed-two-ply, and beam isolation.

Fresh verification:

```text
focused runner: 22 tests, PASS, 0.141 s
full simulator suite: 392 tests, PASS, 15.244 s
independent Sol review: APPROVE, no Critical/Important finding
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -q
```

## Physical command for parent execution

Task001 full stream, explicit B:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python \
  simulator/tests/run_support_extreme_fusion_physics.py \
  --task 001 --items 42 --seed 42 --mode B \
  --b-planner maxrects-regret \
  --output simulator/results/support_extreme_fusion/task001-b-maxrects-regret-seed42.json \
  --snapshot-on-failure simulator/results/support_extreme_fusion/task001-b-maxrects-regret-seed42-failure.npz
```

This command is intentionally not run in Task18c's implementation scope; the
parent owns the physical comparison and acceptance decision.

## Files changed

- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_run_support_extreme_fusion_physics.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-18c-maxrects-regret-runner-adapter-report.md`
