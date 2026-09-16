# Task 24 — Proxy-prefix Mode-A order fallback

Date: 2026-08-19  
Experiment: `proxy_prefix_order_fallback_exact_mask`

## Single-factor behavior

A new non-profile Mode-A setting,
`mode_a_proxy_prefix_order_fallback=False`, remains disabled by default. The
diagnostic runner exposes it only through:

```text
--a-order-fallback proxy-prefix
```

It is effective only for explicitly requested and resolved Mode A.

When strict compilation does not publish a full `ModeAPlan`, but the ranked
order beam returned an exact `ProxyOrderCandidate` partial whose
`occurrence_order` is a complete authoritative permutation, optimize may
return that complete order instead of the original stream. The candidate's
partial skeleton is never stored:

- `mode_a_plan is None`
- online advisory plan hints are absent
- online policy still uses only the current exact catalog and fresh formatter
- no proxy object, receipt, proposal, or action is returned from optimize

Empty results, stale/forged occurrence identity, invalid permutation, nonfinite
clock, or timeout before a usable partial retain the original complete order.
A successfully compiled full plan remains higher priority and unchanged.

Review hardening makes the fallback publication boundary explicit. After the
candidate's exact type, authoritative occurrence identities, and complete
permutation have all been checked, optimize samples the clock again and
requires a finite value strictly below the +145 s final-validation deadline.
It then retains the separate finite, strict-before +150 s hard-return guard.
Equality at either boundary and NaN or either infinity fail closed to the
original order with no fallback trace.

The diagnostic trace contains only exact integers:
`selected_depth` and `seed_lane`.

## Frozen task000 analytical fixture

A synthetic authoritative 41-occurrence fixture uses the top partial order
recorded by the Task22 diagnosis; Task24 does not rerun the order beam or
PyBullet to produce this fixture. Its identities and permutation are rebuilt
from the task000 input before optimize is exercised.
With the explicit setting, optimize returns a non-original full 41-occurrence
permutation beginning:

```text
3, 17, 21, 33, 1, 28, 5, 2
```

It diverges from the original order at step zero, records depth 8 / seed lane 1,
and stores no plan. This is an analytical frozen fixture; Task24 did not run
PyBullet.

## Isolation and integrity

Tests cover:

- default false and unchanged strict profile digest;
- exact authoritative full occurrence identity;
- stale signature rejection;
- duplicate item IDs without occurrence loss;
- empty/invalid fallback to original;
- 20 identical deterministic runs;
- the synthetic authoritative task000 prefix and plan absence;
- post-validation +145 s equality and NaN/positive-infinity/negative-infinity
  rejection;
- full compiled-plan precedence even when a ranked partial also exists;
- requested/effective A-only runner metadata;
- runner serialization of selected depth/seed;
- combined installation of Task23 A adaptive dense and Task24 proxy-prefix:
  the order flag leaves the already-installed adaptive scanner object intact;
- isolation from B/C and unchanged compiler, repair, and exact action formatting.

## TDD and verification

Initial RED:

```text
ImportError: _a_order_fallback_settings did not exist
Ran 1 test — FAILED
```

GREEN:

```text
Focused: Ran 10 tests in 0.121s — OK
Related: Ran 142 tests in 10.203s — OK
Full discovery: exit 0; discovered 558 tests (separate loader count 558)
py_compile: exit 0
```

Review-fix RED was meaningful: before the production change, the focused suite
failed only the +145.0 equality subcase by returning `[2, 1, 3]` instead of the
original `[1, 2, 3]`. The minimal change added the missing post-authority-check
final-deadline sample; the other safety and ordering paths were unchanged.

## Files and SHA-256

```text
4A5D706FCA4923101B21F1FA4535357271DB3BE544F662E50296B24FEBB668B6  agent.py
D7D204F178C18E49B2479BAFB6442E677D1B7D83DF0059A3B218CEAC86D3C274  settings.py
195099245E032D10560026E42350618A35D297D26364368E91F97B222B8FE707  run_support_extreme_fusion_physics.py
4DD1ACEE528B3EAC591E36C17B7F9E98CB3029E8641306E44B5A645737D9CC1B  test_support_extreme_fusion_mode_a_proxy_prefix_fallback.py
39F389169726188726BE947D1BB1BC731856CD7FBB969835F52ECFE643AC4712  progress.md
FCD345185DC583270455B50779023C7828F1269C5C01052D12014DE7B86C875B  2026-08-18-layered-maxrects-regret-exact-mask.md
```

## Physical acceptance boundary

The next controlled physical run should combine neither rank nor safety changes:
use `--a-order-fallback proxy-prefix` with Task23 rescue left legacy first.
Compare the original-order 11-safe baseline at the first divergent action.
The combined installer test proves only configuration isolation, not physical
performance. Task24 itself makes no PyBullet, Public-score, or submission claim.
