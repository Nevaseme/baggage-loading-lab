# Cloud development: design, physics, and submission ZIP

Use this repository as a submission/result notebook. No GitHub Release, tag,
version-numbering ceremony, or release approval is needed. Preserve each ZIP and
its result in a separate `deliverables/YYYY-MM-DD-technique/` folder.

## What a ChatGPT session needs

GitHub access provides project context. Execution additionally needs a writable
copy of the relevant files, Python, NumPy, Gymnasium, PyBullet, Pillow, and enough
time to run physics. The current algorithm needs no GPU, model API, or Torch.

Check the actual session tools first. GitHub search snippets are not a filesystem
checkout: obtain full file contents with paths intact. Use a connected checkout,
an authorized repository download, or a source archive uploaded into the session.
Do not assume the GitHub connector's credentials are available to a shell.

- **GitHub-connected ChatGPT:** can read repository context. This alone does not
  establish that packages, binary modules, subprocesses, or repository files are
  available inside its execution environment.
- **Data-analysis Python:** can generate source and ZIP files from available
  files. Its documented environment cannot make external web/API requests, so
  dependencies must already be installed or supplied as compatible offline wheels.
  If PyBullet or full source is missing, say which step is unavailable; do not
  label an untested ZIP physically verified.
- **A provisioned Linux cloud workspace:** run the commands below. Codex cloud
  supports repository checkout and dependency installation during setup. Set up
  dependencies before any network-disabled execution phase.

These distinctions come from official [GitHub access](https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt),
[data analysis](https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt),
and [cloud environment](https://learn.chatgpt.com/docs/environments/cloud-environment)
documentation. A clean Linux smoke test verifies this repository's portability;
it is not a test of the user's particular web ChatGPT session.

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

Return the downloadable ZIP, its SHA-256, measured results, and remaining limits.
Later place the user's external `result-log.txt` beside it and register the pair
through `tools.lab`. Do not invent a Public aggregate from component scores.
Pushing changes is optional for a read-only ChatGPT session; handing the ZIP and
notes back to the user satisfies file delivery. Releases are unnecessary.
