from __future__ import annotations

import time
import unittest

import numpy as np

from agents.support_extreme_fusion_beam_exact_mask.model import (
    AABB,
    ContainerState,
    ItemSpec,
    PackingState,
    PlacedItem,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (
    ProposalSource,
    iter_fused_proposals,
)


def _container(*, shelf: bool = False, index: int = 0, ordinal: int | None = None) -> ContainerState:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    points = np.asarray(
        [
            [length / 2.0 - thickness, 0.0, 0.0],
            [-length / 2.0 + thickness, 0.0, 0.0],
            [0.0, width / 2.0 - thickness, 0.0],
            [0.0, -width / 2.0 + thickness, 0.0],
            [0.0, 0.0, height - thickness],
            [0.0, 0.0, thickness],
        ],
        dtype=np.float64,
    )
    normals = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        dtype=np.float64,
    )
    return ContainerState(
        index=index,
        length=length,
        width=width,
        height=height,
        thickness=thickness,
        cut_x=0.4,
        cut_y=0.4,
        center=(0.0, 0.0, height / 2.0),
        points=points,
        normals=normals,
        volume=length * width * height,
        ordinal=ordinal,
        shelf=shelf,
        is_prioritized=False,
        buffer=0.0,
    )


def _item(*, dims=(0.5, 0.4, 0.24), index=17) -> ItemSpec:
    return ItemSpec(index=index, length=dims[0], width=dims[1], height=dims[2])


def _proposals(state: PackingState, item: ItemSpec, **kwargs):
    return list(iter_fused_proposals(state, item, 0, **kwargs))


