# SDD ledger — plan: docs/superpowers/plans/2026-09-08-github-submission-feedback-loop.md

2026-09-08: User approved overall direction and confirmed Web ZIP generation. Private repository created at https://github.com/Nevaseme/baggage-loading-lab (UI shows Private). Existing Git credential workflow can read empty repository after network sandbox escalation. GitHub connector metadata lookup returns 404; access through that connector remains unconfirmed.

Ruling: initialize the existing user-authorized project in place with explicit tracked-file allowlist, instead of making a new worktree before any Git baseline exists — preserves the user's existing simulator/runtime and approved repository layout; unrelated historical files stay untracked.

Ruling: use one Luna max implementer for the self-contained registry while root handles GitHub and documentation — avoids shared-file writes and model API cost; requires interface review before migration.

| Boundary | Check |
| --- | --- |
| Task 1 registry → Task 2 migration | Root consumes CLI IDs and schema, preserves raw original evidence; no float roundtrip. |
| Task 1 render → root progress | Root archives old progress before first real render; tests use temporary roots. |
| Task 1 cache → Task 3 assets | `.lab/assets/` is local-only; releases receive only inspected, hash-identified ZIPs. |
| Task 1 | CLI and tests use stdlib, no artifact execution or network. |
| Task 2 | Actual migration and fake acceptance roots are separate. |
| Task 3 | Existing Git credentials only; connector permissions remain a user action if needed. |

Task 1: pending.
Task 2: pending.
Task 3: repository created; content and assets pending.

## Paused at permission boundary

Eight artifact/evaluation directories were created by the registry's temporary staging under the sandbox identity. Normal-user `git add` reported Permission denied for all eight; no ACL/ownership changes were attempted. Other selected files are staged, not committed/pushed. Full publication requires user authorization to repair access for these task-created directories and a regression fix for newly created registry directories.

Root imported four artifacts and four raw evaluations. Their IDs and retry verification are in this plan's `verify-migration.py`; raw Public values and missing-original facts are intact. First real validate fails for three source-only manifest identities. Code inspection indicates import-source identity includes file size whereas generic validation digest does not. The implementer was asked to preserve existing IDs and correct validation; completion is not established.

Owned agents `submission_registry_impl` and `submission_registry_review` were interrupted at the permission boundary. Task reviewer had the working snapshot `task-1-review.diff`; no review verdict received. Resume these agents rather than spawning duplicates. Worker report currently claims 27 unit tests passed before the real migration issue, not acceptance of the full system.

Release draft exists at `https://github.com/Nevaseme/baggage-loading-lab/releases/edit/untagged-b053da0c21a7c1f07ee8`, with `highscore_guarded_20260813.zip` attached. Manifest attachment was reported empty by UI (local file is 1495 bytes), consistent with but not proof of the same access problem. Save-draft was clicked; final save/publish and remote digest still need confirmation. Release is not marked synchronized. No access permission was expanded.

Remaining: authorize/repair task-created directory access; finish source identity regression and portable context dependency fixes; independent review; real migration replay/validation and clean-clone tests; curated commit/push; publish and verify original ZIP; generate design-context bundle and final receipt. Algorithm development remains paused.

Final paused-state reconciliation: implementer report had advanced to 32 tests passed before interruption. Root reran real `validate`: valid=true, revision unchanged. Report says context dependency fixes landed and source identity compatibility was added; independent review is still required, especially the reported ID-suffix compatibility fallback (do not accept weakened content-identity checking merely to make migration pass). Exact ACL readback confirms owner `CodexSandboxOffline`, inheritance disabled, only OWNER RIGHTS/SYSTEM/Administrators have access. User authorization is required before changing those task-created directory ACLs. Release editor moved after Save draft to `https://github.com/Nevaseme/baggage-loading-lab/releases/edit/untagged-d71d05a553cdcfdbd4f5`; tab marked for handoff, publication remains unconfirmed/not done.

## Resumed with user permission

User explicitly authorized TAKUMI access repair for the eight created registry directories and continuation. Targeted DACL grant (TAKUMI Modify with inheritance) succeeded for exactly those eight; ownership and parent ACLs unchanged. Normal-user Git reads all original artifact/evaluation payloads. New record generation after the staging-mkdir fix also reads through normal-user Git without another ACL change.

