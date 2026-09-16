# Task 14 — `fixed_quota_exact_two_ply`

## Outcome

Implemented an independent, non-default mode-B planner that changes only the
analytical work order and work budget.  It retains the current strict root
catalog supplied by the caller, the current lexicographic objective, the
6-item/2-root admission limits, and the exact-mask authorization boundary.
`Agent` and the physical runner are intentionally unchanged.

The prior Beam scanned a child catalog before admission.  The new planner:

1. freshly applies every current depth-zero root and computes state-only
   features;
2. admits at most six item occurrences and two roots per occurrence;
3. spends fixed coverage work on at most eight admitted child states; and
4. proves at most twelve second edges (top four parents times three distinct
   child occurrences), without a grandchild scan.

The returned object is always the original caller-owned depth-zero
`ValidatedRoot`.  Every analytical edge is independently revalidated by
`apply_root(..., exact_revalidator=mask)`.  No raw proposal or proxy action can
leave the planner.

## Fixed coverage scanner

`CatalogWorkQuota` defaults to 128 generated raw records per visible pool
occurrence and 64 global exact attempts.  Dense, deferred, and rescue work are
disabled by default and require explicit quota authorization.

`StrictRootScanner.scan_coverage_fixed`:

- materializes a bounded normal-family list per ordered occurrence;
- performs exact proposal attempts occurrence-round-robin, so every available
  first attempt precedes any second attempt;
- stops an occurrence after its first strict root;
- preserves duplicate global item IDs as distinct pool occurrences;
- checks the absolute deadline before and after the single exact diagnostic;
- publishes only fresh strict roots; and
- records attempted/covered pools, the fixed exact cap, and quota exhaustion in
  `CatalogStats`.

The strict validation profile and its digest were not changed because these
are planner-work fields, not physical acceptance rules.

## Planner trace

`BSearchTrace` records deterministic work rather than wall-clock timings:

- freshly applied stage-one edges;
- admitted items and roots;
- child scan count, child exact attempts, and covered occurrences;
- freshly applied second edges;
- deepest proven placement count;
- deadline observation; and
- isolated branch exceptions.

This makes the 8 child-scan and 12 second-edge contracts directly auditable.

## TDD evidence

Initial focused RED failed at import because neither `CatalogWorkQuota` nor
`fixed_quota.py` existed.  After the minimal implementation, the focused
fixtures cover:

- forty-occurrence first-attempt fairness;
- fixed exact-cap exhaustion;
- duplicate item-ID occurrence identity;
- 64 depth-zero roots producing no more than eight child scans;
- a locally larger one-ply dead end losing to an exactly proven two-step
  branch;
- no grandchild scans and no more than twelve second edges;
- deadline preservation of a fresh original depth-zero incumbent; and
- twenty deterministic runs with identical root identity and trace.

Fresh project-local WSL runtime results:

```text
new focused:                    7 tests, PASS, 0.760s
fixed + catalog + old Beam:    45 tests, PASS, 1.759s
full simulator suite:         339 tests, PASS, 9.809s
```

Canonical full command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -q
```

## Files changed

- `simulator/agents/support_extreme_fusion_beam_exact_mask/catalog.py`
- `simulator/agents/support_extreme_fusion_beam_exact_mask/fixed_quota.py`
- `simulator/tests/test_support_extreme_fusion_fixed_quota.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-14-fixed-quota-exact-two-ply-report.md`

No `Agent`, runner, proposal generator, exact mask, geometry, profile setting,
historical artifact, Git state, dependency, or physical environment was
changed.  The planner is not yet the production default; physical comparison
requires a separate integration factor.

Independent Sol review initially found that a counted attempt called both
`diagnose` and `validate`, repeating the exact geometry pass.  A focused RED
observed the doubled sequence (`0, 0, 1, 1, ...`).  The scanner now consumes
the fresh strict `ValidationTrace.root` from its single diagnosed pass, and the
same test observes exactly one pass per attempt (`0, 1, ..., 39`).  Final
read-only re-review: APPROVE, no remaining Critical or Important finding.
