# Two-Choice Root Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare two high-priority pool items online without starving candidate quality, while keeping the normal policy path below two seconds.

**Architecture:** At online beam depth zero only, rank two items and divide a 1.8-second soft budget equally over the remaining root choices. Deeper beam expansion keeps the global deadline. Candidate geometry and safety remain unchanged. This is an empirical one-factor experiment and must be reverted if the 30-item task001 benchmark does not exceed the accepted 20-safe-placement baseline.

**Tech Stack:** Python 3.12, standard library, NumPy, `unittest`.

## Global Constraints

- No new dependencies and no Git initialization or commits.
- Keep the public Agent API and action shape unchanged.
- Do not alter candidate validation or safety thresholds.
- `policy_hard_limit_seconds` remains 5.75 seconds.
- Root comparison count is exactly 2; `policy_soft_limit_seconds` is exactly 1.8 seconds.

---

### Task 1: Two-Choice Root Budget

**Files:**
- Modify: `simulator/agents/highscore/settings.py`
- Modify: `simulator/agents/highscore/planner.py`
- Modify: `simulator/tests/test_highscore_planner.py`
- Report: `docs/superpowers/plans/2026-08-13-two-choice-root-search-report.md`

**Interfaces:**
- Add `SearchSettings.online_root_item_choices: int = 2`.
- Keep `Planner.choose_online(...) -> Candidate | None` unchanged.

- [ ] Add a failing fake-clock test proving the old code tries one root item when that generator consumes the supplied deadline, while the desired code tries exactly two and can return the second candidate.
- [ ] Run the focused test and record expected RED.
- [ ] Set `policy_soft_limit_seconds=1.8`, use exactly `online_root_item_choices` ranked items at root, and allocate the remaining root deadline over the remaining root choices. Do not apply this limit/allocation below depth zero.
- [ ] Run the focused test and all `unittest` tests; record GREEN.
- [ ] Write the report with exact changes, RED/GREEN evidence, self-review, and concerns. Do not commit.
