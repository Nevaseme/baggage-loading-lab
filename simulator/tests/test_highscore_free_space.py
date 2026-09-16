import pathlib
import sys
import time
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.free_space import grid_recovery_centres  # noqa: E402
from agents.highscore.model import AABB, Rect  # noqa: E402


class GridRecoveryTests(unittest.TestCase):
    def test_finds_interior_lane_left_between_obstacles(self):
        centres = grid_recovery_centres(
            supports=[Rect(0.0, 1.0, 0.0, 1.0)],
            bounds=Rect(0.0, 1.0, 0.0, 1.0),
            obstacles=[
                AABB.from_center_half((0.175, 0.5, 0.1), (0.175, 0.5, 0.1)),
                AABB.from_center_half((0.825, 0.5, 0.1), (0.175, 0.5, 0.1)),
            ],
            half=np.array([0.1, 0.1, 0.1]),
            bottom_z=0.0,
            step=0.1,
            clearance=0.02,
            limit=3,
            deadline=None,
        )

        self.assertTrue(centres)
        self.assertAlmostEqual(centres[0][0], 0.5)
        self.assertAlmostEqual(centres[0][1], 0.9)

    def test_rejects_footprint_that_bridges_an_unsupported_gap(self):
        centres = grid_recovery_centres(
            supports=[
                Rect(0.0, 0.45, 0.0, 1.0),
                Rect(0.55, 1.0, 0.0, 1.0),
            ],
            bounds=Rect(0.0, 1.0, 0.0, 1.0),
            obstacles=[],
            half=np.array([0.2, 0.2, 0.1]),
            bottom_z=0.0,
            step=0.1,
            clearance=0.0,
            limit=20,
            deadline=None,
        )

        self.assertFalse(any(0.4 <= x <= 0.6 for x, _ in centres))

    def test_ignores_obstacle_wholly_below_candidate_height(self):
        centres = grid_recovery_centres(
            supports=[Rect(0.0, 0.4, 0.0, 0.4)],
            bounds=Rect(0.0, 0.4, 0.0, 0.4),
            obstacles=[AABB.from_center_half((0.2, 0.2, 0.05), (0.2, 0.2, 0.05))],
            half=np.array([0.1, 0.1, 0.1]),
            bottom_z=0.2,
            step=0.1,
            clearance=0.02,
            limit=2,
            deadline=None,
        )

        self.assertEqual(centres[0], (0.2, 0.3))

    def test_returns_immediately_after_deadline(self):
        centres = grid_recovery_centres(
            supports=[Rect(-1.0, 1.0, -1.0, 1.0)],
            bounds=Rect(-1.0, 1.0, -1.0, 1.0),
            obstacles=[],
            half=np.array([0.1, 0.1, 0.1]),
            bottom_z=0.0,
            step=0.001,
            clearance=0.0,
            limit=100,
            deadline=time.perf_counter() - 1.0,
        )

        self.assertEqual(centres, [])


if __name__ == "__main__":
    unittest.main()
