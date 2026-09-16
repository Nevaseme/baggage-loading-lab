# Quota-Fair EMS MPC Root-Scheduling Experiment

## Objective

Determine whether exact-root catalog starvation is a material cause of poor
mode-B performance, then increase exact-root coverage across the full visible
item pool without changing the EMS coordinate generator, official validation
path, scoring, MCTS, or fallback behavior.

This is a controlled root-scheduling experiment, not by itself a credible
29.74350010538-to-60 strategy. It primarily targets mode B, where the visible
pool contains 3--40 items. Modes A and C expose one item to online policy and
therefore receive essentially no direct benefit. A broader 60-point roadmap
still requires later, separately measured work on proposal recall, placement
quality, mode-A ordering, and physical stability.

The new algorithm and package are named `quota_fair_ems_mpc`. The historical
`simulator/agents/highscore/` package, historical ZIP files, and the two scored
artifacts under `submit/` remain unchanged.

## Evidence boundary

SIGNATE exposes only aggregate Public scores for the submitted agents. It does
not expose completion status, placed-item count, or component scores through
the browser or SIGNATE CLI 0.12.0. Therefore the 29.74350010538 versus 11-point
difference cannot be attributed to a specific failure mode.

This experiment is evaluated through reproducible local PyBullet/Gymnasium
runs and paired single-factor control/variant Public submissions only after
local acceptance gates pass.

The bundled local evaluator exposes only `fill_score` and
`num_placed_items`. It does not calculate the official `cog_score`,
`stability_score`, `placement_score`, or `soft_item_score`. Local reports must
label any centre-of-gravity, support, or protection measurements as proxy
metrics rather than official component scores.

## Phase 0: prove the starvation mechanism

Do not implement the scheduling change until the current exact-root EMS MPC
shows at least one reproducible starvation case. A non-production diagnostic
runner records, for every visible pool position:

```text
pool_index, item.index, urgency, proposal_count, validated_count,
accepted_root_count, start_time, end_time, stop_reason
```

The trace must call the unchanged production `build_root_catalog` and wrap its
real `propose_actions`, validator, `apply_action`, and clock collaborators. It
must not reproduce the catalog loop. Stop reasons are classified from the
observed production call sequence, catalog size, and clock as `global_cap`,
`catalog_deadline`, `not_visited`, `proposal_exhausted`, `per_item_quota`, or
`unknown`.

For positions omitted by the production catalog, an independent bounded probe
uses the unchanged `propose_actions`, validator, and `apply_action` to determine
whether at least one exact root existed. It also records time-to-first-exact
root. A recoverable starvation case requires all three conditions:

1. the production catalog assigned zero roots because the 48-root cap or
   1.35-second catalog deadline was reached; and
2. the independent probe found at least one exact-valid root for that same
   pool position and observation; and
3. time-to-first-exact-root was no greater than the pass-1 fair share expected
   for that position at the observed lookahead and remaining catalog budget.

Run this diagnostic on saved high-density snapshots, the full task001 sample,
and the fixed generated manifest below. Proceed only when at least three
distinct lookahead-20/40 observations show recoverable starvation and the
recoverable-starvation frequency is at least 5% of measured lookahead-20/40
states. Report the numerator, denominator, stop reasons, and time-to-first-root
distribution. Otherwise stop without changing production code and move to the
next proposal-recall experiment.

## Single behavioral change

The current catalog walks pool items in input order and may accept up to six
roots per item until the 48-root global cap is reached. Eight easy early items
can therefore exclude every later item.

`quota_fair_ems_mpc` changes only catalog scheduling:

1. Pass 1 gives every urgency-ranked visible pool position an opportunity to
   contribute at most one exact root.
2. Pass 2 uses cached proposals and fills the remaining per-item and global
   quotas in deterministic urgency-ranked round-robin order.

The following remain unchanged:

- EMS proposal coordinates and `propose_actions`;
- `CandidateGenerator.validate_proposal` and `apply_action`;
- `_root_key`, candidate scoring, MCTS scoring, seeds, and rollouts;
- planner routing and emergency fallbacks;
- 24 proposals per item, six exact roots per item, 48 global roots, and the
  1.35-second catalog budget;
- 5.40-second MPC and 5.75-second policy hard limits;
- the public `Agent` interface and returned action dictionary.

Create an `exact_root_ems_mpc` standalone control package and a
`quota_fair_ems_mpc` standalone variant. Both activate MPC through normal
`Agent(module_path)` construction without environment variables, CLI flags, or
test-harness mutation. Their production files must be byte-equivalent except
for `catalog.py`; package-directory naming differences and the minimum relative
import metadata needed for those names are excluded from that comparison. This
makes local and Public control-versus-variant comparisons single-factor.

## Item identity and order

Each visible pool position gets an independent work record:

```text
(pool_index, item, urgency, proposals, cursor, accepted_count, rarity)
```

