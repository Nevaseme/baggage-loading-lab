# MPC-MCTS EMS Packing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic EMS/heightmap MPC-MCTS planner that passes 25/25 task000 and 30/30 task001 locally and becomes eligible for controlled SIGNATE iterations toward Public score 60 or higher.

**Architecture:** A pure compressed packing model maintains support layers and empty maximal rectangles.  It supplies cheap rollout actions to an anytime MCTS, while the existing `CandidateGenerator` exactly validates every root action that policy may return.  Agent integration is opt-in until a one-factor physical gate passes.

**Tech Stack:** Python 3.12, standard library, NumPy, `unittest`; the existing PyBullet environment only for integration tests.

## Global Constraints

- Standard library and NumPy only in the submission.
- Do not modify `simulator/src`, install dependencies, initialize Git, or inspect credentials.
- Preserve `Agent` signatures and the exact action dictionary.
- Rebuild state from settled observation after every action; never return a rollout-only action.
- Policy search stops by 5.40 seconds and the measured end-to-end maximum stays below 6 seconds.
- `use_monotone_ingress` and `use_geometry_rescue` remain default `False`.
- Treat `simulator/submissions/highscore_guarded_20260813.zip` and SHA-256 `3789B037DA39BD2F38215D711C42AD9CF504503F44B94016517A675044CB4A54` as immutable.
- Because the workspace has no Git repository, each task writes a report under `.superpowers/sdd/2026-08-13-mpc-mcts-ems/` and receives an independent file-scope review instead of committing.

---

### Task 1: Pure EMS and support-layer state

**Files:**
- Create: `simulator/agents/highscore/ems.py`
- Create: `simulator/tests/test_highscore_ems.py`
- Report: `.superpowers/sdd/2026-08-13-mpc-mcts-ems/task-1-report.md`

**Interfaces:**
- Consumes: `AABB`, `Rect`, `ItemSpec`, `PackingState`, and `oriented_dimensions`.
- Produces:

```python
@dataclass(frozen=True)
class EMS:
    rect: Rect
    bottom_z: float
    max_height: float
    container_index: int
    protection: tuple[bool, bool]

@dataclass(frozen=True)
class ProxyAction:
    item: ItemSpec
    pool_index: int
    container_index: int
    orientation: int
    box: AABB
    support_key: tuple[int, int]

@dataclass
class ProxyState:
    spaces: tuple[EMS, ...]
    boxes: tuple[AABB, ...]
    placed_ids: tuple[int, ...]

def build_proxy_state(state: PackingState, clearance: float) -> ProxyState: ...
def propose_actions(state: ProxyState, item: ItemSpec, pool_index: int,
                    *, limit: int, deadline: float) -> list[ProxyAction]: ...
def apply_action(state: ProxyState, action: ProxyAction,
                 clearance: float) -> ProxyState | None: ...
def state_key(state: ProxyState, remaining_ids: tuple[int, ...],
              quantum: float = 0.01) -> tuple: ...
```

- [ ] **Step 1: Write RED tests for EMS splitting and pruning**

Add tests with a `Rect(0, 2, 0, 2)` EMS and a centred `1x1` footprint.  Assert the four residual rectangles cover all unoccupied area, no residual intersects the placed footprint, and spaces contained by another space are pruned.  Add boundary-touch and sub-millimetre-overlap cases.

- [ ] **Step 2: Run the RED test**

Run:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_ems -v
```

Expected: import failure for `simulator.agents.highscore.ems`.

- [ ] **Step 3: Implement immutable split/prune primitives**

Use exact float64 rectangle arithmetic.  A split returns left, right, front,
and back rectangles with positive area; `prune_spaces` removes duplicates and
strictly contained spaces after rounding only its deterministic sort key.

- [ ] **Step 4: Add RED tests for support layers**

Build floor-only, main-shelf, small-shelf, and placed-top fixtures.  Assert
separate Z layers, correct container indices, no bridge across an unsupported
gap, and priority/soft protection inherited independently.

- [ ] **Step 5: Implement `build_proxy_state`**

Construct floor and static-shelf support rectangles using the same state
conventions as `CandidateGenerator`; add axis-aligned placed tops; subtract
placed footprints at the matching vertical band.  Tilted items remain obstacles
and never become support.

- [ ] **Step 6: Add RED tests for action proposal and transition**

Assert six official orientations are considered, a 0.75 m item spans the old
two-lane boundary, actions are ordered by heightmap increase then residual EMS
area, protected supports reject incompatible items, and `apply_action` cannot
overlap an existing expanded AABB.

- [ ] **Step 7: Implement proposal, transition, and deterministic key**

Propose EMS corners, centre, and wall-aligned fits; deduplicate centres at
1 mm; enforce support, protection, container height, and conservative AABB
collision/path constraints.  `state_key` quantizes only for transposition lookup,
not feasibility.

- [ ] **Step 8: Verify and review Task 1**

Run the EMS suite plus geometry/candidate suites and full discovery.  Write exact
RED/GREEN commands, pass counts, timing, and files to the report; request an
independent spec/code review and resolve all Critical/Important findings.

---

### Task 2: Exact root feasibility mask and compressed catalog

**Files:**
- Modify: `simulator/agents/highscore/candidates.py`
- Create: `simulator/agents/highscore/catalog.py`
- Create: `simulator/tests/test_highscore_catalog.py`
- Modify: `simulator/agents/highscore/settings.py`
- Report: `.superpowers/sdd/2026-08-13-mpc-mcts-ems/task-2-report.md`

**Interfaces:**
- Consumes: Task 1 `ProxyAction`, `ProxyState`, `propose_actions`.
- Produces:

```python
@dataclass(frozen=True)
class RootAction:
    candidate: Candidate
    proxy_action: ProxyAction
    next_state: ProxyState

