# Quota-Fair EMS MPC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether exact-root starvation is material in high-lookahead mode B, and only then build and evaluate a standalone quota-fair EMS MPC variant against an otherwise identical standalone exact-root EMS MPC control.

**Architecture:** Phase 0 instruments the unchanged production catalog through wrapped collaborators and probes omitted pool positions under their expected fair-share budgets. If the evidence gate passes, two self-contained packages are created with identical MPC activation and production files; only the variant catalog changes to two-pass, urgency-ranked, round-robin scheduling. A module-selectable PyBullet harness then performs paired full-sample, generated-case, and latency gates before any packaging or submission.

**Tech Stack:** Python 3.12, standard library, NumPy, project-local Gymnasium 1.2.3 and PyBullet 3.2.7 under WSL Ubuntu.

## Global Constraints

- Follow `/AGENTS.md`; new algorithm packages are `exact_root_ems_mpc` and `quota_fair_ems_mpc`.
- Do not modify `simulator/agents/highscore/`, historical ZIP files, or either scored artifact under `submit/`.
- Do not initialize Git, create commits, install packages globally, or add runtime dependencies.
- Use test-first RED/GREEN cycles for every production or executable-tool behavior change.
- Use `gpt-5.6-luna` at maximum reasoning for implementation; use `gpt-5.6-sol` at high reasoning for architecture and review.
- Preserve the public `Agent` signatures and action dictionary exactly.
- Root actions returned by policy must pass the existing exact validator and have non-null proxy successors.
- The scheduler A/B must preserve proposal coordinates, validation, scoring, MCTS, seeds, rollouts, fallbacks, quotas, and global deadlines.
- The local evaluator exposes only `fill_score` and `num_placed_items`; CoG, support, protection, and stability diagnostics must be labelled as proxies.
- Use `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/` for the ledger, briefs, reports, baseline snapshots, review diffs, and raw evidence.
- Because there is no Git repository, create a pre-task copy of every writable file in the SDD workspace and generate review diffs with `git diff --no-index`; do not use Git history or commits.
- Run unit tests with the bundled Windows Python when possible. Run every PyBullet/Gymnasium test under WSL with `PYTHONPATH=.:tests:.test_deps_linux` from `simulator/`.
- Stop immediately at any explicit evidence, safety, API, timeout, parity, or adoption gate that fails.

---

### Task 1: Phase-0 Diagnostic Core and Fixed Manifest

**Files:**
- Create: `simulator/tests/quota_fair_starvation_diagnostics.py`
- Create: `simulator/tests/quota_fair_case_manifest.py`
- Create: `simulator/tests/test_quota_fair_starvation_diagnostics.py`
- Create: `simulator/tests/run_quota_fair_phase0.py`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-1-report.md`

**Interfaces:**
- Consumes: unchanged `agents.highscore.catalog.build_root_catalog`, `propose_actions`, `apply_action`, `CandidateGenerator.validate_proposal`, `CandidateScorer.item_urgency`.
- Produces:

```python
@dataclass(frozen=True)
class CatalogTraceRow:
    pool_index: int
    item_index: int
    urgency: float
    proposal_count: int
    validated_count: int
    accepted_root_count: int
    start_time: float | None
    end_time: float | None
    stop_reason: str

@dataclass(frozen=True)
class CatalogTrace:
    roots: tuple[RootAction, ...]
    rows: tuple[CatalogTraceRow, ...]
    production_start: float
    catalog_deadline: float
    observed_catalog_budget_seconds: float

@dataclass(frozen=True)
class ProbeMeasurement:
    pool_index: int
    exact_root_found: bool
    time_to_first_exact_root: float | None
    measured_elapsed_seconds: float
    proposals_exhausted: bool

@dataclass(frozen=True)
class ProbeClassification:
    measurement: ProbeMeasurement
    fair_share_seconds: float
    recoverable: bool
```

Required public signatures are:

```text
trace_production_catalog(state, pool, generator, settings, *, deadline)
    -> CatalogTrace
measure_pool_position(state, pool, pool_index, generator, settings,
                      *, probe_budget_seconds) -> ProbeMeasurement
classify_probe(measurement, *, fair_share_seconds) -> ProbeClassification
build_fixed_manifest() -> tuple[dict, ...]
manifest_hash(cases) -> str
materialize_case(template, seed, sample_config) -> dict
```

The tracer algorithm is exact and complete:

```text
real_catalog  := agents.highscore.catalog.build_root_catalog
real_propose  := agents.highscore.catalog.propose_actions
real_apply    := agents.highscore.catalog.apply_action
real_clock    := agents.highscore.catalog.time.perf_counter
records       := one mutable counter record for every enumerate(pool) position
clock_values  := []
active_pool_index := None
accepted_events := []
exact_valid_action_ids := set()

clock_proxy.perf_counter():
    value := real_clock()
    append value to clock_values
    if active_pool_index is not None:
        append (active_pool_index, value, len(accepted_events),
                records[active_pool_index].accepted_root_count)
        to that record's checkpoint_events
    return value

traced_propose(proxy_state, item, pool_index, *, limit, deadline):
    resolve the counter record directly by pool_index
    set active_pool_index := pool_index
    set that record's first start_time from real_clock() if absent
    store the exact per-item deadline supplied by production
    call real_propose with unchanged arguments inside try/finally
    set proposal_end_time and end_time from real_clock() in finally
    on normal return, set proposal_completed_normally=true and add the returned
    proposal count; on exception leave it false and re-raise unchanged
    return the original proposal objects unchanged

traced_apply(proxy_state, action, clearance):
    call real_apply once with unchanged arguments inside try/finally
    update action.pool_index's end_time from real_clock() in finally
    if the returned successor is non-null and id(action) is in
    exact_valid_action_ids, increment that position's accepted_root_count and
    append (pool_index, end_time) to accepted_events before returning
    return the original result unchanged

