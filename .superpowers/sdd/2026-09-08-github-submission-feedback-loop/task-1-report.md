# Task 1 report — local artifact/evaluation registry

Date: 2026-09-08

## Outcome

Implemented the offline local registry and CLI in the Task 1 ownership scope:

- `python -m tools.lab --root PATH ingest --zip PATH --name NAME`
- `python -m tools.lab --root PATH import-source --source PATH --name NAME`
- `python -m tools.lab --root PATH record --artifact ID --result PATH [--public-score DECIMAL] [--rounded-public TEXT] [--submission-id TEXT] [--supersedes EVALUATION_ID]`
- `python -m tools.lab --root PATH render`
- `python -m tools.lab --root PATH validate`
- `python -m tools.lab --root PATH export-context --output PATH`

Successful commands emit one compact JSON object on stdout. Expected input errors emit a compact JSON error and a nonzero exit status. No candidate source is imported, executed, or compiled by these operations.

## Identity and persistence decisions

- ZIP artifacts use `artifact-<64 lowercase hex ZIP SHA-256>` as their stable ID. The exact ZIP bytes are cached at `.lab/assets/<sha256>.zip` and safe members are staged into `artifacts/<id>/source/`.
- Source-only imports use `source-<64 lowercase hex source-manifest SHA-256>`, set `zip_sha256` to null and `archive_availability` to `missing`, and retain the source-file hash manifest. `__pycache__` directories and `.pyc` files are omitted for this import path.
- `source_file_hashes` is a deterministic POSIX-relative-path to SHA-256 map. Source-only identities hash sorted `path + NUL + file SHA-256` entries with no trailing separator; file sizes are used for extraction limits only. ZIP manifests use the explicit, separate `path + NUL + file SHA-256 + trailing NUL` form. Arbitrary source ID suffixes are never accepted: a source ID must equal its recomputed source-manifest identity.
- Evaluation IDs are `evaluation-<64 lowercase hex SHA-256>` over artifact identity, raw-result hash, explicit score/rounded overrides, submission ID, and supersession link. Same evidence retries deduplicate; a distinct submission ID or explicit evidence context produces a separate evaluation.
- Raw result bytes are copied unchanged under `evaluations/<id>/raw/result.json` for parsed JSON or `result.txt` for notes. JSON numeric tokens are parsed as strings, retaining decimal spelling; the original bytes remain authoritative.
- Exact public scores remain validated decimal strings in `public_score`. Rounded/approximate input is stored only in `rounded_public`. A CLI score override is recorded in `association_basis.score_override` together with the raw-result hash and artifact identity.
- Status raw text is retained. Only known explicit statuses are normalized to `completed` or `stopped`; all other values and missing status normalize to `unknown`.
- JSON feedback can be supplied in a `.txt` result log (the historical result-log shape); score-only text and approximate notes are supported. Conflicting score fields, duplicate JSON keys, malformed JSON-looking input, invalid score ranges, and unsafe IDs fail before record creation.
- `--supersedes` and equivalent JSON correction fields create a new immutable record with `supersedes_evaluation_id`; the earlier evaluation and raw evidence are never deleted.

## Safety and recovery

ZIP inspection rejects absolute/drive/UNC/backslash paths, traversal, empty components, normalized and case-insensitive collisions, file/directory collisions, symlinks, excessive member count/size, and malformed archives before extraction. Source trees reject symlinks and unsafe paths. Filesystem writes use a bounded exclusive lock, temporary staging, fsync, and atomic replacement. A failed mutation can leave only verified cache/staging data; it never reports a completed artifact/evaluation directory without its manifest/record and raw evidence.

