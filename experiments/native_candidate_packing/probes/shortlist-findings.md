# Basin retention snapshot experiment

Hypothesis: score-based trimming before support-basin diversification discards
every feasible root in a lower-scoring basin. Increasing candidate generation
alone cannot fix this selection loss.

Control: frozen `../source/agent.py`, 6,500 candidate checks, retained shortlist
96, final native-query cap 96, preview disabled during policy. Use the original
backfill weight for each saved snapshot (0 or 8).

Treatment: `../variants/basin_coverage/agent.py`. The only source change removes
intermediate score-based shortlist trimming. Keep the bounded generated roots
until physical duplicate removal and basin diversification, then retain the
original final 96-candidate/query limits. No support threshold, score, action
semantics, or physics margin changes.

| Saved failure state | Control | Basin-retention treatment | Separate 300-step preview |
| --- | --- | --- | --- |
| Native B, 20 placed | No action, 26 transport rejections | Action after 10 native checks | Safe: displacement 0.05763 m, rotation 1.0624 degrees, no previously-inside volume lost |
| Backfill-8 B, 13 placed | No action, 57 transport rejections | Action after 14 native checks | Safe: displacement 0.03107 m, rotation 0.1022 degrees, no previously-inside volume lost |

The first recovered action is a rotated upper support placement at local
`[0.738862, -0.339334, 1.156665]`; the second is a front floor placement at
`[0, -0.535, 0.173]`. Both use visible pool ordinal 0 and container ordinal 0.

Evidence:

- `shortlist-coverage-initial.json`: original control versus wide retention;
  each record contains exact source/state hashes and action/preview outcomes.
- `shortlist-basin-variant.json`: the distinct minimal variant returns both
  actions with original 96-query limits. Probe timings are marked contended.
- `test_basin_coverage.py`: 2/2 focused regressions passed in 5.303 seconds
  without a competing root physics run. Each checks the original budgets,
  exact native inclusion/target/transport, and full preview safety.

Reproduce from `simulator/` with its WSL Python:

```text
.venv_wsl/bin/python ../experiments/native_candidate_packing/probes/test_basin_coverage.py -v
.venv_wsl/bin/python ../experiments/native_candidate_packing/probes/shortlist_coverage.py --source variants/basin_coverage --output <fresh-output.json>
```

Decision: a full matched episode is justified. Snapshot recovery is demonstrated;
extra physical placements, episode completion, and Public-score improvement
remain unverified. The reduced preview starts packed bodies at zero velocity and
uses plane boundaries, so its prediction does not replace full physics evidence.
