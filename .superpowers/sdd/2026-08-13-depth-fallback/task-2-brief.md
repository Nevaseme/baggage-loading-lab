# Task 2: Geometry rescue A/B physical gate

## Constraints

- Read the depth-fallback design and plan before edits.
- No dependency installation, network, Git, SIGNATE, or `simulator/src` edits.
- Change exactly the geometry-rescue enable flag; monotone ingress stays off.
- Do not use the harness's older `--rescue-without-depth` override.
- Seed 42, optimize seconds 0, same sample prefixes.
- Hard safety validator, candidate ranking, and deadline remain unchanged.

## TDD and files

- Add `SearchSettings.use_geometry_rescue: bool = True`.
- Gate the call to `Agent._geometry_rescue` on that flag.
- Add focused tests for default on and disabled behavior; observe RED before
  implementation and GREEN after.
- Add `--geometry-rescue {on,off}`, default on, to
  `simulator/tests/run_physics_smoke.py`; rebuild both settings and Planner
  consistently and include `geometry_rescue` in JSON.
- Extend the existing CLI help test and observe RED/GREEN.
- Create benchmark logs in
  `.superpowers/sdd/2026-08-13-depth-fallback/benchmarks/`.

## Runs

1. Four-item smoke with monotone off, rescue on.
2. task000 25 items, monotone off, rescue off.
3. task000 25 items, monotone off, rescue on.
4. task001 30 items, monotone off, rescue off.
5. task001 30 items, monotone off, rescue on.

## Adoption gate

Adopt only if task000 rescue-on safe placements are at least 17, task001 is
strictly above 20, every action before the first failure is safe, and maximum
policy time is below 6 seconds.  Otherwise default the flag off and leave it as
diagnostic code.  Record fill, ratio, final status, and exact timings.
