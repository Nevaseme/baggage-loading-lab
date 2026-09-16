# Task 18f: Memoized Streaming Layered-Proxy Rollout

Date: 2026-08-19

## Outcome

Implemented the diagnostic B-planner `memoized-streaming-maxrects-regret` without changing the default planner or the exact authorization boundary. The new executor preserves the existing proposal order, rank, stable ties, rollout quotas, and original depth-zero `ValidatedRoot` return contract while removing repeated proxy validation/materialization work and retaining completed children when a deadline interrupts a level.

This is an analytical executor change only. No PyBullet episode, SIGNATE submission, package installation, Git operation, or default production switch was performed in this task.

## Scoped files

- `simulator/agents/support_extreme_fusion_beam_exact_mask/layered_proxy.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/maxrects_regret.py`
- `simulator/tests/run_support_extreme_fusion_physics.py`
- `simulator/tests/test_run_support_extreme_fusion_physics.py`
- `simulator/tests/test_support_extreme_fusion_memoized_streaming.py` (new)
- this report

No changes were made to Catalog, ExactMask, proposals, Agent, public action formatting, ranking precedence, or work-quota constants.

## Design

### Checked proxy transition

`LayeredProxy.preview_candidates` performs the same candidate enumeration and ordering as the legacy path. Each accepted candidate is checked exactly once, then materializes its immutable child, child metrics, maximal-rectangle waste, and local-cost inputs exactly once into a proof-token-owned `CheckedProxyTransition`.

`LayeredProxy.commit_transition` does not rerun `_check` or `metrics`. It verifies:

- exact parent fingerprint and recomputed parent state digest;
- full candidate and transition signature;
- recomputed child state digest;
- ownership by the current select-local topology cache.

The canonical state digest encodes every nested proxy dataclass field with
explicit structure, type/presence, and collection-length markers.  In
particular it includes support-patch container ownership, AABB alignment, and
all `ItemSpec` fields for both placed proxy boxes and remaining occurrences;
`None`, empty sequences, wrong types, and differently shaped vectors cannot
alias a valid state digest.

The second review round tightened this from field-complete encoding to exact
type integrity.  Every state collection is an exact tuple, every nested value
is the exact declared dataclass rather than a subclass, every scalar is its
exact intended Python type, and AABB vectors are exact read-only,
C-contiguous, shape-(3,) NumPy float64 arrays.  Optional poses are either
`None` or exact tuples of exact Python floats.  Numerically equal aliases such
as `2` for `2.0`, `False` for `0.0`, `Decimal`, NumPy scalars, lists,
writeable arrays, float32 arrays, and dataclass subclasses are rejected.

A foreign cache, stale parent, replaced transition, or mutated child fails closed. The public `LayeredProxy.apply` path is unchanged and still performs a fresh check.

### Select-local topology cache

`ProxyTopologyCache` memoizes maximal rectangles using exact proxy-state, container, support layer, footprint, blocker topology, placement offset, source, and limit data. Its lifetime is one `select` invocation; no cross-call or shared mutable cache was introduced.

### Streaming selector

`MemoizedStreamingRegretProxySelector` subclasses the existing selector but replaces only the rollout executor:

- every adopted depth-zero root still passes fresh `apply_root` through ExactMask;
- analysis plans hold checked transitions rather than raw candidates;
- completed children are committed immediately and inserted into the lineage incumbent/frontier;
- one child per lineage is preserved before second children;
- an interrupted level retains already completed children;
- the deadline is resampled immediately after analysis returns and before any
  new child commit; a commit already begun before expiry remains atomic;
- branch exceptions preserve the best already-authorized original depth-zero root;
- the returned tuple contains original `RootCatalog` `ValidatedRoot` identities only.

The trace adds `duplicate_checks_avoided`, `topology_cache_hits`, `committed_children`, and `completed_partial_level`. Existing quota fields and limits remain unchanged: 24 lineages, depth 12, beam 32, 768 nodes, 96,000 fit tests, 4 items/node, 3 placements/item, 12 children/node, analysis quantum 128, occurrence quantum 8.

### Runner adapter

