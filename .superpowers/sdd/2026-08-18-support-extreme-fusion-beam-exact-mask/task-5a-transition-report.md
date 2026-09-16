# Task 5a: immutable exact-root transition report

## Scope

Writer-owned files only:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/transition.py`
- `simulator/tests/test_support_extreme_fusion_transition.py`
- this report

No existing package, test, simulator, planner, or submission file was edited.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError: No module named
'agents.support_extreme_fusion_beam_exact_mask.transition'
```

A self-review RED then proved that a receipt whose `source` or AABB alignment
was altered with `dataclasses.replace` still passed the initial field checks.
The transition now binds receipt/proposal source and requires the axis-aligned
box implied by an official orientation.

Independent review found a critical coordinated-laundering gap: proposal
position/container/orientation, AABB, proposal key and source could all be
changed together while retaining the original proof token and state
fingerprint. RED fixtures demonstrated both an out-of-bounds child and a child
inside a static obstacle. `apply_root` now requires fresh ExactMask evidence
and compares every receipt/action field with the supplied root before cloning.
Boolean, same-object, absent, expired, or nonmatching evidence cannot authorize
a transition.

Focused GREEN:

```text
python.exe -m unittest tests.test_support_extreme_fusion_transition -v
Ran 12 tests ... OK
```

## Implemented contract

`SimState` is a frozen analytical node containing:

- one `PackingState` snapshot;
- an ordered tuple of immutable `ItemSpec` occurrences;
- an equally sized tuple of unique, exact non-negative original pool
  positions.

`SimPlacement` is a frozen result that retains parent, child, the original
strict root, selected current/original pool positions, and public container
ordinal.

`apply_root` checks before mutation:

- genuine strict-root capability, zero rule violations and current profile;
- current ordered-pool occurrence, item index and complete item signature;
- canonical public container ordinal independent of raw metadata index;
- proposal key and source binding;
- official oriented dimensions, axis alignment and exact centre/position;
- full current state, pool, selected occurrence and profile fingerprint.

After those static checks, it invokes an `ExactMask` (or a trusted callable
with the Agent-style revalidation contract). Only a freshly issued
`ValidatedRoot` whose proposal, exact AABB arrays/alignment, profile,
fingerprint, item signature, proposal key, support/clearance metrics, source,
strict flag, and zero-violation state all match the supplied root authorizes
the clone. The deadline is passed into the ExactMask path.

It then deep-clones every container, placed box, static obstacle, points,
normals and depth array through `PackingState.clone`; appends a newly cloned
AABB/`PlacedItem` only to the selected child container; and removes exactly the
selected pool occurrence and its original-position mapping. Parent and sibling
states remain unchanged.

The transition module does not issue a receipt itself; it requires the exact
mask to issue fresh matching evidence and retains the original root in
`SimPlacement`. It never formats an external action or imports the historical
agent, EMS, MCTS, planner, or fallback code.

## Regression coverage

- duplicate global item IDs are separated by pool occurrence;
- parent fingerprints and arrays remain unchanged and siblings do not alias;
- stale roots fail on children, foreign state/pool roots fail binding;
- altered profile, box, position, ordinal, source and alignment fail closed;
- coordinated out-of-bounds/collision laundering and non-fresh/boolean exact
  evidence fail closed;
- direct/non-root construction is rejected;
- the newly appended child box makes the identical next placement fail both
  ExactMask and a patched strict Catalog path as collision.

## Verification

Fresh final results:

```text
transition focused: 12 tests in 0.400s ... OK
transition + features focused: 35 tests in 0.540s ... OK
foundation + proposals + mask + catalog + transition + features:
  98 tests in 1.233s ... OK
full simulator discovery: 274 tests in 7.084s ... OK
py_compile transition.py, features.py, and both focused test modules: exit 0
```

The earlier full-discovery blocker from the then-unimplemented feature module
is resolved. The final full discovery includes that module and its tests.

Full discovery used repository-top-level package roots:

```powershell
$env:PYTHONPATH = '.;simulator'
python.exe -m unittest discover -s simulator/tests -t . -p 'test_*.py' -q
```

## Known boundary

This is an analytical immutable transition, not a physics rollout. It assumes
the settled current `PackingState` represented by the root fingerprint and
does not claim PyBullet stability or placement-score improvement.
