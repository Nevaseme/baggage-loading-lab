# Packing evidence

Use these findings to choose experiments; no planner is mandatory. See [progress.md](../../progress.md) for registered Public results.

| Observation | Design implication | Evidence limit |
| --- | --- | --- |
| All four recorded lineages have stopped external runs | Separate early-stop effects from packing quality | Per-scene failure steps are incomplete |
| Exact-Root EMS MPC failed after 14 safe placements on task001/seed42; three diagnostic modes produced the same 15 actions | Fix the unchecked fallback route | Does not explain every Public failure |
| A strict mask accepted only 4 of 25 historically safe actions | Measure false rejection as well as unsafe acceptance | Relaxing every predicate is not justified |
| The calibrated shield preserved 25 safe actions, then rejected the next | Useful validation control | No extra placement, natural completion, or Public gain shown |

Sources: [development history](../history/development-progress-before-registry.md), [step-14 traces](../../experiments/step14-forensics/), and [shield checkpoint](../../experiments/historical-shield/development-checkpoint.md).

## Current submission evidence

The [support recovery candidate](../../experiments/submission_candidate/README.md)
preserves historical A/B sample count and fill and improves C task001/seed42 from
18/42, fill 17.8524 to 23/42, fill 25.1853. The exact ZIP reproduces those results.
It remains a partial packer with Public score pending. Motion-carry preview still
misses contact-history effects; diverse raised drops failed full replay. Tested
future-ingress scoring did not improve B. Do not repeat these variants without a
specific change addressing the observed failure.

## Further comparison ideas

- Test whether historical low-column planning produces useful placements excluded by successor search.
- Test whether reserving later ingress routes and support surfaces extends safe packing. The portal-on/off comparison is unfinished, so its causal benefit remains open.
- Revisit Quota-Fair only with a working safety path; the earlier run stopped before testing its allocation hypothesis.

Compare matched tasks and modes. Mode A task000 counts cannot establish improvement over mode B task001.

The reviewed `portal_reserved_scaffold_dag` component is the historical-plan authorizer/shield. Scaffold, portal, and planner work remains partially implemented and unverified. Use the [development guide](../../docs/development.md) to choose the next experiment from that evidence.
