# Support-Extreme Fusion Beam with Exact Mask Implementation Plan

1. Create the standalone package contract and immutable `PlacementProposal` / `ValidatedRoot` types. Prove public API and current-state-only formatting with RED/GREEN tests.
2. Implement pure proposal families and deterministic provenance-aware deduplication. Do not port approximate validators or scoring from the 29.7435 agent.
3. Connect proposals to the strict exact mask. Add one RED fixture for every hard rejection and the task001 step-14 last-resort rejection.
4. Build the three-pass round-robin catalog. Test pool coverage, duplicate-ID isolation, exception/deadline incumbent preservation, caps, determinism, and zero-root-only rescue.
5. Gate proposal recall on saved snapshots before implementing new search. At step 14, recover any strict root found by an exhaustive bounded shadow scan; if none exists, record the state as a certified dead-end and make avoidance of that state the beam regression. Keep every old strict-positive root.
6. Implement deterministic B beam and C one-step selector with lexicographic objectives, exact-root-only return, bounded deadlines, and repeated determinism tests.
7. Implement complete Mode-A order/skeleton planning, strict online revalidation, and stale-plan repair. Reject partial skeletons.
8. Add route/fallback telemetry and canonical benchmark/proxy aggregation outside policy timing.
9. Run one-factor physical gates in order: proposal union only, selector/beam only, Mode-A skeleton only, then combined A/B/C.
10. Obtain independent Sol medium/high reviews after each material boundary and fix all Critical/Important findings with TDD.
11. Audit the strongest extracted package, produce `support-extreme-fusion-beam-exact-mask_<timestamp>.zip`, compute SHA-256, and update `progress.md`.
