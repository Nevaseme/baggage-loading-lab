# Task 11: Family-Yield Staged Round-Robin

## Scope and single factor

This task changes proposal-family scheduling only. It does not change the
geometry, ExactMask profile, beam ranking, agent action boundary, or public
action format.

Production files:

- `simulator/agents/support_extreme_fusion_beam_exact_mask/proposals.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/catalog.py`

Test files:

- `simulator/tests/test_support_extreme_fusion_proposals.py`
- `simulator/tests/test_support_extreme_fusion_catalog.py`

## TDD evidence

The first Catalog fixture placed the only valid FREE proposal at raw ordinal
123, with a valid DENSE proposal available as a deadline distractor. Before
the production change it failed with an empty Catalog and zero raw/exact
attempts. After the staged scheduler implementation it passes and records its
first root at `normal.free_deepen`, without invoking DENSE.

The proposal API fixture first failed with `TypeError` because
`family_subset` was absent. It now proves explicit `None` compatibility,
subset isolation, and rejection of the ambiguous explicit-subset plus
`rescue`/`rescue_only` combinations. `deferred` remains allowed because it is
a container tier, not a proposal-family selector.

## Implementation

### Proposal API

`iter_fused_records(..., family_subset=None)` retains the original family
selection expression and ordering. An explicit sequence:

- accepts only `ProposalSource` members;
- removes repeated family values while retaining requested order;
- emits only the requested families;
- rejects simultaneous `rescue` or `rescue_only` selectors;
- continues to allow `deferred=True`.

The existing iterator-level round robin remains the orientation/family/
container fairness boundary. A 12-raw-work fixture proves one FREE quantum for
all six distinct orientations in both containers before any group receives a
second raw proposal.

### Strict Catalog stages

For ordinary containers, and then separately for an eligible deferred
priority-container tier, the scanner runs:

1. FREE boundary probe;
2. obstacle-face probe;
3. plane-derived-edge probe;
4. FREE deepen to a cumulative raw budget of at least 128 (subject to the
   configured global raw limit);
5. obstacle-face deepen;
6. plane-derived-edge deepen;
7. compact normal families (floor/wall, reserved support, support edge);
8. legacy extreme cross;
9. DENSE last, only for the pre-existing global-zero or explicit breadth
   rescue targets.

Each stage generates bounded work for every eligible pool occurrence before
exact validation proceeds in deterministic per-pool quanta. Each generator
receives at most `0.5 * remaining_time / remaining_pool_count`; this prevents
an early pool from consuming the later pools' construction opportunity and
reserves at least half of the remaining interval for ExactMask work. A
controlled-clock fixture proves the former single-global-deadline behavior
returns zero roots when both pool generators consume their supplied deadline,
while the staged time slices retain fresh roots for both pools before the hard
deadline. Rootless and
least-root pool occurrences sort first at each stage. A probe stops after the
first accepted root for an occurrence, so one pool cannot consume the root
catalog before the other occurrences receive their probe.

The wall-clock deadline is checked before generation and each exact attempt.
The stage raw quotas remain the primary deterministic work allocation.

### Exact-mask ownership and statistics

Every exposed root still comes from `ExactMask.validate` after an accepted
`ExactMask.diagnose`. A pool-local exact proposal-key set is shared across all
families, stages, and ordinary/deferred/rescue passes. The same geometry is
therefore never re-diagnosed merely because a later family generated it.

`CatalogStats` adds backward-compatible defaulted fields:

- `stage_attempts`
- `stage_roots`
- `first_root_stage`

The stage-attempt sum equals `exact_attempts`; an existing counting-mask
fixture now also proves that one repeatedly generated rejected geometry is
diagnosed exactly once across all stages.

Ordinary/deferred gating, per-pool/global root caps, rootless-only breadth
rescue, default global-zero rescue, deadline partial incumbents, duplicate
global item IDs, and child normal-only flags remain covered by regression
tests.

## E2 step-11 snapshot evidence

Snapshot:

`simulator/results/support_extreme_fusion/task001-b-seed42-e2-failure.npz`

A fresh staged scan on this saved pre-action observation found 64 strict
depth-zero roots in 0.424 seconds in the final direct diagnostic run,
well inside the 5.45-second Catalog deadline. The integration fixture repeats
the bounded scan and, for every exposed root, requires both a fresh matching
ExactMask receipt and successful `Agent.format_validated_action`. This is
candidate replay evidence only; no PyBullet physics was run in Task 11.

## Fresh verification

- Proposal + Catalog + Beam + Agent B/C integration after review fixes:
  77 tests, all pass, 6.333 s.
- Full package-aware discovery:
  `python -m unittest discover -t . -s simulator/tests -p 'test_*.py' -q`
  — 329 tests, all pass, 9.066 s.

An initial non-package-aware discovery command produced one collection error
for `test_quota_fair_starvation_diagnostics` because its relative import had
no package parent. The required `-t .` invocation resolved collection and is
the authoritative full-suite result above.

Independent Sol review initially identified two Important risks: an
unfrozen legacy-`None` order and pool-construction deadline starvation. The
Task 2 report confirmed the orientation/family/container round robin
pre-existed Task 11, and a frozen capped-output fixture now protects that
legacy behavior. Generation time slicing plus a dedicated validation reserve
fixed the real starvation edge. The final re-review result is **APPROVE** with
no Critical or Important findings.

## Limitations and next evidence

- This task demonstrates proposal recall and exact authorization at the E2
  failure snapshot; it does not claim improved physical episode completion or
  Public score.
- DENSE remains a bounded last-resort family and is never opened by Beam child
  scans where `allow_rescue=False`.
- A fresh official task001 B physics A/B run is required before deciding
  whether this scheduling factor improves placement count or merely moves the
  next failure boundary.
