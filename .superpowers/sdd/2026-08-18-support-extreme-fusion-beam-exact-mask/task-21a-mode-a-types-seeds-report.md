# Task 21a — Mode-A Immutable Types and Historical Static Seed

Date: 2026-08-19

## Outcome

Implemented the foundation for the algorithm umbrella
`layered_proxy_order_beam_exact_skeleton_repair` without integrating the
public Agent or any search policy.

The new modules provide:

- duplicate-safe immutable offline occurrence identities;
- receipt-free immutable skeleton intents;
- bounded typed optimization traces;
- canonical profile-bound complete plan digests;
- a fail-closed finalizer that returns original occurrence order plus `None`
  for every incomplete or invalid candidate;
- an independent local port of the historical static order seed.

No Agent, Catalog, ExactMask, settings, public action, physics, Git, package
installation, or historical artifact was modified.

## Occurrence boundary

`OfflineOccurrence` contains exact non-negative `original_position`, public
`item_index`, canonical immutable full `_item_signature`, and a duplicate
ordinal. The builder counts duplicates by the complete signature rather than
the public item index. Equal IDs with unequal mass/dimensions/protection or
container binding start independent ordinal sequences; equal complete
signatures retain distinct original positions and increasing ordinals.
Authoritative occurrence tuples must be in exact dense position order
`0..n-1`; ordinals are revalidated as the sequential count of each full
signature, so a caller cannot forge a gap, duplicate, or reordered identity.

The canonical signature accepts only the exact eight scalar fields used by the
current model. Lists, dictionaries, NumPy arrays/scalars, placement proposals,
validated-root objects, and other nested values cannot enter it.

## Skeleton and plan boundary

`SkeletonIntent` stores only:

- one exact occurrence;
- container ordinal and official orientation;
- an exact immutable three-float local position;
- validated `SupportKind`;
- an exact tuple of unique supporter occurrences;
- alternative count and finite margins.

It contains no proposal, validation receipt, NumPy alias, or raw action.

A publishable `ModeAPlan` requires:

- unique authoritative occurrences;
- an occurrence-position order with exactly the same multiset;
- exactly one skeleton intent per occurrence;
- each intent and supporter matching the full authoritative stable identity at
  its position, not merely the integer position;
- a complete non-fallback trace;
- the current descriptive profile version;
- a recomputed matching SHA-256 digest over semantic profile, occurrences,
  order, and skeleton stable keys. Execution trace and wall-clock time are
  deliberately excluded from the semantic plan digest.

`finalize_mode_a_plan` catches every invalid/incomplete candidate and returns
the original occurrence-position order with no plan. It never publishes a
partial skeleton with a changed order.

## Historical seed port

The only mechanics read from the historical 29.7 artifact were
`_static_order_key` at its lines 689–699. They were reimplemented locally as:

```text
protection group (normal, priority, soft)
-mass
-maximum pairwise footprint
-volume
-largest dimension
public item index
original occurrence position
```

The final occurrence-position term is the only added tie-break and prevents
equal IDs/signatures from collapsing or relying on object identity. The new
module imports no historical, highscore, EMS, MCTS, beam, or fixed-quota code.

## TDD evidence

### Review-fix RED

The review regressions were added before the fixes. The focused run produced
11 expected failures: forged intent/supporter identities and duplicate
ordinals were accepted, noncanonical authoritative sequences were accepted,
and different elapsed times changed the plan digest. These failures directly
covered both review findings.

### RED

Tests were written first and executed before either production module existed:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_mode_a_types_seeds
```

Expected result: `ModuleNotFoundError` for `mode_a_seeds`; one import error.

### Focused GREEN

```text
Ran 17 tests in 0.028s
OK
```

The focused suite covers exact ints versus bools, finite exact floats, tuple
and enum boundaries, deep immutability, source-copy mutation, duplicate IDs
and signatures, duplicate ordinals, 40-of-41 and duplicate omission, partial
skeleton rejection, fallback finalization, nested receipt/proposal/action/
NumPy rejection, digest recomputation, 20-run determinism, historical golden
order, duplicate-safe seed order, forged identity/ordinal rejection, semantic
digest invariance to elapsed time, and forbidden-import AST inspection.

### Related GREEN

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_mode_a_types_seeds \
  simulator.tests.test_support_extreme_fusion_contract \
  simulator.tests.test_support_extreme_fusion_transition
```

```text
Ran 45 tests in 0.304s
OK
```

An earlier command named a nonexistent `test_support_extreme_fusion_foundation`
module and therefore produced one loader error. No production failure was
hidden; the corrected explicit existing contract/transition suite above is the
reported related gate.

### Fresh full GREEN

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -t simulator -p 'test_*.py'
```

```text
Ran 478 tests in 27.294s
OK
```

`py_compile` completed with exit code 0 for both new production modules and
the focused test module.

## Files

- `simulator/agents/support_extreme_fusion_beam_exact_mask/mode_a_types.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/mode_a_seeds.py`
- `simulator/tests/test_support_extreme_fusion_mode_a_types_seeds.py`
- `docs/superpowers/plans/2026-08-18-layered-maxrects-regret-exact-mask.md`
- this report

## Self-review

- All public plan containers are frozen and contain exact immutable tuples and
  scalar values only.
- Duplicate identity is full-signature-based and occurrence-position-safe.
- Digest material is deterministic, finite, JSON-canonical, and profile-bound.
- Direct `ModeAPlan` construction and the finalizer enforce the same complete
  plan invariants.
- Historical mechanics are independently implemented and golden-tested; the
  new source has no historical import.
- This task does not claim a usable Mode-A Agent, physical placement, or score
  improvement. Those remain later Task 21 stages.
