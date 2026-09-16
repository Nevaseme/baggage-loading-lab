# Cloud development: design, physics, and submission ZIP

Use this repository as a submission/result notebook. No GitHub Release, tag,
version-numbering ceremony, or release approval is needed. Preserve each ZIP and
its result in a separate `deliverables/YYYY-MM-DD-technique/` folder.

[Verification record](../knowledge/validation/2026-09-16-cloud-readiness.md):
the standalone setup, ZIP build, and official A/B smoke passed both in a clean
Linux environment and on GitHub-hosted Ubuntu. Earlier web ChatGPT work also
produced a submission ZIP and subsequently ran official physics using an uploaded
self-contained Python/PyBullet runtime.

## Start in web ChatGPT

Read the repository's handoff and obtain the working files with their paths intact,
using the connected repository or an uploaded source archive. Reuse an available
Python runtime with NumPy, Gymnasium, PyBullet, and Pillow. The demonstrated offline
workflow extracts an uploaded self-contained runtime and invokes its Python
directly; no network installation is needed. For a fresh environment, use the
setup below. The current algorithm needs no GPU, model API, or Torch.

## Set up once

Use Linux x86-64 and Python 3.12 for the reference setup. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cloud.txt
.venv/bin/python -m tools.cloud_smoke --output .lab/cloud-smoke/first
```

If `venv` reports that `ensurepip` is missing, install the host's Python venv
support, or use an existing pip to populate a venv created with `--without-pip`:

```sh
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install -r requirements-cloud.txt
```

For a managed cloud image with Python/pip already configured, the setup command
can simply be `python -m pip install -r requirements-cloud.txt`; use that same
interpreter for all later commands. Dependencies are pinned for reproducibility.
The supplied official Dockerfile remains an alternative reference environment.

The smoke check builds a ZIP, extracts it, verifies source hashes, and runs the
official spawned-process lifecycle on two tiny A/B tasks. It must complete both
tasks. It proves packaging, imports, physics, and process compatibility; it is
not a score benchmark. Use a fresh output directory each time.

## Design and compare

1. Read `START_HERE.md`, `docs/ai-handoff.md`, `progress.md`, and relevant experiment
   reports. Distinguish submitted scores from local proxies and stopped episodes.
2. Copy a measured parent into a new `experiments/<technique>/source/` package.
   Preserve the public Agent interface and exact scored artifacts. Write the
   expected gain, control, and comparison criterion before a substantial run.
3. Implement and test the changed behavior. Run matched full episodes, for example:

```sh
PYTHONPATH=simulator .venv/bin/python -m tools.benchmark --agent experiments/submission_candidate/source/agent.py --task 001 --mode B --seed 42 --output .lab/cloud-b-full.json
```

Substitute the new source path and a fresh output. Run modes A/B/C separately and
relevant shuffled/configuration cases. Inspect JSON `outcome`: a nonzero benchmark
exit code can mean an intentionally recorded early stop, not a broken runner.
Use `docs/evaluation-contract.md` for full submission verification.

## Build and return the deliverable

```sh
.venv/bin/python -m tools.package_agent --source experiments/submission_candidate/source --package-name support_recovery_packing --output deliverables/YYYY-MM-DD-technique/submission.zip
```

Substitute the new source, technique, and date. The builder creates the parent
folder and refuses overwrites. Extract the exact ZIP into a fresh directory;
put that directory on `PYTHONPATH`, then run the official lifecycle from `simulator/`
using `python -m scripts.run_test --module-path PACKAGE_NAME/` and a fresh result
filename. Keep module paths importable and ending with `/`.

Return the downloadable ZIP, its SHA-256, measured results, and experiment notes.
Later place the user's external `result-log.txt` beside it and register the pair
through `tools.lab`. Do not invent a Public aggregate from component scores.
