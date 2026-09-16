# Dead-end Replay and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make candidate-zero states reproducible and add a bounded support-grid recovery search that finds safe placements missed by the fast extreme-point search.

**Architecture:** Diagnostic snapshot code lives under `simulator/tests` and never enters the submission import graph. A new `free_space.py` module proposes centres from free support-grid windows; `CandidateGenerator` invokes it only after all existing extreme-point stages return zero and validates every proposal with the existing hard geometry checks.

**Tech Stack:** Python 3.12, standard library, NumPy, `unittest`; PyBullet only in the existing manual integration scripts.

## Global Constraints

- Do not change simulator production files under `simulator/src`.
- Do not install global packages; use only the existing repository-local test dependencies.
- Do not relax inclusion, 18 mm path clearance, centre support, or protection rules.
- Keep `Agent.policy` below its internal 5.75 second hard limit.
- Do not initialize Git or create commits because this workspace is not a Git repository.

---

### Task 1: Portable failure snapshots

**Files:**
- Create: `simulator/tests/replay_support.py`
- Create: `simulator/tests/test_highscore_replay.py`
- Modify: `simulator/tests/run_physics_smoke.py`

**Interfaces:**
- Produces: `save_observation_snapshot(path: Path, observation: dict, metadata: dict | None = None) -> None`
- Produces: `load_observation_snapshot(path: Path) -> tuple[dict, dict]`
- Consumes: observations containing `container_list`, `pool_list`, optional `depth_map`, and NumPy scalar values.

- [ ] **Step 1: Write the failing round-trip test**

Create an observation using `container_dict()`, `item_dict()`, and a `(1, 64, 64)` float32 depth map. Save to a temporary `.npz`, load it, and assert exact container/pool values, float32 depth dtype/shape/content, and metadata.

- [ ] **Step 2: Run the replay test and verify RED**

Run:

```powershell
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_replay -v
```

Expected: import failure because `simulator.tests.replay_support` does not exist.

- [ ] **Step 3: Implement JSON-safe snapshot serialization**

Implement recursive conversion of dict/list/tuple, NumPy arrays, and NumPy scalars. Store JSON payload and depth map with `np.savez_compressed`; exclude `shm_name`, `shm_shape`, and `shm_dtype`. Restore the depth array and return metadata separately.

- [ ] **Step 4: Verify GREEN and the full unit suite**

Run the focused test, then `unittest discover`; both must pass.

- [ ] **Step 5: Add opt-in capture to physics smoke**

Add `--snapshot-on-failure PATH`. Immediately before executing an action retain the observation; if any official status is false, save it with task, completed-step count, attempted action, and status metadata.

---

### Task 2: Support-grid free-space proposer

**Files:**
- Create: `simulator/agents/highscore/free_space.py`
- Create: `simulator/tests/test_highscore_free_space.py`
- Modify: `simulator/agents/highscore/settings.py`

**Interfaces:**
- Produces: `grid_recovery_centres(supports: Sequence[Rect], bounds: Rect, obstacles: Sequence[AABB], half: np.ndarray, bottom_z: float, step: float, clearance: float, limit: int, deadline: float | None) -> list[tuple[float, float]]`
- The function returns back-to-front candidate centres whose discretized footprint is fully supported and free at the candidate height.

- [ ] **Step 1: Write failing tests for a fragmented support plane**

Test an interior rectangular gap whose centre is not a wall coordinate, confirm a fitting footprint is proposed, confirm an oversized footprint returns no centres, and confirm an expired deadline returns immediately.

- [ ] **Step 2: Run the focused test and verify RED**

Expected: import failure because `free_space.py` does not exist.

- [ ] **Step 3: Implement the bounded integral-image search**

Rasterize `bounds` at 20 mm. Mark support coverage and obstacle-expanded occupancy at the candidate vertical interval. Build summed-area tables, test each footprint window in O(1), convert feasible window centres to float64 coordinates, rank by descending Y then clearance from occupied cells, deduplicate at 1 mm, and stop at `limit` or `deadline`.

- [ ] **Step 4: Verify GREEN and full unit tests**

Run `test_highscore_free_space`, then the complete unit suite.

---

### Task 3: Candidate-generator recovery integration

**Files:**
- Modify: `simulator/agents/highscore/candidates.py`
- Modify: `simulator/agents/highscore/settings.py`
- Modify: `simulator/tests/test_highscore_candidates.py`

**Interfaces:**
- Consumes: `grid_recovery_centres(...)` from Task 2.
- Preserves: `CandidateGenerator.generate(...) -> list[Candidate]`.
- Adds internal: `_validate_position(...) -> Candidate | None` shared by normal and recovery proposals.

- [ ] **Step 1: Write a failing recovery integration test**

Construct a supported, fragmented state with `coordinate_limit=2` where normal extreme-point stages return zero, invoke `generate`, and assert the returned centre is one of the interior grid positions absent from the normal coordinate set. Do not change the `Candidate` schema. Also assert support ratio, plane inclusion, and clearance.

- [ ] **Step 2: Run the focused test and verify RED**

Expected: no recovery candidate is returned.

- [ ] **Step 3: Extract common candidate validation**

Move the existing checks—frontier reservation, plane inclusion, collision, support union, protection columns, effective lift, swept path, depth comparison, and clearance calculation—into `_validate_position`. Preserve current behavior by running all existing candidate tests immediately after extraction.

- [ ] **Step 4: Add recovery support levels and proposals**

After normal and local-grid stages return zero, enumerate floor, main shelf when present, small shelf, and axis-aligned placed-item tops. For each orientation call `grid_recovery_centres`, set the same floor/shelf/contact Z conventions as normal candidates, validate proposals through `_validate_position`, and stop at `recovery_candidates_per_orientation` or deadline.

- [ ] **Step 5: Verify focused and complete tests**

Run candidate/free-space tests and then all unit tests. No prior candidate test may change expectation.

---

### Task 4: Snapshot replay CLI and regression

**Files:**
- Create: `simulator/tests/replay_candidate_snapshot.py`
- Modify: `simulator/tests/run_physics_smoke.py`

**Interfaces:**
- Consumes: `load_observation_snapshot` and `CandidateGenerator.generate`.
- CLI: `python tests/replay_candidate_snapshot.py SNAPSHOT [--seconds 5.5]`.

- [ ] **Step 1: Write a CLI smoke test around its callable entry point**

Expose `analyze_snapshot(path: Path, seconds: float) -> dict`; save a small snapshot and assert the report contains one result per pool item with candidate count, elapsed time, and a best-action dictionary. For an item with no candidates, the action must be `None`.

- [ ] **Step 2: Verify RED**

Expected: import failure because the replay module does not exist.

- [ ] **Step 3: Implement replay analysis and JSON output**

Load the observation, rebuild `PackingState`, convert pool entries to `ItemSpec`, run generation under a shared deadline, score candidates, and return JSON-safe action dictionaries.

- [ ] **Step 4: Capture and replay real A/B failure states**

Run the physics smoke with `--snapshot-on-failure` for task 000 and 001, then run the replay CLI against both files. Record whether recovery finds a candidate and its runtime; do not claim full completion unless the physical replay succeeds.

- [ ] **Step 5: Run official integration and verification**

Run the four-item official multiprocessing smoke, full `unittest discover`, and `compileall`. Then run long sample regressions only if the replay reports at least one new recovery candidate.
