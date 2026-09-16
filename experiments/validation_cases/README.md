# Additional validation conditions

Derived from the supplied sample task001 without changing cargo physics or validator rules. Use with `tools.benchmark --config <file> --task 001 --mode B`; compare the same file, seed, and shuffle setting for control and candidate.

- `lookahead3.json`: three visible items.
- `lookahead40.json`: forty visible items.
- `two_containers.json`: adds a prioritized second container with 0.06 m buffer and 0.25 m cut width, spaced 3.1 m apart. This exercises nonzero X coordinates and different geometry.

These are generated local conditions, not official or hidden evaluation cases. A file's presence does not mean a candidate has passed it. Results belong in the tested experiment's results directory.

`two_containers.json` was compared in mode C, seed42: the historical control and
historical-prefix progressive recovery both completed 42/42, with fill 21.788.
See [episode records](../native_candidate_packing/RESULTS.md). The lookahead3/40
files were subsequently evaluated against the exact support-recovery ZIP:
25/42 and 24/42 safe placements respectively, with explicit terminal rejection.
These two conditions have no matched historical run. See
[the final campaign](../submission_candidate/validation/README.md).
