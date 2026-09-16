# Progressive recovery checkpoint

Frozen package: `../variants/progressive_recovery/`.

The original historical B failure was retested with complete basin retention.
The first 1.5-second search reached only 111 candidate checks and cannot establish
absence of a recovery. A second 3-second search completed all 6,500 checks across
57 combinations in 2.024 seconds; all 44 shortlisted exact transport checks
failed. No recovery was demonstrated for that historical 23-placement state.
Both attempts are preserved in `historical-wide-support-recovery*.json`.

The progressive variant instead preserves the stronger narrow-native trajectory
while adding recovery:

1. Generate each candidate once and maintain both the exact original narrow
   score-trimmed list (trim to 96 whenever its size exceeds 192) and all bounded
   candidate roots.
2. Apply the original physical-duplicate and basin ordering to each list.
3. Try the narrow stage first. Expand to the wide stage only after its candidates
   fail current native geometry or the full settling preview.
4. Share a single policy deadline and failed-support memory between stages.
   Defer candidates resting on a supporter whose complete preview failed;
   revisit them only after other support choices have been tried.

Defaults: preview enabled, 3-second candidate-search allowance, 5.2-second shared
policy deadline, 6,500 generated candidate checks, 96 native checks. The candidate
search remains capped at policy-deadline minus 1.5 seconds. No partial preview is
accepted, and every returned action passes native inclusion, target separation,
and sampled insertion.

## Evidence

`test_progressive_recovery.py`: 2/2 passed in 7.188 seconds.

- On three matched nominal observations beginning with empty containers, the
  progressive policy returned exactly the original narrow policy's item,
  container, orientation, and float32 center; each completed its stable preview.
  These are focused decision regressions, not a replay of the original physical
  episode or a claim that the full 20-action prefix is preserved.
- On the original narrow-native 20-placement failure snapshot, progressive
  recovery returned an exact-valid action from its wide stage and completed all
  300 preview steps within 5.2 seconds.

`progressive-recovery-freeze.json` records source/state hashes and a matched
snapshot comparison:

| Policy | Outcome | Policy time | Native checks |
| --- | --- | ---: | ---: |
| Original narrow native | NoValidAction | 1.251 s | 26, all transport-rejected |
| Progressive recovery | Wide-stage action | 2.829 s | 28 |

The recovered action uses pool 0, container 0, orientation 3, and local center
`[0.738861978, -0.339334041, 1.156664848]`, supported by observed cargo 23. Its
300-step preview predicts 0.05763 m displacement, 1.0624-degree rotation, and no
loss of previously counted volume.

Decision: run a full matched B episode. If successful, repeat the earlier
backfill-weight-8 ablation: its 13-placement stop was independently shown to be
shortlist loss with a preview-safe omitted root, so that earlier outcome does
not settle the ranking hypothesis after coverage is repaired.

Physical completion and Public improvement remain unverified at this checkpoint.
Packed velocities are unavailable to the observation-only preview, which starts
them at rest; full episodes remain the deciding evidence.
