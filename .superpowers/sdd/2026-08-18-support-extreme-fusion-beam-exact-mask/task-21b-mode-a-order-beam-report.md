# Task 21b — Offline LayeredProxy Order Beam

Date: 2026-08-19

## Outcome

Implemented the offline analytical order beam for
`layered_proxy_order_beam_exact_skeleton_repair`. This task stops before the
strict skeleton compiler and Agent integration.

`LayeredProxyOrderBeam.search` accepts a settled `PackingState`, canonical
Task21a occurrences, matching ordered raw items, and an absolute deadline. It
returns immutable `ProxyOrderCandidate` values only. These contain a complete
occurrence permutation plus the proxy-placed skeleton prefix; they contain no
validated root, placement proposal, receipt, NumPy alias, or action dictionary.

## Search structure

- Three deterministic seed lanes: original order, Task21a historical
  rigid/heavy/footprint order, and descending volume/footprint order.
- Up to six item occurrences per node from seed heads, estimated support-layer
  option scarcity, protection attributes, and large-footprint/few-orientation
  urgency.
- Official six orientations with dimension deduplication.
- Stratified container/support-layer/orientation exposure.
- At most four checked transitions issued per item; preview is capped before
  generation rather than materializing an unbounded batch and slicing later.
- One select-local `ProxyTopologyCache`; preview and commit use the same
  issuer-bound checked transition. Parents and siblings remain immutable.
- Fair retention first covers seed lane, support source, and container, then
  fills the remaining width by rank.

Default fixed work is width 24, 20,000 nodes, 250,000 fit tests, 80,000 checked
transitions, 64 fit tests per preview, four placements per item, six item
choices, and 128 rectangles per patch. The trace records exact consumed work
and quota/deadline/exception state.

An already-expired search returns before seed, `SimState`, proxy construction,
or metrics work. Choice scarcity checks the absolute deadline across
occurrence/container/support/orientation loops. Each preview clamps both fit
work and issued transitions, and the deadline is resampled after preview before
any commit. An atomic commit that began before expiry may finish; its completed
candidate is retained as the incumbent.

Rank is lexicographic: complete, placed count, placed volume, saturated minimum
alternatives, support and clearance margins, material protection capacity,
ingress, largest region, negative sliver, low CoG, low stack, negative seed
discrepancies, then the stable key. Thus no higher-volume partial candidate can
precede a complete candidate.

## TDD evidence

### Review-fix RED

The deadline/work regressions were added before production changes. The run
produced two expected failures and three expected errors: expired calls still
constructed proxy state and returned partial candidates, the per-preview fit
quantum did not exist, and choice enumeration accepted no deadline argument.

### RED

The focused tests were written first. Their first run failed with the expected
`ModuleNotFoundError` because `mode_a_order_beam.py` did not exist.

The first behavioral run exposed five errors: one invalid rank fixture and four
array-valued dataclass equality paths in fair retention. The fixture was made
contract-valid and retention was changed to identity membership. A subsequent
performance diagnosis found preview generated every transition before slicing
to four; generation itself is now bounded to the four-transition item quota.

### Focused GREEN

```text
Ran 20 tests in 1.652s
OK
```

Coverage includes seed lanes, choice-union components, cooperative scarcity
deadline truncation, immediate no-work expiry, per-preview fit/transition
bounds, completed-incumbent preservation, orientation dedupe,
complete-over-partial rank, exact types, real three-item completion, duplicate
occurrences, protection semantics, seed/support/container fairness, select-local
cache provenance, branch exception isolation, deadline incumbent, tiny exact
quotas, 20-run determinism, bounded 41-occurrence smoke, and forbidden AST
dependencies/types.

### Related GREEN

Mode-A types, LayeredProxy, transition, legacy MaxRects, and memoized selector:

```text
Ran 104 tests in 10.016s
OK
```

### Fresh full GREEN

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -t simulator -p 'test_*.py'
```

```text
Ran 498 tests in 27.381s
OK
```

`py_compile` passed for the new production and test modules.

## Files

- `simulator/agents/support_extreme_fusion_beam_exact_mask/mode_a_order_beam.py`
- `simulator/tests/test_support_extreme_fusion_mode_a_order_beam.py`
- `docs/superpowers/plans/2026-08-18-layered-maxrects-regret-exact-mask.md`
- this report

## Scope and caveat

The returned skeleton is proxy evidence only. Partial candidates are explicitly
tagged incomplete, and this module cannot publish a `ModeAPlan`. A later task
must compile every intent through the authoritative exact mask, repair stale or
uncompilable intents, and only then call the Task21a finalizer. No PyBullet,
SIGNATE, Git, package installation, or Agent behavior was exercised here.
