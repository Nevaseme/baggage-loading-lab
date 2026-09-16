# Task 3 report — official-semantics shield and historical-plan cross

Date: 2026-08-24  
Scope: the new `portal_reserved_scaffold_dag` package, its focused tests,
matched cross runner/evidence, and this report. Task 2 code/evidence,
production agents, `progress.md`, the physical environment, and `submit/`
were not modified.

> Evidence in the initial checkpoint and Fix round 1 sections below is
> retained as historical audit context. Their 18-test count, earlier hashes,
> and earlier timing values are superseded by the Fix round 2 section at the
> end. Fix round 2 also corrects the earlier exact-boundary wording: the axis,
> diagonal, and partial-lift fixtures below are the authoritative literals.

## TDD RED → GREEN

The focused tests were written before any Task 3 production package existed.
The canonical RED command was:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_portal_reserved_scaffold_authorizer tests.test_portal_reserved_scaffold_historical_cross -v"
```

RED was the expected package-missing failure:

```text
ModuleNotFoundError: No module named 'agents.portal_reserved_scaffold_dag'
```

The implementation then added one current-state authorizer, a standalone
adaptation of the historical virtual-plan seed, and the public Agent wrapper.
The initial checkpoint focused GREEN command ran 18 tests and passed:

```text
Ran 18 tests in 17.552s
OK
```

The matched cross assertion is no longer skipped after its physical result
was materialized.

## Authorizer semantics and synthetic coverage

`authorizer.py` uses immutable `ActionProposal` and `AuthorizationResult`
receipts. Proposal positions are canonical little-endian float32 bytes and
all geometry checks promote those same bytes to float64. The state fingerprint
contains ordered visible-pool occurrences, full item signatures, container
ordinals/metadata/dimensions/planes/normals/shelf flags, packed signatures and
raw poses/quaternions, and profile semantics. Formatting performs a fresh
authorization and requires the original receipt identity, proposal digest,
state fingerprint, profile digest, and hard evidence to match.

The hard layer implements exact action/type/range/finite checks, selected
occurrence and container metadata binding, official `-0.005 m` plane
inclusion, world/local X handling, the official door clamp, effective lift and
ceiling clipping, Y-then-X motion at `0.01 m` samples, `0.015 m` conservative
transport contact, oriented settled-item OBB contact, and genuine target
penetration. Target contact/nearness is evidence, not an independent 15–18 mm
hard gate.

The settling layer reports support ratio, center/COM support, predicted drop,
landing surface, supporter pose/load, stack height, mass, and softness. Only
no landing surface and a strictly greater-than-`0.3 m` predicted drop reject.
Support/protection/priority/soft/depth terms remain score diagnostics.

Synthetic tests cover:

- every plane at the intended float32 `-5.0001 mm`/`-4.9999 mm` boundaries
  (the hand literals were corrected and reverified in Fix round 2);
- the cut plane and nonzero-container-X world/local conversion;
- `15.001 mm`, equality, and `14.999 mm` transport contact;
- door start-X clamp, lift-zero, default lift, and ceiling clipping;
- orientation 4 with the small shelf and tilted settled OBB versus broad AABB;
- genuine target penetration versus contact/nearness evidence;
- strict `0.300001 m`/`0.299999 m` drop and free-floating no-landing cases;
- non-hard partial-support, settling-gap, priority/soft, protection, and depth
  diagnostics;
- pool reorder, duplicate occurrences, packed raw pose/quaternion, container
  ordinal/metadata, and profile staleness;
- NaN, infinity, float32 overflow, bool/NumPy integer, invalid orientation,
  and expired deadline rejection;
- copy/forge/`dataclasses.replace`/different-state receipts and shared
  historical/planned/repair/emergency authorizer routing.

## Captured corpus

The Task 2 snapshot corpus authorized **25/25** known-safe actions. The known
step-25 failure was not authorized; its first hard rejection evidence was
`target_penetration` plus `transport`, with no support/protection bypass. The
recovered plane steps 0, 1, 2, 3, 5, 16, and 17 all passed plane inclusion.

## Matched physical cross

Command (canonical project-local WSL runtime; raw output is retained beside
the result):

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m tests.run_portal_reserved_scaffold_historical_cross --task 000 --items 41 --seed 42 --output results/portal_reserved_scaffold/task000-official-shield-cross-seed42.json > results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stdout.log 2> results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stderr.log"
```

