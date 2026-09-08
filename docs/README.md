# Project documentation map

Current project behavior is defined in [AGENTS.md](../AGENTS.md); submission acceptance is defined in [evaluation-contract.md](evaluation-contract.md). [progress.md](../progress.md) records results and the latest checkpoint. The user's current request controls whether work is paused, investigative, or developmental.

## Read by purpose

| Need | Reference |
| --- | --- |
| Latest verified outcomes and outstanding work | Root `progress.md`, then the linked evidence |
| Simulator API and mechanics | [Portable Agent contract](../contracts/agent-interface.md); authoritative simulator distribution remains local |
| Candidate acceptance | `docs/evaluation-contract.md` |
| Paused scaffold implementation | [Preserved checkpoint](../experiments/historical-shield/development-checkpoint.md), with local-only original paths inside |
| Why agent instructions changed | [2026-09-08 audit](2026-09-08-instruction-audit.md) |
| Submission/result intake and AI handoff | Root [START_HERE.md](../START_HERE.md) and [registry operations](registry-operations.md); the full design remains under `docs/superpowers/specs/` in GitHub |
| Intake, correction and synchronization commands | [Registry operations](registry-operations.md) |

## Historical plans and briefs

Some archive references point to the user's local simulator and `.superpowers/` workspace, which are not part of the curated initial GitHub upload. Shared evidence is copied into `knowledge/history/` and `experiments/`; absence of a local archive in a clone is not proof that an experiment was never performed.

The dated files under `superpowers/plans/`, `superpowers/specs/`, and `../.superpowers/sdd/` preserve experiment designs, assignments, and reviews. They are evidence and candidate approaches, not a cumulative instruction stack. Read them when relevant; selecting a plan means reconciling its scope and dependencies with the current request and current working agreement.

Past model assignments, mandatory workflow templates, and lineage-specific stopping rules are superseded as general operating policy by `AGENTS.md`. Recorded test outcomes, predeclared experiment thresholds, and artifact hashes retain their historical meaning. A changed experiment criterion gets a new dated rationale and comparison; it does not retroactively turn a failed result into a pass. Unchecked checkboxes alone are not proof that recorded completed work must be repeated.
