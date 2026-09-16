# Task 6: deterministic future-support ingress beam report

## Scope

Writer-owned files only:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/beam.py`
- `simulator/tests/test_support_extreme_fusion_beam.py`
- the normal-only scan gates in
  `simulator/agents/support_extreme_fusion_beam_exact_mask/catalog.py` and
  `simulator/tests/test_support_extreme_fusion_catalog.py`
- this report

No existing foundation, proposal, mask, transition, feature, simulator,
historical algorithm, or submission file was edited.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError: No module named
'agents.support_extreme_fusion_beam_exact_mask.beam'
```

The first implementation made eleven focused contracts GREEN. A subsequent
normal-only child-catalog fixture failed because a deferred child record was
expanded to a grandchild. Filtering returned records was not sufficient: the
scanner could already spend its deadline generating deferred or rescue
families. Child scans now pass `allow_deferred=False` and
`allow_rescue=False`; a returned `pass_name == "normal"` filter remains as
defense in depth. The initial caller-provided catalog remains untouched so the
caller owns any explicit rescue choice.

Independent review then produced three focused REDs. Two stale roots could
consume a two-root quota before fresh validation; six scarce small-item groups
could exclude a larger-volume seventh item; and two high-clearance placements
could exclude a third placement with strictly better future coverage. The
beam now checks current state/pool/profile binding first, fresh-applies every
surviving root, computes its one-edge future features, and only then applies
the per-item and per-root caps using the same lexicographic rank. A normal-zero
child regression also proves that no deferred/rescue construction starves a
later sibling.

A final review found that stale records had still contributed indirectly to
scarcity and feature inputs through the original parent catalog. A seven-item
RED made those stale counts exclude the only three-step branch. Evaluation now
constructs a current-record-only catalog before feature and scarcity
calculation; fresh exact application remains mandatory for every edge. The
independent re-review subsequently returned APPROVE with no Critical or
Important findings.

## Implemented contract

`BeamNode` is a frozen analytical node containing the immutable `SimState`,
the original depth-zero root, exact `SimPlacement` sequence, proven count and
volume, bounded `FutureFeatures`, cumulative selected-root scarcity urgency,
deterministic sequence key, and strict child catalog.

`FutureSupportIngressBeam.choose_b`:

- considers every current, profile-bound strict root in the supplied visible
  pool catalog, including position 39;
- cheaply drops stale state/pool/profile records, then still calls
  `apply_root` for fresh exact revalidation on every surviving edge;
- evaluates one-edge future features before selecting at most six item
  occurrences and two roots per occurrence, so the cap cannot invert the
  declared rank;
- searches to `min(4, visible_pool_size)` with beam width 20;
- calls `apply_root` with the exact mask on every edge;
- scans child states with `breadth_rescue=False`, `allow_deferred=False`, and
  `allow_rescue=False`, and exposes normal records only;
- isolates per-branch apply, scan, and feature exceptions;
- retains the best already-proven depth-zero incumbent at a deadline;
- returns the identical original depth-zero catalog root, never a descendant
  root or reconstructed proxy.

`choose_c` performs one-ply ranking over every supplied strict root. It never
calls the child scanner, assumes no unobserved arrivals, and leaves rescue
catalog construction to the caller.

## Ranking and determinism

Node comparison is lexicographic in this exact order:

1. proven exact placement count;
2. proven volume;
3. future covered occurrences and volume;
4. strict-root robustness;
5. cumulative selected-root scarcity urgency (`1 / (1 + root_count)`);
6. compatible and protection-compatible support capacity;
7. ingress access and largest fitting support rectangle;
8. negative sliver area;
9. low-mass-CoG goodness;
10. selected-root support and clearance margins;
11. low-stack goodness (equivalent to negative normalized stack height).

Stable ordering is established by ascending occurrence/item/container/
orientation/position/source sequence keys before a stable descending quality
sort. Twenty identical runs return the same root object.

## Safety boundary

The module imports no raw proposal class or receipt factory and never formats
an action dictionary. Every branch begins at a `RootRecord`, and only fresh
matching exact evidence inside `apply_root` authorizes its child transition.
There is no stochastic, historical-agent, or alternative search path.

## Regression coverage

- locally attractive one-step dead end versus a three-step branch;
- count over volume and volume over all secondary features;
- stable equal-quality ordering and 20-run determinism;
- rare-item urgency and ingress preservation;
- deadline incumbent preservation and branch exception isolation;
- pool position 39, normal-only child scans, and no breadth rescue;
- normal-zero sibling progress without deferred/rescue proposal calls;
- stale roots not consuming the two-root quota;
- stale roots not distorting scarcity/coverage before the six-item cap;
- volume precedence across the six-item cap and future-coverage precedence
  across the two-root cap;
- C-mode no-scan behavior;
- original catalog membership and object identity;
- real `StrictRootScanner`/`ExactMask` integration;
- immutable node and forbidden import/action/receipt source audit.

## Verification

Fresh final results after review fixes:

```text
beam focused: 17 tests in 0.388s ... OK
catalog + beam focused: 34 tests in 0.478s ... OK
foundation + proposals + mask + catalog + transition + features + beam:
  116 tests in 2.696s ... OK
full simulator discovery: 292 tests in 6.024s ... OK
py_compile catalog.py, beam.py, and their focused tests: exit 0
```

## Known boundary

This is a deterministic analytical search, not a physics rollout. Exact-mask
validity authorizes simulated edges, while settled dynamic stability and
official scoring still require later end-to-end evaluation.
