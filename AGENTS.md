# Baggage-Loading: working agreement

Reviewed 2026-09-08 for GPT-6 Astra. These are project instructions, not model/runtime configuration.

## Outcome and scope

Develop a physically reliable baggage-packing algorithm with evidence supporting a Public score of at least 60, and deliver an independently verified submission ZIP. Public evaluation decides score attainment; local proxies guide experiments.

Follow the user's current request. During authorized development, carry design, implementation, comparison, and packaging through to a reviewable outcome. Status requests are read-only. On a pause, preserve work, stop owned development workers/runs using available controls, and report any unconfirmed stopping state. Resume development when requested.

## Evidence-led decisions

Start from the current code and relevant evidence in [progress.md](progress.md), not an old task checklist. Separate measured facts, hypotheses, and unknowns. Before a substantial experiment, state the expected benefit, matched baseline, and result that would change the decision. At a meaningful result or repeated failure, reassess whether the next action advances score, safety, or a necessary delivery gate. Record the decision and supporting evidence briefly.

Choose algorithms freely, including separate planners for modes A/B/C. Retain, revise, or replace a hypothesis on evidence; an interrupted experiment is unevaluated, not disproved. Prefer controlled changes for causal comparisons; architectural changes are welcome with matched evaluation and focused ablations. Revise stale project procedures with a dated reason while preserving original measurements and user acceptance targets.

## Working style and authority

Use reasonable assumptions for routine, reversible decisions within the authorized task. Ask a focused question when missing user-only information or new authority materially blocks the result. Scale planning, documentation, and review to the change; an already authorized local edit can proceed without a second design-approval round. This is the user's project preference where a skill prescribes additional process; system/developer instructions, tool permissions, and explicit user approval boundaries still apply. If a skill actually blocks work, identify its file, relevant requirement, and concrete impact.

Treat dated plans and `.superpowers/sdd/` briefs as historical context until deliberately selected and reconciled with this agreement. Their old model assignments, stopping rules, and checkboxes describe that experiment. Read the needed sections, rather than loading the entire archive. Use concise Japanese updates: outcome, evidence, remaining uncertainty, next decision.

## Models and collaboration

Use the active orchestrator's judgment (GPT-6 Astra at this review). For useful, bounded parallel work, the default subagent is `gpt-5.6-luna` with `max` reasoning. Choose a different available model or effort when complexity, review independence, reliability, latency, or total task cost warrants it; record a short reason for a material change. Architecture and review are not fixed to Sol. Check the actual tool's supported model/effort combinations at dispatch.

Delegate when the expected time or quality gain exceeds coordination cost. Give each worker an outcome, relevant evidence, file ownership, and acceptance check. Use one writer per shared file scope; reviewers start read-only. Reuse existing workers where useful and reconcile their outputs before integration. Complete or interrupt owned workers at handoff so delegated work remains accounted for.

## Implementation and delivery

Preserve the simulator's public `Agent` interface and action dictionary. Every returned action, including fallback, goes through current-state validation aligned with the official implementation. Calibrate additional safety heuristics against physics; distinguish scoring preferences and stability proxies from official validity predicates.

Use descriptive technique-based names: `snake_case` packages and descriptive kebab-case archives. Historical names stay intact; verified Public scores belong in submission records. Preserve scored artifacts and develop successors in independent packages. Use project-local/configured runtimes, configured authentication with secret-free reporting, and the existing workspace's version-control setup; Git initialization and commits remain user-authorized actions.

Run checks proportionate to the change. Documentation edits need consistency/link checks; behavior changes need relevant unit/regression and physical comparisons. Submission promotion uses the full [evaluation contract](docs/evaluation-contract.md). Repeat or broaden passed checks when changed code or unresolved evidence justifies it. Record submitted artifacts, hashes, verified Public scores, statuses, and available components in `progress.md`; label unavailable values pending and local substitutes as proxies.

## Context map

- [Documentation map](docs/README.md): current references and historical plans.
- [Simulator reference](simulator/README.md) and `simulator/src/ground_handling/`: interface and authoritative local implementation.
- [Instruction audit](docs/2026-09-08-instruction-audit.md): rationale, sources, and remaining limits; read when revising this agreement.
