# Physics comparisons

Local proxies; Public score is not inferred. Each JSON records exact source/settings, configuration, stream, actions, outcome, and timings. A nonzero runner exit preserves physical failures and candidate exhaustion.

| Run | Mode | Safe placements | Fill | Policy max (s) | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| [aligned-a-task000-seed42](results/aligned-a-task000-seed42.json) | A | 25/41 | 28.976 | 1.422 | policy_error |
| [aligned-b-task001-seed42](results/aligned-b-task001-seed42.json) | B | 17/42 | 17.936 | 3.346 | physical_failure |
| [baseline-a-task000-seed42](results/baseline-a-task000-seed42.json) | A | 25/41 | 33.944 | 0.699 | physical_failure |
| [baseline-b-task001-seed42](results/baseline-b-task001-seed42.json) | B | 23/42 | 21.070 | 1.942 | physical_failure |
| [baseline-b-task001-shuffle17](results/baseline-b-task001-shuffle17.json) | B | 23/42 | 25.225 | 1.974 | physical_failure |
| [baseline-c-task001-seed42](results/baseline-c-task001-seed42.json) | C | 18/42 | 17.852 | 0.540 | physical_failure |
| [baseline-c-task001-shuffle17](results/baseline-c-task001-shuffle17.json) | C | 16/42 | 17.971 | 0.512 | physical_failure |
| [baseline-c-two-containers-seed42](results/baseline-c-two-containers-seed42.json) | C | 42/42 | 21.788 | 0.949 | completed |
| [fair-b-task001-seed42](results/fair-b-task001-seed42.json) | B | 15/42 | 12.013 | 2.926 | policy_error |
| [historical-preview-b-task001-seed42](results/historical-preview-b-task001-seed42.json) | B | 23/42 | 21.070 | 4.788 | policy_error |
| [preview-b-task001-seed42](results/preview-b-task001-seed42.json) | B | 17/42 | 17.936 | 5.205 | policy_error |
| [preview-protect-volume-b-task001-seed42](results/preview-protect-volume-b-task001-seed42.json) | B | 17/42 | 17.936 | 5.352 | policy_error |
