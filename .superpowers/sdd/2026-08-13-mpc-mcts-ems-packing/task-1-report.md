# Task 1 report — Pure EMS and support-layer state

## Status

Implemented the Task 1 EMS proxy state only.  No `simulator/src` files,
settings/public flags, dependencies, network calls, or Git operations changed.

## TDD record

### RED

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: failed in 1.8 s before production implementation with the
expected `ModuleNotFoundError: No module named 'agents.highscore.ems'` while
importing the new real-behavior EMS tests.

The test file covers split/prune and boundary/sub-mm collision behaviour;
floor/main-shelf/small-shelf/aligned-top support layers, protection, and tilted
obstacle-only geometry; six orientations, lane-spanning 0.75 m geometry,
ordering, protected supports, collision rejection, immutable transitions, and
quantized state keys.

### GREEN

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 7 tests passed in 1.8 s.

## Regression verification

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates -v
```

Output summary: 33 tests passed in 2.3 s.

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: 68 tests passed in 4.7 s.

## Self-review

- Public Task 1 dataclass/function signatures match the brief exactly.
- `build_proxy_state` mirrors CandidateGenerator's floor, shelf-drop, small
  shelf, and aligned placed-top support conventions; tilted placed boxes enter
  only the obstacle tuple.
- `propose_actions` checks every deadline-bounded proposal loop, considers the
  six existing official orientations, uses wall/corner/centre anchors and 1 mm
  canonical dedupe, and rejects incompatible supports, collisions, and the
  conservative front-to-target proxy path.
- `apply_action` is immutable, revalidates support dimensions/protection,
  uses expanded AABB collision checks with its supplied clearance, splits all
  coincident support layers, and adds the placed top layer.
- `state_key` quantizes only for lookup, preserving unrounded geometry for all
  feasibility checks.

## Changed files

- `simulator/agents/highscore/ems.py` (new)
- `simulator/tests/test_highscore_ems.py` (new)
- `.superpowers/sdd/2026-08-13-mpc-mcts-ems-packing/task-1-report.md` (new)

## Concerns

- Superseded by the review fix below: state-owned clearance is now applied
  consistently to proposals, paths, and transitions.

## Review fix — round 1/5

### Root cause and RED

Review found three state-model inconsistencies: `_proxy_path_clear` held X at
the target value and therefore omitted the second (X) transport leg; source
and action `AABB` NumPy arrays were retained by reference; and proposal-time
collision checks used a hard-coded zero clearance while transition checks used
the argument value.  The test extension reproduced these separately before
the production change:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 11 tests ran, with the expected three RED results: two
`TypeError` errors because `ProxyState` had no `clearance`/entrance-range state,
and an immutability assertion failure after mutation of an observed source
`AABB`.  The added X-leg fixture identifies a blocker that intersects only the
second sweep.  A 1 mm gap fixture identifies a proposal invalid under 2 mm
state clearance.  The test suite also now checks direct containment pruning,
order-independent split residuals, and absence of a tilted-item top layer.

### Implementation and GREEN

- `ProxyState` now owns `clearance` plus container entrance-X ranges.  Both
  proposal and transition checks use `state.clearance`; transitions use
  `max(state.clearance, clearance_argument)` and preserve that value.
- `_proxy_path_clear` now constructs clearance-expanded Y then X swept AABBs,
  clamping start X to the stored entrance interval (with a standalone-state
  EMS-range fallback).
- `build_proxy_state`, `ProxyAction`, and proxy successors copy every `AABB`
  minimum/maximum array before retaining it.

Focused GREEN command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 11 tests passed in 1.8 s.

Related regression command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates -v
```

Output summary: 37 tests passed in 2.4 s.

Full final verification command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: 72 tests passed in 4.7 s.

### Review-fix self-review and remaining concern

All new tests exercise real proxy geometry and mutate the original arrays only
after construction, so they fail if copying, clearance propagation, or either
transport leg is removed.  No public candidate-generator behaviour changed.
`ProxyState` does not retain all container ceiling/resting-surface dimensions,
so it cannot compute the exact `effective_transport_lift`; it performs a
zero-lift clearance-expanded conservative path check and the existing normal
candidate generator remains the exact physical authority.

## Review fix — round 2/5

### RED

The round-1 proxy retained only an entry X range and used the EMS front edge as
the transport door.  It therefore could not derive the CandidateGenerator's
lift or distinguish path-equivalent geometry with different transport context.
New real-geometry fixtures covered a blocker between the physical door and the
support EMS, a blocker touched only by the +0.08 m lifted path, an item whose
half-width makes the stored entry range impossible, construction of all
CandidateGenerator-equivalent transport metadata, and state-key separation for
clearance/transport variants.

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 16 tests ran; the five new tests failed as expected because
`ProxyState` lacked `door_planes`, resting/ceiling surfaces, and transport-key
representation.

### Implementation and GREEN

