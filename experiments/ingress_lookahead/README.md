# Ingress lookahead

This package extends the progressive native controller with a bounded B-mode
lookahead. It first generates current support candidates, then re-scores a
small top set after virtually adding each candidate. The score counts how many
deduplicated remaining visible cargo types still have at least one
supporting, included, native-valid insertion across the observed containers.
Candidates that close the only ingress for a visible type are penalized. The
final action is checked again by the current-state native validator and, when
enabled, by the full settling preview.

The mode is fixed by `get_init_states`: A and B may use lookahead, while C
keeps the historical prefix and a 384-authorization recovery budget. A uses
the measured offline optimization order first. A late B observation with one
visible item remains B. Lookahead has one shared 1.6-second window per policy,
capped by a three-second final-preview reserve. Native queries use
deduplicated physical types and a global cap of 36 generated points per type,
round-robin across fitting container/orientation streams.

A future type is counted only after a native-valid insertion is proven. A
deadline after a proof preserves that positive result as partial coverage; a
deadline before any proof is unknown and receives the base candidate score.
Unknown trials are reported as unknown rather than as a completed miss.

The key comparison is a matched B run against the progressive controller:
measure completed safe placements and fill, then retain the lookahead only if
it avoids the known greedy ingress blocker without a runtime or stability
regression. This package has focused tests but no full-episode or Public-score
result yet.

## Focused checks

From the repository root:

```text
wsl.exe -d Ubuntu --cd /mnt/c/Users/TAKUMI/projects/Baggage-Loading -- env PYTHONPATH=experiments/ingress_lookahead:simulator/.test_deps_linux simulator/.venv_wsl/bin/python -m unittest discover -s experiments/ingress_lookahead/tests -p 'test_*.py'
```