counting_generator.validate_proposal(state, action):
    increment validated_count for action.pool_index
    forward inside try/finally; update that position's end_time from real_clock()
    if the returned candidate is non-null, add id(action) to
    exact_valid_action_ids
    in finally; return the original result unchanged

patch only the catalog module's propose_actions and apply_action references and
replace only the catalog module's `time` reference with a proxy exposing the
forwarding `perf_counter` above (do not patch the process-global time module);
call real_catalog(state, pool, counting_generator, settings, deadline=deadline)
exactly once inside try/finally; restore all patched references in finally
production_start := clock_values[0]
effective_catalog_deadline := min(
    deadline, production_start + max(0, settings.ems_root_budget_seconds))

assert len(accepted_events) == len(original roots); if this instrumentation
invariant fails, mark every otherwise cap/deadline row `unknown` and fail the
diagnostic test rather than emitting recoverability evidence

For each visited position with unhandled proposals, its causal termination
checkpoint is the first recorded catalog-clock checkpoint strictly after that
position's `end_time`. Evaluate that checkpoint in the exact order used by the
production inner loop: item deadline, catalog deadline, per-item quota, global
catalog limit. Separately evaluate the final production outer-loop checkpoint
in its exact order: catalog deadline, then global catalog limit. Derive
`cutoff_pool_index` as the greatest visited pool index. For every pool position,
apply this causal precedence exactly:
    per_item_quota      if accepted_root_count == settings.ems_exact_roots_per_item
    proposal_exhausted  if visited, proposal_completed_normally is true,
                        validated_count == proposal_count, and its
                        proposal/validation end_time is strictly before both
                        its stored item_deadline and effective_catalog_deadline
    global_cap          if this position's causal inner checkpoint selected the
                        global limit, or it is unvisited after cutoff and the
                        final outer checkpoint selected the global limit
    catalog_deadline    if this position's causal inner checkpoint selected the
                        catalog deadline, or it is unvisited after cutoff and
                        the final outer checkpoint selected the catalog deadline
    not_visited         if start_time is absent
    unknown             otherwise

Never assign `global_cap` or `catalog_deadline` to a lower pool position that
had already ended before the causal cutoff. If both global cap and deadline are
true at a checkpoint, mirror production's condition order above rather than
guessing from the final catalog state. An item-deadline termination maps to
`unknown`, not to a global stop. `end_time` is the last proposal-generation,
validation, or apply event for that position, not the time at which a later
position terminates.
return CatalogTrace(tuple(original roots), rows sorted by pool_index,
                    production_start, effective_catalog_deadline,
                    max(0, effective_catalog_deadline - production_start))
```

The independent measurement and immutable classification algorithms are:

```text
reject pool_index outside range
started := time.perf_counter()
probe_deadline := started + max(0.0, probe_budget_seconds)
proxy_state := build_proxy_state(state, settings.path_clearance,
                                 support_inset=max(0, -settings.inclusion_margin),
                                 shelf_drop_gap=settings.shelf_drop_gap)
proposals_exhausted := true
try:
    proposals := real propose_actions(proxy_state, pool[pool_index], pool_index,
                                      limit=settings.ems_proxy_actions_per_item,
                                      deadline=probe_deadline)
except Exception:
    return ProbeMeasurement(pool_index, false, None,
                            time.perf_counter() - started, false)
for action in proposals:
    if time.perf_counter() >= probe_deadline:
        proposals_exhausted := false
        break
    try:
        candidate := generator.validate_proposal(state, action)
        if candidate is None: continue
        successor := real apply_action(proxy_state, action,
                                       settings.path_clearance)
    except Exception:
        continue
    if successor is None: continue
    elapsed := time.perf_counter() - started
    return ProbeMeasurement(pool_index, true, elapsed, elapsed, false)
elapsed := time.perf_counter() - started
if started + elapsed >= probe_deadline:
    proposals_exhausted := false
measurement := ProbeMeasurement(pool_index, false,
                                None, elapsed,
                                proposals_exhausted)
return measurement

classify_probe(measurement, *, fair_share_seconds):
    clamped_share := max(0.0, fair_share_seconds)
    classification := ProbeClassification(
        measurement=measurement,
        fair_share_seconds=clamped_share,
        recoverable=(measurement.exact_root_found
                     and measurement.time_to_first_exact_root is not None
                     and measurement.time_to_first_exact_root
                         <= clamped_share))
    return classification
```

`build_fixed_manifest` returns the literal immutable `FIXED_CASES` tuple.
`manifest_hash` hashes `json.dumps(tuple(cases), sort_keys=True,
separators=(",", ":"))` with SHA-256. `materialize_case` deep-copies
`sample_config["001"]`, sets the template lookahead, applies the literal Step 5
transformations, and returns only JSON-serializable values.

- [ ] **Step 1: Write failing diagnostic tests**

Create literal fixtures proving that the tracer calls the real production catalog exactly once, preserves duplicate `item.index` values as separate pool positions, reports `unknown` rather than guessing an unsupported stop reason, and emits every member of the exact taxonomy `global_cap`, `catalog_deadline`, `not_visited`, `proposal_exhausted`, `per_item_quota`, and `unknown` under its defining trace. Assert that only `global_cap` and `catalog_deadline` rows with zero roots are eligible for the recoverability numerator. The production mutation each test catches is replacing the real catalog with a copied loop or merging records by item ID.

Add two causal-precedence regressions: an early zero-root position that fully
exhausts before a later position reaches 48 roots remains
`proposal_exhausted`, and the same early exhaustion remains
`proposal_exhausted` when a later position reaches the catalog deadline. In
both fixtures only the causally cut-off position and later unvisited positions
may receive the cap/deadline label.

```python
def test_trace_calls_real_catalog_once_and_keeps_duplicate_item_ids_separate():
    pool = (_item(index=7), _item(index=7))
    trace = trace_production_catalog(state, pool, generator, settings, deadline=deadline)
    assert real_catalog_calls == 1
    assert [row.pool_index for row in trace.rows] == [0, 1]

