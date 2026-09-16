from __future__ import annotations

import dataclasses
import pathlib
from types import SimpleNamespace
import sys
import time
import unittest


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    CheckedProxyCandidateBatch,
    LayeredProxy,
    ProxyExposureOrder,
    ProxyTopologyCache,
    ProxyWork,
    ProxyWorkQuota,
)
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    ContinuationAudit,
    MemoizedStreamingRegretProxySelector,
    RankObjective,
    _RolloutNode,
)
from agents.support_extreme_fusion_beam_exact_mask.transition import (  # noqa: E402
    apply_root,
)
from tests.test_support_extreme_fusion_memoized_streaming import (  # noqa: E402
    _selector_case,
    _state,
)


def _audit(
    total: int,
    option: int,
    *,
    volume: float = 0.0,
    zero: int | None = None,
    minimum: int = 1,
    complete: bool = True,
) -> ContinuationAudit:
    zero_count = total - option if zero is None else zero
    audited = total if complete else option + zero_count
    return ContinuationAudit(
        total_occurrences=total,
        audited_occurrences=audited,
        option_occurrences=option,
        option_volume=float(volume),
        zero_option_occurrences=zero_count,
        minimum_options_all=minimum,
        complete=complete,
    )


def _rank_fixture():
    settings, mask, _sim, catalog = _selector_case(pool_size=3, roots=1)
    proxy, proxy_state = _state(pool_size=2)
    node = _RolloutNode(
        proxy_state=proxy_state,
        first_root=catalog.records[0].root,
        root_key=catalog.records[0].stable_key,
        lineage_id=0,
        depth=1,
        placed_count=1,
        placed_volume=0.10,
        metrics=proxy.metrics(proxy_state),
        remaining_fit_count=0,
        remaining_fit_volume=0.0,
        minimum_nonzero_options=0,
        cumulative_backness=0.5,
        stable_sequence_key=((0,),),
    )
    return settings, mask, node


class _CountPreviewProxy(LayeredProxy):
    def __init__(self, counts, errors=()):
        super().__init__()
        self.counts = dict(counts)
        self.errors = set(errors)

    def preview_candidates(self, state, key, work, quota, before, cache, **kwargs):
        position = key.original_position
        if position in self.errors:
            raise RuntimeError(f"unknown occurrence {position}")
        batch = super().preview_candidates(
            state, key, work, quota, before, cache, **kwargs
        )
        count = self.counts.get(position, len(batch.transitions))
        return CheckedProxyCandidateBatch(
            batch.transitions[:count], batch.work, batch.attempted_fit_tests
        )


def _analysis_fixture(proxy, *, max_fit_tests=256):
    settings, mask, sim, catalog = _selector_case(pool_size=4, roots=1)
    selector = MemoizedStreamingRegretProxySelector(
        mask,
        settings=settings,
        proxy=proxy,
        exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
        max_fit_tests=max_fit_tests,
        clock=lambda: 0.0,
    )
    placement = apply_root(
        sim,
        catalog.records[0].root,
        settings,
        exact_revalidator=mask,
        deadline=time.perf_counter() + 10.0,
    )
    proxy_state = proxy.from_sim_state(placement.child)
    node = _RolloutNode(
        proxy_state=proxy_state,
        first_root=catalog.records[0].root,
        root_key=catalog.records[0].stable_key,
        lineage_id=0,
        depth=1,
        placed_count=1,
        placed_volume=float(sim.pool[0].volume),
        metrics=proxy.metrics(proxy_state),
        remaining_fit_count=0,
        remaining_fit_volume=0.0,
        minimum_nonzero_options=0,
        cumulative_backness=0.5,
        stable_sequence_key=(catalog.records[0].stable_key,),
    )
    result = selector._analyze_checked(
        node,
        ProxyWork(nodes=1),
        time.perf_counter() + 100.0,
        ProxyWorkQuota(max_fit_tests=max_fit_tests, max_candidates=max_fit_tests),
        ProxyTopologyCache(),
    )
    return selector, result


class ContinuationAuditTests(unittest.TestCase):
    def test_audit_counts_three_zero_two_including_zero_option_occurrence(self):
        _selector, result = _analysis_fixture(
            _CountPreviewProxy({1: 3, 2: 0, 3: 2})
        )
        updated, plans = result[0], result[1]

        self.assertEqual(
            updated.continuation_audit,
            ContinuationAudit(
                total_occurrences=3,
                audited_occurrences=3,
                option_occurrences=2,
                option_volume=sum(plan.occurrence.item.volume for plan in plans),
                zero_option_occurrences=1,
                minimum_options_all=0,
                complete=True,
            ),
        )
        self.assertEqual(
            sorted(plan.feasible_count for plan in plans), [2, 3]
        )

    def test_exception_is_unknown_not_zero_and_makes_audit_incomplete(self):
        _selector, result = _analysis_fixture(
            _CountPreviewProxy({1: 0, 3: 2}, errors={2})
        )
        audit = result[0].continuation_audit

        self.assertEqual(audit.total_occurrences, 3)
        self.assertEqual(audit.audited_occurrences, 2)
        self.assertEqual(audit.option_occurrences, 1)
        self.assertEqual(audit.zero_option_occurrences, 1)
        self.assertFalse(audit.complete)
        self.assertEqual(result[3], 1)

    def test_quota_stop_is_unknown_not_zero(self):
        _selector, result = _analysis_fixture(
            _CountPreviewProxy({1: 3, 2: 0, 3: 0}), max_fit_tests=8
        )
        audit = result[0].continuation_audit

        self.assertEqual(audit.total_occurrences, 3)
        self.assertEqual(audit.audited_occurrences, 1)
        self.assertEqual(audit.option_occurrences, 1)
        self.assertEqual(audit.zero_option_occurrences, 0)
        self.assertFalse(audit.complete)


