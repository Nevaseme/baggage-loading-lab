# Fair candidate packing

2026-09-16. User authorized algorithm optimization and replacement of historical approaches.

## Hypothesis and comparison

The historical nested candidate loop can spend its budget on early combinations and leave later orientations or containers unseen. Fair rounds should improve useful coverage within the same runtime limit. Keep historical proposal geometry, ranking, support thresholds, and mode A optimization initially; validate every returned action against settled state and try alternatives after rejection.

Compare the unchanged historical source with the successor on matched task, mode, seed, item stream, and host. Retain the change if it extends safe packing/fill without an earlier physical failure or unacceptable policy cost. A safe early stop alone is not a win. After this comparison, test edge-aligned support candidates separately if coverage remains limiting.

## Baseline

Mode B, task001, seed42: 23/42 safe placements, local fill 21.07047576700756, followed by physical failure. Policy max 1.9425 s. See [full result](results/baseline-b-task001-seed42.json) for configuration, actions, hashes, and timing.

## Implementation

`source/historical.py` is a copy of the scored control. `source/agent.py` changes online candidate allocation and rejection recovery; mode A optimization is inherited. `source/authorizer.py` copies the reviewed current-state validator and corrects local-to-world X conversion for offset containers. That defect was caught by a later-container regression. No official simulator source is bundled in the candidate.

Tests cover later-container coverage, rejection of an all-full scene, fresh authorization of returned actions, and the Agent interface. Results from `tools/benchmark.py` use the official physics environment and are local proxies. Public score and submission readiness remain unestablished until the promotion checks and external evaluation.

## Comparison decisions

| Variant | Mode/task/seed | Safe count | Local fill | Result |
| --- | --- | ---: | ---: | --- |
| Historical | A/000/42 | 25/41 | 33.9439 | Physical failure |
| Historical | B/001/42 | 23/42 | 21.0705 | Transport rejection |
| Historical | C/001/42 | 18/42 | 17.8524 | Physical failure |
| Fair allocation only | B/001/42 | 15/42 | 12.0127 | No candidate; reject this variant |
| Aligned support candidates | B/001/42 | 17/42 | 17.9364 | Settling failure; insufficient |
| Aligned support candidates | A/000/42 | 25/41 | 28.9763 | Same count, lower fill; reject |
| Aligned + settling preview | B/001/42 | 17/42 | 17.9364 | Prevented collapse, no packing gain |
| Preview + protect existing volume | B/001/42 | 17/42 | 17.9364 | Same trajectory; no gain |
| Historical proposal + preview/recovery | B/001/42 | 23/42 | 21.0705 | Matched control, no recovery gain |

The aligned generator recovers an authorized action from the 15-placement failure snapshot without changing support/transport thresholds. The full run then fails at a different front stack. The observation-only preview reproduces its 0.471 m displacement and rejects it, but fails to find a useful alternative within budget. In mode A, the same item order/count produces less fill because earlier cargo moves outside the scoring boundary. These variants are evidence, not successors to the scored control.

The historical-prefix run spends most of its recovery budget before the new search, reaching only 86 candidate checks at the failed state. The next experiment replaces the expensive geometric transport validator and removes the old approximate transport prefilter. It must increase actual packing, not merely convert a physical failure into candidate exhaustion.

The benchmark is a strict in-process physics diagnostic. It uses the official environment, but aborts on a policy timeout instead of reproducing the official runner's fallback/restart. Finalists need a separate exact-ZIP official lifecycle run. Applied limits and dependency versions are recorded in new runs.
