from __future__ import annotations

import dataclasses
import inspect
import pathlib
import sys
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import StrictRootScanner  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask, RejectReason  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PlacementProposal,
    ValidatedRoot,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (  # noqa: E402
    FusedProposal,
    ProposalProvenance,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import (  # noqa: E402
    build_packing_state,
    state_fingerprint,
)
from agents.support_extreme_fusion_beam_exact_mask.transition import (  # noqa: E402
    SimPlacement,
    SimState,
    apply_root,
)


def _container(*, index: int = 17, offset_x: float = 0.0) -> dict:
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
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int, *, length: float = 0.20, width: float = 0.16,
          height: float = 0.12) -> ItemSpec:
    return ItemSpec(
        index=index,
        length=length,
        width=width,
        height=height,
        mass=3.0,
    )


def _proposal(item: ItemSpec, pool_index: int, *, container_index: int = 0,
              orientation: int = 0, position=None) -> PlacementProposal:
    dimensions = tuple(
        item.dimensions[index]
        for index in ((0, 1, 2), (0, 2, 1), (2, 1, 0), (1, 0, 2), (1, 2, 0), (2, 0, 1))[orientation]
    )
    if position is None:
        position = (0.0, 0.35, 0.04 + 0.008 + dimensions[2] / 2.0)
    return PlacementProposal(
        item_index=item.index,
        pool_index=pool_index,
        container_index=container_index,
        orientation=orientation,
        position=position,
        source="transition-fixture",
    )


def _strict_root(state, pool, proposal, settings=None):
    settings = settings or SearchSettings(front_floor_release_fill=0.0)
    root = ExactMask(settings).validate(state, pool, proposal)
    if root is None:
        raise AssertionError("fixture did not produce a strict root")
    return root, settings


class ImmutableTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(front_floor_release_fill=0.0)
        self.state = build_packing_state([
            _container(index=91, offset_x=-2.0),
            _container(index=7, offset_x=2.0),
        ])
        self.items = (_item(10), _item(11), _item(12))
        self.pool = tuple(item.to_dict() for item in self.items)
        self.sim = SimState(self.state, self.pool, (4, 8, 15))

    def test_sim_state_requires_tuple_pool_and_exact_unique_original_positions(self):
        self.assertTrue(dataclasses.is_dataclass(self.sim))
        self.assertEqual(tuple(item.index for item in self.sim.pool), (10, 11, 12))
        self.assertEqual(self.sim.original_pool_positions, (4, 8, 15))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.sim.pool = ()  # type: ignore[misc]
        with self.assertRaises(ValueError):
            SimState(self.state, self.pool, (4, True, 15))
        with self.assertRaises(ValueError):
            SimState(self.state, self.pool, (4, 4, 15))
        with self.assertRaises(ValueError):
            SimState(self.state, self.pool, (4, 8))

    def test_apply_root_clones_parent_and_removes_only_selected_occurrence(self):
        proposal = _proposal(self.items[1], 1, container_index=1, orientation=1)
        root, _ = _strict_root(self.state, self.pool, proposal, self.settings)
        before = state_fingerprint(
            self.state, self.pool, 1, self.settings.profile_digest()
        )

        placement = apply_root(self.sim, root, self.settings)

        self.assertIsInstance(placement, SimPlacement)
        self.assertIs(placement.parent, self.sim)
        self.assertIs(placement.root, root)
        self.assertEqual(placement.selected_pool_index, 1)
        self.assertEqual(placement.original_pool_position, 8)
        self.assertEqual(tuple(item.index for item in placement.child.pool), (10, 12))
        self.assertEqual(placement.child.original_pool_positions, (4, 15))
        self.assertEqual(len(self.state.containers[1].placed), 0)
        self.assertEqual(len(placement.child.packing.containers[1].placed), 1)
        self.assertEqual(len(placement.child.packing.containers[0].placed), 0)
        self.assertEqual(
            state_fingerprint(self.state, self.pool, 1, self.settings.profile_digest()),
            before,
        )
        np.testing.assert_allclose(
            placement.child.packing.containers[1].placed[0].box.dimensions,
            root.box.dimensions,
        )

    def test_parent_and_sibling_arrays_do_not_alias_or_change(self):
        root, _ = _strict_root(
            self.state, self.pool, _proposal(self.items[0], 0), self.settings
        )
        parent_points = [container.points.copy() for container in self.state.containers]
        first = apply_root(self.sim, root, self.settings)
        second = apply_root(self.sim, root, self.settings)

        for index, expected in enumerate(parent_points):
            np.testing.assert_array_equal(self.state.containers[index].points, expected)
            self.assertIsNot(first.child.packing.containers[index].points, self.state.containers[index].points)
            self.assertIsNot(second.child.packing.containers[index].points, first.child.packing.containers[index].points)
        self.assertEqual(len(first.child.packing.containers[0].placed), 1)
        self.assertEqual(len(second.child.packing.containers[0].placed), 1)
        self.assertIsNot(
            first.child.packing.containers[0].placed[0].box,
            second.child.packing.containers[0].placed[0].box,
        )

    def test_duplicate_item_ids_are_removed_by_pool_occurrence_not_global_id(self):
        duplicate = _item(30)
        pool = (duplicate.to_dict(), duplicate.to_dict(), _item(31).to_dict())
        sim = SimState(self.state, pool, (20, 21, 22))
        root, _ = _strict_root(
            self.state, pool, _proposal(duplicate, 1), self.settings
        )

        placement = apply_root(sim, root, self.settings)

        self.assertEqual(tuple(item.index for item in placement.child.pool), (30, 31))
        self.assertEqual(placement.child.original_pool_positions, (20, 22))
        self.assertEqual(placement.original_pool_position, 21)

    def test_child_treats_new_box_as_collision_for_mask_and_catalog(self):
        duplicate = _item(40)
        pool = (duplicate.to_dict(), duplicate.to_dict())
        sim = SimState(self.state, pool, (0, 1))
        root, _ = _strict_root(
            self.state, pool, _proposal(duplicate, 0), self.settings
        )
        child = apply_root(sim, root, self.settings).child
        same = _proposal(duplicate, 0, position=root.proposal.position)
        trace = ExactMask(self.settings).diagnose(child.packing, child.pool, same)
        self.assertFalse(trace.accepted)
        self.assertEqual(trace.first_reason, RejectReason.COLLISION)

        fused = FusedProposal(
            same,
            ProposalProvenance(
                sources=("floor_wall_extreme",),
                support_sources=("floor",),
                support_levels=(0.04,),
            ),
        )

        def only_same(*_args, **_kwargs):
            yield fused

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=only_same,
        ):
            catalog = StrictRootScanner(
                self.settings, first_pass_raw_cap=1, pass2_raw_increment=1
            ).scan(child.packing, child.pool)
        self.assertFalse(catalog)
        self.assertGreater(catalog.stats.rejection_count(RejectReason.COLLISION), 0)

    def test_stale_root_cannot_be_applied_to_child(self):
        root, _ = _strict_root(
            self.state, self.pool, _proposal(self.items[0], 0), self.settings
        )
        child = apply_root(self.sim, root, self.settings).child
        with self.assertRaisesRegex(ValueError, "pool|fingerprint|stale"):
            apply_root(child, root, self.settings)

    def test_foreign_state_and_foreign_pool_roots_are_rejected(self):
        root, _ = _strict_root(
            self.state, self.pool, _proposal(self.items[0], 0), self.settings
        )
        foreign_state = self.state.clone()
        foreign_state.containers[0].buffer = 0.01
        foreign = SimState(foreign_state, self.pool, (4, 8, 15))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            apply_root(foreign, root, self.settings)

        reordered = SimState(self.state, tuple(reversed(self.pool)), (15, 8, 4))
        with self.assertRaisesRegex(ValueError, "item|pool|fingerprint"):
            apply_root(reordered, root, self.settings)

    def test_profile_dimensions_position_and_ordinal_are_rechecked(self):
        root, _ = _strict_root(
            self.state, self.pool, _proposal(self.items[0], 0), self.settings
        )
        with self.assertRaisesRegex(ValueError, "profile"):
            apply_root(
                self.sim, root, SearchSettings(path_clearance=0.019)
            )

        wrong_box = AABB.from_center_half(root.box.center, root.box.half + (0.01, 0.0, 0.0))
        forged_dimensions = dataclasses.replace(root, box=wrong_box)
        with self.assertRaisesRegex(ValueError, "dimension"):
            apply_root(self.sim, forged_dimensions, self.settings)

        moved_box = AABB.from_center_half(
            root.box.center + (0.01, 0.0, 0.0), root.box.half
        )
        forged_position = dataclasses.replace(root, box=moved_box)
        with self.assertRaisesRegex(ValueError, "position|center"):
            apply_root(self.sim, forged_position, self.settings)

        wrong_ordinal_proposal = dataclasses.replace(root.proposal, container_index=1)
        wrong_ordinal = dataclasses.replace(root, proposal=wrong_ordinal_proposal)
        with self.assertRaisesRegex(ValueError, "proposal|ordinal|key"):
            apply_root(self.sim, wrong_ordinal, self.settings)

        forged_source = dataclasses.replace(root, source="foreign-source")
        with self.assertRaisesRegex(ValueError, "source"):
            apply_root(self.sim, forged_source, self.settings)

        tilted_box = AABB(
            root.box.minimum, root.box.maximum, axis_aligned=False
        )
        forged_alignment = dataclasses.replace(root, box=tilted_box)
        with self.assertRaisesRegex(ValueError, "alignment"):
            apply_root(self.sim, forged_alignment, self.settings)

    def test_forged_or_non_root_input_is_rejected_and_original_root_is_retained(self):
        root, _ = _strict_root(
            self.state, self.pool, _proposal(self.items[0], 0), self.settings
        )
        with self.assertRaises(TypeError):
            apply_root(self.sim, root.proposal, self.settings)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ValidatedRoot(
                proposal=root.proposal,
                box=root.box,
                state_fingerprint=root.state_fingerprint,
                profile_digest=root.profile_digest,
                item_signature=root.item_signature,
                proposal_key=root.proposal_key,
            )
        placement = apply_root(self.sim, root, self.settings)
        self.assertIs(placement.root, root)

    def test_coordinated_out_of_bounds_and_collision_receipt_laundering_is_rejected(self):
        item = self.items[0]
        root, _ = _strict_root(
            self.state, self.pool, _proposal(item, 0), self.settings
        )

        def launder(position, *, container_index=0, orientation=1, source="laundered"):
            proposal = dataclasses.replace(
                root.proposal,
                position=position,
                container_index=container_index,
                orientation=orientation,
                source=source,
            )
            dimensions = tuple(
                item.dimensions[index]
                for index in ((0, 1, 2), (0, 2, 1), (2, 1, 0), (1, 0, 2), (1, 2, 0), (2, 0, 1))[orientation]
            )
            box = AABB.from_center_half(
                position, np.asarray(dimensions, dtype=np.float64) * 0.5
            )
            key = (
                proposal.item_index,
                proposal.pool_index,
                proposal.container_index,
                proposal.orientation,
                tuple(round(value, 7) for value in proposal.position),
            )
            return dataclasses.replace(
                root,
                proposal=proposal,
                box=box,
                proposal_key=key,
                source=source,
            )

        outside = launder((4.0, 0.35, 0.20), container_index=1)
        with self.assertRaisesRegex(ValueError, "exact|revalid|geometry"):
            apply_root(self.sim, outside, self.settings)

        collision_state = self.state.clone()
        collision_state.containers[0].static_obstacles.append(
            AABB.from_center_half((0.50, 0.35, 0.108), (0.10, 0.08, 0.06))
        )
        collision_sim = SimState(collision_state, self.pool, (4, 8, 15))
        collision_root, _ = _strict_root(
            collision_state, self.pool, _proposal(item, 0), self.settings
        )
        root = collision_root
        colliding = launder((0.50, 0.35, 0.108), orientation=0)
        with self.assertRaisesRegex(ValueError, "exact|revalid|geometry"):
            apply_root(collision_sim, colliding, self.settings)

    def test_boolean_or_nonmatching_exact_revalidation_never_authorizes_transition(self):
        root, _ = _strict_root(
            self.state, self.pool, _proposal(self.items[0], 0), self.settings
        )
        with self.assertRaisesRegex(TypeError, "ValidatedRoot|evidence"):
            apply_root(
                self.sim,
                root,
                self.settings,
                exact_revalidator=lambda *_args: True,
            )
        with self.assertRaisesRegex(ValueError, "fresh"):
            apply_root(
                self.sim,
                root,
                self.settings,
                exact_revalidator=lambda *_args: root,
            )
        with self.assertRaisesRegex(ValueError, "exact|revalid|geometry"):
            apply_root(
                self.sim,
                root,
                self.settings,
                deadline=0.0,
            )

        other_root, _ = _strict_root(
            self.state,
            self.pool,
            _proposal(self.items[1], 1, position=(0.30, 0.35, 0.108)),
            self.settings,
        )
        with self.assertRaisesRegex(ValueError, "match"):
            apply_root(
                self.sim,
                root,
                self.settings,
                exact_revalidator=lambda *_args: other_root,
            )

    def test_transition_is_standalone_and_never_formats_actions_or_imports_search(self):
        import agents.support_extreme_fusion_beam_exact_mask.transition as transition_module

        source = inspect.getsource(transition_module)
        for forbidden in (
            "agents.highscore", ".mcts", ".ems", ".planner",
            "_issue_validated_root", "item_idx", "place_pos",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