class ContinuationSurvivalRankTests(unittest.TestCase):
    def test_shallower_higher_survival_beats_deeper_low_recall_only_in_new_objective(self):
        settings, mask, base = _rank_fixture()
        shallow = dataclasses.replace(
            base,
            placed_count=1,
            placed_volume=0.10,
            continuation_audit=_audit(3, 3, volume=0.30, minimum=1),
            stable_sequence_key=((1,),),
        )
        deep = dataclasses.replace(
            base,
            placed_count=2,
            placed_volume=0.20,
            continuation_audit=_audit(2, 0, volume=0.0, minimum=0),
            stable_sequence_key=((0,),),
        )
        legacy = MemoizedStreamingRegretProxySelector(
            mask, settings=settings, rank_objective=RankObjective.LEGACY
        )
        survival = MemoizedStreamingRegretProxySelector(
            mask,
            settings=settings,
            rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
        )

        self.assertIs(legacy._ordered((shallow, deep))[0], deep)
        self.assertIs(survival._ordered((shallow, deep))[0], shallow)

    def test_minimum_options_saturates_at_two_and_terminal_has_robustness_two(self):
        settings, mask, base = _rank_fixture()
        selector = MemoizedStreamingRegretProxySelector(
            mask,
            settings=settings,
            rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
        )
        two = dataclasses.replace(
            base, continuation_audit=_audit(2, 2, minimum=2)
        )
        three = dataclasses.replace(
            base, continuation_audit=_audit(2, 2, minimum=3)
        )
        terminal = dataclasses.replace(
            base, continuation_audit=_audit(0, 0, minimum=0)
        )

        self.assertEqual(selector._rank(two)[1], 2.0)
        self.assertEqual(selector._rank(three)[1], 2.0)
        self.assertEqual(selector._rank(terminal)[1], 2.0)

    def test_exact_survival_rank_prefix_counts_volume_once_per_occurrence(self):
        settings, mask, base = _rank_fixture()
        selector = MemoizedStreamingRegretProxySelector(
            mask,
            settings=settings,
            rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
        )
        node = dataclasses.replace(
            base,
            placed_count=2,
            placed_volume=0.25,
            continuation_audit=_audit(3, 2, volume=0.40, minimum=0),
        )

        self.assertEqual(selector._rank(node)[:5], (4.0, 0.0, 0.65, 2.0, 0.25))


