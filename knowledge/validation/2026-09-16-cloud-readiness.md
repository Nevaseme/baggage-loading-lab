# Cloud readiness verification

Validated implementation commit: `ae30d987796f52b3ae749865acf108f651764f1f`.

| Check | Result |
| --- | --- |
| GitHub plugin reads `docs/cloud-development.md` and `requirements-cloud.txt` | Passed with the connected account |
| Fresh isolated Linux Python3.12 environment installs requirements | Passed; no existing project test-dependency path used |
| Build ZIP, extract, verify source identity | Passed; archive SHA-256 `40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90` |
| Official spawned-worker A/B smoke with two items each | Both completed; all inclusion/validity/safety flags true |
| Smoke completion/rejection unit checks | 4 passed |
| GitHub-hosted Ubuntu cloud build and official smoke | Passed |
| GitHub-hosted registry/tooling verification | Passed |

Cloud run: [GitHub Actions 35096205663](https://github.com/Nevaseme/baggage-loading-lab/actions/runs/35096205663).
Both `cloud-smoke` and `verify` finished with `success`. The cloud job installed
the standalone dependencies, built the archive, and executed the extracted Agent
through the supplied official runner. Detailed smoke results are in its logs.
The separate [clean Linux report](2026-09-16-clean-linux-smoke.json) preserves
dependency versions, timings, hashes, process settings, and task results.

These checks cover setup, packaging, and runtime compatibility. The two-item
tasks are smoke checks; algorithm comparisons use full episodes.

## Earlier web ChatGPT execution

The referenced conversation, [Branch · Branch · Branch · ZIP提出と最終検証結果](https://chatgpt.com/c/6a90548b-7a90-83e8-9010-f8f612022fd0),
records creation of the Ingress-Preserving Column Scaffold submission ZIP
(SHA-256 `8f395465f592e3f001c6e305a3e613ac29a8d6aeb99ab40f5edc7a4e86ea9f25`).
It later records extraction of an uploaded self-contained Python 3.11.16 runtime
with PyBullet 3.2.7, Gymnasium 1.2.3, NumPy 1.26.4, and Pillow 10.3.0.
The official runner completed four items with all inclusion, validity, and safety
flags true; maximum policy time was 0.0862 seconds. The extracted simulator copy
needed one f-string quotation change for Python 3.11 compatibility. The current
reference setup uses Python 3.12.

This provides a demonstrated offline runtime workflow alongside the current
Linux and GitHub Actions checks. Follow [cloud development](../../docs/cloud-development.md)
to continue from repository context through implementation, comparison, and ZIP creation.
