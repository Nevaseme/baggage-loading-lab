# Task 7c: official physics evaluation runner report

## Scope

New files only:

- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_run_support_extreme_fusion_physics.py`
- this report

No existing runner, production agent, simulator, configuration, historical
algorithm, or submission artifact was edited. Per task ownership, the parent
will execute real PyBullet; this task implements and unit-verifies the runner
without starting physics.

## TDD evidence

The runner contract was written first. Initial RED was:

```text
ModuleNotFoundError: No module named
'tests.run_support_extreme_fusion_physics'
Ran 1 test ... FAILED (errors=1)
```

The first GREEN run exposed one test expectation that treated an exact
serialized `float32(0.2)` as decimal `0.2`. The runner correctly preserved the
submitted coordinate (`0.20000000298023224`), so the assertion was corrected
to a literal target with `1e-7` tolerance rather than rounding the diagnostic
action record. The final focused suite is clean.

Independent review then found one Important pre-physics gap: non-negative but
out-of-range pool/container indices were accepted by the runner. A focused
regression was RED because the validator did not yet accept observation
context. Validation now requires exactly the four public action keys and
checks item/container bounds against the current observation immediately
before `env.step`. Pool index 99, container index 99, and an extra-key action
all produce `other_exception` with zero physics calls. Final independent
re-review returned APPROVE with no Critical or Important findings.

## CLI and materialization

The dedicated CLI accepts only:

```text
--task 000|001
--items POSITIVE_INT
--seed INT
--mode auto|A|B|C
--output JSON_PATH
--snapshot-on-failure NPZ_PATH   # optional
```

It deep-copies the selected entry from `configs/sample_config.json`, truncates
only the copied item list, disables visualization, and applies mode overrides
through `agent.optimize` and `item_stream.look_ahead`. `auto` preserves the
sample mode. Explicit B fixes lookahead above one even for a one-item run;
explicit C fixes lookahead to one. Explicit A is recorded as `not_ready`
because Task 7b has not installed offline planning.

The production class is imported directly from
`agents.support_extreme_fusion_beam_exact_mask.agent`; there is no dynamic
historical-agent selection.

## Episode execution

The runner constructs the official `GroundHandlingEnv`, then calls in order:

1. `reset_settings()`;
2. `reset_item_stream()`;
3. `get_init_states()` and `Agent.get_init_states()`;
4. `reset(seed=...)`.

Before every policy call it copies `env.shm_depth_map` into the observation.
It measures policy wall time, validates exact public action keys, exact integer
fields, current pool/container occurrence bounds, orientation range, position
shape, and finite coordinates, then calls `env.step` exactly once. Malformed
or out-of-range actions never enter physics.

Every completed step records the action, policy seconds, official
`is_included`, `is_valid`, and `is_placed_safe` status, status-format result,
and terminated/truncated flags. The episode stops at the first malformed or
false official predicate and preserves its step, first predicate, and complete
status. No probe, replay, fallback, second step, or post-failure policy occurs.

The final result includes safe placements, completed steps, packed-item count,
termination state, full `env.evaluate()` output including `fill_score` and
`num_placed_items`, and policy count/p50/p95/p99/max. Candidate-zero, planning,
not-ready, and other exceptions have distinct outcome categories, type,
message, and step. `env.evaluate()` is attempted and `env.close()` is called
for success and all failure paths.

## Persistence

`main` writes normal and failure results through `atomic_write_json`. The
writer creates a same-directory temporary file, dumps the complete
JSON-serializable result, flushes and `fsync`s it, and atomically replaces the
target. A failed pre-run configuration/load path is first materialized as a
minimal classified failure result and is saved through the same function.

After the first real task001 B run reached nine safe placements and then
`candidate_zero`, the runner gained an optional replay snapshot boundary. It
deep-copies the current observation after attaching the copied depth map but
before calling policy. The first policy exception or first physical predicate
failure writes that pre-action observation through the existing
`replay_support.save_observation_snapshot` format. A same-directory temporary
snapshot is flushed, `fsync`ed, and atomically replaced; the final file's
SHA-256 and resolved path are stored under `failure_snapshot` in JSON.
Snapshot-write failure is recorded separately and never replaces the primary
physics/planning outcome. Successful episodes create no snapshot.

Snapshot review found one further physical-failure edge: an all-true official
status followed by early termination or truncation before the effective item
target was classified as physical failure but did not save the available
pre-action snapshot. Forced-stop RED fixtures now cover both paths. The runner
retains the last deep pre-action observation, attributes the failure to the
actual last `env.step` index (rather than a nonexistent next step), and stores
the last action/status with predicate `early_termination` or `truncated`.
Final independent re-review returned APPROVE with no Critical or Important
findings.

## Unit coverage

- bounded CLI parser and positive item count;
- deep-copy materialization and A/B/C overrides;
- successful two-step official status/evaluation record;
- first physical predicate failure and immediate stop;
- CandidateZero/Planning/NotReady/other exception classification;
- literal four-sample p50/p95/p99/max values and zero-time handling;
- malformed/non-finite action rejection before `env.step`;
- out-of-range pool/container and extra-key rejection with zero physics calls;
- malformed official status classification;
- copied depth map, reset/init order effects, seed, final packed count, close;
- same-directory atomic replacement and absence of temporary residue.
- candidate-zero snapshot remains unchanged even if policy mutates its input;
- physical-failure snapshot is the observation before the failed action;
- replay loader restores the depth map and failure metadata;
- successful episodes create no snapshot;
- snapshot atomic replacement and recorded file-byte SHA-256.
- early termination and truncation snapshot the actual last pre-action step.

## Verification

Fresh final results after independent review fixes:

```text
runner focused: 11 tests in 0.104s ... OK
full simulator discovery: 315 tests in 17.198s ... OK
py_compile runner and focused test: exit 0
```

## Usage

Example commands for the parent-owned real physics phase:

```powershell
$env:PYTHONPATH='.;simulator'
python simulator/tests/run_support_extreme_fusion_physics.py --task 001 --items 42 --seed 42 --mode B --output results/support-extreme-fusion-task001-b.json --snapshot-on-failure results/support-extreme-fusion-task001-b-failure.npz
python simulator/tests/run_support_extreme_fusion_physics.py --task 000 --items 41 --seed 42 --mode C --output results/support-extreme-fusion-task000-c.json
```

Exit code is zero only for a complete safe result; every failure still writes
JSON and exits nonzero.

## Known boundary

This runner records official local `fill_score` and `num_placed_items` only.
CoG, support, protection, displacement, and stability proxies are explicitly
deferred. No claim about real-physics completion, runtime, or Public score is
made until the parent executes the runner.
