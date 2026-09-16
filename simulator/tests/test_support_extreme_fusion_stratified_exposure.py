from __future__ import annotations

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
    LayeredProxyState,
    ProxyExposureOrder,
    ProxyTopologyCache,
    ProxyWork,
    ProxyWorkQuota,
    SupportPatch,
)
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    MemoizedStreamingRegretProxySelector,
)
from agents.support_extreme_fusion_beam_exact_mask.transition import (  # noqa: E402
    apply_root,
)
from tests.test_support_extreme_fusion_memoized_streaming import (  # noqa: E402
    _selector_case,
    _state,
)


def _same_candidates(proxy, first, second):
    return len(first) == len(second) and all(
        proxy._same_candidate(left, right)
        for left, right in zip(first, second)
    )


def _layered_two_container_state():
    proxy, state = _state(pool_size=1)
    base = state.containers[0]

    def supports(ordinal):
        floor = dataclasses.replace(base.supports[0], container_ordinal=ordinal)
        shelf = SupportPatch(
            ordinal,
            float(floor.height + 0.40),
            floor.footprint,
            0.022,
            None,
            "shelf",
        )
        return (floor, shelf)

    first = dataclasses.replace(base, ordinal=0, supports=supports(0))
    second = dataclasses.replace(base, ordinal=1, supports=supports(1))
    return proxy, LayeredProxyState((first, second), state.remaining)


class _RecordingProxy(LayeredProxy):
    def __init__(self, *, accept_later=False):
        super().__init__()
        self.calls = []
        self.accept_later = accept_later

    def _check(
        self,
        state,
        occurrence,
        container_ordinal,
        orientation,
        position,
        anchor,
        patch_index,
    ):
        source = state.containers[container_ordinal].supports[patch_index].source
        self.calls.append((container_ordinal, source, orientation, anchor, position))
        if not self.accept_later or (patch_index == 0 and orientation == 0):
            return None
        return super()._check(
            state,
            occurrence,
            container_ordinal,
            orientation,
            position,
            anchor,
            patch_index,
        )


class _TopologySpyProxy(LayeredProxy):
    def __init__(self):
        super().__init__()
        self.topology_calls = []

    def _topology_rectangles(
        self,
        state,
        container,
        patch,
        blockers,
        limit,
        topology_cache,
    ):
        self.topology_calls.append((patch.source, patch.height))
        return super()._topology_rectangles(
            state,
            container,
            patch,
            blockers,
            limit,
            topology_cache,
        )


