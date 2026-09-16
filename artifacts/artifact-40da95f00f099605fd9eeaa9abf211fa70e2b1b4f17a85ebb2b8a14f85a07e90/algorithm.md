# Support recovery packing

Created 2026-09-16. Submitted result received; Public aggregate score is pending.
See [external feedback](../../evaluations/evaluation-071bf83d0161662641bdd0f5576019a9b76dc187119831b04d7b3117493ee571/analysis.md).

## Method

Preserve the historical extreme-point packing order while its chosen placements
pass current-state native geometry, transport, and complete settling-preview
checks. On rejection, search footprint-aligned and dense support candidates
with progressive coverage. Use the historical offline permutation for mode A.
The shared internal policy budget is 7.2 seconds for lookahead mode B and
5.2 seconds for A/C, with at most 384 authorizations.

The parent is `experiments/native_candidate_packing/variants/progressive_recovery/`.
The historical implementation is preserved verbatim; its SHA-256 is
`ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82`.
Future-ingress ranking, globally relaxed support, and raised-drop recovery were
compared and excluded after regressions or inaccurate physical predictions.

## Termination and evidence

The API provides no stop action. If bounded search finds no accepted placement,
the wrapper returns a schema-valid terminal action whose observed-plane check
proves it outside the container. Official inclusion rejection ends the episode
before spawning cargo and preserves partial evaluation. This is an explicit
early stop, not a successful placement or evidence that no feasible packing exists.
Unexpected exceptions are not caught by this wrapper.

Local validation, mode-specific comparisons, exact-extraction checks, runtime
measurements, and remaining limitations are recorded in
[the candidate report](../../experiments/submission_candidate/README.md).
No local fill score is a Public score.

Archive SHA-256:
`40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90`.
