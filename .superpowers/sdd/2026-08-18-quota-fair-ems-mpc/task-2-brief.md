# Task 2 Brief — Execute Phase 0 and Enforce the Evidence Gate

Execute only Task 2 from
`docs/superpowers/plans/2026-08-18-quota-fair-ems-mpc.md` using the Sol-approved
Task 1 diagnostic runner.

## Required outputs

- `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/task001.json`
- `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/generated.json`
- `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/results.json`
- `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0/manifest.json`
- `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/phase-0-report.md`
- Update root `progress.md` only with the verified hypothesis result and evidence
  paths; do not create an agent package in this task.

## Constraints

- Use the exact WSL commands and seeds from Task 2.
- No installs, Git operations, production edits, threshold changes, or manual
  changes to raw evidence.
- On an incidental diagnostic bug, first add a focused failing unit regression
  in Task 1's test file, then minimally fix only Task 1 test/tool files, rerun
  the full Task 1 verification, and document it.
- Abort on any false physics status or malformed/contradictory evidence.
- Set `proceed=true` only for at least three distinct qualifying lookahead-20/40
  states and frequency at least 0.05.
- If the gate fails, record rejection and stop. Do not create
  `exact_root_ems_mpc` or `quota_fair_ems_mpc`.
- If it passes, stop after writing the evidence report and request Sol-high
  evidence review. Task 3 remains for a later assignment.

