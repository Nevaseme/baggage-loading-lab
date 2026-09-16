# Review package: two-choice root search

## Production changes

- `settings.py`: add `online_root_item_choices: int = 2`; change `policy_soft_limit_seconds` from `1.0` to `1.8`; hard limit stays `5.75`.
- `planner.py`: name the depth loop; use exactly `online_root_item_choices` at depth zero and the existing six-item cap below it; enumerate root choices; give each root choice `now + (deadline - now) / remaining_choices`; deeper choices keep the global deadline.

## Test changes

- Add fake-clock test `test_online_root_search_tries_two_items_when_first_uses_its_budget`.
- Fake generator consumes each supplied deadline, returns no candidate first and a valid candidate second.
- Expected calls are root pool indices 0 then 1 with deadlines 0.9 then 1.8, and the second candidate must be returned.

## Evidence

See `docs/superpowers/plans/2026-08-13-two-choice-root-search-report.md` for RED/GREEN outputs and concerns.