def CandidateGenerator.validate_proposal(
    self, state: PackingState, action: ProxyAction, *,
    allow_rule_violations: bool = False,
) -> Candidate | None: ...

def build_root_catalog(
    state: PackingState, pool: Sequence[ItemSpec], generator: CandidateGenerator,
    settings: SearchSettings, *, deadline: float,
) -> list[RootAction]: ...
```

- [ ] **Step 1: Write a RED validator-equivalence test**

For a valid floor, shelf, and stack proposal, assert `validate_proposal` returns
the same orientation, box, support ratio, rule violations, and path decision as
the existing generation path.  Add invalid collision, support, priority, depth,
and 15 mm swept-path cases.

- [ ] **Step 2: Run RED and implement the public wrapper**

Expected RED: missing `validate_proposal`.  Implement it by selecting the same
eligible container, obstacles, floor/shelf heights, fill ratio, support target,
and calling the existing `_validate_position`; do not duplicate hard geometry.

- [ ] **Step 3: Write RED catalog tests**

Assert the catalog contains only exact-validated candidates, includes at least
two different pool items when both fit, fairly budgets the deadline across pool
items, maps every root to a valid proxy successor, and is deterministic.

- [ ] **Step 4: Implement bounded catalog construction**

Add settings:

```python
ems_proxy_actions_per_item: int = 24
ems_exact_roots_per_item: int = 6
ems_root_catalog_limit: int = 48
ems_root_budget_seconds: float = 1.35
```

Build Task 1 proposals per item with a fair-share absolute deadline, validate in
heightmap/fragmentation order, retain at most six exact roots per item, then sort
by violations, urgency, support, clearance, low height, and deterministic IDs.

- [ ] **Step 5: Deadline and exception tests**

Use fake clocks and failing validators to prove catalog construction returns all
already validated roots without exceeding its absolute deadline or discarding
earlier results.

- [ ] **Step 6: Verify and review Task 2**

Run catalog/EMS/candidate tests and full discovery; write the report and obtain
independent review before continuing.

---

### Task 3: Deterministic anytime MPC-MCTS

**Files:**
- Create: `simulator/agents/highscore/mcts.py`
- Create: `simulator/tests/test_highscore_mcts.py`
- Modify: `simulator/agents/highscore/settings.py`
- Report: `.superpowers/sdd/2026-08-13-mpc-mcts-ems/task-3-report.md`

**Interfaces:**
- Consumes: `RootAction`, `ProxyState`, `propose_actions`, and `apply_action`.
- Produces:

```python
@dataclass(frozen=True, order=True)
class RolloutValue:
    packed_count: int
    packed_volume: float
    neg_violations: int
    largest_space_volume: float
    minimum_ingress_slack: float
    neg_roughness: float
    neg_cog: float

class MCTSSearch:
    def __init__(self, settings: SearchSettings): ...
    def choose(self, roots: Sequence[RootAction], pool: Sequence[ItemSpec],
               *, deadline: float, seed: int) -> Candidate | None: ...
