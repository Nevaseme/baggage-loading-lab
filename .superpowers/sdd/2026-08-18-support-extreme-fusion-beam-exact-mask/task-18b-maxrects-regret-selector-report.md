# Task 18b — Fixed-Work Layered MaxRects Regret Selector

## Outcome

Implemented a standalone ranking selector that starts only from current strict
Catalog roots and evaluates every descendant with the immutable analytical
LayeredProxy.  The selector is not connected to Agent or the physics runner in
this task.

Public API:

```python
RegretProxySelector.select(
    sim: SimState,
    catalog: RootCatalog,
    mode: str,
    deadline: float,
) -> tuple[ValidatedRoot, ...]
```

The returned tuple contains only the original `ValidatedRoot` objects owned by
the supplied depth-zero Catalog.  Proxy candidates and states never cross the
return boundary.

## Exact depth-zero boundary

Catalog roots are scheduled occurrence-first, with pool positions round-robin
and container/orientation families round-robin within each occurrence.  Every
adopted lineage is freshly applied by `apply_root(...,
exact_revalidator=ExactMask)` before LayeredProxy construction.  Stale,
foreign, invalid, duplicate, or deadline-expired roots are omitted.  The
default lineage cap is 24.

The original root identity is retained on every proxy descendant.  Ranking a
descendant can only move that original root within the returned tuple; it
cannot mint a receipt or synthesize a public action.

## Fixed-work rollout

Mode B defaults:

- 24 depth-zero lineages;
- depth at most `min(12, visible_pool_size)`;
- beam width 32;
- 768 total proxy nodes;
- 96,000 analytical fit tests;
- four item occurrences per node;
- three placements per item;
- twelve children per node.

Lineage pruning preserves one node from every live lineage before admitting a
second node from any lineage.  Child creation is also lineage round-robin.
Fit work is reserved between all first-lineage nodes and divided into fixed
per-node/per-occurrence quanta, preventing one expensive lineage from
consuming the full deadline before other visible occurrences receive work.
The fixed quotas remain the primary limits; the wall clock is an atomic hard
guard between bounded work units.

Mode C adopts and ranks strict depth-zero roots only.  It performs no proxy
candidate enumeration, rollout, or arrival prediction.

## Expansion and ranking

For each analyzed node, remaining visible occurrences are ordered by:

1. exactly one feasible placement;
2. maximum regret between their two best local placements;
3. fewer feasible placements;
4. larger volume;
5. occurrence key.

Local placement cost includes the containing obstacle-coordinate MaxRect's
area, short-side, and long-side waste; ingress and protection-capacity loss;
stack cost; backness; and a stable candidate key.

Lineage rank is lexicographic:

1. predicted placed count;
2. predicted placed volume;
3. remaining fit count and volume;
4. minimum nonzero option scarcity;
5. material protection-capacity bucket;
6. ingress, largest free region, and negative sliver area;
7. low mass-weighted CoG and low stack;
8. depth-zero support and clearance margins;
9. cumulative backness;
10. stable ascending sequence key.

`SelectionTrace` records adopted and ranked lineage keys, nodes, fit tests,
candidates, deepest rollout, quota/deadline state, invalid lineages, isolated
branch exceptions, expansion order, and the leading predicted count, volume,
and largest-free-region proxy.

## TDD and frozen evidence

Initial RED was the expected missing-module import failure.  Focused tests then
covered:

- one-option and maximum-regret ordering;
- count over volume over secondary metrics;
- pool/container/orientation and lineage fairness;
- duplicate global IDs as distinct occurrences;
- default and operational work bounds;
- 20 identical fixed-clock runs;
- deadlines during root adoption, analysis, and child application;
- occurrence-level exception isolation;
- stale-root omission and parent/Catalog immutability;
- C one-ply behavior and original-root identity;
- forbidden historical-search dependencies and absence of action/receipt
  construction.

The available task001 step-8 frozen snapshot produced a deterministic,
decision-relevant divergence:

```text
frozen FixedQuotaExactTwoPly: pool 8, item 16, predicted exact depth 1
Layered MaxRects proxy:      pool 0, item 6, predicted proxy count 2
```

The lightweight frozen regression uses 48 nodes and 1,000 fit tests and checks
that the chosen root is the original strict Catalog object.  Its leading
two-placement descendant retained largest-free-region proxy above 0.20.

This does **not** satisfy a stronger claim that contiguous space is at least
the fixed-two-ply root's immediate-state value: offline diagnosis measured
approximately 0.253 for the two-placement proxy descendant versus 0.428 after
the fixed method's single exact placement.  That comparison is also
different-depth.  Therefore Task18b provides a testable routing hypothesis,
not a physical or score improvement claim; Task18c must decide whether to keep
or reject it from official physics evidence.

## Verification

Fresh results after all fixes:

```text
focused selector: 21 tests, PASS, 4.846 s
selector + layered proxy + transition + catalog: 68 tests, PASS, 6.104 s
full simulator suite: 389 tests, PASS, 15.294 s
independent Sol review: APPROVE, no Critical/Important finding
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -q
```

## Scope audit

- No existing production or test file was edited.
- No Agent, Catalog scanner, ExactMask, LayeredProxy, physics runner, settings,
  historical artifact, dependency, or Git state changed.
- Production imports contain no `highscore`, EMS, MCTS, Beam, or FixedQuota
  dependency.
- The module never constructs `ValidatedRoot` or an action dictionary.

Files added:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/maxrects_regret.py`
- `simulator/tests/test_support_extreme_fusion_maxrects_regret.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-18b-maxrects-regret-selector-report.md`
