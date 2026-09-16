import pathlib
import sys
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.ingress import (  # noqa: E402
    XFrontier,
    build_frontier,
    candidate_x_intervals,
    maximum_free_opening,
)
from agents.highscore.model import AABB, ContainerState, ItemSpec, PlacedItem  # noqa: E402


def _container(*, placed=None, static_obstacles=None):
    return ContainerState(
        index=0,
        length=2.0,
        width=1.6,
        height=1.4,
        thickness=0.1,
        cut_x=0.0,
        cut_y=0.0,
        center=(0.0, 0.0, 0.7),
        points=np.empty((0, 3)),
        normals=np.empty((0, 3)),
        volume=4.48,
        placed=list(placed or []),
        static_obstacles=list(static_obstacles or []),
    )


def _assert_frontier(test_case, actual, expected):
    test_case.assertEqual(len(actual), len(expected))
    for segment, wanted in zip(actual, expected):
        test_case.assertAlmostEqual(segment.min_x, wanted.min_x)
        test_case.assertAlmostEqual(segment.max_x, wanted.max_x)
        test_case.assertAlmostEqual(segment.front_y, wanted.front_y)


class FreeOpeningTests(unittest.TestCase):
    def test_maximum_free_opening_matches_saved_terminal_aperture(self):
        opening = maximum_free_opening(
            [(-0.513, 0.238), (0.529, 0.929)], -0.93, 0.93
        )
        self.assertAlmostEqual(opening, 0.417)
        self.assertLess(opening, 0.55 + 2.0 * 0.015)

    def test_maximum_free_opening_clips_and_merges_adjacent_blockers(self):
        opening = maximum_free_opening(
            [(-1.4, -0.6), (-0.6, -0.2), (0.5, 1.4)], -1.0, 1.0
        )
        self.assertAlmostEqual(opening, 0.7)

    def test_maximum_free_opening_preserves_a_positive_sub_tolerance_gap(self):
        opening = maximum_free_opening(
            [(-1.0, 0.0), (0.0000005, 1.0)], -1.0, 1.0
        )
        self.assertAlmostEqual(opening, 0.0000005)


class FrontierTests(unittest.TestCase):
    def test_empty_container_frontier_uses_the_usable_back_wall(self):
        frontier = build_frontier(_container(), 0.2, 0.6, 0.02, 1e-6)
        _assert_frontier(self, frontier, (XFrontier(-0.9, 0.9, 0.7),))

    def test_frontier_separates_obstacles_by_the_requested_z_band(self):
        lower = AABB.from_center_half((0.0, 0.2, 0.15), (0.2, 0.1, 0.15))
        upper = AABB.from_center_half((0.0, 0.35, 0.75), (0.2, 0.1, 0.15))
        container = _container(static_obstacles=[lower, upper])

        lower_frontier = build_frontier(container, 0.0, 0.3, 0.02, 1e-6)
        upper_frontier = build_frontier(container, 0.6, 0.9, 0.02, 1e-6)

        _assert_frontier(self, lower_frontier, (
            XFrontier(-0.9, -0.2, 0.7),
            XFrontier(-0.2, 0.2, 0.1),
            XFrontier(0.2, 0.9, 0.7),
        ))
        _assert_frontier(self, upper_frontier, (
            XFrontier(-0.9, -0.2, 0.7),
            XFrontier(-0.2, 0.2, 0.25),
            XFrontier(0.2, 0.9, 0.7),
        ))

    def test_tilted_placed_aabb_is_still_a_frontier_obstacle(self):
        tilted = AABB.from_center_half((0.0, 0.24, 0.5), (0.2, 0.1, 0.2), axis_aligned=False)
        placed = PlacedItem(ItemSpec(0, 0.4, 0.2, 0.4), tilted)

        frontier = build_frontier(_container(placed=[placed]), 0.3, 0.7, 0.02, 1e-6)

        _assert_frontier(self, frontier, (
            XFrontier(-0.9, -0.2, 0.7),
            XFrontier(-0.2, 0.2, 0.14),
            XFrontier(0.2, 0.9, 0.7),
        ))


class CandidateIntervalTests(unittest.TestCase):
    def test_wide_footprint_uses_most_advanced_overlapping_frontier(self):
        frontier = (
            XFrontier(-0.9, -0.1, 0.45),
            XFrontier(-0.1, 0.9, 0.20),
        )
        fits = candidate_x_intervals(frontier, 0.8, -0.9, 0.9)
        spanning = min(fits, key=lambda fit: abs(fit[0]))
        self.assertAlmostEqual(spanning[1], 0.20)

    def test_candidate_intervals_include_wall_boundary_and_centred_fits(self):
        frontier = (
            XFrontier(-0.9, -0.3, 0.6),
            XFrontier(-0.3, 0.9, 0.2),
        )

        fits = candidate_x_intervals(frontier, 0.6, -0.9, 0.9)

        self.assertEqual(len(fits), 4)
        for fit, expected in zip(
            fits,
            ((-0.9, 0.6), (-0.3, 0.2), (0.0, 0.2), (0.3, 0.2)),
        ):
            self.assertAlmostEqual(fit[0], expected[0])
            self.assertAlmostEqual(fit[1], expected[1])

    def test_candidate_intervals_reject_a_footprint_even_slightly_wider_than_walls(self):
        fits = candidate_x_intervals(
            (XFrontier(-0.5, 0.5, 0.4),), 1.0000005, -0.5, 0.5
        )
        self.assertEqual(fits, ())

    def test_candidate_interval_counts_a_positive_sub_tolerance_frontier_overlap(self):
        frontier = (
            XFrontier(-0.5, 0.0000004, 0.6),
            XFrontier(0.0000004, 0.5, 0.2),
        )

        fits = candidate_x_intervals(frontier, 0.5000005, -0.5, 0.5)

        left_wall_fit = min(fits, key=lambda fit: fit[0])
        self.assertAlmostEqual(left_wall_fit[0], -0.5)
        self.assertAlmostEqual(left_wall_fit[1], 0.2)


if __name__ == "__main__":
    unittest.main()
