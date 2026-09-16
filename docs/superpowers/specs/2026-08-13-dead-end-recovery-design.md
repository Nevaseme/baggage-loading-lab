# Dead-end replay and recovery design

## Objective

Improve the high-score agent's A/B completion rate without weakening the official
inclusion, transport-clearance, centre-support, or protection constraints. The
immediate target is a deterministic workflow for reproducing a candidate-zero
state and a bounded recovery generator that can find placements missed by the
normal extreme-point cross product.

## Considered approaches

1. Increase the normal coordinate and beam limits. This is simple but already
   exceeded the policy budget in dense states and still returned zero candidates.
2. Relax support or clearance constraints. This risks immediate episode failure
   and contradicts the safety-first objective.
3. Preserve the fast normal search and invoke a support-surface free-rectangle
   search only when it returns zero candidates. This is the selected approach:
   it targets the observed failure mode without slowing ordinary decisions or
   weakening hard constraints.

## Snapshot and replay

`tests/run_physics_smoke.py` will optionally write the observation immediately
before a failed action. The snapshot is a compressed NumPy archive containing a
JSON-safe copy of `container_list` and `pool_list`, plus the depth map as an array.
No PyBullet IDs or process-specific shared-memory names are stored.

A separate replay utility loads the snapshot, rebuilds `PackingState`, runs the
normal and recovery candidate generators for every pool item, and prints candidate
counts, timings, and best actions. Unit tests cover a round trip through the same
serialization helpers. Snapshots are diagnostic artifacts and are not part of the
submission agent.

## Recovery candidate generation

The recovery generator operates per orientation and per usable support level:
floor, main shelf, small shelf, and axis-aligned placed-item tops. It discretizes
the support plane at 20 mm, marks cells blocked by horizontally expanded obstacles,
and uses an integral image to enumerate positions whose full item footprint is
free. Candidate centres are sampled at free-run boundaries and maximal-clearance
cells, ordered from back to front.

Every recovered position is passed through the existing authoritative checks:

- conservative plane inclusion;
- horizontal obstacle clearance;
- support union ratio and 4 cm centre support;
- protection-column rules;
- official-style effective lift and Y-then-X swept AABB;
- auxiliary depth-map comparison.

The recovery search has its own small candidate cap and checks the shared policy
deadline in every loop. It runs only after all normal relaxation stages have
returned zero candidates.

## Planner integration

`CandidateGenerator.generate` retains its existing public contract. Internally it
tries extreme points first, then the current local perturbation, then free-rectangle
recovery. Returned candidates use the existing `Candidate` model and scoring path,
so A/B/C planners require no special cases.

If recovery also returns zero, the current deterministic last-resort behavior is
retained. Hard safety thresholds are never relaxed by recovery.

## Testing and acceptance

- Unit-test snapshot serialization with NumPy values and exact reconstruction.
- Unit-test a synthetic fragmented support surface where extreme points miss a
  feasible placement but recovery finds it.
- Assert every recovery result passes the same support, collision, and inclusion
  checks as a normal candidate.
- Re-run all existing unit tests and `compileall`.
- Replay captured A/B candidate-zero states without restarting PyBullet.
- Run official multiprocessing smoke tests and long sample regressions.

Success for this increment means deterministic failure replay works, recovery adds
safe candidates in at least one previously missed state, ordinary policy latency
does not regress, and no existing test fails. Full sample completion remains the
optimization target, not a claim made by this design.