The runner used the task000 41-item seed42 Mode-A lifecycle and the same
PyBullet/Gymnasium environment. Results:

These values are the superseded initial checkpoint; the current physical
values are recorded in Fix round 2 below.

| measure | value |
| --- | ---: |
| outcome | shield rejection at step 25 |
| returned safe actions | 25 |
| returned action prefix | 25/25 exact; divergence `[]` |
| local fill | `33.94392679167531` |
| returned `is_valid=false` | 0 |
| returned `is_placed_safe=false` | 0 |
| step 25 | rejected before `env.step` |
| first rejection reason | `target_penetration` |
| step-25 reasons | `target_penetration`, `transport` |
| optimize seconds | `19.108141512999282` |
| policy max seconds | `2.8384793040004297` |

The required result is
`simulator/results/portal_reserved_scaffold/task000-official-shield-cross-seed42.json`.
Raw logs are `task000-official-shield-cross-seed42.stdout.log` and
`task000-official-shield-cross-seed42.stderr.log` in the same directory.

## Initial checkpoint hashes and immutable artifact checks (superseded)

```text
package manifest SHA-256:       720f02438ec6d91f02768d52d10627f5473265185838c0843aff66c41ef38865
config SHA-256:                 f321c87bbd5c0b715e1f124e08620e50360634b274a2a38ee16b8be77dd19436
runner SHA-256:                 b2f5f0b5f91d3fea8d4a3bc712983df4db02e0bb75a268a6ccb5e183644f9629
historical seed SHA-256:        5be62aa1aa1982d129a57a0872971673e381023f1de033b7b05f27f07d443ff5
historical source SHA-256:      ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82
returned action-prefix SHA-256: a2074e7439ce83c0af6e0c9a75d8c59eed71c18e5d009e89fa7d465fd218cdab
submit manifest before/after:  95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c / same
```

The `submit/` regular-file manifest remained 20 files with the same
SHA-256 before and after the run.

## Regression and compile verification

Canonical focused Task 3 suite:

```text
Ran 18 tests in 17.552s
OK
```

Task 2 replay/runner plus relevant existing agent contract/integration
regressions were overcounted in the initial checkpoint. The reproducible
command and Fix-round-1 rerun below executed 57 tests.

`py_compile` passed for all four package files, both new test files, and the
cross runner.

## Changed files

```text
simulator/agents/portal_reserved_scaffold_dag/__init__.py
simulator/agents/portal_reserved_scaffold_dag/authorizer.py
simulator/agents/portal_reserved_scaffold_dag/historical_seed.py
simulator/agents/portal_reserved_scaffold_dag/agent.py
simulator/tests/test_portal_reserved_scaffold_authorizer.py
simulator/tests/test_portal_reserved_scaffold_historical_cross.py
simulator/tests/run_portal_reserved_scaffold_historical_cross.py
simulator/results/portal_reserved_scaffold/task000-official-shield-cross-seed42.json
simulator/results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stdout.log
simulator/results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stderr.log
.superpowers/sdd/2026-08-24-portal-reserved-scaffold-portfolio/task-3-report.md
```

No Task 2 file/evidence, current production agent, `progress.md`, physical
environment, or historical artifact was changed.

## Limitations and self-review

- The historical seed is intentionally a proposal seed only. Task 3 adds no
  portal reservation, planner, repair search, or score tuning.
- `_obb_separation` now returns the closest Euclidean OBB distance using exact
  vertex-face and edge-edge feature checks (intersections return zero). The
  transport loop uses an AABB lower bound only to skip pairs already farther
  than the 15 mm threshold, then performs the exact near-threshold check;
  static shelf geometry remains exact axis-aligned boxes.
- No general PyBullet settling-stability claim is made from the positive
  corpus; settling values are evidence/ranking diagnostics except for the two
  explicit impossibility checks.
- The prescribed Windows Signate environment lacks usable NumPy in this host;
  all focused, regression, compile, and physical verification used the
  existing project-local WSL dependency set.
- The unchanged historical worker `<2.0 s` test remains host-sensitive as
  documented by Task 2 (its fresh-process probe was 1/3 pass). Task 3 did not
  alter that worker or its threshold.
- The cross reproduces the 25-action historical prefix and fill target, but
  Task 4 continuation and later A/B/C physical negative coverage remain
  required before any production promotion.