def test_probe_is_recoverable_only_within_fair_share():
    measurement = ProbeMeasurement(9, True, 0.010, 0.015, True)
    fast = classify_probe(measurement, fair_share_seconds=0.050)
    slow = classify_probe(measurement, fair_share_seconds=0.001)
    assert fast == ProbeClassification(measurement, 0.050, True)
    assert slow == ProbeClassification(measurement, 0.001, False)
```

- [ ] **Step 2: Verify RED**

Run from `simulator/`:

```text
python -m unittest tests.test_quota_fair_starvation_diagnostics -v
```

Expected: import failure for the absent diagnostic modules, not a fixture or dependency error.

- [ ] **Step 3: Implement the minimal tracing wrappers**

Call `agents.highscore.catalog.build_root_catalog` once while `unittest.mock.patch.object` temporarily wraps that module's real `propose_actions` and `apply_action`; wrap the passed generator with a forwarding object that counts `validate_proposal` calls. Do not copy the catalog loop. Classify stop reasons only from observed calls, returned roots, the 48-root cap, and elapsed deadline. Advance no production state.

The independent probe calls the unchanged real proposal, validator, and transition functions, stops at the supplied fair-share deadline, and records measured time to the first exact root.

- [ ] **Step 4: Add the literal 16-template manifest and deterministic hash**

Encode the exact 16 tuples from the approved design with no Cartesian expansion. Serialize using `json.dumps(cases, sort_keys=True, separators=(",", ":"))` and hash with SHA-256. Add a literal expected template count of 16 and a hand-recorded expected digest after the first RED run.

- [ ] **Step 5: Implement deterministic case materialization and the Phase-0 CLI**

Deep-copy `sample_config.json["001"]`. Set `look_ahead` from the template. For two-container cases, deep-copy the first container, assign index 1, and let the existing `spacing` field determine its world offset; designate the priority container on alternating two-container template numbers. Set `require_shelf` literally from the template.

Transform the 42 source items deterministically: `normal` clears both attributes; `soft` marks every third item soft; `priority` marks every fourth item prioritized; `combined` applies both rules. Order by `(volume, index)` ascending or descending, use `random.Random(seed).shuffle` for random order, and create repeated-dimension cases by copying the first source dimensions while retaining unique item indices and masses. Store the materialized JSON and SHA-256.

Use warm-up targets `early=0`, `middle=8`, and `high=16`. For `empty`, begin from the empty config and capture the diagnostic observation after the control policy reaches the target. For `preloaded`, run the same deterministic control warm-up once, serialize the settled packed-item poses into `packed_items`, remove those items from the stream, and initialize both later consumers from that identical materialized config. Abort a case if warm-up produces any false status.

The CLI parser accepts exactly `--task`, `--items`, `--include-saved-snapshots`, `--include-fixed-manifest`, `--lookaheads`, `--seeds`, `--aggregate`, `--manifest-output`, and `--output`. It runs `agents.highscore` with `use_mpc_mcts_ems=True`, attaches the real depth map, calls the Task 1 tracer on each selected observation, probes omitted positions, and writes schema-versioned JSON atomically through a temporary file plus `Path.replace`. Aggregate mode reads only the explicitly listed raw JSON files and emits the Task 2 schema.

- [ ] **Step 6: Verify focused GREEN and regression safety**

```text
python -m unittest tests.test_quota_fair_starvation_diagnostics -v
python -m unittest tests.test_highscore_catalog tests.test_highscore_ems tests.test_highscore_mcts -v
python -m compileall -q tests/quota_fair_starvation_diagnostics.py tests/quota_fair_case_manifest.py tests/run_quota_fair_phase0.py
```

Expected: all commands exit 0; historical production files remain unchanged.

- [ ] **Step 7: Write the task report and review package**

Record RED output, GREEN commands/output, manifest digest, changed files, self-review, and concerns in `task-1-report.md`. Generate a no-index diff from the pre-task copies and send the brief, report, and diff to a Sol-high reviewer. Fix all Critical/Important findings through Luna before Task 2.

---

### Task 2: Execute Phase 0 and Enforce the Evidence Gate

**Files:**
- Create evidence: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/results.json`
- Create evidence: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/manifest.json`
- Create report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0-report.md`
- Modify only if a diagnostic bug is found: Task 1 test/tool files, with a new RED test first.

**Interfaces:**
- Consumes: Task 1 CLI and current `agents.highscore` with `use_mpc_mcts_ems=True` supplied to the diagnostic runner.
- Produces: signed-off `proceed: true|false`, recoverable-starvation numerator/denominator/frequency, time-to-first-root distribution, and exact stop reasons.

The aggregate `results.json` schema is exact:

```json
{
  "schema_version": 1,
  "manifest_sha256": "64 lowercase hexadecimal characters",
  "measured_state_count": 0,
  "lookahead_20_40_state_count": 0,
  "recoverable_state_count": 0,
  "recoverable_frequency": 0.0,
  "qualifying_state_ids": [],
  "stop_reason_counts": {},
  "time_to_first_exact_root_seconds": [],
  "proceed": false,
  "source_files": []
}
```

- [ ] **Step 1: Run the saved-snapshot and full-task001 diagnostic**

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_quota_fair_phase0.py --task 001 --items 42 --include-saved-snapshots --output ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/task001.json'
```

- [ ] **Step 2: Run the fixed lookahead-20/40 manifest subset**

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_quota_fair_phase0.py --include-fixed-manifest --lookaheads 20,40 --seeds 17,42,2026 --output ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/generated.json'
```

- [ ] **Step 3: Aggregate the two raw files into the declared outputs**

