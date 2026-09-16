# Layered MaxRects Regret Exact Mask — Implementation Plan

## Goal

Replace the ineffective exact-child beam with a deterministic fixed-work
layered MaxRects proxy while retaining the current exact depth-zero catalog,
fresh ExactMask output authorization, and fail-closed public action boundary.

## Safety invariant

Only an original current-observation `ValidatedRoot` may be returned. Proxy
placements are ranking-only data and can never mint a receipt or action. The
selected root is freshly revalidated by the existing formatter; candidate
zero remains an explicit error.

## Task 18a — Layered proxy geometry and immutable transition

- Add `layered_proxy.py` with immutable protection-tagged support patches,
  height-aware free cells/maximal rectangles, proxy boxes, occurrence keys,
  work quotas, and deterministic state fingerprints.
- Reproduce floor +8 mm, shelf +22 mm, aligned item-top +0 mm support layers.
- Treat tilted items as obstacles only.
- Enumerate six official orientations at back/front/side/flush MaxRect anchors.
- Enforce analytical planes, AABB clearance, headroom, coplanar support ratio,
  center core, protection compatibility, and conservative Y-to-X ingress.
- Apply candidates immutably and create a tagged top patch.
- TDD: layer offsets, tilted behavior, protection combinations, orientation
  dedupe, artificial partition recovery, headroom, support/core, 18 mm
  ingress, back-vs-center continuity, CoG, duplicate occurrences, quotas,
  mutation isolation, and forbidden receipt/action construction.

## Task 18b — Regret rollout selector

- Add `maxrects_regret.py` with lineage-fair, fixed-node/fixed-fit-test rollout.
- B uses only the visible pool; C is strictly one-ply.
- Initial limits: 24 depth-zero roots, depth up to 12, beam width 32,
  768 nodes, 96,000 fit tests, four items/node, three placements/item.
- Expansion order: one-option items, regret, feasible-count scarcity, volume,
  occurrence key.
- Rank: placed count, volume, remaining fit count/volume, scarcity,
  material protection capacity, ingress, largest free region, negative sliver,
  low CoG/stack, depth-zero margins, cumulative backness, stable key.
- Return a ranked tuple of original depth-zero roots only.
- TDD: one-option regret, lineage/pool fairness, fixed quotas and determinism,
  visible-pool-only B, no-arrival C, stale-root retry ordering, no proxy output,
  and frozen task001 prefix divergences.

## Task 18c — Diagnostic routing and physical gate

- Add a runner-only `maxrects-regret` B planner option before changing the
  production Agent default.
- Record proxy work counts, deepest rollout, predicted count/volume, chosen
  lineage, timings, candidate-zero, and physical predicates.
- Compare current fixed-two-ply and MaxRects on task001 seed 42 and frozen
  steps 0/4/8/10/12.
- Initial keep gate: all actions physically safe, safe placements strictly
  above 13 and preferably at least 20, p99 <5.5 s, max <6 s.
- If kept, integrate it as B default and C one-ply while preserving the final
  ExactMask formatter.

## Task 18d — Deadline and terminal-deadlock diagnosis

- Profile depth-zero authorization, proxy-state construction, candidate
  enumeration, immutable apply, MaxRects reconstruction, metrics, and
  scheduling separately on saved early/middle/failure snapshots.
- Certify whether the final candidate-zero is scanner starvation or an
  exhausted implemented candidate space using a generous all-family scan.
- Record per-depth lineage/node/fit/candidate work, deadline-vs-quota stop,
  duplicate proxy checks, and whether completed children are discarded at an
  interrupted level. Keep production code unchanged.

## Task 18e — Global-zero adaptive dense rescue

- Preserve normal/deferred catalogs, proxy rank, and all safety predicates.
- Only when the ordinary catalog is globally empty, run one direct dense
  support-lattice stage with raw limit 4,096; do not repeat smaller expanding
  scans because their generated order is not a monotone prefix.
- Validate in pool-occurrence round-robin order, stop each occurrence after
  its first strict root, stop globally after eight covered occurrences, and
  reserve at least 0.75 s for deterministic root selection and final fresh
  authorization.
- TDD requires nonzero-path action equivalence, global-zero-only activation,
  late-root recovery, occurrence fairness including duplicate item IDs,
  per-pool/global early stops, deadline partial-incumbent retention, frozen
  step-15 root recovery, deterministic work statistics, and strict-root-only
  output.
- Physical keep gate: task001 step0–14 action hash unchanged, step15 root and
  action strict/fresh/physically safe, every policy call <6 s, at least 16 safe
  placements, and zero unchecked output.

