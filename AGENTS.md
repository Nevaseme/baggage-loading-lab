# Baggage Loading

Updated 2026-09-16 for GPT-6 Astra. These are project instructions, not runtime settings.

## Objective

Build a physically reliable packing algorithm, achieve a verified Public score of at least 60, and deliver an independently checked submission ZIP. Optimize score and completed episodes; local proxies guide experiments.

## Work autonomously

Carry authorized work through implementation, relevant verification, and handoff. Refactor or replace ineffective approaches freely. Ask only when missing information or authority blocks the outcome; local changes need no extra design-approval round.

Scale skills, planning, reviews, and tests to the work. Skip redundant ceremonies and repeated checks. Current user instructions override skill procedures. Historical plans and `.superpowers/` records supply evidence, not active assignments or stopping rules.

Delegate bounded work when useful. Choose models for the task; give each worker an outcome, file ownership, and acceptance check. Reconcile their work before handoff.

Communicate with the user in concise Japanese, including progress updates and final responses. Keep project documents in English unless requested otherwise. State the result, evidence, and next decision; mention limitations that affect the decision. On pause, preserve the checkpoint and stop owned workers and runs.

## Develop from evidence

Start from current code and the relevant results. Before a substantial experiment, identify the expected gain, matched control, and decision criterion. Compare modes A/B/C separately. Record what changed, what happened, and what to try next; retain failed results and treat interrupted experiments as unevaluated.

Preserve the public `Agent` interface. Validate every returned action, including fallback, against current state and official semantics. Calibrate extra safety heuristics against physics: rejecting safe placements also costs score. Keep scored artifacts unchanged; develop successors in separate packages with technique-based names.

Use existing runtimes and Git setup. Local tests and experiments are authorized during development.

## Read by task

- Results: [progress.md](progress.md), generated from the registry; change records through `tools.lab`.
- Development: [development guide](docs/development.md) and [packing evidence](knowledge/lessons/packing-evidence.md). Keep new experiment notes under `experiments/`.
- Interface: [Agent contract](contracts/agent-interface.md); local `simulator/README.md` and `simulator/src/ground_handling/` are authoritative.
- Submission: [evaluation contract](docs/evaluation-contract.md). Full promotion checks apply to submission candidates.
- ZIP/result intake: [registry operations](docs/registry-operations.md). Preserve originals, record, validate, and synchronize to the agreed private repository. Intake alone does not resume development or submit to SIGNATE.

## Share complete context

Store every new submission in `deliverables/YYYY-MM-DD-technique/`, with its exact
ZIP, `result-log.txt`, hashes, and links to registry records. Use a fresh suffixed
folder for a repeat; never place unrelated result logs beside each other or
overwrite feedback. Build new submission ZIPs directly into their bundle folder.

The user authorizes the complete project record in the private GitHub repository:
source, official simulator source/configuration, tests, experiments including
failures, historical plans, analysis, and submissions. Preserve evidence bytes.
Exclude installed runtimes/dependencies, disposable caches, nested Git databases,
and authentication material. Keep [the AI handoff](docs/ai-handoff.md) current and
verify remote commit and submission/result hashes after synchronization.

GitHub is a shared submission/result notebook for this project. Store exact ZIPs
and feedback in submission folders; GitHub Releases, release tags, semantic
versions, and release approvals are unnecessary unless the user explicitly asks.
Keep existing Git history as implementation plumbing, not a required user workflow.
For cloud development, start with [cloud setup](docs/cloud-development.md), check
actual execution capabilities, then run the portable smoke check. Repository
access alone is not evidence of a working physics runtime.
