# Motion-aware drop recovery

Self-contained integration candidate based on frozen `controlled_drop_recovery` proposals and the frozen `motion_state_preview` estimator. Mode B keeps the same candidate ranking, support filters, narrow-first/wide fallback, and raised-release fallback. Every returned action requires current-state native inclusion/target/transport validation and a complete safe 300-step motion preview.

The shared policy budget is 7.2 seconds and the native authorization limit is 384. These values also apply to mode C. `get_init_states` enables the historical proposal prefix only when lookahead is one and optimization is disabled (mode C). Mode A inherits the unchanged historical `optimize` ordering. No separate support-relaxation experiment is integrated.

Motion estimates update only at the three successful policy return points. Rejected native/preview proposals cannot commit a frame. Initialization resets motion history, pending previews, native worlds, and historical-prefix activity. Routine diagnostics omit the internal predicted-state frame. New source receives only public observations, selected actions, and private predictions; official simulator imports exist only in other diagnostic experiments, not this package.

The predecessor's fixed-sequence calibration accepted all 22 safe prefix actions and rejected the previously false-safe drop at 0.321407 m displacement (actual 0.379822 m). This is integration evidence, not a new episode score. Full mode-specific benchmarks are required before promotion.

From the simulator directory:

```
env PYTHONPATH=.:tests:.test_deps_linux .venv_wsl/bin/python ../experiments/motion_recovery/test_agent.py
```

The source directory preserves the public `Agent(module_path)`, `get_init_states`, `optimize`, and `policy` interface and can be passed directly to the existing benchmark runner. Use an external 8-second policy deadline to leave room around the shared internal 7.2-second budget. No scored or earlier experiment source was modified.

## Compared recovery

The first full B run preserves 22/42 and fill25.4502, correctly rejects the known
unsafe drop, and exhausts its 7.2-second budget on further previews. A different
cargo's complete preview was still unevaluated at the deadline. Completing that
trial separately predicts displacement0.2578m with no existing-volume loss.

`variants/diverse_release/` first filters raised candidates through native
validation, then gives each physical cargo type a preview turn, lighter cargo
first to reduce load on existing supports. Normal placement ranking is unchanged.
The saved-state regression recovers that cargo with a complete motion preview
inside the same budget. Full replay rejected the variant: it retained 22/42 and
fill 25.4502, then the proposed cargo moved 0.36 m in the official simulator
despite a 0.2578 m preview prediction. Continuing velocity estimates do not
reproduce contact history accurately enough to authorize these raised drops.
The submission candidate excludes this recovery. Raw results are retained under
`results/diverse-release-b-task001-seed42.json`.
