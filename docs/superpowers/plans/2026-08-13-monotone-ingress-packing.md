# Monotone Ingress Packing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace proxy corridor preservation with a continuous-X, back-to-front ingress skyline that improves safe placement count over the submitted public-score baseline of `12.622949582873819`.

**Architecture:** Add a pure interval-skyline module that derives base-layer frontiers from settled AABBs.  Feed its deepest valid positions into the existing conservative candidate validator, benchmark that one-factor change, and only then add joint future-ingress capacity to beam ranking.  Existing hard geometry remains the final authority.

**Tech Stack:** Python 3.12, standard library, NumPy, `unittest`, existing PyBullet simulator only for regression.

## Global Constraints

- Do not modify `simulator/src` or the official simulator configuration.
- Do not add or globally install dependencies.
- Keep the public `Agent` API and exact action dictionary unchanged.
- Never relax inclusion, official 15 mm Y-then-X transport clearance, support, protection, or settling safeguards.
- `policy` hard maximum remains below 6 seconds; `optimize` remains below 165 seconds locally.
- Treat `simulator/submissions/highscore_guarded_20260813.zip` as immutable baseline evidence.
- This workspace is not a Git repository: do not initialize Git or create commits; record task evidence in report files instead.
- Change one algorithmic factor per physical benchmark gate and revert a factor that fails its adoption criterion.

---

### Task 1: Continuous ingress skyline primitives

**Files:**
- Create: `simulator/agents/highscore/ingress.py`
- Create: `simulator/tests/test_highscore_ingress.py`

**Interfaces:**
- Consumes: `AABB`, `ContainerState`, and `Rect` from `model.py`.
- Produces:
  - `XFrontier(min_x: float, max_x: float, front_y: float)` frozen dataclass.
  - `build_frontier(container: ContainerState, bottom_z: float, top_z: float, clearance: float, height_tolerance: float) -> tuple[XFrontier, ...]`.
  - `candidate_x_intervals(frontier: Sequence[XFrontier], footprint_width: float, left: float, right: float) -> tuple[tuple[float, float], ...]` returning `(center_x, back_limit_y)`.
  - `maximum_free_opening(blocked: Sequence[tuple[float, float]], left: float, right: float) -> float`.

- [ ] **Step 1: Write failing interval tests**

Add tests that assert:

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

Also cover adjacent interval merging, empty containers, tilted AABBs as obstacles, and separate Z bands.

- [ ] **Step 2: Verify RED**

Run:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_ingress -v'
```

Expected: import failure for `simulator.agents.highscore.ingress`.

- [ ] **Step 3: Implement the minimal continuous model**

`build_frontier` must:

```text
1. derive usable left/right/back bounds from container dimensions and thickness;
2. split X only at usable walls and obstacle X faces;
3. for each elementary interval, select the minimum obstacle.minimum[Y]
   among AABBs overlapping both the interval and [bottom_z, top_z];
4. use the back wall when no obstacle overlaps;
5. merge adjacent segments only when front_y values differ by <= 1e-6.
```

`candidate_x_intervals` must propose wall-aligned and boundary-aligned centres,
deduplicate at 1e-6, and assign each placement the minimum `front_y` over every
segment overlapped by the footprint.

- [ ] **Step 4: Verify GREEN and regression scope**

Run the Task 1 test plus existing geometry/free-space tests.  Expected: all pass.

- [ ] **Step 5: Write evidence**

Write `docs/superpowers/plans/2026-08-13-monotone-ingress-task1-report.md` with
the RED command/output, GREEN command/output, files changed, and known limits.

---

### Task 2: Make monotone base-layer candidates primary

**Files:**
- Modify: `simulator/agents/highscore/settings.py`
- Modify: `simulator/agents/highscore/candidates.py`
- Modify: `simulator/tests/test_highscore_candidates.py`
- Test: `simulator/tests/test_highscore_ingress.py`

**Interfaces:**
- Consumes: Task 1 `build_frontier` and `candidate_x_intervals`.
- Produces: `CandidateGenerator._monotone_base_positions(...) -> list[tuple[float, float, float]]`.
- Setting: `use_monotone_ingress: bool = True` for controlled on/off benchmarks.

- [ ] **Step 1: Write failing generator tests**

Create a state with rear items whose X ranges form unequal continuous frontiers.
Assert that normal generation contains a base-layer candidate whose back face is
exactly `minimum_overlapped_frontier - path_clearance`, and contains no candidate
behind that limit.  Add a second test proving a 0.75 m footprint spanning the old
two-lane boundary uses both interval segments.

- [ ] **Step 2: Verify RED**

Run the two named tests.  Expected: no `_monotone_base_positions` method or the
old extreme-point position violates the monotone assertion.

- [ ] **Step 3: Implement primary monotone positions**

For each container/orientation/support level:

```text
frontier = build_frontier(container, bottom_z, top_z, clearance, tolerance)
for center_x, back_limit in candidate_x_intervals(...):
    center_y = back_limit - clearance - extra_margin - half_y
    validate position with the existing _validate_position