class FusedProposalTests(unittest.TestCase):
    def test_empty_floor_has_six_floor_wall_extreme_points(self) -> None:
        proposals = _proposals(PackingState([_container()]), _item())
        floor = [
            p
            for p in proposals
            if p.orientation == 0 and p.source.startswith(ProposalSource.FLOOR_WALL_EXTREME.value)
        ]
        self.assertEqual(len(floor), 6)
        for orientation in range(6):
            oriented = [
                p
                for p in proposals
                if p.orientation == orientation
                and p.source.startswith(ProposalSource.FLOOR_WALL_EXTREME.value)
            ]
            self.assertEqual(len(oriented), 6)

    def test_flat_wall_extrema_use_eight_mm_inclusion_margin(self) -> None:
        proposals = _proposals(PackingState([_container()]), _item(dims=(0.20, 0.20, 0.10)))
        floor = [
            p
            for p in proposals
            if p.orientation == 0 and p.source.startswith(ProposalSource.FLOOR_WALL_EXTREME.value)
        ]
        expected_left = -1.0 + 0.04 + 0.008 + 0.10
        self.assertTrue(any(abs(p.position[0] - expected_left) < 1e-9 for p in floor))

    def test_reserved_lattice_is_clipped_to_a_narrow_support(self) -> None:
        container = _container()
        container.static_obstacles = [
            AABB.from_center_half((0.0, 0.0, 0.30), (0.11, 0.09, 0.03))
        ]
        proposals = _proposals(PackingState([container]), _item(dims=(0.18, 0.16, 0.10)))
        lattice = [
            p
            for p in proposals
            if ProposalSource.RESERVED_SUPPORT_LATTICE.value in p.source
            and abs(p.position[2] - 0.402) < 1e-6
        ]
        self.assertTrue(lattice)
        self.assertTrue(all(-0.11 <= p.position[0] <= 0.11 for p in lattice))
        self.assertTrue(all(-0.09 <= p.position[1] <= 0.09 for p in lattice))

    def test_obstacle_faces_and_placed_tops_are_proposed(self) -> None:
        container = _container()
        placed_item = _item(index=3, dims=(0.30, 0.30, 0.20))
        placed = PlacedItem(
            item=placed_item,
            box=AABB.from_center_half((0.0, 0.30, 0.14), (0.15, 0.15, 0.10)),
        )
        container.placed.append(placed)
        proposals = _proposals(PackingState([container]), _item(dims=(0.20, 0.20, 0.10)))
        face = [p for p in proposals if ProposalSource.OBSTACLE_FACE_EXTREME.value in p.source]
        top = [p for p in proposals if abs(p.position[2] - 0.29) < 1e-6]
        self.assertTrue(face)
        self.assertTrue(top)

    def test_shelf_and_small_shelf_support_sources_are_present(self) -> None:
        container = _container(shelf=True)
        container.static_obstacles = [
            AABB.from_center_half((-0.55, 0.0, 0.84), (0.22, 0.70, 0.04)),
            AABB.from_center_half((0.0, 0.35, 0.84), (0.90, 0.34, 0.04)),
        ]
        proposals = _proposals(PackingState([container]), _item())
        lattice = [p for p in proposals if ProposalSource.RESERVED_SUPPORT_LATTICE.value in p.source]
        self.assertTrue(any(abs(p.position[2] - 1.022) < 1e-6 for p in lattice))

    def test_deduplication_unions_provenance_at_one_tenth_mm(self) -> None:
        container = _container()
        container.static_obstacles = [
            AABB.from_center_half((0.0, 0.0, 0.30), (0.20, 0.20, 0.03))
        ]
        proposals = _proposals(PackingState([container]), _item(dims=(0.40, 0.40, 0.10)))
        keys = [
            (p.pool_index, p.container_index, p.orientation, tuple(round(x, 4) for x in p.position))
            for p in proposals
        ]
        self.assertEqual(len(keys), len(set(keys)))
        merged = [
            p
            for p in proposals
            if "floor_wall_extreme" in p.source and "legacy_extreme_cross" in p.source
        ]
        self.assertTrue(merged)

    def test_distinct_dimension_orientations_are_not_collapsed(self) -> None:
        proposals = _proposals(PackingState([_container()]), _item(dims=(0.5, 0.4, 0.24)))
        self.assertEqual({p.orientation for p in proposals}, set(range(6)))

    def test_dimension_identical_orientation_ids_are_deduplicated(self) -> None:
        cube = _proposals(PackingState([_container()]), _item(dims=(0.4, 0.4, 0.4)))
        two_equal = _proposals(PackingState([_container()]), _item(dims=(0.4, 0.4, 0.2)))
        self.assertEqual({p.orientation for p in cube}, {0})
        self.assertEqual({p.orientation for p in two_equal}, {0, 1, 2})

    def test_support_z_semantics_floor_shelf_and_placed_top(self) -> None:
        floor = _proposals(PackingState([_container()]), _item())
        floor_z = [
            p.position[2]
            for p in floor
            if p.orientation == 0 and p.source.startswith("floor_wall_extreme")
        ]
        self.assertTrue(floor_z)
        self.assertTrue(all(abs(value - 0.168) < 1e-9 for value in floor_z))

        shelf_container = _container(shelf=True)
        shelf_container.static_obstacles = [
            AABB.from_center_half((0.0, 0.35, 0.84), (0.90, 0.34, 0.04)),
        ]
        shelf = _proposals(PackingState([shelf_container]), _item())
        self.assertTrue(any(abs(p.position[2] - 1.022) < 1e-9 for p in shelf))

        placed_container = _container()
        placed_container.placed.append(
            PlacedItem(
                _item(index=8, dims=(0.3, 0.3, 0.2)),
                AABB.from_center_half((0.0, 0.2, 0.14), (0.15, 0.15, 0.10)),
            )
        )
        placed = _proposals(PackingState([placed_container]), _item())
        self.assertTrue(any(abs(p.position[2] - 0.360) < 1e-9 for p in placed))

    def test_sloped_container_plane_adds_z_aware_derived_edge(self) -> None:
        container = _container()
        # This plane has a non-axis-aligned normal.  Its x-bound changes with
        # the support-derived candidate z, so a rectangular wall-only union
        # cannot reproduce the resulting edge.
        container.points = np.vstack(
            [container.points, np.asarray([[0.0, 0.0, 0.30]], dtype=np.float64)]
        )
        container.normals = np.vstack(
            [container.normals, np.asarray([[0.6, 0.0, 0.8]], dtype=np.float64)]
        )
        proposals = _proposals(PackingState([container]), _item(dims=(0.20, 0.20, 0.10)))
        derived = [p for p in proposals if p.orientation == 0 and "plane_derived_edge" in p.source]
        self.assertTrue(derived)
        self.assertTrue(any(abs(p.position[0]) > 1e-4 for p in derived))
        self.assertTrue(all(abs(p.position[2] - 0.098) < 1e-9 for p in derived))

    def test_sloped_plane_clips_reserved_lattice_at_support_z_intersection(self) -> None:
        container = _container()
        container.points = np.vstack(
            [container.points, np.asarray([[0.0, 0.0, 0.30]], dtype=np.float64)]
        )
        container.normals = np.vstack(
            [container.normals, np.asarray([[0.6, 0.0, 0.8]], dtype=np.float64)]
        )
        item = _item(dims=(0.20, 0.20, 0.10))
        proposals = _proposals(PackingState([container]), item)
        lattice = [
            p
            for p in proposals
            if p.orientation == 0
            and ProposalSource.RESERVED_SUPPORT_LATTICE.value in p.source
            and abs(p.position[2] - 0.098) < 1e-9
        ]
        expected_x = (0.6 * 0.0 + 0.8 * 0.30 - 0.008 - 0.8 * 0.098 - (0.6 * 0.10 + 0.8 * 0.05)) / 0.6
        self.assertTrue(any(abs(p.position[0] - expected_x) < 1e-9 for p in lattice))

    def test_dense_lattice_is_rescue_only(self) -> None:
        state = PackingState([_container()])
        normal = _proposals(state, _item())
        rescue = _proposals(state, _item(), rescue=True)
        self.assertFalse(any("dense_support_lattice" in p.source for p in normal))
        self.assertTrue(any("dense_support_lattice" in p.source for p in rescue))

    def test_determinism_and_deadline(self) -> None:
        state = PackingState([_container(shelf=True)])
        first = _proposals(state, _item())
        second = _proposals(state, _item())
        self.assertEqual(first, second)
        self.assertEqual(_proposals(state, _item(), deadline=time.perf_counter() - 1.0), [])

    def test_explicit_none_family_subset_is_byte_for_byte_compatible(self) -> None:
        state = PackingState([_container(shelf=True)])
        item = _item(dims=(0.50, 0.40, 0.24))

        implicit = _proposals(state, item, rescue=True)
        explicit = _proposals(state, item, rescue=True, family_subset=None)

        self.assertEqual(explicit, implicit)

    def test_none_family_subset_keeps_frozen_capped_legacy_output(self) -> None:
        state = PackingState(
            [_container(index=10, ordinal=0), _container(index=20, ordinal=1)]
        )
        proposals = _proposals(
            state,
            _item(),
            raw_work_limit=12,
            quantum=1,
            max_proposals=100,
            family_subset=None,
        )
        observed = [
            (
                proposal.container_index,
                proposal.orientation,
                tuple(round(value, 3) for value in proposal.position),
                proposal.source,
            )
            for proposal in proposals
        ]
        self.assertEqual(
            observed,
            [
                (0, 0, (-0.702, 0.502, 0.168), "floor_wall_extreme|reserved_support_lattice|legacy_extreme_cross"),
                (0, 0, (-0.702, -0.502, 0.168), "support_edge_flush"),
                (0, 0, (0.702, -0.502, 0.168), "plane_derived_edge"),
                (0, 1, (-0.702, 0.582, 0.248), "floor_wall_extreme"),
                (1, 0, (-0.702, 0.502, 0.168), "floor_wall_extreme|reserved_support_lattice|legacy_extreme_cross"),
                (1, 0, (-0.702, -0.502, 0.168), "support_edge_flush"),
                (1, 0, (0.702, -0.502, 0.168), "plane_derived_edge"),
                (1, 1, (-0.702, 0.582, 0.248), "floor_wall_extreme"),
            ],
        )

    def test_family_subset_emits_only_requested_sources(self) -> None:
        container = _container()
        container.static_obstacles = [
            AABB.from_center_half((0.0, 0.0, 0.30), (0.20, 0.20, 0.05))
        ]
        state = PackingState([container])
        item = _item(dims=(0.20, 0.20, 0.10))
        requested = (
            ProposalSource.FREE_RECTANGLE_BOUNDARY,
            ProposalSource.OBSTACLE_FACE_EXTREME,
        )

        proposals = _proposals(state, item, family_subset=requested)

        self.assertTrue(proposals)
        emitted = {
            source
            for proposal in proposals
            for source in proposal.source.split("|")
        }
        self.assertEqual(
            emitted,
            {source.value for source in requested},
        )

    def test_explicit_family_subset_rejects_rescue_flag_ambiguity_but_allows_deferred(self) -> None:
        state = PackingState([_container()])
        item = _item()
        subset = (ProposalSource.FREE_RECTANGLE_BOUNDARY,)

        with self.assertRaisesRegex(ValueError, "family_subset.*rescue"):
            _proposals(state, item, family_subset=subset, rescue=True)
        with self.assertRaisesRegex(ValueError, "family_subset.*rescue"):
            _proposals(state, item, family_subset=subset, rescue_only=True)
        self.assertIsInstance(
            _proposals(state, item, family_subset=subset, deferred=True),
            list,
        )

    def test_sub_tenth_mm_duplicate_unions_provenance(self) -> None:
        container = _container()
        item = _item(dims=(0.40, 0.40, 0.10))
        # Put a static face 50 micrometres away from a floor-wall key.  The
        # 0.1-mm key must merge the two source families.
        left = -container.length / 2.0 + container.thickness + 0.008 + item.length / 2.0
        obstacle_min_x = left + item.length / 2.0 + 0.018 + 0.00005
        container.static_obstacles = [
            AABB.from_center_half((obstacle_min_x + 0.10, 0.0, 0.30), (0.10, 0.10, 0.05))
        ]
        proposals = _proposals(PackingState([container]), item)
        self.assertTrue(
            any("floor_wall_extreme" in p.source and "obstacle_face_extreme" in p.source for p in proposals)
        )

    def test_obstacle_face_and_legacy_positions_include_path_clearance(self) -> None:
        container = _container()
        obstacle = AABB.from_center_half((0.0, 0.0, 0.30), (0.20, 0.20, 0.05))
        container.static_obstacles = [obstacle]
        item = _item(dims=(0.20, 0.20, 0.10))
        proposals = _proposals(PackingState([container]), item)
        expected_x = obstacle.minimum[0] - item.length / 2.0 - 0.018
        faces = [
            p
            for p in proposals
            if p.orientation == 0 and "obstacle_face_extreme" in p.source
        ]
        self.assertTrue(any(abs(p.position[0] - expected_x) < 1e-9 for p in faces))

    def test_rescue_free_boundary_subtracts_placed_footprint(self) -> None:
        container = _container()
        blocker = AABB.from_center_half((0.0, 0.0, 0.14), (0.20, 0.20, 0.10))
        container.placed.append(PlacedItem(_item(index=9, dims=(0.4, 0.4, 0.2)), blocker))
        proposals = _proposals(PackingState([container]), _item(dims=(0.20, 0.20, 0.10)), rescue=True)
        free = [p for p in proposals if "free_rectangle_boundary" in p.source]
        self.assertTrue(free)
        self.assertTrue(
            all(
                not (-0.20 < p.position[0] < 0.20 and -0.20 < p.position[1] < 0.20)
                for p in free
                if p.position[2] < 0.25
            )
        )

    def test_round_robin_raw_cap_gives_each_container_a_chance(self) -> None:
        state = PackingState([_container(index=10, ordinal=0), _container(index=20, ordinal=1)])
        proposals = _proposals(
            state,
            _item(),
            raw_work_limit=12,
            quantum=1,
            max_proposals=100,
        )
        self.assertEqual({p.container_index for p in proposals}, {0, 1})

    def test_family_subset_quantum_covers_every_orientation_container_group_first(self) -> None:
        state = PackingState(
            [_container(index=10, ordinal=0), _container(index=20, ordinal=1)]
        )
        proposals = _proposals(
            state,
            _item(dims=(0.50, 0.40, 0.24)),
            family_subset=(ProposalSource.FREE_RECTANGLE_BOUNDARY,),
            raw_work_limit=12,
            quantum=1,
            max_proposals=100,
        )
        self.assertEqual(len(proposals), 12)
        self.assertEqual(
            {(proposal.orientation, proposal.container_index) for proposal in proposals},
            {(orientation, container) for orientation in range(6) for container in range(2)},
        )

    def test_mid_deadline_returns_deterministic_partial_work(self) -> None:
        def make_clock():
            ticks = [0]

            def clock() -> float:
                ticks[0] += 1
                return ticks[0] * 0.00001

            return clock

        state = PackingState([_container(index=10, ordinal=0), _container(index=20, ordinal=1)])
        first = _proposals(state, _item(), deadline=0.0008, quantum=1, clock=make_clock())
        second = _proposals(state, _item(), deadline=0.0008, quantum=1, clock=make_clock())
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual({p.container_index for p in first}, {0, 1})


if __name__ == "__main__":
    unittest.main()
