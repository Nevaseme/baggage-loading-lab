# Task 1 report: Continuous ingress skyline primitives

## Status

DONE

## Changed files

- `simulator/agents/highscore/ingress.py`
- `simulator/tests/test_highscore_ingress.py`
- `.superpowers/sdd/2026-08-13-monotone-ingress-packing/task-1-report.md`

## RED evidence

Command:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_ingress -v'
```

Result: exit code 1. `ModuleNotFoundError: No module named 'agents.highscore.ingress'` while importing the new test module. This was the expected missing-feature failure before `ingress.py` existed.

## GREEN evidence

Command:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_ingress -v'
```

Result: exit code 0; 7 tests ran and all passed.

## Regression evidence

Command:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_geometry simulator.tests.test_highscore_free_space -v'
```

Result: exit code 0; 11 tests ran and all passed.

## Self-review findings

- `maximum_free_opening` clips inputs, merges touching blockers at `1e-6`, and measures complement openings.
- `build_frontier` uses usable walls, both static and placed AABBs, Z-band filtering, raw obstacle front faces, and `1e-6` skyline merging. Tilted placed AABBs are not excluded.
- `candidate_x_intervals` emits wall, frontier-boundary, and centred starts; filters out-of-wall footprints; computes the minimum `front_y` across every overlapped segment; and returns sorted, `1e-6`-deduplicated starts.
- No simulator source or configuration files were changed.

## Concerns

None. `clearance` is retained in the required interface but does not alter the returned physical skyline because the required `front_y` is the raw obstacle `minimum[1]`; placement clearance remains the caller's responsibility.

## Fix round 1

### Changed files

- `simulator/agents/highscore/ingress.py`
- `simulator/tests/test_highscore_ingress.py`
- `.superpowers/sdd/2026-08-13-monotone-ingress-packing/task-1-report.md`

### RED evidence

Command:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_ingress -v'
```

Result: exit code 1; the three new boundary tests failed as expected:

- a `5e-7` positive opening was merged into a blocker and returned `0.0`;
- a width of `1.0000005` within walls `[-0.5, 0.5]` returned an outside start;
- a `1e-7` positive frontier overlap was omitted from the back-limit minimum.

### GREEN evidence

Command:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_ingress -v'
```

Result: exit code 0; 10 tests ran and all passed.

### Regression evidence

Command:

```powershell
wsl.exe -e bash -lc 'cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading && PYTHONPATH=.:simulator/.test_deps_linux python3 -m unittest simulator.tests.test_highscore_geometry simulator.tests.test_highscore_free_space -v'
```

Result: exit code 0; 11 tests ran and all passed.

### Self-review findings

- Blockers now merge only when their clipped intervals overlap or touch exactly; every positive free opening is retained.
- Footprints wider than the wall interval are rejected strictly, and candidate starts are filtered rather than clamped into invalid coordinates.
- Every strictly positive frontier overlap contributes to `back_limit_y`; the `1e-6` tolerance remains limited to coordinate deduplication and skyline merging.

### Concerns

None.
