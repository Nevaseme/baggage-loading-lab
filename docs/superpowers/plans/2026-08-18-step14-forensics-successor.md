# Step 14 Forensics and Successor Implementation Plan

## Phase 1: authoritative failure classification

1. Add RED tests for a three-mode forensic runner: complete-episode-before-shadow-diagnostics ordering, immutable snapshots, route capture, partial atomic JSON on failure, action-sequence divergence, and canonical failure classification.
2. Implement the smallest non-production runner without editing historical agent packages or simulator behavior.
3. Run task001/42/seed42 in control, trace-only, and trace-plus-probe modes.
4. Compare the first divergence, route, exact validation, timings, and official statuses. Save all pre-action snapshots and JSON.
5. Add a focused RED regression for the classified production defect in a new successor package, not the historical package.

## Phase 2: algorithm selection

1. Score the three independent architecture proposals against the failure evidence, prior Public 29.7435 baseline, candidate recall, exact safety, A/B/C requirements, and runtime risk.
2. Select one primary architecture and one bounded challenger only when their factor differs materially.
3. Write the selected package contract: candidate source, exact validator boundary, mode routing, search objective, deadlines, and fallback guarantee.
4. Reject Quota-Fair unless recovered roots change selected action/value or physical outcome.

## Phase 3: TDD implementation and review

1. Create a new descriptive package by copying only reusable production components, preserving the public API.
2. Implement candidate recall and exact validation first, then mode-specific selection/search.
3. Add unit tests for all new geometry/candidate/search behavior and regression snapshots.
4. Run focused, related, full highscore, compile, and import tests.
5. Obtain independent Sol medium/high specification and code-quality reviews; fix every Critical/Important issue with RED/GREEN evidence.

## Phase 4: physical A/B and iteration

1. Compare historical 29.7435-compatible baseline, current Exact-Root EMS MPC control, and the successor on sample tasks with identical seeds/settings.
2. Run generated A/B/C cases with multiple seeds and record the canonical result schema.
3. Reject variants that reduce safety, completed placements, or principal score proxies without a compensating material gain.
4. If the primary successor remains far below the target, move to the ranked challenger architecture rather than tuning a weak local optimum.
5. Repeat while local evidence supports a plausible Public improvement; Public score remains the final arbiter.

## Phase 5: acceptance and ZIP

1. Require all unit/integration/regression tests green.
2. Require official PyBullet/Gymnasium runs through natural completion or first fully classified physical failure.
3. Require policy p99 below 5.5 seconds and max below 6 seconds.
4. Audit extracted ZIP layout, compile/import/API, default planner activation, action reproduction, and source hashes.
5. Write the final descriptive ZIP and SHA-256 and update `progress.md`.