## Task 18f — Memoized streaming proxy rollout

- Keep the exact current-root catalog, proposal order, rank, stable ties, and
  all public quotas unchanged; change only the rollout executor.
- Build each checked proxy transition once and retain its immutable child,
  metrics, and MaxRect waste for commit without duplicate check/metrics work.
- Cache topology values only within one `select` invocation and bind entries to
  the exact parent fingerprint. Foreign, stale, or altered previews fail closed.
- Stream completed lineage-fair children into the incumbent/frontier so an
  interrupted level does not discard already completed work.
- TDD requires legacy candidate/child/rank equivalence under ample time,
  one-check transition accounting, cache isolation, deadline checkpointing,
  deterministic work counters, unchanged quotas, and original strict-root-only
  output.
- Physical keep gate on task001/seed42: all actions safe, no regression before
  step 15, p50 <=4.5 s, median proxy depth >=4, max depth >=6, and at least 16
  safe placements for adoption as the next B candidate.

## Task 19 — Stratified layer/orientation proxy exposure

- Keep the exact root catalog, proxy candidate universe, checks, coordinates,
  final stable ordering, regret rank, local costs, per-occurrence quantum, and
  global work quotas unchanged.
- Add an explicit stratified executor that round-robins candidate prefixes by
  container, support class (floor/shelf/placed-top/proxy-top), and deduplicated
  official orientation. Preserve patch, MaxRect, anchor, and position order
  within each stratum.
- Keep legacy nested exposure as the production/default behavior. Expose the
  stratified executor only through the diagnostic B planner route
  `memoized-stratified-maxrects-regret`; C, A, auto, and every existing route
  remain unchanged.
- Record accepted proxy-candidate exposure by support source/orientation and
  zero-candidate node counts as diagnostic-only trace fields; never feed them
  into rank or public action construction.
- TDD requires unlimited legacy/stratified candidate, child, and metrics
  equivalence; bounded layer/orientation/container diversity; orientation
  deduplication; fixed work and determinism; legacy action/rank preservation;
  exact original-root output; runner isolation; and frozen non-physics replay.
- Status (2026-08-19): implemented and locally verified. Frozen analytical
  replay selects the same initial item but a shelf/back exact root, reaches
  predicted depth three at step 8 where legacy reaches two, and reconfirms the
  stored step-14 state has no exact root even after adaptive dense exposure.
  This is a diagnostic result, not a physical-score claim.

## Task 20 — Certified continuation-survival rank

- Keep Task 19 stratified exposure, proxy candidate generation/order, local
  costs, regret scheduling, work quotas, exact catalog, and formatter
  unchanged. Change only analytical rank evidence and cohort eligibility.
- Audit every visible remaining occurrence, including zero-option occurrences.
  Treat deadline, quota, and exception interruption as incomplete/unknown,
  never as certified zero.
- Rank only a completely audited depth cohort. Unanalysed committed children
  remain eligible for later expansion but cannot replace the last closed
  certified cohort.
- Rank certified nodes by placed-plus-option occurrence survival, saturated
  minimum options, placed-plus-option volume, then existing topology, CoG,
  safety-margin, and backness terms. Count each occurrence volume once.
- Keep legacy rank as the default. Expose survival rank only through explicit
  mode-B `memoized-stratified-maxrects-regret` diagnostic routing and record
  requested/effective objective metadata truthfully.
- Status (2026-08-19): implemented and locally verified with focused,
  related, and full regression tests. No PyBullet or Public-score claim is
  made by this task.

## Task 21 — Mode A offline plan

### Task 21a — Immutable occurrences, exact skeleton boundary, and static seed

- Add immutable occurrence identities keyed by original position, canonical
  full item signature, and duplicate ordinal. Duplicate global IDs and equal
  signatures remain distinct occurrences. Authoritative sequences are exactly
  dense positions `0..n-1`, and duplicate ordinals are recomputed sequentially
  per full signature.
- Add receipt-free skeleton intents, bounded optimize traces, canonical
  profile-bound plan digests, and a fail-closed plan finalizer. Incomplete or
  invalid candidates return the untouched original occurrence order and no
  plan; partial skeletons are never published.
  Skeleton occurrences/supporters must match the complete authoritative stable
  identity, not only their position. Plan digests cover semantic plan contents
  and deliberately exclude wall-clock trace timing.
- Port only the historical static ordering tuple (normal/priority/soft group,
  mass, maximal-pair footprint, volume, largest dimension, item index), with
  original occurrence position as the deterministic duplicate-safe final tie.
