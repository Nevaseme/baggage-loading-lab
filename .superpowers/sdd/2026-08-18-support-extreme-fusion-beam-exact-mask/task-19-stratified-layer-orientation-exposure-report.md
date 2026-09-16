# Task 19 — Stratified Layer/Orientation Exposure Report

Date: 2026-08-19

## Outcome

Implemented the single-factor diagnostic algorithm
`memoized_stratified_layer_orientation_regret`. It changes only the bounded
prefix in which analytical `LayeredProxy` fit candidates are exposed. The
candidate universe, exact checks, coordinates, final stable ordering, regret
rank, local costs, occurrence quantum, global work quotas, strict depth-zero
catalog, and final `ExactMask` formatter are unchanged.

The diagnostic runner route is:

```text
--mode B --b-planner memoized-stratified-maxrects-regret
```

It is explicit mode-B only. The default remains `beam`; A, C, auto, one-ply,
fixed-two-ply, maxrects-regret, and memoized-streaming-maxrects-regret retain
their previous routing. The route can be combined with the existing explicit
`--candidate-rescue global-zero-adaptive-dense` scanner option.

No PyBullet episode, SIGNATE submission, package installation, Git operation,
or production-default switch was performed in this task.

## Design

`ProxyExposureOrder` has two exact enum values:

- `LEGACY_NESTED` is the default and runs the former nested implementation.
- `STRATIFIED_LAYER_ORIENTATION` groups fit specifications by
  `(container ordinal, support source, deduplicated official orientation)`.

The stratified path uses a deterministic diagonal bucket order so that early
bounded work crosses containers, support layers, and orientations. Each active
bucket contributes at most one previously unseen coordinate per round. Within
a bucket, existing support-patch, maximal-rectangle, and anchor order is
preserved. Duplicate coordinates retain the existing global key
`(container, orientation, rounded position)`. If work is not exhausted, both
paths use the same final stable sort and produce exactly matching candidates,
children, metrics, fit counts, and candidate counts.

The memoized streaming selector accepts the exposure enum and passes it only
to checked proxy preview. Its rank tuple and scheduling quotas are untouched.
`SelectionTrace` adds diagnostic-only accepted-candidate counts by support
source/orientation and a zero-candidate-node count. Those values do not enter
the selector rank.

The runner constructs the stratified selector from the Agent-owned strict mask
and settings, forwards the unchanged full B pool/catalog/deadline, and returns
only the selector's original depth-zero root through the Agent's existing
fresh formatter.

### Review fix round 1: lazy topology and truthful route metadata

Independent review identified that the first stratified implementation built
`_topology_rectangles` for every support patch while constructing buckets,
before consuming a single fit-test unit. This was uncounted work and could
spend deadline on support patches that a bounded occurrence quantum could
never reach.

The RED fixture creates 22 support patches and a fit-test quota of eight. The
pre-fix implementation called the topology builder 22 times; the required
value was eight. Bucket construction now stores only lightweight patch and
orientation descriptors. Each bucket iterator calculates same-layer blockers
and MaxRects only when that bucket is first advanced. The GREEN fixture records
exactly eight calls, never visits the final placed-top patch, and still consumes
exactly eight fit tests. Unlimited candidate/child/metrics/order equivalence
and all existing fixed-work counters remain green.

Round-one re-review found a second boundary: when every rectangle in a bucket
is empty or undersized, advancing its generator can cross many patches before
yielding a fit specification. Lazy generation alone therefore still permitted
unbounded topology probes while consuming zero fit tests. The finding was
accepted as Important.

Round-two RED used 20 undersized placed-top patches and quota eight. The
pre-fix iterator made 120 topology calls, returned zero candidates, and
consumed zero fit tests. The stratified call now has a private topology-probe
budget equal to its remaining local fit capacity. Each patch/orientation
topology materialization consumes one private probe; reaching the budget ends
all remaining bucket work without changing public fit/candidate counters. The
GREEN fixture performs eight probes, visits no tail patch, produces no
candidate, consumes zero fit tests, and is identical across 20 runs. Existing
viable quota-eight behavior still performs eight fit checks, while a
sufficiently large quota retains the complete legacy-equivalent universe and
stable ordering. Heavy analytical work is now bounded by at most one topology
probe plus one proxy fit check per unit of remaining local fit capacity.

Authoritative round-two re-review found a remaining fairness issue inside that
bound: one active bucket's `next(iterator)` could consume all eight probes on
successive empty patches before another orientation, layer, or container was
advanced. Round-three RED used 20 patches whose first two orientations were
undersized while orientation two fit. The bounded pre-fix code returned no
candidate because orientation zero consumed the probe budget.

Each patch generator now emits a private patch-boundary sentinel after its
anchors, including when it has no anchors. The scheduler retains that bucket
for the next round and immediately advances the next active bucket. One bucket
advance therefore performs at most one new topology probe; already generated
unique coordinates still consume the unchanged public fit work. The GREEN
fixture reaches orientation two within eight probes and returns a valid
candidate. All-undersized, all-fit, unlimited, multi-container/layer, and
determinism regressions remain green.

The same review noted that JSON's legacy `b_planner` field records the requested
CLI value even when C, A, or auto correctly prevents installation. The field is
retained for backward compatibility, and a new `b_planner_settings` object now
records `requested`, `effective`, and `enabled`. Explicit requested+resolved B
records the selected diagnostic planner; C/A/auto record effective `beam`.

