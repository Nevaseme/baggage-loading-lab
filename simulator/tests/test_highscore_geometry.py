import math
import pathlib
import sys
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.geometry import (  # noqa: E402
    aabb_from_pose,
    box_inside_planes,
    depth_map_path_clear,
    effective_transport_lift,
    oriented_dimensions,
    support_metrics,
    transport_path_clear,
)
from agents.highscore.model import AABB, Rect  # noqa: E402


class OrientationTests(unittest.TestCase):
    def test_six_orientations_match_the_official_dimension_permutations(self):
        dims = (0.75, 0.56, 0.27)
        expected = [
            (0.75, 0.56, 0.27),
            (0.75, 0.27, 0.56),
            (0.27, 0.56, 0.75),
            (0.56, 0.75, 0.27),
            (0.56, 0.27, 0.75),
            (0.27, 0.75, 0.56),
        ]
        self.assertEqual([oriented_dimensions(dims, i) for i in range(6)], expected)

    def test_quaternion_pose_is_converted_to_a_local_conservative_aabb(self):
        angle = math.pi / 2.0
        quat = (0.0, 0.0, math.sin(angle / 2.0), math.cos(angle / 2.0))
        box = aabb_from_pose(
            world_center=(2.25, 0.1, 0.5),
            dimensions=(0.8, 0.4, 0.2),
            quaternion=quat,
            container_offset_x=2.0,
        )
        np.testing.assert_allclose(box.minimum, (0.05, -0.3, 0.4), atol=1e-9)
        np.testing.assert_allclose(box.maximum, (0.45, 0.5, 0.6), atol=1e-9)
        self.assertTrue(box.axis_aligned)


class FeasibilityTests(unittest.TestCase):
    def test_transport_lift_is_clipped_beneath_the_shelf_like_the_official_validator(self):
        lift = effective_transport_lift(
            bottom_z=0.548,
            top_z=0.788,
            resting_surfaces=(0.05, 0.86),
            ceiling_surfaces=(0.81, 1.57),
            requested_lift=0.08,
            ceiling_margin=0.018,
        )
        self.assertAlmostEqual(lift, 0.0035)

    def test_plane_inclusion_uses_the_requested_negative_margin(self):
        points = np.array(
            [
                [1.0, 0.0, 0.0],
                [-1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, -1.0, 0.0],
                [0.0, 0.0, 1.0],
                [0.0, 0.0, 0.0],
            ]
        )
        normals = np.array(
            [
                [1.0, 0.0, 0.0],
                [-1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, -1.0, 0.0],
                [0.0, 0.0, 1.0],
                [0.0, 0.0, -1.0],
            ]
        )
        self.assertTrue(
            box_inside_planes((0.0, 0.0, 0.5), (0.4, 0.4, 0.4), points, normals, -0.008)
        )
        self.assertFalse(
            box_inside_planes((0.6, 0.0, 0.5), (0.4, 0.4, 0.4), points, normals, -0.008)
        )

    def test_support_metrics_use_union_area_and_center_margin(self):
        footprint = Rect(-0.5, 0.5, -0.4, 0.4)
        supports = [
            Rect(-0.5, 0.0, -0.4, 0.4),
            Rect(0.0, 0.5, -0.4, 0.4),
        ]
        ratio, center_supported = support_metrics(footprint, supports, center_margin=0.02)
        self.assertAlmostEqual(ratio, 1.0)
        self.assertTrue(center_supported)

    def test_transport_path_checks_y_then_x_sweeps(self):
        candidate = AABB.from_center_half((0.4, 0.4, 0.5), (0.2, 0.2, 0.1))
        y_blocker = AABB.from_center_half((0.0, -0.1, 0.58), (0.15, 0.15, 0.1))
        x_blocker = AABB.from_center_half((0.2, 0.4, 0.58), (0.08, 0.15, 0.1))

        self.assertFalse(
            transport_path_clear(candidate, [y_blocker], door_y=-1.0, start_x=0.0, lift=0.08, clearance=0.018)
        )
        self.assertFalse(
            transport_path_clear(candidate, [x_blocker], door_y=-1.0, start_x=0.0, lift=0.08, clearance=0.018)
        )
        self.assertTrue(
            transport_path_clear(candidate, [], door_y=-1.0, start_x=0.0, lift=0.08, clearance=0.018)
        )

    def test_depth_map_rejects_observation_in_front_of_a_modelled_packed_aabb(self):
        candidate = AABB.from_center_half((0.0, 0.3, 0.5), (0.2, 0.2, 0.1))
        packed = AABB.from_center_half((0.0, 0.2, 0.5), (0.1, 0.1, 0.1))
        depth_map = np.zeros((64, 64), dtype=np.float32)
        # For a 2.0 x 1.6 front view, this is the ray through x=0, z=0.5.
        depth_map[40:42, 31:33] = 0.20
        self.assertFalse(
            depth_map_path_clear(
                candidate,
                [packed],
                depth_map,
                container_length=2.0,
                container_width=1.5,
                container_height=1.6,
                container_center_z=0.8,
                start_x=0.0,
                lift=0.0,
                clearance=0.018,
            )
        )

        self.assertTrue(
            depth_map_path_clear(
                candidate,
                [],
                depth_map,
                container_length=2.0,
                container_width=1.5,
                container_height=1.6,
                container_center_z=0.8,
                start_x=0.0,
                lift=0.0,
                clearance=0.018,
            )
        )

        depth_map[40:42, 31:33] = 0.74
        self.assertTrue(
            depth_map_path_clear(
                candidate,
                [packed],
                depth_map,
                container_length=2.0,
                container_width=1.5,
                container_height=1.6,
                container_center_z=0.8,
                start_x=0.0,
                lift=0.0,
                clearance=0.018,
            )
        )

        depth_map[40:42, 31:33] = 1.45
        self.assertTrue(
            depth_map_path_clear(
                candidate,
                [packed],
                depth_map,
                container_length=2.0,
                container_width=1.5,
                container_height=1.6,
                container_center_z=0.8,
                start_x=0.0,
                lift=0.0,
                clearance=0.018,
            )
        )


if __name__ == "__main__":
    unittest.main()
