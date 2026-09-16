from __future__ import annotations

import inspect
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogStats,
    RootCatalog,
    RootRecord,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.agent import Agent  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    ItemSpec,
    PlacementProposal,
    ValidatedRoot,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (  # noqa: E402
    FusedProposal,
    ProposalProvenance,
    ProposalSource,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from tests.replay_support import load_observation_snapshot  # noqa: E402


def _container(*, index: int = 17, offset_x: float = 0.0, prioritized: bool = False) -> dict:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (offset_x, 0.0, height / 2.0),
        "points": [
            [offset_x + length / 2.0 - thickness, 0.0, 0.0],
            [offset_x - length / 2.0 + thickness, 0.0, 0.0],
            [offset_x, width / 2.0 - thickness, 0.0],
            [offset_x, -width / 2.0 + thickness, 0.0],
            [offset_x, 0.0, height - thickness],
            [offset_x, 0.0, thickness],
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
        "is_prioritized": prioritized,
        "packed_items": [],
    }


def _item(index: int, *, prioritized: bool = False) -> ItemSpec:
    return ItemSpec(
        index=index,
        length=0.20,
        width=0.16,
        height=0.12,
        mass=3.0,
        is_prioritized=prioritized,
    )


def _record(
    item: ItemSpec,
    pool_index: int,
    *,
    container_index: int = 0,
    serial: int = 0,
    valid: bool = True,
    source: str = "floor_wall_extreme",
) -> FusedProposal:
    x = -0.65 + (serial % 8) * 0.18
    y = 0.58 - (serial // 8) * 0.18
    position = (x, y, 0.04 + 0.008 + item.height / 2.0) if valid else (x, y, 2.0)
    proposal = PlacementProposal(
        item_index=item.index,
        pool_index=pool_index,
        container_index=container_index,
        orientation=0,
        position=position,
        source=source,
    )
    return FusedProposal(
        proposal,
        ProposalProvenance(
            sources=(source,), support_sources=("floor",), support_levels=(0.04,)
        ),
    )


def _bounded_records(records: list[FusedProposal], raw_work_limit: int | None):
    limit = len(records) if raw_work_limit is None else min(len(records), int(raw_work_limit))
    yield from records[:limit]


class _DeadlineIgnoringMask(ExactMask):
    def validate(self, state, pool, proposal, *, deadline=None):
        return super().validate(state, pool, proposal, deadline=None)

    def diagnose(self, state, pool, proposal, *, deadline=None):
        return super().diagnose(state, pool, proposal, deadline=None)


class RootCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(
            raw_proposal_limit=16,
            proposal_quantum=2,
            normal_catalog_limit_seconds=2.0,
        )
        self.state = build_packing_state([_container()])

    def test_real_catalog_contains_only_fresh_exact_roots(self):
        pool = [_item(1).to_dict(), _item(2).to_dict()]
        scanner = StrictRootScanner(self.settings)
        catalog = scanner.scan(self.state, pool)

        self.assertIsInstance(catalog, RootCatalog)
        self.assertTrue(catalog)
        self.assertTrue(all(isinstance(record, RootRecord) for record in catalog))
        self.assertTrue(all(isinstance(root, ValidatedRoot) for root in catalog.roots))
        self.assertTrue(all(root.strict for root in catalog.roots))
        self.assertEqual(catalog.stats.accepted_roots, len(catalog))
        for record in catalog:
            fresh = scanner.mask.revalidate(
                self.state, pool, record.root.proposal, self.settings
            )
            self.assertIsInstance(fresh, ValidatedRoot)
            self.assertEqual(fresh.proposal_key, record.root.proposal_key)

        with self.assertRaisesRegex(ValueError, "profile"):
            StrictRootScanner(
                self.settings,
                mask=ExactMask(SearchSettings(path_clearance=0.019)),
            )

    def test_normal_only_scan_never_opens_deferred_or_rescue_families(self):
        state = build_packing_state(
            [
                _container(index=10, offset_x=-2.0, prioritized=False),
                _container(index=20, offset_x=2.0, prioritized=True),
            ]
        )
        item = _item(1)
        calls: list[tuple[bool, bool]] = []

        def fake_records(_state, raw_item, pool_index, **kwargs):
            deferred = bool(kwargs.get("deferred", False))
            rescue = bool(kwargs.get("rescue_only", False))
            calls.append((deferred, rescue))
            if deferred:
                yield _record(raw_item, pool_index, container_index=1)
            elif rescue:
                yield _record(raw_item, pool_index, container_index=0)

        scanner = StrictRootScanner(
            self.settings,
            first_pass_raw_cap=1,
            pass2_raw_increment=16,
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            normal_only = scanner.scan(
                state,
                (item,),
                allow_deferred=False,
                allow_rescue=False,
            )
        self.assertFalse(normal_only)
        self.assertTrue(calls)
        self.assertTrue(all(not deferred and not rescue for deferred, rescue in calls))

        calls.clear()
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            default_catalog = scanner.scan(state, (item,))
        self.assertTrue(default_catalog)
        self.assertTrue(any(deferred or rescue for deferred, rescue in calls))

    def test_pass_one_raw_cap_gives_every_pool_position_a_first_chance(self):
        pool_items = [_item(10), _item(11), _item(12)]
        pool = [item.to_dict() for item in pool_items]
        calls: list[tuple[int, int | None, bool, bool]] = []

        def fake_records(_state, item, pool_index, **kwargs):
            item = item if isinstance(item, ItemSpec) else ItemSpec.from_dict(item)
            calls.append((pool_index, kwargs.get("raw_work_limit"), kwargs.get("rescue_only", False), kwargs.get("deferred", False)))
            yield from _bounded_records(
                [_record(item, pool_index, serial=serial) for serial in range(12)],
                kwargs.get("raw_work_limit"),
            )

        scanner = StrictRootScanner(
            self.settings, first_pass_raw_cap=2, pass2_raw_increment=2
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(self.state, pool)

        self.assertEqual([entry[0] for entry in calls[:3]], [0, 1, 2])
        self.assertEqual([entry[1] for entry in calls[:3]], [2, 2, 2])
        self.assertEqual(catalog.stats.per_pool_roots, (8, 8, 8))
        self.assertEqual([record.pool_index for record in tuple(catalog)[:3]], [0, 1, 2])

    def test_generation_time_slice_preserves_later_pool_probe(self):
        settings = SearchSettings(
            raw_proposal_limit=16,
            proposal_quantum=2,
            normal_catalog_limit_seconds=10.0,
        )
        items = [_item(15), _item(16)]
        pool = [item.to_dict() for item in items]
        current_time = [0.0]
        calls: list[tuple[int, float]] = []

        def clock() -> float:
            return current_time[0]

        def fake_records(_state, current, pool_index, **kwargs):
            calls.append((pool_index, float(kwargs["deadline"])))
            # Both occurrences legitimately consume their complete reserved
            # construction slice and still return a viable proposal.
            current_time[0] = float(kwargs["deadline"])
            yield _record(items[pool_index], pool_index)

        scanner = StrictRootScanner(
            settings,
            mask=_DeadlineIgnoringMask(settings),
            clock=clock,
            first_pass_raw_cap=4,
        )
        with patch.object(
            scanner,
            "_fair_generation_deadline",
            side_effect=lambda deadline, remaining: deadline,
        ), patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            starved = scanner.scan(
                self.state,
                pool,
                deadline=10.0,
                allow_deferred=False,
                allow_rescue=False,
            )
        self.assertFalse(starved)

        current_time[0] = 0.0
        calls.clear()
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(
                self.state,
                pool,
                deadline=10.0,
                allow_deferred=False,
                allow_rescue=False,
            )

        self.assertTrue(catalog.for_pool(0))
        self.assertTrue(catalog.for_pool(1))
        first_pool_zero = next(deadline for index, deadline in calls if index == 0)
        self.assertLess(first_pool_zero, 10.0)
        self.assertIn(1, [index for index, _ in calls[:2]])
        self.assertLess(current_time[0], 10.0)

    def test_free_raw_123_root_is_recovered_before_dense_stage(self):
        settings = SearchSettings(
            raw_proposal_limit=256,
            proposal_quantum=4,
            normal_catalog_limit_seconds=10.0,
        )
        item = _item(13)
        pool = [item.to_dict()]
        calls: list[tuple[tuple[ProposalSource, ...], int]] = []

        def fake_records(_state, current, pool_index, **kwargs):
            families = tuple(kwargs.get("family_subset") or ())
            budget = int(kwargs["raw_work_limit"])
            calls.append((families, budget))
            if families == (ProposalSource.FREE_RECTANGLE_BOUNDARY,):
                records = [
                    _record(
                        item,
                        pool_index,
                        serial=serial,
                        valid=False,
                        source=ProposalSource.FREE_RECTANGLE_BOUNDARY.value,
                    )
                    for serial in range(122)
                ]
                records.append(
                    _record(
                        item,
                        pool_index,
                        serial=0,
                        source=ProposalSource.FREE_RECTANGLE_BOUNDARY.value,
                    )
                )
                yield from _bounded_records(records, budget)
            elif families == (ProposalSource.DENSE_SUPPORT_LATTICE,):
                yield _record(
                    item,
                    pool_index,
                    source=ProposalSource.DENSE_SUPPORT_LATTICE.value,
                )

        scanner = StrictRootScanner(
            settings,
            mask=_DeadlineIgnoringMask(settings),
            clock=lambda: 0.0,
            first_pass_raw_cap=8,
            pass2_raw_increment=32,
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(self.state, pool)

        self.assertTrue(catalog)
        self.assertFalse(
            any(families == (ProposalSource.DENSE_SUPPORT_LATTICE,) for families, _ in calls)
        )
        self.assertGreaterEqual(
            dict(catalog.stats.stage_attempts).get("normal.free_deepen", 0),
            115,
        )
        self.assertEqual(catalog.stats.first_root_stage, ("normal.free_deepen",))

    def test_obstacle_and_plane_structural_stages_are_not_starved(self):
        item = _item(14)
        pool = [item.to_dict()]
        calls: list[tuple[ProposalSource, ...]] = []

        def fake_records(_state, current, pool_index, **kwargs):
            families = tuple(kwargs.get("family_subset") or ())
            calls.append(families)
            if families == (ProposalSource.OBSTACLE_FACE_EXTREME,):
                yield _record(
                    item,
                    pool_index,
                    valid=False,
                    source=families[0].value,
                )
            elif families == (ProposalSource.PLANE_DERIVED_EDGE,):
                yield _record(
                    item,
                    pool_index,
                    serial=1,
                    source=families[0].value,
                )

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(
                self.state,
                pool,
                allow_rescue=False,
            )

        self.assertTrue(catalog)
        self.assertIn((ProposalSource.OBSTACLE_FACE_EXTREME,), calls)
        self.assertIn((ProposalSource.PLANE_DERIVED_EDGE,), calls)
        stage_attempts = dict(catalog.stats.stage_attempts)
        self.assertEqual(stage_attempts["normal.obstacle_probe"], 1)
        self.assertEqual(stage_attempts["normal.plane_probe"], 1)
        self.assertEqual(catalog.stats.first_root_stage, ("normal.plane_probe",))

    def test_e2_step11_catalog_yields_fresh_format_capable_depth_zero_roots(self):
        snapshot = pathlib.Path(__file__).resolve().parents[1] / (
            "results/support_extreme_fusion/task001-b-seed42-e2-failure.npz"
        )
        observation, _ = load_observation_snapshot(snapshot)
        pool = observation["pool_list"]
        state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        scanner = StrictRootScanner()
        started = time.perf_counter()
        catalog = scanner.scan(state, pool, deadline=started + 5.45)
        elapsed = time.perf_counter() - started

        self.assertTrue(catalog)
        self.assertLess(elapsed, 5.45)
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        root_ids = {id(record.root) for record in catalog}
        for record in catalog:
            fresh = scanner.mask.revalidate(
                state, pool, record.proposal, scanner.settings
            )
            self.assertIsInstance(fresh, ValidatedRoot)
            self.assertEqual(fresh.proposal_key, record.root.proposal_key)
            action = agent.format_validated_action(record.root, state, pool)
            self.assertEqual(action["item_idx"], record.pool_index)
            self.assertIn(id(record.root), root_ids)

    def test_duplicate_global_item_ids_remain_distinct_pool_choices(self):
        duplicate = _item(20)
        pool = [duplicate.to_dict(), duplicate.to_dict()]

        def fake_records(_state, item, pool_index, **kwargs):
            item = item if isinstance(item, ItemSpec) else ItemSpec.from_dict(item)
            yield _record(item, pool_index, serial=pool_index)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(self.state, pool)

        self.assertEqual({record.pool_index for record in catalog}, {0, 1})
        self.assertEqual({record.item_index for record in catalog}, {20})
        self.assertEqual(len({root.state_fingerprint for root in catalog.roots}), 2)

    def test_per_pool_and_global_caps_preserve_stable_first_pass_order(self):
        items = [_item(30 + index) for index in range(10)]
        pool = [item.to_dict() for item in items]

        def fake_records(_state, item, pool_index, **kwargs):
            item = item if isinstance(item, ItemSpec) else ItemSpec.from_dict(item)
            yield from _bounded_records(
                [_record(item, pool_index, serial=serial) for serial in range(12)],
                kwargs.get("raw_work_limit"),
            )

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            first = StrictRootScanner(self.settings).scan(self.state, pool)
            second = StrictRootScanner(self.settings).scan(self.state, pool)

        self.assertEqual(len(first), 64)
        self.assertTrue(all(count <= 8 for count in first.stats.per_pool_roots))
        self.assertEqual([record.pool_index for record in tuple(first)[:10]], list(range(10)))
        self.assertEqual(
            [record.stable_key for record in first],
            [record.stable_key for record in second],
        )

    def test_deadline_returns_exact_partial_incumbent(self):
        item = _item(50)
        pool = [item.to_dict()]
        ticks = iter(index * 0.16 for index in range(100))
        clock = lambda: next(ticks)

        def fake_records(_state, current, pool_index, **kwargs):
            current = current if isinstance(current, ItemSpec) else ItemSpec.from_dict(current)
            yield from [_record(current, pool_index, serial=serial) for serial in range(12)]

        scanner = StrictRootScanner(
            self.settings,
            mask=_DeadlineIgnoringMask(self.settings),
            clock=clock,
            first_pass_raw_cap=4,
            pass2_raw_increment=4,
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(self.state, pool, deadline=1.0)

        self.assertGreater(len(catalog), 0)
        self.assertLess(len(catalog), 8)
        self.assertTrue(catalog.stats.deadline_reached)
        self.assertTrue(all(isinstance(root, ValidatedRoot) for root in catalog.roots))
        self.assertEqual(sum(dict(catalog.stats.stage_attempts).values()), catalog.stats.exact_attempts)
        self.assertEqual(catalog.stats.first_root_stage, ("normal.free_probe",))

    def test_item_generator_exception_isolated_and_later_item_survives(self):
        items = [_item(60), _item(61)]
        pool = [item.to_dict() for item in items]

        def fake_records(_state, item, pool_index, **kwargs):
            if pool_index == 0:
                raise RuntimeError("isolated-item-failure")
            yield _record(items[pool_index], pool_index)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(self.state, pool)

        self.assertEqual({record.pool_index for record in catalog}, {1})
        self.assertEqual(catalog.stats.item_exceptions[0][0], 0)
        self.assertIn("RuntimeError", catalog.stats.item_exceptions[0][1])

    def test_normal_roots_exclude_dense_rescue_provenance(self):
        catalog = StrictRootScanner(self.settings).scan(
            self.state, [_item(70).to_dict()]
        )
        self.assertTrue(catalog)
        self.assertTrue(all(record.pass_name == "normal" for record in catalog))
        self.assertTrue(
            all("dense_support_lattice" not in record.provenance.sources for record in catalog)
        )
        self.assertEqual(catalog.stats.rescue_roots, 0)

    def test_global_zero_runs_rescue_for_all_rootless_positions(self):
        items = [_item(80), _item(81)]
        pool = [item.to_dict() for item in items]
        rescue_calls: list[int] = []

        def fake_records(_state, item, pool_index, **kwargs):
            current = items[pool_index]
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                rescue_calls.append(pool_index)
                yield _record(
                    current, pool_index, serial=pool_index,
                    source="dense_support_lattice",
                )
            else:
                yield _record(current, pool_index, valid=False)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(self.state, pool)

        self.assertEqual(set(rescue_calls), {0, 1})
        self.assertEqual({record.pool_index for record in catalog}, {0, 1})
        self.assertTrue(all(record.pass_name == "rescue" for record in catalog))
        self.assertEqual(catalog.stats.normal_roots, 0)

    def test_normal_time_slice_expires_before_later_hard_rescue_deadline(self):
        settings = SearchSettings(
            raw_proposal_limit=16,
            proposal_quantum=1,
            normal_catalog_limit_seconds=0.25,
            zero_root_rescue_limit_seconds=2.0,
        )
        item = _item(82)
        pool = [item.to_dict()]
        ticks = iter(index * 0.05 for index in range(200))
        normal_budgets: list[int] = []
        dense_calls: list[int] = []

        def fake_records(_state, current, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                dense_calls.append(int(kwargs["raw_work_limit"]))
                yield _record(item, pool_index, source="dense_support_lattice")
            else:
                normal_budgets.append(int(kwargs["raw_work_limit"]))
                yield _record(item, pool_index, valid=False)

        scanner = StrictRootScanner(
            settings,
            mask=_DeadlineIgnoringMask(settings),
            clock=lambda: next(ticks),
            first_pass_raw_cap=2,
            pass2_raw_increment=2,
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(self.state, pool, deadline=2.0)

        self.assertTrue(normal_budgets)
        self.assertTrue(dense_calls)
        self.assertTrue(catalog.stats.deadline_reached)
        self.assertTrue(catalog)
        self.assertTrue(all(record.pass_name == "rescue" for record in catalog))

    def test_explicit_breadth_rescue_targets_only_normal_rootless_items(self):
        items = [_item(90), _item(91)]
        pool = [item.to_dict() for item in items]
        rescue_calls: list[int] = []

        def fake_records(_state, item, pool_index, **kwargs):
            current = items[pool_index]
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                rescue_calls.append(pool_index)
                yield _record(current, pool_index, serial=5, source="free_rectangle_boundary")
            elif pool_index == 0:
                yield _record(current, pool_index)
            else:
                yield _record(current, pool_index, valid=False)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(
                self.state, pool, breadth_rescue=True
            )

        self.assertEqual(set(rescue_calls), {1})
        self.assertTrue(any(record.pass_name == "normal" for record in catalog))
        self.assertTrue(any(record.pass_name == "rescue" for record in catalog))

    def test_ordinary_root_suppresses_deferred_priority_tier(self):
        state = build_packing_state([
            _container(index=100, offset_x=-2.0),
            _container(index=5, offset_x=2.0, prioritized=True),
        ])
        item = _item(100)
        pool = [item.to_dict()]
        deferred_calls: list[bool] = []

        def fake_records(_state, current, pool_index, **kwargs):
            deferred = bool(kwargs.get("deferred"))
            deferred_calls.append(deferred)
            yield _record(item, pool_index, container_index=1 if deferred else 0)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(state, pool)

        self.assertTrue(catalog)
        self.assertTrue(all(record.container_index == 0 for record in catalog))
        self.assertNotIn(True, deferred_calls)

    def test_deferred_priority_tier_exposed_only_after_ordinary_strict_zero(self):
        settings = SearchSettings(raw_proposal_limit=4, proposal_quantum=2)
        state = build_packing_state([
            _container(index=100, offset_x=-2.0),
            _container(index=5, offset_x=2.0, prioritized=True),
        ])
        item = _item(110)
        pool = [item.to_dict()]
        deferred_calls: list[bool] = []

        def fake_records(_state, current, pool_index, **kwargs):
            deferred = bool(kwargs.get("deferred"))
            deferred_calls.append(deferred)
            yield _record(
                item,
                pool_index,
                container_index=1 if deferred else 0,
                valid=deferred,
            )

        scanner = StrictRootScanner(
            settings, first_pass_raw_cap=2, pass2_raw_increment=2
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(state, pool)

        self.assertIn(True, deferred_calls)
        self.assertTrue(catalog)
        self.assertTrue(all(record.container_index == 1 for record in catalog))
        self.assertTrue(all(record.pass_name == "deferred" for record in catalog))

    def test_deferred_transition_runs_when_coverage_already_reached_raw_limit(self):
        settings = SearchSettings(raw_proposal_limit=2, proposal_quantum=2)
        state = build_packing_state([
            _container(index=200, offset_x=-2.0),
            _container(index=9, offset_x=2.0, prioritized=True),
        ])
        item = _item(111)
        pool = [item.to_dict()]
        deferred_calls: list[bool] = []

        def fake_records(_state, current, pool_index, **kwargs):
            deferred = bool(kwargs.get("deferred"))
            deferred_calls.append(deferred)
            yield _record(
                item,
                pool_index,
                container_index=1 if deferred else 0,
                valid=deferred,
            )

        scanner = StrictRootScanner(
            settings, first_pass_raw_cap=2, pass2_raw_increment=2
        )
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(state, pool)

        self.assertIn(True, deferred_calls)
        self.assertEqual([record.pass_name for record in catalog], ["deferred"])
        self.assertEqual([record.container_index for record in catalog], [1])

    def test_rejection_counts_and_empty_catalog_never_invent_an_action(self):
        item = _item(120)
        pool = [item.to_dict()]

        def fake_records(_state, current, pool_index, **kwargs):
            if kwargs.get("rescue_only"):
                return
            yield _record(item, pool_index, valid=False)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = StrictRootScanner(self.settings).scan(self.state, pool)

        self.assertFalse(catalog)
        self.assertEqual(catalog.roots, ())
        self.assertIsInstance(catalog.stats, CatalogStats)
        self.assertGreater(catalog.stats.rejection_count("plane_inclusion"), 0)
        self.assertEqual(catalog.stats.accepted_roots, 0)

        empty = StrictRootScanner(self.settings).scan(self.state, [])
        self.assertFalse(empty)
        self.assertEqual(empty.stats, CatalogStats())

    def test_rejected_proposal_is_diagnosed_once_without_second_validate_pass(self):
        class CountingMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.validate_calls = 0
                self.diagnose_calls = 0

            def validate(self, *args, **kwargs):
                self.validate_calls += 1
                return super().validate(*args, **kwargs)

            def diagnose(self, *args, **kwargs):
                self.diagnose_calls += 1
                return super().diagnose(*args, **kwargs)

        item = _item(121)
        pool = [item.to_dict()]
        counting = CountingMask(self.settings)

        def fake_records(_state, current, pool_index, **kwargs):
            if not kwargs.get("rescue_only"):
                yield _record(item, pool_index, valid=False)

        scanner = StrictRootScanner(self.settings, mask=counting)
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=fake_records,
        ):
            catalog = scanner.scan(self.state, pool)

        self.assertFalse(catalog)
        self.assertEqual(counting.validate_calls, 0)
        self.assertEqual(counting.diagnose_calls, 1)
        self.assertEqual(sum(dict(catalog.stats.stage_attempts).values()), 1)

    def test_catalog_is_standalone_and_has_no_approximate_or_planner_imports(self):
        import agents.support_extreme_fusion_beam_exact_mask.catalog as catalog_module

        source = inspect.getsource(catalog_module)
        forbidden = (
            "agents.highscore",
            ".planner",
            ".scoring",
            "CandidateGenerator",
            "validate_proposal",
            "random",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertIn("iter_fused_records", source)
        self.assertIn("ExactMask", source)


if __name__ == "__main__":
    unittest.main()
