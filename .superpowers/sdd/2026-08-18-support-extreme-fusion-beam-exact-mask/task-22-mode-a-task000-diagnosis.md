# Task 22 — task000 Mode-A diagnostic report

Date: 2026-08-19  
Algorithm under diagnosis: `layered_proxy_order_beam_exact_skeleton_repair`

## Scope

This is a non-production, non-physics diagnosis. It reads the authoritative
sample task000 item stream and the saved pre-action step11 observation. The
initial container geometry is reconstructed from that saved observation after
clearing `packed_items`; no Gymnasium environment, PyBullet client, public
action, package installation, Git operation, or SIGNATE submission was run.

Source physical record:

- `optimize_time_seconds = 44.600421272`
- `optimized_order = [0, 1, ..., 40]`
- `mode_a_plan_trace = null`
- 11 safe placements, then step11 `CandidateZeroError`

## Finding 1 — optimize fell back before strict compilation

The analytical replay took 47.0964 s on this run (the saved physical run took
44.6004 s) and recorded:

| Signal | Value |
|---|---:|
| Nodes | 3,401 |
| Fit tests | 36,045 |
| Checked transitions | 3,398 |
| Deepest proxy prefix | 8 |
| Returned analytical candidates | 24 |
| Complete candidates | 0 |
| Compiler invocations | 0 |
| Branch exceptions | 0 |
| Deadline reached | false |
| Node/fit/transition quota exhausted | false |

Therefore the original order was not returned because compilation failed. The
compiler was never entered: `Agent.optimize` filters for complete proxy
candidates, and the order beam produced none. Search ended naturally when the
depth-8 frontier produced no further checked proxy child.

All 24 returned candidates were incomplete depth-8 candidates from historical
seed lane 1 and shared the occurrence prefix:

```text
3, 17, 21, 33, 1, 28, 5, 2
```

Their full order begins
`3,17,21,33,1,28,5,2,9,11,...`. This is distinct from both the original
stream and the descending-volume seed, but no partial candidate is eligible to
become a `ModeAPlan`.

All three full static seed permutations do exist at initialization:

- original: `0,1,2,...,40`
- historical rigid/heavy/footprint: begins
  `3,17,21,33,5,9,11,19,20,22,...`
- descending volume: begins
  `3,17,21,33,1,28,5,8,9,11,...`

A full static seed is only an ordering input, not a full proxy skeleton. There
was no full proxy candidate.

## Finding 2 — step11 is candidate exposure exhaustion, not exact dead-end

The saved step11 observation contains 11 settled items and one visible
occurrence, item index 11 at pool position 0.

### Normal families, no advisory

A generous normal-only scan completed all stages:

- 501 exact attempts
- 0 roots
- no deadline or quota stop
- rejections:
  - collision/clearance 357
  - transport 85
  - plane inclusion 39
  - support ratio 18
  - protection 2

This reproduces the online empty catalog when the plan is null and therefore
supplies no advisory proposals.

### Direct dense family

Exhaustive direct `DENSE_SUPPORT_LATTICE` generation produced 9,196 unique
records and 10 strict roots in 0.711 s. Aggregate failures were:

- collision/clearance 5,653
- plane inclusion 2,134
- support ratio 1,268
- protection 69
- transport 62

The first strict root is:

```text
item 11 / pool 0 / container 0 / orientation 2
position = (0.0085956444, -0.4294947040, 1.0149927065)
support_ratio = 0.9501059196
min_clearance = 0.1684133308
source = dense_support_lattice
```

### Adaptive dense

With a generous direct dense cap, the adaptive scanner:

- activated only after normal global zero;
- generated all 9,196 dense records;
- accepted its first root on dense exact attempt 4,520;
- stopped with one covered occurrence and `early_stop=true`;
- took 0.523 s.

The accepted proposal was independently revalidated with the unmodified
default production `SearchSettings`/`ExactMask` profile and passed fresh
`apply_root`. The direct-dense copy of the same proposal also passed. Thus
this is current physically strict evidence, not a generous-profile receipt
artifact or proxy-only placement.

The existing 4,096 raw adaptive exposure is below this state's first-root
prefix. This explains why a globally-zero rescue configured at 4,096 would
still miss the root.

## Root-cause classification

1. Offline fallback: implemented proxy search exhaustion at depth 8, with no
   complete candidate. It was not a deadline, quota, compiler, exception, or
   plan validation failure.
2. Online step11: normal-family candidate exposure exhaustion. It is not an
   authoritative ExactMask dead-end because current-profile dense roots exist
   and fresh transition authorization succeeds.
3. The two failures are separable. Fixing the step11 exposure does not prove
   the 41-item offline skeleton can complete, and changing the offline order
   does not prove step11 dense recovery is unnecessary.

## Ranked single-factor experiments

### E22a — A-only global-zero adaptive dense 12,288

Highest-confidence next experiment: on A policy only, when normal plus advisory
catalog roots are globally zero, run one direct dense pass with a raw limit of
12,288 (enough to cover this observed 9,196-record universe), first-root stop,
and the existing output reserve/fresh formatter. Keep proposal geometry,
ExactMask, repair rank, offline order, and B/C defaults unchanged.

Expected decision test: saved step11 exposes at least one identical current
catalog root within the A hard deadline, then a physical task000 rerun places
item11 safely and advances beyond 11. This is not yet a claim that later states
will complete.

### E22b — historical-seed fallback order

Separate experiment: when proxy search has no complete candidate and strict
compiler therefore has no input, return the complete historical static seed
instead of the original order while keeping `mode_a_plan=None`. Evidence is
limited but directional: all 24 deepest analytical candidates belonged to the
historical lane. Do not combine this with E22a in the first attribution run.

### E22c — proxy frontier diversity/recall

Later experiment: diagnose why 24 retained depth-8 candidates collapse to one
seed lane/order prefix and why the next layer has zero children despite the
physical online route reaching 11. Change only analytical exposure/retention,
not exact masks or online rescue. This requires node-level zero-candidate
instrumentation before implementation.

## Verification

```text
Focused diagnostic: Ran 2 tests in 0.580s — OK
Related diagnostics: Ran 40 tests in 0.823s — OK
Full suite: Ran 543 tests in 34.501s — OK
py_compile: exit 0
```

## Artifacts and SHA-256

```text
302C9D003D269A2ED0A30B02A291DB4DDFA3745ED439C94BB23851B2851ECD37  diagnose_mode_a_task000.py
6FE4E892626BFB0A9A9557FC7E015A946949DF885AF5C1202D41765573256DF9  test_diagnose_mode_a_task000.py
BF552DCE6A2D7E790034FF16FE96DEC2E62FE981AFBDEA7A06AAACA87279EF4F  task-22-mode-a-task000-diagnosis.json
```
