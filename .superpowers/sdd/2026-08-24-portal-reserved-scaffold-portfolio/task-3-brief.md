# Task 3 brief — Official-semantics shield and historical-plan cross

Read `C:\Users\TAKUMI\projects\Baggage-Loading\AGENTS.md` first and obey it.
Task 2 evidence must have a clean Sol review before this task starts. Historical
artifacts under `submit/` are immutable and may not be imported at runtime.

## Goal

Create the new algorithm package `portal_reserved_scaffold_dag` with a single
fresh current-state authorizer. In this task, the historical Public-29.7
virtual plan/order/action policy is only a proposal seed. Reproduce its known
safe action prefix while rejecting its known failed action before `env.step`.
Do not add portal reservation, a new planner, repair search, or score tuning yet.

## Evidence that constrains the design

- Task 2 replay contains 25 officially safe actions and one `is_valid=false`
  action at zero-based step 25.
- Current ExactMask accepts only 4/25 safe actions and rejects the failure 0/1.
- False results on known-safe actions overlap: plane 7, 18 mm target clearance
  5, support ratio 10, center support 8, protection 5, 18 mm swept transport 5.
- Official sample semantics use inclusion margin `-0.005 m`, transport contact
  margin `0.015 m`, Y then X motion in 0.01 m samples, and PyBullet settling.
- Current `-0.008 m`, 18 mm AABB, 75/90% support, 2 cm core, protection, and
  depth gates are not valid substitutes for official process validity.
- The step-25 failure has zero target clearance and failed transport. It must
  be rejected by the transport/penetration evidence, not by support/protection.

## Files

- Create `simulator/agents/portal_reserved_scaffold_dag/__init__.py`.
- Create `simulator/agents/portal_reserved_scaffold_dag/authorizer.py`.
- Create `simulator/agents/portal_reserved_scaffold_dag/historical_seed.py`.
- Create `simulator/agents/portal_reserved_scaffold_dag/agent.py`.
- Create `simulator/tests/test_portal_reserved_scaffold_authorizer.py`.
- Create `simulator/tests/test_portal_reserved_scaffold_historical_cross.py`.
- Create `simulator/tests/run_portal_reserved_scaffold_historical_cross.py`.
- Produce `simulator/results/portal_reserved_scaffold/task000-official-shield-cross-seed42.json`.
- Write `.superpowers/sdd/2026-08-24-portal-reserved-scaffold-portfolio/task-3-report.md`.

Do not modify current production agents, Task 2 code/evidence, the physical
environment, `progress.md`, or anything under `submit/`.

## Required public and internal interfaces

The package exports the official `Agent` with the same constructor and public
methods as the competition interface. Returned action dictionaries retain the
exact official keys and value types.

`authorizer.py` defines immutable types equivalent to:

```python
ActionProposal(
    route,
    pool_ordinal,
    item_index,
    item_signature,
    container_ordinal,
    container_metadata_index,
    orientation,
    position_f32_le,
    source_key,
    proposal_digest,
)

AuthorizationResult(
    accepted,
    proposal,
    state_fingerprint,
    profile_digest,
    hard_evidence,
    settling_evidence,
    score_evidence,
    reject_reasons,
)

authorize_current(proposal, observation, profile=None, deadline=None)
format_authorized_action(result, observation, profile=None, deadline=None)
```

The proposal stores the canonical little-endian 12-byte float32 position.
Every check promotes those same bytes to float64. Formatting must not introduce
a second rounding path.

The state fingerprint includes ordered pool occurrences and full item
signatures, container ordinal/metadata/dimensions/planes/normals/shelf flags,
all packed item signatures and raw poses/quaternions, and profile semantics.
The proposal digest includes the canonical float32 bytes. A changed pool order,
packed quaternion, container, profile, or selected occurrence makes an earlier
authorization stale.

`format_authorized_action` performs a fresh authorization on the supplied
current observation and compares proposal/profile/fingerprint/hard evidence.
A boolean, copied/forged/replaced result, result from a different state, or an
unaccepted result cannot format an action. Planned, repair, and emergency route
labels all use this same function; Task 3 implements only the historical route.

## Three separate evidence layers

### Hard official-semantics evidence

- exact action key/type/range/finite checks; booleans are not integers;
- ordered pool occurrence and full selected-item binding;
- canonical container ordinal and metadata binding;
- official float32 plane inclusion with margin `-0.005 m`;
- Y-then-X path with official start clamp, effective lift/ceiling clipping,
  0.01 m sample locations, and `0.015 m` contact margin;
- genuine positive-volume target penetration.

Do not add an independent 15–18 mm target-nearness hard gate. Contact and tiny
positive numerical overlap are reported, while only proven penetration or
transport obstruction rejects.

### Settling feasibility/risk evidence

Report support ratio, center/COM support, predicted drop, lower landing surface,
landing support, supporter pose/load, stack height, mass, and softness where
calculable. The former 75/90%, 2 cm core, and 12 mm contact-layer rules are risk
features, not hard validity.

