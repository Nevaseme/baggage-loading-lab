# Review package: root fair search

## Production diff

File: `simulator/agents/highscore/planner.py`

```diff
-        for _ in range(max_depth):
+        for depth in range(max_depth):
             expanded: list[_BeamNode] = []
             for node in beam:
                 if time.perf_counter() >= deadline:
                     break
                 item_choices = self._rank_items(node.remaining, node.state, min(6, len(node.remaining)))
-                for pool_index, item in item_choices:
+                for choice_offset, (pool_index, item) in enumerate(item_choices):
                     if time.perf_counter() >= deadline:
                         break
+                    item_deadline = deadline
+                    if depth == 0:
+                        remaining_choices = len(item_choices) - choice_offset
+                        now = time.perf_counter()
+                        item_deadline = now + max(0.0, deadline - now) / max(1, remaining_choices)
                     candidates = self._top_candidates(
                         node.state,
                         item,
                         pool_index,
                         self.settings.candidates_per_item,
-                        deadline,
+                        item_deadline,
                     )
```

## Test diff summary

File: `simulator/tests/test_highscore_planner.py`

- Added `unittest.mock.patch` and `AABB`, `Candidate` imports.
- Added `PlannerTests.test_online_planner_fairly_checks_all_ranked_root_items`.
- The fake candidate generator advances a patched monotonic clock to each supplied item deadline, returns no candidate for the first five root attempts, and returns one valid candidate for the sixth.
- Assertions require six distinct root attempts and the sixth candidate to be returned.

## Evidence

See `docs/superpowers/plans/2026-08-13-root-fair-search-report.md` for the observed RED and GREEN outputs.
