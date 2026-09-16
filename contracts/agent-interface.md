# Agent interface

Reference: the supplied `simulator/README.md`, Dockerfile, and `simulator/src/ground_handling/`, checked 2026-09-16. Use the actual distribution as authority when its version changes. Its source and configurations are now shared in the private repository; installed dependencies remain local.

## Calls and observation

Implement `Agent` in `agent.py`:

| Call | Contract |
| --- | --- |
| `Agent(module_path)` | Initialize from the module directory |
| `get_init_states(init_states)` | Receive `optimize`, `lookahead_k`, and `container_list` |
| `optimize(item_list)` | Return a list of item `index` values for mode A ordering |
| `policy(observation)` | Return the action below for the current observation |

Observations contain `optimize`, `lookahead_k`, `depth_map`, `pool_list`, and `container_list`. Mode A exposes all items for advance planning; B selects from visible lookahead; C sees one item. Future unseen items are unavailable to the policy.

```python
{
    "item_idx": int,             # current pool_list position, not permanent item index
    "container_idx": int,        # current container_list position
    "place_pos": numpy.ndarray, # shape (3,), dtype float32; item center
    "orientation": int,          # 0..5
}
```

`place_pos` is relative to the container's `(offset_x, 0, 0)` origin. Packed item `pos` is in world coordinates and `orn` is an `(x, y, z, w)` quaternion. Settled items may no longer be axis-aligned. Pool indices change as items are consumed.

## Geometry and physics

Containers include `length`, `width`, `height`, `thickness`, `buffer`, `cut_x`, `cut_y`, `require_shelf`, `is_prioritized`, and `packed_items`. Model wall thickness, cuts, and shelves as geometry. Items include dimensions, mass, soft/priority flags, pose, friction, restitution, and damping; soft items also have contact properties.

Orientations in the supplied README: 0 unchanged; 1 X90; 2 Y90; 3 Z90; 4 Y90 then Z90; 5 X90 then Z90. Match transforms to the implementation.

Validate current-state actions through the official insertion route, including Y insertion and X translation. Final-position collision checks alone miss transport failures. Compare analytical approximations and extra support/protection heuristics with simulator outcomes.

## Runtime and results

The supplied Dockerfile uses Python 3.12, Gymnasium 1.2.3, PyBullet 3.2.7, Pillow 10.3.0, and CPU Torch 2.7.0. Registry tooling uses only the standard library.

The evaluation README specifies initialization 10 s, policy 8 s, optimization 180 s, and memory 12 GB. Local configurations can differ. Choose internal deadlines with margin justified by measured overhead and runtime variability, as specified in the evaluation contract.

Public total, external feedback components, and local `fill_score` are separate metrics. Feedback `num_placed_items` is the placed fraction. Do not infer missing score weights or thresholds.

An action with `is_valid=false` may never reach placement; a simultaneous `is_placed_safe=false` does not establish collapse. Classify failure using execution order. See the [evaluation contract](../docs/evaluation-contract.md).
