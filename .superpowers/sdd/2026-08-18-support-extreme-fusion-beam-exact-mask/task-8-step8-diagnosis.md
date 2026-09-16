# Task 8 — task001 B seed42 step 8 diagnosis

## Scope and outcome

This is a read-only diagnosis of production code. No agent, geometry, mask,
catalog, beam, or simulator source was changed.

The physical failure is **not a strict-geometry dead end and not a stale-root
failure**. The direct cause is a deadline inversion:

- the root catalog may scan until `started + 5.45s`;
- mode-B beam search receives the earlier deadline `started + 5.30s`;
- on this snapshot the catalog needs the rescue phase and returns five valid
  strict roots at about `5.46s`;
- `choose_b` therefore enters with a deadline already exceeded and returns
  `None` without evaluating a depth-zero edge;
- `Agent.policy` raises `PlanningError("B beam returned no root")`.

The snapshot contains valid future work. A longer normal scan finds 11 strict
normal roots, and fresh exact transition validation accepts all 11.

## Inputs

- Snapshot: `simulator/results/support_extreme_fusion/task001-b-seed42-failure.npz`
- Failed result: `simulator/results/support_extreme_fusion/task001-b-seed42-snapshot.json`
- Earlier comparison: `simulator/results/support_extreme_fusion/task001-b-seed42.json`
- Snapshot metadata: task `001`, seed `42`, mode `B`, failed policy step `8`
- State: one container, eight settled items, ten visible pool occurrences
- Reported exception: `PlanningError: B beam returned no root`

The diagnostic used the bundled project Python runtime and reconstructed the
state through the same `build_packing_state` path. The serialized depth map was
present with shape `(1, 64, 64)`, `float32`, range `0.0 .. 1.196637`.

## Reproduction with online deadlines

Two independent agent-like repetitions used the production settings and an
absolute policy start time. Scanner deadline was `+5.45s`; beam deadline was
`+5.30s`.

| Repeat | scanner elapsed | roots | root pass | elapsed before beam | beam budget at entry | result |
|---:|---:|---:|---|---:|---:|---|
| 0 | 5.462533s | 5 | rescue | 5.463523s | -0.163523s | `None` |
| 1 | 5.457924s | 5 | rescue | 5.458918s | -0.158918s | `None` |

All five roots were container `0`, orientation `0`, source
`free_rectangle_boundary`, position approximately
`(0.3837610, 0.5020000, 0.6499810)`, support ratio `1.0`, and minimum
clearance `0.0181139m`. They belonged to pool occurrences `3, 4, 5, 6, 9`
(item IDs `11, 12, 13, 14, 17`).

The two scans examined 629 and 649 raw/exact proposals. The first repetition's
rejection counts were collision/clearance `536`, floor frontier `41`, shelf
front release `27`, and support ratio `20`; the remaining five were accepted.

Production evidence for the timing mechanism:

- `agent.py:118-120` constructs catalog `+5.45s`, search `+5.30s`, and hard
  output `+5.75s` deadlines.
- `agent.py:122-126` lets the scanner consume the catalog deadline before
  calling the beam at `agent.py:134-142`.
- `beam.py:96-111` evaluates the depth-zero catalog under the already-expired
  search deadline; without an evaluated node its incumbent remains `None`.
- The configured values are in `settings.py:69-80`.

## Normal scan and exact-mask rejection evidence

With only the ordinary `1.80s` normal slice and rescue disabled:

- elapsed: `1.807138s`;
- raw/exact attempts: `285`;
- roots: `0`;
- per-pool raw attempts: `[31,31,31,31,27,27,27,27,26,27]`;
- rejections: collision/clearance `207`, floor frontier `41`, shelf front
  release `27`, support ratio `10`;
- no item exceptions.

With a `5.0s` normal slice and a `10.0s` hard scan deadline:

- elapsed: `5.014458s`;
- raw/exact attempts: `441`;
- strict normal roots: `11`;
- roots per pool: `[0,1,0,2,2,2,2,0,0,2]`;
- sources: six `plane_derived_edge`, five `obstacle_face_extreme`;
- all roots use container `0` and orientation `0`;
- rejections: collision/clearance `333`, floor frontier `41`, protection `3`,
  shelf front release `27`, support ratio `26`;
- no item exceptions.

The normal roots are:

- pool `1`, soft item `9`: one `plane_derived_edge` root at approximately
  `(-0.177567, 0.527, 1.391964)`, support source `placed_top:7`, ratio
  `0.998995`, clearance proxy `1.0`;
- pools `3,4,5,6,9`, items `11,12,13,14,17`: one
  `plane_derived_edge` root each at approximately
  `(0.383761, 0.502, 0.649981)`, support source `placed_top:4`, ratio `1.0`,
  clearance `0.018114m`;
- the same five occurrences each also have an `obstacle_face_extreme` root at
  approximately `(0.440973, 0.502, 0.649981)`, support source
  `placed_top:4`, ratio `0.896011`, clearance `0.075326m`.