class CertifiedCohortTests(unittest.TestCase):
    class _ScriptedSelector(MemoizedStreamingRegretProxySelector):
        reverse_analysis = False

        def _fair_node_order(self, nodes):
            ordered = super()._fair_node_order(nodes)
            return tuple(reversed(ordered)) if self.reverse_analysis else ordered

        def _analyze_checked(self, node, work, deadline, local_quota, cache):
            del deadline, local_quota, cache
            total = len(node.proxy_state.remaining)
            options = min(total, node.lineage_id + 1)
            updated = dataclasses.replace(
                node,
                continuation_audit=_audit(
                    total,
                    options,
                    volume=sum(
                        value.item.volume
                        for value in node.proxy_state.remaining[:options]
                    ),
                    minimum=1 if options else 0,
                ),
            )
            occurrence = node.proxy_state.remaining[0]
            plan = SimpleNamespace(occurrence=occurrence, choices=(object(),))
            return updated, (plan,), work, 0, 0, (), False

        def _commit_checked_child(self, parent, choice, occurrence, work, cache):
            del choice, cache
            child = dataclasses.replace(
                parent,
                depth=parent.depth + 1,
                placed_count=parent.placed_count + 1,
                placed_volume=parent.placed_volume + occurrence.item.volume,
                continuation_audit=None,
                stable_sequence_key=parent.stable_sequence_key + (("child",),),
            )
            return child, work.consume_node(self.proxy_quota), False

    def test_unanalysed_committed_child_cannot_replace_closed_parent_cohort(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        kwargs = dict(
            settings=settings,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            max_depth=2,
            max_nodes=32,
            clock=lambda: 0.0,
        )
        legacy = self._ScriptedSelector(
            mask, rank_objective=RankObjective.LEGACY, **kwargs
        )
        survival = self._ScriptedSelector(
            mask,
            rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
            **kwargs,
        )
        deadline = time.perf_counter() + 100.0

        legacy_ranked = legacy.select(sim, catalog, "B", deadline)
        survival_ranked = survival.select(sim, catalog, "B", deadline)

        self.assertIs(legacy_ranked[0], catalog.records[0].root)
        self.assertIs(survival_ranked[0], catalog.records[1].root)
        self.assertEqual(legacy.last_trace.committed_children, 2)
        self.assertEqual(survival.last_trace.committed_children, 2)
        self.assertEqual(survival.last_trace.predicted_count, 1)

    def test_partial_cohort_never_changes_incumbent_and_is_order_invariant(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        hard_deadline = time.perf_counter() + 100.0

        class PartialClock:
            armed = False
            expired = False

            def __call__(self):
                if self.armed:
                    self.armed = False
                    self.expired = True
                    return 0.0
                return hard_deadline + 1.0 if self.expired else 0.0

        outputs = []
        for reverse in (False, True):
            clock = PartialClock()

            class PartialSelector(self._ScriptedSelector):
                reverse_analysis = reverse

                def _analyze_checked(inner_self, *args, **kwargs):
                    result = super(PartialSelector, inner_self)._analyze_checked(
                        *args, **kwargs
                    )
                    clock.armed = True
                    return result

            selector = PartialSelector(
                mask,
                settings=settings,
                rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
                exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
                max_depth=2,
                clock=clock,
            )
            ranked = selector.select(sim, catalog, "B", hard_deadline)
            outputs.append(ranked[0])
            self.assertTrue(selector.last_trace.deadline_reached)

        self.assertIs(outputs[0], catalog.records[0].root)
        self.assertIs(outputs[1], catalog.records[0].root)


class ObjectiveCompatibilityTests(unittest.TestCase):
    def test_default_and_explicit_legacy_are_bit_equivalent(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        kwargs = dict(
            settings=settings,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            max_depth=3,
            max_nodes=64,
            max_fit_tests=256,
            analysis_fit_quantum=64,
            clock=lambda: 0.0,
        )
        default = MemoizedStreamingRegretProxySelector(mask, **kwargs)
        explicit = MemoizedStreamingRegretProxySelector(
            mask, rank_objective=RankObjective.LEGACY, **kwargs
        )
        deadline = time.perf_counter() + 100.0

        first = default.select(sim, catalog, "B", deadline)
        second = explicit.select(sim, catalog, "B", deadline)

        self.assertEqual(tuple(id(value) for value in first), tuple(id(value) for value in second))
        self.assertEqual(default.last_trace, explicit.last_trace)

    def test_objectives_share_depth_zero_and_candidate_work_before_rank(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        kwargs = dict(
            settings=settings,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
            max_depth=2,
            max_nodes=64,
            max_fit_tests=256,
            analysis_fit_quantum=64,
            clock=lambda: 0.0,
        )
        legacy = MemoizedStreamingRegretProxySelector(
            mask, rank_objective=RankObjective.LEGACY, **kwargs
        )
        survival = MemoizedStreamingRegretProxySelector(
            mask,
            rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
            **kwargs,
        )
        deadline = time.perf_counter() + 100.0

        legacy.select(sim, catalog, "B", deadline)
        ranked = survival.select(sim, catalog, "B", deadline)

        self.assertEqual(legacy.last_trace.root_lineages, survival.last_trace.root_lineages)
        self.assertEqual(legacy.last_trace.fit_tests, survival.last_trace.fit_tests)
        self.assertEqual(legacy.last_trace.candidates, survival.last_trace.candidates)
        self.assertEqual(
            legacy.last_trace.exposure_by_support_source,
            survival.last_trace.exposure_by_support_source,
        )
        self.assertEqual(
            legacy.last_trace.exposure_by_orientation,
            survival.last_trace.exposure_by_orientation,
        )
        self.assertTrue(all(any(root is record.root for record in catalog) for root in ranked))
        placement = apply_root(
            sim,
            ranked[0],
            settings,
            exact_revalidator=mask,
            deadline=time.perf_counter() + 10.0,
        )
        self.assertIsNotNone(placement)

    def test_twenty_survival_runs_are_deterministic_and_quota_bounded(self):
        settings, mask, sim, catalog = _selector_case(pool_size=3, roots=2)
        outputs = []
        for _ in range(20):
            selector = MemoizedStreamingRegretProxySelector(
                mask,
                settings=settings,
                exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
                rank_objective=RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
                max_depth=3,
                max_nodes=64,
                max_fit_tests=256,
                analysis_fit_quantum=64,
                clock=lambda: 0.0,
            )
            ranked = selector.select(
                sim, catalog, "B", time.perf_counter() + 100.0
            )
            outputs.append((tuple(id(root) for root in ranked), selector.last_trace))

        self.assertTrue(all(value == outputs[0] for value in outputs[1:]))
        trace = outputs[0][1]
        self.assertLessEqual(trace.nodes, 64)
        self.assertLessEqual(trace.fit_tests, 256)
        self.assertLessEqual(trace.candidates, 256)


if __name__ == "__main__":
    unittest.main()
