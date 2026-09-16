# Root Fair Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure online beam search gives every one of the pre-ranked root pool items a fair share of the soft deadline, so one expensive candidate search cannot prevent comparison across the pool.

**Architecture:** Keep the existing candidate generator and hard safety checks unchanged. In `Planner.choose_online`, divide the remaining root-level deadline among the remaining ranked root items; deeper beam levels continue using the global deadline. This preserves the six-item/four-or-eight-placement search contract while making the first decision less dependent on which item happens to consume the clock first.

**Tech Stack:** Python 3.12, standard library, NumPy, `unittest`.

## Global Constraints

- Do not add dependencies.
- Do not change the public `Agent` API or action dictionary.
- Do not relax official inclusion, path-clearance, support-centre, or protection constraints.
- Keep the global policy hard deadline as the final safety cutoff.
- The workspace is not a Git repository; do not initialize Git or commit.

---

### Task 1: Fair Root-Level Deadline Allocation

**Files:**
- Modify: `simulator/agents/highscore/planner.py`
- Modify: `simulator/tests/test_highscore_planner.py`
- Report: `docs/superpowers/plans/2026-08-13-root-fair-search-report.md`

**Interfaces:**
- Consumes: `Planner.choose_online(state, pool, *, deadline) -> Candidate | None`
- Produces: unchanged interface; root calls to `_top_candidates` receive monotonically increasing per-item deadlines ending at the global deadline.

- [ ] **Step 1: Write the failing test**

Add a `PlannerTests` test using `unittest.mock.patch` on `agents.highscore.planner.time.perf_counter`. Replace `planner.generator` with a fake whose `generate(...)` records each item index, advances the fake clock to the supplied deadline, returns no candidates for the first five ranked items, and returns one valid `Candidate` for the sixth. Use six items with dimensions chosen so `_rank_items` has a deterministic order. Assert all six root items were attempted and the returned candidate is the sixth attempted item.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest simulator.tests.test_highscore_planner.PlannerTests.test_online_planner_fairly_checks_all_ranked_root_items
```

Expected: FAIL because the current planner gives the first generator call the entire global deadline and never reaches the sixth root item.

- [ ] **Step 3: Implement the minimal root deadline allocator**

In root depth only, before each ranked item call, calculate:

```python
remaining_choices = len(item_choices) - choice_offset
now = time.perf_counter()
item_deadline = now + max(0.0, deadline - now) / max(1, remaining_choices)
```

Pass `item_deadline` to `_top_candidates`. At deeper depths, pass the original global `deadline`. Do not change candidate validation, ranking keys, beam widths, or emergency fallback.

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
python -m unittest simulator.tests.test_highscore_planner.PlannerTests.test_online_planner_fairly_checks_all_ranked_root_items -v
python -m unittest discover -s simulator/tests -p 'test_*.py' -v
```

Expected: PASS.

- [ ] **Step 5: Write the report**

Record RED and GREEN command outputs, files changed, exact behavioral change, self-review, and concerns in the report file. Do not commit.
