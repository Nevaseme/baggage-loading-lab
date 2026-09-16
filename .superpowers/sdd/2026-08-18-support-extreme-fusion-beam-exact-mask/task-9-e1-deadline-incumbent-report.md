# Task 9 — E1 strict deadline incumbent

## Outcome

Implemented the single-factor deadline-inversion repair identified by Task 8.
Only the Agent boundary and its B/C integration tests changed. Proposal
generation, ExactMask, RootCatalog, beam search, settings, and simulator code
were not changed.

When a non-empty strict catalog returns after the mode-B search deadline, the
Agent now selects a deterministic original depth-zero catalog root without
starting child search. When `choose_b` returns `None`, this recovery is used
only if a fresh clock sample proves that the B deadline has been reached and
the 5.75-second hard deadline has not. An early `None` and every beam exception
remain fail-closed.

The selected root still cannot authorize an action directly. It must pass the
existing identity membership check and the formatter's fresh matching
`ExactMask.revalidate` before an action dictionary is constructed.

## Production change

File: `simulator/agents/support_extreme_fusion_beam_exact_mask/agent.py`

After scanning a non-empty `RootCatalog`, `policy` now:

1. establishes a cheap `_deadline_incumbent` from the catalog immediately;
2. samples the post-scanner time and rejects non-finite time or scanner return
   at/after the 5.75-second hard boundary;
3. preserves the unchanged B beam path when the scanner returns before the
   5.30-second search deadline;
4. skips the B beam and uses the catalog incumbent when that deadline is
   already reached;
5. recovers from a B `None` only when a post-beam clock sample proves deadline
   expiry before the hard boundary;
6. allows only this deadline incumbent to cross the old 5.45-second
   output-reserve boundary, while retaining the formatter's mandatory
   post-revalidation `<5.75s` check.

The deterministic incumbent rank is lexicographic:

1. zero rule violations;
2. strict evidence;
3. lower violation count;
4. higher support ratio;
5. higher minimum clearance;
6. lower box top;
7. lower box center Z;
8. ascending `RootRecord.stable_key` and raw ordinal.

All production `ValidatedRoot` instances are already strict and zero-violation;
those leading fields keep the helper's contract explicit without relaxing the
type boundary.

## Safety boundary

- No raw proposal, approximate candidate, fallback action dictionary, or proxy
  transition is introduced.
- The incumbent is the identical `ValidatedRoot` object from the current
  depth-zero catalog.
- No child scan or transition is performed on the deadline path.
- The final formatter repeats pool occurrence, item signature, container
  ordinal, profile, state fingerprint, box, proposal, and strict evidence
  checks.
- Exact revalidation returning boolean, stale evidence, or mismatched evidence
  remains non-authorizing.
- Finishing formatting at exactly `5.75s` still emits no action.
- Beam exceptions are never converted to an incumbent.

## TDD evidence

The scanner-late regression was first observed failing with:

```text
PlanningError: planning exceeded the 5.45s output-reserve boundary
```

The rank regression was first observed failing with:

```text
AttributeError: 'Agent' object has no attribute '_deadline_incumbent'
```

The post-beam expiry regression was run after temporarily retaining the old
`None` behavior and failed with:

```text
PlanningError: B beam returned no root
```

After the minimal implementation, all three became GREEN. The controlled-clock
fixtures cover:

- scanner returns a non-empty exact catalog at `start + 5.45s`;
- B beam is not called;
- an identical catalog depth-zero root reaches the real formatter;
- B beam called before expiry may return `None` at exactly `start + 5.30s` and
  recover to the catalog incumbent;
- a late incumbent whose fresh revalidation finishes at exactly
  `start + 5.75s` is rejected, with the active deadline guard cleaned up;
- rank precedence through support, clearance, top height, center height, and
  stable key.

## Fresh verification

Bundled project WSL runtime with project-local dependencies:

```text
Agent B/C focused:                 15 tests, PASS, 5.747s
support_extreme_fusion combined: 131 tests, PASS, 12.913s
simulator full suite:            318 tests, PASS, 16.613s
```

Canonical full-suite command:

```bash
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator -p 'test_*.py' -v
```

An earlier discovery invocation rooted at `simulator/tests` produced a
collection-only relative-import error in the existing quota-fair diagnostic
test. Running discovery from `simulator` preserved its package context and
completed all 318 tests successfully; no test was changed to hide that issue.

## Files changed

- `simulator/agents/support_extreme_fusion_beam_exact_mask/agent.py`
- `simulator/tests/test_support_extreme_fusion_agent_bc.py`
- `.superpowers/sdd/2026-08-18-support-extreme-fusion-beam-exact-mask/task-9-e1-deadline-incumbent-report.md`

No physical episode was run in this task. The next evidence step is to replay
task001 mode B seed42 and verify that the former step-8 PlanningError becomes a
freshly revalidated physical action while the hard policy limit remains intact.
