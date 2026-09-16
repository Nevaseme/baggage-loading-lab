# Task 7a: exact-mask Agent B/C integration report

## Scope

Writer-owned files:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/agent.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/settings.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/__init__.py`
- `simulator/tests/test_support_extreme_fusion_agent_bc.py`
- this report

The parent explicitly expanded scope to update the single obsolete
`test_support_extreme_fusion_contract.py` assertion that required every
initialized C policy to remain `NotReady`. The replacement keeps uninitialized
and mode-A routes explicit while requiring initialized C to return only a
strict formatted action or fail closed.

Offline ordering and mode-A planner files were not added or edited. Existing
proposal, mask, catalog, transition, feature, beam, simulator, historical
algorithm, and submission artifacts were not changed.

## TDD evidence

The new focused contract was written first. Initial RED was the missing public
failure boundary:

```text
ImportError: cannot import name 'CandidateZeroError' from
'agents.support_extreme_fusion_beam_exact_mask.agent'
Ran 1 test ... FAILED (errors=1)
```

Minimal production integration then made all eleven B/C tests GREEN. The test
suite uses real state construction, exact mask, strict catalog, beam, and
formatter for public one-item B/C actions. Narrow recording dependencies are
used only to isolate orchestration, absolute deadlines, and injected failure
stages.

Independent review found one Important deadline gap: the 5.75s limit had been
sampled only before fresh formatting. A twelfth test was RED when revalidation
started before 5.45s but completed exactly at 5.75s and still emitted an
action. Policy now installs a temporary hard-deadline guard around only the
formatter call; after matching fresh evidence and constructing the action,
the formatter resamples the clock and rejects non-finite or `>= 5.75s`
completion. `finally` clears the guard on both success and failure. The final
independent re-review returned APPROVE with no Critical or Important findings.

## Implemented boundary

`Agent.__init__` now owns one profile-consistent `ExactMask`,
`StrictRootScanner`, and `FutureSupportIngressBeam`. It immediately installs
the mask's receipt-returning `revalidate` callback. Beam construction uses the
fixed B/C settings: width 20, depth 4, six item occurrences, and two roots per
occurrence.

`get_init_states` fixes the mode for the episode:

- A iff `optimize` is true;
- otherwise B iff initial `lookahead_k > 1`;
- otherwise C.

Mode is never inferred again from the shrinking observation pool, so a B
episode's one-item tail remains B.

`policy` starts its clock before state construction, requires the ordered raw
pool, and rebuilds settled geometry/depth state on every call. It scans the
strict catalog to the absolute `started + 5.45s` boundary. Mode B calls the
deterministic beam and mode C calls its one-ply selector with absolute
`started + 5.30s`. The selected receipt must be the identical object from the
depth-zero catalog.

Before returning, policy preserves a 0.30s output interval by requiring
planning to finish before `started + 5.45s`, then calls only
`format_validated_action`. That formatter obtains a fresh strict receipt from
the installed mask and compares proposal, AABB, profile, state, ordered pool
occurrence, item metadata, support, clearance, source, and proposal key before
emitting the public `float32[3]` action. No boolean validation result can
authorize output. It resamples completion time after that work and suppresses
the action at or beyond `started + 5.75s`.

`CandidateZeroError` represents an absent/empty pool or strict-root-zero
catalog. `PlanningError` wraps state, scanner, beam, membership, clock, and
format failures with the failed stage. Neither path creates a fallback action.
Uninitialized, mode-A policy, and `optimize` remain explicit `NotReadyError`
until Task 7b.

## Regression coverage

- owned exact components and installed receipt revalidator;
- fixed A/B/C mode and B one-item tail behavior;
- real one-item B and C public actions with exact dtype and shape;
- B/C dispatch without cross-mode fallback;
- absolute 1.80/5.30/5.45/5.75 timing settings and 0.30 output reserve;
- fresh receipt completion at the exact 5.75s boundary emits no action and
  clears the temporary deadline guard;
- empty pool and strict-root-zero with no formatter call;
- state, scanner, beam, and formatter exception isolation;
- pool reorder rejection and duplicate-ID occurrence preservation;
- identical depth-zero catalog membership;
- task001 step-14 historical last-resort and 29.7 shadow actions never emitted;
- uninitialized/A explicit-not-ready behavior;
- AST audit: policy contains no action literal and its only return calls the
  exact formatter; no historical, random, or unchecked fallback import.

## Verification

Fresh final results after independent review fixes:

```text
agent B/C focused: 12 tests in 5.661s ... OK
legacy strict foundation contract: 16 tests in 5.491s ... OK
foundation + proposals + mask + catalog + transition + features + beam + agent:
  128 tests in 12.516s ... OK
full simulator discovery: 304 tests in 20.224s ... OK
py_compile five changed Python files: exit 0
```

## Known boundary

Task 7a does not implement mode-A ordering or offline skeleton planning, does
not package a submission ZIP, and does not claim PyBullet or Public score
improvement. It connects the analytically strict B/C path only. A fresh exact
mask pass is intentionally repeated at formatting time; the 0.30s reserve is
allocated for that fail-closed authorization.
