# Observation-only motion carry

This prototype fixes the demonstrated false-safe drop **on one saved sequence** without rejecting its 22 preceding safe placements. It is ready for integration testing, not submission promotion.

The finite-mesh preview previously assumed packed items began at rest, predicting 0.217579 m displacement for a drop that actually moved 0.379822 m. This package carries predicted final velocities from the last selected action's complete preview. It reconciles all geometry to the next actual observed poses before predicting another action. No measured velocity, simulator object, hidden body ID, or private environment state enters candidate code.

## Fixed interface

Import `MotionStatePreview` from `source.motion` (or the corresponding submission package's `.motion`). Construct one instance per Agent, with `residual_gain=0.0` by default.

```python
preview = MotionStatePreview()
trial = preview.evaluate(container, item, action, deadline=policy_deadline)
if native_valid and trial['safe']:
    preview.accept(trial)  # Only after selecting the action actually returned.
    return action
```

`evaluate` retains existing preview arguments and safety fields: `steps=300`, `inclusion_margin=-0.005`, optional monotonic `deadline`, `safe`, displacement, angle, timing, and previous-item volume effects. `safe` requires all 300 steps. It additionally returns `inferred_velocity_count` and a JSON-compatible `_motion_frame`. Keep that frame for `accept`; it need not be included in routine diagnostics. `accept` copies the selected complete frame and refuses partial previews. Speculative or rejected trials never update estimator history. Call `reset()` at a new episode and `close()` at shutdown. A context manager is supported.

Call `accept` only when the action is selected for return. It intentionally does not independently authorize transport or action safety: those remain the caller's responsibility. During diagnostic replay, a historical action is committed after a complete prediction even if prediction disagrees with its known actual safe outcome, allowing false rejections to be measured without changing the fixed sequence.

Unknown or unexpected packed-item sets start at zero velocity; only the most recently selected container has a retained frame. Alternating containers therefore currently discard stale carry for other containers. Optional `residual_gain` adds pose prediction residual divided by 1.25 seconds to velocity, but only the default zero-gain behavior was calibrated. It should remain zero until a matched experiment warrants changing it.

## Evidence

`replay_probe.py` replays the fixed 22-action prefix from the saved controlled-drop B result without loading an Agent or searching for actions. Source receives only each public observation and selected action. The diagnostic separately reads official velocity as evaluation truth, never supplying it to the predictor. The final saved drop is previewed only. `sequential-carry.json` retains source hashes, state hashes, actions, complete predicted states, measured truth, and decisions.

| Check | Prediction | Actual label |
|---|---:|---|
| 22 safe prefix actions | All accepted | All safe |
| Step20 native recovery | 0.064701 m | Safe |
| Step21 last safe placement | 0.214842 m | Safe |
| Step22 raised drop | 0.321407 m, rejected | Unsafe; actual 0.379822 m |

There were zero false rejections and zero false-safe decisions across these 23 saved actions. The sequential diagnostic took 52.12 seconds; individual complete previews peaked at 2.6203 seconds with timings marked contended. An 8-second policy must share its deadline across generation, native validation, and preview; these measurements do not authorize extra candidate trials beyond that deadline.

This is a useful causal result, not proof of general reliability. The failed-drop prediction still underestimates displacement by approximately 0.0584 m. The default finite reconstruction differs in geometry loading and contact history, and inferred motion can accumulate error. No full new policy episode was run and no Public score was measured. Root integration must retain current-state native validation for every returned action and compare mode-specific full trajectories before considering promotion.

Reproduce from the existing simulator runtime:

```
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/motion_state_preview/test_motion.py
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/motion_state_preview/replay_probe.py
```

Owned files are isolated here. The earlier finite, drop, native, and scored packages remain unchanged.
