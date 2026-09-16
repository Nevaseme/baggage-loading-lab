# Native search and progressive recovery

2026-09-16. Native PyBullet queries replace the historical transport approximation. Bounded candidate search and complete settling previews recover from rejected actions. Packages are self-contained; official simulator code is not bundled.

## Current result

The strongest mode-C variant is `variants/progressive_recovery/` with `settings/historical_prefix_queries384.json`. It preserves historical actions while they pass current-state validation and preview, then searches alternative support locations. The 384-query setting removes a premature query stop while retaining the shared 5.2-second policy budget.

| Mode C condition | Historical safe / fill | Successor safe / fill |
| --- | ---: | ---: |
| Task001, original stream | 18/42 / 17.8524 | 23/42 / 25.1853 |
| Task001, shuffle17 | 16/42 / 17.9710 | 16/42 / 17.9710 |
| Two offset containers, original stream | 42/42 / 21.7880 | 42/42 / 21.7880 |

The single-container original-stream successor's policy maximum is 4.044 seconds. Both single-container successor runs end in candidate exhaustion. Both controllers complete the two-container case; the successor's policy maximum is 3.322 seconds. Across these three pairs, the successor improves one and ties two, with higher runtime. See [all episode results](RESULTS.md) for exact records and source/settings hashes. Public performance remains unverified.

## Design decisions

- Native/reference checks agree on saved real actions. At exactly 15 mm, the native floating-point query follows the official implementation.
- Fair allocation alone changes the trajectory unfavorably. Early score trimming also deletes useful support locations: [saved-state probes](probes/shortlist-findings.md) demonstrate recoveries after retaining them.
- Progressive recovery tries the original narrow selection first, then a wider spatial selection. After an unstable preview, it tries other supporting items before spending the remaining budget on variants of the same failed support.
- Mode B reaches 22/42 and fill 25.4502 versus 23/42 and 21.0705 for the historical control: a fill/count tradeoff. Native mode A and rear-first ranking regress; neither replaces the corresponding control.
- Wider selection at the final C23 state still rejects every tested route ([probe](probes/c23-wide-selection.json)). More queries alone do not solve it.

Every returned action receives fresh inclusion, target-clearance, transport, and complete-preview checks. Preview is an estimate: [controlled drops](../controlled_drop_recovery/README.md) exposed a false-safe prediction caused partly by continuing cargo motion.

The next substantial change should preserve future ingress or estimate that motion from observation/action history. Repeating larger fixed search caps has not justified its cost. Compare a successor against this mode-C variant and the historical A/B controls before promotion.
