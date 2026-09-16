# Task 3: One-factor physical benchmark gate

## Context

Task 2 added `SearchSettings.use_monotone_ingress`.  Compare exactly that flag
with all other settings fixed.  This task is measurement and adoption/revert;
it must not tune or modify production algorithm logic.

## Global constraints

- No dependency installation, network, Git, SIGNATE, or `simulator/src` edits.
- Use `apply_patch` for any harness/report edits.
- Do not change production settings other than selecting the existing Boolean flag at runtime.
- No rescue-without-depth in accepted benchmark runs.
- Seed is exactly 42; optimize seconds exactly 0.
- Adoption requires both tasks non-regressing, at least one strict improvement, all prior actions safe, and max policy < 6 seconds.

## Files

- Modify `simulator/tests/run_physics_smoke.py` only to add CLI selection and concise JSON output support if necessary.
- Create/update `docs/superpowers/plans/2026-08-13-monotone-ingress-benchmark.md`.
- Report `.superpowers/sdd/2026-08-13-monotone-ingress-packing/task-3-report.md`.

## Required harness behaviour

Add CLI option:

```python
parser.add_argument(
    "--monotone-ingress",
    choices=("on", "off"),
    default="on",
)
```

Immediately after constructing `Agent`, replace its settings with
`use_monotone_ingress=args.monotone_ingress == "on"` and reconstruct
`Planner`.  Include `monotone_ingress` in result JSON.  Do not change action
selection or environment behaviour.

Before editing, add a small unittest or parser/helper test that fails because
the harness cannot select the flag; after editing, verify it passes.  If making
the parser importable would create excessive refactoring, a subprocess
`--help` assertion is acceptable and must be observed RED then GREEN.

## Benchmark commands

Use the existing WSL dependency environment.  Run official four-item smoke
with monotone on first.  Then run:

```text
task000: 25 items, seed 42, optimize 0, monotone off
task000: 25 items, seed 42, optimize 0, monotone on
task001: 30 items, seed 42, optimize 0, monotone off
task001: 30 items, seed 42, optimize 0, monotone on
```

Save stdout/stderr to uniquely named files under
`.superpowers/sdd/2026-08-13-monotone-ingress-packing/benchmarks/`.  A nonzero
exit due to incomplete placement is expected; still parse the final JSON.

Report for every run:

- completed safe placements before first failed action (`completed_steps - 1` when final status is unsafe, else completed_steps);
- fill score and placed item ratio;
- exact failing status;
- maximum policy seconds;
- whether every action before the failed action had all statuses true.

## Adoption gate

```text
task000_on_safe >= task000_off_safe
and task001_on_safe >= task001_off_safe
and (task000_on_safe > task000_off_safe or task001_on_safe > task001_off_safe)
and every pre-failure on-action is safe
and max(on max_policy_seconds) < 6.0
```

If accepted, leave `use_monotone_ingress=True`.  If rejected, change only its
default in `settings.py` to `False`, add a focused test asserting the default,
run full unit suite, and retain ingress primitives/integration behind the flag.
Do not attempt another tuning factor.

## Evidence

Write exact commands, captured paths, metrics, adoption decision, full-suite
result after any default revert, original ZIP SHA-256
`3789B037DA39BD2F38215D711C42AD9CF504503F44B94016517A675044CB4A54`,
and Public baseline `12.622949582873819` to both benchmark doc and task report.

Return only status, concise four-run comparison, adoption decision, concerns.