`validate` checks schema-required fields, IDs and parent links, artifact/source closure and hashes, ZIP cache hashes when the cache is present, source-manifest identity and artifact↔ZIP/source ID correspondence, raw-result hashes, evaluation identity recomputation, and reparses the preserved raw result bytes before comparing `raw_feedback`, score/rounded values, status, metrics, timing, kind, and other derived fields. Explicit CLI overrides remain separately evidenced in `association_basis`. It also checks raw-feedback score consistency, score shape/range/precision, status/kind/field types, correction links/cycles, and exact freshness of `progress.md` and `knowledge/CURRENT.md`. `.lab/views.json` is optional; when present it is checked for exact freshness. Missing local ZIP caches and other ignored `.lab` metadata are tolerated for a clean clone; re-ingesting the supplied ZIP safely restores a missing cache while rejecting a corrupt one.

`render` derives deterministic views and a registry revision from structured manifests/records. Before the first replacement, an existing root `progress.md` is preserved as `knowledge/history/progress-original.md`. `export-context` creates a deterministic ZIP with `START_HERE.md`, the explicit handoff files (`README.md`, `AGENTS.md`, `progress.md`, `docs/evaluation-contract.md`, `docs/registry-operations.md`, `docs/README.md`, and `docs/2026-09-08-instruction-audit.md` when present), registry records, source/evidence files, selected `experiments/` evidence, `REGISTRY.json`, and `FILE_HASHES.json`. It excludes `.git`, `.lab`, credentials, environment files, private-key extensions, bytecode, caches, and files reached through symlinked ancestors. Output may be a new external file or an overwrite beneath `.lab/exports`; protected registry paths and existing generic files are refused.

## TDD evidence

The first roundtrip test was run before implementation and failed because `tools.lab.__main__` was absent. After the minimal CLI/import implementation it passed. Focused RED/GREEN cases then covered:

- exact roundtrip source bytes and manifest;
- same-name/different-content and exact duplicate identity;
- source-only import and source-only evaluation recording;
- historical JSON result logs, decimal precision, unknown status, raw/unknown-field fidelity;
- score-only and rounded/approximate input, explicit override evidence, ambiguous and duplicate fields;
- same-evidence retry deduplication, distinct submission reevaluation, and supersession;
- traversal, absolute/drive-like, symlink, case-collision, malformed, and corrupt archives;
- incomplete mutation retry and invalid-score no-write behavior;
- source/raw/metadata/schema/parent-link corruption and stale/tampered generated views;
- deterministic context ZIP content, explicit guidance/experiment inclusion, symlinked-ancestor safety, hashes, and credential/cache exclusion.
- clean-clone ZIP-cache repair and corrupt-cache rejection;
- evaluation-ID/tampered-score validation, artifact↔ZIP identity, schema/type/status checks, and supersession target/cycle/cross-artifact checks;
- result symlink rejection, protected export-output preservation, known secret-name denylisting, source-ID recipe regression, and ACL-inheriting staging directory creation.
- raw-byte reparsing regression for simultaneous `public_score`/`raw_feedback` tampering and derived metrics/timing/status/kind fields; the denylist fixture is placed under scanned `experiments/` evidence so each credential-name filter is exercised.

Verification command:

```text
simulator/.signate_venv/Scripts/python.exe -m unittest discover -s tests -p "test_lab*.py" -v
```

Result: 46 tests passed after the scoped review fix. Python 3.12 bytecode compilation of all owned Python files also passed. The real four-artifact/four-evaluation registry also revalidated successfully with no errors.

## Remaining concerns / boundaries

- This task does not perform historical migration, Git/GitHub publication, release uploads, or Public evaluation; those remain root-owned Task 2/3 work.
- The registry uses conservative fixed extraction limits (10,000 members, 128 MiB per member, 512 MiB total/archive). Larger legitimate submissions require an explicit policy change.
- Archive/source identities are content-based and deterministic, but the first imported algorithm name/original filename is retained on duplicate re-ingest; metadata is intentionally immutable. Known credential filenames are denylisted during context export as a best-effort boundary; arbitrary embedded secrets still require human intake review.
- `progress.md` and `knowledge/CURRENT.md` must be regenerated after every mutation before `validate` can pass. `export-context` is offline and does not call GitHub or a model API.
