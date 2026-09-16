# Task 10 — E2 official-mask proposal recall

## Outcome

Removed two policy heuristics from strict exact acceptance:

- two-lane floor-frontier balance;
- early front-floor release in shelf containers.

These were placement-order preferences, not official physical validity
predicates. Otherwise safe proposals can now become strict roots. No new score,
penalty, or fallback path was introduced, so this task changes one experimental
factor only.

The strict receipt profile was bumped from
`support-extreme-fusion-strict-v1` to
`support-extreme-fusion-strict-v2`. A receipt issued under v1 is stale and the
Agent formatter rejects it before action construction.

## Production changes

### `mask.py`

Removed from `_validate_exact`:

- `_floor_frontier_balanced(...)` hard rejection;
- fill-ratio/front-Y `SHELF_FRONT_RELEASE` hard rejection;
- the two obsolete `RejectReason` values;
- the now-unused `_floor_frontier_balanced` helper and fill-ratio calculation.

The remaining strict order still checks:

1. state, ordered pool occurrence, item identity, and container ordinal;
2. priority-container eligibility;
3. 18 mm horizontal collision clearance;
4. conservative container-plane inclusion;
5. support ratio and 4 cm center core;
6. independent priority/soft protection rules;
7. effective lift and official Y-then-X transport path with 18 mm clearance;
8. depth-map blocking;
9. state/profile/item/proposal-bound receipt issuance.

No plane, path, clearance, support, core, protection, tilt, or depth tolerance
was changed.

### `settings.py`

`STRICT_VALIDATION_PROFILE_VERSION` is now v2. The legacy
`lane_frontier_skew` and `front_floor_release_fill` dataclass fields remain as
configuration compatibility fields for existing callers and historical test
fixtures, but the strict mask no longer reads them. Their presence does not
restore either acceptance gate.

Back-first and lane-preservation behavior remains in existing proposal ordering
and the beam's ingress/fragmentation future features. No separate feature
penalty was necessary.

## TDD evidence

The safe synthetic fixture first failed against the old mask because a floor
proposal that skewed the two lanes returned `None`:

```text
AssertionError: None is not an instance of ValidatedRoot
```

After removing the two non-official predicates, both cases issue strict roots:

- a safe floor proposal with frontier skew greater than the former
  `lane_frontier_skew` limit;
- a safe front-floor proposal in an empty shelf container, below the former
  20% release fill.

The v1-staleness fixture first failed because the pre-change formatter accepted
the reconstructed v1 receipt. After the profile bump it fails closed with a
profile-digest mismatch.

Existing physical regressions remained active:

- plane inclusion and 18 mm collision clearance;
- Y-then-X transport and effective-lift blocker;
- support ratio and center-support core;
- soft support threshold;
- non-coplanar support separation;
- tilted-top exclusion;
- priority and soft column protection;
- depth-map blocking;
- deadline and validator exception fail-closed behavior.

## Historical action classification

The two task001 step14 actions were re-evaluated without the policy gates:

- historical last-resort action: rejected by `collision_or_clearance`;
- Public-29.7 shadow action: rejected by `collision_or_clearance`.

The regression now asserts this concrete remaining physical reason. It no
longer permits a heuristic `floor_frontier` explanation and makes no claim that
the old action was otherwise safe.

## Step9 replay evidence

Snapshot:
`simulator/results/support_extreme_fusion/task001-b-seed42-e1-failure.npz`

Under the v2 mask and the production scanner:

- the 5.45-second deadline produced at least one current strict root;
- the focused run produced the catalog in about 1.8 seconds;
- the selected object was the identical depth-zero catalog root;
- the real Agent formatter freshly revalidated it and produced the public
  action ordinals.

A manual diagnostic immediately before the production edit, with only the two
gates test-time disabled, found 10 normal roots after about 1.805 seconds. This
supports the single-factor interpretation: the snapshot was recall-starved by
the policy predicates rather than by official geometry.

## Fresh verification

Project-bundled WSL runtime and project-local dependencies:

```text
mask + step9 focused:             15 tests, PASS, 1.950s
support_extreme_fusion combined: 133 tests, PASS, 11.281s
simulator full suite:            320 tests, PASS, 16.626s
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -v
```

## Files changed

- `simulator/agents/support_extreme_fusion_beam_exact_mask/mask.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/settings.py`
- `simulator/tests/test_support_extreme_fusion_mask.py`
- `simulator/tests/test_support_extreme_fusion_agent_bc.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-10-e2-official-mask-recall-report.md`

No beam, proposal, catalog, Agent production, simulator, or physical runner code
was changed. No physical episode was run in Task 10; a fresh task001 B seed42
episode is the next external evidence step.
