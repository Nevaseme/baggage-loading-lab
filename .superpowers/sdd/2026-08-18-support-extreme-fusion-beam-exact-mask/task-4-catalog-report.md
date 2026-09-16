# Task 4: fair strict-root catalog report

## Scope

Writer-owned files only:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/catalog.py`
- `simulator/tests/test_support_extreme_fusion_catalog.py`
- this report

Existing foundation, proposal, mask, planner, simulator, and historical
submission files were not edited.

Task 6 review later reopened this writer scope for one backward-compatible
catalog API refinement: child analytical search can explicitly disable both
deferred-container and rescue proposal families. No default caller behavior
was changed.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError: No module named
'agents.support_extreme_fusion_beam_exact_mask.catalog'
```

Self-review added a second RED proving that a caller's later hard deadline was
incorrectly being used as the entire normal scan budget. The normal scan could
reach its raw limit rather than stop at `normal_catalog_limit_seconds`. The
scanner now has a distinct normal deadline and preserves the later hard budget
for rootless rescue.

Independent review added a third RED for a no-progress phase transition:
coverage had already reached `raw_proposal_limit`, the ordinary proposal was
invalid, and the deferred proposal was valid. The final ordinary rescan had no
unseen record, so the outer no-progress guard stopped immediately after setting
`phase="deferred"`. Phase transition is now explicit progress, guaranteeing a
following deferred scheduling turn.

Rejected proposals originally ran `validate` and then `diagnose`, duplicating
the full geometry pass. They now run `diagnose` once; diagnostic accepts alone
receive a second `validate` call whose fresh receipt is the only root exposed
by the catalog. A counting-mask regression proves rejected proposals call
`diagnose` once and `validate` zero times.

Beam review added a fourth RED proving that filtering a returned catalog was
too late: a child scan had already generated deferred/rescue proposals and
could spend its deadline before a later sibling. `scan` now accepts
`allow_deferred` and `allow_rescue` (both default `True`). When false, their
proposal families are never invoked. The public/default global-zero recovery
and ordinary/deferred behavior remain unchanged.

Focused GREEN at implementation completion:

```text
python.exe -m unittest tests.test_support_extreme_fusion_catalog -v
Ran 16 tests ... OK
```

## Public structures

- `RootRecord` carries one strict `ValidatedRoot`, fused provenance, pass name,
  stable key, and raw acceptance ordinal.
- `CatalogStats` is immutable and records exact attempts, accepted roots,
  duplicates, stable rejection counts, pool coverage, exceptions, pass names,
  caps, and deadline state.
- `RootCatalog` is an immutable iterable of records with exact-root and
  per-pool views. An empty pool yields a zero-valued empty catalog and never an
  action.
- `StrictRootScanner.scan` (`build` alias) is the only proposal-to-root bridge.
  Its default-compatible `allow_deferred=True` and `allow_rescue=True` gates
  permit normal-only analytical child scans without constructing forbidden
  families.

The scanner rejects an `ExactMask` whose profile digest differs from catalog
settings. Every exposed root comes directly from `ExactMask.validate`; the
catalog never imports an approximate validator, scorer, planner, random
fallback, or historical agent.

## Scheduling and gates

The deterministic schedule is:

1. Coverage pass: each valid pool position gets a small raw-work cap and stops
   after its first strict root.
2. Scarcity pass: pool positions are repeatedly ordered by current root count
   and pool ordinal; small validation quanta expand raw budgets until eight
   roots per pool position, 64 globally, exhaustion, or deadline.
3. Rootless rescue: normal global-zero automatically scans all rootless pool
   positions using only `free_rectangle_boundary` and
   `dense_support_lattice`. Explicit breadth rescue targets only positions
   with zero normal/deferred roots.

Accepted incumbents survive deadline and item-local exceptions. Duplicate
global item IDs remain isolated by pool ordinal. Normal and rescue provenance
never merge.

For a normal item, ordinary containers are scanned to strict exhaustion first.
One ordinary strict root suppresses the deferred prioritized-container tier.
Only ordinary strict-zero opens that deferred tier. Prioritized-item fixation
continues to be enforced by the exact mask.

The caller deadline is a hard bound. Normal work is additionally capped at
`start + normal_catalog_limit_seconds`; rootless rescue may use the remaining
hard budget, whose default is `start + zero_root_rescue_limit_seconds`.

## Test coverage

The focused suite covers:

- exact-only roots and fresh field-matching revalidation;
- profile binding and forbidden imports;
- first-pass raw-cap fairness and deterministic scarcity ordering;
- duplicate IDs, eight-per-pool and 64-global caps;
- deadline partial incumbents and separated rescue deadline;
- item exception isolation and stable rejection counts;
- normal exclusion of dense provenance;
- global-zero and explicit breadth rescue rootless targeting;
- ordinary/deferred priority-container gating;
- empty catalog behavior.
- normal-only scanning that never calls deferred or rescue proposal families.

## Verification

Fresh final results after the Task 6 normal-only review fix:

```text
catalog + beam focused: 34 tests in 0.478s ... OK
foundation + proposals + mask + catalog + transition + features + beam:
  116 tests in 2.696s ... OK
full project discovery: 292 tests in 6.024s ... OK
py_compile catalog.py, beam.py, and their focused tests: exit 0
```

Full discovery used repository-top-level package roots:

```powershell
$env:PYTHONPATH = '.;simulator'
python.exe -m unittest discover -s simulator/tests -t . -p 'test_*.py' -q
```

## Known constraints

- Proposal generation exposes no raw-exhaustion receipt. To prove ordinary
  strict-zero before deferred exposure, the scanner incrementally reaches the
  configured `raw_proposal_limit` and processes all unique records returned at
  that bound. This is conservative under short deadlines: it may omit a
  deferred root rather than expose it before ordinary exhaustion is proven.
- This task builds a root catalog only. It does not select or format an action,
  certify the step-14 state, or claim physical score improvement.
