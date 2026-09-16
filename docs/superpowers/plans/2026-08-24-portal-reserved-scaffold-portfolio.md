# Portal-Reserved Scaffold Portfolio Implementation Plan

> **Status note — 2026-09-08:** This is the historical candidate plan, not an automatic resume instruction. The ledger records Tasks 1–3 complete and Task 4 paused with unverified partial code. Use the root `AGENTS.md` for current workflow/model selection and `docs/evaluation-contract.md` for submission acceptance. Select or revise the remaining approach from evidence; the task sequence and unchecked boxes below preserve the original plan, not a requirement to repeat completed work.

**Goal:** Build and experimentally select a mode-aware portal-reserved scaffold algorithm whose local evidence is materially stronger than the Public-29.7 historical control and whose package is eligible for a controlled Public submission.

**Architecture:** Preserve the observed low-column virtual-planning advantage as a slot/support DAG, add future Y-then-X portal precedence, and keep a single calibrated current-state action authorizer. Test a multi-frontier portal profile as an independent candidate-recall spike before integrating it. Mode A, B, and C use different planners behind the same authorization boundary.

**Tech Stack:** Python 3.12, NumPy, Gymnasium, PyBullet, `unittest`, project-local `.signate_venv`.

**Spec:** `docs/superpowers/specs/2026-08-24-portal-reserved-scaffold-portfolio-design.md`

## Global Constraints

- Preserve the simulator public `Agent` interface and exact action dictionary.
- Every returned action must pass fresh current-state inclusion, target, transport, support-risk, occurrence, and float32 checks.
- No unchecked fallback and no candidate-zero episode may be promoted.
- Policy p99 must be below 5.5 seconds and maximum below 6 seconds; official timeout is 8 seconds.
- Optimization must stay below 180 seconds.
- Historical submissions and score-bearing artifacts are read-only.
- New names must describe the algorithm and must not include generic or unverified-score terms.
- Official component weights are unknown; local CoG, protection, support, displacement, and rotation values are proxies.
- The workspace is not a Git repository; use test/review checkpoints instead of commits.

---

### Task 1: Normalize external feedback and experiment evidence

**Files:**
- Create: `analysis/submission_result_matrix.json`
- Create: `analysis/episode_evidence_schema.json`
- Modify: `progress.md`
- Test: `simulator/tests/test_submission_result_matrix.py`

**Interfaces:**
- Consumes: four `submit/**/result-log.txt` files and current result JSONs.
- Produces: `load_submission_result_matrix(root: Path) -> list[dict]` in the test helper contract and a documented two-grain evidence schema.

- [ ] Write a failing test that requires exactly four uniquely resolved result-log records, all documented fields, source paths, status, and nullable Public score.
- [ ] Run `simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_submission_result_matrix -v` and confirm the matrix is absent or incomplete.
- [ ] Create the normalized matrix with no inferred metric, score, task count, denominator, or failure step.
- [ ] Update `progress.md` to add `ingress_preserving_column_scaffold`, populate externally returned component metrics/status for all four artifacts, label their grain, and remove stale “pending/not run” claims.
- [ ] Run the focused test and independently review the ledger against every one-line source log.

### Task 2: Capture historical pre-action snapshots and predicate recall

**Files:**
- Modify: `simulator/tests/run_historical_conservative_extreme_point_physics.py`
- Create: `simulator/tests/replay_historical_predicates.py`
- Test: `simulator/tests/test_replay_historical_predicates.py`
- Output: `simulator/results/portal_reserved_scaffold/historical-task000-predicate-recall.json`

**Interfaces:**
- Produces: `capture_pre_action_snapshot(...)`, `replay_action(snapshot, action, profile) -> dict[str, bool]`, and one immutable record per attempted action.

- [ ] Write failing tests for snapshot count, action identity, post-episode replay isolation, float32 binding, and predicate result fields.
- [ ] Verify the tests fail before changing the runner.
- [ ] Add an opt-in `--capture-all-snapshots` path that never probes or mutates the live physics state.
- [ ] Add offline replay for occurrence, inclusion, target collision, support/core, protection, and effective transport predicates.
- [ ] Run the matched historical task000 A control, verify 25 safe actions plus one failed attempt, and save artifact/config/runner/action hashes.
- [ ] Review the recall table; do not calibrate a predicate in this task.

### Task 3: Calibrated historical-plan shield cross

**Files:**
- Create: `simulator/agents/portal_reserved_scaffold_dag/authorizer.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/historical_seed.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/agent.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/__init__.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_authorizer.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_historical_cross.py`

**Interfaces:**
- Produces: `ActionProposal`, `AuthorizationResult`, `authorize_current(proposal, observation)`, and a public `Agent` preserving the official interface.

- [ ] Write RED tests that replay all captured historical actions, require at least 24 of the 25 known-safe actions to be accepted, and require the known failed action to be rejected.
- [ ] Write RED tests proving planned, repair, and emergency routes cannot format an action without `AuthorizationResult.accepted=True` bound to the same state fingerprint.
- [ ] Implement the minimum official-semantics authorizer and historical proposal adapter; do not add portal scoring yet.
- [ ] Run focused unit tests, compile the package, and run the matched A physical cross.
- [ ] Promote only if it reaches at least 24 safe placements, fill 32, no invalid/unsafe returned action, and policy maximum below 6 seconds.