Guarded Release published and both GitHub displayed digests match local ZIP/manifest. Receipt: `knowledge/sync/2026-09-08-guarded-release.json`. Private connector fetch of AGENTS.md still returns404; portable handoff remains the supported fallback, no connector access expansion attempted.

Task1 Sol-high independent review found six issue groups (identity recomputation, protected export targets, result symlink resolution, secret-name filter scope, correction closure, schema validation). Sent to original Luna-max implementer as one fix batch, together with exact source-ID/staging fixes. Review/freeze pending.

Root migration acceptance caught PowerShell numeric argument rounding of 12.622949582873819 to 12.6229495828738. Erroneous prepublication generated record a360... is preserved in `.lab/migration-errors/`, not uploaded. Correct record is evaluation-786e70e5a08bbed8ff042c618439d19d94833d8994ac9df94d06be6c5c8c6825; raw inputs unchanged. Docs now quote exact decimal strings. A newly generated duplicate source record f0a15... from a changing implementation recipe was likewise quarantined (recoverable). Root independently proved all three original source IDs equal SHA256(concat(sorted(path + NUL + hash_ascii))) with no file size or trailing NUL; implementer notified to preserve that exact canonical recipe. Further replay mutations run only inside isolated temporary copies.

Git bootstrap: main commit `930f3d58f929394e599eab8ccc587c6582a897bd` pushed and verified against remote. Git user identity was unset; repository-local author uses account name Nevaseme and GitHub ID-based noreply address, not a private email. Ownership differs between sandbox and user; approved Git calls use a command-scoped safe.directory for this exact workspace, with no global trust change.

Archive inventory: guarded ZIP SHA256 `3789b037da39bd2f38215d711c42ad9cf504503f44b94016517a675044cb4a54` matches all 10 saved source members. `submit/algorithm.zip` is a four-family backup, not a submission; baseline ZIP has no authoritative result association. Other three original submission ZIPs remain missing.

Ruling: initial GitHub upload includes project-owned code/evidence and a rewritten Agent contract, not the official simulator distribution — avoids assuming redistribution scope; Web designers can generate ZIPs but physical verification still uses the user's local official environment.

## Integration verification 2026-09-09

Task review corrections completed by Luna then Sol (one writer at a time). Sol's bounded repair requires exactly one raw-result reference, rejects unknown kinds, parses original bytes independent of mutable filename metadata, and supports legacy association fields without rewriting existing records. Root independently ran all49 tests (44.137s), actual validate, and isolated real4+4 replay successfully. Registry revision remains d34182ab85c93c1383d7372e3b86036b23c5cf258f23aa87a6da3a49e1b6baff. Curated baseline and fix commits a63f516 and b66815d are local only pending final review.

One independent final Astra-medium reviewer was selected for cross-file architecture/evidence review; Sol had authored the last fix and therefore could not independently approve it. The review found two concrete integration cases: same evidence renamed on retry incorrectly conflicts, and scalar JSON string scores are accepted by intake but rejected by redundant feedback validation. Sol is reassigned as sole writer for these two RED/GREEN cases; Luna remains frozen. These do not alter historical records or invalidate the original ZIP/Release digest comparison. Remote CI and Web interactive access remain distinct pending checks.

## Delivered

Both integration cases fixed with regression tests; independent Astra scoped review ready. Final Sol run51tests passed61.550s. Root independently observed the first full51 run's outdated error-message expectation failure, then verified its focused correction and real4+4migration/validate. First remoteCI exposed a hardcoded Windows Python test path; root's one-line sys.executable correction was independently reviewed. RemoteCI run34243899480 passed on code commit3894cfa77dbfd77c8ffec774e659a5e873c8cd28 (22s total). A real remote clone was updated to that SHA and its own validate + isolated ingest test passed without simulator/cache in the clone.

Final published main and remote readback: 3dc73b11bd186837fa3da4085a6dfc591193d4cc (adds knowledge/sync/2026-09-09-github-acceptance.json only). Generated .lab/exports/design-context-2026-09-09-3dc73b1.zip,54files; all hash closure/current guidance links passed. ZIP SHA256063c5bed5f724513bb5685dafdbd1bff438713e4988fc98f43888acf1d24e94d. It is a design-context bundle, not a submission ZIP. Tracked worktree/index clean; unrelated historical untracked docs preserved. All three owned workers report completed, no running child. Algorithm development remains paused. Web direct connector and user's actual bundle-open remain unverified; portable bundle is the delivery fallback.
