# Task 13: Initial Staged-Beam Diagnosis

## Decision

The current mode-B Beam should not be tuned in place. Its work ordering is
structurally inverted: it scans a child Catalog for every root it encounters
before applying the existing item/root admission caps. On the reconstructed
task001 initial state, the entire 5.30-second budget produces only depth-one
nodes and returns the same first root as one-ply. A fixed-work redesign should
rank all depth-zero roots cheaply, admit a bounded diverse set, then spend
child-scan work only on those admitted edges.

This diagnosis changes no production file and runs no PyBullet physics.

Artifacts:

- `simulator/tests/diagnose_support_extreme_fusion_initial_beam.py`
- `task-13-initial-beam-diagnostic.json`

## Reconstruction validity

The diagnostic reconstructs the empty task001 shelf container from
`sample_config.json` with the same `write_open_cut_corner_cup_obj` and affine
geometry used by the official Container implementation. The first ten stream
items are the official mode-B visible pool. No depth map is needed for the
empty container reconstruction.

The reconstructed one-ply action is:

```text
pool 2 / item 2 / container 0 / orientation 0
position (-0.2221941282, 0.0, 0.183)
source free_rectangle_boundary
```

It matches the recorded staged-beam and staged-one-ply physical first action
to float32 output precision. This is the cross-check that the read-only initial
state is the relevant physical decision state.

## Initial exact Catalog

The fresh staged scan took 0.192 seconds and returned the global cap of 64
strict roots:

| Pool position | Roots |
|---:|---:|
| 0–7 | 7 each |
| 8 | 5 |
| 9 | 3 |

All 64 roots use orientation 0. Source counts are 44 FREE boundary, 10
obstacle-face, and 10 plane-derived. All pool positions first receive a root
in `normal.free_probe`; the remaining roots arrive from FREE deepen and the
two structural probe stages. Compact normal and legacy families never enter
the capped Catalog.

This exposes a second fixed-work issue: raw-family round robin does not
produce orientation-diverse exact receipts once per-pool/global caps are
filled. The global cap is also reached mid-distribution, leaving later pool
positions with fewer roots. The previous E2 first action at
`(-0.177, 0.527, 0.997)` is absent from the current 64-root Catalog.

The diagnostic JSON contains every root's proposal, immediate feature vector,
lexicographic rank, and parent-Catalog root count—not only the top roots.

## Why item 2 at Y=0 wins

One-edge, no-child evaluation of all 64 roots takes 0.451 seconds. In this
route, `future_covered_items`, `future_covered_volume`, and
`root_robustness` are all zero because one-ply intentionally has no child
Catalog. The rank therefore behaves as follows:

1. `proven_count` is one for every root.
2. `proven_volume` selects the 0.073125 m³ item group at pool positions 2, 5,
   and 6 over smaller items.
3. Those three items have identical dimensions and the same seven parent
   roots, so their early rank terms and scarcity urgency (0.125) tie.
4. Stable ordering selects the lowest pool occurrence, pool 2.
5. For that item, the center-floor root wins on
   `compatible_support_capacity`: 0.553222 versus 0.552696 for the otherwise
   corresponding back-floor root at Y=0.477.

That support-capacity advantage is only 0.000526, but it occurs before
`largest_free_support` in the tuple. The back-floor root's largest free
support is 0.677465 versus 0.477020 at Y=0—a 0.200445 advantage that is never
consulted. Their volume, coverage, robustness, scarcity, ingress, CoG,
support margin, clearance margin, and stack terms otherwise tie.

The higher shelf root at Y=0.477/Z=1.007 has largest-free-support 1.0, but its
compatible-support capacity falls to 0.517365 and its CoG/low-stack values
fall sharply. It is therefore also dominated before the back-space benefit is
considered.

Globally back-most roots at Y=0.527 belong to smaller 0.052325 m³ items, so
they lose at the second lexicographic component, volume. A pure “back-most
first” replacement would therefore change both item and placement choice; the
evidence supports a within-quality backness/continuity tie-break, not an
unconditional Y sort.

## What the 5.30-second Beam actually proves

An isolated Beam trace with a literal 5.30-second search deadline reports:

| Metric | Result |
|---|---:|
| Child Catalog scans before admission | 41 |
| Sum of child-scan time | 5.051 s |
| Median child-scan time | 0.118 s |
| Constructed nodes | 41 |
| Node counts by proven depth | depth 1: 41 |
| Deepest `proven_count` | 1 |
| First incumbent comparison | 5.305 s |
| Beam return | 5.309 s |

The first 40 child scans return 64-root child Catalogs; the final partial scan
is deadline-limited. Across the evaluated nodes, future item coverage, future
volume coverage, robustness, ingress, support margin, and clearance margin
are each constant. Thus more than five seconds are spent recomputing saturated
features that do not discriminate the initial roots.

The admission caps (`6 items × 2 roots`) are applied only after
`_evaluate_catalog` returns. Since it returns at the deadline, no frontier is
expanded to depth two. Incumbent comparisons also begin only after the full
evaluation loop, at 5.305 seconds. The Beam is therefore an expensive
depth-one scorer in this state, not a lookahead search.