class StratifiedLayerOrientationExposureTests(unittest.TestCase):
    def test_unlimited_legacy_and_stratified_have_identical_candidates_children_and_metrics(self):
        proxy, state = _state(pool_size=2)
        quota = ProxyWorkQuota(max_fit_tests=10_000, max_candidates=10_000)
        before = proxy.metrics(state)

        legacy = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            before,
            ProxyTopologyCache(),
            exposure_order=ProxyExposureOrder.LEGACY_NESTED,
        )
        stratified = proxy.preview_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            before,
            ProxyTopologyCache(),
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertTrue(
            _same_candidates(
                proxy,
                tuple(value.candidate for value in legacy.transitions),
                tuple(value.candidate for value in stratified.transitions),
            )
        )
        self.assertEqual(legacy.work, stratified.work)
        self.assertEqual(legacy.attempted_fit_tests, stratified.attempted_fit_tests)
        self.assertEqual(
            tuple(
                (value.child_state.fingerprint, value.child_metrics)
                for value in legacy.transitions
            ),
            tuple(
                (value.child_state.fingerprint, value.child_metrics)
                for value in stratified.transitions
            ),
        )

    def test_unlimited_equivalence_spans_multiple_containers_and_support_layers(self):
        proxy, state = _layered_two_container_state()
        quota = ProxyWorkQuota(max_fit_tests=10_000, max_candidates=10_000)

        legacy = proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            exposure_order=ProxyExposureOrder.LEGACY_NESTED,
        )
        stratified = proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertTrue(_same_candidates(proxy, legacy.candidates, stratified.candidates))
        self.assertEqual(legacy.work, stratified.work)
        self.assertEqual(legacy.attempted_fit_tests, stratified.attempted_fit_tests)

    def test_quantum_eight_stratifies_container_layer_and_orientation(self):
        _proxy, state = _layered_two_container_state()
        proxy = _RecordingProxy()
        batch = proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=8, max_candidates=8),
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertEqual(batch.attempted_fit_tests, 8)
        self.assertEqual(len(proxy.calls), 8)
        self.assertGreaterEqual(len({value[0] for value in proxy.calls}), 2)
        self.assertGreaterEqual(len({value[1] for value in proxy.calls}), 2)
        self.assertGreaterEqual(len({value[2] for value in proxy.calls}), 3)

    def test_quantum_eight_lazily_materializes_only_reached_support_buckets(self):
        _proxy, state = _state(pool_size=1)
        container = state.containers[0]
        placed_tops = tuple(
            SupportPatch(
                container.ordinal,
                0.20 + 0.02 * index,
                container.inner_floor,
                0.0,
                None,
                "placed_top",
            )
            for index in range(20)
        )
        state = LayeredProxyState(
            (dataclasses.replace(container, supports=container.supports + placed_tops),),
            state.remaining,
        )
        proxy = _TopologySpyProxy()

        batch = proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=8, max_candidates=100),
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertEqual(batch.attempted_fit_tests, 8)
        self.assertEqual(len(proxy.topology_calls), 8)
        self.assertNotIn(placed_tops[-1].height, {
            height for _source, height in proxy.topology_calls
        })

    def test_quantum_eight_bounds_topology_probes_when_every_patch_is_undersized(self):
        _proxy, state = _state(pool_size=1)
        container = state.containers[0]
        tiny = dataclasses.replace(
            container.inner_floor,
            min_x=-0.005,
            max_x=0.005,
            min_y=-0.005,
            max_y=0.005,
        )
        undersized = tuple(
            SupportPatch(
                container.ordinal,
                0.20 + 0.02 * index,
                tiny,
                0.0,
                None,
                "placed_top",
            )
            for index in range(20)
        )
        state = LayeredProxyState(
            (dataclasses.replace(container, supports=undersized),),
            state.remaining,
        )
        outputs = []
        for _ in range(20):
            proxy = _TopologySpyProxy()
            batch = proxy.enumerate_candidates(
                state,
                state.remaining[0].key,
                ProxyWork(),
                ProxyWorkQuota(max_fit_tests=8, max_candidates=100),
                exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            )
            outputs.append((batch, tuple(proxy.topology_calls)))

        self.assertTrue(all(value == outputs[0] for value in outputs[1:]))
        batch, topology_calls = outputs[0]
        self.assertEqual(batch.attempted_fit_tests, 0)
        self.assertEqual(batch.candidates, ())
        self.assertLessEqual(len(topology_calls), 8)
        self.assertNotIn(undersized[-1].height, {
            height for _source, height in topology_calls
        })

    def test_empty_first_orientation_cannot_starve_later_fitting_orientation(self):
        _proxy, state = _state(pool_size=1)
        container = state.containers[0]
        orientation_two_only = dataclasses.replace(
            container.inner_floor,
            min_x=-0.07,
            max_x=0.07,
            min_y=-0.09,
            max_y=0.09,
        )
        supports = tuple(
            SupportPatch(
                container.ordinal,
                0.20 + 0.02 * index,
                orientation_two_only,
                0.0,
                None,
                "placed_top",
            )
            for index in range(20)
        )
        state = LayeredProxyState(
            (dataclasses.replace(container, supports=supports),),
            state.remaining,
        )
        proxy = _TopologySpyProxy()

        batch = proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=8, max_candidates=8),
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertLessEqual(len(proxy.topology_calls), 8)
        self.assertTrue(batch.candidates)
        self.assertTrue(any(value.orientation == 2 for value in batch.candidates))

    def test_later_orientation_is_found_when_legacy_spends_quantum_on_invalid_first_bucket(self):
        _base, state = _state(pool_size=1)
        quota = ProxyWorkQuota(max_fit_tests=8, max_candidates=8)
        legacy_proxy = _RecordingProxy(accept_later=True)
        stratified_proxy = _RecordingProxy(accept_later=True)

        legacy = legacy_proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            exposure_order=ProxyExposureOrder.LEGACY_NESTED,
        )
        stratified = stratified_proxy.enumerate_candidates(
            state,
            state.remaining[0].key,
            ProxyWork(),
            quota,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertEqual(len(legacy.candidates), 0)
        self.assertGreaterEqual(len(stratified.candidates), 1)
        self.assertTrue(any(value.orientation != 0 for value in stratified.candidates))
        self.assertEqual(legacy.attempted_fit_tests, 8)
        self.assertEqual(stratified.attempted_fit_tests, 8)

    def test_orientation_dimension_dedupe_is_preserved(self):
        proxy, state = _state(pool_size=1)
        cube = dataclasses.replace(
            state.remaining[0].item,
            length=0.2,
            width=0.2,
            height=0.2,
        )
        occurrence = dataclasses.replace(state.remaining[0], item=cube)
        state = LayeredProxyState(state.containers, (occurrence,))
        recording = _RecordingProxy()

        recording.enumerate_candidates(
            state,
            occurrence.key,
            ProxyWork(),
            ProxyWorkQuota(max_fit_tests=8, max_candidates=8),
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )

        self.assertEqual({value[2] for value in recording.calls}, {0})
        self.assertEqual(len(recording.calls), 8)

    def test_twenty_stratified_runs_have_identical_prefix_and_exact_work(self):
        proxy, state = _state(pool_size=1)
        outputs = []
        for _ in range(20):
            batch = proxy.enumerate_candidates(
                state,
                state.remaining[0].key,
                ProxyWork(),
                ProxyWorkQuota(max_fit_tests=8, max_candidates=8),
                exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            )
            outputs.append(
                (
                    tuple(
                        (
                            value.container_ordinal,
                            value.orientation,
                            value.position,
                            value.anchor,
                        )
                        for value in batch.candidates
                    ),
                    batch.work,
                    batch.attempted_fit_tests,
                )
            )
        self.assertTrue(all(value == outputs[0] for value in outputs[1:]))
        self.assertEqual(outputs[0][2], 8)

    def test_selector_returns_only_original_fresh_root_and_records_exposure(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        selector = MemoizedStreamingRegretProxySelector(
            mask,
            settings=settings,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            max_depth=3,
            max_nodes=64,
            max_fit_tests=256,
            analysis_fit_quantum=64,
            clock=lambda: 0.0,
        )

        ranked = selector.select(sim, catalog, "B", time.perf_counter() + 100.0)

        self.assertTrue(ranked)
        self.assertTrue(
            all(any(root is record.root for record in catalog) for root in ranked)
        )
        placement = apply_root(
            sim,
            ranked[0],
            settings,
            exact_revalidator=mask,
            deadline=time.perf_counter() + 2.0,
        )
        self.assertIsNotNone(placement)
        self.assertTrue(selector.last_trace.exposure_by_support_source)
        self.assertTrue(selector.last_trace.exposure_by_orientation)

    def test_default_and_explicit_legacy_selectors_keep_identical_rank_and_trace(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        kwargs = {
            "settings": settings,
            "max_depth": 3,
            "max_nodes": 64,
            "max_fit_tests": 256,
            "analysis_fit_quantum": 64,
            "clock": lambda: 0.0,
        }
        default = MemoizedStreamingRegretProxySelector(mask, **kwargs)
        explicit = MemoizedStreamingRegretProxySelector(
            mask,
            exposure_order=ProxyExposureOrder.LEGACY_NESTED,
            **kwargs,
        )

        deadline = time.perf_counter() + 100.0
        default_ranked = default.select(sim, catalog, "B", deadline)
        explicit_ranked = explicit.select(sim, catalog, "B", deadline)

        self.assertEqual(len(default_ranked), len(explicit_ranked))
        self.assertTrue(
            all(left is right for left, right in zip(default_ranked, explicit_ranked))
        )
        self.assertEqual(default.last_trace, explicit.last_trace)

    def test_zero_candidate_nodes_are_diagnostic_only_and_root_identity_survives(self):
        settings, mask, sim, catalog = _selector_case(pool_size=2, roots=2)
        rejecting_proxy = _RecordingProxy()
        selector = MemoizedStreamingRegretProxySelector(
            mask,
            settings=settings,
            proxy=rejecting_proxy,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            max_depth=3,
            max_nodes=64,
            max_fit_tests=128,
            analysis_fit_quantum=8,
            clock=lambda: 0.0,
        )

        ranked = selector.select(
            sim, catalog, "B", time.perf_counter() + 100.0
        )

        self.assertTrue(ranked)
        self.assertTrue(
            all(any(root is record.root for record in catalog) for root in ranked)
        )
        self.assertGreater(selector.last_trace.zero_candidate_nodes, 0)
        self.assertEqual(selector.last_trace.candidates, 0)
        self.assertEqual(selector.last_trace.deepest, 1)


if __name__ == "__main__":
    unittest.main()