Only an unambiguous impossibility may reject: no lower landing surface or a
minimum predicted drop strictly greater than the official displacement limit
of 0.3 m. Because the positive corpus has no settling failure, do not claim
that this predicts general PyBullet stability.

### Score-proxy evidence

Priority-container routing, hard-on-soft/priority, CoG, support, stack height,
and depth-map consistency are ranking/diagnostic values only. None directly
sets `accepted=False` in this task.

## Transport implementation boundary

Match official constants and sample positions. Use settled item orientation in
collision geometry; do not inflate a tilted item to its broad world AABB when
an oriented-box/contact calculation can distinguish it. Static shelf geometry
may remain exact axis-aligned boxes. Record any remaining approximation.

The Task 2 corpus is a recall gate, not permission to special-case step numbers,
item IDs, seed, positions, or recorded hashes. Production authorizer code may
not read Task 2 result files.

## Historical proposal seed

`historical_seed.py` contains a standalone adaptation of the historical
virtual-order/plan/action policy. It may copy and attribute required algorithmic
logic, but it may not import, compile, read, or depend on `submit/` at runtime.
Preserve the historical full-stream virtual optimization, partial plan,
heavy/rigid tail, planned targets, and action selection for this cross.

Every candidate becomes an `ActionProposal`. Delete/bypass no rejected action.
The historical unchecked fallback is not an authorization route. If the seed
cannot propose or the authorizer rejects, raise a typed fail-closed diagnostic
exception before `env.step`; do not return a dummy or previous action.

## TDD sequence and RED requirements

Write focused tests before implementation and record the expected package-
missing/current-4-of-25 RED output.

Required captured-corpus tests:

- at least 24/25 known-safe actions authorize;
- step 25 does not authorize;
- recovered plane steps 0,1,2,3,5,16,17 pass the official margin;
- safe close-contact/transport cases pass while step 25 fails;
- support, center, protection, and depth remain diagnostic, not hard validity.

Required synthetic negative/boundary tests:

- every plane: float32 inside `-5.0001 mm` passes and `-4.9999 mm` fails;
- cut plane, nonzero container X offset, and world/local conversion;
- contact gap `15.001 mm` passes, `14.999 mm` fails, equality is conservative;
- door start-X clamp; lift 0, 0.08, and ceiling-clipped partial lift;
- orientation-4 small-shelf case and a tilted settled OBB that broad AABB would
  falsely reject;
- genuine target penetration rejects while contact/nearness is risk evidence;
- drop `0.300001 m` rejects and `0.299999 m` is not rejected for that reason;
- a free-floating no-landing-surface negative;
- 67% partial support, 14 mm settling gap, priority/soft violation do not hard
  reject by themselves;
- pool reorder, duplicate item index with different occurrence, packed raw pose
  or quaternion, container ordinal, and profile changes stale authorization;
- NaN, infinity/float32 overflow, bool-as-int, NumPy integer, invalid orientation,
  and expired deadline reject;
- forged/copy/`dataclasses.replace`/different-state authorization cannot format;
- historical/planned/repair/emergency route labels cannot bypass the authorizer.

Expected values in synthetic tests are hand-derived literals. Do not derive
expected outputs from the production helper being tested.

Run focused tests with the canonical project-local WSL runtime:

```text
cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator
PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest \
  tests.test_portal_reserved_scaffold_authorizer \
  tests.test_portal_reserved_scaffold_historical_cross -v
```

Then run Task 2 regressions and the relevant existing agent tests. Compile all
new package and runner files.

## Matched physical cross

The new runner uses task000, 41 items, seed42, Mode A lifecycle and the same
PyBullet/Gymnasium environment. It records immutable package/config/runner/
historical-source/action-prefix hashes, every policy time, returned versus
rejected attempts, first rejection reason, official statuses, fill, and count.

Run with the canonical WSL runtime and save raw stdout/stderr. The cross passes
only if all are true:

- serialized returned actions for steps 0–24 equal the Task 2 historical prefix;
- at least 24 actions are safely placed and local fill is at least 32;
- step 25 is rejected before `env.step` rather than returned;
- zero returned actions have `is_valid=false` or `is_placed_safe=false`;
- no unchecked/dummy fallback is used;
- policy maximum is below 6 seconds;
- historical artifacts and the 20-file `submit/` manifest remain unchanged.

The stretch reproduction target is 25 safe placements and fill
`33.94392679167531`. Task 3 remains a diagnostic candidate even if it passes;
production promotion still needs Task 4 continuation and later A/B/C physical
negative coverage.

## Report

Write the full report to `task-3-report.md`: RED/GREEN, focused/regression
commands, corpus recall/reject reasons, synthetic coverage, physical cross,
action-prefix divergence, fill/count/timing, hashes, changed files, immutable
artifact checks, limitations, and self-review. Do not spawn subagents.

