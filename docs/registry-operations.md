# Record submissions and results

A submitted ZIP plus its result authorizes intake and synchronization to the agreed private repository, `Nevaseme/baggage-loading-lab`. Use the existing Git checkout and authentication.

## Intake

Create `deliverables/YYYY-MM-DD-technique/` first and place the exact ZIP and
`result-log.txt` there. Use a new suffixed folder for another submission. Keep
the original bytes and filenames, add a short README linking the artifact and
evaluation, and update `deliverables/README.md`. A build date is not evidence of
the submission/evaluation timestamp. Build future ZIPs into these folders too.

Check repository state for concurrent changes, then run from the project root:

```powershell
python -m tools.lab --root . ingest --zip C:/path/to/technique-name.zip --name technique_name
python -m tools.lab --root . record --artifact ARTIFACT_ID --result C:/path/to/result.txt --public-score '42.123456789'
python -m tools.lab --root . render
python -m tools.lab --root . validate
```

Use the returned artifact ID. Quote exact decimal scores to preserve their precision. Omit `--public-score` when the result text contains the value. Use `--rounded-public '11'` for an approximate score; leave unavailable values absent. Preserve screenshot originals under the evaluation's `raw/` directory and note any transcribed values; the CLI does not perform OCR.

Identical ZIP bytes share an artifact ID. Repeated identical evidence is deduplicated. Supply `--submission-id` for a distinct evaluation of the same ZIP when known. Use `--supersedes EVALUATION_ID` for a correction; keep the previous record and raw evidence. Clarify only if a repeat and a new evaluation cannot be distinguished.

Use `import-source --source PATH --name technique_name` for historical source whose original ZIP is missing. This does not establish the original archive's identity.

## Notes and provenance

Write the method, parent candidate, changes, and evidence in the artifact's `algorithm.md`. Put observations, interpretation, and the next experiment in the evaluation's `analysis.md`. Use new records for corrections instead of editing structured manifests or records. Generated views are refreshed by `render`.

`source_commit` records the registry HEAD at intake, not necessarily the algorithm's source commit. Preserve feedback values at their reported granularity: `num_placed_items` is a ratio in official feedback, and an unknown denominator cannot be reconstructed as a count.

## Synchronize

1. Run registry tests and validation. Review the selected changes, then commit and push the intake files using existing authentication.
2. For an original ZIP, attach `.lab/assets/<sha256>.zip` and its manifest to the artifact's GitHub Release. Preserve its original filename in the manifest.
3. Verify the remote asset digest or downloaded bytes against the local hash.
4. Record the commit, Release URL, and verification result under `knowledge/sync/`, then push that record.

Resume partial synchronization using existing IDs and assets. GitHub's automatic
Source code ZIP is not the original submission. The exact ZIP and result also
live together under `deliverables/`, directly readable in the repository.

The user expanded sharing on 2026-09-16 to the complete project record: include
the official simulator source/configuration/tests, local experiments and logs,
old submissions, analysis, historical plans, and useful `.lab/` audit evidence.
Exclude installed environments/dependencies, caches, duplicate checkout/export
directories, nested Git databases, and credentials. Document actual coverage
in [AI handoff](ai-handoff.md) and the synchronization record. Check content as
well as filenames before uploading; never print credentials during checks.

## Offline context

```powershell
python -m tools.lab --root . export-context --output .lab/exports/design-context.zip
```

Give the receiving agent this ZIP and [START_HERE.md](../START_HERE.md). `REGISTRY.json` identifies the revision; `FILE_HASHES.json` identifies the bundled bytes. Use direct repository access when available. Physics verification requires the official simulator environment separately.
