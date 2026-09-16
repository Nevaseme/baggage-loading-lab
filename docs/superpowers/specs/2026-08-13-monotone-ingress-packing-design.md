# Monotone Ingress Packing Design

## Objective

Replace the current proxy-based corridor preservation with a packing state that
directly represents the official door-to-target insertion order.  The first
deliverable must improve the local task000/task001 safe-placement baselines
without relaxing inclusion, 15 mm transport clearance, support, protection, or
settling safeguards.  The submitted public score `12.622949582873819` is the
external baseline.

## Diagnosis

The current candidate generator can place safe items near the door while leaving
unreachable voids behind them.  Its two sample lanes only compare two frontier
points and do not represent the continuous width required by differently sized
items.  At the saved task001 step-24 failure, the largest remaining continuous
door opening was 0.417 m while the remaining 0.55 m-wide items required 0.580 m
including two 15 mm margins.  No candidate passed the official transport path,
so the arrangement—not the last-resort action—was already terminal.

## Chosen Architecture

Use a hybrid monotone-ingress planner:

1. Keep the existing exact/conservative safety kernel for inclusion, collision,
   support, protection, Y-then-X transport, and depth-map cross-checking.
2. Replace floor and shelf-base extreme-point placement with a continuous
   interval skyline that advances from the back wall toward the door.
3. Keep existing stack-top candidates initially, but rank every action by the
   remaining door-connected capacity for visible or known future item classes.
4. Retain the existing generator as a zero-candidate fallback during the first
   experiment.  It may not outrank monotone candidates when both exist.
5. If the interval model improves both sample tasks, make it the primary state
   representation and add a conservative voxel reverse-reachability recovery
   only for irregular shelf/cutout regions.

This is deliberately not a fixed-lane method.  X is partitioned only at actual
container, shelf, and settled-item boundaries, so wide items spanning former
lane boundaries are represented correctly.

## Continuous Interval Skyline

For each container and support level `z`, form sorted X breakpoints from:

- usable left and right walls;
- shelf and cutout boundaries;
- minimum and maximum X faces of settled AABBs intersecting that level.

For each elementary interval `I`, store a front coordinate `F_z(I)`.  The
occupied/reserved region is conservatively treated as extending from
`F_z(I)` toward the back wall.  Empty intervals start at the back-wall frontier.

For an oriented footprint with X interval `Q`, its back face is placed at:

```text
candidate_back_y = min(F_z(I) for I intersecting Q) - 0.015 - extra_margin
```

and its front face is derived from its Y dimension.  This rule places the new
item immediately in front of the most advanced intersected skyline segment.  It
cannot create a new item behind a previously placed item in the same X/Z swept
band.  Candidate X positions come from wall alignment, skyline breakpoints,
support-rectangle edges, and centred fits within maximal adjacent intervals.

The skyline proposes positions only.  Every proposal still passes the existing
hard geometry and physics-proxy validators before it becomes a `Candidate`.

## Future Ingress Capacity

For every candidate, simulate only its AABB insertion into the interval state.
For each remaining item and orientation, calculate whether an X interval of
width `oriented_x + 0.030` remains door-connected at the required swept Z band
and whether the monotone skyline has sufficient Y depth for its footprint.

Define the lexicographic candidate key as:

```text
(
    count of remaining items with at least one ingress-capable orientation,
    total volume of those items,
    minimum normalized opening slack across required width classes,
    -protection violations,
    existing secondary score,
)
```

This replaces the current volume-only `future_feasible_fraction` for nodes that
have an interval state.  It does not predict unseen items in mode B.  Mode C
uses conservative width classes derived from the current item and the remaining
container aperture rather than fabricating an arrival distribution.

## Mode Behaviour

### Mode A

`optimize` builds a complete monotone skeleton using the full known item list.
The returned order is accepted only when all items have a validated skeleton,
preserving the existing complete-skeleton guard.  During `policy`, the next
skeleton action is treated as a hint and is revalidated against settled state;
failure to revalidate triggers online replanning.

### Mode B

The planner evaluates only visible pool items.  Beam leaves use joint ingress
capacity of the remaining visible pool, not independent dimensional fit.
Candidate generation remains deterministic and deadline-aware.

### Mode C

The specified item is placed at the deepest monotone skyline location that
passes hard validation.  Priority and soft protection columns remain hard
constraints.

## Conservative Voxel Recovery

Voxel reverse reachability is a second-stage recovery, not part of the first
experiment.  A 30 mm grid marks walls, shelves, cutouts, and settled AABBs.
For an item orientation, obstacles are dilated by item half-extents plus 15 mm.
NumPy prefix operations identify cells with a clear reverse X segment followed
by a clear reverse Y segment to the door.  Continuous hard validation refines
and verifies cells before use.

This recovery is introduced only if the interval skyline improves normal cases
but misses geometrically valid irregular placements.  It must not replace exact
continuous validation.

## Failure Handling

- A monotone proposal that fails any hard check is discarded.
- A stale offline hint is discarded and replanned; it is never returned
  directly.
- Deadline expiry returns the best already validated candidate.
- The old deterministic last resort remains only as an API-format guard.  Test
  success is measured before that path is reached.
- No new dependency, global installation, network call, or simulator change is
  permitted.

## Test Strategy

### Unit tests

- continuous X partitioning at item, wall, shelf, and cutout boundaries;
- skyline update after narrow, wide, and boundary-spanning items;
- 0.417 m opening rejects a 0.580 m required width;
- back-to-front placement invariant over overlapping X intervals;
- future ingress count requires a shared feasible aperture, not independent
  volume fit;
- shelf and floor skylines remain separate;
- offline hints are revalidated before use;
- deadline and public API contract remain unchanged.

### Physical regression

- all existing unittests and official four-item smoke must pass;
- task000 must exceed 17 safe placements without optimization;
- task001 must exceed the deterministic 20-safe-placement baseline and must not
  regress below the observed 24-place diagnostic rescue run;
- no accepted run may fail `is_included`, `is_valid`, or `is_placed_safe` before
  its claimed placement count;
- `policy` must remain below 6 seconds, with p99 targeted below 2 seconds.

### Adoption gates

1. First experiment changes only primary base-layer candidate coordinates to the
   interval skyline.  Safety checks, beam settings, item ranking, and score
   weights remain fixed.
2. Keep the change only if task000 and task001 both improve or one improves while
   the other is unchanged, with no safety/API/time regression.
3. Then replace the future-feasibility proxy with ingress capacity and repeat.
4. Add voxel recovery only after both interval stages pass.
5. Build and submit a new ZIP only after the complete local verification gate.

## Alternatives Rejected for the First Iteration

- Weight-only tuning cannot represent a missing continuous-aperture state.
- Fixed lanes fail when items span lane boundaries.
- Full 3D voxel replacement adds discretization and runtime risk before the
  simpler monotone invariant is tested.
- CVaR arrival rollouts assume a future distribution unavailable in mode C and
  are premature before deterministic ingress is modelled correctly.
- External solvers and physics rollouts violate the dependency/time plan.

## External Review Inputs

Two clean-context GPT reviews independently favoured monotone shelf/skyline or
reverse-reachability representations over the current extreme-point proxy.
Wolfram references identify Shelf, Skyline, Guillotine, and MaxRects as standard
2D rectangle-packing families; the official insertion order makes a monotone
Shelf/Skyline extension the relevant family here.  Wolfram arithmetic confirmed
the saved failure aperture calculation above.  Hugging Face paper and Space
search endpoints were unavailable (`Tool not found`), so no unverified result
from that plugin is used in the design.
