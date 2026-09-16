# Task 18a — Layered Proxy Geometry and Immutable Transition

## Outcome

Implemented the bounded analytical geometry/state foundation for the planned
Layered MaxRects Regret selector.  This task does **not** route the proxy into
the production Agent and does not create a public action or a
`ValidatedRoot`.  It is ranking-only infrastructure for Task 18b.

## Production API

`layered_proxy.py` provides immutable, typed values for:

- protection tags with independent priority and soft constraints;
- occurrence-safe pool keys, including duplicate global item IDs;
- floor, shelf, placed-top, and proxy-top support patches;
- actual/static/proxy AABBs and immutable container/state snapshots;
- fixed node, fit-test, candidate, and rectangle quotas;
- proxy candidates, candidate batches, and bounded finite metrics;
- deterministic obstacle-coordinate maximal empty rectangles;
- candidate enumeration, analytical checking, fresh checked application, and
  deterministic state fingerprints.

The proxy reconstructs floor `+8 mm`, shelf `+22 mm`, and aligned top `+0 mm`
placement levels.  Tilted placed items remain obstacles but do not become
support patches.  Six official orientations are dimension-deduplicated.
Candidates use back, front, left, right, and flush/corner anchors.

Analytical acceptance checks container planes, 18 mm horizontal separation,
headroom, same-height support union, support ratio, the center core,
priority/soft protection columns, effective lift, and conservative Y-then-X
transport against actual and proxy obstacles.

`apply` is immutable and fail closed.  It reruns the analytical check against
the current state, requires exact agreement of every binding, geometry,
margin, source, and fingerprint field, and only then appends the freshly
recomputed proxy box/top patch.  A coordinated `dataclasses.replace` mutation
of position and AABB is therefore rejected.

## Metrics

All reported metrics are finite and clamped to `[0, 1]`:

- ingress access;
- largest free region and sliver area;
- low mass-weighted CoG goodness and low-stack goodness;
- compatible support capacity;
- protection-compatible support capacity.

Capacity uses rectangle union area rather than summing overlapping artificial
partitions.  A rectangle contributes only when at least one remaining
occurrence has a realizable orientation within its horizontal extent and
actual vertical headroom.  Protection capacity additionally requires an
unrestricted support or `tag.allows(remaining_tag)`.  Consequently empty
floor/shelf support counts as universally compatible, while a tagged top that
allows none of the remaining occurrences does not.

## TDD evidence

Initial RED evidence included a missing production module.  The first
implementation exposed and fixed three geometry/fixture issues: placed-top
transport lift, wall-inset anchors, and a back-placement continuity fixture.
Expanded regressions then covered all plan contracts.

Independent review found one Important metric defect: untagged support was
excluded from protection capacity while any tagged support was included
without considering remaining items.  Two focused tests reproduced the issue.
The corrected implementation uses remaining feasible orientations, headroom,
and protection tags.

Self-review added a coordinated candidate-forgery regression.  It was RED
before fresh application validation and GREEN after exact proxy-field matching
was introduced.

Fresh verification after all fixes:

```text
focused layered proxy: 14 tests, PASS, 0.108 s
related proxy/features/transition/mask: 63 tests, PASS, 0.439 s
full simulator suite: 368 tests, PASS, 13.201 s
independent Sol review: APPROVE, no Critical/Important finding
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -q
```

An earlier noncanonical run used `-s simulator/tests` without a top-level
package and produced one relative-import collection error.  It is excluded
from verification; the canonical fresh run above is the accepted result.

## Safety and scope audit

- No `ValidatedRoot`, receipt, or action dictionary is imported or minted.
- No `highscore`, EMS, MCTS, Beam, FixedQuota, Catalog, or ExactMask module is
  imported.
- The parent and sibling proxy states are not mutated.
- Duplicate item IDs are removed by occurrence key, not global ID.
- No production Agent, exact validator, planner route, physics runner,
  dependency, Git state, or historical artifact changed.

## Files changed

- `simulator/agents/support_extreme_fusion_beam_exact_mask/layered_proxy.py`
- `simulator/tests/test_support_extreme_fusion_layered_proxy.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-18a-layered-proxy-report.md`

## Next boundary

Task 18b may consume these proxy values for fixed-work regret rollout, but it
must return only ranked original depth-zero strict roots.  This task alone does
not establish any Public-score or physical-safety improvement.
