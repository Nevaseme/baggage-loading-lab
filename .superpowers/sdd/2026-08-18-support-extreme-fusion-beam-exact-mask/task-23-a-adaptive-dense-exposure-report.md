# Task 23 — A-only global-zero adaptive dense exposure

Date: 2026-08-19  
Experiment algorithm: `adaptive_dense_exact_skeleton_repair`

## Single-factor change

The diagnostic runner now accepts:

```text
--a-candidate-rescue global-zero-adaptive-dense-12288
```

It is effective only when both requested and resolved mode are A. It replaces
only the Agent's online scanner with the existing
`StrictRootScanner + AdaptiveDenseRescueConfig` path:

- raw work limit: 12,288
- distinct occurrence target: 8 (bounded by the visible pool and catalog cap)
- output reserve: 0.75 s

The production Agent default, Mode-A optimize/order/compiler/repair/rank,
ExactMask, proposal generation, B adaptive route, C route, and auto route are
unchanged. The existing Task18e diagnose-then-fresh-validate full receipt
comparison remains the sole way adaptive roots enter a catalog. The unchanged
Agent formatter still performs final fresh authorization.

Runner JSON records `requested`, `effective`, `enabled`, all three adaptive
settings, and first-catalog adaptive statistics. Requested A rescue under
auto/B/C is truthfully reported as ineffective legacy.

## Frozen step11 evidence

Saved task000 Mode-A step11 was replayed without physics:

- legacy scanner: 0 roots
- explicit A 12,288 scanner: at least 1 strict root
- adaptive activation: true
- all returned roots passed fresh `apply_root` with the Agent-owned
  ExactMask/settings
- scan completed below 3.65 s, preserving the configured 0.75 s reserve inside
  the Agent's +4.40 s catalog deadline

The test uses the saved observation/depth map and current exact geometry. It
does not claim the subsequent PyBullet placement or episode completion.

## TDD evidence

Initial RED:

```text
ImportError: _a_candidate_rescue_settings did not exist
Ran 1 test — FAILED
```

GREEN:

```text
Focused Task23: Ran 5 tests in 0.974s — OK
A/B/C related: Ran 82 tests in 6.355s — OK
Full suite: Ran 548 tests in 34.433s — OK
py_compile: exit 0
```

## Files and SHA-256

```text
D109D16ED45C701D0F9808E9D9A8BAC7CC9D3987AE47132D0FA40393E1AF51A4  run_support_extreme_fusion_physics.py
C809A85ED54BBF7E12A0610E69DBB68D4531DECB2798A92179EA8FE7ABA72D64  test_support_extreme_fusion_a_adaptive_dense_runner.py
```

## Scope limit

No physical episode, default switch, production Agent edit, package install,
Git action, ZIP, score claim, or submission occurred. The next attribution step
is one task000 physical run using only this explicit runner flag.

