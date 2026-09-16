# Support recovery packing — submission candidate

2026-09-16. Public score is pending. The target of 60 is not established by local
tests. This candidate is a usable successor with explicit partial termination,
not a demonstrated solution to all cargo streams.

## Delivery

- [Submission ZIP](../../deliverables/2026-09-16-support-recovery-packing/support-recovery-packing-2026-09-16.zip):
  22,124 bytes; one importable `support_recovery_packing/` package, nine Python
  files and a source-hash manifest. Dependencies: standard library, NumPy,
  PyBullet; no simulator imports, external assets, or network access.
- SHA-256: `40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90`.
- [Archive and official lifecycle verification](validation/archive-verification.json)
  records exact source, configuration, runner hashes, and official sample results.
- [Registered method](../../artifacts/artifact-40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90/algorithm.md).

## Submitted result

The user supplied [result-log.txt](../../deliverables/2026-09-16-support-recovery-packing/result-log.txt)
for this exact ZIP. It reports a placed-item ratio of 0.46453610097631837 and
early termination. Public aggregate score is absent. See
[the registered analysis](../../evaluations/evaluation-071bf83d0161662641bdd0f5576019a9b76dc187119831b04d7b3117493ee571/analysis.md).
The local validation below predates this external result and remains unchanged.
Recorded absolute paths describe the original test location; the submission
bundle now lives in its own dated folder.

## Selected algorithm

Keep the historical planner's next action when fresh native checks and a full
300-step settling preview accept it. On rejection, progressively search
footprint-aligned and dense support roots. Preserve historical mode-A ordering.
Use at most 384 authorizations and shared internal policy budgets of 7.2 seconds
for B, 5.2 for A/C. The former B budget of 5.2 seconds interrupted a known-safe
preview after 225 steps and stopped at 19 items; 7.2 seconds restored 23.

On search exhaustion, the wrapper returns a well-formed terminal rejection,
validated against observed container planes. The official environment rejects it
before cargo creation. This preserves partial evaluation and permits later tasks
to run. It is not a valid placement, successful packing, or proof of infeasibility.
Only `NoValidAction` is caught; unexpected errors remain visible.

## Official samples from the exact extraction

| Mode | Safe count | Fill proxy | Policy max | Outcome |
| --- | ---: | ---: | ---: | --- |
| A, task000 | 25/41 | 33.9439 | 4.883 s | Explicit terminal rejection |
| B, task001 | 23/42 | 21.0705 | 6.812 s | Explicit terminal rejection |

Both official records have `status=success`, non-null evaluation, and final
`is_included=false`. That status describes valid execution, not all-items completion.
Mode A optimization took 25.643 seconds. The official runner used spawned workers,
shared observations, and its 12 GB address-space limit. No timeout/fallback or
format error occurred. These match the historical A/B count and fill controls;
the benefit is validated recovery and reliable termination, not an A/B score gain.

C on task001 reproduces 23/42 and fill 25.1853 (historical: 18/42, 17.8524).
The shuffled C holdout ties at 16/42 and 17.9710. With two offset containers it
completes all 42 items, matching the control's fill 21.7880. These are three
different local conditions, not three measurements of Public performance.

The shuffled B holdout accepts 24/42 safely versus the control's 23/42. Fill
stays at 25.2248; the candidate's maximum policy time is 6.507 seconds. One more
safe placement does not imply a fill-score increase.

[Six additional exact-extraction conditions](validation/README.md) completed
without format errors, policy timeouts, or unsafe placement outcomes. One episode
packed all items; five used explicit terminal rejection. Combined with the two
official samples, this is eight episodes. B lookahead3 reached 25/42 and
lookahead40 reached 24/42; no matched control was run for these two generated
conditions, so they establish compatibility rather than improvement. Overall
policy maximum was 7.233 seconds. This is a small local timing sample.

The exact C extraction reproduced all 23 accepted actions of its pre-package
progressive control. Independent review found no submission blocker. All 64
standard-library tooling tests passed on Windows. Whole-directory discovery also
reported a NumPy import error for the physics module; its seven tests then passed
in the configured Linux environment. Registry validation passed, and 174 protected
historical source/result files retain their original hashes.

## Rejected experiments

| Change | B or C result | Decision |
| --- | --- | --- |
| Future-ingress ranking, fixed | B: 22/42, fill 25.4502 | Same trajectory as progressive control; extra cost |
| Spatially diverse ingress probes | B: 13/42, fill 13.4140 | Regressed; final preview incomplete |
| Motion-aware diverse raised drops | B: 22/42, then physical failure | Predicted 0.258 m versus actual 0.360 m displacement |
| Relaxed support on shuffle17 | C: 18/42, fill 13.5678 | More items but less fill than 16/42, 17.971 control |

See [development design](../submission_development/README.md),
[motion recovery](../motion_recovery/README.md), and
[ingress variant](../ingress_lookahead/variants/diverse_lookahead/README.md).
Raw failures, including two launch-path/syntax errors, remain in `results/`.

## Reproduction

Build: `python -m tools.package_agent --source experiments/submission_candidate/source --package-name support_recovery_packing --output NEW.zip`.
The builder refuses overwrites. Extract to a fresh directory and put its parent
on `PYTHONPATH`. From `simulator/`, run `python -m scripts.run_test --config-path configs/sample_config.json --module-path support_recovery_packing/ --result-dir ../experiments/submission_candidate/validation --result-fname NEW.json`.

`validate_extraction.py` runs six additional conditions serially against the
extracted source under strict 8-second per-policy deadlines. It refuses existing
result paths. `verify_archive.py` checks archive bytes, source equality, and the
two-task official lifecycle. The Linux runtime is the configured WSL Python3.12
environment with the supplied physics dependencies. Raw benchmark records contain
dependency versions, simulator hashes, per-action diagnostics, poses, timing
quantiles, and mass-weighted cargo CoG proxies. These are local proxies only.
