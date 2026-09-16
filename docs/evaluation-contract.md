# Submission evaluation contract

Updated 2026-09-16. Apply this gate when promoting a submission candidate. Exploratory changes need only the checks relevant to their hypothesis.

## Target and comparison

Success is a verified Public score of at least 60 plus a reproducible, independently checked ZIP. Compare A (offline), B (lookahead 3-40), and C (one visible item) separately against the strongest relevant control. Match tasks, seeds, item streams, configuration, and host. Keep Public scores, feedback aggregates, and local proxies distinct.

## Promotion evidence

1. **Correctness:** Pass relevant unit, integration, and regression suites. Resolve failures affecting the candidate; document the treatment of host-sensitive tests.
2. **Physics:** Run every official sample and multiple generated conditions/seeds to natural termination or first physical failure. Record attempts, safe placements, first failure step/predicate, and termination cause. Candidate exhaustion or a shield rejection is an early stop.
3. **Improvement:** Show paired safety and main score-proxy improvement, per-mode results, and worst regressions. Measure count alongside fill/layout quality. Explain measured tradeoffs. Resolve malformed or unchecked actions and investigate invalid or unsafe placement attempts. Report explicit terminal rejection separately: the supplied API has no stop action, and a policy exception discards the task's evaluation. A tested, well-formed terminal rejection may preserve partial results after search exhaustion; it does not count as successful packing.
4. **Metrics:** Record `fill_score`, placed count/ratio and denominator, mass-weighted CoG proxy, soft/priority violations, support ratio, post-placement translation/rotation, policy p50/p95/p99/max, fallback rate, and success after fallback. Label unavailable components and substitute proxies explicitly.
5. **Runtime:** Meet the actual evaluation limits: the supplied README specifies 10 s initialization, 8 s policy, 180 s optimization, and 12 GB memory. Record workload, host, sample size, warmup, and p50/p95/p99/max across full episodes. Set internal deadlines with margin justified by measured overhead and variability; fixed historical 6 s/5.5 s gates are not universal requirements. Sample further when tail uncertainty affects acceptance.
6. **Exact ZIP:** Extract the archive and verify layout, imports/dependencies, public API, planner/fallback paths, and action reproduction. Record SHA-256 and source/configuration/runner hashes. Obtain independent review of material planner or validation changes.

## Interpretation

Declare candidate-specific decision criteria before comparing. Revise them prospectively with a dated reason; retain the original result. Historical count gates and fixed timing sample sizes are experiment choices, not universal requirements.

Calibrate geometry, transport, and extra safety checks against the official implementation and physical outcomes. Save pre-action snapshots for diagnostics that could perturb a live simulation. Distinguish transport rejection from post-placement instability. A missing candidate is not evidence of physical impossibility; stopping safely is not an improvement in score.

See the [Agent contract](../contracts/agent-interface.md) for interface details and the [registry workflow](registry-operations.md) for recording the submission.