Self-review conclusion: Task 3's single authorizer is the only path from the
historical proposal to a returned action; rejected candidates fail closed
before `env.step`. The historical seed's legacy candidate fallback remains
proposal-only and cannot escape the authorizer as an unchecked, dummy, or
previous action.

## Fix round 1 — Sol review closure and reproducible verification

The first review identified one Critical official door-clamp false acceptance
and Important gaps in full observable fingerprinting, float32 action range,
Euclidean OBB distance, lower-surface landing search, diagnostics, synthetic
coverage, cross provenance, and report reproducibility. This section supersedes
the initial checkpoint values above where they differ.

### TDD RED → GREEN

The new focused tests were written with comments naming the production
mutation each catches. The first Fix-round-1 focused run showed the intended
old-behavior failures: 5 assertion failures and 1 missing-diagnostic error
(inverted clamp, action range, fingerprint, OBB distance, settling support,
and protection/depth evidence). Production changes were then made only in the
new authorizer/cross scope. The final canonical focused command was:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_portal_reserved_scaffold_authorizer tests.test_portal_reserved_scaffold_historical_cross -v"
```

The core Fix-round-1 focused set was 27/27; one additional standalone
diagonal-transport fixture was then run as a separate synthetic check. The
final raw log `simulator/results/portal_reserved_scaffold/fix-round-1-focused.log`
therefore records:

```text
Ran 28 tests in 13.398s
OK
```

The implementation now applies `min(max(target_x, x_min), x_max)` even for an
inverted door interval; fingerprints all observable container keys (including
volume and arbitrary metadata), ordered packed keys, container ordinals, and
deterministic array fields such as depth maps; hard-validates canonicalized
place positions in `[-100, 100]`; and separates positive-volume penetration
from exact closest-distance evidence. Settling considers every overlapping
surface at or below the target bottom plus floor, reports highest landing,
14 mm support gaps, 67% support, supporter load, hard-on-soft/priority
protection evidence, and nullable depth-map consistency without using these
risk terms as hard gates. Four-centimeter drops and `0.299999 m` remain legal;
only `>0.3 m` predicted drop and genuine no-landing reject.

Synthetic coverage added in this round includes the official inverted-clamp
reviewer probe (`length=1.5`, target X `-0.1`, obstacle X `0.85`, start X
`0.20`), float32 `X=200` rejection, hand-derived vertex/face and edge/edge
distance cases, diagonal `11 mm + 11 mm` transport clearance above 15 mm,
lift `0`/`0.08`/ceiling-clipped partial values, and a true diagonal cut plane.
The exact axis/diagonal hand literals and partial-lift assertion were corrected
and reverified in Fix round 2 below, along with independent packed
pose/quaternion and container-ordinal staleness, 67%/14 mm support,
protection attributes, and depth evidence changes.

### Corpus and regression commands/raw logs

The explicit corpus command was:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest -v tests.test_portal_reserved_scaffold_authorizer.PortalReservedScaffoldAuthorizerTests.test_captured_task000_recalls_at_least_24_of_25_and_rejects_step_25 tests.test_portal_reserved_scaffold_authorizer.PortalReservedScaffoldAuthorizerTests.test_recovered_plane_margin_steps_are_accepted"
```

Raw log: `simulator/results/portal_reserved_scaffold/fix-round-1-corpus.log`;
known-safe recall was 25/25, the known failure was 0/1 accepted, and recovered
plane steps passed.

The canonical regression command was:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_replay_historical_predicates tests.test_run_historical_conservative_extreme_point_physics tests.test_run_support_extreme_fusion_physics -v"
```

The first raw run is retained at
`simulator/results/portal_reserved_scaffold/fix-round-1-regression.log`; it
has one known host-sensitive Task 2 worker timing failure at 3.156 s versus
the unchanged 2.0 s assertion. The immediate same-command rerun is retained
at `fix-round-1-regression-rerun.log` and passed all 57 tests. No Task 2 or
current production worker was changed. Compile verification used:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m py_compile agents/portal_reserved_scaffold_dag/__init__.py agents/portal_reserved_scaffold_dag/authorizer.py agents/portal_reserved_scaffold_dag/historical_seed.py agents/portal_reserved_scaffold_dag/agent.py tests/test_portal_reserved_scaffold_authorizer.py tests/test_portal_reserved_scaffold_historical_cross.py tests/run_portal_reserved_scaffold_historical_cross.py"
```

