# Task 21e — Mode-A Agent and runner integration report

Date: 2026-08-19  
Algorithm: `layered_proxy_order_beam_exact_skeleton_repair`

## Outcome

Mode A is now wired through the public `Agent` lifecycle without changing the
B/C planner route or the exact action boundary.

- `get_init_states(optimize=True)` fixes mode A, records the initial
  container/packed-item baseline, and clears any prior plan.
- `optimize` constructs canonical occurrences, runs the existing
  `LayeredProxyOrderBeam`, compiles only complete candidates with
  `StrictSkeletonCompiler`, validates the resulting `ModeAPlan`, and stores
  only a full digest-valid plan.
- Any malformed/interrupted/partial/exceptional optimization clears the plan
  and returns the original complete index sequence.
- `policy` rebuilds settled state, injects at most six plan-derived advisory
  proposals, scans the current exact catalog, and delegates current-root
  selection to `ModeAExactSkeletonRepair`. It accepts only an identical
  catalog depth-zero root and returns through the existing fresh
  `format_validated_action` path.
- The official diagnostic runner now executes
  `get_info_for_optimization -> Agent.optimize -> set_item_order ->
  reset_item_stream -> env.reset` for resolved mode A and records optimization
  time, order, and the published plan trace.

No receipt, offline root, proxy candidate, or raw action dictionary is stored in
the Mode-A plan. No PyBullet episode, package install, Git operation, or Public
submission was performed in this task.

## Absolute schedules

Optimization uses one start time and these non-profile A-only settings:

- seed/input validation boundary: +8 s
- order beam deadline: +82 s
- strict compile deadline: +138 s
- final plan validation boundary: +145 s
- hard return boundary: +150 s

Online A policy uses +4.40 s catalog, +5.30 s repair, +5.45 s output reserve,
and +5.75 s hard formatting boundaries. Fresh ExactMask revalidation remains
mandatory at the public action boundary.

The A-only timing fields are excluded from `SearchSettings.profile_digest()`,
so B/C strict receipt profiles are unchanged.

## TDD evidence

Initial focused RED before Agent A integration:

```text
6 tests: 5 errors (Mode A NotReady) and 1 failure (plan not cleared)
```

Runner RED before official optimize flow integration:

```text
FAIL: test_mode_a_runs_official_optimize_order_reset_flow_and_records_timing
expected outcome success, observed not_ready
Ran 1 test — FAILED
```

Focused/related GREEN after the minimal implementation and stale NotReady
contract update:

```text
python -m unittest   tests.test_support_extreme_fusion_agent_a   tests.test_support_extreme_fusion_agent_bc   tests.test_support_extreme_fusion_contract   tests.test_run_support_extreme_fusion_physics

Ran 68 tests in 4.886s
OK
```

Fresh full package discovery:

```text
PYTHONPATH=simulator/.test_deps_linux:simulator   ./simulator/.venv_wsl/bin/python -m unittest discover   -s simulator/tests -t simulator -p 'test_*.py'

Ran 537 tests in 33.252s
OK
```

Compilation:

```text
python -m py_compile   simulator/agents/support_extreme_fusion_beam_exact_mask/agent.py   simulator/agents/support_extreme_fusion_beam_exact_mask/settings.py   simulator/tests/run_support_extreme_fusion_physics.py   simulator/tests/test_support_extreme_fusion_agent_a.py   simulator/tests/test_support_extreme_fusion_agent_bc.py   simulator/tests/test_support_extreme_fusion_contract.py   simulator/tests/test_run_support_extreme_fusion_physics.py

exit 0
```

## Changed files and SHA-256

```text
49D412268D5DE2420699DB13F67EA61A8743B8058433EF7EA20B4F517E35CCF4  agent.py
798D2F3A8F2F7ED889A84C029CEF78D83A2A3B2DAB27AFDE9D752A81BD2864C3  settings.py
247D4EDE9A508A8B600CD284623D7E071DB96618F5646F19A03FEADEEFA5EC62  run_support_extreme_fusion_physics.py
AA0461434C6443A33D8B29BFAB9E22C0B8BA1C02D51F19E3E76673064BFC61D9  test_support_extreme_fusion_agent_a.py
E98FE0B12260437A6674B0E1D4DDA8C49C6F761AE18C5B870C1BAEF7F50B5519  test_support_extreme_fusion_agent_bc.py
DAB4BED1FF060F3F50CB501000AC5DF60F6A9190890F547FE85E4E20894F55F8  test_support_extreme_fusion_contract.py
EA6BE84550933EA972092260AB9EC2CB1389BC692542EFB8F7126BC8A230C35A  test_run_support_extreme_fusion_physics.py
```

## Acceptance boundary

This establishes a runnable, exact-mask Mode-A route and an official-flow
runner path. It does not establish physical completion, timing acceptance on
the official environment, score improvement, or submission readiness. Those
remain Task 22 evidence gates.


## Sol review fix round 1

Three fail-closed boundaries were tightened without changing the root source or
public formatter:

1. A nonempty current exact catalog now establishes the same deterministic
   depth-zero incumbent used by mode B. If scanning reaches +5.30 s, repair is
   skipped; if A repair returns no root, the incumbent is retained provided the
   +5.75 s hard boundary has not elapsed. It remains an original catalog object
   and must pass the unchanged fresh formatter revalidation.
2. Compiler output is accepted only when `type(plan) is ModeAPlan`.
   Duck-typed or subclass-like objects cannot supply a returned order or become
   stored plan state.
3. Optimization now checks a finite clock strictly before +138 immediately
   after compile, strictly before +145 after plan/digest/permutation validation,
   and strictly before +150 immediately before publication. Equality, NaN, and
   infinity fail closed to the original complete order and clear plan state.

The runner regression also fixes the observable official lifecycle order:
`optimize -> set_item_order -> reset_item_stream -> reset`.

RED evidence:

```text
Focused Agent A: 9 tests
6 failures + 2 errors:
- late scanner invoked repair
- repair None returned PlanningError
- duck plan was stored
- +145 and +150/nonfinite boundaries published a plan
```

Fresh verification:

```text
Focused/related: Ran 72 tests in 5.469s — OK
Full:            Ran 541 tests in 32.373s — OK
py_compile:      exit 0
```

Updated hashes:

```text
C6A00852440C37507FDE2B0F1111E0A05EDE8C794750F0E8D7158035C1C0D079  agent.py
798D2F3A8F2F7ED889A84C029CEF78D83A2A3B2DAB27AFDE9D752A81BD2864C3  settings.py
247D4EDE9A508A8B600CD284623D7E071DB96618F5646F19A03FEADEEFA5EC62  run_support_extreme_fusion_physics.py
6C2377ACC9CFA2C0667E8FE5F0B4A38CA04EA7E2CBB2A51901692CA0CC6D91B0  test_support_extreme_fusion_agent_a.py
E98FE0B12260437A6674B0E1D4DDA8C49C6F761AE18C5B870C1BAEF7F50B5519  test_support_extreme_fusion_agent_bc.py
DAB4BED1FF060F3F50CB501000AC5DF60F6A9190890F547FE85E4E20894F55F8  test_support_extreme_fusion_contract.py
5D36E7B5675F699E7174689B0F7CDC42B0016A4C8277289079081E187F450EC5  test_run_support_extreme_fusion_physics.py
```

