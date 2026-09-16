# Depth-Aware Geometry Rescue Design

## Objective

Prevent a conservative or stale depth map from forcing the invalid deterministic
last-resort action when the settled `packed_items` geometry still contains a
safe, officially valid placement.  The public baseline is
`12.622949582873819`; the local task001 baseline is 20 safe placements.

## Evidence

At the saved task001 step-20 failure, depth-aware generation returned no safe
candidate for the visible ten-item pool and the deterministic fallback failed
`is_valid` and `is_placed_safe`.  The existing diagnostic harness rebuilt the
same observation from `packed_items` without the depth map and reached 24 safe
placements under real PyBullet before the entrance became physically blocked.

The depth map remains the primary source.  Geometry-only rescue is entered only
after the normal depth-aware planner returns no candidate.  All inclusion,
container/shelf collision, settled-item swept-AABB, 18 mm path clearance,
support, centre support, and protection checks remain unchanged.

## Algorithm

1. Run the normal online planner against `packed_items` plus `depth_map` until
   the existing soft deadline.
2. If it returns no candidate and hard-deadline time remains, rebuild the state
   from the same settled `container_list` with no depth map.
3. Sort visible items by the existing emergency order and divide the remaining
   hard-deadline budget fairly over the remaining items.
4. Generate geometry-validated emergency candidates for every item that gets a
   time slice; score all found candidates and return the lexicographically best
   candidate by rule violations, score, support, clearance, and height.
5. Use the deterministic API-format fallback only when both stages find zero
   candidates.

## Safety and Adoption Gate

- Geometry rescue must never run before depth-aware planning fails.
- A rescue candidate must come from the unchanged production validator.
- No simulator source or dependency changes.
- task000 must not regress below 17 safe placements.
- task001 must strictly exceed 20 safe placements.
- Every action before the first failure must have all official statuses true.
- Maximum policy time must remain below 6 seconds.

If the gate fails, revert the production rescue while retaining diagnostic
evidence.  Only after this gate may the next MaxRects/layer batch-planning factor
be introduced.