- Status (2026-08-19): implemented and locally verified. This foundation does
  not integrate Agent.optimize, generate coordinates, mint validation receipts,
  or run physics.

### Task 21b — Offline LayeredProxy order beam

- Add a Mode-A-only fixed-work beam over select-local checked LayeredProxy
  transitions. It emits analytical `ProxyOrderCandidate` values containing a
  full occurrence permutation and a placed-prefix skeleton, never receipts or
  actions.
- Seed three fair lanes: original occurrence order, the Task21a historical
  rigid/heavy/footprint seed, and descending volume. Per-node item choice is a
  deterministic union of seed heads, estimated option scarcity, protection
  attributes, and large-footprint/few-orientation urgency, capped at six.
- Use deduplicated official orientations and stratified layer/orientation
  exposure, with at most four issued transitions per item. Retain fair coverage
  across seed, support source, and container before filling rank order.
- Fixed defaults are width 24, 20,000 nodes, 250,000 fit checks, 80,000 checked
  transitions, 64 fit checks per preview, and 128 MaxRects per patch. An
  already-expired call performs no seed/proxy work; occurrence/support/
  orientation selection checks the absolute deadline cooperatively, and no
  transition commit begins after a preview reaches the deadline. Complete
  candidates precede every
  partial candidate; partial results remain analytical and cannot become a
  `ModeAPlan` without the later exact compiler.
- Status (2026-08-19): implemented and locally verified, including a real
  three-item analytical completion and a bounded 41-occurrence deadline smoke.
  No strict compiler, Agent integration, or physics claim is included.

### Task 21c — Strict virtual skeleton compiler

- Compile only complete, authoritative `ProxyOrderCandidate` permutations.
  Each ordered occurrence is rebound to a singleton current pool, so duplicate
  global item IDs and equal signatures remain occurrence-distinct.
- For each settled virtual state, try no more than six intent-derived advisory
  proposals (planned center plus floor/shelf/placed-top rebases), then run a
  normal-family fixed-work strict scan capped at 64 exact attempts. Deferred,
  rescue, and dense families are excluded from this compiler stage.
- Rank only strict current roots by planned-intent proximity, suffix evidence,
  and exact support/clearance. Apply the selected root through a fresh
  `ExactMask` revalidation to a cloned state. Receipts and proposals remain
  local and are discarded; the published skeleton contains only canonical
  occurrence references, geometry, support kind, alternatives, and margins.
- Divide remaining wall time fairly over uncompiled occurrences and check the
  absolute deadline around advisory validation, scanning, and transition work.
  Any timeout, exception, stale evidence, identity mismatch, or partial
  compilation returns no plan.
- Status (2026-08-19): implemented and review-hardened with 18 focused, 102
  related, and 516 full tests. Compiled supporter identities are container-local,
  shelf classification requires XY overlap, and long compiler loops abort
  cooperatively on the absolute deadline. Support reconstruction now uses the
  exact mask's 12 mm contact tolerance, axis-alignment gate, and nonnegative
  shelf-gap semantics. This task does not integrate `Agent.optimize`,
  execute PyBullet, or store offline validation receipts/actions.

### Task 21d — Observation-derived exact skeleton repair

- Extend `StrictRootScanner.scan` with an optional empty-by-default Mode-A
  advisory sequence. At most six unique current proposals are considered before
  ordinary families; each must pass diagnose, a separate fresh validate, full
  receipt/action binding comparison, and existing catalog caps. Empty advisory
  input preserves the B/C records, stats, and ordering contract.
- Reconstruct the next offline occurrence from the settled packed multiset on
  every call. Initial packed signatures are subtracted, duplicate full
  signatures bind deterministically to the first matching live pool occurrence,
  and no mutable plan cursor exists.
- Freshly apply every current catalog root through `ExactMask` before ranking.
  Use actual supporter translation/top settling to rebase the intended center;
  compare container, exact support class, orientation, and 3-D distance. For
  the top 12 intent matches, measure fixed-work LayeredProxy fit survival over
  at most eight planned suffix occurrences before applying local hint terms.
- Invalid/stale plans disable hints but retain the deterministic exact catalog
  fallback. Deadline or branch exceptions preserve the first freshly applied
  incumbent. Only an original `RootCatalog` root identity can be returned.
- Status (2026-08-19): implemented and review-hardened with 14 focused, 149
  related, and 530 full tests. Actual supporter rebasing is container-local and
  uses a canonical typed settled-support tuple; a deadline crossed during
  observation-derived context reconstruction returns the retained fresh exact
  incumbent before any hint/fallback work. Agent integration and physics remain out of
  scope; suffix survival is an analytical fixed-work proxy, not a physics claim.