Urgency is computed once using the existing
`CandidateScorer.item_urgency(item, state.containers)`. Work records are ordered
by:

```text
(-urgency, item.index, pool_index)
```

`pool_index` is the authoritative choice identity. Equal `ItemSpec.index`
values at different pool positions are not merged.

## Pass 1: one-root coverage

For each ordered work record, compute a fair absolute deadline from the
remaining catalog time and remaining first-pass items. Call `propose_actions`
once with the unchanged proposal limit and cache its deterministic output.

Starting at cursor zero, validate each proposal through the production
validator and `apply_action`. Stop the item after its first unique exact root,
proposal exhaustion, item deadline, global deadline, or
global root limit. A failure for one item preserves earlier roots and does not
prevent later items from receiving their pass-1 opportunity.

Apply these cursor and deadline rules exactly:

- if the deadline is observed before taking the next proposal, leave the cursor
  unchanged so the unattempted proposal may be considered in a later turn;
- once a proposal is taken, advance the cursor before calling the validator or
  `apply_action`;
- a rejected, blocking, duplicate, or throwing proposal is never retried;
- after a per-proposal exception, continue within the current slice if its
  deadline has not expired; otherwise end the turn while preserving roots.

This prevents one slow or failing proposal from consuming every subsequent
turn without discarding proposals that were never attempted.

Rarity retains the existing definition:

```text
1.0 / max(1, len(proposals))
```

## Pass 2: quota filling

Do not regenerate proposals. Revisit non-exhausted work records in repeated
urgency-ranked round-robin rounds. Each turn continues from the stored cursor
and may add at most one unique exact root.

Each turn receives a fair absolute slice of the remaining catalog time based
on the number of active turns left in that round. Unused time carries forward.
An item reaching its turn deadline retains the cursor position after the last
proposal actually taken and can resume with the next unattempted proposal in a
later round while global time remains.

Stop when every record is exhausted or at its per-item quota, or when the
global root limit or catalog deadline is reached.

## Root uniqueness and final ordering

A root is accepted only when both exact operations succeed:

```python
candidate = generator.validate_proposal(state, proposal)
successor = apply_action(proxy_state, proposal, settings.path_clearance)
```

Deduplicate only within the same pool position by pool index, container index,
orientation, and exact AABB coordinates. The first unique geometry may consume
one quota slot. Repeated proposals with the same key advance the cursor but do
not increment `accepted_count`, the per-item quota, or the global root count.
Identical luggage at different pool positions remains distinct.

After collection, use the existing `_root_key` and global truncation unchanged.

## Package isolation

- Create `simulator/agents/exact_root_ems_mpc/` as the standalone control and
  `simulator/agents/quota_fair_ems_mpc/` as its standalone variant.
- Both packages activate MPC through the same internal construction path.
- All production modules in the two packages except `catalog.py` must remain
  byte-equivalent where package naming permits and behaviorally equivalent in
  every case. Relative imports keep both packages self-contained.
- Add tests named for `quota_fair_ems_mpc`; do not weaken or rewrite historical
  tests to make the variant pass.
- Extend only non-production test tooling as needed to select either standalone
  module path for control-versus-variant physical A/B.
- A later accepted archive is named descriptively, such as
  `quota-fair-ems-mpc_YYYYMMDD-HHMM.zip`, and contains only the top-level
  `quota_fair_ems_mpc/` production package.
- Build and extract both control and variant ZIPs. Run import/policy smoke tests
  through the public interface and assert that MPC is active in both while the
  appropriate catalog is invoked without external configuration.

## Required tests

The TDD suite must prove:

- urgency-ranked pass-1 proposal order;
- every reachable item receives a first root before any item receives a second;
- invalid proposals and per-item exceptions do not starve later items;
- pass 2 cycles across active items rather than filling one item first;
- per-item and global quotas remain enforced;
- duplicate item IDs remain independent pool choices;
- duplicate proposals for one pool position count once;
- fake-clock deadline reservation protects later pass-1 and pass-2 turns;
- deadline and validator/apply exceptions preserve accepted incumbents;
- identical observations produce identical root order;
- validators receive unchanged proposal objects returned by
  `propose_actions`, proving that no coordinate source was added;
- all returned roots revalidate exactly and have non-null proxy successors.

Deadline tests also verify the cursor-advance rule. Performance diagnostics
record p50, p95, p99, and maximum duration for one `propose_actions` call, one
`validate_proposal` call, one `apply_action` call, catalog construction, MCTS,
and the complete policy. Cooperative deadline checks cannot interrupt a single
blocking call, so the maximum per-call measurements are an explicit acceptance
input.

Existing EMS, catalog, MCTS, planner, replay, and public-API tests remain part
of the regression suite.

## Evaluation and decision gates

Compare standalone `exact_root_ems_mpc` and `quota_fair_ems_mpc` with identical
task, seed, runtime, limits, and internal MPC activation. Measure both coverage
and quality:

