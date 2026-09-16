# AI handoff: current state and full project record

Updated 2026-09-16. Read this file before proposing the next packing experiment.
Communicate with the user in Japanese; write project documents in English.

## Current result

Goal: physically reliable packing and a verified Public score of at least 60.
That target has not been achieved. The best recorded exact Public aggregate is
29.74350010538 for historical conservative extreme-point packing.

The latest submitted algorithm is **support recovery packing**. Its
[submission folder](../deliverables/2026-09-16-support-recovery-packing/README.md)
contains the exact ZIP and original `result-log.txt`. The submitted feedback
reports a placed-item ratio of 0.46453610097631837 and early termination. Its
Public aggregate score and per-mode breakdown are absent. Do not call its fill
component 33.96645688180599 a Public aggregate or infer a hidden item count.
See [the registered interpretation](../evaluations/evaluation-071bf83d0161662641bdd0f5576019a9b76dc187119831b04d7b3117493ee571/analysis.md).

## What was tried

1. Historical conservative extreme-point packing achieved the best known Public
   score. Guarded and other reconstructed lineages also stopped; original records
   and exact/rounded/missing score distinctions are in [progress](../progress.md).
2. Fair candidate allocation and native validation exposed false rejection and
   transport failures. A conservative settling preview helps, but reconstructing
   bodies at rest does not reproduce continuing motion/contact history.
3. Footprint-aligned support roots and progressive recovery improved C task001
   locally from 18 to 23 safe placements, with fill 17.8524 to 25.1853. The C
   shuffled holdout tied at 16; two containers completed all 42 for both controls.
4. Offline/rear-first ordering regressed. Future-ingress ranking either tied the
   progressive B trajectory or regressed after spatial diversification. Relaxed
   support added some items but lost fill. Motion-history estimates corrected one
   unsafe drop but authorized another that moved 0.360 m despite predicting 0.258 m.
   Those variants were excluded from the submitted ZIP.
5. The selected package preserves historical A/B proposals while accepted, then
   searches progressive support recoveries. Policy budgets are 5.2 s for A/C and
   7.2 s for B. On exhausted search it deliberately triggers an inclusion rejection
   before cargo creation: the API has no stop action, and raising an exception
   discards evaluation and can skip later tasks. This is partial termination,
   never successful all-items packing.
6. The exact extracted ZIP ran both official samples and six additional local
   conditions, without format errors, timeout, or unsafe physical placement.
   Seven ended by explicit terminal rejection; the two-container condition
   completed. Maximum policy time was 7.233 s. C reproduced its 23 accepted
   pre-package actions exactly. B shuffle improved safe count 23 to 24 with tied
   fill. These local observations do not establish general completion or Public gain.

The [candidate report](../experiments/submission_candidate/README.md) links full
JSON traces, source/configuration hashes, timings, reviews, and rejected variants.
[Experiments index](../experiments/README.md) and [development guide](development.md)
provide the next layer of detail. Original measurements stay intact even when
their paths, hypotheses, or procedures become historical.

## How to navigate everything

- `artifacts/`, `evaluations/`: content-addressed source, manifests, raw submitted
  feedback, and interpretation. Generated views: `progress.md`, `knowledge/CURRENT.md`.
- `deliverables/`: one folder per ZIP/result association; future results use a
  new folder, never a growing collection of unrelated root-level result logs.
- `experiments/`, `simulator/agents/`, `simulator/results/`, `analysis/`: implementations,
  diagnostics, failure snapshots, comparisons, and code reviews.
- `simulator/src/`, `configs/`, `scripts/`, `tests/`, `dockerfiles/` beneath simulator:
  official execution and physics context plus locally added verification.
- `submit/`, `knowledge/history/`, `docs/superpowers/`, `.superpowers/`: historical
  source/result copies and planning records. Old assignments are not active instructions.
- `official_mhtml/`: captured official references. `.agents/`: project skills.
- `tools/`, root `tests/`, `.github/`: registry, benchmarks, packaging, and automation.
- `.lab/`: retained audit/migration evidence; installed environments, duplicate
  checkout/export caches, and authentication material are excluded from sharing.
  The inaccessible old `evaluation-786e70-private-staging` directory is also
  excluded: its record and raw result are byte-identical to the registered
  `evaluation-786e70e5a08bbed8ff042c618439d19d94833d8994ac9df94d06be6c5c8c6825` files.

## Next decision and use by another AI

The external aggregate cannot identify the first failing scene or distinguish
intentional terminal rejection from an unexpected physical failure. Diagnose
specific unresolved states, then compare a changed packing trajectory across
modes, safe count, fill, completion, and runtime. Do not repeat larger search caps
or previously rejected drops without a concrete fix to their observed failure.
Result registration does not authorize a new development run on its own.

Read this private repository using an account/connector with repository access,
or use its downloaded source archive. Installed Python/WSL dependencies are
machine-specific and are not uploaded; runtime commands and versions are in
[development](development.md). A recorded failure is evidence, not an unfinished
instruction to resume an old plan. Follow the user's current request and AGENTS.md.