### Task 4: Scaffold slot and future portal DAG

**Files:**
- Create: `simulator/agents/portal_reserved_scaffold_dag/scaffold.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/portal.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/planner.py`
- Modify: `simulator/agents/portal_reserved_scaffold_dag/agent.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_dag.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_planner.py`

**Interfaces:**
- Produces: `ScaffoldSlot`, `SupportEdge`, `PortalEdge`, `build_plan(items, containers, deadline)`, and `repair_plan(observation, plan, deadline)`.

- [ ] Write RED tests for back-before-front portal precedence, supporter-before-child order, priority-container capacity, soft/priority compatible tops, and deterministic plan hashes.
- [ ] Implement slot extraction from floor, shelf, and item-top supports and construct Y-then-X swept portal conflicts.
- [ ] Implement Mode-A beam repair retaining partial plans and lexicographic layout quality.
- [ ] Add a one-factor portal-reservation flag and run paired historical-cross controls.
- [ ] Promote portal reservation only if it moves or delays the entrance blocker and reaches at least 30 safe placements or a predeclared material paired gain.

### Task 5: Multi-frontier portal-profile candidate spike

**Files:**
- Create: `simulator/agents/portal_profile_reverse_reachability/profile.py`
- Create: `simulator/agents/portal_profile_reverse_reachability/__init__.py`
- Test: `simulator/tests/test_portal_profile_reverse_reachability.py`
- Output: `simulator/results/portal_profile_reverse_reachability/snapshot-spike.json`

**Interfaces:**
- Produces: `build_profiles(observation, item, orientation) -> list[PortalComponent]` and `propose_centers(component) -> list[np.ndarray]`.

- [ ] Write RED synthetic tests with two reachable frontiers, an obstructed single skyline, shelves, and a narrow portal.
- [ ] Implement obstacle dilation and reverse Y interval connectivity at multiple support-height bands.
- [ ] Refine profile extrema to continuous centers and pass them through Task 3's authorizer.
- [ ] Benchmark saved task001 and historical terminal snapshots.
- [ ] Integrate only if at least one newly authorized root appears within 1.5 seconds; otherwise record rejection and stop this lineage.

### Task 6: Mode B and C planners

**Files:**
- Create: `simulator/agents/portal_reserved_scaffold_dag/mode_b.py`
- Create: `simulator/agents/portal_reserved_scaffold_dag/mode_c.py`
- Modify: `simulator/agents/portal_reserved_scaffold_dag/agent.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_modes.py`

**Interfaces:**
- Produces: `choose_mode_b(observation, deadline)` and `choose_mode_c(observation, deadline)`, both returning only proposals for the shared authorizer.

- [ ] Write RED tests for lookahead dispatch, completed-child retention, lexicographic count/volume/protection/CoG/portal rank, and no unseen-arrival assumptions in C.
- [ ] Implement bounded rolling slot assignment for B and deepest-low portal-preserving selection for C.
- [ ] Add generated one/two-container, shelf/no-shelf, initialized/empty, priority/soft scenarios with fixed manifests.
- [ ] Run A/B/C physical paired tests across at least three seeds and reject any mode with a negative median completion delta or earlier safety failure.

### Task 7: Official lifecycle, timing, and provenance gates

**Files:**
- Modify: `simulator/tests/run_support_extreme_fusion_physics.py`
- Create: `simulator/tests/run_portal_reserved_scaffold_acceptance.py`
- Test: `simulator/tests/test_portal_reserved_scaffold_acceptance.py`

**Interfaces:**
- Produces: episode facts and paired aggregate records conforming to Task 1 schemas.

- [ ] Write RED tests for `TimedAgentRunner` lifecycle, eight-second timeout enforcement, 10 warmups plus 200 measured calls, immutable hashes, attempted versus safe step counts, and action-sequence hashes.
- [ ] Implement the generic acceptance runner without changing the physical environment or historical artifacts.
- [ ] Run the focused acceptance tests, full unit/integration suite, and fixed-host timing campaign.
- [ ] Fail promotion unless p99 is below 5.5 seconds, maximum below 6 seconds, and every required action is validated and physically safe.

### Task 8: Select, package, and report the strongest candidate

**Files:**
- Create: `submit/<descriptive-algorithm-name>/agent.py` and required modules
- Create: `submit/<descriptive-algorithm-name>.zip`
- Create: `analysis/portal-reserved-scaffold-experiment-report.html`
- Modify: `progress.md`
- Test: `simulator/tests/test_submission_package.py`

**Interfaces:**
- Produces: one extracted-import-verified submission ZIP, SHA-256, normalized evidence, and a durable technical report.

- [ ] Write RED package tests for exactly one top-level algorithm directory, public API, no cache/results files, deterministic action replay, and extracted ZIP import.
- [ ] Select the empirically strongest architecture without combining rejected factors.
- [ ] Build the descriptively named archive and compute its SHA-256.
- [ ] Run all unit, integration, regression, lifecycle, physics, timing, and package tests on the exact archive bytes.
- [ ] Update `progress.md` and the technical report with adopted/rejected hypotheses, paired evidence, limitations, archive path, and hash.  Keep Public score pending until authoritative feedback is supplied.
