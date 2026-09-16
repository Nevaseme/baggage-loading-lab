# Task 21c — Strict Virtual Skeleton Compiler

Date: 2026-08-19

## Outcome

Implemented the Mode-A strict virtual skeleton compiler in
`simulator/agents/support_extreme_fusion_beam_exact_mask/mode_a_exact_compile.py`.
It is deliberately not connected to `Agent.optimize` yet.

The compiler accepts only a complete authoritative `ProxyOrderCandidate`.
For each occurrence in its full permutation it rebuilds a singleton current
pool, proposes at most six intent/rebased placements, also obtains normal-family
fixed-work strict roots, and advances a cloned virtual packing state only via
`apply_root(..., exact_revalidator=ExactMask)`. The returned `ModeAPlan` contains
no `ValidatedRoot`, `PlacementProposal`, receipt token, action dictionary, or
NumPy alias.

## Exact boundary and work contract

- Canonical raw occurrences and full signatures must exactly match the input.
- Duplicate item IDs/signatures remain distinct by original occurrence
  position.
- Advisory roots are current-state `ExactMask.validate` results and are capped
  at six proposals per occurrence.
- The repair scan uses `CatalogWorkQuota(per_pool_raw_limit=128,
  global_exact_attempt_cap=64)` with dense, deferred, and rescue disabled.
- Every chosen root is passed to `apply_root`, which requires a separate fresh
  matching exact receipt before cloning and placement.
- Root receipts and transition objects never enter the compiled skeleton.
- Remaining time is split fairly across uncompiled steps. A hard-deadline
  crossing after scanning, during application, or before finalization discards
  the entire result.
- Any partial candidate, forged occurrence identity, scanner exception, stale
  root, or incomplete compilation returns `None`.

The selected-root order is deterministic: planned position distance first,
then suffix alternatives/margins, current exact support/clearance, and the
stable proposal key.

## TDD evidence

Initial RED:

```text
python -m unittest simulator.tests.test_support_extreme_fusion_mode_a_exact_compile
ImportError: No module named
agents.support_extreme_fusion_beam_exact_mask.mode_a_exact_compile
```

The focused suite covers:

- real three-item full compilation and digest recomputation;
- singleton binding for duplicate occurrences;
- rejected advisory repair through the normal strict scanner;
- floor/support Z rebasing;
- six-advisory and 64-exact scan caps;
- fresh selected-root revalidation and parent-state immutability;
- later-step scanning against the freshly applied child collision state;
- scanner-return deadline crossing;
- partial/forged candidate rejection;
- immediate timeout and scanner exception fail-closed behavior;
- 20-run determinism and recursive receipt/action absence;
- authoritative supporter occurrence references.

## Fresh verification

Focused:

```text
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_mode_a_exact_compile

Ran 12 tests in 2.480s
OK
```

Related Mode-A/exact boundary suite:

```text
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest \
  simulator.tests.test_support_extreme_fusion_mode_a_exact_compile \
  simulator.tests.test_support_extreme_fusion_mode_a_order_beam \
  simulator.tests.test_support_extreme_fusion_mode_a_types_seeds \
  simulator.tests.test_support_extreme_fusion_transition \
  simulator.tests.test_support_extreme_fusion_catalog \
  simulator.tests.test_support_extreme_fusion_mask

Ran 95 tests in 4.067s
OK
```

Full discovery (top-level specified so package-relative diagnostic imports are
resolved):

```text
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator/tests -t . -p 'test_*.py'

Ran 510 tests in 30.860s
OK
```

Compilation:

```text
python -m py_compile \
  simulator/agents/support_extreme_fusion_beam_exact_mask/mode_a_exact_compile.py \
  simulator/tests/test_support_extreme_fusion_mode_a_exact_compile.py

exit 0
```

An initial full-discovery invocation without `-t .` produced one test-loader
ImportError in an existing package-relative diagnostic test; rerunning with the
correct project top-level passed all 509 tests. This was an invocation issue,
not a product test failure.

