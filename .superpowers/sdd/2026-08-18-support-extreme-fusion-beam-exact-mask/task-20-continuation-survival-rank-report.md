# Task 20 — Memoized Stratified Continuation-Survival Rank

Date: 2026-08-19

## Outcome

Implemented the diagnostic algorithm variant
`memoized_stratified_continuation_survival_rank` as a single ranking-evidence
factor over the existing Task 19 executor.

The legacy objective remains the default and retains its original rank and
streaming-incumbent path. The new objective is enabled only by the explicit
mode-B stratified runner route with
`--b-rank-objective continuation-survival`.

No Catalog, ExactMask, proposal, public Agent, action formatter, candidate
coordinate, local-cost, regret-order, or quota behavior changed. No PyBullet,
SIGNATE, Git, package installation, or global environment mutation was used.

## Root cause addressed

The previous streaming selector could place a newly committed but unanalysed
child into `best_by_lineage`. Because the legacy rank starts with placed count
and volume, that child could replace an analysed parent despite carrying zero
continuation fields only because no audit had run yet. In addition, occurrences
with zero exposed options were absent from `minimum_nonzero_options`.

The new objective separates expansion from publication:

- every remaining occurrence contributes an audit result, including zero;
- interrupted or exceptional occurrence analysis is unknown/incomplete;
- children may be committed and expanded, but no depth cohort is published
  unless every node in the cohort has a complete occurrence audit;
- a partial cohort never changes the returned exact root order;
- the returned values remain original current-catalog `ValidatedRoot` objects.

## Implementation

### Typed objective and audit

`RankObjective` contains:

- `LEGACY`
- `CERTIFIED_CONTINUATION_SURVIVAL`

`ContinuationAudit` is frozen and records:

- total and audited occurrence counts;
- option and zero-option occurrence counts;
- option volume counted once per occurrence;
- minimum options across all audited occurrences, including zero;
- exact completion state.

Its constructor rejects negative/inconsistent counts, non-finite volume, and a
completion flag inconsistent with audited coverage.

### Certified rank

For a complete audit, the exact descending rank prefix is:

```text
placed_count + option_occurrences
terminal ? 2 : min(2, minimum_options_all)
placed_volume + option_volume
placed_count
placed_volume
```

It then uses the unchanged material protection bucket, ingress access, largest
free region, negative sliver area, low CoG, low stack, depth-zero support and
clearance margins, and cumulative backness. Stable sequence ordering remains
the deterministic final tie-break.

An incomplete or absent audit has no publishable survival rank. The selector
keeps the last completely audited cohort, with the freshly applied depth-zero
catalog roots as the fail-closed initial incumbent.

### Runner isolation

The runner adds:

```text
--b-rank-objective legacy|continuation-survival
```

The top-level requested objective and requested/effective/enabled settings are
recorded separately. The objective is effective only when both requested and
resolved mode are B and the planner is
`memoized-stratified-maxrects-regret`. A/C/auto and every other B planner record
effective `legacy`, even if survival was requested. The existing exact final
formatter remains the only public-action path.

## TDD evidence

### RED 1 — selector contract

Before production implementation:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_continuation_survival
```

Result: expected import failure because `ContinuationAudit` did not exist.

### RED 2 — runner contract

After the selector API was green but before runner implementation:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_continuation_runner
```

Result: expected import failure because `_b_rank_objective_settings` did not
exist.

### Focused GREEN

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_continuation_runner \
  simulator.tests.test_support_extreme_fusion_continuation_survival
```

```text
Ran 15 tests in 4.609s
OK
```

The tests cover `[3, 0, 2]` option counts, zero-option inclusion, exception and
quota unknown state, robustness saturation, exact count/volume prefix,
shallower survival over a deeper low-recall child, unanalysed-child exclusion,
partial-cohort order invariance, exact-root identity/fresh authorization,
20-run determinism, unchanged work/exposure evidence, legacy equivalence, CLI,
route isolation, and truthful result metadata.

### Related GREEN

```text
Ran 97 tests in 13.490s
OK
```

This combined MaxRects, memoized streaming, Task 19 stratified exposure,
physics-runner unit tests, and both Task 20 modules.

### Fresh full GREEN

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -t simulator -p 'test_*.py'
```

```text
Ran 461 tests in 27.108s
OK
```

`py_compile` completed with exit code 0 for the changed production module,
runner, and both new test modules.

## Files

- `simulator/agents/support_extreme_fusion_beam_exact_mask/maxrects_regret.py`
- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_support_extreme_fusion_continuation_survival.py`
- `simulator/tests/test_support_extreme_fusion_continuation_runner.py`
- `docs/superpowers/plans/2026-08-18-layered-maxrects-regret-exact-mask.md`
- this report

## Self-review

- Legacy remains the constructor default and follows the unchanged rank and
  `best_by_lineage` update path.
- Survival audit counts each occurrence at most once; candidate multiplicity
  cannot inflate option occurrence count or volume.
- Zero candidates are evidence only when an occurrence call completes;
  exceptions and pre-occurrence quota/deadline stops remain unknown.
- Publication is cohort-atomic. Partial analysis and unanalysed committed
  children cannot alter the returned incumbent.
- Proxy states remain analytical. Only original depth-zero strict roots leave
  the selector, and the Agent's fresh exact formatter remains mandatory.
- This report makes no physical-safety improvement or Public-score claim.
