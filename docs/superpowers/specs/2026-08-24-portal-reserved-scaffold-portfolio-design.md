# Portal-Reserved Scaffold Portfolio Design

> **Status note — 2026-09-08:** Historical candidate design, with only the calibrated authorizer/historical shield cross accepted at the last development checkpoint. Scaffold/portal planning remains unverified. Interpret architectural and causal claims below as the hypotheses of this design unless supported by matched experiments; in particular, the earlier entrance-blocking placement has not been isolated as a causal factor by a completed portal-on/off comparison. Current operating policy is in root `AGENTS.md`, with submission gates in `docs/evaluation-contract.md`.

## Objective

Build a submission algorithm that can plausibly exceed Public 60 by improving
completed placement count and final layout quality together.  The design must
cover official modes A, B, and C, keep every online call below the project
timing gates, and never return an action that bypasses the final current-state
authorization path.

## Controlling evidence

The four externally returned `submit/**/result-log.txt` files all ended with
`is_valid=false` and `is_placed_safe=false`.  Because transport validation runs
before physical placement, that signature is consistent with an ingress-path
failure where settling was never attempted.  Every submitted implementation
contains an unchecked final fallback, including the newest
`ingress_preserving_column_scaffold`.

The Public-29.74350010538 historical agent is still the strongest observed
layout generator.  Its feedback has `fill_score=33.6777`, `cog_score=32.4836`,
`stability_score=38.0491`, `placement_score=20.2`, `soft_item_score=14.85`, and
`num_placed_items=0.458286`.  On the matched local task000 A control it produced
25 safe placements and `fill_score=33.9439` before an unchecked ingress-invalid
fallback.  The strongest current strict A combination produced only 15 safe
placements and `fill_score=13.1177`.  This rules out safety filtering, deeper
proxy search, or historical order alone as sufficient explanations.

The useful historical signal is a coherent full-stream virtual plan that builds
low, repeatable columns.  The observed terminal defect is loss of future ingress:
an entrance-side floor item placed earlier blocks a later planned sweep.  The
successor therefore represents support and ingress dependencies explicitly
instead of replacing the successful scaffold with a generic free-space rank.

## Considered architectures

1. `portal_reserved_scaffold_dag` (selected primary): column slots with support
   dependencies and back-to-front portal precedence.  It has the strongest
   empirical starting point and enough historical runtime headroom.
2. `portal_profile_reverse_reachability` (selected independent spike):
   door-connected free-space profiles at multiple support heights.  It directly
   tests whether missing interior ingress roots can be recovered without a full
   voxel planner.
3. `attribute_capacity_flow` (deferred): item-to-slot flow with conflict and
   protection edges.  It is promising for B and two-container cases, but cannot
   repair missing candidate recall by itself.
4. `sparse_voxel_contact_mpc` (deferred): configuration-space occupancy and
   reverse reachability.  It has high recall potential but is too risky for the
   six-second internal policy ceiling until the cheaper portal spike succeeds.

## Primary architecture: `portal_reserved_scaffold_dag`

### Shared state

Each container is represented by a small set of scaffold slots.  A slot records
its support rectangle and height, admissible orientation footprint, cumulative
load, remaining headroom, protection tags, and an ingress portal.  Directed
support edges require lower slots to be placed first.  Directed portal edges
require deeper or wider sweeps to occur before placements that would obstruct
them.

The scaffold is a proposal and planning structure only.  It never authorizes a
public action.

### Mode A

The offline phase starts from the historical virtual low-column plan because it
is the only observed plan with adequate trajectory quality.  It converts planned
placements into slot intents and constructs a future-sweep set for every
remaining item.  Beam repair may change container, orientation, coordinate, or
order when a placement would block a scarce future portal.  A partial plan is
retained; unresolved items are appended with a stable heavy-rigid-first order
rather than causing the entire plan to be discarded.

Online execution rebinds the next intent to settled geometry.  If the intended
target is rejected, repair candidates are ranked by minimum deviation from the
remaining support/portal DAG, not by the existing generic MaxRects proxy.

### Mode B