```

Support levels are floor, main shelf top, small-shelf top, and axis-aligned
settled-item tops.  Return validated monotone candidates before legacy extreme
points.  If at least one monotone candidate exists for an orientation/support
level, do not add legacy base-layer positions for that same level.  Preserve
legacy stack/recovery positions and use them only when monotone generation is
empty.

- [ ] **Step 4: Verify GREEN**

Run ingress, candidate, geometry, free-space, and planner unittests.  Expected:
all pass with no timing/API changes.

- [ ] **Step 5: Run the full unit suite**

Run `python3 -m unittest discover -s simulator/tests -p "test_*.py" -v` in the
existing WSL dependency environment.  Expected: all tests pass.

- [ ] **Step 6: Write evidence**

Write `docs/superpowers/plans/2026-08-13-monotone-ingress-task2-report.md` with
RED/GREEN evidence and the full suite summary.

---

### Task 3: One-factor physical benchmark gate

**Files:**
- Modify only if needed for metrics: `simulator/tests/run_physics_smoke.py`
- Create: `docs/superpowers/plans/2026-08-13-monotone-ingress-benchmark.md`

**Interfaces:**
- Consumes: `SearchSettings(use_monotone_ingress=True|False)`.
- Produces: deterministic JSON records for baseline and experiment.

- [ ] **Step 1: Run official smoke with the experiment enabled**

Run the official four-item runner smoke.  Expected: all four items and all three
safety statuses true, maximum policy below 6 seconds.

- [ ] **Step 2: Run task000 baseline and experiment**

Run 25 items, seed 42, no optimize, once with the flag false and once true.  Save
completed count, fill score, failure status, and maximum policy time.

- [ ] **Step 3: Run task001 baseline and experiment**

Run 30 items, seed 42, no optimize, once with the flag false and once true.  Save
the same metrics and failure snapshot.

- [ ] **Step 4: Apply the adoption gate**

Keep Task 2 only when:

```text
(task000_experiment >= task000_baseline and
 task001_experiment >= task001_baseline and
 at least one strict improvement and
 all experiment actions before the claimed count are safe and
 max_policy_seconds < 6.0)
```

If rejected, restore only Task 2 integration while retaining the independently
tested Task 1 primitives for the voxel/score alternative.  Record the exact
reason; do not tune another factor in this task.

- [ ] **Step 5: Write benchmark evidence**

Record both configurations, exact commands, results, adoption decision, public
baseline score, and ZIP immutability hash.

---

### Task 4: Replace dimensional future fit with joint ingress capacity

**Precondition:** Task 3 adopted the monotone generator.  If not, write a skipped
report and create a follow-up voxel-reachability plan instead of implementing
this task.

**Files:**
- Modify: `simulator/agents/highscore/ingress.py`
- Modify: `simulator/agents/highscore/model.py`
- Modify: `simulator/agents/highscore/planner.py`
- Modify: `simulator/agents/highscore/scoring.py`
- Modify: `simulator/tests/test_highscore_ingress.py`
- Modify: `simulator/tests/test_highscore_planner.py`

**Interfaces:**
- Produces `IngressCapacity(feasible_count: int, feasible_volume: float, minimum_slack: float)`.
- Produces `evaluate_ingress_capacity(state: PackingState, remaining: Sequence[tuple[int, ItemSpec]], clearance: float) -> IngressCapacity`.
- Adds `Candidate.future_ingress_count`, `future_ingress_volume`, and `future_ingress_slack`.

- [ ] **Step 1: Write failing joint-capacity tests**

Use two remaining items that independently fit by volume but require the same
0.58 m aperture.  Assert that closing the only aperture decreases feasible count
and volume to zero.  Assert that two disjoint apertures can serve two compatible
width classes.

- [ ] **Step 2: Verify RED**

Run ingress/planner tests.  Expected: missing `IngressCapacity` or old
`future_feasible_fraction` returns the incorrect independent-fit result.

- [ ] **Step 3: Implement joint capacity and lexicographic ranking**

Compute remaining-item capacity from the post-candidate frontier without
guessing unseen mode-B items.  Rank beam nodes by:

```python
(
    len(node.order) + node.future_ingress_count,
    node.placed_volume + node.future_ingress_volume,
    node.future_ingress_slack,
    -node.violations,
    node.secondary_score,
)
```

Keep the old secondary score as the final tie-breaker and preserve deadlines.

- [ ] **Step 4: Verify GREEN and full suite**

Run ingress/planner tests, then the entire unittest suite.  Expected: all pass.

- [ ] **Step 5: Repeat the Task 3 physical gate**

Compare Task 4 on/off with Task 2 fixed on.  Keep Task 4 only under the same
non-regression/strict-improvement/safety/time criterion.

- [ ] **Step 6: Write evidence**

Write `docs/superpowers/plans/2026-08-13-monotone-ingress-task4-report.md`.

---

### Task 5: Final verification and submission artifact

**Files:**
- Create: `docs/superpowers/plans/2026-08-13-monotone-ingress-final-report.md`
- Create conditionally: `simulator/submissions/highscore_monotone_20260813.zip`

**Interfaces:**
- Consumes: only factors adopted by Tasks 3 and 4.
- Produces: a validated ZIP with top-level `highscore/` and no test/cache/dependency files.

- [ ] **Step 1: Run final verification**

Run full unittest discovery, compileall, official runner smoke, task000, and
task001.  Record exact pass counts and timing.

- [ ] **Step 2: Perform independent code review**

Review spec compliance, deadline behaviour, safety invariants, array bounds,
container index handling, and fallback behaviour.  Resolve all Critical and
Important findings and re-run covering tests.

- [ ] **Step 3: Build the ZIP only on improvement**

Include exactly the production files under `highscore/`, including the new
`ingress.py`.  Exclude `__pycache__`, tests, dependencies, reports, and snapshots.

- [ ] **Step 4: Validate artifact contents and hash**

List all ZIP members, import the extracted agent in a temporary directory, and
record SHA-256 and byte size.

- [ ] **Step 5: Do not submit automatically without a passing local gate**

If no factor passes, keep the original guarded ZIP as the only candidate and
write the next voxel-reachability experiment plan.  If the new ZIP passes, it is
eligible for the next SIGNATE submission and must be compared against Public
score `12.622949582873819`.

