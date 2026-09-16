# Task 1: Continuous ingress skyline primitives

## Global constraints

- Do not modify `simulator/src` or simulator configuration.
- Standard library and NumPy only; no installation.
- Do not modify the public Agent API or any safety threshold.
- Do not initialize Git or commit.
- Use TDD: add tests, run and capture expected RED, then implement, run GREEN.
- Use `apply_patch` for edits.

## Files

- Create `simulator/agents/highscore/ingress.py`.
- Create `simulator/tests/test_highscore_ingress.py`.
- Write the report to `.superpowers/sdd/2026-08-13-monotone-ingress-packing/task-1-report.md`.

## Required interfaces

```python
@dataclass(frozen=True)
class XFrontier:
    min_x: float
    max_x: float
    front_y: float

def build_frontier(
    container: ContainerState,
    bottom_z: float,
    top_z: float,
    clearance: float,
    height_tolerance: float,
) -> tuple[XFrontier, ...]: ...

def candidate_x_intervals(
    frontier: Sequence[XFrontier],
    footprint_width: float,
    left: float,
    right: float,
) -> tuple[tuple[float, float], ...]: ...

def maximum_free_opening(
    blocked: Sequence[tuple[float, float]],
    left: float,
    right: float,
) -> float: ...
```

Use `AABB`, `ContainerState`, and `Rect` from `model.py` as needed.

## Required behaviour

`build_frontier`:

1. Derive usable left/right/back from container dimensions and thickness.
2. Split X at usable walls and every overlapping obstacle X face.
3. An obstacle participates when its Z span overlaps `[bottom_z, top_z]`, including tilted placed AABBs.
4. `front_y` is the minimum obstacle `minimum[1]` over the elementary X interval, or the usable back wall when empty.
5. Merge adjacent segments only when their `front_y` differs by at most `1e-6`.

`candidate_x_intervals`:

1. Propose wall-aligned, segment-boundary-aligned, and centred fits.
2. Reject footprints outside `[left, right]`.
3. Assign `back_limit_y` as the minimum `front_y` of every overlapped segment.
4. Deduplicate coordinates at `1e-6` and return deterministic X order.

`maximum_free_opening` clips blockers to `[left,right]`, merges overlapping or adjacent intervals, and returns the widest complement interval.

## Mandatory tests

```python
def test_maximum_free_opening_matches_saved_terminal_aperture(self):
    opening = maximum_free_opening(
        [(-0.513, 0.238), (0.529, 0.929)], -0.93, 0.93
    )
    self.assertAlmostEqual(opening, 0.417)
    self.assertLess(opening, 0.55 + 2.0 * 0.015)

def test_wide_footprint_uses_most_advanced_overlapping_frontier(self):
    frontier = (
        XFrontier(-0.9, -0.1, 0.45),
        XFrontier(-0.1, 0.9, 0.20),
    )
    fits = candidate_x_intervals(frontier, 0.8, -0.9, 0.9)
    spanning = min(fits, key=lambda fit: abs(fit[0]))
    self.assertAlmostEqual(spanning[1], 0.20)
```

Also test blocker merging/clipping, empty container frontier, Z-band separation, and a tilted placed AABB treated as an obstacle.

## Commands

RED and GREEN:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_ingress -v'
```

Regression:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_geometry simulator.tests.test_highscore_free_space -v'
```

## Report contract

The report must include status (`DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, or `BLOCKED`), changed files, RED evidence, GREEN evidence, regression evidence, self-review findings, and concerns. Return only status, one-line test summary, and concerns in the agent message.
