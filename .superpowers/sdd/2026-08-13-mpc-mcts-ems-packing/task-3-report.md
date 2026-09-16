# Task 3 — Deterministic anytime MPC-MCTS report

## Scope

Created `simulator/agents/highscore/mcts.py` and
`simulator/tests/test_highscore_mcts.py`; added the six specified MCTS
settings defaults to `simulator/agents/highscore/settings.py`.  No Agent,
Planner, catalog, candidates, EMS, simulator-core, packaging, or Git changes
were made by this task.

## Implementation

- `RolloutValue` is an ordered, root-aware lexicographic value: visible packed
  count, volume, exact-root violation count, EMS volume, ingress slack,
  roughness, then mass-weighted CoG.
- `MCTSSearch.choose` considers only exact `RootAction.candidate` objects for
  its return value.  It removes just the selected pool position from deeper
  proxy state, so duplicate `ItemSpec.index` values do not remove two visible
  items.
- Selection, widening, proposal, apply, rollout, and backup operate under an
  absolute caller deadline capped by `mcts_policy_limit_seconds`.  Baseline
  exact roots are incumbents before any proxy search; exceptions retain them.
- Expansion and rollouts use only Task 1 EMS proposal/transition APIs.  A local
  `random.Random(seed)` chooses among the three stable best-fit options.
  Stable keys use pool/item/container/orientation and quantized AABB geometry.
- Proxy transposition entries are keyed by Task 1 `state_key`; an entry is
  rejected if its pool position is no longer visible, including duplicate item
  IDs.

## TDD evidence

Initial RED command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts.RolloutValueAndSelectionTests -v
```

Result: expected import failure, `ModuleNotFoundError: agents.highscore.mcts`.

Focused GREEN after value/UCB primitives: 2/2 passed.

Second RED command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts.AnytimeMCTSTests -v
```

Result: expected missing `propose_actions` module attribute and missing
`MCTSSearch.choose` errors.  Later RED cycles caught stale duplicate-pool
transposition replay and an uncapped configured MCTS deadline; both were fixed
before proceeding.

Latest focused GREEN:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts -v
```

Result: 7/7 passed in 0.008 s.

Latest initially-dependent run before concurrent EMS test additions:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems simulator.tests.test_highscore_catalog -v
```

Result: 40/40 passed in 0.266 s.

Controlled determinism command:

```text
1..20 | ForEach-Object { python -m unittest simulator.tests.test_highscore_mcts.AnytimeMCTSTests.test_choose_prefers_root_with_three_visible_items_and_is_deterministic -q }
```

Result: 20/20 passed, 9.780 s wall time (each controlled search selected the
three-visible-item exact root with the same seed and clock).

Earlier full highscore discovery command:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Result: 101/101 passed in 2.540 s.

## Final verification

After Task 1 completed its concurrent EMS correction, fresh verification was:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m compileall -q simulator\agents\highscore
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems simulator.tests.test_highscore_catalog -v
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
```

Result: compilation succeeded; dependent MCTS/EMS/catalog suite 45/45 passed
in 0.263 s; full highscore discovery 106/106 passed in 2.570 s.

## Self-review

- Final root choice uses `RolloutValue`, not UCB scalar means.
- The only public return paths are `RootAction.candidate` or `None`.
- Empty roots and expired deadlines return safely; failures after an incumbent
  preserve it.
- Stable action keys contain no object identity or randomized Python hash.
- Feature calculations use finite NumPy float64 values and safely handle no
  spaces or zero mass.

## Remaining concern

Task 4 must integrate this module behind its default-off flag and run physical
gates.  Unit search deliberately relies on conservative EMS proxy feasibility
below the exact root; it cannot establish PyBullet execution safety by itself.

## Review-fix round 1

Five Important review findings were addressed only in `mcts.py` and its focused
tests.  Each was first added as a RED regression: terminal/actionless roots
spun to the policy cap; cache replay stopped after one transition; equal
`RolloutValue`s ignored `Candidate.secondary_score`; a broken root baseline
aborted the earlier incumbent; and `_backup` could partially update statistics
after expiry.  The focused RED command ran the five new named test methods and
failed 3 assertions plus 2 expected missing/error paths.

The minimal changes are:

- genuinely exhausted nodes are terminal and the outer search stops when every
  root converges, while nodes whose widening limit may grow retain pending work;
- cache replay continues across successor-state entries, rejects cycles, and
  removes exactly the cached action's pool position;
- incumbent ordering is `(RolloutValue, finite secondary score, stable inverse
  action key)`;
- each baseline is isolated, with a deterministic exact-root minimum fallback
  only when lower proxy features reach deadline; and
- value/feature loops take a deadline and backup preflights its complete path
  before changing any node statistics.

Fresh verification after the review fixes:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts -v
# 12/12 passed in 0.017 s

# 20 controlled repetitions of the deterministic synthetic branch
# 20/20 passed in 10.402 s wall time

C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems simulator.tests.test_highscore_catalog -v
# 50/50 passed in 0.271 s

C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
# 111/111 passed in 2.559 s
```

Self-review: terminal status is assigned only for empty remaining pools or
generated nodes with neither pending actions nor children.  Nodes with
progressive-widening capacity remain nonterminal.  Timeout paths return a
previous exact incumbent when a baseline was established; no lower-feature
timeout changes it to `None`.

## Review-fix round 2

The final Important finding was unchecked work inside two lower-order value
features. RED tests with controlled clocks showed that `_space_features` could
complete an inner remaining-item/EMS generator after the deadline and that the
final packed-volume `sum` similarly had no per-item deadline check. Those tests
initially failed because `_DeadlineExpired` was not raised.

Both paths now use explicit loops and check the absolute deadline for every
remaining-item/EMS comparison and every volume accumulation. Two integration
regressions also confirm that either baseline expiry returns the deterministic
minimal exact-root incumbent, never `None`. The other value-helper loops were
reviewed: spaces, remaining items, rollout actions, masses, and backup path
already check at their corresponding granularity.

Fresh verification:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts -v
# 16/16 passed in 0.016 s

C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems simulator.tests.test_highscore_catalog -v
# 54/54 passed in 0.248 s

C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
# 115/115 passed in 2.628 s
```

## Review-fix round 3 — deadline-test precision

Production MCTS logic was unchanged. The two deadline regressions were made
diagnostic rather than merely broad: the inner-space controlled clock now has
two EMSs and returns expiry only on call 8, the second inner comparison. It
therefore fails if that exact inner deadline check is removed, even if the
outer loops remain guarded. The volume/fallback test uses no spaces and records
the exact six observations: policy start, value entry, mass loop, feature
entry, volume-item expiry, then outer-loop exit. It asserts both the returned
exact candidate and `_last_root_values == (_minimal_value(root),)`. In this
one-item/no-space fixture, the exact `clock.calls == 6` assertion is what fails
if the volume deadline check is removed; the candidate/value assertions verify
the fallback result once that expiry is raised.

Fresh verification:

```text
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts -v
# 16/16 passed in 0.015 s

C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest simulator.tests.test_highscore_mcts simulator.tests.test_highscore_ems simulator.tests.test_highscore_catalog -v
# 54/54 passed in 0.366 s

C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s simulator/tests -p 'test_highscore_*.py' -v
# 115/115 passed in 3.005 s
```
