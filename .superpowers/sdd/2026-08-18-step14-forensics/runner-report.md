# Step-14 forensic runner implementation

## Scope

Implemented the non-production runner in `simulator/tests/run_step14_forensics.py`
and focused tests in `simulator/tests/test_step14_forensics.py`. Historical
agent and simulator packages were not changed.

The runner supports `control`, `trace`, and `trace_probe`. All three physical
arms use fresh environments and agents with identical task, seed, config, and
MPC-on settings. The physical Agent and planner are never monkeypatched. During
an episode the runner performs policy, an atomic pre-action snapshot,
`env.step`, collision/stdout capture, and an atomic partial JSON write. Saved
snapshots are reloaded only after the environment is closed.

Route provenance is reconstructed after the episode with a fresh shadow agent
and explicitly labelled `diagnostic_shadow_replay`. Shadow-only wrappers capture
Candidate presence and the live planner `build_root_catalog` root count plus
content-derived stable root keys. Wrapper installation and restoration are
transactional, and inherited methods are restored by deleting temporary
instance attributes rather than leaving bound-method overrides behind.

Captured evidence also includes action/observation SHA-256 values, pool and
global item indices, policy and shadow-policy elapsed times, strict public
action format checks, canonical status, post-episode exact validation in all
three modes, `env_step_calls`, `safe_placement_count`, final packed item count
and indices, collision/contact fields, and validator stdout collision lines.
The real CLI writes a partial result for every arm and a final pairwise action
sequence/hash summary. `complete` and `success` become true only when all three
arms have materialized without `runner_error` or `diagnostic_runner_error`;
otherwise `failed_modes` is preserved and the CLI exits nonzero.

Failure labels apply format → inclusion → transport → placement precedence and
include `unchecked_last_resort_transport_defect`,
`exact_or_emergency_candidate_safety_defect`, and
`diagnostic_interference` when evidence supports them. Missing or non-boolean
simulator status predicates are malformed failures. Diagnostic callback
signatures are inspected before invocation; a callback's internal `TypeError`
is not retried.

`completed_steps` now means successful physical placements and matches
`safe_placement_count`; all attempted policy records are counted separately as
`attempted_policy_records`. Status success considers only the three official
predicates. Missing collision evidence is represented explicitly with
`available: false`, source, and reason fields.

## Verification

WSL configured NumPy runtime:

```text
PYTHONPATH=simulator python3 -m unittest simulator.tests.test_step14_forensics
Ran 18 tests ... OK

PYTHONPATH=simulator python3 -m unittest \
  simulator.tests.test_step14_forensics \
  simulator.tests.test_quota_fair_starvation_diagnostics
Ran 51 tests ... OK
```

No PyBullet episode was launched by this implementation task. The implemented
CLI is ready to create and run all three fresh physical arms in the configured
WSL environment.
