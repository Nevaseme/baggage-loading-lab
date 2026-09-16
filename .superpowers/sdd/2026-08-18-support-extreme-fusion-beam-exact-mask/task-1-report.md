# Task 1 report: standalone strict-root contract

## Scope

Added the new `agents.support_extreme_fusion_beam_exact_mask` package without
changing the historical `agents.highscore` package or simulator core.  The
package currently contains the migrated model/state/geometry/settings boundary
and an intentionally not-ready public `Agent`.

## Contract implemented

- `PlacementProposal` is a frozen raw proposal type.
- `ValidatedRoot` is evidence only.  It carries a strict profile digest, item
  signature, proposal key, finite AABB, and zero rule violations, but even a
  receipt issued by the package-private factory cannot authorize an action by
  itself.  `dataclasses.replace` copies are rejected by final exact
  revalidation before formatting.
- `Agent.format_validated_action` is an instance method that requires the
  ordered current pool and an exact-mask verifier installed by a future
  planner.  It uses the agent-owned `SearchSettings`, checks proposal/box/
  item/profile/ordinal/fingerprint bindings, calls
  `exact_revalidate(state, pool, proposal, settings)`, and emits only after
  a freshly returned, matching strict evidence object is returned.  Boolean
  verifier results are deliberately not format-authorizing.
- `AABB` stores endpoints in bytes-backed read-only float64 views (including
  resistance to `setflags(write=True)`) and rejects non-finite, malformed, or
  inverted bounds.  `PackingState.clone` deep-copies endpoint arrays, placed
  boxes, static obstacles, and observation arrays.
- `ContainerState` carries an explicit ordinal separate from metadata index;
  state reconstruction and action formatting use ordinal semantics.
- `PlacementProposal` validates exact non-negative integer identities,
  official orientations, finite `(3,)` positions, and a string provenance.
- State fingerprints use canonical little-endian float64 array encoding and
  include a profile digest plus the complete ordered pool and selected action
  position.  `ItemSpec.from_dict` and raw container parsing reject bool or
  fractional identity values rather than coercing them.
- `policy` and `optimize` raise `NotReadyError` until a strict planner is
  implemented; they do not emit arbitrary coordinates or partial orders.
- `model.py`, `state.py`, and `geometry.py` use only NumPy and the standard
  library and have no imports from historical agent modules.

## Verification

RED before implementation:

```text
ModuleNotFoundError: No module named 'agents.support_extreme_fusion_beam_exact_mask'
```

Round-2 RED before implementation included:

```text
setflags(write=True) unexpectedly succeeded
bool/fractional raw IDs were silently coerced
formatter accepted a receipt without an exact verifier/current pool
deferred proposal API was absent
boolean `True` verifier output was previously accepted as an action gate
```

GREEN after implementation:

```text
$env:PYTHONPATH='C:\Users\TAKUMI\projects\Baggage-Loading\simulator'
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_support_extreme_fusion_contract -v
Ran 16 contract tests ... OK
```

The focused contract suite now covers receipt forgery/relaxation rejection
with a final verifier, mandatory ordered-pool binding, non-contiguous metadata
indices versus Gym ordinals, bytes-backed AABB immutability/deep-copy
isolation, malformed identity boundaries, profile-string rejection, and
ordinary/deferred container tiers in addition to the original contract.  It
also rejects `True`, `False`, and `None` verifier results, requiring exact
evidence matching the current root.

Import/compile smoke:

```text
python -m compileall -q simulator/agents/support_extreme_fusion_beam_exact_mask
from agents.support_extreme_fusion_beam_exact_mask import Agent, PlacementProposal, ValidatedRoot
```

Both completed successfully.  Planner/catalog work is intentionally deferred
to subsequent tasks; this boundary has no unchecked fallback.
