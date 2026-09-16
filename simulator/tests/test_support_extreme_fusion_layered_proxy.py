from __future__ import annotations

import ast
import dataclasses
import math
import pathlib
import sys
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    LayeredProxy,
    OccurrenceKey,
    ProtectionTag,
    ProxyWork,
    ProxyWorkQuota,
    maximal_empty_rectangles,
)
from agents.support_extreme_fusion_beam_exact_mask.model import AABB, ItemSpec, Rect  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState  # noqa: E402


def _container(*, shelf: bool = False, packed=()) -> dict:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": 17,
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
        "shelf": shelf,
        "is_prioritized": False,
        "packed_items": list(packed),
    }


def _raw_item(
    index: int,
    *,
    length: float = 0.20,
    width: float = 0.16,
    height: float = 0.12,
    mass: float = 2.0,
    prioritized: bool = False,
    soft: bool = False,
    pos=None,
    orn=None,
) -> dict:
    value = {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "mass": mass,
        "is_prioritized": prioritized,
        "is_soft": soft,
    }
    if pos is not None:
        value["pos"] = tuple(pos)
    if orn is not None:
        value["orn"] = tuple(orn)
    return value


def _proxy(container: dict, pool: tuple[dict, ...]):
    packing = build_packing_state([container])
    sim = SimState.from_current(packing, pool)
    engine = LayeredProxy()
    return engine, engine.from_sim_state(sim)


