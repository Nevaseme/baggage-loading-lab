# Task 2 Brief — Exact root feasibility mask and compressed catalog

Implement only Task 2 from `docs/superpowers/plans/2026-08-13-mpc-mcts-ems-packing.md`.

## Files

- Modify `simulator/agents/highscore/candidates.py`
- Create `simulator/agents/highscore/catalog.py`
- Create `simulator/tests/test_highscore_catalog.py`
- Modify `simulator/agents/highscore/settings.py`
- Write `.superpowers/sdd/2026-08-13-mpc-mcts-ems-packing/task-2-report.md`

Do not edit simulator core, Agent integration, MCTS, EMS, or unrelated tests. No Git operations or installs.

## Required interfaces

```python
@dataclass(frozen=True)
class RootAction:
    candidate: Candidate
    proxy_action: ProxyAction
    next_state: ProxyState

def CandidateGenerator.validate_proposal(
    self, state: PackingState, action: ProxyAction, *,
    allow_rule_violations: bool = False,
) -> Candidate | None: ...

def build_root_catalog(
    state: PackingState, pool: Sequence[ItemSpec], generator: CandidateGenerator,
    settings: SearchSettings, *, deadline: float,
) -> list[RootAction]: ...
```

Add settings with these exact defaults:

```python
ems_proxy_actions_per_item: int = 24
ems_exact_roots_per_item: int = 6
ems_root_catalog_limit: int = 48
ems_root_budget_seconds: float = 1.35
```

## TDD sequence

1. Add RED tests proving `validate_proposal` equivalence for floor, shelf, and stack proposals. It must preserve orientation, box, support ratio, rule violations, and path outcome from the existing validation path. Add rejection fixtures for collision, support, priority, depth-map, and official swept-path clearance.
2. Run focused RED and record exact failure.
3. Implement the wrapper by routing through existing `_validate_position`; do not duplicate hard geometry. Resolve container by `action.container_index`, preserve `action.pool_index`, derive the same obstacles/floor/shelf/fill/support target, and require the action's exact centre/orientation.
4. Add RED catalog tests: exact-only roots, at least two fitting pool items, fair deadline budget, valid proxy successor for each root, determinism.
5. Implement bounded catalog: build one `ProxyState`; give each remaining item a fair-share absolute subdeadline; request at most 24 proxy actions/item; exact-validate in proxy order; keep at most 6/item; global cap 48. Sort deterministically by rule violations, item urgency/rarity, support, clearance, lower top height, item/pool/container/orientation/position IDs. Do not let one item consume the entire clock.
6. Add fake-clock and throwing-validator tests. On deadline or per-action exceptions, return all roots already validated. Isolate failures so a bad item/action does not discard earlier roots.
7. Run focused catalog+EMS+candidates and full `test_highscore_*.py` discovery. Report RED/GREEN commands, counts/timing, files, self-review and concerns.

## Constraints

- Standard library + NumPy only.
- Compute in float64.
- Preserve current public candidate generation behavior.
- Every `RootAction.candidate` must be returned by the exact existing validator, never by proxy alone.
- Every root must have a non-None `apply_action` successor using the same clearance.
- Deadline checks belong in item, proposal, validation, sorting/assembly loops where meaningful.
- Deterministic output for the same state/pool/deadline allowance.
- `use_monotone_ingress` and `use_geometry_rescue` stay default False.
- Do not package or submit.
