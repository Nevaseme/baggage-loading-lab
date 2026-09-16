# Task 3 Brief — Deterministic anytime MPC-MCTS

Implement only Task 3 from `docs/superpowers/plans/2026-08-13-mpc-mcts-ems-packing.md`.

## Files

- Create `simulator/agents/highscore/mcts.py`
- Create `simulator/tests/test_highscore_mcts.py`
- Modify `simulator/agents/highscore/settings.py`
- Write `.superpowers/sdd/2026-08-13-mpc-mcts-ems-packing/task-3-report.md`

Do not edit Agent, Planner, catalog, candidates, EMS, simulator core, or unrelated tests. No Git, installs, packaging, or submission.

## Required public API

```python
@dataclass(frozen=True, order=True)
class RolloutValue:
    packed_count: int
    packed_volume: float
    neg_violations: int
    largest_space_volume: float
    minimum_ingress_slack: float
    neg_roughness: float
    neg_cog: float

class MCTSSearch:
    def __init__(self, settings: SearchSettings): ...
    def choose(self, roots: Sequence[RootAction], pool: Sequence[ItemSpec],
               *, deadline: float, seed: int) -> Candidate | None: ...
```

Add exact settings defaults:

```python
mcts_exploration: float = 1.15
mcts_progressive_k: float = 2.0
mcts_progressive_alpha: float = 0.50
mcts_rollout_limit: int = 64
mcts_transposition_quantum: float = 0.01
mcts_policy_limit_seconds: float = 5.40
```

## TDD sequence

1. RED lexicographic-value tests: packed count dominates all lower fields, then packed volume, then fewer rule violations. RED UCB tests: unvisited child before visited; stable action-key tie break.
2. Implement node/value/UCB primitives. Keep scalar total/mean backup separate from lexicographic best rollout; final root choice must use `RolloutValue`, never scalar mean alone.
3. RED synthetic planning test with two exact `RootAction`s: immediately attractive/lower first root fits only 2 visible items total, other fits 3; choose must select 3. Test progressive widening bound `children <= floor(k*visits**alpha)`, finite rollout, and same controlled clock+seed deterministic result.
4. Implement expansion/rollout. Each root begins from its exact `next_state`; remove exactly that root pool entry, not unseen/future items. Expansion ranks scarce/large visible items and low-waste proxy actions. Use only `propose_actions` + `apply_action`, no Candidate at deeper proxy levels. Use local `random.Random(seed)`, top-3 best-fit selection, no global RNG, no Python randomized hash. Cache by `state_key(proxy_state, remaining IDs, quantum)` without conflating root rule violations.
5. Rollout value is root-aware: count/volume includes the exact root plus feasible deeper placements; violations includes exact root candidate violations; largest free-space volume, ingress slack, surface roughness and mass-weighted CoG are deterministic finite features. Handle empty spaces/zero mass safely.
6. RED deadline tests for expiry during selection, expansion and rollout; return the best exact root already evaluated. Exceptions in one root/node/rollout must preserve a previously evaluated exact Candidate. `choose` returns only `RootAction.candidate` or None, never ProxyAction.
7. Verify focused MCTS; MCTS+EMS+catalog; at least 20 controlled deterministic repetitions; full `test_highscore_*.py` discovery. Report exact RED/GREEN commands, counts/timing, files, self-review, concerns.

## Invariants

- Standard library + NumPy only; float64 features.
- Deterministic stable tuple keys use item/pool/container/orientation/quantized AABB, not object identity.
- Deadline check in selection, proposal, expansion, apply, rollout, backup loops; preserve incumbent on timeout.
- Visible pool only. Item identity uses pool position for removal and ItemSpec.index for state keys; duplicates must not remove multiple entries.
- `roots=[]` or deadline already expired returns None safely.
- MCTS never weakens Task1 geometry/protection rules and cannot directly escape the Task2 exact-root mask.
