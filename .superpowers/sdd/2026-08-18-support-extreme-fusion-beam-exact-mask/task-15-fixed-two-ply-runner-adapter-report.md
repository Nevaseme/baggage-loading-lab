# Task 15 — runner-only `fixed-two-ply` adapter

## Outcome

The official-physics diagnostic runner now accepts:

```text
--b-planner beam|one-ply|fixed-two-ply
```

`beam` remains the default.  `fixed-two-ply` is installed only when both the
requested and initialized mode are explicitly B.  Auto-resolved B, A, and C
are not wrapped.  No production Agent default or physical validator changed.

## Exact dispatch boundary

The runner constructs `FixedQuotaExactTwoPly` from the initialized Agent's
existing `scanner`, `exact_mask`, and `settings`.  Its narrow adapter replaces
only `choose_b` dispatch and forwards the exact same state, complete ordered
pool (including lookahead 40), root catalog, and absolute deadline.  The
Agent's fixed mode, lookahead, state rebuilding, initial catalog, deadline
incumbent, and final fresh exact formatter remain unchanged.

The original Beam is retained by the adapter and its `choose_c` is delegated
unchanged.  Existing `beam` and `one-ply` routes are unchanged.

## Diagnostic trace

The result JSON continues to record `b_planner` and now contains:

```json
{
  "diagnostic": {
    "b_search_traces": []
  }
}
```

Each actual fixed-planner `choose_b` invocation contributes one serializable
`BSearchTrace` with its policy step.  The adapter increments an invocation
revision only inside `choose_b`; the runner compares the revision before and
after each policy call.  Therefore:

- an Agent deadline-incumbent path that skips the planner emits no fake
  all-zero trace;
- a planner invocation followed by formatter failure retains the matching
  trace in the policy-exception result; and
- a planner invocation that itself raises clears its pending trace and cannot
  relabel the preceding step's trace; and
- a stale trace from a preceding policy step cannot be relabelled as current.

## TDD and review evidence

Initial RED failed because the runner had no `FixedQuotaExactTwoPly` route.
The first GREEN covered parser selection, exact Agent-component construction,
40-element pool identity, argument identity, B-only installation, existing
route isolation, and JSON trace serialization.

Independent Sol review then found that trace capture was not tied to the
current `choose_b` invocation.  Two focused RED fixtures reproduced both the
false initial trace and lost formatter-exception trace.  Invocation revision
binding made both GREEN.  Re-review then identified a planner-exception path
that could still reuse the prior trace.  A two-step RED reproduced the stale
`[(0, 7), (1, 7)]` record; trace clearing before invocation and publication
only after successful planner return reduced it to the truthful `[(0, 7)]`.

Fresh project-local WSL results after the review fix:

```text
runner focused:       19 tests, PASS, 0.113s
full simulator suite: 344 tests, PASS, 11.455s
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -q
```

## Files changed

- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_run_support_extreme_fusion_physics.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-15-fixed-two-ply-runner-adapter-report.md`

No production algorithm, strict profile, action formatter, simulator,
dependency, historical artifact, Git state, or physics episode was changed or
executed in Task 15.  The next evidence step is a separate task001 seed42
physical comparison with `--mode B --b-planner fixed-two-ply`.
