# MPC-MCTS EMS Packing Design

## Objective

Raise the SIGNATE Public score from `12.622949582873819` to at least `60.0`.
Leaderboard scores above 68 establish that incremental safety-only tuning is not
competitive.  The agent must plan coordinated placements for the visible or
known batch while retaining the existing exact safety kernel and the public API.

Local sample prefixes are development gates, not substitutes for the Public
score.  No variant is a 60-point candidate until it completes both task000/25
and task001/30 locally without an unsafe action, then improves through controlled
SIGNATE submissions.

## Evidence and Lessons

The accepted local control places 17/25 task000 items and 20/30 task001 items.
Two isolated changes were rejected:

- continuous monotone base candidates kept task000 at 17 but regressed task001
  from 20 to 18;
- geometry-only rescue kept task000 at 17 but regressed task001 from 20 to 16.

Both failures show that preserving an opening or finding one extra feasible
action is insufficient.  A locally valid action can destroy the joint placement
capacity of the rest of the visible pool.

Research inputs:

- arXiv `2601.02649` formulates online 3D bin packing with short lookahead as
  model-predictive control and applies Monte Carlo tree search, including a
  reward for long-term spatial waste;
- arXiv `2006.14978` demonstrates the value of an explicit feasibility mask in
  constrained online packing;
- arXiv `1812.04093` uses heightmap minimization to accelerate stable robotic
  packing;
- arXiv `2507.09123` separates a fast packing policy from explicit structural
  stability validation.

The Hugging Face paper-search and identity tools were visible after reconnect,
but returned MCP `Internal error`; primary arXiv records were used as the
fallback.  No external code, model, dependency, or learned checkpoint is added.

## Chosen Architecture

Use model-predictive Monte Carlo tree search over compressed Empty Maximal Space
(EMS) actions.

1. Build support-aware 2D free rectangles for each floor, shelf, and eligible
   placed-item top.
2. Generate a small deterministic action catalog by fitting every visible item
   orientation to EMS corners, wall alignments, and heightmap minima.
3. Apply the existing exact continuous validator to every root action.  This is
   the feasibility mask and remains the only source of actions policy may return.
4. Simulate deeper tree nodes with conservative AABBs, support rectangles,
   protection rules, and the official Y-then-X swept path.  Expensive depth-map
   and continuous checks are not repeated at every rollout node.
5. Run an anytime MCTS/MPC search over the visible batch.  Return the first
   action of the best validated root branch, settle it in PyBullet, then rebuild
   and replan from observation.

The method is neither a fixed-lane layout nor a single scalar aperture penalty.
It plans a sequence of mutually compatible actions and directly estimates how
many visible items remain jointly packable.

## EMS and Heightmap State

Each `SupportLayer` contains:

- container and support owner identifiers;
- support height and usable `Rect` union;
- protection attributes inherited from supporting items;
- a 20 mm conservative height/occupancy grid used only for fast scoring;
- non-overlapping maximal free rectangles maintained by guillotine splitting
  and containment pruning.

For a footprint, proposals come from each fitting EMS's four corners, centre,
and alignments with neighboring occupied faces.  Six official orientations are
considered, but dominated duplicates are removed.  Wide items can span any old
lane boundary.

Root proposals are converted to production `Candidate` objects only through the
existing inclusion, collision, path, support, centre-support, priority, soft,
and depth checks.  Rollout proposals use a conservative subset and can never be
returned directly.

## Search

An `MCTSNode` stores the compressed packing state, remaining visible items,
incoming action, visits, value, and children.

- Selection uses UCB with deterministic tie-breaking.
- Progressive widening limits each item/orientation/EMS expansion.
- Expansion prioritizes scarce large items, heightmap minima, rear placement,
  low centre of gravity, and low fragmentation.
- Rollouts use randomized best-fit decreasing with a deterministic seed derived
  from observation geometry; no process-global randomness is used.
- Transpositions are keyed by quantized occupied AABBs plus remaining item IDs.
- The search stops at an absolute deadline and returns the best fully validated
  root action already available.

Root rank is lexicographic:

```text
(
    maximum rollout packed-item count,
    maximum rollout packed volume,
    minimum rule violations,
    maximum remaining largest-EMS volume,
    maximum minimum ingress slack for remaining width classes,
    minimum heightmap roughness and void volume,
    minimum mass-weighted centre of gravity,
    existing secondary score,
)
```

No unseen mode-B or mode-C item distribution is invented.

## Mode Behaviour

### A

The 150-second optimizer runs the same compressed search over all known items,
optimizing item order and an approximate layout skeleton.  A complete exact
skeleton is accepted when available; otherwise the best robust order is returned
only if replay under the compressed feasibility model exceeds the original
order by a fixed validation margin.  Online policy always revalidates the next
action after physical settling.

### B

Use all visible pool items, including large lookahead pools.  Search depth is
the pool size, with progressive widening and rollouts making this cheaper than
the current exact beam expansion.  Count of jointly packable visible items is
the primary objective.

### C

With a one-item pool, choose the exact-validated action minimizing heightmap
increase, fragmentation, and protected-column loss.  No fictitious future item
is sampled.

## Time and Failure Handling

- Reserve at least 0.35 seconds for formatting and simulator overhead.
- Root exact-candidate generation receives a bounded budget.
- MCTS stops no later than 5.40 seconds from policy start.
- `policy` returns only an exact-validated root action.
- If MCTS has no root action, use the existing depth-aware emergency path.
- The rejected monotone and geometry-rescue experiments remain default-off.
- All loops check absolute deadlines; exceptions preserve the best validated
  root already found.

## Alternatives

1. **Joint aperture scalar only:** inexpensive, but previous experiments show
   local scores cannot coordinate several future placements.
2. **Full 30 mm 3D voxel reachability:** expressive, but too expensive and
   discretization-sensitive for the six-second online budget.
3. **Learned DRL policy:** potentially strong but requires a training and
   generalization pipeline not justified before a competitive deterministic
   planner exists.

The selected EMS-MCTS approach provides batch coordination without new runtime
dependencies or a learned model.

## Test and Adoption Strategy

### Pure unit tests

- EMS split, prune, and fit invariants;
- shelf/floor/protected support layers;
- heightmap-minimizing placement;
- wide item spanning prior proxy lanes;
- rollout path and support rejection;
- deterministic transposition key;
- progressive widening and UCB selection;
- hard deadline returns the best validated root;
- mode A/B/C behavior and exact action contract.

### Snapshot tests

- replay task000 and task001 terminal snapshots;
- compare jointly packable counts before choosing the first action;
- prove the chosen branch beats the legacy branch on at least one saved
  pre-terminal state without relaxing safety.

### Physical gates

1. Official four-item smoke: 4/4 safe.
2. task000/25: 25/25 safe.
3. task001/30: 30/30 safe.
4. maximum policy below 6 seconds; every action safe.
5. full unit discovery, compileall, ZIP import test, and content audit.

Only a variant passing all five gates is packaged and submitted.  Each SIGNATE
submission changes one recorded factor.  Public score below 60 triggers
diagnosis from the returned score and the next controlled variant; it is not
reported as completion.  The guarded ZIP remains immutable evidence.

## Scope and Constraints

- Standard library and NumPy only in the submission.
- No global install, simulator-source modification, external network at
  evaluation time, Git initialization, or credential inspection.
- Public `Agent` signatures and action dictionary remain unchanged.
- SIGNATE authentication remains user-owned; the already configured local CLI
  may be used only after local acceptance gates pass.
