# Task 25 — Historical Conservative Extreme-Point Control Harness

Date: 2026-08-19  
Diagnostic name: `conservative_extreme_point_packing_historical_control`

## Outcome

A nonproduction runner now exercises the untouched 29.74350010538 historical
artifact through the same official environment lifecycle and guarded telemetry
path as the current experimental runner. Task25 did not run PyBullet, modify the
historical source, install software, use Git, or make a Public submission.

Historical source:

```text
submit/Conservative Extreme-Point Packing_score29.7/high_score/agent.py
SHA-256 EBE909962AB3A0722ABB5ED3E67A42DCEB64B116DD1F374C9EF739FDD3967F82
```

The harness records the resolved absolute package and source paths, source and
artifact-manifest digests, complete relative artifact file set, descriptive
algorithm name, and `historical_source_untouched=true` in every normal result.
A digest mismatch fails before a control run can begin; a source, metadata, or
file-set mutation during a call is rejected before an order/action can reach
the environment and is recorded as `artifact_mutation` with `unchanged=false`.

## Isolation and official lifecycle

The loader takes an atomic logical snapshot of the artifact directory, reads
`agent.py` bytes once for that snapshot, hashes those exact bytes, and passes
the same immutable bytes to `compile(bytes, literal_path, "exec")`. Execution
uses a fresh `ModuleType` which is never registered in `sys.modules`. No
`SourceFileLoader`, normal import, pyc read, or pyc write is involved. Existing
misleading pyc content is preserved in the manifest but ignored by execution.
The loader verifies the public `Agent` class and its `get_init_states`,
`optimize`, and `policy` methods before construction.

Agent state lives in one persistent isolated spawn worker. Calls use the
task000 configuration deadlines rather than unrestricted wall time:

```text
get_init_states / construction boundary: 10 s
optimize:                              180 s
policy:                                  8 s
```

Each call polls the worker, checks the artifact manifest before and after, and
kills/joins the worker on timeout. Initialization, optimization, and policy
timeouts are classified independently. They return no action, never call
`env.step`, save a replay-compatible atomic snapshot labelled
`failure_kind=agent_timeout` and `timeout_stage`, and close the worker. A worker
exception is also bounded and fail-closed.

The runner delegates to the already-tested official physics runner with
requested/resolved Mode A. The relevant lifecycle is therefore:

```text
get_info_for_optimization
→ Agent.optimize
→ env.set_item_order
→ env.reset_item_stream
→ env.reset(seed=42)
→ guarded policy / env.step loop
```

The surrounding official initialization (`reset_settings`, initial item-stream
reset, `get_init_states`) is retained. Each action must pass the same exact key,
integer/range, finite float32-compatible position, current pool index, and
container index checks before `env.step`. Timing summaries, official status,
first failure, evaluation, atomic failure snapshot, and atomic JSON use the
same implementation as the current runner.

## TDD evidence

RED was observed before runner implementation:

```text
ModuleNotFoundError:
tests.run_historical_conservative_extreme_point_physics
Ran 1 test — FAILED (errors=1)
```

Focused GREEN covers:

- fixed task000 / 41 items / seed42 parser defaults;
- exact historical digest and isolated module loading;
- exact source-byte compile with an existing misleading pyc ignored and no new
  cache file;
- artifact source and file-set mutation rejection before physics;
- persistent worker late return, infinite hang, and exception bounds;
- init/optimization/policy timeout classification, snapshot, no `env.step`, and
  process cleanup;
- public Agent interface;
- optimize → set order → reset stream → reset ordering;
- optimize and policy timing telemetry;
- policy exception classification and replay-compatible atomic NPZ snapshot;
- out-of-range action rejection before any physics step;
- atomic JSON materialization and artifact metadata.

Fresh verification:

```text
Focused: Ran 10 tests in 5.311s — OK
Related historical/current runners: Ran 41 tests in 6.232s — OK
Full discovery: exit 0; discovered 568 tests
py_compile: exit 0
```

The full runner output stream is muted by an existing test-side stream capture;
the process exited zero and a separate loader count over the identical
`simulator/tests`, `test_*.py`, top-level `simulator` discovery reported 568.

## Files and SHA-256

```text
687CC5B44AAB51F46C10379E8A8DFF555B3123E008325E251326DAF51F5ED1F1  simulator/tests/run_historical_conservative_extreme_point_physics.py
A487324C14586E3A653A859F468253AEBEC2D6253527FE42B4E3A9BDDBF8379E  simulator/tests/test_run_historical_conservative_extreme_point_physics.py
B42A3700376FF03AE26E2F9B2428F32AB3EEDE44D229B67A7403529B590A2106  progress.md
```

The historical source digest above is a read-only control fact, not a changed
file hash.

## Pending physical control

The intended physical command, to be run separately by the parent after this
nonproduction implementation handoff, is equivalent to:

```text
python simulator/tests/run_historical_conservative_extreme_point_physics.py \
  --task 000 --items 41 --seed 42 \
  --output simulator/results/support_extreme_fusion/task000-a-historical-conservative-extreme-point-control-seed42.json \
  --snapshot-on-failure simulator/results/support_extreme_fusion/task000-a-historical-conservative-extreme-point-control-seed42-failure.npz
```

Until that run completes, safe placements, failure predicate, fill/count,
timing, and physical comparison with Task24 remain pending. No historical
control performance is inferred from the Public score.

## Task24 evidence recorded alongside the harness

`progress.md` now records the already-existing local files without treating
them as Public results:

- proxy-prefix alone: 10 safe actions, candidate-zero,
  `fill_score=9.4678630468`, count proxy `0.2439024390`;
- proxy-prefix plus Task23 adaptive dense: 15 safe actions, candidate-zero,
  `fill_score=13.1177476481`, count proxy `0.3658536585`.

Both runs retained the same prefix `3,17,21,33,1,28,5,2`, stored no full plan,
and are local PyBullet evidence only.