The visible pool is assigned to current scaffold slots with a shallow rolling
beam.  The rank is lexicographic: authorized placed count, placed volume,
protection feasibility, low mass-weighted CoG, remaining wide/deep portal
capacity, then deterministic tie breakers.  Candidate count and depth are
deadline-adaptive; completed children are retained when the deadline expires.

### Mode C

With one visible item, the policy chooses the deepest low authorized slot that
leaves the largest door-connected portal profile.  It makes no assumptions
about unseen item distribution.  Stable full-support floor or same-footprint
column placements are preferred over fragmented bridges.

### Protection and stability

Priority-container routing is a hard eligibility rule when such a container is
available.  Placing ordinary rigid cargo on soft or priority cargo is a scoring
violation, not a universal geometry rejection; the search reserves compatible
top slots and only permits a violation when no non-violating authorized action
exists.  Heavy items are charged by normalized center height and supporter load.
Support ratio, center-in-support, stack height, displacement, and rotation are
local proxies unless the official evaluator reports the component.

## Independent spike: `portal_profile_reverse_reachability`

For each orientation and support-height band, obstacles are dilated by the item
half extents plus the official 15 mm path margin.  Free X intervals are swept
from the door toward the back to form multiple connected portal components.
Candidate coordinates come from component extrema, widest interior intervals,
and intersections with support boundaries.  Every coordinate is passed to the
same final authorizer.

The first spike is snapshot-only and read-only with respect to physical state.
It is accepted only if it finds a newly authorized root on a saved terminal
snapshot within 1.5 seconds.  If it fails, the voxel/contact architecture is not
implemented yet.

## Authoritative action boundary

Every proposal route, including planned targets, repair, dense search, portal
search, and emergency handling, must use this single return path:

1. bind the exact visible item occurrence and container ordinal;
2. cast the target to the serialized float32 coordinate;
3. check container inclusion using current planes and the official margin;
4. check target overlap against shelves and settled items;
5. check the official Y-then-X swept path with 15 mm clearance;
6. apply a calibrated support-risk rule that accepts the 25 historically safe
   matched actions and rejects the known step-25 failure;
7. bind a current-state fingerprint and repeat all mutable checks immediately
   before formatting the public action.

There is no unchecked deterministic fallback.  Candidate-zero is a diagnostic
failure and is not accepted as a submission result.

## Diagnostic and evidence design

Historical task000 control must be rerun while saving every pre-action snapshot,
action, route, elapsed time, and official step predicates.  The current masks are
replayed after the episode to avoid mutating physics during diagnosis.  A
predicate-by-step recall table must show which hard predicate accepts each of the
25 known-safe actions and rejects the failed action.

Evidence has two grains:

- episode facts: immutable artifact/config/runner hashes, task, mode, seed,
  requested items, attempts, safe placements, fill, terminal predicate, timing,
  action hash, and raw path;
- paired aggregates: matched cases, one-factor delta, safe-placement and fill
  deltas, worst safety regression, timing sample size, and gate outcome.

Public aggregate scores, external result-log scene averages, and single local
episodes remain separate.  Missing official component weights and denominators
must not be inferred.

## Falsification and promotion gates

The calibrated shield is rejected if it rejects more than one of the 25 known-
safe historical actions or accepts the known failed action.  The primary A
cross must reproduce at least 24 safe placements and fill 32 on the matched
control before portal reservation is added.  Portal reservation must then reach
at least 30 safe placements or demonstrate a material paired improvement without
an earlier safety failure.

Across generated and sample A/B/C cases, a candidate must have zero malformed,
unchecked, ingress-invalid, or settle-unsafe returned actions; no earlier failure
than the strongest matched control; nonnegative median completion delta in every
mode; and a material gain in at least one mode.  Policy timing must be measured
with at least 10 warmups and 200 calls on a fixed host, with p99 below 5.5 seconds,
maximum below 6 seconds, and the official eight-second lifecycle enforced.
Optimization must remain below 180 seconds.

Promotion requires unit, integration, regression, official-lifecycle, physics,
and extracted-ZIP import tests.  The archive name must describe the technique and
must not contain an unverified score.