- `build_proxy_state` records per-container door Y plane, entry base bounds,
  floor/shelf resting surfaces, and the two exact CandidateGenerator ceiling
  surfaces.
- Metadata-bearing states call `effective_transport_lift` and
  `transport_path_clear` directly with the same door plane, clamped entry X,
  lift, and clearance semantics as CandidateGenerator.  An entry range that
  cannot admit the item's half-width is rejected; only completely metadata-free
  synthetic states retain the EMS-range fallback.
- `state_key` includes quantized clearance plus every transport metadata field;
  `apply_action` retains the metadata unchanged for successors.

Focused GREEN command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 16 tests passed in 0.03 s.

Related regression command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates -v
```

Output summary: 42 tests passed in 0.41 s.

Full final verification command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: 77 tests passed in 2.42 s.

### Self-review and concerns

The physical-metadata path delegates to the existing geometry functions rather
than maintaining a second sweep/lift implementation.  The fallback is limited
to completely metadata-free synthetic states, preserving the public proxy API
for unit tests without weakening production states.  No remaining Task 1
concern was identified; normal candidate validation remains an intentional
second safety gate.

## Reopened semantics fix — support levels vs path clearance

### RED

Task 2 exposed that `build_proxy_state(clearance=0.018)` used path clearance
as a vertical floor/shelf/top offset. This produced a 0.058 m floor instead of
CandidateGenerator's 0.048 m floor, outside its 12 mm support-height tolerance.
New tests require a clearance-18 mm proxy to retain CandidateGenerator-equivalent
floor, shelf, and placed-top Z values; propose the exact floor level; retain an
exact top contact after a repeated transition; reject a 10 mm horizontal obstacle
gap using 18 mm path clearance; and distinguish support parameters in state keys.

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 20 tests ran. The new support tests failed as expected: floor
and action tops contained clearance-derived vertical gaps and `ProxyState`
lacked support parameter metadata. The 10 mm clearance-path test already
passed, documenting the behaviour to retain.

### Implementation and regression diagnosis

- `build_proxy_state` now has compatible keyword-only `support_inset=0.008`
  and `shelf_drop_gap=_SHELF_DROP_GAP`. `clearance` remains collision/swept-path
  clearance only.
- Support Z values now match CandidateGenerator: floor is `floor_z + support_inset`;
  shelf is `shelf_top + shelf_drop_gap`; placed and generated item tops are exact
  box maxima. Collision tests keep vertical contact legal and apply clearance
  horizontally; transport sweeps retain geometry-owned expanded clearance.
- `ProxyState` and `state_key` preserve/quantize support parameters. Physical
  container bounds apply path clearance to wall feasibility without distorting
  support surfaces or their Z values.

The first full run found two newly present Task 2 catalog deadline test failures:
their wall-aligned proxy proposals had `validate_proposal(...) == None`, rather
than a deadline failure. State-owned container bounds restored wall clearance;
the catalog suite then passed without changing catalog code.

Focused GREEN command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 20 tests passed in 0.05 s.

Catalog regression command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_catalog -v
```

Output summary: 28 tests passed in 0.23 s.

Related regression command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates -v
```

Output summary: 46 tests passed in 0.44 s.

Full final verification command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: 89 tests passed in 2.63 s.

### Self-review and concerns

Support Z is no longer derived from clearance. Container wall clearance,
obstacle collision, and swept-path clearance remain action filters, while
support surfaces retain exact vertical contacts. No remaining concern was
identified.

## Review fix — round 4/5

### RED

`apply_action` correctly computed `effective_clearance = max(state.clearance,
clearance_argument)`, but the container-wall helper silently read
`state.clearance`. A direct fixture used a zero-clearance state and a
wall-touching action that passed every other support/collision/path check. It
required `apply_action(..., 0.0)` to accept and `apply_action(..., 0.018)` to
reject.

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems.ProxyActionTests.test_apply_action_uses_stronger_argument_clearance_for_container_walls -v
```

Output summary: 1 test failed as expected because both calls returned a
successor; the stronger transition clearance did not reach the wall check.

### Implementation and GREEN

`_inside_container_clearance` now takes an explicit `clearance`. Proposal
generation passes `state.clearance`; transition validation passes the computed
`effective_clearance`. There are no implicit helper reads of state clearance.

Focused regression command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 21 tests passed in 0.03 s.

Related regression command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates simulator.tests.test_highscore_catalog -v
```

Output summary: 55 tests passed in 0.53 s.

Full final verification command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: 90 tests passed in 2.59 s.

### Self-review and concerns

All wall-clearance callers now state which clearance contract they use, and the
transition successor cannot claim a stronger clearance than was validated. No
remaining concern was identified.

## Final review fix — round 5/5

### RED

`ProxyState.boxes` held local-coordinate boxes from every container without a
container identity. Two-container fixtures placed identical-local-coordinate
geometry in container 0 and required an action plus swept path in container 1
to remain feasible; tagging the same blocker as container 1 had to reject both.

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems.ProxyActionTests.test_boxes_only_block_actions_in_their_own_container simulator.tests.test_highscore_ems.ProxyActionTests.test_transport_path_ignores_other_container_blocker_but_rejects_same_container -v
```