The physics runner accepts explicit `--b-planner memoized-streaming-maxrects-regret`. It is installed only when requested mode and resolved mode are both B. It uses the Agent-owned ExactMask/settings, the unchanged full visible pool and catalog, and the existing final fresh formatter. Default `beam`, `one-ply`, `fixed-two-ply`, `maxrects-regret`, A, C, and auto routes are unchanged. It can be combined with `--candidate-rescue global-zero-adaptive-dense`.

## TDD evidence

RED boundaries observed before production completion:

1. Import failed because `CheckedProxyTransition`/`ProxyTopologyCache` did not exist.
2. Selector import failed because `MemoizedStreamingRegretProxySelector` did not exist.
3. A forged child-content mutation was initially accepted by commit; recomputed state digests made the test GREEN.
4. Streaming committed a child before later lineage analysis and reduced comparable fit work from 32 to 16; separating analysis fit/candidate gating from committed node count restored the required lineage work and made the regression GREEN.
5. Runner parsing rejected the new option and the adapter class was absent before the scoped runner implementation.

Independent review produced two additional truthful RED boundaries:

6. Coordinated mutations to ten previously omitted digest categories were
   accepted by `commit_transition`, including support ownership and box/item
   protection, ownership, pose, and remaining-item identity fields.
7. In a two-lineage controlled-clock case, analysis of the later lineage
   expired the deadline but the selector still committed its child, producing
   two commits where only the earlier completed child was allowed.

The canonical serializer and immediate post-analysis deadline gate made both
regressions GREEN.  The deadline fixture now proves that the first lineage's
pre-expiry child remains the incumbent while the later lineage performs no
post-expiry commit.

The second review round added two further RED tests.  Thirteen coordinated
equal-value forgeries using list/tuple aliases, scalar aliases, writeable or
wrong-dtype AABB arrays, nested subclasses, and non-float pose components were
accepted before the exact-type checks.  After the canonical type contracts
were added, all thirteen aliases fail closed while valid production proxy
states and legacy/streaming rank equivalence remain GREEN.

A final audit extended the same exact-class rule to the transition envelope:
equal-valued subclasses of `ProxyCandidate`, `LayeredProxyState`, and
`ProxyMetrics` were each observed RED before signature hardening and are now
rejected by the select-local receipt signature.

The third review round exercised the outer envelope rather than only nested
content.  Eleven RED bypasses showed that a permissive cache subclass,
equal-valued state/transition subclasses, `str`-subclass fingerprints, and
preview argument subclasses could enter commit or preview.  Commit now
requires exact `LayeredProxyState`, `CheckedProxyTransition`, and
`ProxyTopologyCache` types. Preview independently requires exact state,
occurrence key, work, quota, metrics, cache, numeric fields, and a canonical
state digest. All parent, candidate, state, and child fingerprints are exact
built-in strings, and cache registration/lookup rejects transition subclasses.

The fourth review round closed receipt re-registration laundering.  Before the
fix, a caller could invoke public `ProxyTopologyCache.register` to bless an
otherwise legitimate transition into a foreign cache, or to register a
`dataclasses.replace` result containing a different canonical child/metrics.
The RED fixture reproduced that authorization bypass.  Public registration is
now absent.  A module-private atomic issuance factory constructs the
transition, attaches a cache-unique capability and per-transition seal as
non-dataclass/private attributes, and records its full signature in the exact
issuing cache in one operation.  `dataclasses.replace` does not copy this
receipt, and neither the same nor a foreign cache exposes a registration path.
The original unchanged receipt still commits through its issuing cache.

The fifth and final review round closed cache-object aliasing.  Before the fix,
`copy.copy` could duplicate the cache object while sharing its capability and
issued-receipt dictionary.  Each receipt record now stores the exact issuing
cache object and `owns_unchanged` requires `issuer is self`, so even a manually
constructed exact cache whose `__dict__` aliases the original cannot authorize
the transition.  `copy.copy`, `copy.deepcopy`, and pickle reduction all fail
closed with `TypeError`.  The stable cache repr exposes counters only; neither
cache nor transition repr contains capability, seal, token, or object address.

Focused GREEN verification during development:

```text
46 tests in 4.548s — PASS
```

Related LayeredProxy, legacy MaxRects, streaming selector, and runner verification:

```text
81 tests in 8.833s — PASS
```

Final fresh full-suite command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -t simulator -p 'test_*.py'
```

Final result:

```text
Ran 431 tests in 20.675s
OK
```

The mandatory regressions cover legacy candidate/order equivalence, preview child/metrics/local-cost equivalence, one check per preview and zero extra work on commit, forged/foreign/stale transition rejection, cache and sibling isolation, ample-clock selector rank/root equivalence, mid-level deadline retention, lineage fairness, deterministic repeated traces, unchanged quota bounds, C single-step behavior, original root identity, branch exception isolation, and B-only runner installation.

## Frozen analytical profiles

These are replay-only measurements using stored observations; no physics was run. Scanner time is separate from selector elapsed time. Every selected root passed a fresh `apply_root` check. Timings are machine/run dependent and are not Public-score evidence.

| Snapshot | Executor | Scan roots / adaptive | Selector elapsed | Deepest | Nodes | Fit tests | Candidates | Predicted count | Selected pool/item |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| initial | legacy | 64 / no | 5.304907s | 2 | 312 | 2,528 | 1,439 | 2 | 2 / 2 |
| initial | streaming, review-fixed | 64 / no | 5.305237s | 3 | 326 | 2,680 | 1,511 | 3 | 2 / 2 |
| step8 | legacy | 64 / no | 5.303708s | 2 | 57 | 1,728 | 549 | 2 | 0 / 6 |
| step8 | streaming, review-fixed | 64 / no | 5.304186s | 3 | 258 | 2,832 | 585 | 3 | 0 / 6 |
| step15 | legacy | 8 / yes | 3.396550s | 2 | 36 | 2,368 | 28 | 2 | 8 / 23 |
| step15 | streaming, review-fixed | 8 / yes | 1.189609s | 2 | 36 | 2,368 | 28 | 2 | 8 / 23 |

Additional streaming trace evidence:

| Snapshot | Committed children | Partial level | Deadline |
|---|---:|---|---|
| initial | 302 | yes | yes |
| step8 | 234 | no | yes |
| step15 | 28 | no | no |

The selected depth-zero item occurrence remained identical to the legacy executor on all three frozen snapshots. The deeper initial/step8 proxy search and shorter step15 runtime support a physical diagnostic, but do not establish a physical-score improvement. Initial and step8 wall times completed about 5--7 ms past the nominal 5.30-second boundary because an already-started analytical preview is atomic. The selector resampled the clock immediately when that analysis returned and performed no subsequent commit; the controlled two-lineage regression proves this boundary. Both remained below Agent's 5.75-second hard output boundary in this offline replay.

After the round-five issuer-identity change, a fresh frozen replay again
selected initial pool2/item2 at depth 3, step8 pool0/item6 at depth 3, and
step15 pool8/item23 at depth 2.  Their selector times were respectively
5.313679s, 5.309228s, and 1.231300s, and all three returned roots passed fresh
exact `apply_root` authorization.  This reconfirms valid original-cache
receipts without making a physics claim.

## Suggested physical diagnostic command

Run only after the parent task elects to execute physics:

```bash
python simulator/tests/run_support_extreme_fusion_physics.py \
  --task 001 --items 42 --seed 42 --mode B \
  --b-planner memoized-streaming-maxrects-regret \
  --candidate-rescue global-zero-adaptive-dense \
  --snapshot-on-failure simulator/results/support_extreme_fusion/task001-b-memoized-streaming-failure.npz \
  --output simulator/results/support_extreme_fusion/task001-b-memoized-streaming-seed42.json
```

## Self-review

- Default execution remains `beam`.
- The runner adapter is explicit B only.
- Exact depth-zero transition and final action authorization remain mandatory.
- Proxy candidates, checked transitions, and child states cannot cross the public action boundary.
- No global/shared cache was introduced.
- No quota, rank, stable tie, candidate family, or mask profile was changed.
- No unchecked fallback, random action, historical algorithm import, package install, Git action, or physics execution was added.
