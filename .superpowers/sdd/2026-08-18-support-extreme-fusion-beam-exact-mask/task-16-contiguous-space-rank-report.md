# Task 16 — contiguous-space rank for `fixed_quota_exact_two_ply`

## Outcome

Changed one factor only: the lexicographic secondary order inside
`FixedQuotaExactTwoPly._rank`.  Candidate generation, initial catalog, fixed
work quotas, admission caps, exact transitions, Agent, runner, and the legacy
Beam are unchanged.

The exact descending precedence is now:

1. proven placement count;
2. proven volume;
3. future covered item count;
4. future covered volume;
5. root robustness;
6. selected-item scarcity urgency;
7. protection-compatible support capacity;
8. ingress access;
9. largest contiguous free support;
10. negative sliver area;
11. total compatible support capacity;
12. low mass-weighted CoG goodness;
13. support margin;
14. clearance margin; and
15. low-stack goodness.

Ascending stable sequence key remains the deterministic final tie break.

This moves total compatible support below contiguous-space quality.  A tiny
increase in aggregate support area can no longer dominate a much larger
single usable rectangle.  Protection and ingress deliberately remain above
contiguous space.

## TDD evidence

The initial RED reproduced both old-order failures:

- total support `0.91` / largest rectangle `0.20` incorrectly beat total
  support `0.90` / largest rectangle `0.70`; and
- total support `1.0` / sliver `0.20` incorrectly beat total support `0.10` /
  sliver `0.10`.

After the rank-only change, focused fixtures prove:

- largest contiguous support precedes a tiny total-support gain;
- protection precedes ingress/largest, and ingress precedes largest;
- proven volume, future item/volume coverage, robustness, and scarcity retain
  their earlier precedence;
- lower sliver precedes total compatible support;
- total support still resolves a tie after sliver;
- stable keys resolve a complete feature tie; and
- the chosen action remains the original caller-owned strict root while a
  separate fresh mask call issues matching authorization evidence.

The existing synthetic dead-end fixture continues to prove that an exact
two-placement branch beats a larger local one-placement branch, preserving
the primary count-before-volume objective.

## Optional task001 initial replay

A read-only analytical replay was run, but the proposed back-root assertion
was not added because its premise was false under the mandated ordering:

```text
center y=0.000: protection capacity 0.553222, ingress 1.0, largest 0.477020
back   y=0.477: protection capacity 0.552696, ingress 1.0, largest 0.677465
```

Because protection must precede largest contiguous support, the specified
rank correctly retains the center root.  Forcing the back root would require a
second experimental factor (moving or redefining protection capacity), so it
was not done in this task.

## Fresh verification

Project-local WSL runtime:

```text
fixed-quota focused: 12 tests, PASS, 0.641s
full simulator suite: 349 tests, PASS, 10.910s
independent Sol review: APPROVE, no Critical/Important finding
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -q
```

## Files changed

- `simulator/agents/support_extreme_fusion_beam_exact_mask/fixed_quota.py`
- `simulator/tests/test_support_extreme_fusion_fixed_quota.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-16-contiguous-space-rank-report.md`

No physics episode, dependency installation, Git operation, strict-profile
change, or production-default switch occurred.
