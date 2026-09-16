# Diverse ingress lookahead

This variant keeps the corrected ingress controller and changes only probe
selection. Before the bounded prefix is taken, candidate actions are
interleaved by spatial basin. The future probe then examines at most three
deduplicated visible types, ordered by descending volume and maximum
dimension, with a global 144-point cap per type.

The one shared 1.6-second lookahead window and three-second final-preview
reserve are unchanged. A proven insertion remains a positive partial proof if
coverage is interrupted. A timeout with no proof remains unknown and keeps the
base score. Every returned action still receives a fresh native check and the
settling preview.

This isolated B/A candidate was rejected after the full B comparison: 13/42 safe
placements and fill 13.4140, versus 22/42 and 25.4502 for progressive ranking.
The final preview reached only 250 of 300 steps within the shared deadline.
Spatial diversity changed the trajectory but did not justify its search cost.
The full record is at
`../../../submission_candidate/results/diverse-lookahead-b-task001-seed42-r1.json`.

## Focused checks

From the repository root:

```text
wsl.exe -d Ubuntu --cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading -- env PYTHONPATH=experiments/ingress_lookahead/variants/diverse_lookahead:simulator/.test_deps_linux simulator/.venv_wsl/bin/python -m unittest discover -s experiments/ingress_lookahead/variants/diverse_lookahead/tests -p 'test_*.py'
```
