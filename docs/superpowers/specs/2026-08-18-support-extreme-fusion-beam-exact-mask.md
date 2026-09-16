# Support-Extreme Fusion Beam with Exact Mask

## Name and purpose

Production package: `support_extreme_fusion_beam_exact_mask`.

The algorithm restores the floor/support/extreme-point proposal recall and useful Mode-A plan handoff of the verified 29.7435 Public submission while retaining strict modular inclusion, collision, support, protection, Y-then-X transport, and depth validation. It removes MCTS and the unchecked deterministic last resort.

## Safety invariant

Only a `ValidatedRoot` bound to the current state fingerprint may be formatted as a public action. Raw proposals, analytical beam children, stale offline actions, and fixed fallback coordinates cannot be returned.

If the normal catalog is empty, the planner activates free-rectangle boundary and dense support-lattice proposal families without relaxing any hard validator rule. Candidate-zero is an explicit benchmark failure; it is never hidden by an unchecked action. A ZIP is not accepted unless required A/B/C physical cases have zero candidate-zero and zero unchecked-return events.

## Proposal union

For all distinct orientation dimensions, containers, and support levels, lazily union:

1. `floor_wall_extreme`: legal left/middle/right X crossed with back/front Y on the floor.
2. `reserved_support_lattice`: clipped 3x3 min/mid/max grid on floor, shelves, and aligned placed-item tops.
3. `obstacle_face_extreme`: flush positions around packed-item X faces and door-side Y faces.
4. `support_edge_flush`: centers flush to support, wall, shelf, and cutout edges.
5. `legacy_extreme_cross`: current modular wall/packed/shelf coordinate crosses, without first-nonempty early stop.
6. Zero-root rescue only: `free_rectangle_boundary` and round-robin 11x11 `dense_support_lattice`.

Deduplicate by pool position, container, orientation, and position rounded to 0.1 mm. Duplicate coordinates union their source provenance. Duplicate global item IDs at different pool positions remain distinct choices.

The 29.7435 agent's approximate inclusion, support, path, score, thresholds, and fallback are not ported.

## Fair bounded exact mask

Proposal work uses small deterministic round-robin quanta, not per-item wall-clock slices:

- Pass 1 gives every visible pool position a chance to find its first exact root.
- Pass 2 diversifies accepted roots by item, container, orientation, support, and source family.
- Pass 3 fills quality roots until the catalog cap or deadline.

Initial fixed limits:

- four proposals per quantum;
- eight roots per pool position;
- 64 roots globally;
- normal catalog to `start + 1.80 s`;
- deterministic search to `start + 5.30 s`;
- zero-root rescue to `start + 5.45 s`;
- at least 0.30 s output reserve.

Exceptions and deadlines never discard an already exact-validated incumbent.

## Exact validation

Every proposal is converted to an AABB and checked under the current strict profile with `allow_rule_violations=False`:

- official orientation dimensions;
- prioritized-container eligibility;
- container plane inclusion;
- target and swept-path clearance;
- support union ratio and core support;
- soft/priority protection;
- effective transport lift and Y-then-X path;
- depth-map cross-check.

The step-14 old last-resort proposal must remain rejected. A shadow constraint ablation shows that current pool items are blocked primarily by support and, for item 17, transport as well; therefore a strict root at that already-dead state is not assumed to exist. The proposal-union gate first performs an exhaustive bounded shadow scan: if a strict root exists it must be recovered, otherwise the successor must avoid reaching the equivalent state through future-support-aware earlier decisions.

## Mode routing

Mode is fixed from initial `optimize` and lookahead metadata and does not change when a B pool shrinks near stream end.

- A: full-list deterministic beam/LNS creates a complete order and complete action skeleton. Partial skeletons are discarded. Each planned action is strict-revalidated after settling; stale actions use one-item fusion repair.
- B: exact catalog covers all visible pool positions, then a depth-at-most-four deterministic beam optimizes visible placed count/volume and future exact coverage.
- C: no sequence beam and no arrival model. Choose one exact root by safety margin, support, low CoG, rigid back-first placement, protection, and general residual-aperture proxies.

## Deterministic beam objective

Lexicographically maximize:

1. visible items placed;
2. visible volume placed;
3. remaining items with an exact child;
4. minimum remaining exact-child count;
5. support margin;
6. absence of protection violations;
7. low normalized mass-weighted CoG;
8. largest residual supported rectangle;
9. low residual sliver area;
10. secondary proxy and stable action key.

Only the original exact root selected at the beam root can be returned. Analytical descendants are never exposed directly.

## Acceptance gates

- All focused, integration, regression, compile, and extracted-import tests pass.
- No earlier physical failure than the strongest control in any A/B/C gate.
- Candidate-zero and unchecked return are both zero in required physical cases.
- Every returned action has strict current-state revalidation evidence.
- Policy p99 is below 5.5 seconds and maximum below 6 seconds.
- Median completed safe steps do not regress in any mode and at least one mode improves materially.
- ZIP contains one top-level descriptive package and production Python files only.
