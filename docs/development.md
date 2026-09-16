# Development guide

Updated 2026-09-16. The next design should improve completed packing, starting from the strongest relevant measured control.

Start with the [current optimization results](../experiments/README.md). They identify the compared controls, active successors, and next decisions by mode.

## Available work

| Component | Location | Status |
| --- | --- | --- |
| Current submission candidate | [Support recovery](../experiments/submission_candidate/README.md) | Exact ZIP passes official A/B lifecycle; C recovery measured; Public pending |
| Best exact Public record | `conservative_extreme_point_packing` in [progress.md](../progress.md) | 29.74350010538; stopped; original ZIP missing |
| Historical control | `submit/Conservative Extreme-Point Packing_score29.7/` | Local source/result copy; registered source is under `artifacts/` |
| Reviewed shield | `simulator/agents/portal_reserved_scaffold_dag/agent.py` and `authorizer.py` | Historical proposals with current-state validation; 25 safe placements in the recorded cross |
| Scaffold/portal successor | Same package: `scaffold.py`, `portal.py`, `planner.py` | Partial implementation; not connected to `Agent` or physically compared |
| Other search experiments | `simulator/agents/highscore/`, `support_extreme_fusion_beam_exact_mask/` | Experimental lineages; assess relevant evidence before reuse |
| Official environment | `simulator/src/ground_handling/`, `simulator/configs/` | Local authority for physics and actions |

The [packing evidence](../knowledge/lessons/packing-evidence.md) explains early failures and false rejections. The [shield checkpoint](../experiments/historical-shield/development-checkpoint.md) preserves the earlier review. Neither commits the next design to that architecture.

## Choose the next experiment

Establish a matched control, then test one cause of lost placements: candidate coverage, false rejection, fallback validity, or later ingress/support. Compare safe count, fill, first failure, and runtime by mode. Keep a change when its measured benefit justifies its cost; replace a stalled approach when evidence supports a better one.

Native transport and progressive recovery improve one mode-C stream and tie a
shuffled holdout. Global rear-first ordering regresses. Tested future-ingress
ranking did not improve B; motion estimates corrected one false-safe drop but
missed another. The current ZIP excludes both. Next work needs a changed packing
trajectory with a full matched gain, or stronger calibration of contact history.
See the [evaluation contract](evaluation-contract.md) before promotion.

## Local commands

Run registry commands from the project root with `simulator/.signate_venv/Scripts/python.exe`. Physics uses Ubuntu WSL and the existing Linux dependency bundle; the Windows environment does not have the physics packages.

Verified runtime: Python 3.12.3, NumPy 2.5.2, Gymnasium 1.2.3, and PyBullet. From PowerShell at the project root:

```powershell
wsl.exe -d Ubuntu --cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading -- env PYTHONPATH=simulator:simulator/tests:simulator/.test_deps_linux simulator/.venv_wsl/bin/python -m tools.benchmark --agent experiments/native_candidate_packing/source/agent.py --task 001 --mode B --seed 42 --output .lab/benchmarks/native-b-001.json
```

Choose the experiment's source/variant and a fresh output path. `tools.benchmark --help` lists mode, shuffle, settings, and input controls. WSL service access may require the tool's normal permission escalation.

The benchmark records strict in-process physics outcomes, hashes, timings, final poses, and cargo CoG proxies. It exits nonzero on physical failure or candidate exhaustion. Historical shield runners can exit successfully on a recorded failure; inspect their result fields.

The official lifecycle entry point is `python -m scripts.run_test`, with `--config-path`, `--module-path`, and `--result-dir`. Its module path expects forward slashes and a trailing slash, such as `agents/base/`.

## Save useful work

Keep successors separate from scored source. Put each experiment's hypothesis, control, source/configuration hashes, seed, result path, and next decision in `experiments/<technique>/`. Update notes when a result changes the decision; avoid duplicating raw traces in prose.

`progress.md` and `knowledge/CURRENT.md` are generated registry views. Keep
development checkpoints in experiment notes and link the current one here.
The private repository includes simulator source, tests, configurations, and
results. Installed runtime environments/dependencies stay local. Preserve exact
submitted artifacts through the registry, with test and runner evidence, before
handoff. See [AI handoff](ai-handoff.md) for complete project coverage.
