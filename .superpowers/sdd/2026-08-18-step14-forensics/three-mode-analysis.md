# Step 14 Three-Mode Physical Analysis

Date: 2026-08-18

## Outcome

The task001 / 42 items / seed 42 failure is not caused by trace or probe instrumentation.

Control, trace-only, and trace+probe were run with independent fresh PyBullet environments and agents. The live policy path was unwrapped in all three modes. Route tracing, exact validation, and probing ran only after each physical environment had closed.

All three modes:

- returned the same 15-action sequence;
- had action-sequence SHA-256 `97b58c7d9546a9727d41c11f8ade2c4658238ccff209685cd0bcbe374681f455`;
- had no first divergent step;
- completed 14 safe placements;
- failed on zero-based step 14;
- returned pool index 4 / item 17, container 0, orientation 0 at `[0.0, 0.492000013589859, 0.17800000309944153]`;
- received `is_included=true`, `is_valid=false`, `is_placed_safe=false`;
- replayed the route as `deterministic_last_resort` with no authoritative candidate;
- failed strict post-episode shadow validation;
- were classified `unchecked_last_resort_transport_defect`.

Failed-step policy times were 5.750520593 s, 5.750329050 s, and 5.750344836 s for control, trace-only, and trace+probe.

Validator collision telemetry was identical: item 17 collided with item 11 at `(0.0, -0.134, 0.178)`, with distance `0.01246067472503443 m`.

## Decision

- Reject the diagnostic-interference hypothesis for this reproduction.
- Do not treat this as a Quota-Fair result; root scheduling was never meaningfully evaluated after the policy reached a strict-root-zero state.
- Treat the immediate defect as an unchecked last-resort transport failure.
- Treat the upstream design problem as a likely earlier support/ingress dead-end. The successor must change earlier choices using future strict-root coverage, support-union capacity, and ingress preservation; adding more terminal fallback coordinates alone is insufficient.

## Evidence

- `three-mode-summary.json`
- `three-mode-summary-control.json`
- `three-mode-summary-trace.json`
- `three-mode-summary-trace_probe.json`
- `three-mode-snapshots/`

