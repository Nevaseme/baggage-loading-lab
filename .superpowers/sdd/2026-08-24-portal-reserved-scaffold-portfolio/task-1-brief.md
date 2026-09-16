# Task 1 brief — Normalize external feedback and experiment evidence

Read `C:\Users\TAKUMI\projects\Baggage-Loading\AGENTS.md` first and obey it.

## Goal

Normalize all four externally returned `submit/**/result-log.txt` records,
define the two-grain local experiment schema, and reconcile `progress.md`
without inferring any unavailable value.

## Files

- Create `analysis/submission_result_matrix.json`.
- Create `analysis/episode_evidence_schema.json`.
- Create `simulator/tests/test_submission_result_matrix.py`.
- Modify `progress.md` only where needed to reconcile the submission ledger,
  stale Mode-A/historical-control statements, and evidence-grain caveats.

Do not modify any file under `submit/`.

## Required TDD sequence

1. Write tests first.
2. Run
   `simulator\.signate_venv\Scripts\python.exe -m unittest simulator.tests.test_submission_result_matrix -v`.
3. Record the expected RED result caused by missing matrix/schema files.
4. Create the minimum JSON/documentation changes.
5. Rerun the focused test and record the GREEN output.

## Matrix contract

The JSON root is an object with:

- `schema_version`: integer `1`;
- `source_grain`: string explaining that fields are externally returned
  feedback averages/maxima over an unspecified evaluation scene set;
- `records`: exactly four objects, one per real `result-log.txt`.

Every record contains:

- `algorithm` (descriptive working/historical label);
- `artifact_path` (workspace-relative directory);
- `result_log_path` (workspace-relative file);
- `public_score` (exact known float for Conservative and Guarded, `null` for
  Ingress, and `null` for Surface because only the rounded observation 11 is
  known);
- `public_score_note` (exact/rounded/pending provenance);
- `status` copied exactly;
- numeric `fill_score`, `cog_score`, `stability_score`, `placement_score`,
  `soft_item_score`, `num_placed_items`, `optimization_max_seconds`, and
  `policy_max_seconds` copied exactly;
- `metrics_provenance`: `external_result_log`;
- `status_interpretation`: explicitly state that `is_valid=false` occurs
  before placement, so `is_placed_safe=false` does not prove settling ran.

The test must load every source result log and compare each copied value to
the source.  It must fail if paths are duplicated, a source is omitted, a
numeric value is changed, an unknown Public score is filled, or a status is
not exact.  Expectations must be literal or source-boundary comparisons, not
computed by production logic.

## Evidence schema contract

The JSON root contains `schema_version: 1`, `episode_fact`, and
`paired_experiment_aggregate`.  Each section lists required fields and their
types/nullability.  Episode fields include experiment/baseline IDs,
artifact/config/runner hashes, lifecycle, environment/hardware/timestamp,
task/mode/lookahead/seed, requested/effective items, attempted steps, policy
calls, safe placements, explicit completion numerator/denominator, fill plus
evaluator version, terminal outcome/reason/first failed predicate, malformed/
unchecked/invalid/unsafe counts, optimize time/limit, policy sample count and
p50/p95/p99/max/limit, action hash, and raw evidence path.  Paired fields
include matched manifest/hash, pair/seed counts, median safe delta, mean fill
delta, worst safety regression, candidate-zero delta, timing sample count,
p99/max, and gate result.

## `progress.md` changes

- Add `Ingress-Preserving Column Scaffold` to the Public-submission ledger with
  Public score pending and all external result-log metrics/status.
- Populate the external result-log metrics/status for the other three rows;
  keep exact Public scores separate and leave Surface exact Public score
  pending with its rounded observation in a note.
- State that all four external feedback records stopped mid-episode on
  `is_valid`/`is_placed_safe`, with transport-first caveat.
- Correct the stale `Mode A pending` and `historical control not run` text.
- Preserve all detailed historical experimental evidence; do not rewrite or
  delete unrelated project history.
- Explain that Public score, external component feedback, and local single-case
  physics have different grains.

## Report

Write the implementation report to
`.superpowers/sdd/2026-08-24-portal-reserved-scaffold-portfolio/task-1-report.md`.
Include changed files, RED command/output summary, GREEN command/output summary,
self-review, SHA-256 for the two JSON outputs, and any concern.  Do not spawn
subagents.  Return only status, one-line test summary, and concerns.