For comparison, the current cheap admission selects 12 roots. Exact child
Catalog scans for only those 12 take 1.754 seconds total (median 0.149 s).
Adding the initial Catalog (0.192 s) and all-root cheap evaluation (0.451 s)
gives about 2.40 seconds, leaving roughly 2.9 seconds of the 5.30-second
budget for rich reranking and deeper fixed-count work. These timings are a
counterfactual work estimate, not a claim that the unimplemented redesign
already improves physical placement.

Production Beam has slightly less than a full 5.30 seconds because its
absolute deadline begins before state and initial-Catalog construction. The
physical staged record confirms total policy time around 5.31 seconds.

## Physical sequence comparison

| Route | Safe placements | Local fill score | Policy p50 | First action |
|---|---:|---:|---:|---|
| E2 pre-staging | 11 | 10.0989 | 5.321 s | current pool 0, back/high shelf |
| staged Beam | 10 | 6.9883 | 5.313 s | pool 2, center floor |
| staged one-ply | 10 | 7.0235 | 1.254 s | pool 2, center floor |

Staged Beam and one-ply choose the same first root and stop after the same ten
safe placements. One-ply is over four times faster at p50, while its fill
score differs by only 0.0352. This rejects the hypothesis that the current
Beam's 5.3 seconds buy useful initial lookahead.

The older E2 sequence uses back/shelf positions much more aggressively,
places one additional item, and has about 44% more local fill score than
staged one-ply. E2 predates the staged Catalog and differs in more than one
factor, so it does not prove that backness alone causes the gain. It does show
that current candidate exposure and immediate rank remain plausible
confounders; this comparison cannot isolate their contribution from the other
E2-to-staged changes.

## Hypotheses

### Adopt

1. **Pre-admission child scans are the primary time sink.** Direct trace:
   5.051 of 5.309 seconds and depth remains one.
2. **Immediate rank systematically prefers the center root.** A 0.000526
   support-capacity difference lexicographically suppresses a 0.200445
   largest-free-support advantage.
3. **The capped Catalog lacks useful diversity.** All 64 roots are orientation
   0 and early structural families consume the cap; an E2 first-action root is
   absent.

### Reject for the present implementation

1. **Current Beam improves the task001 trajectory over one-ply.** It does not:
   same first root, same ten safe placements, essentially the same fill.
2. **More wall-clock budget alone will make the current Beam deep.** It first
   scales with every depth-zero root's child scan, so extra time primarily
   evaluates more siblings before admission.

### Not yet established

- A back-first rule alone improves Public score.
- Twelve is the optimal root budget at every depth.
- The initial-state timing distribution generalizes unchanged to late dense
  states or two-container cases.

## Separated follow-up experiments

The evidence supports three different hypotheses, but they must not be changed
in one package or physical comparison.

### E4: fixed-work ordering only — next experiment

Keep the current staged 64-root Catalog byte-for-byte, preserve the current
rank tuple and item/root admission caps, and change only when child scans run:

1. Apply every current exact root once without a child scan, compute the same
   immediate features, and establish a valid incumbent immediately.
2. Run the existing `6 items × 2 roots` admission before child scans.
3. Scan child Catalogs only for those admitted edges. Enforce a fixed global
   expansion count per depth plus the existing hard deadline, so one parent
   cannot enumerate all children before its siblings.
4. Preserve the existing ExactMask receipt and formatter boundaries.

This is the directly diagnosed factor. The measured initial work estimate is
0.192 s Catalog + 0.451 s cheap evaluation + 1.754 s for the existing 12
admitted child scans, leaving roughly 2.9 seconds for deeper work. Physical
results can then be attributed to work ordering/admission rather than a
simultaneous change in candidate quality.

### E5: Catalog diversity — separate experiment if E4 is insufficient

Hold E4 search and rank fixed, then test explicit receipt quotas across pool
occurrence, orientation, support level, and family. A specific variant may
reserve slots for compact/legacy candidates rather than allowing FREE deepen
to fill the global cap. This diagnosis proves current diversity collapse, but
does **not** prove that unexposed compact/legacy proposals yield useful strict
roots; E5 must measure that independently.

### E6: immediate rank precedence — separate experiment

Hold E4 search and the E5-selected Catalog fixed, then test one rank change at
a time. A first candidate is to prevent a sub-0.1% aggregate support-capacity
delta from dominating a 42% largest-contiguous-support gain, either through a
within-tier backness/face-continuity term or by moving largest support ahead of
aggregate capacity. The same fixed snapshots and physical seeds must be used
to attribute the result.

## Non-negotiable boundaries

- Preserve exact geometry, transport, support, protection, receipt, and final
  formatter checks in every experiment.
- Use the same task/seed and report safe placements, fill, first failure,
  policy timing, and action sequence for each single-factor comparison.
- Do not infer Public-score improvement from this initial analytical trace.

The next experiment is E4 only: move the existing admission boundary before
child scans while keeping the current root set and rank unchanged.