## TDD evidence

The first RED run failed during collection with two import errors because
`ProxyExposureOrder` did not exist. After adding only the enum, the behavioral
RED run exposed the intended missing boundaries: six calls rejected the new
`exposure_order` keyword, the selector rejected the new constructor contract,
and the runner rejected the new route. The first scheduler implementation then
had three failing prefix/equivalence assertions plus the unimplemented selector
route. Instrumented calls identified Python generator late binding: every
stratified bucket used the last orientation. Storing orientation in each bucket
entry fixed that root cause.

The tests cover:

- unlimited legacy/stratified candidate, child-state, metrics, and work
  equivalence, including two containers and floor+shelf layers;
- eight-fit bounded diversity across container, layer, and orientation;
- recovery when the first legacy bucket is invalid but a later orientation is
  valid;
- six-orientation dimension deduplication for a cube;
- exact fit quota accounting and 20 deterministic repetitions;
- default versus explicit legacy selector rank/trace identity;
- original catalog-root object identity and fresh `apply_root` authorization;
- accepted exposure counters and zero-candidate-node diagnostics;
- runner parser/dispatch/full-pool/trace serialization and B-only isolation.

An initial full-suite run found one test-fixture order dependency: two new
tests passed the selector a literal deadline `100.0` while `ExactMask` uses the
real monotonic clock, which had advanced past 100 seconds during the suite.
The observed WSL `time.perf_counter()` was 150.661460457. Replacing the fixture
with `time.perf_counter() + 100.0` fixed the source mismatch; no production code
was changed for that failure.

## Frozen analytical replay

These are replay-only measurements from stored observations. Scanner time is
separate from selector time. No physics was run. Every selected root below was
an original current catalog object and passed fresh `apply_root` authorization.
Wall times are machine/run dependent and are not Public-score evidence.

| Snapshot | Exposure | Catalog | Selector s | Deepest | Nodes | Fits | Candidates | Predicted | Selected pool/item | Position | Fresh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| initial | legacy | 64 | 5.303683 | 3 | 332 | 3,072 | 1,675 | 3 | 2 / 2 | (-0.222194, 0.000000, 0.183000) | yes |
| initial | stratified | 64 | 5.301791 | 3 | 308 | 2,536 | 1,875 | 3 | 2 / 2 | (-0.568500, 0.477000, 1.007000) | yes |
| step 8 | legacy | 64 | 5.325182 | 2 | 44 | 1,720 | 549 | 2 | 0 / 6 | (0.108822, -0.087596, 0.183000) | yes |
| step 8 | stratified | 64 | 4.370707 | 3 | 288 | 5,568 | 413 | 3 | 8 / 16 | (0.003126, -0.422000, 0.193000) | yes |

The initial decision remains item 2 but moves from the floor center to the
shelf/back exact root. At step 8, stratification completes without its 5.30 s
deadline flag, reaches predicted depth three rather than two, and selects a
decision-relevant different strict root. Candidate count is lower at step 8,
so the evidence supports diversity/depth recovery rather than a claim of raw
candidate-count improvement.

The stored memoized-streaming step-14 terminal snapshot was rescanned with the
unchanged strict-v2 mask and adaptive dense exposure:

```text
scan 4.089275 s
catalog roots 0
adaptive raw generated 40,900
adaptive exact attempts 39,894
covered occurrences 0
deadline reached false
```

Therefore Task 19 does not recover that already-terminal state. Its intended
effect is earlier decision quality. Whether the changed prefix delays or avoids
physical exhaustion requires a separate PyBullet run.

## Verification

Focused after review fix round 3:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_stratified_exposure
```

```text
Ran 12 tests in 0.748s
OK
```

Runner plus Task 19 focused tests after round 3:

```text
Ran 41 tests in 0.840s
OK
```

Related proxy/selector/adaptive-rescue/runner suite:

```text
Ran 106 tests in 10.532s
OK
```

Fresh full discovery after the fixture correction:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -t simulator -p 'test_*.py'
```

```text
Ran 446 tests in 20.210s
OK
```

`py_compile` also completed with exit code 0 for both changed production
modules, the runner, and the related tests.

## Files

- `simulator/agents/support_extreme_fusion_beam_exact_mask/layered_proxy.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/maxrects_regret.py`
- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_support_extreme_fusion_stratified_exposure.py`
- `simulator/tests/test_run_support_extreme_fusion_physics.py`
- `docs/superpowers/plans/2026-08-18-layered-maxrects-regret-exact-mask.md`
- this report

## Self-review

- The default legacy path is a separate unchanged branch.
- No rank tuple, local-cost coefficient, quota, strict mask, catalog, proposal,
  Agent public API, or action formatter was changed.
- Stratified candidates remain analytical only; no proxy type, receipt, or raw
  action can leave the selector.
- Truncated scheduling is deterministic and bounded by existing work counters.
- Finite-quota stratification materializes topology lazily and independently
  caps topology probes by remaining local fit capacity, including when no
  patch yields a fit specification.
- A patch-boundary sentinel prevents one empty bucket from monopolizing that
  topology budget before other active orientations/layers/containers advance.
- Unlimited scheduling is set-equivalent and stable-order equivalent to legacy.
- Runner metadata separates a requested diagnostic planner from the route that
  was actually installed.
- The frozen replay is explicitly analytical and makes no safety, physics, or
  Public-score claim beyond fresh exact authorization of the depth-zero root.
