# Task18e: `global_zero_adaptive_dense_rescue`

## Outcome

Implemented the Task18d single-factor follow-up without changing the default
agent or strict profile.  An explicitly configured `StrictRootScanner` now
uses one direct 4,096-work dense generation pass only after normal and deferred
families produce a globally empty exact catalog.  Exact checks are scheduled
one proposal per pool occurrence per round, stop an occurrence at its first
strict root, and stop globally after eight distinct occurrences.

The official-physics runner exposes this only through:

```text
--mode B --candidate-rescue global-zero-adaptive-dense
```

The default remains `--candidate-rescue legacy`.  `Agent`, `ExactMask`,
proposal generation, LayeredProxy, MaxRects rank, profile digest, and public
action formatting were not changed.

## Implementation

### Catalog

`AdaptiveDenseRescueConfig` is a non-profile scanner work policy:

- `raw_work_limit=4096`
- `covered_occurrence_target=8`
- `output_reserve_seconds=0.75`

`StrictRootScanner(..., adaptive_dense_rescue=None)` preserves the legacy
branch.  With a config, adaptive work activates only when:

1. normal plus eligible deferred scanning has accepted zero roots;
2. `allow_rescue=True`;
3. at least one valid pool occurrence remains.

The dense family is passed directly to `iter_fused_records` once per pool with
`raw_work_limit=4096`; no 256→1,024→2,048→4,096 restart sequence exists.
Materialized occurrence streams are exact-checked round-robin.  Duplicate
global item IDs do not collapse ordered pool positions.

An accepted diagnostic is never catalogued directly. It triggers exactly one
fresh `ExactMask.validate` call, and only that fresh returned receipt may enter
the catalog. The diagnostic and fresh receipts must be distinct objects and
match all formatter/transition fields:

- ExactMask ownership proof, `ValidatedRoot`, and `strict=True`;
- zero rule violations and current profile digest;
- current state+ordered-pool+selected-occurrence fingerprint;
- item signature, exact fused proposal, and proposal key;
- box min/max, axis alignment, oriented dimensions, and proposal center;
- support ratio, minimum clearance, source, and zero violations.

A diagnostic rejection calls `validate` zero times. A diagnostic accept whose
fresh validation returns `None`, returns a mismatching receipt, or reaches the
deadline is rejected.

No raw proposal or proxy value can enter the catalog.  The adaptive deadline
is `caller_hard_deadline - 0.75 seconds`; partial strict roots remain available
when that boundary is reached.

New deterministic `CatalogStats` fields record activation, generated dense
records, exact attempts, covered occurrences, early-stop/deadline state, and
per-pool generation/exact counts.  “Raw generated” is the number of
deduplicated `FusedProposal` records returned by the bounded generator; it is
not claimed to equal internal pre-dedup family iterations.

### Runner

The runner installs an adaptive scanner only for explicit requested and
resolved mode B.  It rebinds the Agent scanner and existing beam scanner before
installing the selected B planner, so `beam`, `one-ply`, `fixed-two-ply`, and
`maxrects-regret` retain their existing dispatch and formatter boundary.

The runner-only scanner recorder captures only the first catalog scan of each
policy call.  JSON now includes:

- `candidate_rescue` as the requested setting;
- `candidate_rescue_settings.requested`, `.effective`, and `.enabled`, so an
  A/C/auto no-op cannot be reported as active;
- the exact fixed parameters only when installation succeeded for explicit B;
- `diagnostic.adaptive_dense_scans`, including step and complete catalog
  statistics.

A/C/auto, default legacy, and non-B planner behavior are unchanged.

## Frozen Task18d evidence

On
`task001-b-maxrects-regret-seed42-failure.npz`, using the current strict-v2
mask and a 5.45-second caller deadline:

| Measure | Result |
|---|---:|
| Elapsed scanner time | 2.340 s |
| Strict roots | 8 |
| Covered pool occurrences | 8/10 |
| Dense records generated | 40,900 |
| Adaptive exact attempts | 5,382 |
| Per-pool strict roots | 1,1,1,0,1,1,1,1,1,0 |
| Eight-occurrence early stop | true |
| Adaptive deadline reached | false |
| Caller hard deadline reached | false |

