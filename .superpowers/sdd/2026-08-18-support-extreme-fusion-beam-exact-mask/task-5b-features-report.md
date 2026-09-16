# Task 5b: pure future-space feature report

## Scope

Writer-owned files only:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/features.py`
- `simulator/tests/test_support_extreme_fusion_features.py`
- this report

No planner, mask, catalog, transition, simulator, historical algorithm, or
submission artifact was edited.

## TDD evidence

Initial focused RED with the bundled project runtime:

```text
ModuleNotFoundError: No module named
'agents.support_extreme_fusion_beam_exact_mask.features'
```

The pre-existing nine fixtures were audited and expanded before production
code to cover occurrence-based catalog volume/coverage, rarity, the complete
named feature schema, and forbidden receipt/search dependencies. A completion
audit then added a thirteenth RED fixture proving that a strict root from a
different state or profile was still being counted; fingerprint/profile
binding made that fixture GREEN.

The first GREEN attempt exposed three useful failures:

- support capacity saturated at 1.0 because extra top/shelf planes were
  normalized only by floor area;
- the same saturation hid the difference between compatible and incompatible
  protected top surfaces;
- a source-text guard matched `ItemSpec` rather than an actual forbidden
  module import.

Capacity is now normalized by every available support plane, so replacing low
floor area with a higher plane loses vertical capacity without hiding
protection compatibility. The dependency guard now checks import forms rather
than arbitrary substrings.

Independent review then produced further RED fixtures. They demonstrated
artificial boundaries in guillotine rectangle subtraction, unmodelled
overhead/inner-roof collisions, selected-root binding gaps, an ambiguous CoG
field name, singleton/rootless scarcity aliasing, covered-only robustness, and
support-layer offsets that missed shelf placements. Each fixture failed the
pre-fix implementation and is included in the final focused suite.

Final review added two more RED boundaries: vertical space was measured from
the physical support plane rather than the effective `+8/+22 mm` item bottom,
and an invalid selected root fell through to valid catalog margins. The final
implementation deducts the layer offset from every overhead/roof headroom and
returns zero margins whenever a supplied selected root fails binding. It also
replaces repeated rectangle cell writes with a two-dimensional difference
accumulator, preserving coverage while removing the high-order write path.

Initial focused GREEN before the completion-audit fixture:

```text
features focused: 12 tests in 0.196s ... OK
```

## Implemented feature contract

`compute_future_features(sim_state, *, catalog=None, selected_root=None,
settings=None)` is a deterministic, read-only calculation returning a frozen
`FutureFeatures`. Every value is finite and clamped to `[0, 1]`.

Goodness features, where larger is better:

- `future_covered_items`: fraction of ordered pool occurrences with at least
  one strict catalog root;
- `future_covered_volume`: corresponding occurrence-volume fraction, including
  duplicate global item IDs independently;
- `root_robustness`: mean best per-occurrence joint support/clearance margin,
  with every rootless occurrence contributing zero;
- `compatible_support_capacity`: headroom-weighted free support area on which
  at least one remaining item orientation fits;
- `protection_compatible_capacity`: the same capacity after priority and soft
  lower-surface compatibility;
- `largest_free_support`, `ingress_access`, `min_support_margin`,
  `min_clearance_margin`, and `low_stack`;
- `low_mass_cog_goodness`: explicitly directional; 1 means low/empty and
  values fall as mass moves upward.

Penalty or urgency features, where larger is worse/more urgent:

- `root_scarcity`: mean `1 / (1 + root_count)`, so rootless > singleton >
  multi-root occurrences;
- `fragmentation`: free support area outside the largest free rectangle;
- `sliver_area`: free support area unable to fit any remaining orientation.

## Geometry and purity

Floor, shelf/static-top, and axis-aligned placed-item support planes are
represented on an obstacle-edge coordinate grid. Floor, shelf, and placed-top
same-layer bottoms are recognized at `+8 mm`, `+22 mm`, and `+0 mm`
respectively. Contiguous row bands and column intervals reconstruct all
axis-aligned empty rectangles, so an arbitrary subtraction partition cannot
hide a placement spanning multiple cells. `largest_free_support` considers
only rectangles that fit a remaining official orientation; fragmentation uses
the largest geometric empty rectangle. Tilted placed tops are obstacles but
never new supports.

Every cell carries its nearest placed/static overhead and the container inner
roof (`height - thickness`). Compatibility therefore excludes vertical
collisions as well as horizontal footprints. Headroom is measured from the
effective layer-specific item bottom, not the physical support plane, and
sliver area is the exact cell area not covered by any fitting empty rectangle.

Protection capacity independently applies priority-only, soft-only, and
combined stacking rules to the supporting item. Ingress access samples 32
deterministic door lanes per container, pairing X span, Y depth, and Z height
from one real official orientation rather than mixing independent minima. CoG
is mass-weighted; zero mass is handled without division errors.

The module consumes a `RootCatalog` but never calls proposal generation, exact
validation, or a receipt factory. It does not mutate state, catalog, pool,
arrays, or roots; a repeated call is value-identical and the parent fingerprint
is unchanged. Catalog roots count toward coverage only when their profile and
state/pool/selected-occurrence fingerprint match the analytical node. A stale
or foreign-profile selected root contributes zero safety margins.

## Verification

Fresh final results:

```text
features focused: 23 tests in 0.228s ... OK
transition focused: 12 tests in 0.400s ... OK
transition + features focused: 35 tests in 0.540s ... OK
foundation + proposals + mask + catalog + transition + features:
  98 tests in 1.233s ... OK
full simulator discovery: 274 tests in 7.084s ... OK
py_compile transition.py, features.py, and both focused test modules: exit 0
```

The first final full-discovery attempt hit one old `highscore` planner
snapshot identity assertion. The feature package is not connected to that
historical planner; the exact failing test passed alone (1/1), and the
immediate fresh full rerun passed all 274 tests as reported above.

Full discovery command:

```powershell
$env:PYTHONPATH = '.;simulator'
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe `
  -m unittest discover -s simulator/tests -t . -p 'test_*.py' -q
```

## Known boundary

These are analytical ranking proxies, not official score components and not a
physics rollout. The feature module makes no claim of PyBullet stability or
Public-score improvement until a later planner integrates the values and is
benchmarked end to end.