### Task 21e — Agent and official-runner integration

- Install the Task21a-d pipeline behind `get_init_states(optimize=True)`.
  Every initialization clears prior Mode-A state and records the initial
  packed-item multiset. `optimize` stores only a complete, digest-valid strict
  skeleton and otherwise returns the untouched complete item-index sequence.
- Bound the offline stages by one absolute clock: validation +8 s, order beam
  +82 s, strict compile +138 s, final validation +145 s, hard return +150 s.
  These Mode-A-only timing controls do not enter the exact-mask profile digest.
- At policy time, rebuild settled state, admit at most six plan-derived
  advisories through the current scanner, and let
  `ModeAExactSkeletonRepair` choose only an identical current catalog root.
  Catalog, repair, output-reserve, and hard deadlines are +4.40/+5.30/+5.45/
  +5.75 s. The unchanged formatter performs mandatory fresh ExactMask
  revalidation and remains the sole action-dictionary construction path.
- For resolved Mode A, the physics runner follows the official optimization
  lifecycle before reset and records optimization elapsed time, returned order,
  and complete-plan trace. B/C/default diagnostic planner routes remain
  unchanged.
- Status (2026-08-19): implemented and Sol-review-hardened with 72 focused/
  related and 541 full tests plus compilation. Late A scans/repairs retain only
  a current exact catalog incumbent; compiler output is exact-type checked; all
  +138/+145/+150 publication clocks fail closed on equality/non-finite values.
  This task did not run PyBullet
  or claim physical/Public-score acceptance.

## Task 22 — Mode-A task000 failure diagnosis

- Replay the saved task000 optimize input and step11 pre-action observation
  without PyBullet. Separate order-beam exhaustion, strict compiler failure,
  and online exact candidate exposure.
- Status (2026-08-19): completed. Order beam ended naturally at proxy depth 8
  with zero complete candidate and therefore zero compiler calls. At step11,
  normal families had zero roots, while a 9,196-record dense universe contained
  10 current-profile fresh-applicable roots; the first adaptive root appeared
  on dense exact attempt 4,520.

## Task 23 — A-only global-zero adaptive dense exposure

- Add an explicit diagnostic runner route
  `global-zero-adaptive-dense-12288`, effective only for requested/resolved
  Mode A. Keep the production Agent/default and B/C/auto routes unchanged.
- Reuse the existing exact diagnose/fresh-validate catalog admission and retain
  0.75 s of the +4.40 s catalog window. Record requested/effective settings and
  initial scan statistics truthfully.
- Status (2026-08-19): implemented and locally verified. Frozen step11 changes
  from legacy zero roots to a fresh-applicable strict root within the reserved
  time. This is analytical replay only; no PyBullet result is claimed.

## Task 24 — Proxy-prefix Mode-A order fallback

- Add a default-off, non-profile Mode-A experiment that returns the ranked top
  partial proxy candidate's complete authoritative occurrence order only when
  strict compilation published no full plan. Never store the partial skeleton
  or expose proxy/receipt/action state.
- Keep original-order fallback for empty, stale, invalid, nonfinite, or
  pre-partial timeout cases. Full strict plans retain precedence.
- Expose only through explicit requested/resolved A runner metadata and record
  selected analytical depth/seed lane. Keep Task23 rescue and B/C/auto
  independent.
- Status (2026-08-19): implemented and locally verified with 10 focused, 142
  related, and 558 full tests. Review hardening requires the authoritative
  partial-permutation check to finish strictly before the +145 s final
  deadline (including equality and nonfinite rejection), while retaining the
  separate +150 s hard return guard. A synthetic authoritative task000 fixture
  derived from the diagnosed partial returns a full non-original order
  beginning `3,17,21,33,1,28,5,2`, with plan null. Full compiled plans retain
  precedence. No Task24 physics or Public claim has been made.

## Task 25 — Acceptance and packaging

- Run A/B/C, lookahead 3/10/20/40, sample tasks, multiple seeds, shelf/no-shelf,
  initial-items and multi-container cases.
- Record safe placements, first failure, fill/count, labelled CoG/support/
  protection/stability proxies, timing percentiles, candidate-zero and route.
- Require all tests green, no unchecked output, p99 <5.5 s, max <6 s, ZIP
  import/API/action reproduction audit, and then create a standalone package
  named `layered_maxrects_regret_exact_mask` with SHA-256.