- covered pool positions and per-position root-count distribution;
- overall top-1 and top-5 mean `secondary_score` after normal scoring;
- the best root score for each covered pool position;
- selected root score and pool position;
- MCTS root visits and achieved search iterations;
- successful physical placements, local `fill_score`, local
  `num_placed_items`, and all per-step status fields;
- proxy mass-weighted CoG, protection-rule violations, and support ratio,
  explicitly labelled as proxies.

Adopt the scheduling change only when all of the following hold:

1. Old and new unit/integration tests, compile, import, and package-content
   audits pass.
2. Returned actions retain exact validation and no safety/API regression.
3. A Phase-0 starvation case exists, and unique pool-index root coverage is
   non-decreasing on every measured snapshot.
4. Report paired top-1, top-5 mean, per-item best, and selected-root score
   deltas. These are diagnostic proxy scores rather than standalone adoption
   criteria; physical placed-item and fill non-regression in gate 7 governs the
   trade-off between broader item coverage and shallower placement coverage.
5. The official smoke test completes 4/4 placements safely.
6. Run all 41 task000 and all 42 task001 items to natural completion or first
   physical failure; do not truncate to the former 25/30 prefixes. Record
   pre-action validation, `env.step()` result, post-step status, final status,
   completed steps, and local evaluation. Run five paired repetitions per task
   with seeds `17`, `42`, `314`, `2026`, and `8191`, alternating control-first
   and variant-first order.
7. Across the five paired repetitions of each full sample, the variant median
   completed-step count must be at least the control median and its mean
   `fill_score` may be no more than 0.25 absolute points below the control mean.
   No paired variant run may produce a false safety status earlier than its
   control. At least one task must strictly improve median completed steps,
   mean fill by at least 0.50 points, or recoverable root coverage. Full 41/41
   and 42/42 completion remains the target, but is not falsely claimed as a
   prerequisite for deciding whether this isolated scheduler is better than
   its baseline.
8. Generated A/B cases use the fixed 16-template covering manifest below with
   seeds `17`, `42`, and `2026`, for 48 paired control/variant cases. Aggregate
   median completed-step delta must be non-negative, mean fill delta must be at
   least -0.25 absolute points, and no variant run may produce a false safety
   status earlier than its paired control. At least one high-
   lookahead template must strictly improve median completed steps, mean fill
   by at least 0.50 points, or recoverable root coverage.
9. Measure at least 200 policy calls after 10 unmeasured warm-up calls. Run WSL
   Ubuntu with `taskset -c 0-3`, visualizer disabled, no concurrent benchmark
   processes, and the project-local Python/dependency paths. Policy p99 must be
   below 5.5 seconds and the absolute maximum below six seconds. Record p50,
   p95, p99, and maximum for the internal calls listed above; no single call may
   invalidate the policy headroom.
10. The extracted control and variant ZIPs activate MPC without external flags,
    differ behaviorally only in catalog scheduling, and reproduce their source
    package choices on fixed observations.

Reject and leave the variant unsubmitted on any safety, timeout,
determinism, API, task000, task001, or source-scope regression. A Public result
below 60 is evidence for the next controlled experiment, not completion.

## Fixed generated-case manifest

Each tuple is `(lookahead, containers, shelf, initial_state, attributes,
item_order, density)`. Two-container templates alternate whether a priority
container is designated. Exact generated inputs and hashes are stored with the
benchmark report.

```text
1:  (1,  1, no,  empty,     normal,   large-to-small, early)
2:  (1,  2, yes, preloaded, combined, random,         high)
3:  (3,  1, yes, empty,     soft,     small-to-large, middle)
4:  (3,  2, no,  preloaded, priority, repeated,       high)
5:  (10, 1, no,  preloaded, combined, random,         middle)
6:  (10, 2, yes, empty,     normal,   large-to-small, high)
7:  (20, 1, yes, preloaded, priority, small-to-large, high)
8:  (20, 2, no,  empty,     soft,     repeated,       middle)
9:  (20, 1, no,  empty,     combined, large-to-small, early)
10: (20, 2, yes, preloaded, normal,   random,         high)
11: (20, 1, yes, preloaded, soft,     repeated,       middle)
12: (20, 2, no,  empty,     priority, small-to-large, high)
13: (40, 1, no,  preloaded, normal,   repeated,       high)
14: (40, 2, yes, empty,     combined, random,         middle)
15: (40, 1, yes, empty,     priority, large-to-small, high)
16: (40, 2, no,  preloaded, soft,     small-to-large, early)
```

## Out of scope

- adding 29.7-style extreme-point coordinates;
- dense backfill or relaxed validation stages;
- replacing MCTS with beam search;
- changing scoring weights or the proxy objective;
- changing offline mode-A optimization;
- changing MPC activation asymmetrically between control and variant;
- adding dependencies, global installs, Git initialization, or commits.
