# Current optimization

2026-09-16. Public results remain in the registry. The new
[support recovery ZIP](submission_candidate/README.md) preserves historical A/B
results and the measured C recovery. Its Public score is pending.

| Mode | Historical control | Strongest compared successor | Decision |
| --- | --- | --- | --- |
| A, task000 | 25/41 safe; fill 33.944 | Offline planner: 24/41; fill 30.261 | Keep historical control; rear-first variant also regresses |
| B, task001 | 23/42 safe; fill 21.070 | Progressive recovery: 22/42; fill 25.450 | Higher fill, one fewer placement; drop recovery rejected |
| C, task001 | 18/42 safe; fill 17.852 | Historical prefix + progressive recovery: 23/42; fill 25.185 | Local gain; shuffled holdout ties the control |

All listed comparisons use seed42 and the unchanged sample item stream. Earlier
prototypes raise a policy error on exhaustion. The submission wrapper now uses
an explicitly recorded terminal rejection to retain partial evaluation.

Additional mode-C pairs: shuffle17 ties at 16/42 and fill 17.971; the generated
two-container case completes all 42 items for both controllers, with fill 21.788.
The successor improves one of three conditions and ties two, while using more
runtime (maximum 4.044 seconds across these candidate runs).

- [Native search and recovery](native_candidate_packing/README.md): source variants, settings, and complete results.
- [Fair search history](fair_candidate_packing/README.md): rejected allocation and preview variants.
- [Offline planning](offline_settling_plan/README.md): virtual settled layouts and rejected rear-first ordering.
- [Preview calibration](finite_mesh_preview/README.md): measured continuing cargo motion explains a false-safe drop prediction.
- [Additional validation conditions](validation_cases/README.md): lookahead3/40 and a second offset container.

Read individual result JSON files for exact code/configuration hashes, actions, final geometry, and timing. A saved-state recovery must survive full replay before it supports an improvement claim.

## Next decision

Motion estimates rejected one known unsafe drop but still authorized another
physically unsafe action. Future-ingress ranking either tied the control or
regressed after spatial diversification. Neither is in the submission ZIP.
The immediate next evidence is Public evaluation of that exact archive. Further
development should change the packing trajectory before first exhaustion and
demonstrate a full matched gain; isolated recovered actions and larger search
caps have not been sufficient. The Public target remains unmet.