Raw log: `simulator/results/portal_reserved_scaffold/fix-round-1-py_compile.log`;
the command exited 0.

### Independent matched-cross verification

The cross was rerun with the canonical command and raw stdout/stderr:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m tests.run_portal_reserved_scaffold_historical_cross --task 000 --items 41 --seed 42 --output results/portal_reserved_scaffold/task000-official-shield-cross-seed42.json > results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stdout.log 2> results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stderr.log"
```

The cross test independently hashes current package files (excluding
`__pycache__`), the runner, `historical_seed.py`, and the real immutable
`submit/Conservative Extreme-Point Packing_score29.7/high_score/agent.py`;
it independently rebuilds the submit manifest baseline, action-prefix hash,
safe count, maximum record timing, evaluator inside-volume fill, and packed
count rather than accepting the result JSON's self-claims. Current physical
values are:

```text
outcome: shield_rejection at step 25
safe placements: 25; records: 26 (25 safe + one pre-step rejection)
prefix: 25/25 exact; divergence: []
local fill: 33.94392679167531; packed count: 25
policy timing count/p50/p95/p99/max: 26 / 0.7281827059996431 / 1.7625456977484646 / 2.0739378137495805 / 2.1533975199999986 s
optimize: 24.26772184299989 s
step 25: rejected before env.step; first reason: target_penetration
step 25 reasons: target_penetration, transport
returned invalid/unsafe: 0 / 0
```

Current hashes are:

```text
package manifest SHA-256:       2727211ea9ab51aacb9c5190ce0c2e292587d8bcce502448668dd84bd4ed4701
config SHA-256:                 f321c87bbd5c0b715e1f124e08620e50360634b274a2a38ee16b8be77dd19436
runner SHA-256:                 741bac6311be61f158f8817a3d422ee367d72bb6f3c499f855686db19778f997
historical seed SHA-256:        5be62aa1aa1982d129a57a0872971673e381023f1de033b7b05f27f07d443ff5
historical source SHA-256:      ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82
returned action-prefix SHA-256: a2074e7439ce83c0af6e0c9a75d8c59eed71c18e5d009e89fa7d465fd218cdab
submit manifest before/after:  95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c / same
```

The final changed-file scope is the four package files, two package tests,
the cross runner, refreshed cross result/stdout/stderr, the Fix-round-1 raw
logs, and this report. `progress.md`, all Task 2 files/evidence, current
production agents, and every file under `submit/` remained unchanged.

## Fix round 2 — exact synthetic boundaries and physical step accounting

This round addresses the review findings that the Fix-round-1 report
overstated its exact boundary literals and that the cross runner used the
post-rejection record length (`26`) as the number of actual `env.step` calls.
No authorizer or historical-seed production code changed in this round.

### TDD RED → GREEN

Before the runner fix, the focused review probes were run against the saved
artifact with these tests:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest -v tests.test_portal_reserved_scaffold_authorizer.PortalReservedScaffoldAuthorizerTests.test_float32_plane_margin_is_strict_for_every_axis_plane tests.test_portal_reserved_scaffold_authorizer.PortalReservedScaffoldAuthorizerTests.test_effective_lift_has_zero_default_and_ceiling_clipped_partial_values tests.test_portal_reserved_scaffold_authorizer.PortalReservedScaffoldAuthorizerTests.test_diagonal_cut_plane_float32_boundary_uses_hand_literal_one_e_minus_seven_m tests.test_portal_reserved_scaffold_authorizer.PortalReservedScaffoldAuthorizerTests.test_action_position_range_is_hard_validated_after_float32_canonicalization tests.test_portal_reserved_scaffold_historical_cross.PortalReservedScaffoldHistoricalCrossTests.test_matched_cross_artifact_records_prefix_and_rejection_boundary"
```

The intentional RED result was `Ran 5 tests ... FAILED`: the four
authorizer-boundary tests passed, while the cross assertion failed with
`AssertionError: 26 != 25` for `env_step_count_before`. Raw output is
`simulator/results/portal_reserved_scaffold/fix-round-2-red.log`.

The tests now use hand-derived float32-sensitive fixtures: every axis plane
uses the `-5.0001/-4.9999 mm` pair, the true diagonal cut plane uses z
positions `0.62476110` and `0.62476100` whose literals differ by exactly
`1e-7 m`, and the expected signed margins are `-0.0050000412` and
`-0.0049999569`. The partial ceiling branch asserts the hand-derived
`effective_lift == 0.0515000095`; the range test covers exact `-100`/`100`
and float32-canonicalized values just outside those bounds. The cross test
explicitly catches substituting the post-rejection `len(records)` for the
actual environment-step counter.

