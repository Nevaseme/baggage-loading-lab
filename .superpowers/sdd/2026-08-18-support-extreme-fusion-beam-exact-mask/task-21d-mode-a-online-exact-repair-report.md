# Task 21d — Mode-A Observation-Derived Exact Skeleton Repair

Date: 2026-08-19

## Outcome

Implemented two unintegrated Mode-A building blocks:

1. an optional advisory ingress on `StrictRootScanner.scan`; and
2. `ModeAExactSkeletonRepair`, a stateless observation-derived selector.

No Agent route, public action formatter, PyBullet episode, or submission package
was changed by this task.

## Catalog advisory boundary

`scan(..., advisory_proposals=())` is empty by default. With the default, no
new branch, counter, pass label, or proposal work executes. A golden regression
compares ordered proposal keys, provenance, pass names, raw ordinals, and the
complete `CatalogStats` value for omitted versus explicit-empty calls.

When supplied, the scanner:

- deduplicates by exact proposal key and considers at most six unique hints;
- validates against the current ordered pool and current state;
- runs `ExactMask.diagnose`, then a distinct fresh `ExactMask.validate`;
- compares every receipt/action binding through the existing full helpers;
- rejects altered, missing, stale, invalid, or mismatched evidence;
- exposes accepted evidence as an ordinary current `RootCatalog` member with
  stable `advisory` pass/provenance metadata;
- applies the existing per-pool/global caps and seeds normal-family exact
  deduplication.

Invalid advisory proposals never become roots. Ordinary normal-family scanning
continues, so a bad planned hint can still be repaired safely.

## Stateless online repair

The repair selector derives progress from settled state on every call:

- canonical signatures of configured initial packed items are subtracted;
- the longest consumable prefix of the plan order is rebuilt from remaining
  packed full signatures;
- duplicate equal signatures remain plan occurrences and bind to the first
  matching live pool position deterministically;
- repeated identical observations return the same original catalog root and do
  not advance hidden state.

Every catalog record is freshly passed through `apply_root(...,
exact_revalidator=ExactMask)` before it can participate in ranking. Exceptions
are isolated per record. The first successful exact root is retained as the
deadline incumbent.

For a valid current plan hint, actual completed-supporter center translation and
settled top height rebase the planned center. The immediate comparison uses:

1. planned container match;
2. actual support-class match, including completed plan supporters;
3. official orientation match;
4. squared 3-D rebased-center distance.

At most the top 12 exact roots receive a bounded suffix check. The analytical
LayeredProxy examines at most eight planned suffix occurrences with a fixed
256-fit/64-candidate/32-rectangle quota. Suffix fit occurrence count and volume
precede local hint terms. This is a fixed analytical survival proxy only; it is
not an exact or physical rollout.

Invalid digest/profile/type/binding disables all plan hints and falls back to a
deterministic freshly applicable catalog root. The selector never returns a raw
proposal, proxy candidate, offline receipt, or newly minted root.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
agents.support_extreme_fusion_beam_exact_mask.mode_a_repair
```

Focused coverage includes:

- omitted versus explicit-empty advisory equivalence;
- valid advisory freshness and catalog identity;
- reject, deduplicate, and six-hint cap;
- deliberately altered diagnose/fresh receipt mismatch rejection;
- plan-root identity and repeated-observation idempotence;
- invalid planned coordinate repaired by a normal exact root;
- stale plan fallback;
- duplicate signature cursor and initial-preload subtraction;
- actual supporter XY translation and Z rebase;
- every catalog root freshly applied;
- per-root exception isolation and deadline incumbent retention;
- suffix survival precedence over local container hint in a two-container state;
- immediate expired-deadline fail-closed behavior.

## Fresh verification

Focused:

```text
Ran 13 tests in 1.857s
OK
```

Mode-A, Catalog, B/C Agent/Beam, transition, and mask related suite:

```text
Ran 148 tests in 10.366s
OK
```

Full project discovery:

```text
PYTHONPATH=simulator/.test_deps_linux:simulator \
  ./simulator/.venv_wsl/bin/python -m unittest discover \
  -s simulator/tests -t . -p 'test_*.py'

Ran 529 tests in 30.614s
OK
```

Compilation:

```text
python -m py_compile \
  simulator/agents/support_extreme_fusion_beam_exact_mask/catalog.py \
  simulator/agents/support_extreme_fusion_beam_exact_mask/mode_a_repair.py \
  simulator/tests/test_support_extreme_fusion_mode_a_repair.py

exit 0
```

## SHA-256

```text
30A69AA8454BDD9CF673D22195E78C127B214430C98848EBD607C9A98C0AC336  catalog.py
EF247366F0C84481D7D3792AAD433A84220215CABDADF54098D92FF8154F155E  mode_a_repair.py
7D89261CC63C56D057CF84C9256FCC06ADD5EC24DC882253DD0FDFFA4BFB9C55  test_support_extreme_fusion_mode_a_repair.py
```

## Scope limits

This task does not install the repair in `Agent.policy`, does not implement
Mode-A `optimize`, and does not run physics. The suffix proxy is intentionally
small and fixed-work; Public or PyBullet quality requires the later integration
and acceptance tasks. No packages were installed and Git was not used.

The final deadline audit added post-diagnose, post-fresh-validate, and
post-suffix checkpoints. A final fresh targeted run passed 50/50 related tests
in 6.503 s, followed by the 529/529 full result recorded above.

## Review fix round 1

Supporter settling evidence is now a canonical exact four-tuple:

```text
(center: tuple[float, float, float], top: float,
 container_ordinal: int, footprint: Rect)
```

Tuple/list aliases, non-finite or non-exact scalar types, invalid ordinals, and
non-`Rect` footprints fail closed. A named actual supporter changes the planned
XY/Z target only when its actual container ordinal equals the intent container.
The new negative control proves an otherwise identical foreign-container
supporter has no effect.

Immediately after observation-derived context reconstruction, `choose` now
checks the absolute deadline. If context walking consumed the remaining time it
returns the first freshly applied exact incumbent without rebasing, hint
ranking, or fallback sorting. The regression deliberately orders the incumbent
away from the normal fallback best and verifies zero rebase calls.

Additional cooperative checks cover initial-signature subtraction, remaining
placed-item matching, supporter rebasing, static/placed support classification,
hint scoring, and fallback sort boundaries. The omitted-versus-empty advisory
golden now compares every root proposal/box/fingerprint/profile/signature/
support/clearance/strict field as well as provenance, ordering, and full stats.

Fresh round-1 verification:

```text
Focused: Ran 14 tests in 2.114s — OK
Related: Ran 149 tests in 11.090s — OK
Full:    Ran 530 tests in 31.160s — OK
py_compile: exit 0
```

Updated hashes:

```text
30A69AA8454BDD9CF673D22195E78C127B214430C98848EBD607C9A98C0AC336  catalog.py
7E7B7C49EAD330B52A1DF4F7A2BE9133504BF554B461920D26333CE75FEA44B7  mode_a_repair.py
A6AE9A715E30875078D9F0042A38F36B68770A171931B3C317354737F44022BF  test_support_extreme_fusion_mode_a_repair.py
```