The CLI also accepts `--aggregate INPUT [INPUT ...]`, `--manifest-output`, and `--output`. Run:

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_quota_fair_phase0.py --aggregate ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/task001.json ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/generated.json --manifest-output ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/manifest.json --output ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/results.json'
```

The denominator is the number of distinct measured observation IDs whose visible lookahead is 20 or 40. The numerator is the number of those distinct states containing at least one omitted pool position whose stop reason is `global_cap` or `catalog_deadline`, whose independent probe found an exact root, and whose measured time-to-first-root did not exceed its fair share.

Calculate fair shares over the full visible ordering sorted exactly by
`(-CandidateScorer.item_urgency(item, state.containers), item.index,
pool_index)`, including positions already covered by the baseline. Independently
measure every position with a fresh proxy state and
`probe_budget_seconds=observed_catalog_budget_seconds`; never share a live probe
deadline or mutate proxy state between positions. Then derive new immutable
`ProbeClassification` values with this recurrence:

```python
remaining_budget = observed_catalog_budget_seconds
classifications = []
for rank, measurement in enumerate(full_urgency_ordered_measurements):
    remaining_positions = len(full_urgency_ordered_measurements) - rank
    fair_share_seconds = remaining_budget / remaining_positions
    classification = classify_probe(
        measurement, fair_share_seconds=fair_share_seconds
    )
    classifications.append(classification)
    consumed_seconds = min(
        measurement.measured_elapsed_seconds, fair_share_seconds
    )
    remaining_budget = max(0.0, remaining_budget - consumed_seconds)
