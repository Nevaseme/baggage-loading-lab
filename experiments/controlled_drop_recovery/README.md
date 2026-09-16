# Controlled release-height recovery

**Decision: reject the current controller.** The [full B replay](results/drop-b-task001-seed42.json)
packs 22/42 safely, then the raised action moves about 0.38 m and fails settling.
Local fill is 24.1459, below progressive recovery's 25.4502 at the same safe count.
The preview predicted only 0.2542 m. [Velocity calibration](../finite_mesh_preview/README.md)
identifies continuing motion of existing cargo as a material omitted input.
Snapshot acceptance below is diagnostic evidence, not a successful recovery.

The historical candidate generator places a new target about 6 mm above a packed
support. The official process permits up to 0.30 m displacement while settling.
This experiment preserves a supported landing footprint, raises its requested
release center by 0.06/0.12/0.18/0.24 m, and independently checks native inclusion,
target clearance, sampled transport, and all 300 settling steps at the raised
action. No immediate-support requirement is imposed on the raised release pose.

`probe.py` uses the frozen observation-only progressive-recovery modules; it does
not import official simulator source or run episodes. Records include exact
dependency/state/probe hashes. Timings in these runs are marked contended because
root benchmark runs could overlap.

## Findings

- **Historical 23-placement B stop:** all 176 raised actions (44 supported roots
  times four release heights) still failed transport; 83 also failed inclusion.
  No recovery was found in this bounded candidate set.
- **Native 20-placement B stop, exploratory run:** one +0.06 m action completed
  safely, but predicted 0.073125 cubic meters of previously counted volume lost.
  That first exploratory record did not compare the unraised route, so it does
  not establish restored-ingress benefit and is not the selected recovery.
- **Progressive 22-placement B stop:** raising a blocked target by 0.06 m restored
  Y ingress. Its full preview passed with no loss of previously counted volume.

Selected progressive-22 action:

| Property | Value |
| --- | --- |
| Pool ordinal / container / orientation | 7 / 0 / 0 |
| Original landing center | `[-0.014328156, -0.435688496, 1.084738374]` |
| Raised local action center | `[-0.014328156, -0.435688496, 1.144738317]` |
| Landing support | Cargo 17, predicted support ratio 1.0 |
| Unraised native checks | Included, target-clear, Y transport blocked |
| Raised native checks | Included, target-clear, transport clear |
| Full settling preview | 300 steps, 0.254248 m displacement, 11.8385-degree rotation |
| Previously counted volume lost | 0 |

The standalone probe took 3.988 seconds, including candidate generation, 120
raised native queries, and a 2.014-second full preview. Thirty unique supported
roots yielded 31 native-valid raised actions; the first full preview succeeded.
The displacement is only about 46 mm below the official limit, and the preview
starts observed packed bodies at zero velocity, so full physical replay is the
next deciding check.

Evidence: `raised-targets-initial.json` and
`progressive22-raised-targets.json`. Reproduce the selected probe from simulator:

```text
.venv_wsl/bin/python ../experiments/controlled_drop_recovery/probe.py --only progressive22 --require-no-volume-loss --output <fresh-output.json>
```

## Integrated controller

`source/` is a separate self-contained package copied from the frozen progressive
controller. Earlier packages are unchanged. Its first-choice narrow/wide stages
are preserved. If they fail, the controller reuses this call's generated roots
and recorded native failures, tries the four raised release heights, and then
revisits deferred failed-support targets only if time remains. All stages share
the 5.2-second deadline and 96-query budget. Actual raised poses receive fresh
native checks and full previews; landing identities are retained for diagnostics
and support deferral.

`test_policy.py`: 2/2 passed in 7.355 seconds. The progressive-22 snapshot recovers
with complete native/preview checks inside 5.2 seconds, and three matched nominal
early observations return the exact unchanged progressive actions.

`policy-freeze.json` records final source/state hashes. On the same snapshot,
control stops after 30 rejected native queries in 1.915 seconds; the integrated
controller returns the +0.06 m action after 45 queries in 3.318 seconds. Its
preview reports no lost previously counted volume, but one prior item moves
0.321 m. This remaining layout change and the new item's small displacement
headroom require full physical replay before promotion.
