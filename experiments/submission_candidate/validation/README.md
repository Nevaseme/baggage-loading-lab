# Exact-extraction validation

Local proxies; Public score pending. All cases use task001 with 42 items.

| Case | Safe | Fill | Policy p50/p95/p99/max (s) | Outcome |
| --- | ---: | ---: | --- | --- |
| [c-original](c-original.json) | 23/42 | 25.1853 | 1.341/3.719/4.680/4.942 | terminal_rejection |
| [c-shuffle17](c-shuffle17.json) | 16/42 | 17.9710 | 0.912/2.118/2.273/2.311 | terminal_rejection |
| [c-two-containers](c-two-containers.json) | 42/42 | 21.7880 | 1.275/2.817/3.621/3.864 | completed |
| [b-shuffle17](b-shuffle17.json) | 24/42 | 25.2248 | 1.994/4.764/6.160/6.507 | terminal_rejection |
| [b-lookahead3](b-lookahead3.json) | 25/42 | 29.5557 | 1.739/3.295/6.261/7.233 | terminal_rejection |
| [b-lookahead40](b-lookahead40.json) | 24/42 | 29.3001 | 2.271/3.609/4.208/4.387 | terminal_rejection |

No additional warmup; full episodes ran serially under an 8-second policy deadline.
Terminal rejection is an early stop, not a successful placement.

See [structured summary](summary.json) for layout proxies and metric limitations.
