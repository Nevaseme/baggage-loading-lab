# Future-Support / Ingress Beam Implementation Plan

## Goal

Complete `support_extreme_fusion_beam_exact_mask` as a standalone submission candidate that improves decisions before the task001 step-14 dead state. Every public action must be a depth-0 strict root for the current settled observation and ordered pool, freshly revalidated immediately before formatting.

## Non-negotiable invariants

- No MCTS, EMS, historical `highscore`, or 29.7-package runtime dependency.
- No unchecked fallback or fabricated action when the strict catalog is empty.
- Safe predicted placement count and volume are lexicographically above all secondary features.
- Beam descendants are ranking evidence only; only the original current-state root may be returned.
- Mode is fixed at initialization: A when optimize is enabled, otherwise B when initial lookahead is greater than one, otherwise C.

## Task 1: Fair strict-root catalog

Create `catalog.py` and `test_support_extreme_fusion_catalog.py`.

- Scan fused proposals through `ExactMask` only.
- Preserve pool-position identity, including duplicate global item IDs.
- Use deterministic staged fairness across pool positions.
- Normal proposals are scanned first. Deferred priority-container proposals are hidden while any ordinary-container strict root exists and exposed only after ordinary strict-zero. Rescue scans only rootless items.
- Return immutable `RootCatalog`, per-pool roots, rejection counts, coverage, deadline state, and stable ordering.
- Deadline or exception yields a deterministic partial catalog, never a root invented from a raw proposal.

## Task 2: Immutable transition and future features

Create `transition.py`, `features.py`, and `test_support_extreme_fusion_transition_features.py`.

- Deep-clone state and append hypothetical placements only to the child.
- Remove the selected pool occurrence while preserving original pool-position mapping.
- Revalidate all child roots on the child state.
- Compute bounded float64 proxies for exact-root coverage/rarity, compatible support capacity, ingress access, free-support fragmentation, mass-weighted CoG, protection-compatible area, support/clearance margin, and maximum stack height.

## Task 3: Deterministic B/C beam

Create `beam.py` and `test_support_extreme_fusion_beam.py`.

- B: width 20, depth up to 4, six item choices, two roots per item.
- C: one-step strict ranking only, with no future-arrival assumptions.
- Rank by proven exact count, proven volume, future coverage, then robustness/support/ingress/fragmentation/CoG/stability.
- Preserve the best exact incumbent at every deadline and under isolated branch exceptions.
- Prove deterministic output over repeated runs and verify no forbidden imports.

## Task 4: Mode A and Agent integration

Create `offline.py`; update `agent.py`, `settings.py`, and `__init__.py`; create `test_support_extreme_fusion_agent_modes.py`.

- A uses the complete list with rolling exact beam: width 48, depth 4, eight item choices, six roots per item.
- Reserve five seconds from the 150-second optimize budget for permutation validation and return.
- Keep a placement skeleton only if every input occurrence is planned; otherwise keep only the order and discard stale coordinates.
- Online policy always rebuilds settled state and strictly revalidates a planned coordinate or performs strict repair.
- Candidate-zero raises a descriptive error and records telemetry; it never emits a fallback action.

## Task 5: Earlier-prefix and physical gates

- Capture/control snapshots at steps 0, 4, 8, and 12/13 without in-policy instrumentation.
- Compare old/new actions, strict-root coverage, four-step compatible count/volume, support capacity, ingress, fragmentation, and CoG.
- Require a decision-relevant divergence before step 14 and a full physical run beyond the old failure with no earlier predicate failure.
- Run task000 A, task001 B with lookahead 3/10/20/40, explicit C lookahead 1, and multiple seeds.
- Record safe steps, first failure, fill/count, all proxy metrics, fallback/candidate-zero rate, and policy p50/p95/p99/max.

## Completion gate

- All focused, integration, regression, and physical tests pass.
- Unchecked action returns are zero; required-case candidate-zero is zero.
- Policy p99 is below 5.5 seconds and maximum below 6 seconds.
- The strongest candidate has a descriptive ZIP name, verified extraction/import/API/action replay, SHA-256, and a complete `progress.md` entry.