Every returned original root was freshly accepted again by `apply_root` with
the same ExactMask, state, ordered pool, and profile.  This is an analytical
snapshot result only; no PyBullet step was executed in Task18e.

## TDD evidence

RED was recorded before implementation:

```text
python -m unittest \
  simulator.tests.test_global_zero_adaptive_dense_rescue \
  simulator.tests.test_run_support_extreme_fusion_physics -v
```

Both modules failed to import for the intended missing boundaries:
`AdaptiveDenseRescueConfig` and `_install_candidate_rescue`.

A second targeted RED was recorded for explicit runner parameter
serialization: the test failed with missing
`candidate_rescue_settings` before that payload was implemented.

Review-fix RED was recorded before the round-one corrections. The 35-test
focused run produced 8 expected failures: three subcases showed that adaptive
diagnostic accepts made zero `validate` calls, one showed the install API could
not report effectiveness, and four showed requested adaptive rescue serialized
as enabled even when ineffective (C, auto, A, and the updated explicit-B
schema). The diagnose-reject subcase already proved zero validate calls and
remained green.

Covered behaviors:

- legacy/default and adaptive nonzero-root path equivalence;
- no dense call when an ordinary root exists;
- one direct 4,096-cap dense call and a root after the legacy 256 cap;
- pool round-robin fairness and rootless early-pool non-starvation;
- first-root-per-pool and global-eight stopping;
- duplicate global IDs as distinct occurrences;
- deadline-reserve partial incumbent;
- stale/foreign exact evidence rejection;
- diagnose reject to zero validate calls, diagnose accept to exactly one fresh
  validate call, and rejection of `None` or field-mismatching fresh evidence;
- `allow_rescue=False` never invoking the adaptive dense generator;
- 20 deterministic synthetic scans with identical roots and stats;
- frozen step15 strict roots and fresh transitions;
- explicit-B-only runner installation and install-success reporting;
- requested/effective separation for C, A, and auto-resolved B;
- default isolation, exact setting serialization, and adaptive stats capture.

## Verification

- Final focused catalog+runner suite: **35/35 PASS** in 2.588 s.
- Related catalog+beam+Agent+runner suite: **89/89 PASS** in 8.204 s.
- Final package-aware full simulator discovery: **410/410 PASS** in
  17.298 s.

Commands used with the existing project WSL virtual environment:

```text
python -m unittest \
  simulator.tests.test_global_zero_adaptive_dense_rescue \
  simulator.tests.test_run_support_extreme_fusion_physics -v

python -m unittest \
  simulator.tests.test_support_extreme_fusion_catalog \
  simulator.tests.test_support_extreme_fusion_beam \
  simulator.tests.test_support_extreme_fusion_agent_bc \
  simulator.tests.test_global_zero_adaptive_dense_rescue \
  simulator.tests.test_run_support_extreme_fusion_physics -v

python -m unittest discover -s simulator -t simulator -p 'test_*.py'
```

## Self-review

- No setting was added to `SearchSettings`; strict profile digest is unchanged.
- Default scanner construction passes no adaptive config and stays on the
  existing legacy rescue branch.
- No change was made to Mask, proposals, LayeredProxy, MaxRects rank, Agent, or
  the public action dictionary.
- The adaptive branch uses only a fresh receipt returned by `mask.validate`,
  compares it field-for-field with diagnostic evidence and current bindings,
  and never formats output.
- The runner remains diagnostic-only and cannot activate adaptive rescue for
  A, C, auto-resolved B, or the default legacy flag.
- No global installation, Git operation, network call, or physics execution
  was performed.

## Next physical command (not run in this task)

```text
python simulator/tests/run_support_extreme_fusion_physics.py \
  --task 001 --items 42 --seed 42 --mode B \
  --b-planner maxrects-regret \
  --candidate-rescue global-zero-adaptive-dense \
  --snapshot-on-failure simulator/results/support_extreme_fusion/task001-b-maxrects-regret-adaptive-seed42-failure.npz \
  --output simulator/results/support_extreme_fusion/task001-b-maxrects-regret-adaptive-seed42.json
```
