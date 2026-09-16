# Task 3 report: one-factor physical benchmark gate

## Status

Rejected.  The parent WSL A/B runs show task001 regressing from 20 safe
placements with monotone ingress off to 18 with it on.  The default is therefore
reverted only in `SearchSettings` to `False`; the runtime flag and ingress
implementation are retained.  This sandbox cannot start WSL, and no alternative
runtime was created or used.

## Harness TDD state

Added a small subprocess `--help` unittest to
`simulator/tests/run_physics_smoke.py`.  The parent task observed the required
RED failure: the help output lacked `--monotone-ingress`.  The harness now adds
the required `on`/`off` option (default `on`), replaces the Agent's immutable
setting immediately after construction, reconstructs its Planner, and includes
the chosen string mode as `monotone_ingress` in the result JSON.

The parent-observed RED command was:

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 -m unittest tests.run_physics_smoke.PhysicsSmokeCliTests -v'
```

The WSL sandbox command attempted in this task was rejected before execution
with `Wsl/Service/CreateInstance/E_ACCESSDENIED` (access denied); its raw
diagnostic is saved as
`benchmarks/2026-08-13-task3-harness-red-sandbox-denied.stderr.txt`.  The parent
then completed the A/B benchmark runs below.

## Four-run comparison

| Run | Safe placements | Fill score | Placed ratio | Failure status | Max policy seconds | Pre-failure safe |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| task000, monotone off | 17 | 11.337727 | 0.68 | `included=true, valid=false, placed_safe=false` | 2.9123 | yes |
| task000, monotone on | 17 | 12.919968 | 0.68 | `included=true, valid=false, placed_safe=false` | 3.0049 | yes |
| task001, monotone off | 20 | 20.221333 | 0.6667 | `included=true, valid=false, placed_safe=false` | 5.7507 | yes |
| task001, monotone on | 18 | 17.122425 | 0.6 | `included=true, valid=false, placed_safe=false` | 5.7503 | yes |

The raw files are `benchmarks/task000_off.stdout.txt`,
`benchmarks/task000_off.stderr.txt`, `benchmarks/task000_on.stdout.txt`,
`benchmarks/task000_on.stderr.txt`, `benchmarks/task001_off.stdout.txt`,
`benchmarks/task001_off.stderr.txt`, `benchmarks/task001_on.stdout.txt`, and
`benchmarks/task001_on.stderr.txt`.  Exact invocations are recorded in
`docs/superpowers/plans/2026-08-13-monotone-ingress-benchmark.md`.  Every run
uses seed 42, `--optimize-seconds 0`, and omits rescue-without-depth.

## Adoption

Rejected.  `task001_on_safe` (18) is below `task001_off_safe` (20), so the
non-regression condition is false; neither task has a strict safe-placement
improvement.  All pre-failure on-actions were safe and the maximum on policy
time was 5.7503 seconds (<6.0), but those passing conditions cannot override the
regression.  `SearchSettings.use_monotone_ingress` now defaults to `False`.

## Default-revert TDD and tests

Added `tests/test_highscore_settings.py` with a focused default assertion.

```text
Windows RED:  .\.signate_venv\Scripts\python.exe -m unittest tests.test_highscore_settings.SearchSettingsDefaultTests -v
Result: FAIL — AssertionError: True is not false

Windows GREEN: .\.signate_venv\Scripts\python.exe -m unittest tests.test_highscore_settings.SearchSettingsDefaultTests -v
Result: OK (Ran 1 test)

Windows full: .\.signate_venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
Result: FAILED (errors=6); all highscore modules failed at import with ModuleNotFoundError: No module named 'numpy'.
```

The full-discovery failure is an existing Windows environment dependency gap,
not a test failure in the changed setting.  No dependency was installed.  The
brief-required WSL full suite remains outstanding because WSL cannot start in
this sandbox.

## Immutable reference evidence

- Original ZIP SHA-256: `3789B037DA39BD2F38215D711C42AD9CF504503F44B94016517A675044CB4A54`
- Public baseline: `12.622949582873819`

## Concerns

The official four-item monotone-on smoke has no separately supplied captured
output, and the WSL full suite after the default revert is still needed for a
complete green-suite claim.  The Windows full discovery cannot substitute for
it because NumPy is absent from the existing Windows virtual environment.
