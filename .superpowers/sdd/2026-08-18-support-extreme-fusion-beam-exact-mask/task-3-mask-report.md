# Task 3: strict exact mask report

## Scope

Writer-owned files:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/mask.py`
- `simulator/tests/test_support_extreme_fusion_mask.py`
- this report

No proposal, planner, state, model, geometry, agent, settings, or historical
submission file was edited by this task.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError: No module named
'agents.support_extreme_fusion_beam_exact_mask.mask'
```

An additional RED fixture proved that combining two half-footprint supports
whose top heights differ by 5 mm falsely produced a valid 100% support union.
The mask now evaluates support per coplanar layer (1 mm grouping tolerance), so
unequal-height surfaces cannot manufacture a platform.

Focused GREEN command:

```powershell
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe `
  -m unittest tests.test_support_extreme_fusion_mask -v
```

Result at implementation completion: `Ran 13 tests ... OK`.

## Implemented contract

`ExactMask.validate` is fail-closed and returns either a freshly minted strict
`ValidatedRoot` or `None`. `ExactMask.revalidate` matches the Agent callback
contract and refuses a different settings profile. It re-runs all predicates
and returns fresh field-matching evidence; a boolean is never authorization.

The receipt binds:

- ordered pool position and immutable item metadata index/signature;
- public Gym container ordinal plus container raw metadata through the full
  state fingerprint;
- all six official orientation dimensions and exact proposal position;
- canonical `SearchSettings.profile_digest()`;
- strict support and clearance metrics, zero rule violations, and proposal
  provenance.

The exact predicates cover:

- deadline and exception fail-closed behavior;
- prioritized-item fixation to an available prioritized container;
- conservative plane inclusion;
- target collision and the agent's conservative 18 mm horizontal
  clearance proxy (stricter than the official 15 mm minimum);
- floor frontier and shelf front-release gating;
- floor, physical shelf top, small shelf and axis-aligned placed-top supports;
- rigid/soft support ratios, complete 4 cm centre core and coplanar layers;
- priority, soft and combined column protection;
- effective transport lift, door aperture and Y-then-X swept path;
- depth-map/model disagreement.

`ValidationTrace` records acceptance, fresh root, first/failing reason, support
ratio, required support, minimum clearance, effective lift and safe exception
detail.

Normal items are intentionally accepted in a prioritized container when all
physical and protection predicates pass. Ordinary-first routing is a catalog
exposure policy, not exact geometry. The next Catalog task must test that a
deferred prioritized-container root is not exposed while at least one ordinary
root exists, while still exposing that deferred tier when ordinary roots are
empty. Prioritized items remain fixed to prioritized containers whenever one
exists.

## Step 14 regression

Against `task001_step14_control_failure.npz`:

- historical last-resort action (pool 4/item 17,
  `[0, 0.4920000136, 0.1780000031]`, orientation 0) is rejected first by
  `collision_or_clearance`;
- Public-29.7 shadow action (pool 3/item 16,
  `[-0.172, -0.2195, 0.193]`, orientation 0) is rejected first by
  `floor_frontier`.

Thus neither historical unsafe action can become a strict root.

## Related-suite status

The first combined run exposed 19 proposal-writer integration errors at
`proposals.py:553`: `_surface_center_bounds` was temporarily called without its
new `legal_bounds` and `settings` arguments. This task did not edit that shared
writer scope. After that writer completed, the fresh integration command was:

```powershell
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe `
  -m unittest tests.test_support_extreme_fusion_contract `
  tests.test_support_extreme_fusion_proposals `
  tests.test_support_extreme_fusion_mask -v
```

After the mask/Catalog responsibility correction, the fresh result was
`Ran 47 tests in 0.647s` and `OK`. A following `py_compile` of `mask.py` and
`test_support_extreme_fusion_mask.py` also exited 0.

The full project discovery was run from the repository top level so both the
`simulator.tests` package and `agents` package had their required import roots:

```powershell
$env:PYTHONPATH = '.;simulator'
C:\Users\TAKUMI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe `
  -m unittest discover -s simulator/tests -t . -p 'test_*.py' -q
```

Fresh result: `Ran 223 tests in 6.439s` and `OK`.

## Review correction: mask versus Catalog responsibility

A focused RED proved that the initial exact mask rejected a physically valid
normal-item proposal solely because its target container was prioritized. That
made the proposal generator's deferred priority tier unreachable. The policy
gate was removed from the mask; its new regression is GREEN. Only prioritized
items remain fixed to a prioritized container. Ordinary-first suppression is
explicitly assigned to the next Catalog task as described above.

## Known conservative choices

- Shelf placement needs the configured 22 mm `shelf_drop_gap`; placing only
  8 mm above the physical shelf top fails the agent's conservative 18 mm
  swept-path proxy. The contest's official minimum is 15 mm, so this is an
  intentional safety margin/parity choice rather than an official threshold.
- Support faces more than 1 mm apart are never unioned. This is deliberately
  conservative and may reduce root count on visibly unsettled stacks; tilted
  boxes already remain obstacles rather than support sources.
