import pathlib
import sys
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.candidates import CandidateGenerator  # noqa: E402
from agents.highscore.geometry import (  # noqa: E402
    box_inside_planes,
    effective_transport_lift,
    support_metrics,
    transport_path_clear,
)
from agents.highscore.model import AABB, ItemSpec  # noqa: E402
from agents.highscore.scoring import protection_rule_violations  # noqa: E402
from agents.highscore.settings import SearchSettings  # noqa: E402
from agents.highscore.state import build_packing_state  # noqa: E402


def container_dict(*, index=0, offset_x=0.0, shelf=False, prioritized=False, packed=None):
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    points = np.array(
        [
            [offset_x + length / 2 - thickness, 0.0, 0.0],
            [offset_x - length / 2 + thickness, 0.0, 0.0],
            [offset_x, width / 2 - thickness, 0.0],
            [offset_x, -width / 2 + thickness, 0.0],
            [offset_x, 0.0, height - thickness],
            [offset_x, 0.0, thickness],
        ],
        dtype=float,
    )
    normals = np.array(
        [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        dtype=float,
    )
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (offset_x, 0.0, height / 2),
        "points": points.tolist(),
        "n_vecs": normals.tolist(),
        "volume": 4.0,
        "shelf": shelf,
        "is_prioritized": prioritized,
        "packed_items": packed or [],
    }


def item_dict(index=0, *, soft=False, prioritized=False, pos=None, orn=None, belongs_to=None):
    return {
        "index": index,
        "length": 0.5,
        "width": 0.4,
        "height": 0.24,
        "mass": 10.0,
        "is_soft": soft,
        "is_prioritized": prioritized,
        "belongs_to": belongs_to,
        "pos": pos,
        "orn": orn,
    }


class StateBuilderTests(unittest.TestCase):
    def test_world_coordinates_are_normalized_to_each_container(self):
        packed = [
            item_dict(
                5,
                belongs_to=1,
                pos=(2.25, 0.2, 0.16),
                orn=(0.0, 0.0, 0.0, 1.0),
            )
        ]
        state = build_packing_state([container_dict(index=1, offset_x=2.0, packed=packed)])
        placed = state.containers[0].placed[0]
        np.testing.assert_allclose(placed.box.center, (0.25, 0.2, 0.16))
        np.testing.assert_allclose(state.containers[0].points[0], (0.96, 0.0, 0.0))

    def test_shelf_and_small_shelf_are_reconstructed_as_static_obstacles(self):
        state = build_packing_state([container_dict(shelf=True)])
        container = state.containers[0]
        self.assertEqual(len(container.static_obstacles), 2)
        self.assertTrue(any(abs(box.maximum[2] - 0.84) < 1e-9 for box in container.static_obstacles))

    def test_buffer_is_inferred_from_the_floor_plane_when_observation_omits_it(self):
        raw = container_dict()
        raw["points"][5][2] = 0.05
        state = build_packing_state([raw])

        self.assertAlmostEqual(state.containers[0].buffer, 0.01)
        item = ItemSpec.from_dict(item_dict())
        candidates = CandidateGenerator(SearchSettings()).generate(state, item, pool_index=0)
        self.assertTrue(candidates)
        self.assertAlmostEqual(min(candidate.box.minimum[2] for candidate in candidates), 0.058)


class ProtectionTests(unittest.TestCase):
    def test_priority_and_soft_rules_are_independent(self):
        below_both = ItemSpec.from_dict(item_dict(1, soft=True, prioritized=True))
        rigid_priority = ItemSpec.from_dict(item_dict(2, prioritized=True))
        soft_normal = ItemSpec.from_dict(item_dict(3, soft=True))
        both = ItemSpec.from_dict(item_dict(4, soft=True, prioritized=True))

        self.assertEqual(protection_rule_violations(rigid_priority, [below_both]), 1)
        self.assertEqual(protection_rule_violations(soft_normal, [below_both]), 1)
        self.assertEqual(protection_rule_violations(both, [below_both]), 0)


class CandidateGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.settings = SearchSettings()
        self.generator = CandidateGenerator(self.settings)

    def test_empty_container_has_a_supported_back_floor_candidate(self):
        state = build_packing_state([container_dict()])
        item = ItemSpec.from_dict(item_dict())
        candidates = self.generator.generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        best_back = max(candidates, key=lambda candidate: candidate.position[1])
        self.assertGreaterEqual(best_back.support_ratio, 0.75)
        self.assertAlmostEqual(best_back.box.minimum[2], 0.048, places=6)
        self.assertLessEqual(best_back.box.maximum[1], 0.75 - 0.04 - 0.008 + 1e-9)

    def test_monotone_floor_candidate_advances_in_front_of_overlapped_skyline(self):
        left_rear = item_dict(
            41,
            belongs_to=0,
            pos=(-0.45, 0.45, 0.16),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        left_rear["length"] = 0.7
        right_rear = item_dict(
            42,
            belongs_to=0,
            pos=(0.45, 0.25, 0.16),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        right_rear["length"] = 0.7
        state = build_packing_state([container_dict(packed=[left_rear, right_rear])])
        raw_item = item_dict(43)
        raw_item.update(length=0.75, width=0.2)
        item = ItemSpec.from_dict(raw_item)
        settings = SearchSettings(extra_margins=(0.0,), use_monotone_ingress=True)

        candidates = CandidateGenerator(settings).generate(state, item, pool_index=0)

        expected_back_face = 0.05 - settings.path_clearance
        spanning_floor = [
            candidate
            for candidate in candidates
            if candidate.orientation == 0
            and candidate.box.minimum[2] <= 0.04 + settings.support_height_tolerance
            and candidate.box.minimum[0] < -0.1
            and candidate.box.maximum[0] > 0.1
        ]
        self.assertTrue(spanning_floor)
        self.assertTrue(
            any(
                abs(float(candidate.box.maximum[1]) - expected_back_face) <= 1e-6
                for candidate in spanning_floor
            )
        )
        self.assertTrue(
            all(float(candidate.box.maximum[1]) <= expected_back_face + 1e-6 for candidate in spanning_floor)
        )

    def test_monotone_wide_item_spans_old_lane_boundary(self):
        state = build_packing_state([container_dict()])
        container = state.containers[0]
        floor_z = container.thickness + container.buffer
        container.static_obstacles = [
            AABB.from_center_half((-0.45, 0.45, 0.16), (0.35, 0.20, 0.12)),
            AABB.from_center_half((0.45, 0.25, 0.16), (0.35, 0.20, 0.12)),
        ]
        settings = SearchSettings(extra_margins=(0.0,), use_monotone_ingress=True)
        generator = CandidateGenerator(settings)
        raw_item = item_dict(44)
        raw_item.update(length=0.75, width=0.2)
        item = ItemSpec.from_dict(raw_item)

        candidates = generator.generate(state, item, pool_index=0)

        crossing = [
            candidate
            for candidate in candidates
            if candidate.orientation == 0
            and candidate.box.minimum[2] <= floor_z + settings.support_height_tolerance
            and candidate.box.minimum[0] < 0.0 < candidate.box.maximum[0]
        ]
        self.assertTrue(crossing)
        self.assertTrue(
            any(
                abs(float(candidate.box.maximum[1]) - (0.05 - settings.path_clearance)) <= 1e-6
                for candidate in crossing
            )
        )

    def test_disabling_monotone_ingress_preserves_legacy_floor_candidates(self):
        state = build_packing_state([container_dict()])
        item = ItemSpec.from_dict(item_dict())
        settings = SearchSettings(use_monotone_ingress=False)

        candidates = CandidateGenerator(settings).generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].orientation, 0)
        np.testing.assert_allclose(candidates[0].position, (-0.689, 0.489, 0.168), atol=1e-9)

    def test_monotone_candidates_still_pass_all_hard_checks(self):
        left_rear = item_dict(
            51,
            belongs_to=0,
            pos=(-0.45, 0.45, 0.16),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        left_rear["length"] = 0.7
        right_rear = item_dict(
            52,
            belongs_to=0,
            pos=(0.45, 0.25, 0.16),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        right_rear["length"] = 0.7
        state = build_packing_state([container_dict(packed=[left_rear, right_rear])])
        container = state.containers[0]
        raw_item = item_dict(53)
        raw_item.update(length=0.75, width=0.2)
        item = ItemSpec.from_dict(raw_item)
        settings = SearchSettings(extra_margins=(0.0,), use_monotone_ingress=True)
        generator = CandidateGenerator(settings)

        candidates = generator.generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        floor_z = container.thickness + container.buffer
        shelf_top = container.height / 2.0 + container.thickness + container.buffer
        obstacles = [placed.box for placed in container.placed] + container.static_obstacles
        for candidate in candidates:
            self.assertTrue(
                box_inside_planes(
                    candidate.box.center,
                    candidate.box.half,
                    container.points,
                    container.normals,
                    settings.inclusion_margin,
                )
            )
            supports, _ = generator._supports(container, candidate.box, floor_z, shelf_top)
            support_ratio, center_supported = support_metrics(
                candidate.box.footprint,
                supports,
                settings.center_support_margin,
            )
            self.assertGreaterEqual(support_ratio + 1e-9, settings.rigid_support_relaxations[0])
            self.assertTrue(center_supported)
            lift = effective_transport_lift(
                bottom_z=float(candidate.box.minimum[2]),
                top_z=float(candidate.box.maximum[2]),
                resting_surfaces=(floor_z, shelf_top),
                ceiling_surfaces=(
                    container.height / 2.0 + container.buffer,
                    container.height + container.buffer - container.thickness,
                ),
                requested_lift=0.08,
                ceiling_margin=settings.path_clearance,
            )
            half = candidate.box.half
            start_x = min(
                max(
                    float(candidate.box.center[0]),
                    -container.length / 2.0
                    + container.thickness
                    + container.cut_x
                    + half[0]
                    + 0.01,
                ),
                container.length / 2.0 - container.thickness - half[0] - 0.01,
            )
            self.assertTrue(
                transport_path_clear(
                    candidate.box,
                    obstacles,
                    door_y=-container.width / 2.0 + half[1],
                    start_x=start_x,
                    lift=lift,
                    clearance=settings.path_clearance,
                )
            )

    def test_coincident_stack_height_does_not_restore_unrelated_legacy_base_positions(self):
        packed = item_dict(
            61,
            belongs_to=0,
            pos=(0.55, 0.4, 0.742),
            orn=(0.0, 0.0, 0.0, 1.0),
        )
        packed.update(length=0.3, width=0.3)
        state = build_packing_state([container_dict(shelf=True, packed=[packed])])
        container = state.containers[0]
        item = ItemSpec.from_dict(item_dict(62))
        settings = SearchSettings(
            extra_margins=(0.0,),
            front_floor_release_fill=0.0,
            use_monotone_ingress=True,
        )
        generator = CandidateGenerator(settings)
        half = np.asarray(item.dimensions, dtype=np.float64) * 0.5
        coincident_bottom = (
            container.height / 2.0
            + container.thickness
            + container.buffer
            + settings.shelf_drop_gap
        )
        monotone_positions = {
            tuple(round(float(value), 6) for value in position)
            for position in generator._monotone_base_positions(
                container,
                half,
                coincident_bottom,
                0.0,
            )
        }

        candidates = generator.generate(state, item, pool_index=0)

        coincident = [
            candidate
            for candidate in candidates
            if candidate.orientation == 0
            and abs(float(candidate.box.minimum[2]) - coincident_bottom) <= 1e-6
        ]
        self.assertTrue(coincident)
        placed_footprint = container.placed[0].box.footprint
        unrelated = [
            candidate
            for candidate in coincident
            if candidate.box.footprint.intersection(placed_footprint) is None
        ]
        self.assertTrue(unrelated)
        self.assertTrue(
            all(
                tuple(round(float(value), 6) for value in candidate.position)
                in monotone_positions
                for candidate in unrelated
            )
        )

    def test_candidates_keep_eighteen_millimetres_from_axis_aligned_walls(self):
        state = build_packing_state([container_dict()])
        item = ItemSpec.from_dict(item_dict())
        candidates = self.generator.generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertGreaterEqual(candidate.box.minimum[0], -1.0 + 0.04 + 0.018 - 1e-9)
            self.assertLessEqual(candidate.box.maximum[0], 1.0 - 0.04 - 0.018 + 1e-9)
            self.assertGreaterEqual(candidate.box.minimum[1], -0.75 + 0.04 + 0.018 - 1e-9)
            self.assertLessEqual(candidate.box.maximum[1], 0.75 - 0.04 - 0.018 + 1e-9)

    def test_floor_frontier_does_not_advance_two_rows_in_only_one_x_lane(self):
        packed = [
            item_dict(
                31,
                belongs_to=0,
                pos=(-0.5, 0.4, 0.16),
                orn=(0.0, 0.0, 0.0, 1.0),
            )
        ]
        state = build_packing_state([container_dict(packed=packed)])
        item = ItemSpec.from_dict(item_dict())
        candidates = self.generator.generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        floor_candidates = [
            candidate
            for candidate in candidates
            if candidate.box.minimum[2] < 0.04 + self.settings.support_height_tolerance
        ]
        self.assertTrue(floor_candidates)
        self.assertFalse(
            any(
                candidate.position[0] < 0.0 and candidate.box.minimum[1] < -0.1
                for candidate in floor_candidates
            )
        )
        self.assertTrue(any(candidate.position[0] > 0.0 for candidate in floor_candidates))

    def test_front_half_floor_is_reserved_until_back_and_shelf_skeleton_is_built(self):
        state = build_packing_state([container_dict(shelf=True)])
        item = ItemSpec.from_dict(item_dict())
        candidates = self.generator.generate(state, item, pool_index=0)
        floor_candidates = [
            candidate
            for candidate in candidates
            if candidate.box.minimum[2] < 0.04 + self.settings.support_height_tolerance
        ]

        self.assertTrue(floor_candidates)
        self.assertTrue(all(candidate.box.minimum[1] >= 0.0 for candidate in floor_candidates))

    def test_rigid_normal_item_is_not_generated_on_top_of_soft_priority_item(self):
        packed = [
            item_dict(
                8,
                soft=True,
                prioritized=True,
                belongs_to=0,
                pos=(0.0, 0.35, 0.16),
                orn=(0.0, 0.0, 0.0, 1.0),
            )
        ]
        state = build_packing_state([container_dict(packed=packed)])
        item = ItemSpec.from_dict(item_dict(9))
        candidates = self.generator.generate(state, item, pool_index=0)

        protected_top = state.containers[0].placed[0].box.maximum[2]
        self.assertTrue(candidates)
        self.assertTrue(all(abs(candidate.box.minimum[2] - protected_top) > 1e-6 for candidate in candidates))

    def test_item_stack_candidates_use_vertical_contact_without_a_drop_gap(self):
        packed = [
            item_dict(
                8,
                belongs_to=0,
                pos=(0.0, 0.35, 0.16),
                orn=(0.0, 0.0, 0.0, 1.0),
            )
        ]
        state = build_packing_state([container_dict(packed=packed)])
        item = ItemSpec.from_dict(item_dict(9))
        candidates = self.generator.generate(state, item, pool_index=0)
        top = state.containers[0].placed[0].box.maximum[2]
        stacked = [
            candidate
            for candidate in candidates
            if abs(candidate.box.minimum[2] - top) <= self.settings.support_height_tolerance
        ]

        self.assertTrue(stacked)
        self.assertAlmostEqual(min(abs(candidate.box.minimum[2] - top) for candidate in stacked), 0.0)

    def test_priority_item_is_only_assigned_to_designated_container(self):
        state = build_packing_state(
            [container_dict(index=0), container_dict(index=1, offset_x=2.0, prioritized=True)]
        )
        item = ItemSpec.from_dict(item_dict(7, prioritized=True))
        candidates = self.generator.generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        self.assertEqual({candidate.container_index for candidate in candidates}, {1})

    def test_shelf_candidates_clear_the_official_transport_margin_then_settle(self):
        state = build_packing_state([container_dict(shelf=True)])
        item = ItemSpec.from_dict(item_dict())
        candidates = self.generator.generate(state, item, pool_index=0)
        shelf_top = 0.8 + 0.04
        shelf_candidates = [
            candidate
            for candidate in candidates
            if candidate.box.minimum[2] > shelf_top + 0.015
        ]

        self.assertTrue(shelf_candidates)
        self.assertAlmostEqual(
            min(candidate.box.minimum[2] for candidate in shelf_candidates),
            shelf_top + self.settings.shelf_drop_gap,
        )

    def test_container_without_main_shelf_only_supports_mid_level_on_small_shelf(self):
        state = build_packing_state([container_dict(shelf=False)])
        item = ItemSpec.from_dict(item_dict())
        candidates = self.generator.generate(state, item, pool_index=0)
        shelf_top = 0.8 + 0.04
        mid_level = [
            candidate
            for candidate in candidates
            if abs(candidate.box.minimum[2] - shelf_top)
            <= self.settings.shelf_drop_gap + self.settings.support_height_tolerance
        ]
        small_shelf = state.containers[0].static_obstacles[0]

        self.assertTrue(
            all(
                candidate.box.footprint.intersection(small_shelf.footprint) is not None
                for candidate in mid_level
            )
        )

    def test_grid_recovery_finds_central_floor_lane_missed_by_limited_extreme_points(self):
        settings = SearchSettings(
            coordinate_limit=2,
            fallback_coordinate_limit=2,
            recovery_candidate_limit=12,
            recovery_candidates_per_orientation=3,
        )
        state = build_packing_state([container_dict()])
        state.containers[0].static_obstacles = [
            AABB.from_center_half((-0.70, 0.0, 0.77), (0.25, 0.65, 0.72)),
            AABB.from_center_half((0.70, 0.0, 0.77), (0.25, 0.65, 0.72)),
        ]
        item = ItemSpec.from_dict(item_dict())

        candidates = CandidateGenerator(settings).generate(state, item, pool_index=0)

        self.assertTrue(candidates)
        self.assertTrue(any(abs(candidate.position[0]) <= 0.05 for candidate in candidates))
        self.assertTrue(all(candidate.support_ratio >= settings.rigid_support_relaxations[-1] for candidate in candidates))
        for orientation in range(6):
            self.assertLessEqual(
                sum(candidate.orientation == orientation for candidate in candidates),
                settings.recovery_candidates_per_orientation,
            )


if __name__ == "__main__":
    unittest.main()
