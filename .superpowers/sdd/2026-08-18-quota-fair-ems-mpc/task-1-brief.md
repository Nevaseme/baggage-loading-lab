# Task 1 Brief — Phase-0 Diagnostic Core and Fixed Manifest

Implement only Task 1 from
`docs/superpowers/plans/2026-08-18-quota-fair-ems-mpc.md`, following the
approved design in
`docs/superpowers/specs/2026-08-18-quota-fair-ems-mpc-design.md`.

## Allowed files

- Create `simulator/tests/quota_fair_starvation_diagnostics.py`.
- Create `simulator/tests/quota_fair_case_manifest.py`.
- Create `simulator/tests/test_quota_fair_starvation_diagnostics.py`.
- Create `simulator/tests/run_quota_fair_phase0.py`.
- Create/update `.superpowers/sdd/2026-08-18-quota-fair-ems-mpc/task-1-report.md`.

Do not modify production code, historical tests, `progress.md`, submission
archives, dependencies, or any file outside this list.

## Required process

1. Read the complete Task 1 plan and approved design before editing.
2. Use test-driven development: run the focused test first and record genuine
   RED caused by absent behavior; implement minimally; run focused and related
   GREEN commands exactly as the plan specifies.
3. The tracer must invoke the unchanged real production catalog exactly once,
   preserve proposal object identity, record causal per-position termination,
   and never infer cap/deadline from final catalog state alone.
4. The diagnostic clock wrapper must not patch the process-global `time`
   module. It must preserve the production call's clock values and condition
   order.
5. Measurement and fair-share classification are separate immutable results.
6. Manifest content, materialization, CLI schema, atomic writes, and accepted
   CLI options must match the plan literally.
7. No package installs, Git operations, or production edits.
8. Report exact commands, outputs/counts, changed files, manifest digest,
   self-review, and unresolved concerns. Return a short status/tests/concerns
   summary to the parent.

## Review acceptance

- All focused/related tests and compile checks pass.
- Historical production hashes remain unchanged.
- No Critical/Important finding from a Sol-high read-only review remains.

