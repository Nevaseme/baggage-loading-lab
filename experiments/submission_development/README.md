# Submission development — 2026-09-16

User requested resumed algorithm development through a submission-ready ZIP.

## Design and acceptance

The main successor ranks placements by remaining visible cargo's insertion opportunities after virtual placement. A/B exploit known cargo; C starts from the historical-prefix progressive control. Compare against historical A/B and progressive C on identical streams, then validate untouched conditions. Keep a change for useful count/fill improvement within official runtime limits. Avoid broad search-cap tuning without a recovered physical trajectory.

A separate predictor estimates continuing motion from public observation/action history. Measured simulator velocities are diagnostic truth only. Integrate only if it fixes false-safe predictions without unacceptable false rejections or runtime cost. A bounded support-relaxation probe tests whether historical support heuristics hide native-valid stable recoveries.

## Execution

1. Implement and test future-ingress ranking (`experiments/ingress_lookahead/`) and motion estimation (`experiments/motion_state_preview/`) in separate scopes.
2. Run matched full physics comparisons, inspect first failure, and revise the causal weakness.
3. Freeze a self-contained candidate, independently review returned actions and lifecycle behavior, and run all official samples plus generated/held-out conditions.
4. Build the exact submission ZIP, extract it into a fresh directory, run the official lifecycle on that extraction, and record hashes, metrics, and remaining Public-score uncertainty.

Root owns integration, full benchmarks, packaging, and final decision. Workers own their named packages; the lifecycle reviewer is read-only. Source and full result records from prior experiments remain unchanged.

## Terminal protocol decision

Official `runner.py` propagates policy exceptions; `app.py` records `evaluation: null`
and skips later tasks. The public API has no stop action. On exhausted search, the
submission wrapper therefore returns a well-formed action within the supplied
coordinate range, with observed-plane validation proving rejection before any
physical placement. This deliberately ends the episode and retains its partial
evaluation. It is recorded as terminal rejection, not a valid placement or an
improved completed episode. `test_terminal.py` verifies official format checks,
termination without truncation, and unchanged existing score. Ordinary placement
actions still require all native checks and complete-preview acceptance.
