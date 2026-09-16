# Task 1 implementation report — normalized external feedback and evidence schema

## Changed files

- `analysis/submission_result_matrix.json`
  - Normalizes exactly the four workspace `submit/**/result-log.txt` records.
  - Copies every source component metric, optimization/policy time, and status exactly.
  - Keeps the two verified Public scores exact, Ingress pending, and Surface as a rounded observation with its exact value pending.
  - Records the transport-first interpretation without inferring a placement count, denominator, failure step, or settling result.
- `analysis/episode_evidence_schema.json`
  - Defines schema version 1 for single-episode facts and matched paired aggregates.
  - Lists every required field with its JSON-level type and nullability.
- `simulator/tests/test_submission_result_matrix.py`
  - Adds source-boundary tests for source coverage, unique paths, literal copied values, exact statuses, Public-score nullability, provenance, and all schema fields.
- `progress.md`
  - Adds the Ingress-Preserving Column Scaffold ledger row.
  - Reconciles all four external result-log rows with component metrics, optimization/policy maxima, exact statuses, and Public-score provenance.
  - Adds the transport-first and evidence-grain caveat.
  - Corrects stale Mode-A and historical-control state statements without deleting detailed historical evidence.

No file under `submit/` was modified.

## TDD evidence

### RED

Command:

```text
simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_submission_result_matrix -v
```

Result: exit code 1. All 3 tests failed with the expected `FileNotFoundError` because `analysis/submission_result_matrix.json` and `analysis/episode_evidence_schema.json` did not exist yet.

### GREEN

Command:

```text
simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_submission_result_matrix -v
```

Result: exit code 0; `Ran 3 tests in 0.004s`, `OK`.

Independent JSON parsing also completed successfully (`JSON parse OK`).

## Self-review

- The test resolves and loads every source result log, requires exactly four records, rejects duplicate or omitted source paths, and compares all copied values at the source boundary rather than through production logic.
- Numeric feedback and timing values in the matrix match the four one-line source logs byte-for-value after JSON parsing; status strings preserve each source's exact set ordering.
- Unknown Public values remain `null`; the Surface rounded observation is retained only in its provenance note.
- The schema has separate episode and paired grains and explicitly models unavailable evaluator/delta values as nullable.
- The ledger keeps Public aggregates, external scene-set feedback, and local single-case physics evidence distinct.

## SHA-256

```text
analysis/submission_result_matrix.json  B0AA6029728270C0B8CA9443E63D9605BACCC61D29CC799716C3406C91FA99A5
analysis/episode_evidence_schema.json   6DDFF2D95559EDB3A64262D5371EE778050F4756FF5277B51BA06EB299943C54
```

## Concerns

The external result logs expose aggregate feedback over an unspecified evaluation scene set and do not establish per-episode placement or settling behavior. Ingress has no supplied Public score, and Surface has only the rounded observation `11`; both remain pending rather than inferred.

## Fix round 1

### Findings addressed

- The Surface row now keeps its Public score cell exactly `pending`; rounded observation `11` appears only in the provenance/note cell.
- The stale statement that the Mode-A planner is still missing now reads: `Mode-A baseline and experiments are recorded below.` The detailed runs at the following entries remain unchanged.
- Episode policy p50/p95/p99/max and paired policy p99/max are nullable when their sample count is zero. Both schema sections now state that zero samples require `null` and prohibit fabricated zero timing values.
- The Public-evaluation evidence limit now distinguishes browser-only aggregate Public scores from component/status values returned in external result logs, and states that they are different grains rather than Public component scores.

### Fix-round TDD evidence

RED command:

```text
simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_submission_result_matrix -v
```

Result: exit code 1; the six-test regression suite reported 3 failures and 1 error for the uncorrected Surface row, stale Mode-A text, missing conditional schema semantics, and non-null timing descriptors.

GREEN command:

```text
simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_submission_result_matrix -v
```

Result: exit code 0; `Ran 6 tests in 0.006s`, `OK`.

Additional verification: both JSON files parsed successfully (`JSON parse OK`), and the focused source-boundary tests continued to pass for all four external logs. No file under `submit/` was modified; the workspace still contains 20 files under `submit/`.

### Fix-round SHA-256

```text
analysis/submission_result_matrix.json  B0AA6029728270C0B8CA9443E63D9605BACCC61D29CC799716C3406C91FA99A5
analysis/episode_evidence_schema.json   C07AFAF0CA80C1AAFF917507F5817445BD12D0E8F47276D2DC34884B4DC5559C
```

Fix-round concern: Public component scores remain unavailable; external result-log component/status values are retained as a separate scene-set evidence grain and are not promoted to Public-evaluation facts.
