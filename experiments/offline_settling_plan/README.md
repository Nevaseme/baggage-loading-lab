# Offline settling plan

The corrected controller with rear-first weighting also regresses:
[backfill8 A](results/offline-backfill8-a-task000-seed42.json) reaches 18/41,
fill 16.3658, then finds no authorized action. Reject this ordering; neither
offline variant replaces the historical A control.

This is an isolated mode-A prototype. It builds the item order by repeatedly
running the observation-only native validator and a full 300-step PyBullet
settling preview on a deep-copied container state. After an accepted trial, it
copies the settled pose of every existing body and the new body into the next
virtual state. Identical cargo profiles are represented once per trial because
their geometry and dynamics are interchangeable; the selected stream
occurrence is removed from the real remaining list.

The planner has a 150-second wall-clock budget, leaving margin under the
official 180-second optimization timeout. If the virtual prefix cannot find a
settled action, unresolved items are appended with the historical static key.
The online policy checks each stored local action against the current observed
container and current native transport path. If a stored action drifts or its
preview fails, it searches current candidates and then uses a bounded native
recovery path. If all recovery candidates fail authorization, it raises
`NoValidAction` instead of returning an unchecked action.

The initial source was evaluated locally in mode A at 24/41 safe placements
with fill 30.2609748598, versus the historical control at 25/41 and
33.9439267917. That source is frozen under `variants/initial/`; the corrected
source has been evaluated with backfill8 as recorded above, but not with its
default ordering.

This package copies the private geometric helpers and does not import the
official simulator. It is an experiment, not a Public-score claim. The preview
starts observed bodies at rest, does not model hidden velocities, and does not
predict every interaction outside its reconstructed scene. Full-episode
comparison and official-runner validation remain required before promotion.

## Focused checks

Run the package tests from the repository root with the project WSL runtime:

```text
wsl.exe -d Ubuntu --cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading -- env PYTHONPATH=experiments/offline_settling_plan:simulator/.test_deps_linux simulator/.venv_wsl/bin/python -m unittest discover -s experiments/offline_settling_plan/tests -p 'test_*.py'
```

The command above is a focused package check. It is not a full episode or a
score evaluation.