```

`observed_catalog_budget_seconds` is read from the immutable `CatalogTrace`
field, whose value is `effective_catalog_deadline - production_start`. Only
omitted cap/deadline positions whose derived
`ProbeClassification.recoverable=True` contribute to the numerator.

- [ ] **Step 4: Calculate the literal evidence gate**

Set `proceed=true` only when at least three distinct lookahead-20/40 observations contain a recoverable omitted position and `recoverable_state_count / lookahead_20_40_state_count >= 0.05`. Store numerator, denominator, exact frequency, per-position fair shares, and manifest hash. Root-found omissions exceeding fair share remain diagnostic records but are not qualifying observations.

- [ ] **Step 5: Stop or continue**

If the gate fails, write `phase-0-report.md`, update `/progress.md` with the rejected hypothesis and evidence paths, mark the experiment rejected, and stop without creating either production package. If it passes, obtain Sol-high evidence review and continue to Task 3 without asking for an intermediate user confirmation.

---

### Task 3: Bootstrap Identical Standalone Control and Variant

**Files:**
- Create: `simulator/agents/exact_root_ems_mpc/*.py`
- Create: `simulator/agents/quota_fair_ems_mpc/*.py`
- Create: `simulator/tests/test_quota_fair_ems_mpc_packages.py`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-3-report.md`

**Interfaces:**
- Consumes: all production `.py` files from historical `simulator/agents/highscore/` without caches.
- Produces: `agents.exact_root_ems_mpc.agent.Agent` and `agents.quota_fair_ems_mpc.agent.Agent`, both internally configured with `use_mpc_mcts_ems=True`, `use_monotone_ingress=False`, and `use_geometry_rescue=False`.

- [ ] **Step 1: Write failing package-parity tests**

```python
def test_both_standalone_agents_activate_the_same_mpc_profile():
    control = ControlAgent("agents/exact_root_ems_mpc/")
    variant = VariantAgent("agents/quota_fair_ems_mpc/")
    assert control.settings.use_mpc_mcts_ems is True
    assert variant.settings == control.settings

def test_before_scheduler_edit_policy_and_root_keys_are_identical():
    assert control_root_keys(observation) == variant_root_keys(observation)
    assert normalized_action(control.policy(observation)) == normalized_action(variant.policy(observation))
```

Also compare SHA-256 for corresponding production files and require equality before Task 4.

- [ ] **Step 2: Verify RED**

```text
python -m unittest tests.test_quota_fair_ems_mpc_packages -v
```

Expected: package import failure.

- [ ] **Step 3: Copy production modules mechanically and activate MPC identically**

Copy only `.py` files, excluding `__pycache__`. Apply the same minimal settings/agent activation patch to the control, then mechanically copy the resulting files to the variant. Do not touch historical `highscore/`.

- [ ] **Step 4: Verify GREEN and byte parity**

```text
python -m unittest tests.test_quota_fair_ems_mpc_packages -v
python -m compileall -q agents/exact_root_ems_mpc agents/quota_fair_ems_mpc
```

Expected: imports, settings, roots, and fixed-observation actions match; all corresponding files have equal hashes.

- [ ] **Step 5: Report and Sol review**

Record hashes and tests. Sol-high must approve public-interface parity, identical activation, and historical immutability before Task 4.

---

### Task 4: Implement the Quota-Fair Catalog with TDD

**Files:**
- Modify only: `simulator/agents/quota_fair_ems_mpc/catalog.py`
- Create: `simulator/tests/test_quota_fair_ems_mpc_catalog.py`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-4-report.md`

**Interfaces:**
- Consumes: Task 3 standalone package and unchanged catalog dependencies.
- Preserves exactly the signature
  `build_root_catalog(state, pool, generator, settings, *, deadline) -> list[RootAction]`.
- Returns only exact-validated `RootAction` values whose proxy successor is
  non-null, sorted by the existing `_root_key`; empty input or expired deadline
  returns `[]`.

- Internal work model:

```python
@dataclass
class _CatalogWork:
    pool_index: int
    item: ItemSpec
    urgency: float
    proposals: tuple[ProxyAction, ...] = ()
    cursor: int = 0
    accepted_count: int = 0
    rarity: float = 0.0
```

The replacement body follows this complete algorithm; all time values are
absolute `time.perf_counter()` deadlines:

```text
start := time.perf_counter()
catalog_deadline := min(deadline,
                        start + max(0, settings.ems_root_budget_seconds))
if pool is empty or start >= catalog_deadline: return []

proxy_state := build_proxy_state(
    state, settings.path_clearance,
    support_inset=max(0, -settings.inclusion_margin),
    shelf_drop_gap=settings.shelf_drop_gap)
work := [_CatalogWork(pool_index, item,
         CandidateScorer.item_urgency(item, state.containers))
         for pool_index, item in enumerate(pool)]
sort work by (-urgency, item.index, pool_index)
records := []
seen := {work.pool_index: set() for work in work}

PROPOSAL_KEY(action):
    return (action.pool_index, action.container_index, action.orientation,
            tuple(float(x) for x in action.box.minimum),
            tuple(float(x) for x in action.box.maximum))

TAKE_ONE(work_record, turn_deadline):
    # returns (accepted_one, advanced_cursor)
    initial_cursor := work_record.cursor
    while work_record.cursor < len(work_record.proposals):
        now := time.perf_counter()
        if now >= turn_deadline or now >= catalog_deadline:
            return (false, work_record.cursor != initial_cursor)
        proposal := work_record.proposals[work_record.cursor]
        work_record.cursor += 1                 # advance before risky calls
        key := PROPOSAL_KEY(proposal)
        if key in seen[work_record.pool_index]: continue
        add key to seen[work_record.pool_index] # throwing/rejected key is consumed
        try:
            candidate := generator.validate_proposal(state, proposal)
            if candidate is None: continue
            successor := apply_action(proxy_state, proposal,
                                      settings.path_clearance)
        except Exception:
            if time.perf_counter() < min(turn_deadline, catalog_deadline):
                continue
            return (false, true)
        if successor is None: continue
        records.append((RootAction(candidate, proposal, successor),
                        work_record.urgency, work_record.rarity))
        work_record.accepted_count += 1
        return (true, true)
    return (false, work_record.cursor != initial_cursor)

# Pass 1: every urgency-ranked pool position receives one fair opportunity.
for rank, work_record in enumerate(work):
    now := time.perf_counter()
    if now >= catalog_deadline or len(records) >= settings.ems_root_catalog_limit:
        break
    remaining_records := len(work) - rank
    turn_deadline := now + (catalog_deadline - now) / remaining_records
    try:
        proposals := propose_actions(proxy_state, work_record.item,
                    work_record.pool_index,
                    limit=settings.ems_proxy_actions_per_item,
                    deadline=turn_deadline)
        work_record.proposals := tuple(proposals)
        work_record.rarity := 1.0 / max(1, len(work_record.proposals))
    except Exception:
        work_record.proposals := ()
        work_record.rarity := 1.0
        continue
    TAKE_ONE(work_record, turn_deadline)

# Pass 2: no proposal regeneration; one accepted root per active turn.
while time.perf_counter() < catalog_deadline \
      and len(records) < settings.ems_root_catalog_limit:
    active := [w for w in work
               if w.accepted_count < settings.ems_exact_roots_per_item
               and w.cursor < len(w.proposals)]
    if not active: break
    round_advanced := false
    for turn_index, work_record in enumerate(active):
        now := time.perf_counter()
        if now >= catalog_deadline \
           or len(records) >= settings.ems_root_catalog_limit: break
        remaining_turns := len(active) - turn_index
        turn_deadline := now + (catalog_deadline - now) / remaining_turns
        accepted_one, advanced_cursor := TAKE_ONE(work_record, turn_deadline)
        round_advanced := round_advanced or accepted_one or advanced_cursor
    if not round_advanced: break

ordered := sorted(records,
                  key=lambda record: _root_key(record[0],
                                                urgency=record[1],
                                                rarity=record[2]))
return [root for root, _, _ in
        ordered[:settings.ems_root_catalog_limit]]
```

No exception may discard an earlier `records` entry.

- [ ] **Step 1: RED for urgency order and first-root barrier**

Patch proposal/validator collaborators with literal action sequences. Assert proposal call order `(-urgency, item.index, pool_index)` and validation order `[A, B, C, A, B, C]`, never `[A, A, A, B, C]` before all reachable items receive pass-1 opportunity.

- [ ] **Step 2: Implement pass-1 scheduling minimally and verify GREEN**

Compute urgency once, stable-sort work records, allocate the remaining absolute time over remaining pass-1 records, call `propose_actions` once per record, and stop after the first unique exact root.

- [ ] **Step 3: RED/GREEN for cursor and exception semantics**

Assert: pre-pop expiry leaves cursor unchanged; post-pop increments before validation; rejected/duplicate/throwing proposals are not retried; exceptions continue only while the slice remains; accepted incumbents survive all failures.

- [ ] **Step 4: RED/GREEN for round-robin pass 2 and quotas**

Assert one accepted root per active record per round, per-item maximum six, global maximum 48, cached proposals only, and fair absolute turn slices.

- [ ] **Step 5: RED/GREEN for identity, deduplication, and determinism**

Use two pool positions with the same `item.index`. Deduplicate within a pool position by `(pool_index, container_index, orientation, exact AABB minimum, exact AABB maximum)`; repeated keys consume no quota. Assert proposal object identity reaches validator/apply and final ordering still uses the unchanged `_root_key`.

For every returned root in a real geometry fixture, call `generator.validate_proposal(state, root.proxy_action)` again and assert equality with `root.candidate`; call `apply_action(proxy_state, root.proxy_action, settings.path_clearance)` again and assert the successor is non-null. This test must fail if either exact guard is removed from catalog acceptance.

- [ ] **Step 6: Run focused and full regressions**

```text
python -m unittest tests.test_quota_fair_ems_mpc_catalog -v
python -m unittest tests.test_quota_fair_ems_mpc_catalog tests.test_highscore_catalog tests.test_highscore_ems tests.test_highscore_mcts -v
python -m unittest discover -s tests -p 'test_*.py' -v
python -m compileall -q agents/exact_root_ems_mpc agents/quota_fair_ems_mpc
```

- [ ] **Step 7: Source-scope audit, report, and Sol review**

Hash corresponding package files. Every file except `catalog.py` must match. The reviewer checks exact validation, deadlines, cursor semantics, duplicate identity, deterministic ordering, and incumbent preservation. Resolve all Critical/Important findings before Task 5.

---

### Task 5: Make the Physical Harness Package-Selectable

**Files:**
- Modify: `simulator/tests/run_physics_smoke.py`
- Create: `simulator/tests/quota_fair_benchmark_support.py`
- Create: `simulator/tests/test_quota_fair_benchmark_support.py`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-5-report.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class AgentBundle:
    Agent: type
    ItemSpec: type
    Planner: type
    build_packing_state: Callable

def load_agent_package(name: str) -> AgentBundle:
    module_root = {
        "highscore": "agents.highscore",
        "exact_root_ems_mpc": "agents.exact_root_ems_mpc",
        "quota_fair_ems_mpc": "agents.quota_fair_ems_mpc",
    }[name]
    return AgentBundle(
        Agent=import_module(f"{module_root}.agent").Agent,
        ItemSpec=import_module(f"{module_root}.model").ItemSpec,
        Planner=import_module(f"{module_root}.planner").Planner,
        build_packing_state=import_module(f"{module_root}.state").build_packing_state,
    )

def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]
```

`run_episode(*, agent_package: str, task: str, items: int, seed: int,
materialized_config: dict | None = None, materialized_config_sha256: str | None
= None) -> dict` loads the bundle through `load_agent_package`. When a
materialized config is supplied, it requires the supplied SHA-256, recomputes
the canonical `json.dumps(config, sort_keys=True, separators=(",", ":"))`
digest, rejects a mismatch, and passes a fresh `copy.deepcopy(config)` to the
environment. Otherwise it loads the named sample task. It executes the existing
`GroundHandlingEnv` loop without mutating standalone settings and returns this
exact JSON-compatible schema:

```text
{
  "schema_version": 1,
  "agent_package": str,
  "task": str,
  "items_requested": int,
  "seed": int,
  "materialized_config_sha256": str | null,
  "completed_steps": int,
  "actions": [action dictionaries with list-valued place_pos],
  "policy_elapsed_seconds": [float],
  "pre_action_valid": [bool],
  "step_status": [dict[str, bool]],
  "post_step_status": [dict[str, bool]],
  "final_status": dict[str, bool],
  "evaluation": {"fill_score": float, "num_placed_items": int},
  "proxy_mass_weighted_cog": float | null,
  "proxy_protection_violations": int,
  "proxy_mean_support_ratio": float | null
}
```

CLI additions:

```text
--agent-package {highscore,exact_root_ems_mpc,quota_fair_ems_mpc}
--seed INT
```

- [ ] **Step 1: Write RED tests for package loading and parser behavior**

Assert the default remains historical `highscore`; both standalone packages load by name; no path traversal or arbitrary module string is accepted; standalone agents receive no external MPC mutation; `--help` succeeds without importing PyBullet.

- [ ] **Step 2: Implement dynamic package loading and episode extraction**

Use a literal allow-list mapping package names to relative import roots. Move common loop behavior into `run_episode`. Preserve existing historical experimental flags only for `highscore`. Record action, policy elapsed time, pre-action validation, `env.step()` status, post-step/final status, completed steps, and `env.evaluate()`.

- [ ] **Step 3: Add explicitly labelled proxy metrics**

Record `proxy_mass_weighted_cog`, `proxy_protection_violations`, and `proxy_mean_support_ratio`; never use official component-score field names.

- [ ] **Step 4: Focused GREEN and 4/4 physical smoke**

```text
python -m unittest tests.run_physics_smoke.PhysicsSmokeCliTests tests.test_quota_fair_benchmark_support -v
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --agent-package exact_root_ems_mpc --task 000 --items 4 --seed 42'
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --agent-package quota_fair_ems_mpc --task 000 --items 4 --seed 42'
```

Expected: both return exit 0, 4 completed steps, and all status fields true. Stop on either failure.

- [ ] **Step 5: Report and Sol review**

Review must approve import safety, standalone activation, unchanged public API, status capture, proxy labels, and deferred PyBullet import.

---

### Task 6: Paired Coverage, Quality, Physics, and Timing Gate

**Files:**
- Create: `simulator/tests/run_quota_fair_ab.py`
- Extend with RED first: `simulator/tests/test_quota_fair_benchmark_support.py`
- Create raw evidence under: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/benchmarks/`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-6-report.md`

**Interfaces:**

```text
analyze_observation(bundle, observation, *, deadline) -> dict
run_paired_case(case, seed, *, control_first) -> dict
summarize_pairs(records) -> dict
```

`analyze_observation` rebuilds the package-local state, invokes that package's
exact catalog and scorer, runs a separate package-local `MCTSSearch`, and returns
the following diagnostics outside the timed production policy call:

```text
{
  "unique_pool_indices": [int], "root_count": int,
  "top1_secondary_score": float | null,
  "top5_mean_secondary_score": float | null,
  "per_item_best_secondary_score": dict[str, float],
  "selected_root_secondary_score": float | null,
  "mcts_root_visits": [int], "mcts_iterations": int,
  "timings": {"propose_actions_max": float, "validate_proposal_max": float,
              "apply_action_max": float, "catalog": float, "mcts": float}
}
```

`run_paired_case` requires `case["materialized_config"]` and
`case["materialized_config_sha256"]` for generated-manifest cases. It verifies
the digest once, passes independent deep copies and the same digest to both
`run_episode` calls, runs `exact_root_ems_mpc` then `quota_fair_ems_mpc` when
`control_first` is true, and reverses only the execution order otherwise. Its
returned keys are exactly `case_id`, `task`, `lookahead`, `seed`,
`materialized_config_sha256`, `control`, and `variant`, so labels and input
identity do not depend on execution order. Full-sample cases set the digest to
`null` and use the same task/items/seed parameters for both runs.

`summarize_pairs` first rejects an empty input. For every run, define
`first_false_step` as the first zero-based step whose `step_status` or
`post_step_status` contains `False`; use `completed_steps` when no false status
exists. A variant has an earlier safety failure exactly when its
`first_false_step` is smaller than the paired control value. Group full-sample
records by `case.task` and compute these exact fields:

```text
{
  "by_task": {
    task: {
      "control_median_completed_steps": median(control completed_steps),
      "variant_median_completed_steps": median(variant completed_steps),
      "mean_fill_delta": fmean(variant fill_score - control fill_score),
      "earlier_safety_failure": any paired earlier failure,
      "recoverable_coverage_delta": variant coverage - control coverage
    }
  },
  "generated": {
    "median_paired_step_delta": median(variant steps - control steps),
    "mean_fill_delta": fmean(variant fill - control fill),
    "high_lookahead_strict_improvement": bool
  },
  "timing": {"p50": float, "p95": float, "p99": float, "max": float,
             "internal_call_maxima": dict[str, float]},
  "any_earlier_safety_failure": bool
}
```

- [ ] **Step 1: RED/GREEN for paired aggregation**

Use literal records to prove median completed-step delta, mean fill delta, earlier-safety-failure detection, high-lookahead strict improvement, and p50/p95/p99/max calculations. The mutation each test catches is reversing control/variant subtraction or allowing one unsafe variant run.

- [ ] **Step 2: Implement shadow diagnostics outside timed policy**

Analyze root coverage, root-count distribution, overall top-1/top-5 mean secondary score, per-item best score, selected-root score, MCTS root visits/iterations, and per-call timings without adding the shadow-analysis time to the production policy measurement.

- [ ] **Step 3: Run five paired full-sample repetitions**

Run all 41 task000 and 42 task001 items with seeds `17,42,314,2026,8191`, alternating control-first and variant-first. Continue only to normal completion or first physical failure; do not truncate prefixes.

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_quota_fair_ab.py --phase full-samples --seeds 17,42,314,2026,8191 --output-dir ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/benchmarks/full'
```

- [ ] **Step 4: Run the fixed 16-template manifest**

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_quota_fair_ab.py --phase generated-manifest --seeds 17,42,2026 --output-dir ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/benchmarks/generated'
```

- [ ] **Step 5: Run the four-CPU timing profile**

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && taskset -c 0-3 env PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_quota_fair_ab.py --phase performance --warmup-calls 10 --policy-calls 200 --output-dir ../.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/benchmarks/performance'
```

- [ ] **Step 6: Apply the preliminary empirical gates literally**

Continue to staged ZIP audit only if:

```text
each task variant median completed_steps >= control median
each task mean fill delta >= -0.25
no paired variant safety status becomes false earlier
at least one task: median steps improves OR mean fill delta >= 0.50 OR recoverable coverage improves
generated aggregate median step delta >= 0
generated aggregate mean fill delta >= -0.25
at least one high-lookahead template strictly improves
unique pool-index root coverage is non-decreasing on every measured snapshot
policy p99 < 5.5 seconds
policy maximum < 6.0 seconds
maximum propose_actions, validate_proposal, apply_action, catalog, and MCTS call < 5.5 seconds
all unit, compile, parity, determinism, and API checks pass
```

If any line fails, mark the variant rejected, update `/progress.md`, preserve raw evidence, and do not create staged or final archives. If all lines pass, record status `empirically-qualified` rather than `adopted` and continue to Task 7.

- [ ] **Step 7: Report and final Sol-high algorithm review**

The reviewer receives the approved spec, plan, all task reports, source diff between standalone packages, benchmark summary, and failed/passed gates. Resolve any Critical/Important code finding; a failed empirical gate is not repaired by changing its threshold.

---

### Task 7: Staged ZIP Audit and Final Adoption

**Files:**
- Create: `simulator/tests/verify_quota_fair_archives.py`
- Create: `simulator/tests/test_quota_fair_archive_verifier.py`
- Create unique staging archives under: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/staging/<audit-id>/`
- Create on final adoption: `simulator/submissions/exact-root-ems-mpc_YYYYMMDD-HHMM.zip`
- Create on final adoption: `simulator/submissions/quota-fair-ems-mpc_YYYYMMDD-HHMM.zip`
- Create on final adoption: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/adopted-artifacts.json`
- Modify: `/progress.md`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-7-report.md`

**Interfaces:**
- Consumes: adopted Task 6 source trees and raw evidence.
- Produces: audited staging archives, then immutable SHA-256-addressed standalone control/variant archives only after every gate passes.

- [ ] **Step 1: RED/GREEN the archive verifier**

Create literal good and bad ZIP fixtures. Tests must reject: an extra top-level
entry, a missing package file, `.pyc`/`__pycache__`, an import failure, inactive
MPC settings, wrong catalog invocation, a fixed-observation action differing
from the source tree, and any corresponding production-file difference other
than `catalog.py`. Tests must accept two minimal valid archives and write this
schema atomically:

```text
{
  "schema_version": 1, "audit_id": str,
  "control_zip": {"path": absolute str, "sha256": str, "entries": [str]},
  "variant_zip": {"path": absolute str, "sha256": str, "entries": [str]},
  "checks": {"entry_layout": true, "compile": true, "import": true,
             "mpc_active": true, "catalog_invocation": true,
             "fixed_choice_reproduction": true,
             "only_catalog_source_differs": true},
  "passed": true
}
```

Run RED before implementation and GREEN after it:

```text
python -m unittest tests.test_quota_fair_archive_verifier -v
python -m compileall -q tests/verify_quota_fair_archives.py
```

- [ ] **Step 2: Build clean staging archives before final adoption**

Each ZIP contains exactly one top-level directory matching its package name and only production `.py` files. Exclude tests, `__pycache__`, `.pyc`, snapshots, dependencies, and reports.

From project-root PowerShell, with the two agent source directories first verified by `Resolve-Path` to be under `simulator/agents/`, run:

```powershell
$auditId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$stage = Join-Path '.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/staging' $auditId
if (Test-Path -LiteralPath $stage) { throw "Refusing to reuse staging path: $stage" }
New-Item -ItemType Directory -Path $stage | Out-Null
$controlFiles = Get-ChildItem -LiteralPath 'simulator/agents/exact_root_ems_mpc' -File -Filter '*.py'
$variantFiles = Get-ChildItem -LiteralPath 'simulator/agents/quota_fair_ems_mpc' -File -Filter '*.py'
$controlInput = "$stage/input-control/exact_root_ems_mpc"
$variantInput = "$stage/input-variant/quota_fair_ems_mpc"
New-Item -ItemType Directory -Force -Path $controlInput,$variantInput | Out-Null
Copy-Item -LiteralPath $controlFiles.FullName -Destination $controlInput
Copy-Item -LiteralPath $variantFiles.FullName -Destination $variantInput
Compress-Archive -Path $controlInput -DestinationPath "$stage/exact-root-ems-mpc.zip"
Compress-Archive -Path $variantInput -DestinationPath "$stage/quota-fair-ems-mpc.zip"
```

The unique `$stage` path is recorded in `task-7-report.md` and is never reused.

- [ ] **Step 3: Audit both ZIPs from unique extraction directories**

The verifier creates new UUID-named extraction directories beneath `$stage`,
never uses `-Force`, and executes all entry, import, compile, activation,
catalog-invocation, fixed-choice, and source-diff assertions. Run:

```powershell
$python = 'C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $python 'simulator/tests/verify_quota_fair_archives.py' `
  --audit-id $auditId `
  --control-zip "$stage/exact-root-ems-mpc.zip" `
  --variant-zip "$stage/quota-fair-ems-mpc.zip" `
  --source-control 'simulator/agents/exact_root_ems_mpc' `
  --source-variant 'simulator/agents/quota_fair_ems_mpc' `
  --output "$stage/archive-audit.json"
if ($LASTEXITCODE -ne 0) { throw 'Archive audit failed' }
$audit = Get-Content -LiteralPath "$stage/archive-audit.json" -Raw | ConvertFrom-Json
if (-not $audit.passed) { throw 'Archive audit did not pass every check' }
```

The fixed-choice assertion uses the same serialized observation for source and
extracted packages, validates both returned actions with their package-local
exact validator, and compares item/container/orientation plus float64 position
coordinates exactly. The catalog-invocation assertion wraps the extracted
package's `planner.build_root_catalog`, calls policy once, and requires one or
more calls. The source-diff assertion compares the complete `.py` basename set
and SHA-256 for every corresponding file, allowing unequal hashes only for
`catalog.py`.

- [ ] **Step 4: Apply the final adoption decision**

Adopt only when Task 6 status is `empirically-qualified` and both staged archives pass entry-layout, extracted import, no-flag MPC activation, catalog invocation, fixed-choice reproduction, compile, and source-diff checks. A failed archive audit rejects the variant; it does not relax Task 6 thresholds.

- [ ] **Step 5: Copy adopted immutable archives and record hashes**

Resolve timestamp once with `Get-Date -Format yyyyMMdd-HHmm`, copy the two audited staging archives to `simulator/submissions/exact-root-ems-mpc_<timestamp>.zip` and `simulator/submissions/quota-fair-ems-mpc_<timestamp>.zip`, and calculate SHA-256 with `Get-FileHash -Algorithm SHA256`. Write `adopted-artifacts.json` atomically with absolute `control.path`, `control.sha256`, `variant.path`, and `variant.sha256` fields.

Update `/progress.md` with names, methods, hashes, full local gates, and status `ready-not-submitted`. Do not infer unavailable SIGNATE component metrics.

- [ ] **Step 6: Report and final Sol-high package review**

The reviewer receives archive entry listings, extracted smoke output, source hashes, Task 6 gates, and `progress.md` diff. Resolve all Critical/Important findings before Task 8.

---

### Task 8: Controlled Paired SIGNATE Submission

**Files:**
- Modify: `/progress.md`
- Report: `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-8-report.md`

**Interfaces:**
- Consumes: exact adopted archive paths and hashes from Task 7.
- Produces: paired submissions to task key `54eb698257344d638111c73d49664ddb` or an explicit authentication blocker.

- [ ] **Step 1: Check project-local CLI authentication without exposing secrets**

```powershell
& '.\simulator\.signate_venv\Scripts\signate.exe' competition-list
```

If this returns HTTP 401, stop and ask the user to run the following from `C:\Users\TAKUMI\projects\Baggage-Loading`, entering the email and password interactively:

```powershell
$signateEmail = Read-Host 'SIGNATE email'
& '.\simulator\.signate_venv\Scripts\signate.exe' token -e $signateEmail
```

- [ ] **Step 2: Submit control first and variant second**

Load the exact archive paths recorded in Task 7 and run:

```powershell
$artifacts = Get-Content -LiteralPath '.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/adopted-artifacts.json' -Raw | ConvertFrom-Json
& '.\simulator\.signate_venv\Scripts\signate.exe' submit --task_key '54eb698257344d638111c73d49664ddb' --path $artifacts.control.path --memo 'Exact-Root EMS MPC control; standalone MPC; control for quota-fair catalog scheduling'
& '.\simulator\.signate_venv\Scripts\signate.exe' submit --task_key '54eb698257344d638111c73d49664ddb' --path $artifacts.variant.path --memo 'Quota-Fair EMS MPC; only catalog item scheduling differs from paired control'
```

- [ ] **Step 3: Record submission receipts and authoritative Public totals**

Update `/progress.md` with submission status and the browser-visible Public aggregate scores supplied by SIGNATE or the user. Do not claim completion unless the variant Public score is at least 60.
