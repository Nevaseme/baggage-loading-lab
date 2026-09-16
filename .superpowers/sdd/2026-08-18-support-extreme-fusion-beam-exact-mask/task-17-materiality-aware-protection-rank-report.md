# Task 17 — materiality-aware protection rank

## Outcome

Changed one factor in `FixedQuotaExactTwoPly`: protection-compatible capacity
now has a configurable materiality threshold before topology is compared.
The default is one percentage point:

```python
protection_materiality = 0.01
bucket = floor((protection_compatible_capacity + 1e-12) / 0.01)
```

The constructor rejects zero, negative, non-finite, boolean, and nonnumeric
materiality values.  This is a planner-only field and does not alter the strict
receipt profile.

## Exact rank order

Descending comparison is now:

1. proven count;
2. proven volume;
3. future covered item count;
4. future covered volume;
5. root robustness;
6. scarcity urgency;
7. material protection bucket;
8. ingress access;
9. largest contiguous free support;
10. negative sliver area;
11. exact protection-compatible capacity;
12. total compatible support capacity;
13. low mass-weighted CoG goodness;
14. support margin;
15. clearance margin; and
16. low-stack goodness.

Ascending stable sequence key remains the final deterministic tie break.

Protection differences of at least one bucket therefore dominate topology.
Sub-material differences within the same bucket defer to ingress, contiguous
space, and sliver.  Exact protection then breaks a remaining topology tie.
Hard priority/soft protection validation in `ExactMask` is unchanged.

## TDD evidence

Initial RED results reproduced the intended distinction:

- center protection `0.553222`, largest `0.477020` incorrectly beat back
  protection `0.552696`, largest `0.677465`;
- rank component 6 exposed raw `0.599999` instead of material bucket `59`; and
- the real task001 initial replay still chose `y=0.0`.

After the rank-only change:

- the measured center/back pair shares bucket 55 and the back root wins;
- protection `0.56` beats `0.55` even when the latter has much better largest
  space;
- the `0.599999`/`0.60` boundary deterministically produces buckets 59/60;
- exact protection wins after ingress/largest/sliver ties and before total
  compatible support;
- all earlier count/volume/coverage/robustness/scarcity tiers and stable ties
  remain intact; and
- original strict root identity plus independently fresh matching
  authorization remain intact.

The read-only task001 initial analytical replay uses the actual staged scanner,
fixed quota planner, and exact mask.  It selects the same item occurrence
(`pool_index=2`) at back `y≈0.477` and a fresh final exact-mask call issues a
matching receipt.

## Fresh verification

Project-local WSL runtime:

```text
fixed-quota focused: 17 tests, PASS, 1.998s
full simulator suite: 354 tests, PASS, 12.424s
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
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-17-materiality-aware-protection-rank-report.md`

No candidate generation, work quota, catalog, exact mask, feature definition,
Agent, runner, physics episode, dependency installation, Git operation, or
production-default switch changed.
