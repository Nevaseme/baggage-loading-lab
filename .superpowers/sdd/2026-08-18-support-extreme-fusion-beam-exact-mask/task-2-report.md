# Task 2 report: fused strict-mask proposal families

## Scope

This task adds only the pure proposal union and its focused tests.  The
historical `agents.highscore` package, simulator core, strict validator, and
submission artifacts were not modified.

## Implemented contract

- `ProposalSource` names the eight deterministic families and exposes both
  enum-style and canonical string names.
- `iter_fused_records` emits a `PlacementProposal` plus a provenance sidecar
  containing the source-family union and support-level/source union.
- `iter_fused_proposals` and `generate_fused_proposals` expose raw proposals
  for later exact-mask integration; this module does not port approximate
  validation, scoring, or fallback coordinates.
- Every container is evaluated in local coordinates.  A future explicit
  `ContainerState.ordinal` is preferred, with the current `index` fixture as a
  compatibility fallback; no center offset is applied during generation.
- Normal support levels use the exact package profile: floor plus the 8 mm
  support inset, shelf/small-shelf plus the 22 mm drop gap, and aligned
  placed-item tops at exact contact.  Tilted placed boxes remain obstacles,
  never support levels.
- The normal union includes floor/wall extremes, support-bound lattices,
  obstacle faces, support-edge flush points, z-aware plane-derived edges, and
  the complete legacy-style coordinate cross.  Support lattices preserve the
  raw support rectangle intersected with a single support-Z-specific,
  plane-aware center region; flat walls use the 8 mm inclusion margin while
  sloped/cut planes are intersected at that Z.  Strict support-union
  validation owns overhang rejection.  Obstacle-face and legacy obstacle
  coordinates include the 18 mm path clearance, without applying it to
  container inclusion bounds.
- Free-rectangle boundaries are generated after subtracting blocker
  footprints from each support rectangle; the 11x11 dense support lattice is
  emitted only when `rescue=True` (or explicitly `rescue_only=True`).
- Deduplication uses `(pool_index, container ordinal, orientation, position
  rounded to 0.1 mm)`.  Repeated global item IDs at different pool positions
  therefore remain distinct, while duplicate coordinates union their
  provenance.
- Dimension-identical official orientations are collapsed (six for distinct
  dimensions, three for two-equal dimensions, one for cubes).  Work units are
  scheduled in deterministic container/inter-orientation/family round-robin
  quanta with raw-work and unique-output caps.  Absolute monotonic deadlines
  are checked throughout and already-built deterministic partial output is
  retained.
- Ordinary items expose ordinary containers first.  Priority-container
  proposals are available only through the explicit `deferred=True` tier so a
  catalog can request them after proving ordinary strict-zero.

## TDD evidence

RED before implementation:

```text
ImportError: No module named
'agents.support_extreme_fusion_beam_exact_mask.proposals'
```

Round-2 RED before implementation included:

```text
support Z levels used contact instead of profile inset/drop gap
support lattice shrank raw support bounds
obstacle faces lacked path clearance
orientation-identical proposals were duplicated
deferred/priority tier and raw-cap fairness were absent
z-aware plane-derived edges were absent for sloped/cut container planes
normal families used the 18 mm transport margin as a wall inclusion margin
```

GREEN after implementation:

```text
python -m unittest simulator.tests.test_support_extreme_fusion_proposals \
    simulator.tests.test_support_extreme_fusion_contract -v
Ran 34 tests ... OK
```

The focused suite covers empty-floor six-point families, 8 mm flat-wall
inclusion bounds, profile support-Z semantics, narrow/raw support clipping,
z-aware sloped-plane lattice intersections, obstacle-face path clearance,
shelf/small-shelf and placed tops, genuine rescue free-region subtraction,
0.1 mm and sub-0.1 mm provenance-aware deduplication, official orientation
deduplication, metadata-index/ordinal separation, multi-container
round-robin fairness, rescue-only dense sampling, deadline behavior, and
same-schedule deterministic output.  `compileall` for the standalone package
also passed.

Final fresh verification after plane-aware clipping:

```text
focused contract+proposal: 34 tests ... OK
exact-mask integration suite: 13 tests ... OK
full simulator discovery: 223 tests ... OK
compileall: OK
```

## Files

- `simulator/agents/support_extreme_fusion_beam_exact_mask/proposals.py`
- `simulator/tests/test_support_extreme_fusion_proposals.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-2-report.md`

The next task must connect these raw proposals to the strict exact mask; no
raw proposal from this task is safe to format as an action until that gate
accepts it.
