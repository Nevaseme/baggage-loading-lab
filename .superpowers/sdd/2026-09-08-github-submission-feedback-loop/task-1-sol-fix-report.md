# Task 1 Sol fix report — raw binding and replay compatibility

Date: 2026-09-09

## Outcome

Implemented the scoped fix in `tools/lab/registry.py` and
`tests/test_lab_registry.py`. No migration data, artifact/evaluation records,
or source payloads were changed.

## Root cause and decisions

- Validation reparsed raw evidence only when an evidence reference happened to
  retain `kind: raw_result`. Unknown kinds could therefore suppress the raw
  binding check. Validation now rejects every unknown evidence kind and
  requires exactly one verified raw-result reference before reparsing.
- Parser selection used mutable `association_basis.source_path_name`. Parsing
  now depends only on the preserved raw bytes, so changing source-name metadata
  cannot reinterpret scalar JSON as a plain note.
- Real migration replay generated the same evaluation ID and evidence but added
  three provenance keys to `association_basis`:
  `rounded_public_override`, `submission_id_override`, and
  `supersedes_override`. The existing immutable record lacked those keys, so a
  strict whole-record comparison raised a conflict. Deduplication now performs
  a narrow compatibility comparison that fills only those missing legacy keys
  in memory. It never rewrites the existing record, and every other record and
  raw byte must still match.

## TDD evidence

The following focused tests were added and each was observed failing before the
production change, then passing afterward:

- `test_same_evidence_deduplicates_against_legacy_association_metadata`
- `test_validate_requires_one_known_raw_result_reference`
- `test_validate_binds_parser_selection_to_recorded_source_name`

Full command:

```text
simulator/.signate_venv/Scripts/python.exe -m unittest discover -s tests -p "test_lab*.py" -v
```

Result: 49 tests passed in 42.904 seconds; exit code 0.

## Real migration replay

Command:

```text
simulator/.signate_venv/Scripts/python.exe .superpowers/sdd/2026-09-08-github-submission-feedback-loop/verify-migration.py
```

Result: exit code 0. The isolated replay retained 4 artifact IDs and 4
evaluation IDs, deduplicated all retries, preserved the exact Public-score
strings and raw-result hashes, matched all 10 members of the available original
ZIP byte-for-byte, and finished with registry revision
`d34182ab85c93c1383d7372e3b86036b23c5cf258f23aa87a6da3a49e1b6baff`.

## Freeze

Writer scope is frozen after this report. Files for independent review:

- `tools/lab/registry.py`
- `tests/test_lab_registry.py`
- this report
