# Support recovery: submitted evaluation

The user explicitly associated `result-log.txt` with archive
`40da95f00f099605fd9eeaa9abf211fa70e2b1b4f17a85ebb2b8a14f85a07e90`.
The original result bytes have SHA-256
`205e66528b62bad9d9c8f563236974a6a346305e480c6186d1a8ed71305dcee5`.

| Reported component | Value |
| --- | ---: |
| Fill | 33.96645688180599 |
| CoG | 32.483576512195285 |
| Stability | 38.02599992053441 |
| Placement | 20.2 |
| Soft items | 14.85 |
| Placed-item ratio | 0.46453610097631837 |
| Optimization time | 47.459679456 s |
| Policy time | 6.14273356800004 s |

Status: stopped in the middle; inclusion, validity, and safe-placement predicates
were not all satisfied. The log contains no Public aggregate score, per-mode
breakdown, scene count, item denominator, or first-failure trace. Do not infer any
of these from component scores or the aggregate ratio.

The result is consistent with the candidate's known tendency to terminate early,
but the aggregate status cannot distinguish explicit terminal rejection from an
unexpected physical failure. The eight local episodes establish local execution
and selected gains, not completion on the submitted evaluation distribution.

Next development should target the first unresolved packing state and improve
completed packing across matched modes. Increasing search caps alone or treating
normal execution status as successful packing is not supported by this evidence.
Result intake does not itself resume algorithm development.

- [Submission bundle](../../deliverables/2026-09-16-support-recovery-packing/README.md)
- [Local comparisons and rejected ideas](../../experiments/submission_candidate/README.md)
- [Machine-readable record](record.json); [original bytes](raw/result.json)