## Artifact hashes

```text
35A4C2C1CBA73BA23B3AC3911A783CD13C84463DF602159E766724BC5D7D89F3  mode_a_exact_compile.py
D970124DF88A80854C4D50FBFE1F67FF9AA57CF3F1AE34181ADD4A3936F3A0C0  test_support_extreme_fusion_mode_a_exact_compile.py
```

## Limits and next boundary

This is virtual strict compilation, not a physics or Public-score result. It
does not yet expose Mode A through `Agent.optimize`, replay the skeleton against
settled online observations, or package a submission. Those belong to the next
integration/acceptance tasks. No packages were installed, Git was not used,
and PyBullet was not run.

## Review fix round 1

Independent review found two correctness gaps. Both were reproduced by RED
tests before production changes:

1. Compiled supporter boxes lacked their container ordinal, so coincident local
   coordinates in another container could be recorded as a supporter. Shelf
   classification also compared only height, not shelf footprint overlap.
2. Advisory, ranking, and support-classification loops could continue after the
   compiler deadline even though the outer loop was guarded.

The compiler now stores `(occurrence, container_ordinal, AABB)` internally and
requires exact container equality, top contact, and XY overlap for compiled
supporters. Shelf classification requires the current container's actual static
shelf footprint to intersect the root footprint at an allowed vertical gap;
otherwise exact placed-top/floor semantics are used. The real stack regression
is nonvacuous and records exactly its canonical lower occurrence.

A private cooperative expiration signal is threaded through canonical identity
walks, advisory obstacle/placed walks, root dedup/ranking, compiled-support and
shelf/placed walks, and finalization boundaries. Expiration immediately after a
fresh `apply_root` is checked before intent construction, so no partial plan is
published.

Fresh round-1 verification:

```text
Focused: Ran 16 tests in 2.345s — OK
Related: Ran 100 tests in 5.667s — OK
Full:    Ran 514 tests in 29.871s — OK
py_compile: exit 0
```

Updated artifact hashes:

```text
E3C0E6985D52FCE0B6809F805D88C39E6C40DAB6C2FE51F9BF89063ADA3C0D46  mode_a_exact_compile.py
05B7A906AD5CF2BC3A226BF17F60392604FD381193AE783115D327D9A37B6F67  test_support_extreme_fusion_mode_a_exact_compile.py
```

## Review fix round 2

The reconstructed support label is now aligned exactly with the authoritative
mask semantics used by the strict root:

- compiled and initial placed tops must be axis-aligned;
- vertical top/bottom contact uses
  `settings.support_height_tolerance` (12 mm), replacing the compiler-only
  2 mm threshold;
- shelf support requires the exact nonnegative gap
  `0 <= bottom - shelf_top <= shelf_drop_gap + support_height_tolerance`;
- shelf and placed support still require same-container XY intersection.

RED evidence showed both prior errors: a valid 10 mm settled compiled top was
discarded while a tilted top was selected, and a root 1 mm below a shelf was
mislabelled as shelf-supported. Positive controls cover an aligned settled top,
an aligned initial placed top, and a root 1 mm above an overlapping shelf.

The scan spy now also proves `allow_deferred=False`, `allow_rescue=False`, and
`catalog.stats.exact_attempts <= 64`, in addition to the existing quota-family
assertions.

Fresh round-2 verification:

```text
Focused: Ran 18 tests in 2.242s — OK
Related: Ran 102 tests in 6.104s — OK
Full:    Ran 516 tests in 29.987s — OK
py_compile: exit 0
```

Updated artifact hashes:

```text
787D9C21C18AACD4D89A9C469C323C5510505F9ECD333DAED674660A0F779FE8  mode_a_exact_compile.py
8D5B72A61783653EEB9CFB13F2CF6DA101AA4CD7A8F880148E5440C5D0453C32  test_support_extreme_fusion_mode_a_exact_compile.py
```
