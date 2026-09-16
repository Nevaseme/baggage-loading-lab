# Review package: offline complete skeleton guard

## Production change

`Agent.optimize` now accepts an optimized permutation only if `len(skeleton) == len(items)` in addition to the existing permutation checks. Every other path clears `offline_skeleton` and returns the original input order.

## Tests

- Incomplete skeleton: fake planner returns `[13, 5, 8]` with two skeleton entries for three items; expected result is `[5, 8, 13]` and an empty stored skeleton.
- Complete skeleton: fake planner returns `[13, 5, 8]` with three skeleton entries; expected optimized result and the same stored skeleton object.

## Evidence

See `docs/superpowers/plans/2026-08-13-offline-complete-skeleton-guard-report.md`.
