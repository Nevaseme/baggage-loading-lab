# Finite container preview calibration

Status: **not a validated recovery controller**. The finite boundary hypothesis does not explain the controlled-drop false positive. Do not promote this package or tighten the displacement limit to conceal the mismatch.

The standalone preview derives an inset five-sided cup and cut-side closure from observed dimensions. It adds the runtime's standard ground plane and shelf boxes in creation order. No simulator implementation is imported. Packed bodies use their observed poses and dynamics; missing velocities start at zero. The acceptance rule remains a complete 300 steps, displacement at most 0.30 m, and angle at most 45 degrees.

| Saved placement | Actual | Plane prediction | Finite prediction |
|---|---|---:|---:|
| Progressive B step 22, raised 0.06 m | Unsafe, about 0.38 m | Safe, 0.25425 m | Safe, 0.21758 m |
| Native B step 20 recovery | Safe | 0.05763 m | 0.06763 m |
| Support-diverse B step 17 recovery | Safe | 0.05732 m | 0.05959 m |
| Aligned B step 17 tower | Unsafe | 0.47112 m | 0.38166 m |

`mesh-calibration.json` records source and state hashes, exact actions, full preview outputs, and potentially contended timings. On the failed drop, generating an OBJ from the same independent geometry predicts 0.21661 m (`obj-loader-calibration.json`), versus 0.21758 m in memory. Loader precision is too small here to explain the observed gap. Finite geometry also predicts a 0.177775 cubic metre inside-to-outside change for previous items on the native20 control, despite the new bag being safe; score protection needs separate calibration.

The public observation has no linear or angular velocities. Ordinary successful placement advances exactly 300 steps and then reports updated poses; it does not zero old body velocities or wait for sleep. The initial container build has a separate sleep loop, which does not apply between ordinary placements. Contact manifold caches are also absent from reconstruction.

## Measured velocity experiment

`velocity_replay.py` replays only the fixed saved 22-action prefix without loading any Agent. This diagnostic imports the official environment; the standalone `source/` does not. Its observed cargo state matches the saved snapshot exactly. It measures velocity immediately before the failed drop, then compares the same official world with velocities retained versus zeroed. It also supplies those measured velocities to the independent finite preview solely for calibration.

| World | Initial packed velocity | Displacement | Decision |
|---|---|---:|---|
| Official replay, existing contacts | Retained | 0.379822 m | Unsafe |
| Official replay, existing contacts | Zeroed | 0.306246 m | Unsafe |
| Finite reconstruction | Zeroed | 0.217579 m | Incorrectly safe |
| Finite reconstruction | Measured | 0.342137 m | Unsafe |

Actual initial speeds were 0.353539 m/s for item13, 0.268934 m/s for item12, and 0.124260 m/s for item23. Their angular speeds were about 0.336 rad/s. These are substantial continuing motions, not numerical noise. Injecting measured velocities flips the finite predictor to the correct decision without changing official safety limits. In the official world, removing velocities reduces displacement by 0.073575 m; velocities matter but are not the entire discrepancy. The measured-velocity finite result remains 0.037685 m below actual, leaving geometry, contact history, and solver-state differences unresolved. These effects interact and should not be treated as additive error terms.

`velocity-replay.json` records all measured vectors, source/simulator/state hashes, exact action, outcomes, and timings (28.48 s total, marked contended). The preview API's optional velocity injection is a diagnostic facility: **those hidden values are unavailable to a submitted Agent**. This result does not validate production prediction or establish a recovery. A future observation-only state estimator would need independent validation before relying on inferred velocities.

## Next implementable path (not implemented)

Maintain a bounded observation-only state estimator using the previous observation and the last accepted action. For an accepted action, retain predicted final packed poses and velocities from its complete 300-step preview. At the next policy call, reconcile those predicted poses against the newly observed poses, reset geometry to the actual observations, and update estimated velocity from the prediction residual and pose change over the known 1.25-second physics interval. Quaternion changes can similarly inform angular motion. Pose differences alone give interval-average motion, not exact instantaneous velocity; prediction residuals must therefore remain explicit uncertainty rather than being treated as measurements.

Only previous/current public observations, accepted actions, and private predictions may enter that estimator. Never read the official physics client, hidden body IDs, or measured replay velocities inside candidate code. First calibrate the estimator on saved consecutive observations from safe controls and this failed drop, recording predicted versus diagnostic measured velocities, false-safe and false-reject rates, pose residuals, and runtime. Promote neither the finite preview nor controlled-drop package on the evidence here. Geometry and contact-history uncertainty still needs independent checks even if estimated velocity improves the failed-drop prediction.

Reproduction from the existing simulator runtime:

```
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/finite_mesh_preview/probe.py --output ../experiments/finite_mesh_preview/mesh-calibration.json
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/finite_mesh_preview/obj_probe.py
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/finite_mesh_preview/test_mesh.py
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/finite_mesh_preview/velocity_replay.py
```

The original progressive/drop snapshot cargo state is identical; their raw JSON hashes differ only because shared-memory names differ. Original native and plane-preview packages remain unchanged.