class LayeredProxyGeometryTests(unittest.TestCase):
    def test_floor_shelf_and_aligned_top_offsets_are_exact(self) -> None:
        placed = _raw_item(
            90,
            pos=(0.55, 0.45, 0.148),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        engine, state = _proxy(_container(shelf=True, packed=(placed,)), (_raw_item(1),))
        del engine
        supports = state.containers[0].supports
        floor = next(patch for patch in supports if patch.source == "floor")
        shelves = tuple(patch for patch in supports if patch.source == "shelf")
        top = next(patch for patch in supports if patch.source == "placed_top")

        self.assertAlmostEqual(floor.placement_offset, 0.008, places=12)
        self.assertTrue(shelves)
        self.assertTrue(all(abs(patch.placement_offset - 0.022) < 1e-12 for patch in shelves))
        self.assertAlmostEqual(top.placement_offset, 0.0, places=12)
        self.assertEqual(top.tag, ProtectionTag(False, False))

    def test_tilted_item_is_obstacle_only(self) -> None:
        angle = math.radians(10.0)
        tilted = _raw_item(
            91,
            pos=(0.45, 0.35, 0.18),
            orn=(math.sin(angle / 2.0), 0.0, 0.0, math.cos(angle / 2.0)),
        )
        _engine, state = _proxy(_container(packed=(tilted,)), (_raw_item(1),))
        container = state.containers[0]
        self.assertTrue(any(not box.box.axis_aligned for box in container.boxes))
        self.assertFalse(any(patch.source == "placed_top" for patch in container.supports))

    def test_priority_soft_and_combined_tags_are_independent(self) -> None:
        normal = ProtectionTag(False, False)
        priority = ProtectionTag(True, False)
        soft = ProtectionTag(False, True)
        both = ProtectionTag(True, True)
        self.assertTrue(normal.allows(normal))
        self.assertFalse(priority.allows(normal))
        self.assertTrue(priority.allows(priority))
        self.assertFalse(soft.allows(priority))
        self.assertTrue(soft.allows(soft))
        self.assertFalse(both.allows(priority))
        self.assertFalse(both.allows(soft))
        self.assertTrue(both.allows(both))

        for lower_flags, upper_flags, accepted in (
            ((True, False), (False, False), False),
            ((True, False), (True, False), True),
            ((False, True), (True, False), False),
            ((False, True), (False, True), True),
            ((True, True), (True, False), False),
            ((True, True), (False, True), False),
            ((True, True), (True, True), True),
        ):
            with self.subTest(lower=lower_flags, upper=upper_flags):
                lower = _raw_item(
                    50,
                    length=0.30,
                    width=0.25,
                    height=0.20,
                    prioritized=lower_flags[0],
                    soft=lower_flags[1],
                    pos=(0.0, 0.40, 0.148),
                    orn=(0, 0, 0, 1),
                )
                upper = _raw_item(
                    51,
                    length=0.25,
                    width=0.20,
                    height=0.12,
                    prioritized=upper_flags[0],
                    soft=upper_flags[1],
                )
                engine, state = _proxy(_container(packed=(lower,)), (upper,))
                candidate, _ = engine.check_candidate(
                    state,
                    state.remaining[0].key,
                    0,
                    0,
                    (0.0, 0.40, 0.308),
                    ProxyWork(),
                    ProxyWorkQuota(),
                )
                self.assertEqual(candidate is not None, accepted)

    def test_six_orientations_are_dimension_deduplicated(self) -> None:
        engine = LayeredProxy()
        cube = ItemSpec.from_dict(_raw_item(1, length=0.2, width=0.2, height=0.2))
        distinct = ItemSpec.from_dict(_raw_item(2, length=0.2, width=0.3, height=0.4))
        self.assertEqual(engine.orientation_options(cube), ((0, (0.2, 0.2, 0.2)),))
        self.assertEqual(len(engine.orientation_options(distinct)), 6)

    def test_maximal_rectangle_spans_artificial_obstacle_partition(self) -> None:
        base = Rect(0.0, 10.0, 0.0, 10.0)
        blocker = Rect(4.0, 6.0, 6.0, 10.0)
        rectangles = maximal_empty_rectangles(base, (blocker,), limit=64)
        self.assertIn(Rect(0.0, 10.0, 0.0, 6.0), rectangles)
        self.assertFalse(any(
            rectangle.min_x == 0.0 and rectangle.max_x == 4.0
            and rectangle.min_y == 0.0 and rectangle.max_y == 6.0
            for rectangle in rectangles
        ))

    def test_support_union_accepts_seam_but_center_core_rejects_gap(self) -> None:
        left = _raw_item(10, length=0.20, width=0.20, height=0.20, pos=(-0.10, 0.40, 0.148), orn=(0, 0, 0, 1))
        right = _raw_item(11, length=0.20, width=0.20, height=0.20, pos=(0.10, 0.40, 0.148), orn=(0, 0, 0, 1))
        upper = _raw_item(12, length=0.40, width=0.20, height=0.12)
        engine, state = _proxy(_container(packed=(left, right)), (upper,))
        key = state.remaining[0].key
        accepted, _work = engine.check_candidate(
            state, key, 0, 0, (0.0, 0.40, 0.248 + 0.06), ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNotNone(accepted)
        self.assertAlmostEqual(accepted.support_ratio, 1.0, places=8)

        gap_left = _raw_item(20, length=0.17, width=0.20, height=0.20, pos=(-0.115, 0.40, 0.148), orn=(0, 0, 0, 1))
        gap_right = _raw_item(21, length=0.17, width=0.20, height=0.20, pos=(0.115, 0.40, 0.148), orn=(0, 0, 0, 1))
        engine2, state2 = _proxy(_container(packed=(gap_left, gap_right)), (upper,))
        rejected, _ = engine2.check_candidate(
            state2, state2.remaining[0].key, 0, 0,
            (0.0, 0.40, 0.248 + 0.06), ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNone(rejected)

    def test_headroom_horizontal_clearance_and_yx_ingress_are_conservative(self) -> None:
        overhead = _raw_item(30, length=0.50, width=0.50, height=0.10, pos=(0.0, 0.35, 0.50), orn=(0, 0, 0, 1))
        tall = _raw_item(31, length=0.20, width=0.20, height=0.60)
        engine, state = _proxy(_container(packed=(overhead,)), (tall,))
        candidate, _ = engine.check_candidate(
            state, state.remaining[0].key, 0, 0, (0.0, 0.35, 0.048 + 0.30),
            ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNone(candidate)

        door_block = _raw_item(32, length=0.30, width=0.20, height=0.40, pos=(0.0, -0.55, 0.248), orn=(0, 0, 0, 1))
        small = _raw_item(33, length=0.20, width=0.20, height=0.12)
        engine2, state2 = _proxy(_container(packed=(door_block,)), (small,))
        blocked, _ = engine2.check_candidate(
            state2, state2.remaining[0].key, 0, 0, (0.0, 0.50, 0.108),
            ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNone(blocked)

        side_block = _raw_item(34, length=0.20, width=0.20, height=0.12, pos=(0.0, 0.40, 0.108), orn=(0, 0, 0, 1))
        engine3, state3 = _proxy(_container(packed=(side_block,)), (small,))
        too_close, _ = engine3.check_candidate(
            state3, state3.remaining[0].key, 0, 0, (0.217, 0.40, 0.108),
            ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNone(too_close)
        exact_clearance, _ = engine3.check_candidate(
            state3, state3.remaining[0].key, 0, 0, (0.219, 0.40, 0.108),
            ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNotNone(exact_clearance)


class LayeredProxyTransitionTests(unittest.TestCase):
    def test_enumeration_has_back_front_side_anchors_and_obeys_fit_quota(self) -> None:
        engine, state = _proxy(_container(), (_raw_item(1, length=0.30, width=0.20),))
        batch = engine.enumerate_candidates(
            state, state.remaining[0].key, ProxyWork(), ProxyWorkQuota(max_fit_tests=128)
        )
        anchors = {candidate.anchor for candidate in batch.candidates}
        self.assertTrue({"back", "front", "left", "right"}.issubset(anchors))
        self.assertEqual(batch.work.fit_tests, batch.attempted_fit_tests)

        limited = engine.enumerate_candidates(
            state, state.remaining[0].key, ProxyWork(), ProxyWorkQuota(max_fit_tests=1)
        )
        self.assertEqual(limited.work.fit_tests, 1)
        self.assertTrue(limited.work.quota_exhausted(ProxyWorkQuota(max_fit_tests=1)))

    def test_apply_is_immutable_adds_tagged_top_and_preserves_duplicate_occurrences(self) -> None:
        duplicate = _raw_item(7, prioritized=True, soft=True)
        engine, state = _proxy(_container(), (duplicate, duplicate))
        self.assertNotEqual(state.remaining[0].key, state.remaining[1].key)
        batch = engine.enumerate_candidates(
            state, state.remaining[0].key, ProxyWork(), ProxyWorkQuota(max_fit_tests=64)
        )
        candidate = batch.candidates[0]
        parent_fingerprint = state.fingerprint
        sibling = engine.apply(state, candidate)
        child = engine.apply(state, candidate)

        self.assertEqual(state.fingerprint, parent_fingerprint)
        self.assertEqual(len(state.remaining), 2)
        self.assertEqual(len(child.remaining), 1)
        self.assertEqual(child.remaining[0].key, state.remaining[1].key)
        self.assertEqual(child.fingerprint, sibling.fingerprint)
        self.assertNotEqual(child.fingerprint, state.fingerprint)
        top = child.containers[0].supports[-1]
        self.assertEqual(top.source, "proxy_top")
        self.assertEqual(top.tag, ProtectionTag(True, True))

        forged = dataclasses.replace(
            candidate,
            position=(0.0, 0.0, 10.0),
            box=AABB.from_center_half((0.0, 0.0, 10.0), candidate.box.half),
        )
        with self.assertRaises(ValueError):
            engine.apply(state, forged)

    def test_back_placement_preserves_larger_region_and_metrics_are_finite(self) -> None:
        item = _raw_item(40, length=0.50, width=0.30, height=0.20, mass=8.0)
        engine, state = _proxy(_container(), (item,))
        key = state.remaining[0].key
        z = 0.048 + 0.10
        back, _ = engine.check_candidate(
            state, key, 0, 0, (0.0, 0.55, z), ProxyWork(), ProxyWorkQuota()
        )
        center, _ = engine.check_candidate(
            state, key, 0, 0, (0.0, 0.0, z), ProxyWork(), ProxyWorkQuota()
        )
        self.assertIsNotNone(back)
        self.assertIsNotNone(center)
        back_metrics = engine.metrics(engine.apply(state, back))
        center_metrics = engine.metrics(engine.apply(state, center))
        self.assertGreater(back_metrics.largest_free_region, center_metrics.largest_free_region)
        self.assertGreater(back_metrics.sliver_area, 0.0)
        self.assertLess(back_metrics.low_mass_cog_goodness, 1.0)
        self.assertLess(back_metrics.low_stack, 1.0)
        for value in vars(back_metrics).values():
            self.assertTrue(math.isfinite(float(value)))
            self.assertGreaterEqual(float(value), 0.0)
            self.assertLessEqual(float(value), 1.0)

    def test_protection_capacity_counts_unrestricted_support(self) -> None:
        engine, state = _proxy(_container(), (_raw_item(51),))
        metrics = engine.metrics(state)

        self.assertGreater(metrics.protection_compatible_capacity, 0.0)
        self.assertAlmostEqual(
            metrics.protection_compatible_capacity,
            metrics.compatible_support_capacity,
            places=12,
        )

    def test_protection_capacity_excludes_incompatible_tagged_top(self) -> None:
        prioritized = _raw_item(
            52,
            length=0.80,
            width=0.80,
            height=0.20,
            prioritized=True,
            pos=(0.0, 0.20, 0.148),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        normal = _raw_item(53, length=0.50, width=0.50, height=0.12)
        engine, state = _proxy(_container(packed=(prioritized,)), (normal,))

        metrics = engine.metrics(state)

        self.assertGreater(metrics.compatible_support_capacity, 0.0)
        self.assertGreater(metrics.protection_compatible_capacity, 0.80)
        self.assertLess(
            metrics.protection_compatible_capacity,
            metrics.compatible_support_capacity,
        )

        compatible_engine, compatible_state = _proxy(
            _container(packed=(prioritized,)),
            (_raw_item(54, prioritized=True),),
        )
        compatible_metrics = compatible_engine.metrics(compatible_state)
        self.assertAlmostEqual(
            compatible_metrics.protection_compatible_capacity,
            compatible_metrics.compatible_support_capacity,
            places=12,
        )

    def test_work_accounting_and_fingerprint_are_stable_and_bounded(self) -> None:
        quota = ProxyWorkQuota(max_nodes=2, max_fit_tests=3)
        work = ProxyWork().consume_node(quota).consume_node(quota)
        self.assertEqual(work.nodes, 2)
        self.assertTrue(work.quota_exhausted(quota))
        with self.assertRaises(RuntimeError):
            work.consume_node(quota)
        fit = ProxyWork().consume_fit(quota).consume_fit(quota).consume_fit(quota)
        self.assertEqual(fit.fit_tests, 3)
        with self.assertRaises(RuntimeError):
            fit.consume_fit(quota)

        engine, state = _proxy(_container(), (_raw_item(1),))
        rebuilt = engine.from_sim_state(
            SimState.from_current(build_packing_state([_container()]), (_raw_item(1),))
        )
        self.assertEqual(state.fingerprint, rebuilt.fingerprint)

    def test_module_cannot_import_or_construct_receipts_or_actions(self) -> None:
        path = SIMULATOR_ROOT / "agents/support_extreme_fusion_beam_exact_mask/layered_proxy.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = ("highscore", "ems", "mcts", "beam", "fixed_quota", "catalog", "mask")
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, (ast.ImportFrom,))
        ]
        self.assertFalse(any(any(word in module.lower() for word in forbidden) for module in imports))
        self.assertNotIn("ValidatedRoot", source)
        dict_keys = {
            key.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertFalse({"item_idx", "container_idx", "place_pos", "orientation"}.issubset(dict_keys))


if __name__ == "__main__":
    unittest.main()
