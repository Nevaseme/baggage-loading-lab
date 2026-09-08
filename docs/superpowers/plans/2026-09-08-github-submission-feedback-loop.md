# GitHub Submission Feedback Loop Implementation Plan

Approved direction: private `Nevaseme/baggage-loading-lab`; Web ChatGPT can generate ZIPs. Execute using the current working agreement, bounded subagents, and review checkpoints.

Goal: migrate four historical submission families and provide tested ZIP/result ingestion plus a portable AI handoff, then publish and read back the repository and artifact assets.

Spec: `docs/superpowers/specs/2026-09-08-github-submission-feedback-loop-design.md`.
Stack: Python 3.12 standard library, unittest, existing Git authentication, GitHub Releases. No model API or global packages needed.

## Scope and interfaces

- Existing `submit/`, simulator code, and original results remain unchanged.
- `artifacts/` and `evaluations/` are structured records; raw inputs are preserved. ZIP SHA-256 is artifact identity; unavailable originals remain missing.
- Exact Public scores are strings; rounded/unknown values stay separate. Evaluation success and artifact readiness are different facts.
- Incoming ZIP code is never executed by ingestion or registry CI. Reject traversal, absolute/drive/UNC paths, symlinks, duplicate normalized paths, and excessive size before writing extracted files.
- Use isolated temporary directories for tests; fake data never enters the real registry.
- Root owns GitHub, documentation, migration execution and integration. The implementer owns `tools/lab/` and `tests/test_lab*.py`. Reviewers are read-only.

## Task 1 — local artifact/evaluation registry and CLI

Files: `tools/__init__.py`, `tools/lab/{__init__,__main__,archive,registry,views}.py`, `tests/test_lab*.py`.

Commands use `python -m tools.lab --root PATH` followed by:
- `ingest --zip PATH --name NAME`: inspect/cache original in ignored `.lab/assets/`, create `artifacts/<id>/manifest.json` and exact `source/` tree. Repeated identical input returns the same ID; different ZIP bytes give different IDs.
- `import-source --source PATH --name NAME`: archive missing, source manifest identity clearly distinguished from ZIP identity.
- `record --artifact ID --result PATH [--public-score DECIMAL] [--rounded-public TEXT] [--submission-id TEXT]`: preserve input bytes and normalize fields from JSON feedback or a plain score note; explicit score overrides only with its own recorded evidence. Missing values stay null; ambiguous values fail clearly. Stable evidence identity deduplicates retries; explicit different submission IDs allow reevaluation. Support superseding an earlier evaluation without deleting it.
- `render`: regenerate `progress.md` and `knowledge/CURRENT.md` from records, including a deterministic registry revision and links. Preserve the original root progress under `knowledge/history/` before first replacement (root owns that copy).
- `validate`: check record schemas, reference closure, artifact file hashes, raw-result hashes, score type/range/precision, and generated-view freshness; return nonzero for a discrepancy.
- `export-context --output PATH`: deterministic ZIP with START_HERE, current guidance, registry, source files and relevant knowledge; exclude credentials, `.git`, `.lab`, caches. Include source commit when available plus file-hash manifest. Offline tool tests need no Git/network.

The CLI returns compact JSON including IDs and paths and nonzero exit on invalid input. Writes use temporary staging/atomic replacement; existing immutable record conflicts fail clearly. Recovery retains verified input cache and can regenerate views without overwriting evidence. A bounded exclusive local mutation lock prevents two writers interleaving.

TDD acceptance: tests exercise real temporary ZIPs and files. First assert normal import/roundtrip fails because the CLI is absent; then implement. Add focused RED/GREEN cases for same-name/different-content, exact duplicate, reevaluation, score-only input, missing/rounded score, unknown fields/raw fidelity, correction links, unsafe archives, corrupted source/raw metadata, stale views, context content/hashes, and interrupted/retried operations. Run `python -m unittest discover -s tests -p 'test_lab*.py' -v`.

## Task 2 — migration, human/AI entrypoints and CI

Root files: `.gitignore`, `.gitattributes`, `README.md`, `START_HERE.md`, `contracts/agent-interface.md`, `knowledge/lessons/*.md`, `.github/workflows/registry.yml`, migration receipt and usage instructions.

Read each existing result with decimal-preserving JSON. Compare available ZIP payload file hashes with the recorded source tree; preserve unknown archive association. Import four historical families and their raw results, then record exact user-provided scores or rounded score with provenance. Save original progress and relevant evidence snapshots. Render and validate, replay migration to establish idempotency. Include step 14/control-trace comparison, 4/25 strict-mask recall, accepted shield cross and unfinished Task 4 in evidence-led lessons.

CI runs only stdlib unit tests and registry validation, with read-only repository permissions. It does not execute artifact source or call any model. Docs define Web-produced delivery (ZIP + method/change note + test evidence) and Codex intake; local physics checks retain the existing separate environment.

## Task 3 — private publication, asset identity and handoff

Initialize Git in the existing user-authorized workspace, with an explicit allowlist of tracked paths. Preserve untracked historical files. Commit only selected project-owned records/docs/tools, push through existing Git credentials, and compare remote commit.

Publish verified archive originals to artifact-specific Releases using available authorized GitHub UI; set draft first where supported, attach exact bytes, then finalize. Record immutable asset URLs/hashes in a separate sync receipt so the artifact identity is not rewritten. Read back assets or their authoritative digest before marking synced. Missing-original records have no claimed ZIP Release.

Check the connector can read the new repository; if its repository permissions need user action, report that separately and provide the portable context bundle rather than changing permissions silently. Test one fake roundtrip in an isolated temporary root; real registry validation must still show only real records.

## Review and completion

Give an independent reviewer the new-file diff, Task 1 report, actual migration receipt, and validation evidence. Address correctness/security issues with focused regression tests, then review the fix. Report repository URL, imported families, exact/missing ZIPs, local tests/CI status, handoff files, and any unverified remote access. Algorithm development stays paused.