Thus the online zero-normal-root result is proposal scheduling/recall under
the 1.8-second slice, not proof that no strict placement exists.

## Root binding, transition, and child availability

For the online rescue catalog:

- catalog roots: `5`;
- current state/pool/profile binding survivors: `5`;
- roots accepted by fresh `apply_root(... exact_revalidator=mask)`: `5`;
- each child default `1.8s` normal scan returned zero roots.

For the longer normal catalog:

- catalog roots: `11`;
- current binding survivors: `11`;
- fresh exact transition successes: `11`;
- the item-9 child produced ten strict normal roots with a 5-second child
  slice;
- each of the other ten edges produced one strict normal child root with the
  same slice.

There were no binding, exact-mask, transition, or edge-trace exceptions.
Therefore stale evidence, a forged receipt, and a true one-step future dead end
are excluded as explanations for this snapshot.

A separate generous beam run used the 11-root catalog and a 60-second beam
deadline. It returned a valid original depth-zero root after `60.045s`, choosing
pool `3`, item `11`, position approximately
`(0.383761, 0.502, 0.649981)`, source `plane_derived_edge`. This also exposes a
second performance bottleneck: `_evaluate_catalog` performs a child scan while
forming every candidate edge (`beam.py:291-378`) before the 6-item/2-root
admission cap is applied. Eleven roughly five-second child scans consume nearly
the entire generous budget.

## Comparison with the earlier nine-safe run

The earlier JSON completed nine safe placements, then failed with
`candidate_zero` on the next policy call. Its actions agree with the current
run for steps `0..3` and diverge at step `4`:

- current eight-safe trajectory: x approximately `0.383833`;
- earlier nine-safe trajectory: x approximately `0.441000`.

The earlier trajectory's successful step-8 action used pool `3`, orientation
`0`, position approximately `(0.4409732, 0.502, 0.6499832)`. That is the same
family as the longer scan's strict `obstacle_face_extreme` root at
`(0.4409732, 0.502, 0.6499810)`.

This comparison reinforces the recall diagnosis: a placement family that
succeeded physically is present in the failed snapshot, but it is reached too
late for the online normal slice. The subsequent `candidate_zero` belongs to a
different physical state after that ninth action, so it must not be treated as
the same failure. It does show that merely forcing one more action is unlikely
to be sufficient for sustained score improvement.

## Root-cause classification

| Hypothesis | Result | Evidence |
|---|---|---|
| True strict physical dead end | Rejected | 11 strict normal roots with longer scan |
| Stale/foreign/forged root | Rejected | 5/5 online and 11/11 generous roots match current binding |
| Exact transition failure | Rejected | every traced root passed fresh exact revalidation |
| Child state has no valid continuation | Rejected as a physical claim | every generous child scan found roots; 1.8s misses them |
| Beam exception | Rejected | no edge exception; beam exits immediately on deadline |
| Deadline inversion | Confirmed direct cause | scanner returns after beam's earlier deadline |
| Proposal recall latency | Confirmed contributing cause | 0 roots at 1.8s versus 11 at 5.0s |
| Pre-admission child-scan cost | Confirmed structural bottleneck | 60s beam mostly consumed by per-edge scans |

## Smallest high-leverage hypotheses for the next implementation task

1. **Guarantee a strict depth-zero incumbent before continuation search.**
   Reserve time for at least one fresh-bound/fresh-applied catalog root, or make
   the catalog stop no later than the B-search boundary. If rescue returns a
   strict root after continuation time is exhausted, select it with an exact
   one-ply rank rather than raising. This directly fixes the observed failure
   without introducing an unchecked fallback.

2. **Promote the late placed-top families into the fair coverage pass.**
   Source-balanced scheduling of `plane_derived_edge`,
   `obstacle_face_extreme`, and the equivalent free-rectangle boundary should
   surface a valid strict root inside the 1.8-second normal budget. This creates
   real time for planning and targets both observed late-stage failures.

3. **Cap/admit cheaply before scanning child catalogs.**
   Freshly apply depth-zero roots, preserve the best exact incumbent, compute
   cheap one-edge features, admit at most the configured item/root limits, then
   spend fair micro-budgets on child catalogs. Do not launch a full child scan
   for every root before admission.

Hypothesis 1 is the smallest safety-preserving fix and should be a RED
regression first. It may recover the ninth placement, but the prior trajectory's
next-step `candidate_zero` means hypotheses 2 and 3 are needed for meaningful
late-episode and score improvement.

## Reproduction artifacts

- Diagnostic script: `simulator/tests/diagnose_support_extreme_fusion_snapshot.py`
  - SHA-256: `61AF5DB1F33984790C956E1D0EE22BD819729FDCB821C34505DDE8F5C01A4B64`
- Complete structured result: `task-8-step8-diagnostic.json`
  - SHA-256: `C1E239CC70BF778D88B6F1C7365EFDCEFED2364178B690F4B5085301BA58A98E`

The JSON is the authoritative full root/edge trace; rounded values in this
report are for readability.
