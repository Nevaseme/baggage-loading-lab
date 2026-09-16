# Offline Complete Skeleton Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent offline optimization from replacing the input order with an order whose simulated placement skeleton is incomplete.

**Architecture:** Keep the offline beam search unchanged. At the `Agent.optimize` output boundary, accept its order only when it is a complete permutation and its safety-validated skeleton contains one candidate for every input item; otherwise clear the stored skeleton and return the original input order. This turns an incomplete timeout result into the simulator's known-safe default ordering rather than appending an unvalidated urgency tail.

**Tech Stack:** Python 3.12, standard library, NumPy, `unittest`.

## Global Constraints

- No new dependencies, Git initialization, or commits.
- Keep the public Agent API and return types unchanged.
- Do not change candidate geometry, safety constraints, or online policy behavior.
- A complete optimized skeleton has exactly `len(item_list)` candidates.
- Incomplete skeletons must return the exact original input index order and leave `offline_skeleton == []`.

---

### Task 1: Guard Incomplete Offline Search Results

**Files:**
- Modify: `simulator/agents/highscore/agent.py`
- Modify: `simulator/tests/test_highscore_planner.py`
- Report: `docs/superpowers/plans/2026-08-13-offline-complete-skeleton-guard-report.md`

**Interfaces:**
- Consumes: `Planner.optimize_order(...) -> tuple[list[int], list[Candidate]]`.
- Produces: unchanged `Agent.optimize(item_list) -> list[int]`.

- [ ] Add a failing test replacing `agent.planner` with a fake that returns a valid non-original permutation plus an incomplete skeleton; assert `optimize` returns the original index order and clears `offline_skeleton`.
- [ ] Add a companion test where the fake returns the same permutation plus a full-length skeleton; assert the optimized permutation and skeleton are accepted.
- [ ] Run the focused tests and record RED from the incomplete case.
- [ ] Change the existing acceptance condition in `Agent.optimize` to require both a valid complete permutation and `len(skeleton) == len(items)`; otherwise clear `offline_skeleton` and return the original order.
- [ ] Run focused tests and the full unittest suite; record GREEN.
- [ ] Write the report with RED/GREEN output, files, exact behavior, self-review, and concerns. Do not commit.
