# Step 14 Forensics and Successor Algorithm Design

## Objective

Determine why task001 fails at step 14 without changing historical agents or scored archives, then use the result to build a descriptively named successor that improves completed safe placements and score proxies. Quota-Fair is retained only if it becomes decision-relevant.

## Current evidence

- The normal, non-instrumented MPC control reproduces the step 14 failure.
- The selected action is item pool index 4 / item 17, container 0, orientation 0, position `[0.0, 0.4920000136, 0.1780000031]`.
- Policy time is 5.75084 seconds.
- The authoritative result is `is_included=true`, `is_valid=false`, `is_placed_safe=false`.
- Because the environment calls placement only after the transport-path check succeeds, the primary failure is the official transport path. `is_placed_safe=false` is downstream and does not independently prove instability.
- All ten legacy emergency candidate scans reported zero candidates. The action geometry matches the deterministic last-resort construction, but route provenance still needs explicit capture.

## Forensic runner

Create a non-production runner with three modes using the same task, seed, settings, and agent:

1. `control`: no catalog trace and no starvation probe.
2. `trace`: the full normal physical episode runs first; catalog traces run only after termination/failure on saved pre-action snapshots.
3. `trace_probe`: the full normal physical episode runs first; traces and probes run only after termination/failure on saved pre-action snapshots.

The physical episode must never run a shadow trace/probe between physical steps. Each step atomically saves a pre-action snapshot before physical execution. After the episode terminates or reaches its first failure, the runner analyzes the immutable snapshots. Partial JSON must be written even on the first false status or exception.

Per-step records include:

- selected action and pool/item identity;
- exact policy elapsed time;
- route: `mpc`, `emergency_depth`, `geometry_rescue`, `deterministic_last_resort`, or failure route;
- whether an authoritative exact candidate object was returned by that route;
- post-policy shadow exact-validation outcome and reason, clearly labelled diagnostic;
- environment statuses in canonical order;
- transport collision telemetry obtainable without modifying historical production packages;
- hashes of the pre-action observation/action to compare modes.

The runner compares action sequences and reports the first divergent step. Failure classification is one of:

- diagnostic interference;
- exact-root or emergency candidate safety defect;
- unchecked last-resort transport defect;
- policy timeout/runner fallback;
- unresolved, with missing evidence listed.

## Safety correction gate

If control reaches the deterministic last resort, no successor may return that unchecked placement. A successor action must originate from an exact validator-approved candidate. If no original candidate exists, candidate recall must be expanded; suppressing the action alone is not a solution because the public API still requires an action.

## Successor candidates

The first implementation candidate is selected only after forensics. The current preferred direction is a fusion of high-recall extreme/support-frontier coordinates with the strict current validator, followed by a bounded deterministic beam/regret search. MCTS is not required. Alternative C-space maximal-rectangle and slot-stack designs remain independent challengers.

Mode-specific behavior is permitted:

- Mode A: full-list ordering plus coarse placement skeleton; revalidate every online action.
- Mode B: visible-pool regret and future-space search across lookahead 3--40.
- Mode C: one-item exact candidate selection with broad coordinate recall and short deterministic scoring.

## Evaluation contract

Every physical episode reports:

- completed `env.step` calls and final placed count;
- first failure step, all false predicates, and primary reason;
- local `fill_score` and `num_placed_items`;
- mass-weighted CoG, support, protection, displacement, and rotation values labelled as proxies;
- nearest-rank policy p50/p95/p99/max;
- fallback route frequency and post-fallback success;
- explicit A/B/C benchmark metadata rather than inference from task identifiers.

Diagnostics are outside the policy timing window. Policy p99 must remain below 5.5 seconds and maximum below 6 seconds.

## Preservation and packaging

- Do not modify historical submission archives or score-labelled packages.
- Each algorithm variant uses a new descriptive snake-case package name.
- The accepted ZIP contains one top-level production package, no tests, snapshots, caches, or bytecode.
- Extracted compile/import/API/action-reproduction checks must pass.
- Record the ZIP path, SHA-256, algorithm summary, verified Public result fields, and missing fields in `progress.md`.