The minimal GREEN change was to increment an explicit `env_step_count` only
after a successful `env.step(action)` and to record that counter on the
pre-step rejection path. The targeted RED→GREEN rerun passed:

```text
Ran 5 tests in 1.980s
OK
```

Raw output is `simulator/results/portal_reserved_scaffold/fix-round-2-green.log`.

### Focused, corpus, regression, and compile verification

The final focused command was:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_portal_reserved_scaffold_authorizer tests.test_portal_reserved_scaffold_historical_cross -v"
```

The final focused log records `Ran 28 tests in 7.461s` and `OK` at
`simulator/results/portal_reserved_scaffold/fix-round-2-focused.log`.
The explicit corpus command records `Ran 2 tests in 5.714s` and `OK` in
`fix-round-2-corpus.log`: the known-safe replay is 25/25 and the known
step-25 negative is 0/1 accepted.

The canonical regression command from Fix round 1 was rerun without changing
Task 2 or its worker:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m unittest tests.test_replay_historical_predicates tests.test_run_historical_conservative_extreme_point_physics tests.test_run_support_extreme_fusion_physics -v"
```

It records `Ran 57 tests in 13.884s` and `OK` in
`fix-round-2-regression.log`. The required compile command was also rerun for
all four package files, both package tests, and the cross runner; it exited 0
with raw output in `fix-round-2-py_compile.log`.

### Canonical matched physical cross

The final physical command was:

```text
wsl.exe -e bash -lc "cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading/simulator && PYTHONPATH=.:tests:.test_deps_linux ./.venv_wsl/bin/python -m tests.run_portal_reserved_scaffold_historical_cross --task 000 --items 41 --seed 42 --output results/portal_reserved_scaffold/task000-official-shield-cross-seed42.json > results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stdout.log 2> results/portal_reserved_scaffold/task000-official-shield-cross-seed42.stderr.log"
```

The current result and the independent cross test agree on:

```text
outcome: shield_rejection at step 25
safe placements / records: 25 / 26 (one pre-step rejection record)
actual env.step count before/after rejection: 25 / 25
prefix: 25/25 exact; divergence: []
local fill: 33.9439267916753; packed count: 25
returned invalid / unsafe: 0 / 0
policy timing count/p50/p95/p99/max: 26 / 1.10213229299916 / 1.71950064875 / 1.79878066825222 / 1.82230253800299 s
optimize: 27.7168867340006 s
step-25 first reason: target_penetration
step-25 reasons: target_penetration, transport
```

The cross test recomputes the current package manifest, runner digest,
historical source digest, submit manifest before/after, action-prefix digest,
safe count, maximum record timing, packed count, and fill from recorded volume
inputs; it does not trust the result JSON's self-reported values. Current
hashes are:

```text
package manifest SHA-256:       2727211ea9ab51aacb9c5190ce0c2e292587d8bcce502448668dd84bd4ed4701
config SHA-256:                 f321c87bbd5c0b715e1f124e08620e50360634b274a2a38ee16b8be77dd19436
runner SHA-256:                 31f4134f8c4de6f7f5f7bd82a53e5d614f0e7890276251c2e2a1fbdf20f6507f
historical seed SHA-256:        5be62aa1aa1982d129a57a0872971673e381023f1de033b7b05f27f07d443ff5
historical source SHA-256:      ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82
returned action-prefix SHA-256: a2074e7439ce83c0af6e0c9a75d8c59eed71c18e5d009e89fa7d465fd218cdab
submit manifest before/after:  95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c / same
```

### Fix-round-2 changed scope and concerns

Changed in this round: the two focused test files, the matched-cross runner,
the regenerated matched-cross JSON and its canonical stdout/stderr, the
Fix-round-2 raw logs, and this report. The authorizer package, historical
seed, Task 2 evidence/code, current production agents, `progress.md`, and
`submit/` remained unchanged.

The Task 2 worker `<2.0 s` timing check remains host-sensitive as documented
in Fix round 1; the fresh Fix-round-2 57-test run passed, but that unrelated
flaky concern is not hidden and Task 3 did not alter its worker or threshold.
