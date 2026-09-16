from __future__ import annotations

import pathlib
import math
from types import SimpleNamespace
import sys
import time
import unittest
from unittest.mock import patch


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogStats,
    CatalogWorkQuota,
    RootCatalog,
    RootRecord,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.fixed_quota import (  # noqa: E402
    FixedQuotaExactTwoPly,
)
from agents.support_extreme_fusion_beam_exact_mask.features import FutureFeatures  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    ItemSpec,
    PlacementProposal,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (  # noqa: E402
    FusedProposal,
    ProposalProvenance,
    ProposalSource,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from tests.diagnose_support_extreme_fusion_initial_beam import _initial_case  # noqa: E402


def _container() -> dict:
    length, width, height, thickness = 4.0, 2.0, 2.0, 0.04
    return {
        "index": 91,
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


def _fused(item: ItemSpec, pool_index: int, serial: int = 0) -> FusedProposal:
    position = (
        -1.70 + 0.08 * (pool_index % 40),
        0.70 - 0.12 * serial,
        0.04 + 0.008 + item.height / 2.0,
    )
    proposal = PlacementProposal(
        item_index=item.index,
        pool_index=pool_index,
        container_index=0,
        orientation=0,
        position=position,
        source=ProposalSource.FREE_RECTANGLE_BOUNDARY.value,
    )
    return FusedProposal(
        proposal,
        ProposalProvenance(
            (ProposalSource.FREE_RECTANGLE_BOUNDARY.value,),
            ("floor",),
            (0.04,),
        ),
    )


class _RecordingMask(ExactMask):
    def __init__(self, settings):
        super().__init__(settings)
        self.diagnosed: list[int] = []

    def diagnose(self, state, pool, proposal, *, deadline=None):
        self.diagnosed.append(proposal.pool_index)
        return super().diagnose(state, pool, proposal, deadline=deadline)


class FixedCoverageCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(raw_proposal_limit=256)
        self.state = build_packing_state([_container()])

    def test_forty_occurrences_receive_first_exact_attempt_before_any_second(self):
        pool = tuple(_item(index) for index in range(40))
        mask = _RecordingMask(self.settings)
        scanner = StrictRootScanner(self.settings, mask=mask)

        def records(_state, item, pool_index, **kwargs):
            self.assertFalse(kwargs.get("deferred", False))
            self.assertNotIn(ProposalSource.DENSE_SUPPORT_LATTICE, kwargs["family_subset"])
            yield _fused(item, pool_index, 0)
            yield _fused(item, pool_index, 1)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = scanner.scan_coverage_fixed(
                self.state,
                pool,
                deadline=time.perf_counter() + 30.0,
                quota=CatalogWorkQuota(per_pool_raw_limit=2, global_exact_attempt_cap=80),
            )

        self.assertEqual(mask.diagnosed[:40], list(range(40)))
        self.assertEqual(catalog.stats.fixed_pools_attempted, 40)
        self.assertEqual(catalog.stats.fixed_pools_covered, 40)
        self.assertEqual(catalog.stats.exact_attempts, 40)  # stop after first strict root

    def test_global_exact_cap_is_fixed_and_duplicate_ids_remain_occurrence_distinct(self):
        duplicate = _item(7)
        pool = (duplicate, duplicate, _item(8))
        scanner = StrictRootScanner(self.settings)

        def records(_state, item, pool_index, **_kwargs):
            yield _fused(item, pool_index, 0)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = scanner.scan_coverage_fixed(
                self.state,
                pool,
                deadline=time.perf_counter() + 30.0,
                quota=CatalogWorkQuota(per_pool_raw_limit=1, global_exact_attempt_cap=2),
            )

        self.assertEqual([record.pool_index for record in catalog], [0, 1])
        self.assertEqual(catalog.stats.exact_attempts, 2)
        self.assertTrue(catalog.stats.fixed_quota_exhausted)
        self.assertEqual(catalog.stats.fixed_pools_covered, 2)


class _TreeCoverageScanner:
    def __init__(self, mask: ExactMask, tree: dict[tuple[int, ...], tuple[int, ...]]):
        self.mask = mask
        self.tree = tree
        self.calls: list[tuple[int, ...]] = []
        self.expire_callback = None

    def _prefix(self, state) -> tuple[int, ...]:
        return tuple(
            placed.item.index
            for container in state.containers
            for placed in container.placed
        )

    def catalog(self, state, pool, choices: tuple[int, ...], roots_each: int = 1):
        records: list[RootRecord] = []
        prefix = self._prefix(state)
        depth = len(prefix)
        for pool_index in choices:
            item = pool[pool_index]
            if not isinstance(item, ItemSpec):
                item = ItemSpec.from_dict(item)
            for serial in range(roots_each):
                x = -1.70 + 0.42 * ((item.index + serial) % 9)
                y = 0.72 - 0.28 * depth - 0.11 * serial
                proposal = PlacementProposal(
                    item_index=item.index,
                    pool_index=pool_index,
                    container_index=0,
                    orientation=0,
                    position=(x, y, 0.04 + 0.008 + item.height / 2.0),
                    source=f"tree-{depth}-{pool_index}-{serial}",
                )
                root = self.mask.validate(state, pool, proposal, deadline=None)
                if root is None:
                    continue
                records.append(
                    RootRecord(
                        root,
                        ProposalProvenance((proposal.source,), ("floor",), (0.04,)),
                        "normal",
                        len(records),
                    )
                )
        counts = tuple(sum(record.pool_index == i for record in records) for i in range(len(pool)))
        return RootCatalog(
            tuple(records),
            CatalogStats(
                exact_attempts=len(records),
                accepted_roots=len(records),
                normal_roots=len(records),
                per_pool_raw=counts,
                per_pool_roots=counts,
                fixed_pools_attempted=sum(bool(count) for count in counts),
                fixed_pools_covered=sum(bool(count) for count in counts),
            ),
        )

    def scan_coverage_fixed(
        self,
        state,
        pool,
        *,
        deadline,
        quota,
        allow_deferred=False,
        allow_rescue=False,
    ):
        self.assert_normal_only = not allow_deferred and not allow_rescue
        prefix = self._prefix(state)
        self.calls.append(prefix)
        current = tuple(item.index if isinstance(item, ItemSpec) else item["index"] for item in pool)
        wanted_ids = self.tree.get(prefix, ())
        choices = tuple(
            pool_index
            for wanted in wanted_ids
            for pool_index, item_id in enumerate(current)
            if item_id == wanted
        )
        result = self.catalog(state, pool, choices)
        if self.expire_callback is not None:
            self.expire_callback()
        return result


class _SwitchClock:
    def __init__(self):
        self.base = time.perf_counter()
        self.expired = False

    def __call__(self):
        return self.base + (100.0 if self.expired else 0.0)


class FixedQuotaTwoPlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings()
        self.mask = ExactMask(self.settings)
        self.state = build_packing_state([_container()])

    def _planner(self, scanner, **kwargs):
        return FixedQuotaExactTwoPly(
            scanner,
            self.mask,
            self.settings,
            clock=kwargs.pop("clock", None),
            **kwargs,
        )

    def _rank_node(
        self,
        key: int,
        *,
        proven_count: int = 1,
        proven_volume: float = 1.0,
        scarcity: float = 0.5,
        **features,
    ):
        return SimpleNamespace(
            proven_count=proven_count,
            proven_volume=proven_volume,
            scarcity_urgency=scarcity,
            features=FutureFeatures(**features),
            stable_sequence_key=(key,),
        )

    def test_contiguous_largest_space_precedes_tiny_total_support_gain(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        tiny_support_gain = self._rank_node(
            0,
            compatible_support_capacity=0.91,
            largest_free_support=0.20,
        )
        contiguous_space = self._rank_node(
            1,
            compatible_support_capacity=0.90,
            largest_free_support=0.70,
        )

        self.assertIs(planner._ordered((tiny_support_gain, contiguous_space))[0], contiguous_space)

    def test_protection_and_ingress_each_precede_largest_space(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        protected = self._rank_node(
            0,
            protection_compatible_capacity=0.80,
            ingress_access=0.10,
            largest_free_support=0.10,
        )
        exposed = self._rank_node(
            1,
            protection_compatible_capacity=0.79,
            ingress_access=1.00,
            largest_free_support=1.00,
        )
        ingress = self._rank_node(
            2,
            protection_compatible_capacity=0.80,
            ingress_access=0.90,
            largest_free_support=0.10,
        )

        self.assertIs(planner._ordered((protected, exposed))[0], protected)
        self.assertIs(planner._ordered((protected, ingress))[0], ingress)

    def test_sub_material_protection_delta_lets_contiguous_topology_win(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        center = self._rank_node(
            0,
            protection_compatible_capacity=0.553222,
            ingress_access=1.0,
            largest_free_support=0.477020,
        )
        back = self._rank_node(
            1,
            protection_compatible_capacity=0.552696,
            ingress_access=1.0,
            largest_free_support=0.677465,
        )

        self.assertIs(planner._ordered((center, back))[0], back)

    def test_one_percentage_point_protection_gain_precedes_topology(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        protected = self._rank_node(
            0,
            protection_compatible_capacity=0.56,
            largest_free_support=0.10,
        )
        contiguous = self._rank_node(
            1,
            protection_compatible_capacity=0.55,
            largest_free_support=1.00,
        )

        self.assertIs(planner._ordered((protected, contiguous))[0], protected)

    def test_protection_materiality_bin_boundary_is_explicit_and_deterministic(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        below = self._rank_node(0, protection_compatible_capacity=0.599999)
        boundary = self._rank_node(1, protection_compatible_capacity=0.60)

        self.assertEqual(planner._rank(below)[6], 59.0)
        self.assertEqual(planner._rank(boundary)[6], 60.0)
        self.assertIs(planner._ordered((below, boundary))[0], boundary)

        for invalid in (0.0, -0.01, math.inf, math.nan):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self._planner(
                        _TreeCoverageScanner(self.mask, {}),
                        protection_materiality=invalid,
                    )

    def test_exact_protection_breaks_tie_after_topology_before_total_support(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        exact_protection = self._rank_node(
            0,
            protection_compatible_capacity=0.557,
            ingress_access=0.8,
            largest_free_support=0.7,
            sliver_area=0.1,
            compatible_support_capacity=0.1,
        )
        aggregate_support = self._rank_node(
            1,
            protection_compatible_capacity=0.552,
            ingress_access=0.8,
            largest_free_support=0.7,
            sliver_area=0.1,
            compatible_support_capacity=1.0,
        )

        self.assertIs(
            planner._ordered((exact_protection, aggregate_support))[0],
            exact_protection,
        )

    def test_coverage_volume_robustness_and_scarcity_keep_precedence(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        later_advantage = {
            "protection_compatible_capacity": 1.0,
            "ingress_access": 1.0,
            "largest_free_support": 1.0,
        }
        cases = (
            ("proven_volume", {"proven_volume": 1.1}),
            ("future_covered_items", {"future_covered_items": 0.6}),
            ("future_covered_volume", {"future_covered_volume": 0.6}),
            ("root_robustness", {"root_robustness": 0.6}),
            ("scarcity", {"scarcity": 0.6}),
        )
        for name, advantage in cases:
            with self.subTest(feature=name):
                preferred = self._rank_node(0, **advantage)
                later = self._rank_node(1, **later_advantage)
                self.assertIs(planner._ordered((preferred, later))[0], preferred)

    def test_sliver_precedes_total_support_then_stable_key_breaks_full_tie(self) -> None:
        planner = self._planner(_TreeCoverageScanner(self.mask, {}))
        low_sliver = self._rank_node(
            2, sliver_area=0.10, compatible_support_capacity=0.10
        )
        high_support = self._rank_node(
            1, sliver_area=0.20, compatible_support_capacity=1.00
        )
        self.assertIs(planner._ordered((low_sliver, high_support))[0], low_sliver)

        support = self._rank_node(
            3, sliver_area=0.10, compatible_support_capacity=0.80
        )
        self.assertIs(planner._ordered((low_sliver, support))[0], support)

        tie_high_key = self._rank_node(9)
        tie_low_key = self._rank_node(4)
        self.assertIs(planner._ordered((tie_high_key, tie_low_key))[0], tie_low_key)

    def test_sixty_four_roots_trigger_at_most_eight_child_scans(self):
        pool = tuple(_item(100 + index) for index in range(8))
        scanner = _TreeCoverageScanner(self.mask, {})
        catalog = scanner.catalog(self.state, pool, tuple(range(8)), roots_each=8)
        planner = self._planner(scanner)

        chosen = planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)

        self.assertIsNotNone(chosen)
        self.assertLessEqual(planner.last_trace.child_scans, 8)
        self.assertEqual(
            planner.last_trace.child_exact_attempts,
            planner.last_trace.child_covered_occurrences,
        )
        self.assertLessEqual(planner.last_trace.second_edges, 12)
        self.assertTrue(any(chosen is root for root in catalog.roots))

    def test_ranked_choice_retains_original_identity_and_fresh_strict_authorization(self):
        pool = (_item(150), _item(151))
        scanner = _TreeCoverageScanner(self.mask, {})
        catalog = scanner.catalog(self.state, pool, (0, 1), roots_each=2)
        planner = self._planner(scanner)

        chosen = planner.choose_b(
            self.state, pool, catalog, time.perf_counter() + 30.0
        )
        fresh = self.mask.validate(
            self.state, pool, chosen.proposal, deadline=time.perf_counter() + 30.0
        )

        self.assertTrue(any(chosen is root for root in catalog.roots))
        self.assertTrue(chosen.strict)
        self.assertEqual(chosen.rule_violations, 0)
        self.assertIsNot(fresh, chosen)
        self.assertEqual(fresh.proposal_key, chosen.proposal_key)

    def test_two_step_proof_beats_locally_larger_dead_end(self):
        large = _item(200, 0.28)
        small = _item(201, 0.16)
        continuation = _item(202, 0.14)
        pool = (large, small, continuation)
        scanner = _TreeCoverageScanner(
            self.mask,
            {(small.index,): (continuation.index,)},
        )
        catalog = scanner.catalog(self.state, pool, (0, 1))
        planner = self._planner(scanner)

        chosen = planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)

        self.assertEqual(chosen.proposal.item_index, small.index)
        self.assertEqual(planner.last_trace.deepest_proven_count, 2)
        self.assertLessEqual(planner.last_trace.second_edges, 12)
        self.assertFalse(any(len(prefix) >= 2 for prefix in scanner.calls))

    def test_deadline_preserves_fresh_depth_zero_incumbent(self):
        pool = (_item(300), _item(301))
        clock = _SwitchClock()
        scanner = _TreeCoverageScanner(self.mask, {})
        catalog = scanner.catalog(self.state, pool, (0, 1))
        scanner.expire_callback = lambda: setattr(clock, "expired", True)
        planner = self._planner(scanner, clock=clock)

        chosen = planner.choose_b(self.state, pool, catalog, clock.base + 50.0)

        self.assertIsNotNone(chosen)
        self.assertTrue(any(chosen is root for root in catalog.roots))
        self.assertTrue(planner.last_trace.deadline_reached)

    def test_twenty_runs_have_identical_original_root_and_trace(self):
        pool = tuple(_item(400 + index) for index in range(4))
        scanner = _TreeCoverageScanner(self.mask, {})
        catalog = scanner.catalog(self.state, pool, tuple(range(4)), roots_each=2)
        outcomes = []
        for _ in range(20):
            planner = self._planner(scanner)
            root = planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)
            outcomes.append((root, planner.last_trace))

        self.assertTrue(all(root is outcomes[0][0] for root, _ in outcomes))
        self.assertTrue(all(trace == outcomes[0][1] for _, trace in outcomes))

    def test_duplicate_item_ids_keep_pool_occurrences_separate(self):
        duplicate = _item(500)
        tail = _item(501)
        pool = (duplicate, duplicate, tail)
        scanner = _TreeCoverageScanner(self.mask, {(duplicate.index,): (tail.index,)})
        catalog = scanner.catalog(self.state, pool, (0, 1))
        planner = self._planner(scanner)

        chosen = planner.choose_b(self.state, pool, catalog, time.perf_counter() + 30.0)

        self.assertIsNotNone(chosen)
        self.assertIn(chosen.proposal.pool_index, (0, 1))
        self.assertTrue(any(chosen is root for root in catalog.roots))

    def test_task001_initial_material_rank_selects_back_root_with_fresh_authorization(self):
        state, pool, _raw = _initial_case()
        scanner = StrictRootScanner(self.settings, mask=self.mask)
        started = time.perf_counter()
        catalog = scanner.scan(state, pool, deadline=started + 5.45)
        planner = self._planner(scanner)

        chosen = planner.choose_b(state, pool, catalog, started + 30.0)
        fresh = self.mask.validate(
            state, pool, chosen.proposal, deadline=started + 30.0
        )

        self.assertEqual(chosen.proposal.pool_index, 2)
        self.assertAlmostEqual(chosen.proposal.position[1], 0.477, places=3)
        self.assertTrue(any(chosen is root for root in catalog.roots))
        self.assertIsNot(fresh, chosen)
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.proposal_key, chosen.proposal_key)



if __name__ == "__main__":
    unittest.main()
