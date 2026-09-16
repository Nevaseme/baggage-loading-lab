# Baggage Loading Lab

Build and compare baggage-packing algorithms toward a verified Public score of at least 60. This private repository preserves source, submissions, results, and the evidence needed for the next experiment.

Use [START_HERE.md](START_HERE.md) to find the relevant code or workflow. [progress.md](progress.md) is the generated results table; [development.md](docs/development.md) describes the local research environment.

## Feedback loop

1. Develop and compare a candidate against a matched control.
2. Verify the exact ZIP using the [evaluation contract](docs/evaluation-contract.md).
3. Submit to SIGNATE, then give Codex the actual ZIP and available result text/Public score.
4. Codex records the evidence and synchronizes it to `Nevaseme/baggage-loading-lab` using the [registry workflow](docs/registry-operations.md).

## Layout

| Path | Purpose |
| --- | --- |
| `artifacts/`, `evaluations/` | Registered source, hashes, original feedback, and method notes |
| `experiments/`, `knowledge/lessons/` | Comparisons, checkpoints, and useful findings |
| `tools/lab/`, `tests/` | Registry tooling and its tests |
| `contracts/`, `docs/` | Interface, evaluation, and operating references |
| `deliverables/` | One folder per submitted ZIP/result pair |
| `simulator/` | Official source/configurations, development agents, tests, and run evidence |
| `submit/`, `.superpowers/`, `official_mhtml/`, `analysis/` | Historical submissions, plans, official reference captures, and analysis |
| `.lab/` | Useful audit/migration evidence; duplicate checkouts/exports and caches excluded |

## Registry checks

Python 3.12 and the standard library are sufficient for registry operations:

```powershell
python -m unittest discover -s tests -p 'test_lab*.py' -v
python -m tools.lab --root . validate
python -m tools.lab --help
```

On this PC, use `simulator/.signate_venv/Scripts/python.exe` if Python is not on PATH. Physics runs need the locally supplied simulator and its dependencies.

## Saved archives

- [Support recovery candidate, 2026-09-16](experiments/submission_candidate/README.md): new local submission ZIP, validation, and hashes; Public score pending.
- [Guarded original submission](https://github.com/Nevaseme/baggage-loading-lab/releases/tag/artifact-3789b037da39bd2f38215d711c42ad9cf504503f44b94016517a675044cb4a54): `highscore_guarded_20260813.zip`.
- [Four reconstructed source/result bundles](https://github.com/Nevaseme/baggage-loading-lab/releases/tag/reconstructed-source-results-2026-09-09): choose `*-source-result-reconstructed.zip`. These preserve code and result logs but are not original submission ZIPs.
- [Bundle identities and verification record](knowledge/sync/2026-09-09-reconstructed-bundles.json).

The other three original submission ZIPs remain unavailable. Scores stay attached to their recorded evaluations, not to reconstructed archives.

For another AI reading this private repository, use [the AI handoff](docs/ai-handoff.md).
It separates the latest submitted result, local experimental evidence, rejected
approaches, and next decisions. Installed runtimes and authentication are not
part of the shared project; source and recorded results are.
