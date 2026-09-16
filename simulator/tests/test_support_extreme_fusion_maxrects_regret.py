from __future__ import annotations

import ast
from dataclasses import dataclass
import pathlib
import sys
import time
import unittest

from types import SimpleNamespace


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogStats,
    RootCatalog,
    RootRecord,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    OccurrenceKey,
    ProxyCandidateBatch,
    ProxyMetrics,
    ProxyOccurrence,
    ProxyWork,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    RegretProxySelector,
    SelectionTrace,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PlacementProposal,
    Rect,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (  # noqa: E402
    ProposalProvenance,
    ProposalSource,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState  # noqa: E402
from tests.replay_support import load_observation_snapshot  # noqa: E402


def _container(index: int = 0) -> dict:
    length, width, height, thickness = 4.0, 2.0, 2.0, 0.04
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (0.0, 0.0, height / 2.0),
        "points": [
            [length / 2.0 - thickness, 0.0, 0.0],
            [-length / 2.0 + thickness, 0.0, 0.0],
            [0.0, width / 2.0 - thickness, 0.0],
            [0.0, -width / 2.0 + thickness, 0.0],
            [0.0, 0.0, height - thickness],
            [0.0, 0.0, thickness],
        ],
        "n_vecs": [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        "volume": length * width * height,
        "shelf": False,
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int, side: float = 0.12) -> ItemSpec:
    return ItemSpec(index=index, length=side, width=side, height=side, mass=2.0)


def _catalog(state, pool, mask, specs) -> RootCatalog:
    records = []
    for raw_ordinal, (pool_index, container, orientation, serial) in enumerate(specs):
        item = pool[pool_index]
        x = -1.65 + 0.10 * (pool_index % 25) + 0.02 * serial
        y = 0.70 - 0.24 * serial
        proposal = PlacementProposal(
            item_index=item.index,
            pool_index=pool_index,
            container_index=container,
            orientation=orientation,
            position=(x, y, 0.048 + item.height / 2.0),
            source=ProposalSource.FREE_RECTANGLE_BOUNDARY.value,
        )
        root = mask.validate(state, pool, proposal, deadline=time.perf_counter() + 30.0)
        if root is None:
            raise AssertionError(f"fixture proposal was rejected: {proposal}")
        records.append(
            RootRecord(
                root,
                ProposalProvenance((proposal.source,), ("floor",), (0.04,)),
                "normal",
                raw_ordinal,
            )
        )
    counts = tuple(sum(record.pool_index == index for record in records) for index in range(len(pool)))
    return RootCatalog(
        tuple(records),
        CatalogStats(
            accepted_roots=len(records),
            normal_roots=len(records),
            per_pool_roots=counts,
        ),
    )


@dataclass(frozen=True)
class _FakeState:
    remaining: tuple[ProxyOccurrence, ...]
    path: tuple[tuple[int, int], ...]
    containers: tuple
    fingerprint: str


class _FakeProxy:
    def __init__(self, original_pool, tree=None, metric_values=None):
        self.original_pool = tuple(original_pool)
        self.tree = tree or {}
        self.metric_values = metric_values or {}
        self.enumerated = []
        self.applied = []

    @staticmethod
    def _placed(path):
        return tuple(position for position, _serial in path)

    def from_sim_state(self, sim):
        remaining_positions = tuple(sim.original_pool_positions)
        placed = tuple(
            position for position in range(len(self.original_pool))
            if position not in remaining_positions
        )
        remaining = tuple(
            ProxyOccurrence(OccurrenceKey(position, sim.pool[index].index), sim.pool[index])
            for index, position in enumerate(remaining_positions)
        )
        floor = Rect(-2.0, 2.0, -1.0, 1.0)
        container = SimpleNamespace(inner_floor=floor)
        path = tuple((position, 0) for position in placed)
        return _FakeState(remaining, path, (container,), repr((path, remaining_positions)))

    def enumerate_candidates(self, state, key, work, quota):
        placed = self._placed(state.path)
        count = int(self.tree.get(placed, {}).get(key.original_position, 0))
        self.enumerated.append((placed, key.original_position))
        candidates = []
        current = work
        for serial in range(count):
            if current.fit_tests >= quota.max_fit_tests or current.candidates >= quota.max_candidates:
                break
            current = current.consume_fit(quota).consume_candidate(quota)
            candidates.append(
                SimpleNamespace(
                    occurrence=key,
                    item_index=key.item_index,
                    container_ordinal=0,
                    orientation=0,
                    position=(0.0, 0.8 - 0.1 * serial, 0.20),
                    box=AABB.from_center_half((0.0, 0.8 - 0.1 * serial, 0.20), (0.05, 0.05, 0.05)),
                    anchor=f"fake-{serial}",
                    support_ratio=1.0,
                    min_clearance=1.0,
                    support_source="floor",
                    state_fingerprint=state.fingerprint,
                    serial=serial,
                )
            )
        return ProxyCandidateBatch(tuple(candidates), current, current.fit_tests - work.fit_tests)

    def apply(self, state, candidate):
        self.applied.append((self._placed(state.path), candidate.occurrence.original_position))
        remaining = tuple(value for value in state.remaining if value.key != candidate.occurrence)
        path = state.path + ((candidate.occurrence.original_position, candidate.serial),)
        return _FakeState(remaining, path, state.containers, repr(path))

    def metrics(self, state):
        values = self.metric_values.get(state.path, {})
        return ProxyMetrics(
            ingress_access=float(values.get("ingress", 0.8)),
            largest_free_region=float(values.get("largest", 0.8)),
            sliver_area=float(values.get("sliver", 0.1)),
            low_mass_cog_goodness=float(values.get("cog", 0.8)),
            low_stack=float(values.get("stack", 0.8)),
            compatible_support_capacity=float(values.get("support", 0.8)),
            protection_compatible_capacity=float(values.get("protection", 0.8)),
        )


class _CountingMask(ExactMask):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = []

    def validate(self, state, pool, proposal, *, deadline=None):
        self.calls.append((proposal.pool_index, proposal.container_index, proposal.orientation))
        return super().validate(state, pool, proposal, deadline=deadline)


class _StepClock:
    def __init__(self, base, live_calls):
        self.base = float(base)
        self.live_calls = int(live_calls)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.base if self.calls <= self.live_calls else self.base + 100.0


class _ToggleClock:
    def __init__(self):
        self.base = time.perf_counter()
        self.expired = False

    def __call__(self):
        return self.base + (100.0 if self.expired else 0.0)


class RegretProxySelectorTests(unittest.TestCase):
    def setUp(self):
        self.settings = SearchSettings()
        self.mask = ExactMask(self.settings)
        self.state = build_packing_state([_container()])

    def _case(self, items, specs, *, proxy=None, **kwargs):
        pool = tuple(items)
        catalog = _catalog(self.state, pool, self.mask, specs)
        sim = SimState.from_current(self.state, pool)
        selector = RegretProxySelector(
            self.mask,
            proxy=proxy or _FakeProxy(pool),
            settings=self.settings,
            **kwargs,
        )
        return selector, sim, catalog

    def test_defaults_match_fixed_work_contract(self):
        selector, _sim, _catalog_value = self._case((_item(1),), ((0, 0, 0, 0),))
        self.assertEqual(selector.max_lineages, 24)
        self.assertEqual(selector.max_depth, 12)
        self.assertEqual(selector.beam_width, 32)
        self.assertEqual(selector.proxy_quota.max_nodes, 768)
        self.assertEqual(selector.proxy_quota.max_fit_tests, 96_000)
        self.assertEqual(selector.items_per_node, 4)
        self.assertEqual(selector.placements_per_item, 3)
        self.assertEqual(selector.children_per_node, 12)

    def test_c_is_single_step_and_returns_only_original_roots(self):
        items = (_item(10), _item(11))
        proxy = _FakeProxy(items, {(0,): {1: 3}, (1,): {0: 3}})
        selector, sim, catalog = self._case(
            items, ((0, 0, 0, 0), (1, 0, 0, 0)), proxy=proxy
        )

        ranked = selector.select(sim, catalog, "C", time.perf_counter() + 30.0)

        self.assertTrue(ranked)
        self.assertTrue(all(any(root is original for original in catalog.roots) for root in ranked))
        self.assertEqual(proxy.enumerated, [])
        self.assertEqual(selector.last_trace.deepest, 1)
        self.assertEqual(selector.last_trace.fit_tests, 0)

    def test_one_option_item_is_expanded_before_multi_option_item(self):
        items = (_item(20), _item(21), _item(22))
        proxy = _FakeProxy(items, {(0,): {1: 1, 2: 3}})
        selector, sim, catalog = self._case(items, ((0, 0, 0, 0),), proxy=proxy)

        selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertTrue(selector.last_trace.expanded_occurrences)
        self.assertEqual(selector.last_trace.expanded_occurrences[0], 1)

    def test_max_regret_breaks_tie_between_multi_option_items(self):
        items = (_item(23), _item(24), _item(25))
        proxy = _FakeProxy(
            items,
            {(0,): {1: 2, 2: 2}},
            {
                ((0, 0), (1, 0)): {"largest": 0.90},
                ((0, 0), (1, 1)): {"largest": 0.20},
                ((0, 0), (2, 0)): {"largest": 0.80},
                ((0, 0), (2, 1)): {"largest": 0.75},
            },
        )
        selector, sim, catalog = self._case(items, ((0, 0, 0, 0),), proxy=proxy)

        selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertEqual(selector.last_trace.expanded_occurrences[0], 1)

    def test_proven_count_precedes_volume_and_secondary_metrics(self):
        small = _item(30, 0.10)
        large = _item(31, 0.30)
        tail = _item(32, 0.10)
        items = (small, large, tail)
        proxy = _FakeProxy(
            items,
            {
                (0,): {2: 1},
                (0, 2): {1: 1},
                (1,): {},
            },
            {((1, 0),): {"largest": 1.0, "protection": 1.0}},
        )
        selector, sim, catalog = self._case(
            items, ((0, 0, 0, 0), (1, 0, 0, 0)), proxy=proxy
        )

        ranked = selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertEqual(ranked[0].proposal.pool_index, 0)
        self.assertGreaterEqual(selector.last_trace.deepest, 2)

    def test_proven_volume_precedes_secondary_proxy_metrics(self):
        small = _item(33, 0.10)
        large = _item(34, 0.30)
        items = (small, large)
        proxy = _FakeProxy(
            items,
            {},
            {
                ((0, 0),): {"largest": 1.0, "protection": 1.0},
                ((1, 0),): {"largest": 0.1, "protection": 0.1},
            },
        )
        selector, sim, catalog = self._case(
            items, ((0, 0, 0, 0), (1, 0, 0, 0)), proxy=proxy
        )

        ranked = selector.select(sim, catalog, "C", time.perf_counter() + 30.0)

        self.assertEqual(ranked[0].proposal.pool_index, 1)

    def test_root_adoption_is_pool_then_container_orientation_fair(self):
        items = (_item(40), _item(41), _item(42))
        specs = tuple(
            (pool_index, 0, orientation, serial)
            for pool_index in range(3)
            for serial, orientation in enumerate((0, 1, 2))
        )
        selector, sim, catalog = self._case(items, specs, max_lineages=6)

        selector.select(sim, catalog, "C", time.perf_counter() + 30.0)
        pools = tuple(key[0] for key in selector.last_trace.root_lineages)

        self.assertEqual(pools[:3], (0, 1, 2))
        self.assertEqual(pools[3:6], (0, 1, 2))

    def test_duplicate_global_ids_remain_occurrence_distinct(self):
        duplicate = _item(50)
        items = (duplicate, duplicate, _item(51))
        proxy = _FakeProxy(items, {(0,): {2: 1}, (1,): {2: 1}})
        selector, sim, catalog = self._case(
            items, ((0, 0, 0, 0), (1, 0, 0, 0)), proxy=proxy
        )

        ranked = selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertEqual({key[0] for key in selector.last_trace.root_lineages}, {0, 1})
        self.assertTrue(ranked)

    def test_lineage_fairness_precedes_second_node_and_bounds_work(self):
        items = tuple(_item(60 + index) for index in range(5))
        tree = {(index,): {other: 3 for other in range(5) if other != index} for index in (0, 1, 2)}
        proxy = _FakeProxy(items, tree)
        selector, sim, catalog = self._case(
            items,
            ((0, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0)),
            proxy=proxy,
            max_nodes=9,
            max_fit_tests=100,
        )

        selector.select(sim, catalog, "B", time.perf_counter() + 30.0)
        first = selector.last_trace.expanded_lineages[:3]

        self.assertEqual(set(first), {0, 1, 2})
        self.assertEqual(len(first), 3)
        self.assertLessEqual(selector.last_trace.nodes, 9)
        self.assertLessEqual(selector.last_trace.fit_tests, 100)

    def test_fit_work_is_reserved_for_each_first_lineage(self):
        items = tuple(_item(65 + index) for index in range(5))
        tree = {
            root: {other: 20 for other in range(5) if other != root}
            for root in (0, 1, 2)
        }
        proxy = _FakeProxy(items, tree)
        selector, sim, catalog = self._case(
            items,
            ((0, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0)),
            proxy=proxy,
            max_nodes=6,
            max_fit_tests=12,
        )

        selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertEqual(selector.last_trace.expanded_lineages[:3], (0, 1, 2))
        self.assertLessEqual(selector.last_trace.fit_tests, 12)

    def test_twenty_four_lineage_cap_and_every_adopted_root_is_freshly_applied(self):
        items = tuple(_item(200 + index) for index in range(30))
        catalog = _catalog(
            self.state,
            items,
            self.mask,
            tuple((index, 0, 0, 0) for index in range(30)),
        )
        sim = SimState.from_current(self.state, items)
        recording = _CountingMask(self.settings)
        selector = RegretProxySelector(
            recording,
            proxy=_FakeProxy(items),
            settings=self.settings,
        )

        ranked = selector.select(sim, catalog, "C", time.perf_counter() + 30.0)

        self.assertEqual(len(ranked), 24)
        self.assertEqual(len(selector.last_trace.root_lineages), 24)
        self.assertEqual(len(recording.calls), 24)

    def test_deadline_preserves_already_evaluated_exact_depth_zero_root(self):
        items = (_item(70), _item(71))
        base = time.perf_counter()
        clock = _StepClock(base, live_calls=3)
        selector, sim, catalog = self._case(
            items,
            ((0, 0, 0, 0), (1, 0, 0, 0)),
            clock=clock,
        )

        ranked = selector.select(sim, catalog, "B", base + 50.0)

        self.assertTrue(ranked)
        self.assertTrue(any(ranked[0] is root for root in catalog.roots))
        self.assertTrue(selector.last_trace.deadline_reached)

    def test_deadline_during_analysis_preserves_depth_zero_incumbent(self):
        items = (_item(72), _item(73))
        clock = _ToggleClock()

        class ExpiringAnalysisProxy(_FakeProxy):
            def enumerate_candidates(inner_self, *args, **kwargs):
                result = super(ExpiringAnalysisProxy, inner_self).enumerate_candidates(*args, **kwargs)
                clock.expired = True
                return result

        proxy = ExpiringAnalysisProxy(items, {(0,): {1: 1}})
        selector, sim, catalog = self._case(
            items,
            ((0, 0, 0, 0),),
            proxy=proxy,
            clock=clock,
        )

        ranked = selector.select(sim, catalog, "B", clock.base + 50.0)

        self.assertEqual(ranked, (catalog.roots[0],))
        self.assertEqual(selector.last_trace.deepest, 1)
        self.assertTrue(selector.last_trace.deadline_reached)

    def test_deadline_during_child_apply_does_not_publish_proxy_child(self):
        items = (_item(74), _item(75))
        clock = _ToggleClock()

        class ExpiringChildProxy(_FakeProxy):
            def apply(inner_self, state, candidate):
                result = super(ExpiringChildProxy, inner_self).apply(state, candidate)
                if len(inner_self.applied) == 2:
                    clock.expired = True
                return result

        proxy = ExpiringChildProxy(items, {(0,): {1: 1}})
        selector, sim, catalog = self._case(
            items,
            ((0, 0, 0, 0),),
            proxy=proxy,
            clock=clock,
        )

        ranked = selector.select(sim, catalog, "B", clock.base + 50.0)

        self.assertEqual(ranked, (catalog.roots[0],))
        self.assertEqual(selector.last_trace.predicted_count, 1)
        self.assertTrue(selector.last_trace.deadline_reached)

    def test_occurrence_exception_is_isolated_and_later_item_still_expands(self):
        items = (_item(76), _item(77), _item(78))

        class FaultProxy(_FakeProxy):
            def enumerate_candidates(inner_self, state, key, work, quota):
                if key.original_position == 1:
                    raise RuntimeError("synthetic item failure")
                return super(FaultProxy, inner_self).enumerate_candidates(
                    state, key, work, quota
                )

        proxy = FaultProxy(items, {(0,): {1: 1, 2: 1}})
        selector, sim, catalog = self._case(
            items, ((0, 0, 0, 0),), proxy=proxy
        )

        ranked = selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertTrue(ranked)
        self.assertGreaterEqual(selector.last_trace.branch_exceptions, 1)
        self.assertIn(2, selector.last_trace.expanded_occurrences)

    def test_stale_root_is_omitted_while_current_root_survives(self):
        items = (_item(80), _item(81))
        current = _catalog(self.state, items, self.mask, ((0, 0, 0, 0),))
        foreign_state = build_packing_state([_container()])
        foreign_pool = (items[1], items[0])
        stale = _catalog(foreign_state, foreign_pool, self.mask, ((0, 0, 0, 0),))
        mixed = RootCatalog(stale.records + current.records, CatalogStats())
        sim = SimState.from_current(self.state, items)
        selector = RegretProxySelector(self.mask, proxy=_FakeProxy(items), settings=self.settings)

        ranked = selector.select(sim, mixed, "C", time.perf_counter() + 30.0)

        self.assertEqual(ranked, (current.roots[0],))
        self.assertEqual(selector.last_trace.invalid_lineages, 1)

    def test_parent_catalog_and_original_root_identity_are_immutable(self):
        items = (_item(90), _item(91))
        selector, sim, catalog = self._case(
            items, ((0, 0, 0, 0), (1, 0, 0, 0))
        )
        parent_fingerprint = sim.fingerprint(self.settings)
        records = catalog.records

        ranked = selector.select(sim, catalog, "B", time.perf_counter() + 30.0)

        self.assertEqual(sim.fingerprint(self.settings), parent_fingerprint)
        self.assertIs(catalog.records, records)
        self.assertTrue(all(any(root is original for original in catalog.roots) for root in ranked))

    def test_frozen_task001_step8_diverges_from_fixed_root_and_proves_two_proxy_steps(self):
        snapshot = (
            SIMULATOR_ROOT
            / "results/support_extreme_fusion/task001-b-seed42-failure.npz"
        )
        if not snapshot.exists():
            self.skipTest("frozen task001 step8 snapshot is unavailable")
        observation, _metadata = load_observation_snapshot(snapshot)
        pool = observation["pool_list"]
        state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        mask = ExactMask(self.settings)
        scanner = StrictRootScanner(self.settings, mask=mask)
        started = time.perf_counter()
        catalog = scanner.scan(state, pool, deadline=started + 5.45)
        selector = RegretProxySelector(
            mask,
            settings=self.settings,
            max_nodes=48,
            max_fit_tests=1_000,
        )

        ranked = selector.select(
            SimState.from_current(state, pool),
            catalog,
            "B",
            time.perf_counter() + 10.0,
        )

        self.assertTrue(ranked)
        self.assertEqual(ranked[0].proposal.pool_index, 0)
        self.assertEqual(ranked[0].proposal.item_index, 6)
        self.assertNotEqual(
            (ranked[0].proposal.pool_index, ranked[0].proposal.item_index),
            (8, 16),  # frozen FixedQuotaExactTwoPly decision
        )
        self.assertEqual(selector.last_trace.predicted_count, 2)
        self.assertGreater(selector.last_trace.largest_free_region, 0.20)

    def test_twenty_fixed_clock_runs_are_identical(self):
        items = (_item(100), _item(101), _item(102))
        catalog = _catalog(self.state, items, self.mask, ((0, 0, 0, 0), (1, 0, 0, 0)))
        sim = SimState.from_current(self.state, items)
        outcomes = []
        fixed_now = time.perf_counter()
        for _ in range(20):
            selector = RegretProxySelector(
                self.mask,
                proxy=_FakeProxy(items, {(0,): {2: 2}, (1,): {2: 1}}),
                settings=self.settings,
                clock=lambda: fixed_now,
            )
            ranked = selector.select(sim, catalog, "B", fixed_now + 30.0)
            outcomes.append((ranked, selector.last_trace))

        self.assertTrue(outcomes[0][0])
        self.assertTrue(all(value == outcomes[0] for value in outcomes))

    def test_invalid_mode_and_all_invalid_catalog_fail_closed(self):
        items = (_item(110),)
        selector, sim, catalog = self._case(items, ((0, 0, 0, 0),))
        with self.assertRaises(ValueError):
            selector.select(sim, catalog, "A", time.perf_counter() + 30.0)

        empty = selector.select(sim, RootCatalog.empty(1), "B", time.perf_counter() + 30.0)
        self.assertEqual(empty, ())
        self.assertIsInstance(selector.last_trace, SelectionTrace)

    def test_module_has_no_unsafe_or_historical_search_dependencies(self):
        path = SIMULATOR_ROOT / "agents/support_extreme_fusion_beam_exact_mask/maxrects_regret.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = ("highscore", "ems", "mcts", "beam", "fixed_quota")
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ] + [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertFalse(any(any(token in module.lower() for token in forbidden) for module in imports))
        self.assertNotIn("ValidatedRoot(", source)
        self.assertNotIn('"item_idx"', source)
        self.assertNotIn("'item_idx'", source)


if __name__ == "__main__":
    unittest.main()
