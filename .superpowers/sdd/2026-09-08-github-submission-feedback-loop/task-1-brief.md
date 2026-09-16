# Task 1: local registry

Read Task 1 and Scope and interfaces in `docs/superpowers/plans/2026-09-08-github-submission-feedback-loop.md` as your exact contract. Own only `tools/__init__.py`, `tools/lab/`, and `tests/test_lab*.py`, plus this directory's task-1-report.md. Root handles docs, actual historical migration, Git and GitHub. Do not mutate existing artifacts/results or root progress during development; tests run in TemporaryDirectory.

Python runtime: `simulator/.signate_venv/Scripts/python.exe` (Python 3.12.10). Use standard library and unittest. No external installation or network. Read root AGENTS.md. Do not spawn subagents. Use apply_patch for source edits. No commits from the worker (root integrates the initial repository).

Implement the specified CLI with focused RED/GREEN tests and self-review. Keep modules small enough to review; preserve input bytes, decimal precision and unknown status without inference. Source import may exclude `__pycache__`/`.pyc` but must retain all actual source payload. Archive import should preserve the exact safe member path layout and explicit hash manifest. Validate all IDs/paths before using them as filesystem targets. A mutation failure must not produce a false completed registry entry.

Report interfaces and CLI examples early to root so docs can use exact names. Write the full test evidence, changed files, decisions, any incomplete requirements and concerns to task-1-report.md. Final response under 15 lines: status, test count, concerns, report path. Escalate unclear material requirements rather than silently omitting them.
