# Submission evaluation contract

Reviewed 2026-09-08 against the user's acceptance requirements and the 2026-08-24 candidate gates. This is the submission gate, not a checklist for every edit. Algorithm choice and exploratory methods remain open; old candidate-specific thresholds retain their historical scope.

## Success and comparison

The target is a verified Public score of at least 60 and a reproducible submission artifact. A local improvement or test pass establishes only its measured claim. A lower Public result feeds the next design during authorized development; a user pause still takes effect immediately.

Evaluate separately: A uses all items for offline ordering/planning; B uses the available lookahead (3–40); C uses one visible item. Compare with the strongest relevant control under matched task, seed, item stream, configuration, and host conditions. Keep Public totals, external feedback aggregates, and individual local episodes distinct.

## Required evidence for a submission candidate

- Passing unit, integration, and regression suites, with any host-sensitive or previously failing test resolved and its treatment documented.
- Official PyBullet/Gymnasium runs on every sample through natural termination or the first physical failure, plus generated multiple conditions and seeds. Record attempts, safe placements, first failure step/predicate, and termination cause. A shield rejection or candidate-zero stop is not natural completion.
- Paired safety and main score-proxy improvement against the strongest relevant control, with per-mode results and worst regressions visible. Resolve malformed, unchecked, ingress-invalid, and settle-unsafe returned actions before claiming readiness. Compare count together with fill and layout quality; a count-only gate from an old candidate is not a universal scoring objective. Explicitly justify any proxy tradeoff with measured evidence. Experimental failures remain useful evidence but do not establish submission readiness.
- Local `fill_score`, both placed count and ratio with denominator, mass-weighted CoG proxy, soft/priority protection violations, support ratio, translation/rotation after placement, policy p50/p95/p99/max, fallback rate, and success after fallback. Label unavailable official components as pending and substitute measurements as proxies.
- Policy maximum below 6 seconds and p99 below 5.5 seconds, measured on a fixed host with a documented representative workload, sample size, warmup treatment, and full-episode timing. The prior 10-warmup/200-call campaign is a starting protocol, not proof of tail reliability; increase sampling when tail uncertainty matters. Verify initialization, optimization, and lifecycle deadlines from the actual evaluation configuration and allow headroom. On 2026-09-08 the locally supplied simulator README was checked: it states initialization 10 seconds, policy 8 seconds, optimization 180 seconds and memory 12 GB. These are documented in the [portable contract](../contracts/agent-interface.md); this supersedes the earlier audit's uncertainty about the local 180-second value, without claiming that remote competition rules cannot change.
- Extract the exact ZIP and verify its file layout, dependencies/imports, public API, planner and fallback paths, and action reproduction. Record archive path and SHA-256. Include relevant independent review for material planner/validation changes.

## Evidence integrity

Bind comparisons to source/configuration/runner hashes and seeds. Keep historical submissions unchanged. Save normal pre-action snapshots for post-episode diagnostics where live probing could affect physics. Distinguish a transport rejection from post-placement instability using the actual execution sequence.

Validate safety checks against official geometry/transport behavior and physical outcomes. Additional support, protection, or clearance heuristics need measured justification: both false acceptance and excessive rejection can harm the objective. Missing candidate coverage alone is not proof of physical impossibility, and restored coverage alone is not a score improvement.

Predeclare candidate-specific promotion criteria before its comparison. Revise a criterion prospectively when evidence warrants it, preserving the prior result and reason for the revision. Changes to user acceptance targets or external authority boundaries require user direction.
