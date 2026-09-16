# Task 2 brief — Capture historical pre-action snapshots and predicate recall

Read `C:\Users\TAKUMI\projects\Baggage-Loading\AGENTS.md` first and obey it.
Task 1 owns `progress.md`; do not modify it in this task.  Historical artifacts
under `submit/` are immutable.

## Goal

Rerun the untouched Public-29.7 historical task000 Mode-A control while
capturing every pre-action observation without probing or mutating live physics,
then analyze the saved snapshots only after the episode to produce a predicate-
by-step recall table for the current strict validation profile.

## Files

- Modify `simulator/tests/run_historical_conservative_extreme_point_physics.py`.
- Create `simulator/tests/replay_historical_predicates.py`.
- Create `simulator/tests/test_replay_historical_predicates.py`.
- Produce, when the physical command is run,
  `simulator/results/portal_reserved_scaffold/historical-task000-predicate-recall.json`
  and a sibling snapshot directory.

Do not alter `simulator/tests/run_support_extreme_fusion_physics.py`, the
physical environment, current production agents, or any historical artifact.

## TDD sequence

1. Write focused tests first using real snapshot serialization and small fake
   agent/environment boundaries where physics is not required.
2. Run
   `simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_replay_historical_predicates -v`
   and record an expected RED failure caused by missing capture/replay behavior.
3. Implement the minimum diagnostic behavior.
4. Rerun the focused test and record GREEN.
5. Run existing historical-runner and replay-support focused tests to detect
   regressions.

Before each test, name the production mutation it catches.  Expected values for
synthetic cases must be hand-derived literals.

## Capture contract

Add opt-in CLI flag:

```text
--capture-all-snapshots <directory>
```

The default path remains disabled and preserves existing behavior byte-for-byte
at the public result boundary.  When enabled:

- capture the exact observation given to every `policy` call and the action
  returned for that call;
- do not call any validator/probe against the live environment;
- do not copy or write the snapshot inside the measured policy interval;
- keep observation references/call evidence in the parent diagnostic proxy and
  serialize deep copies only after `run_episode` returns;
- use `tests.replay_support.save_observation_snapshot` through an atomic file
  replacement, one `step-000.npz` style file per attempted action;
- metadata contains task, seed, requested/resolved mode, zero-based step,
  serialized float32 action, historical source SHA-256, config SHA-256, runner
  SHA-256, and action-sequence SHA-256;
- return `pre_action_snapshots` in the result as ordered objects with step,
  workspace-relative path where possible, and lowercase SHA-256;
- save an atomic `manifest.json` with the same ordered records and a manifest
  SHA-256 in the episode result;
- 26 attempted actions in the matched control must yield 26 snapshots; 25 are
  known safe and attempt 25 is the existing ingress failure;
- artifact manifests before and after must remain identical.

If capture serialization fails, record a structured `snapshot_capture_error`,
mark the diagnostic result non-promotable, and leave the physical outcome
unchanged.

## Replay API and output

Expose:

```python
def replay_action(snapshot: dict, action: dict, profile=None) -> dict[str, object]
```

The default profile is the current
`support_extreme_fusion_beam_exact_mask.settings.SearchSettings`.  Build the
current `PackingState` and exact visible pool from the saved observation, bind
the serialized float32 target to a `PlacementProposal`, and run
`ExactMask.diagnose`.

The row must include:

- `step`, item occurrence/index, container ordinal, orientation, float32 target;
- `state_fingerprint` and `profile_digest`;
- independent booleans for `item_binding`, `container_ordinal`,
  `container_eligibility`, `target_collision_clear`, `plane_inclusion`,
  `support_ratio`, `center_support`, `protection`, `transport`, and `depth_map`;
- measured `support_ratio_value`, `required_support`, `min_clearance`, and
  `effective_lift` where calculable;
- `exact_mask_accepted`, `exact_mask_first_reason`, and detail;
- observed official step status from the capture metadata;
- `known_safe` derived only from the observed official status, not from the
  analytical predicates.

Independent predicate reporting is diagnostic duplication, not a new action
authorizer.  Reuse existing geometry/state/model functions and `ExactMask`
private helpers where safe; keep any remaining duplication confined to this
test script and explain it.  Do not change current strict thresholds and do not
calibrate them in this task.

The CLI accepts a snapshot manifest and episode result path and writes a JSON
object containing artifact/config/runner/action hashes, current profile digest,
counts by first reject reason, known-safe exact-mask recall numerator/
denominator, failed-action acceptance, and all ordered rows.

## Physical command

Run from `simulator/` with the project-local runtime and official lifecycle:

```powershell
.\.signate_venv\Scripts\python.exe -m tests.run_historical_conservative_extreme_point_physics --task 000 --items 41 --seed 42 --output results/portal_reserved_scaffold/historical-task000-captured.json --snapshot-on-failure results/portal_reserved_scaffold/historical-task000-failure.npz --capture-all-snapshots results/portal_reserved_scaffold/historical-task000-snapshots
```

Then run the replay CLI to create the required recall JSON.  The historical
runner exits 1 for the known physical failure; this is expected only if the
JSON proves 25 safe placements, first failure step 25, `is_valid=false`, and
unchanged artifact integrity.

## Report

Write the full report to
`.superpowers/sdd/2026-08-24-portal-reserved-scaffold-portfolio/task-2-report.md`.
Include RED/GREEN outputs, regression tests, physical/replay commands, exact
outcome/count/fill/timing, recall counts/reasons, hashes, changed files, and
self-review.  Do not spawn subagents.  Return only status, changed files,
one-line test/physical summary, and concerns.

