# Task 2: Make monotone base-layer candidates primary

## Context

Task 1 added and reviewed these interfaces in `agents.highscore.ingress`:

```python
build_frontier(container, bottom_z, top_z, clearance, height_tolerance)
candidate_x_intervals(frontier, footprint_width, left, right)
```

This task integrates them into the production candidate generator as one
controlled factor.  Existing hard validation remains authoritative.

## Global constraints

- Do not modify `simulator/src`, simulator configuration, public Agent API, or safety thresholds.
- Standard library and NumPy only; no install/network/Git.
- Use `apply_patch` for edits.
- TDD: add focused failing tests and capture RED before production changes.
- The legacy generator must remain reachable with one immutable settings flag for A/B comparison.
- Do not alter planner beam width/depth, item ranking, scoring weights, or deadline limits.

## Files

- Modify `simulator/agents/highscore/settings.py`.
- Modify `simulator/agents/highscore/candidates.py`.
- Modify `simulator/tests/test_highscore_candidates.py`.
- Read/use `simulator/agents/highscore/ingress.py` without changing it unless an integration-blocking bug is proven by a new failing ingress test.
- Report: `.superpowers/sdd/2026-08-13-monotone-ingress-packing/task-2-report.md`.

## Interface

Add exactly:

```python
# SearchSettings field
use_monotone_ingress: bool = True

# CandidateGenerator method
def _monotone_base_positions(
    self,
    container: ContainerState,
    half: np.ndarray,
    bottom_z: float,
    extra_margin: float,
) -> list[tuple[float, float, float]]: ...
```

The method returns centre `(x,y,z)` positions only.  `_generate_for_container`
passes each through the existing `_validate_position` unchanged.

## Required behaviour

1. For each orientation, identify base support bottoms already considered by the generator:
   - floor: `container.thickness + container.buffer - inclusion_margin inset` semantics matching current `z_values`;
   - main shelf top plus current `shelf_drop_gap` when `container.shelf`;
   - small-shelf top using the existing static obstacle geometry;
   - do not replace placed-item-top stack candidates in this task.
2. For each base bottom, compute candidate `top_z = bottom_z + 2*half[2]` and call `build_frontier` for the swept Z band.
3. Use the same wall bounds as current `_generate_for_container`:
   `left/right` include container thickness and `max(-inclusion_margin, path_clearance)`.
4. For every `(center_x, back_limit_y)`, propose:

```python
center_y = back_limit_y - self.settings.path_clearance - extra_margin - half[1]
center_z = bottom_z + half[2]
```

5. Reject proposed centres whose footprint exceeds current `front/back/left/right` bounds.
6. Deterministically deduplicate at 1e-6 and order deepest Y first, then low Z,
   then centre-nearest X.
7. With `use_monotone_ingress=True`, validate monotone base positions before
   the legacy Cartesian extreme points.  For a base support level that yields
   at least one validated monotone candidate in an orientation, do not add
   legacy base-layer positions for that same orientation/support level.
8. Legacy placed-item-top stack positions remain available.  If all monotone
   positions fail hard validation, normal local-grid and recovery fallback
   behaviour remains available.
9. With `use_monotone_ingress=False`, candidate output/order must follow the
   pre-task implementation; the new helper must not affect generation.
10. Do not change `_validate_position`, `transport_path_clear`, depth-map checks,
    support thresholds, or protection handling.

## Mandatory tests

Add tests with real `CandidateGenerator` and container/item fixtures:

1. `test_monotone_floor_candidate_advances_in_front_of_overlapped_skyline`:
   two rear floor AABBs have unequal X frontiers; a spanning footprint's back
   face equals the minimum overlapped frontier minus `path_clearance` (within
   1e-6) and no monotone floor candidate is behind that limit.
2. `test_monotone_wide_item_spans_old_lane_boundary`:
   a 0.75 m footprint crossing X=0 uses both skyline segments, proving no fixed
   two-lane assumption.
3. `test_disabling_monotone_ingress_preserves_legacy_floor_candidates`:
   `SearchSettings(use_monotone_ingress=False)` produces the legacy back-floor
   coordinate already asserted by existing tests.
4. `test_monotone_candidates_still_pass_all_hard_checks`:
   generated candidates satisfy inclusion, support, and production transport
   checks; test real functions rather than mocks.
5. Existing shelf, protection, grid recovery, and candidate-count cap tests remain green.

## Commands

Focused RED/GREEN:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_candidates -v'
```

Full unit suite after GREEN:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest discover -s simulator/tests -p "test_*.py" -v'
```

## Report contract

Write status, exact changed files, RED evidence, GREEN evidence, full-suite
evidence, candidate-count/runtime observations, self-review, and concerns to the
report path.  Return only status, one-line tests, and concerns in the message.
