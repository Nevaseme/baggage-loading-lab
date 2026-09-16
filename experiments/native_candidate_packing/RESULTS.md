# Physics comparisons

Local proxies; Public score is not inferred. Each JSON records exact source/settings, configuration, stream, actions, outcome, and timings. A nonzero runner exit preserves physical failures and candidate exhaustion.

| Run | Mode | Safe placements | Fill | Policy max (s) | Outcome |
| --- | --- | ---: | ---: | ---: | --- |
| [basin-b-task001-seed42](results/basin-b-task001-seed42.json) | B | 17/42 | 17.936 | 1.085 | physical_failure |
| [basin-preview-b-task001-seed42](results/basin-preview-b-task001-seed42.json) | B | 17/42 | 17.936 | 5.206 | policy_error |
| [native-a-task000-seed42](results/native-a-task000-seed42.json) | A | 24/41 | 26.341 | 1.097 | policy_error |
| [native-b-task001-seed42](results/native-b-task001-seed42.json) | B | 20/42 | 22.842 | 1.694 | policy_error |
| [native-backfill8-b-task001-seed42](results/native-backfill8-b-task001-seed42.json) | B | 13/42 | 13.245 | 1.801 | policy_error |
| [native-c-task001-seed42](results/native-c-task001-seed42.json) | C | 14/42 | 12.443 | 0.906 | physical_failure |
| [native-coverage26000-b-task001-seed42](results/native-coverage26000-b-task001-seed42.json) | B | 13/42 | 12.398 | 1.735 | policy_error |
| [progressive-b-task001-seed42](results/progressive-b-task001-seed42.json) | B | 22/42 | 25.450 | 3.923 | policy_error |
| [progressive-backfill8-b-task001-seed42](results/progressive-backfill8-b-task001-seed42.json) | B | 22/42 | 23.000 | 3.818 | policy_error |
| [progressive-c-task001-seed42](results/progressive-c-task001-seed42.json) | C | 15/42 | 13.747 | 5.213 | policy_error |
| [progressive-historical-c-task001-seed42](results/progressive-historical-c-task001-seed42.json) | C | 21/42 | 22.769 | 4.109 | policy_error |
| [progressive-historical-queries384-c-task001-seed42](results/progressive-historical-queries384-c-task001-seed42.json) | C | 23/42 | 25.185 | 4.044 | policy_error |
| [progressive-historical-queries384-c-task001-shuffle17](results/progressive-historical-queries384-c-task001-shuffle17.json) | C | 16/42 | 17.971 | 2.013 | policy_error |
| [progressive-historical-queries384-c-two-containers-seed42](results/progressive-historical-queries384-c-two-containers-seed42.json) | C | 42/42 | 21.788 | 3.322 | completed |
| [support-preview-b-task001-seed42](results/support-preview-b-task001-seed42.json) | B | 19/42 | 20.533 | 5.158 | policy_error |
