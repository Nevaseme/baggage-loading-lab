# Monotone-ingress one-factor physical benchmark

## Status

Complete: the physical A/B gate rejected monotone ingress because task001
regressed from 20 to 18 safe placements.  The sole production reversion is the
default `SearchSettings.use_monotone_ingress=False`; the runtime A/B switch and
ingress implementation remain intact.  This sandbox cannot start WSL
(`Wsl/Service/CreateInstance/E_ACCESSDENIED`), so parent-supplied WSL results
are recorded below and no alternate environment, dependency installation,
network access, SIGNATE action, Git command, or `simulator/src` edit was
attempted.

## Intended one-factor harness change

`simulator/tests/run_physics_smoke.py` contains a subprocess `--help` unittest
asserting that `--help` exposes `--monotone-ingress`.  After the parent task
observed that test fail for the expected missing option, the harness added the
required `on`/`off` option (default `on`).  Immediately after constructing the
Agent, it replaces `use_monotone_ingress` from that option and reconstructs the
Planner.  The result JSON records `monotone_ingress` as the selected string
mode.  The parent physical outputs establish that both flag modes execute.

The exact blocked RED command is:

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 -m unittest tests.run_physics_smoke.PhysicsSmokeCliTests -v'
```

Its sandbox diagnostic is captured in
`.superpowers/sdd/2026-08-13-monotone-ingress-packing/benchmarks/2026-08-13-task3-harness-red-sandbox-denied.stderr.txt`.

## Parent WSL benchmark commands and captured outputs

All commands must use the existing WSL dependency environment, with no
`--rescue-without-depth` argument.

```text
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 -m unittest tests.run_physics_smoke.PhysicsSmokeCliTests -v'
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --task 000 --items 4 --optimize-seconds 0 --monotone-ingress on'
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --task 000 --items 25 --optimize-seconds 0 --monotone-ingress off'
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --task 000 --items 25 --optimize-seconds 0 --monotone-ingress on'
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --task 001 --items 30 --optimize-seconds 0 --monotone-ingress off'
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux python3 tests/run_physics_smoke.py --task 001 --items 30 --optimize-seconds 0 --monotone-ingress on'
```

Captured stdout/stderr paths are:

| Run | stdout | stderr |
| --- | --- | --- |
| task000 off | `benchmarks/task000_off.stdout.txt` | `benchmarks/task000_off.stderr.txt` |
| task000 on | `benchmarks/task000_on.stdout.txt` | `benchmarks/task000_on.stderr.txt` |
| task001 off | `benchmarks/task001_off.stdout.txt` | `benchmarks/task001_off.stderr.txt` |
| task001 on | `benchmarks/task001_on.stdout.txt` | `benchmarks/task001_on.stderr.txt` |

All four runs use seed 42 (the harness's fixed seed),
`--optimize-seconds 0`, and omit `--rescue-without-depth`.

## Physical results

`safe placements` is `completed_steps - 1` because every run ends in its first
unsafe action.  Every action before that final action had all statuses true.

| Run | Safe placements | Fill score | Placed ratio | Final failing status | Max policy seconds | Pre-failure safe |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| task000 off | 17 | 11.337727 | 0.68 | `included=true, valid=false, placed_safe=false` | 2.9123 | yes |
| task000 on | 17 | 12.919968 | 0.68 | `included=true, valid=false, placed_safe=false` | 3.0049 | yes |
| task001 off | 20 | 20.221333 | 0.6667 | `included=true, valid=false, placed_safe=false` | 5.7507 | yes |
| task001 on | 18 | 17.122425 | 0.6 | `included=true, valid=false, placed_safe=false` | 5.7503 | yes |

## Adoption gate

Rejected.  task000 is unchanged at 17, while task001 regresses from 20 to 18;
therefore both non-regression and strict-improvement requirements fail.  The
other gate conditions pass: all pre-failure on-actions are safe and the larger
on-run policy maximum is 5.7503 seconds, below 6.0 seconds.

The default was changed only to `False`.  A focused default test observed RED
(`AssertionError: True is not false`) before that edit and GREEN afterward.
The available Windows full discovery run cannot import NumPy and reported six
module import errors; it is not a regression verdict.  The WSL full-suite
verification remains outstanding because this sandbox cannot start WSL.

## Immutable reference evidence

- Original ZIP SHA-256: `3789B037DA39BD2F38215D711C42AD9CF504503F44B94016517A675044CB4A54`
- Public baseline: `12.622949582873819`