Output summary: 2 tests errored as expected because `ProxyState` had no
`box_containers` metadata.

### Implementation and GREEN

- The public `boxes` tuple is unchanged. Parallel `box_containers` metadata is
  populated for every static/placed box built from production state.
- Proposal collision, transition collision, and transport-path checks select
  boxes tagged for the action/EMS container. Backward-compatible synthetic
  states whose tags are absent or incomplete treat every box as relevant.
- Successors deep-copy boxes as before and append the action's container tag.
  `state_key` pairs each quantized box geometry with its container tag; legacy
  untagged boxes receive a deterministic sentinel.

Focused GREEN command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 23 tests passed in 0.05 s.

Task 1 related command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates -v
```

Output summary: 49 tests passed in 0.49 s.

Broader related/full commands:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates simulator.tests.test_highscore_catalog -v
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: the broader related run executed 59 tests and the full run 94;
each reported the same 3 errors in concurrently added Task 2 tests outside the
permitted EMS files: two invalid-orientation cases raise from
`CandidateGenerator.validate_proposal`, and one catalog fake-clock fixture
exhausts its `perf_counter` side effect. All Task 1 EMS, geometry, and existing
candidate tests passed in both runs.

### Final self-review and concerns

Every use of proxy obstacles in collision or path feasibility now passes
through `_container_boxes`. Production builders emit one tag per box;
successors preserve that invariant and immutable array copies. Legacy states
retain their conservative all-box behaviour. Container tags participate in the
transposition key paired with geometry, preventing cross-container aliasing.

Remaining concern is limited to the 3 external Task 2 test errors described
above. They require changes in `catalog.py`/`candidates.py`, which were expressly
outside this round's allowed files; no EMS failure remains.

## Post-review completion correction A

### Root cause and RED

Two breadth gaps remained. `_split_ems` made disjoint front/back strips only
within the removed footprint's X span, rather than the four overlapping maximal
rectangles. Separately, `build_proxy_state` added placed boxes and aligned top
supports without removing their footprint from the floor, shelf, or placed-top
support layer on which they rested.

Command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems.EMSSplitTests.test_split_returns_nondominated_maximal_spaces_covering_free_area simulator.tests.test_highscore_ems.ProxySupportTests.test_floor_placed_footprint_is_removed_only_from_its_base_layer simulator.tests.test_highscore_ems.ProxySupportTests.test_shelf_placed_footprint_is_removed_only_from_shelf_layer simulator.tests.test_highscore_ems.ProxySupportTests.test_tilted_item_removes_its_base_footprint_without_adding_top_support -v
```

Output summary: all 4 tests failed as expected. The split lacked full-width
front/back EMS, and floor/shelf/tilted fixtures retained occupied base support.

### Implementation

- Center removal now yields maximal left/right full-height and front/back
  full-width rectangles. Individual residuals exclude the footprint; EMS
  overlap at free corner regions is intentional. The test independently checks
  union area equals the literal 3.0 m² free area and pruning preserves all four
  nondominated rectangles.
- For each container, placed items are processed bottom-up. Their footprint
  sequentially splits only support spaces matching CandidateGenerator's floor
  tolerance, shelf drop-gap/tolerance, or a previously placed top. Protection,
  container, layer Z, and max height are retained through `_split_ems`.
- Axis-aligned placed items add their top support after base subtraction.
  Tilted items subtract the matching occupied base but remain obstacle-only.
  Static shelf obstacles are not projected onto unrelated layers.

During self-review, a nearby floating box exposed that the generic placed-top
matcher could accidentally select the known floor layer even when the box was
outside floor tolerance. This additional RED isolated the boundary:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems.ProxySupportTests.test_nearby_but_unsupported_height_does_not_subtract_floor_layer -v
```

Output summary: 1 test failed as expected. Floor and shelf layers now use only
their dedicated support semantics; the generic tolerance applies only to
non-floor/non-shelf placed-top layers.

### GREEN and regression verification

Focused command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems -v
```

Output summary: 27 tests passed in 0.04 s.

Related command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest simulator.tests.test_highscore_ems simulator.tests.test_highscore_geometry simulator.tests.test_highscore_candidates simulator.tests.test_highscore_catalog -v
```

Output summary: 64 tests passed in 0.47 s.

Full command:

```powershell
& 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Output summary: 106 tests passed in 3.02 s.

### Final self-review and concerns

Every residual EMS excludes every footprint already removed from that layer;
sequential splitting retains maximal edge opportunities and nondominated
pruning. Floor, shelf, placed-top, unrelated-height, tilted, multi-container,
clearance, immutability, and key invariants all have focused coverage. The
previous external Task 2 errors are now resolved in the workspace. No remaining
Task 1 concern was identified.
