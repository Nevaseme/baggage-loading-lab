# Task18d: MaxRects-Regret step 15 candidate-zero diagnosis

## Decision summary

The task001 seed42 MaxRects-Regret run did **not** reach an authoritative
ExactMask dead-end at step 15.  It reached a **proposal-exposure cap**:

- the production-equivalent staged scanner reproducibly returned zero roots
  after 7,226 exact attempts in 0.91–1.07 seconds and did not hit its deadline;
- the unchanged state and unchanged strict-v2 ExactMask accepted six dense
  proposals when the dense raw-work limit was raised to 3,072 and 283 at
  4,096;
- therefore relaxing inclusion, collision/18 mm clearance, transport,
  support/core, protection, tilt, or depth checks is unsupported by this
  evidence;
- MaxRects-Regret itself was never invoked on the failed production step,
  because the depth-zero catalog was empty.

The smallest decision-ready experiment is to change only zero-root dense
rescue exposure from the current 256-scale work to 3,072 per visible
occurrence, retain every ExactMask check, and rely on the existing late-root
exact incumbent when little rollout time remains.  This is a hypothesis for a
new physical A/B run, not a claim that the newly exposed root will be
PyBullet-safe after settling.

## Observed run outcome

| Measure | Authoritative saved result |
|---|---:|
| Outcome | `candidate_zero` |
| Failure step | 15 |
| Safe placements | 15 |
| Final packed count | 15 |
| Exception | `CandidateZeroError: strict root catalog is empty` |
| Local fill score | 15.051133837261006 |
| Local normalized item count | 0.35714285714285715 |
| Policy calls | 16 |
| Policy p50 / p95 / p99 / max | 5.30596 / 5.31455 / 5.31624 / 5.31666 s |

All 15 actions before the exception have all three saved official predicates
true.  The saved runner trace has 15 successful action records and includes
the failed 16th policy duration only in its authoritative timing summary.

Of the 15 successful MaxRects-Regret searches, 13 stopped on the deadline and
none stopped on node, fit-test, or candidate quotas.  Most reached analytical
depth 2; steps 5 and 7 reached only depth 1.  The full per-step
`nodes`/`fit_tests`/`candidates`/`deepest` table is preserved in the diagnostic
JSON rather than duplicated here.

## 1. Authoritative exact-candidate exhaustion

The failure snapshot contains 15 settled items and a ten-occurrence visible B
pool.  Three fresh state builds and scans produced identical logical results:

| Repeat | Exact attempts | Strict roots | Deadline reached | Total time |
|---:|---:|---:|---|---:|
| 0 | 7,226 | 0 | no | 1.066 s |
| 1 | 7,226 | 0 | no | 0.915 s |
| 2 | 7,226 | 0 | no | 0.905 s |

The first-failure distribution was also identical:

| ExactMask predicate | Rejects |
|---|---:|
| collision or 18 mm horizontal clearance | 6,667 |
| plane inclusion | 210 |
| support ratio | 191 |
| transport | 91 |
| depth map | 57 |
| protection | 10 |

Stage attempts were: free probe 160, obstacle probe 144, plane probe 160,
free deepen 1,060, obstacle deepen 960, plane deepen 1,096, compact 360,
legacy 906, and dense rescue 2,380.  No stage produced a root.

The decisive counterfactual keeps the settled state and ExactMask fixed and
changes only dense-lattice raw exposure:

| Dense raw limit per pool | Generated | Strict accepts | Accepts by pool occurrence | Time |
|---:|---:|---:|---|---:|
| 256 | 2,560 | 0 | 0,0,0,0,0,0,0,0,0,0 | 0.189 s |
| 3,072 | 30,660 | 6 | 0,0,0,0,2,2,2,0,0,0 | 2.363 s |
| 4,096 | 40,900 | 283 | 24,24,24,0,53,53,53,26,26,0 | 3.725 s |

The iterator sorts/deduplicates after bounded generation, so a sorted proposal
ordinal is not a raw generation threshold.  The report deliberately does not
claim that “root 3,072” is a stable ordinal; it claims only that this fixed
work setting exposed strict roots while 256 did not.

Conclusion: this is not `default_scan_deadline` and not a certified exact
dead-end.  It is classified as `candidate_exposure_cap`.

## 2. MaxRects-Regret stage profile after roots are exposed

A diagnostic dense-only catalog was constructed with the same ExactMask,
capped at eight roots per pool and 64 globally.  It required 9,358 exact
attempts and covered eight of ten pool occurrences.  Every selector lineage
was then freshly revalidated through `apply_root`; no proxy object was used as
an action/root substitute.

Under the 5.30-second selector deadline:

| Selector measure | Value |
|---|---:|
| Input exact roots | 64 |
| Freshly applied depth-zero lineages | 24 |
| Returned ranked original roots | 24 |
| Analytical nodes | 108 |
| Fit tests | 1,904 |
| Proxy candidates | 84 |
| Deepest analytical depth | 2 |
| Predicted placed count / volume | 2 / 0.125925 |
| Largest free region | 0.21164648 |
| Deadline / work quota | deadline; no node/fit/candidate quota |

The top diagnostic root was pool occurrence 8 / item 23, container 0,
orientation 0 at `(-0.1900253, -0.1126372, 0.4249962)`, support ratio
0.8000011, clearance 0.0396387.  This is ranking evidence only; the production
failed step did not expose or select this root.

### Inclusive stage timings

