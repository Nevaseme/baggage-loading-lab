from __future__ import annotations

import ast
from collections import Counter
import dataclasses
import pathlib
import sys
import time
import unittest


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    LayeredProxy,
    ProxyMetrics,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_order_beam import (  # noqa: E402
    LayeredProxyOrderBeam,
    ModeAOrderBeamSettings,
    ProxyOrderCandidate,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (  # noqa: E402
    SupportKind,
    build_offline_occurrences,
)
from agents.support_extreme_fusion_beam_exact_mask.model import ItemSpec  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import (  # noqa: E402
    build_packing_state,
)
from tests.test_support_extreme_fusion_layered_proxy import (  # noqa: E402
    _container,
    _raw_item,
)
from tests.test_support_extreme_fusion_mode_a_types_seeds import _skeleton  # noqa: E402


def _candidate(occurrences, *, placed_count, placed_volume, complete=None):
    metrics = ProxyMetrics(0.7, 0.8, 0.1, 0.9, 0.8, 0.7, 0.6)
    if complete is None:
        complete = placed_count == len(occurrences)
    skeleton = _skeleton(occurrences)[:placed_count]
    return ProxyOrderCandidate(
        occurrence_order=occurrences,
        skeleton=skeleton,
        placed_count=placed_count,
        placed_volume=float(placed_volume),
        min_alternatives=1 if placed_count else 0,
        support_margin=0.0,
        clearance_margin=0.0,
        metrics=metrics,
        seed_discrepancies=0,
        complete=complete,
        seed_lane=0,
    )


class ModeAOrderBeamContractTests(unittest.TestCase):
    def test_default_fixed_work_contract(self):
        value = ModeAOrderBeamSettings()
        self.assertEqual(value.beam_width, 24)
        self.assertEqual(value.max_nodes, 20_000)
        self.assertEqual(value.max_fit_tests, 250_000)
        self.assertEqual(value.max_checked_transitions, 80_000)
        self.assertEqual(value.max_rectangles_per_patch, 128)
        self.assertEqual(value.max_item_choices, 6)
        self.assertEqual(value.max_placements_per_item, 4)
        self.assertEqual(value.per_preview_fit_quantum, 64)

    def test_three_seed_lanes_are_original_historical_and_volume(self):
        raw = (
            _raw_item(0, length=0.1, width=0.1, height=0.1, mass=1.0),
            _raw_item(1, length=0.2, width=0.2, height=0.2, mass=5.0),
            _raw_item(2, length=0.3, width=0.2, height=0.2, mass=2.0),
        )
        occurrences = build_offline_occurrences(raw)
        beam = LayeredProxyOrderBeam(clock=lambda: 0.0)

        seeds = beam.seed_orders(occurrences, raw)

        self.assertEqual(seeds[0], (0, 1, 2))
        self.assertEqual(seeds[1], (1, 2, 0))
        self.assertEqual(seeds[2], (2, 1, 0))

    def test_choice_union_contains_seed_heads_scarce_special_large_within_six(self):
        raw = (
            _raw_item(0, length=0.10, width=0.11, height=0.12),
            _raw_item(1, length=0.20, width=0.20, height=0.20),  # one orientation
            _raw_item(2, prioritized=True),
            _raw_item(3, soft=True),
            _raw_item(4, length=0.40, width=0.30, height=0.20),
            _raw_item(5),
            _raw_item(6),
        )
        occurrences = build_offline_occurrences(raw)
        beam = LayeredProxyOrderBeam(clock=lambda: 0.0)
        seeds = ((0, 5, 6), (5, 2, 4), (6, 3, 1))

        selected = beam.choice_occurrences(occurrences, raw, seeds)

        self.assertLessEqual(len(selected), 6)
        self.assertTrue({0, 5, 6}.issubset({value.original_position for value in selected}))
        self.assertIn(1, {value.original_position for value in selected})
        self.assertTrue({2, 3} & {value.original_position for value in selected})
        self.assertIn(4, {value.original_position for value in selected})
        self.assertEqual(selected, beam.choice_occurrences(occurrences, raw, seeds))

    def test_orientation_dimension_dedupe_uses_official_six(self):
        beam = LayeredProxyOrderBeam()
        cube = ItemSpec.from_dict(_raw_item(1, length=0.2, width=0.2, height=0.2))
        rectangular = ItemSpec.from_dict(
            _raw_item(2, length=0.3, width=0.2, height=0.1)
        )
        self.assertEqual(beam.orientation_count(cube), 1)
        self.assertEqual(beam.orientation_count(rectangular), 6)

    def test_rank_places_complete_before_higher_volume_partial(self):
        occurrences = build_offline_occurrences((_raw_item(0), _raw_item(1)))
        beam = LayeredProxyOrderBeam()
        complete = _candidate(occurrences, placed_count=2, placed_volume=0.1)
        partial = _candidate(
            occurrences, placed_count=1, placed_volume=100.0, complete=False
        )
        self.assertIs(beam.rank_candidates((partial, complete))[0], complete)

    def test_settings_and_candidates_reject_bool_negative_and_inconsistent_complete(self):
        with self.assertRaises(ValueError):
            ModeAOrderBeamSettings(max_nodes=True)
        occurrences = build_offline_occurrences((_raw_item(0),))
        with self.assertRaises(ValueError):
            _candidate(occurrences, placed_count=0, placed_volume=0.0, complete=True)


class ModeAOrderBeamIntegrationTests(unittest.TestCase):
    def _run(self, raw, *, settings=None, clock=None, deadline=None, container=None):
        occurrences = build_offline_occurrences(raw)
        beam = LayeredProxyOrderBeam(
            settings=settings,
            clock=clock or time.perf_counter,
        )
        result = beam.search(
            build_packing_state([container or _container(shelf=True)]),
            occurrences,
            raw,
            deadline if deadline is not None else time.perf_counter() + 10.0,
        )
        return beam, occurrences, result

    def test_real_small_integration_places_all_and_returns_full_orders_only(self):
        raw = (
            _raw_item(0, length=0.18, width=0.16, height=0.12),
            _raw_item(1, length=0.20, width=0.14, height=0.10),
            _raw_item(2, length=0.12, width=0.12, height=0.12, soft=True),
        )
        beam, occurrences, result = self._run(raw)

        self.assertTrue(result)
        self.assertTrue(result[0].complete)
        self.assertEqual(result[0].placed_count, 3)
        self.assertEqual(len(result[0].skeleton), 3)
        self.assertEqual(
            Counter(value.original_position for value in result[0].occurrence_order),
            Counter(range(3)),
        )
        self.assertLessEqual(beam.last_trace.nodes, beam.settings.max_nodes)
        self.assertLessEqual(beam.last_trace.fit_tests, beam.settings.max_fit_tests)
        self.assertLessEqual(
            beam.last_trace.checked_transitions,
            beam.settings.max_checked_transitions,
        )

    def test_duplicate_occurrences_remain_distinct_in_full_order(self):
        raw = (_raw_item(4), _raw_item(4), _raw_item(4))
        _beam, _occurrences, result = self._run(raw)
        self.assertTrue(result[0].complete)
        self.assertEqual(
            Counter(value.original_position for value in result[0].occurrence_order),
            Counter((0, 1, 2)),
        )

    def test_protection_tags_are_respected_by_checked_proxy_transitions(self):
        raw = (
            _raw_item(0, soft=True, length=0.7, width=0.6, height=0.12),
            _raw_item(1, length=0.2, width=0.2, height=0.12),
        )
        _beam, _occurrences, result = self._run(raw, container=_container(shelf=False))
        for candidate in result:
            for intent in candidate.skeleton:
                if intent.supporter_occurrences:
                    lower = next(
                        value
                        for value in candidate.occurrence_order
                        if value == intent.supporter_occurrences[0]
                    )
                    lower_soft = bool(lower.item_signature[6])
                    upper_soft = bool(intent.occurrence.item_signature[6])
                    self.assertFalse(lower_soft and not upper_soft)

    def test_retention_exposes_seed_support_and_container_lanes(self):
        raw = (_raw_item(0, length=0.2, width=0.2, height=0.2),)
        occurrences = build_offline_occurrences(raw)
        second = _container(shelf=True)
        second["index"] = 18
        beam = LayeredProxyOrderBeam(clock=lambda: 0.0)
        result = beam.search(
            build_packing_state([_container(shelf=True), second]),
            occurrences,
            raw,
            100.0,
        )

        self.assertEqual({value.seed_lane for value in result}, {0, 1, 2})
        self.assertEqual(
            {intent.container_ordinal for value in result for intent in value.skeleton},
            {0, 1},
        )
        self.assertTrue(
            {SupportKind.FLOOR, SupportKind.SHELF}.issubset(
                {intent.support_kind for value in result for intent in value.skeleton}
            )
        )

    def test_actual_incomplete_frontier_retains_seed_support_container_fairness(self):
        raw = (_raw_item(0), _raw_item(1))
        occurrences = build_offline_occurrences(raw)
        second = _container(shelf=True)
        second["index"] = 18
        settings = ModeAOrderBeamSettings(max_nodes=27)
        beam = LayeredProxyOrderBeam(settings=settings, clock=lambda: 0.0)

        result = beam.search(
            build_packing_state([_container(shelf=True), second]),
            occurrences,
            raw,
            100.0,
        )

        self.assertTrue(result)
        self.assertTrue(all(not value.complete for value in result))
        self.assertEqual({value.seed_lane for value in result}, {0, 1, 2})
        self.assertEqual(
            {intent.container_ordinal for value in result for intent in value.skeleton},
            {0, 1},
        )
        self.assertTrue(
            {SupportKind.FLOOR, SupportKind.SHELF}.issubset(
                {intent.support_kind for value in result for intent in value.skeleton}
            )
        )

    def test_branch_exception_isolated_and_cache_is_select_local(self):
        class RecordingProxy(LayeredProxy):
            def __init__(self):
                super().__init__()
                self.preview_calls = 0
                self.cache_ids = set()

            def preview_candidates(self, *args, **kwargs):
                self.preview_calls += 1
                self.cache_ids.add(id(args[5]))
                if self.preview_calls == 1:
                    raise RuntimeError("synthetic isolated branch")
                return super().preview_candidates(*args, **kwargs)

            def commit_transition(self, *args, **kwargs):
                self.cache_ids.add(id(args[2]))
                return super().commit_transition(*args, **kwargs)

        proxy = RecordingProxy()
        raw = (_raw_item(0),)
        occurrences = build_offline_occurrences(raw)
        packing = build_packing_state([_container(shelf=True)])
        before_placed = packing.containers[0].placed
        beam = LayeredProxyOrderBeam(proxy=proxy, clock=lambda: 0.0)

        result = beam.search(packing, occurrences, raw, 100.0)

        self.assertTrue(result)
        self.assertTrue(result[0].complete)
        self.assertGreaterEqual(beam.last_trace.branch_exceptions, 1)
        self.assertEqual(len(proxy.cache_ids), 1)
        self.assertIs(packing.containers[0].placed, before_placed)

    def test_immediate_deadline_does_no_proxy_construction(self):
        class NoConstructionProxy(LayeredProxy):
            def __init__(self):
                super().__init__()
                self.from_calls = 0
                self.metric_calls = 0

            def from_sim_state(self, sim):
                self.from_calls += 1
                return super().from_sim_state(sim)

            def metrics(self, *args, **kwargs):
                self.metric_calls += 1
                return super().metrics(*args, **kwargs)

        raw = (_raw_item(0), _raw_item(1))
        occurrences = build_offline_occurrences(raw)
        now = time.perf_counter()
        proxy = NoConstructionProxy()
        beam = LayeredProxyOrderBeam(proxy=proxy, clock=lambda: now + 1.0)
        result = beam.search(
            build_packing_state([_container(shelf=True)]),
            occurrences,
            raw,
            now,
        )

        self.assertEqual(result, ())
        self.assertEqual(proxy.from_calls, 0)
        self.assertEqual(proxy.metric_calls, 0)
        self.assertTrue(beam.last_trace.deadline_reached)

    def test_preview_fit_delta_and_issued_transitions_are_locally_bounded(self):
        class RecordingProxy(LayeredProxy):
            def __init__(self):
                super().__init__()
                self.rows = []

            def preview_candidates(self, state, key, work, quota, *args, **kwargs):
                batch = super().preview_candidates(
                    state, key, work, quota, *args, **kwargs
                )
                self.rows.append(
                    (
                        quota.max_fit_tests - work.fit_tests,
                        batch.work.fit_tests - work.fit_tests,
                        len(batch.transitions),
                    )
                )
                return batch

        proxy = RecordingProxy()
        settings = ModeAOrderBeamSettings(
            max_nodes=12,
            max_fit_tests=500,
            max_checked_transitions=20,
            per_preview_fit_quantum=32,
        )
        raw = (_raw_item(0, length=0.9, width=0.9, height=0.9),)
        beam = LayeredProxyOrderBeam(proxy=proxy, settings=settings, clock=lambda: 0.0)
        beam.search(
            build_packing_state([_container(shelf=True)]),
            build_offline_occurrences(raw),
            raw,
            100.0,
        )

        self.assertTrue(proxy.rows)
        self.assertTrue(all(limit <= 32 and used <= 32 for limit, used, _ in proxy.rows))
        self.assertTrue(all(issued <= 4 for _, _, issued in proxy.rows))

    def test_choice_scarcity_stops_before_tail_after_deadline(self):
        class ExpiringClock:
            def __init__(self):
                self.calls = 0

            def __call__(self):
                self.calls += 1
                return 0.0 if self.calls < 4 else 10.0

        raw = tuple(_raw_item(index) for index in range(20))
        occurrences = build_offline_occurrences(raw)
        clock = ExpiringClock()
        beam = LayeredProxyOrderBeam(clock=clock)
        engine, proxy_state = self._proxy_state(raw)
        del engine

        selected = beam.choice_occurrences(
            occurrences,
            raw,
            (tuple(range(20)),) * 3,
            proxy_state=proxy_state,
            deadline=5.0,
        )

        self.assertLess(len(selected), 6)
        self.assertLess(clock.calls, 20)

    def test_completed_incumbent_survives_deadline_after_first_commit(self):
        class ToggleClock:
            expired = False

            def __call__(self):
                return 10.0 if self.expired else 0.0

        class ExpiringCommitProxy(LayeredProxy):
            def __init__(self, clock):
                super().__init__()
                self.clock = clock

            def commit_transition(self, *args, **kwargs):
                result = super().commit_transition(*args, **kwargs)
                self.clock.expired = True
                return result

        clock = ToggleClock()
        proxy = ExpiringCommitProxy(clock)
        raw = (_raw_item(0),)
        beam = LayeredProxyOrderBeam(proxy=proxy, clock=clock)
        result = beam.search(
            build_packing_state([_container(shelf=True)]),
            build_offline_occurrences(raw),
            raw,
            5.0,
        )

        self.assertTrue(result)
        self.assertTrue(result[0].complete)
        self.assertTrue(beam.last_trace.deadline_reached)

    def test_tiny_quotas_are_exact_and_preserve_incumbent(self):
        settings = ModeAOrderBeamSettings(
            beam_width=2,
            max_nodes=4,
            max_fit_tests=8,
            max_checked_transitions=4,
            max_rectangles_per_patch=2,
            max_item_choices=2,
            max_placements_per_item=1,
        )
        beam, _occurrences, result = self._run(
            (_raw_item(0), _raw_item(1), _raw_item(2)), settings=settings
        )
        self.assertTrue(result)
        self.assertLessEqual(beam.last_trace.nodes, 4)
        self.assertLessEqual(beam.last_trace.fit_tests, 8)
        self.assertLessEqual(beam.last_trace.checked_transitions, 4)
        self.assertEqual(beam.last_trace.rectangle_limit, 2)

    def test_forty_one_occurrence_deadline_smoke_is_bounded_and_complete_ordered(self):
        raw = tuple(_raw_item(index) for index in range(41))
        now = time.perf_counter()
        beam, occurrences, result = self._run(
            raw, clock=lambda: now + 1.0, deadline=now
        )
        self.assertEqual(result, ())
        self.assertEqual(beam.last_trace.nodes, 0)

    @staticmethod
    def _proxy_state(raw):
        from agents.support_extreme_fusion_beam_exact_mask.transition import SimState

        engine = LayeredProxy()
        state = engine.from_sim_state(
            SimState.from_current(
                build_packing_state([_container(shelf=True)]), raw
            )
        )
        return engine, state

    def test_twenty_runs_are_deterministic(self):
        raw = (_raw_item(0), _raw_item(1))
        settings = ModeAOrderBeamSettings(
            beam_width=4,
            max_nodes=24,
            max_fit_tests=64,
            max_checked_transitions=24,
            max_rectangles_per_patch=8,
            max_item_choices=2,
            max_placements_per_item=1,
        )
        outputs = []
        for _ in range(20):
            beam, _occurrences, result = self._run(
                raw, settings=settings, clock=lambda: 0.0, deadline=100.0
            )
            outputs.append(
                (
                    tuple(value.stable_key for value in result),
                    beam.last_trace,
                )
            )
        self.assertTrue(all(value == outputs[0] for value in outputs[1:]))

    def test_source_has_no_receipt_action_or_historical_search_imports(self):
        path = (
            SIMULATOR_ROOT
            / "agents"
            / "support_extreme_fusion_beam_exact_mask"
            / "mode_a_order_beam.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "").lower())
        self.assertFalse(any("highscore" in value or "mcts" in value or "ems" in value for value in imports))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("ValidatedRoot", names)
        self.assertNotIn("PlacementProposal", names)


if __name__ == "__main__":
    unittest.main()