```

- [ ] **Step 1: RED tests for value and selection**

Assert packed count dominates every lower field, volume breaks count ties,
rule violations are minimized next, and UCB selects an unvisited child before
visited children while deterministic ties choose the stable action key.

- [ ] **Step 2: Implement node/value/UCB primitives**

Store total scalar backup separately from the lexicographic best rollout.
Normalize each secondary feature for the UCB scalar but use `RolloutValue` for
final root selection.

- [ ] **Step 3: RED tests for progressive widening and rollouts**

Use a tiny synthetic proxy state where one first action packs three visible
items and another packs only two despite better immediate height.  Assert MCTS
chooses the three-item branch.  Assert widening follows
`child_count <= floor(k * visits**alpha)`, rollouts terminate, and the same seed
gives the same result.

- [ ] **Step 4: Implement expansion and rollout policy**

Add settings:

```python
mcts_exploration: float = 1.15
mcts_progressive_k: float = 2.0
mcts_progressive_alpha: float = 0.50
mcts_rollout_limit: int = 64
mcts_transposition_quantum: float = 0.01
mcts_policy_limit_seconds: float = 5.40
```

Expansion ranks scarce large items and low-waste actions.  Rollouts use a local
`random.Random(seed)` and select among the top three best-fit actions; unseen
items are never created.  Cache rollout values by Task 1 state key.

- [ ] **Step 5: RED deadline and best-root preservation tests**

Patch the clock so search expires during selection, expansion, and rollout.
Assert `choose` returns the best exact root already evaluated and never a proxy
action.  Inject node exceptions and preserve the previous root.

- [ ] **Step 6: Verify and review Task 3**

Run MCTS/EMS/catalog tests, deterministic repetitions, full discovery, report,
and independent review.

---

### Task 4: Planner and Agent integration behind one flag

**Files:**
- Modify: `simulator/agents/highscore/settings.py`
- Modify: `simulator/agents/highscore/planner.py`
- Modify: `simulator/agents/highscore/agent.py`
- Modify: `simulator/tests/test_highscore_planner.py`
- Modify: `simulator/tests/run_physics_smoke.py`
- Report: `.superpowers/sdd/2026-08-13-mpc-mcts-ems/task-4-report.md`

**Interfaces:**
- Adds `SearchSettings.use_mpc_mcts_ems: bool = False`.
- Adds `Planner.choose_mpc(state, pool, *, deadline, seed) -> Candidate | None`.
- Adds harness `--mpc-mcts-ems {on,off}` and JSON field `mpc_mcts_ems`.

- [ ] **Step 1: RED planner-contract tests**

With a fake catalog and MCTS, assert flag ON calls `choose_mpc`, returns its exact
root candidate, and never calls legacy `choose_online`.  Flag OFF must call the
unchanged legacy path, including its depth-aware emergency behavior.

- [ ] **Step 2: Implement `Planner.choose_mpc`**

Allocate at most 1.35 seconds to the exact catalog and the remainder to MCTS,
bounded by `min(caller_deadline, start + 5.40)`.  Seed from a stable hash of
container AABBs and visible item IDs, not Python's randomized `hash()`.

- [ ] **Step 3: Integrate Agent policy**

When ON, give policy an absolute 5.40-second MCTS deadline.  When OFF, retain
the current 1.0-second legacy planner plus legacy emergency.  Exact formatting,
pool index clamping, and container index clamping remain unchanged.

- [ ] **Step 4: RED/GREEN harness selection test**

Extend the subprocess help test for `--mpc-mcts-ems`.  Immediately after Agent
construction replace all three flags consistently and reconstruct `Planner`.
Record the selected mode in result JSON.

- [ ] **Step 5: Snapshot regressions**

Replay the saved task000/task001 observations.  Assert ON returns an exact root,
does not select the known invalid deterministic action, and its proxy branch has
a strictly larger jointly packable pool count on at least one snapshot.  This is
a diagnostic gate only; PyBullet remains authoritative.

- [ ] **Step 6: Verify and review Task 4**

Run all 61+ existing tests, new suites, compileall, CLI smoke, and independent
review.  Resolve every Critical/Important issue before physics runs.

---

### Task 5: Physical acceptance, artifact, and Public-score loop

**Files:**
- Create: `docs/superpowers/plans/2026-08-13-mpc-mcts-ems-benchmark.md`
- Create conditionally: `simulator/submissions/highscore_mpc_mcts_ems_<timestamp>.zip`
- Report: `.superpowers/sdd/2026-08-13-mpc-mcts-ems/task-5-report.md`

**Interfaces:**
- Consumes the Task 4 runtime flag.
- Produces a ZIP whose top level is exactly `highscore/` and a recorded SIGNATE submission memo only after all local gates pass.

- [ ] **Step 1: Run official four-item smoke**

Run with monotone OFF, geometry rescue OFF, MPC-MCTS ON.  Require 4/4 safe and
max policy below 6 seconds.

- [ ] **Step 2: Run one-factor task000 A/B**

Run 25 items, seed 42, optimize 0, MPC OFF then ON.  Save raw stdout/stderr.
Require ON 25/25 safe; otherwise leave the flag default OFF and diagnose before
any submission.

- [ ] **Step 3: Run one-factor task001 A/B**

Run 30 items, seed 42, optimize 0, MPC OFF then ON.  Require ON 30/30 safe,
every status true, and max policy below 6 seconds.

- [ ] **Step 4: Final verification and review**

Run full unittest discovery, compileall, ZIP import in an extracted temporary
directory, content audit excluding tests/cache/dependencies, and independent
spec/code review.  Record exact counts, timings, memory if available, and the
guarded ZIP hash.

- [ ] **Step 5: Build and submit one controlled variant**

Only after Steps 1-4 pass, package exactly the production Python files under
`highscore/`.  Use the already configured repository-local SIGNATE CLI; do not
log tokens or browser data.  Submit with a memo naming `MPC-MCTS EMS v1`, local
25/25 and 30/30 counts, ZIP SHA-256, and the one changed factor.

- [ ] **Step 6: Iterate to Public 60**

Record the returned Public score beside baseline `12.622949582873819`.  If below
60, change only one of: root catalog budget, MCTS exploration/widening, or
rollout waste value; rerun Steps 1-5.  Never tune two factors from one score.
Completion requires an actual SIGNATE Public score `>= 60.0`, not an inferred
local score.