| Stage | Calls | Outputs | Inclusive time |
|---|---:|---:|---:|
| depth-zero fresh `apply_root` | 24 | 24 | 0.054 s |
| `LayeredProxy.from_sim_state` | 24 | 24 | 0.014 s |
| `metrics` | 192 | 192 | 3.644 s |
| `enumerate_candidates` by item | 238 | 84 | 1.122 s |
| proxy `apply` | 168 | 168 | 0.147 s |
| maximal-empty-rectangle calls inside proxy | 4,054 | 17,314 rects | 2.580 s |
| rank-time maximal rectangle calls | 84 | 1,512 rects | 0.304 s |
| analyzed nodes | 27 | 84 item plans | 3.118 s |
| fair-prune schedules | 4 | 112 output slots | <0.001 s |

These timings are nested/inclusive and must not be summed.  They show the
dominant analytical cost is geometry/metrics—especially maximal-rectangle
reconstruction—not exact depth-zero revalidation.

### Work by depth and lineage

- Depth 0 adopted all 24 fair lineages once before any descendant survived.
- Every depth-1 lineage received one analysis turn.  Each normally consumed
  nine item enumerations and 72 fit tests, yielding three or four candidates.
- Those 24 analyses yielded 84 depth-2 nodes; fair pruning retained 32, with
  at least one node from every lineage before additional nodes for lineages
  7, 15, and 23.
- Only three depth-2 lineages began another analysis before the deadline:
  lineages 7, 15, and 23 consumed 64, 64, and 48 fit tests and yielded no new
  candidate.

Per-lineage counters and every scheduling input/output distribution are in
`selector_stage_profile.profile.by_depth_lineage` and `.scheduling`.

## 3. Deadline versus quota

There are two distinct facts:

1. **Terminal step 15:** the scanner stopped normally in about one second with
   zero exposed roots.  The selector could not run.  Neither selector deadline
   nor selector quota caused the exception.
2. **Earlier successful steps and the expanded-root counterfactual:** selector
   work is ordinarily deadline-bound.  The expanded step-15 profile stopped at
   5.305 seconds with no work quota reached.  Thus exposing more roots can
   recover an exact incumbent but cannot be assumed to provide deep rollout
   within the current policy budget.

This distinction rules out “increase selector node/fit quotas” as a direct fix
for the terminal failure.

## 4. Frozen replay reproducibility

Two independent replays per state used a deliberately short 0.75-second
diagnostic selector window so the whole audit remains bounded.  This verifies
catalog/choice determinism at the tested window; it does not claim full
5.30-second rank equivalence.

| State | Catalog roots | Repeated result |
|---|---:|---|
| reconstructed initial | 64, 64 | pool 2 / item 2, same back placement both runs |
| historical step 8 snapshot | 64, 64 | pool 8 / item 16, same placement both runs |
| failing step 15 snapshot | 0, 0 | no selector invocation both runs |

The initial result is consistent with the earlier frozen analytical replay.
The step-8 file is the historical exact-beam failure snapshot, not a snapshot
from the MaxRects-Regret physical trajectory; it is included only as a stable
intermediate geometry fixture.  The step-15 file is the authoritative
MaxRects-Regret failure boundary.

## 5. Ranked next hypotheses

1. **E7: zero-root dense exposure 256 → 3,072 only.** Keep candidate family,
   ExactMask, ranking, and formatter unchanged.  This is the cleanest
   single-factor test and the smallest measured cap that exposed roots in the
   chosen sweep.  Record scan time, fresh-formatter authorization, and physical
   result.
2. **Adaptive dense continuation after E7.** On a globally empty strict
   catalog, deepen pool occurrences round-robin and stop each after its first
   exact root.  This should reduce the 30,660-proposal cost, but it changes
   scheduling as well as work and therefore should be a separate experiment.
3. **Earlier-state support-space avoidance.** If E7 recovers a root but the
   physical trajectory remains weak, penalize states whose remaining items are
   reachable only through late dense work.  This is broader and should follow,
   not obscure, the direct exposure test.

Rejected for this failure: weakening strict geometry/support/transport/depth,
raising selector work quotas, or calling the state an unavoidable physical
dead-end.

## Sources, reproducibility, and limitations

- Saved physical JSON SHA-256:
  `662871e313f2ebe5b4b5494c139a46a2445e2ffa885f32de6a48de06b7bdac12`
- MaxRects-Regret failure NPZ SHA-256:
  `6faec9292ce2a0197c6ed580e84f8537b23a0c92b8eafc5c6fcb86492ceed14d`
- Historical step-8 NPZ SHA-256:
  `eaf7753f42403e5265554c3e9fdeb26711b718e372e5f8413f7a9edd1a1df82b`
- Diagnostic JSON SHA-256:
  `3f8f8d11f2416465976107075ea16b7679b96b400ea9f57e5307d04cd7067ecf`

The diagnostic script performs no environment step and changes no production
module.  Exact acceptance establishes only validator-safe proposals for the
saved settled state.  It does not establish subsequent PyBullet stability or
Public score.  No new physics run, global installation, network access, Git
initialization, or commit was performed.

No chart is included: the decision turns on a single threshold comparison and
stage/counter tables are more precise than a visual encoding here.

## Verification

- Focused diagnostic unit tests: **5/5 PASS** in 0.016 s.
- Full package-aware simulator discovery: **397/397 PASS** in 14.165 s.
- A first generic discovery command found one loader error because it omitted
  the simulator package top-level; the package-aware rerun above is the valid
  full-suite result.  There was no test assertion or production-code failure.
- Final diagnostic materialization used three production-equivalent step-15
  scans, two frozen replays for each of initial/step8/step15, a 0.75-second
  replay-selector window, and dense limits 256/3,072/4,096.
