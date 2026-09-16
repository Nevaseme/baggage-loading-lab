from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.mask import (  # noqa: E402
    ExactMask,
    RejectReason,
)
from agents.support_extreme_fusion_beam_exact_mask.agent import Agent  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PlacementProposal,
    PlacedItem,
    ValidatedRoot,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import (  # noqa: E402
    build_packing_state,
    state_fingerprint,
)
from tests.replay_support import load_observation_snapshot  # noqa: E402


def _container_dict(
    *,
    index: int = 7,
    offset_x: float = 0.0,
    shelf: bool = False,
    prioritized: bool = False,
    packed: list[dict] | None = None,
) -> dict:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.40,
        "cut_y": 0.40,
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
        "shelf": shelf,
        "is_prioritized": prioritized,
        "packed_items": packed or [],
    }


def _item(
    index: int,
    *,
    length: float = 0.24,
    width: float = 0.20,
    height: float = 0.16,
    prioritized: bool = False,
    soft: bool = False,
) -> ItemSpec:
    return ItemSpec(
        index=index,
        length=length,
        width=width,
        height=height,
        mass=4.0,
        is_prioritized=prioritized,
        is_soft=soft,
    )


def _floor_position(item: ItemSpec, orientation: int = 0, *, x: float = 0.0, y: float = 0.30):
    dimensions = tuple(item.dimensions[i] for i in ((0, 1, 2), (0, 2, 1), (2, 1, 0), (1, 0, 2), (1, 2, 0), (2, 0, 1))[orientation])
    return (x, y, 0.04 + 0.008 + dimensions[2] / 2.0)


def _proposal(item: ItemSpec, *, pool_index: int = 0, container_index: int = 0,
              orientation: int = 0, position=None, source: str = "fixture") -> PlacementProposal:
    return PlacementProposal(
        item_index=item.index,
        pool_index=pool_index,
        container_index=container_index,
        orientation=orientation,
        position=position or _floor_position(item, orientation),
        source=source,
    )


class ExactMaskContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(front_floor_release_fill=0.0)
        self.mask = ExactMask(self.settings)
        self.state = build_packing_state([_container_dict()])
        self.item = _item(11)
        self.pool = [self.item.to_dict()]

    def assertRejected(self, proposal, reason, *, state=None, pool=None):
        state = state or self.state
        pool = pool or self.pool
        self.assertIsNone(self.mask.validate(state, pool, proposal))
        trace = self.mask.diagnose(state, pool, proposal)
        self.assertFalse(trace.accepted)
        self.assertEqual(trace.first_reason, reason)
        self.assertIn(reason, trace.failed_predicates)
        return trace

    def test_floor_root_is_strict_fresh_and_binds_pool_profile_and_raw_container_metadata(self):
        state = build_packing_state([
            _container_dict(index=17, offset_x=-2.0),
            _container_dict(index=91, offset_x=2.0),
        ])
        proposal = _proposal(self.item, container_index=1)
        first = self.mask.validate(state, self.pool, proposal)
        second = self.mask.validate(state, self.pool, proposal)

        self.assertIsInstance(first, ValidatedRoot)
        self.assertIsInstance(second, ValidatedRoot)
        self.assertIsNot(first, second)
        self.assertTrue(first.strict)
        self.assertEqual(first.proposal.container_index, 1)
        self.assertEqual(first.profile_digest, self.settings.profile_digest())
        self.assertEqual(first.proposal_key, second.proposal_key)
        self.assertEqual(first.state_fingerprint, second.state_fingerprint)

        reordered = [dict(self.pool[0], index=22), self.pool[0]]
        self.assertRejected(proposal, RejectReason.ITEM_BINDING, state=state, pool=reordered)

    def test_all_six_orientations_issue_dimension_matching_roots(self):
        item = _item(12, length=0.22, width=0.28, height=0.34)
        pool = [item.to_dict()]
        for orientation in range(6):
            with self.subTest(orientation=orientation):
                root = self.mask.validate(self.state, pool, _proposal(item, orientation=orientation))
                self.assertIsInstance(root, ValidatedRoot)
                expected = tuple(item.dimensions[i] for i in ((0, 1, 2), (0, 2, 1), (2, 1, 0), (1, 0, 2), (1, 2, 0), (2, 0, 1))[orientation])
                np.testing.assert_allclose(root.box.dimensions, expected)

    def test_agent_revalidator_receives_a_fresh_field_matching_root_not_a_boolean(self):
        proposal = _proposal(self.item)
        root = self.mask.validate(self.state, self.pool, proposal)
        reissued = self.mask.revalidate(self.state, self.pool, proposal, self.settings)
        self.assertIsInstance(reissued, ValidatedRoot)
        self.assertIsNot(reissued, root)
        self.assertEqual(reissued.proposal_key, root.proposal_key)
        self.assertEqual(reissued.state_fingerprint, root.state_fingerprint)
        self.assertIsNone(
            self.mask.revalidate(
                self.state,
                self.pool,
                proposal,
                SearchSettings(path_clearance=0.019),
            )
        )

        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.settings = self.settings
        agent.install_exact_revalidator(self.mask.revalidate)
        action = agent.format_validated_action(root, self.state, self.pool)
        self.assertEqual(action["item_idx"], 0)
        self.assertEqual(action["container_idx"], 0)

    def test_profile_v1_receipt_is_stale_under_v2_mask(self):
        proposal = _proposal(self.item)
        root = self.mask.validate(self.state, self.pool, proposal)
        old_payload = {
            "version": "support-extreme-fusion-strict-v1",
            "settings": asdict(self.settings),
        }
        old_digest = hashlib.sha256(
            json.dumps(
                old_payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        old_root = replace(
            root,
            profile_digest=old_digest,
            state_fingerprint=state_fingerprint(
                self.state, self.pool, proposal.pool_index, old_digest
            ),
        )
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.settings = self.settings
        agent.install_exact_revalidator(self.mask.revalidate)

        with self.assertRaisesRegex(ValueError, "profile digest"):
            agent.format_validated_action(old_root, self.state, self.pool)

    def test_inclusion_collision_and_horizontal_18mm_clearance_are_strict(self):
        outside = _proposal(self.item, position=(0.90, 0.30, _floor_position(self.item)[2]))
        self.assertRejected(outside, RejectReason.INCLUSION)

        obstacle = AABB.from_center_half((0.0, 0.30, 0.128), (0.12, 0.10, 0.08))
        collision_state = self.state.clone()
        collision_state.containers[0].static_obstacles.append(obstacle)
        self.assertRejected(_proposal(self.item), RejectReason.COLLISION, state=collision_state)

        near_state = self.state.clone()
        near_state.containers[0].static_obstacles.append(
            AABB.from_center_half((0.12 + 0.018 - 0.0001 + 0.05, 0.30, 0.128), (0.05, 0.10, 0.08))
        )
        self.assertRejected(_proposal(self.item), RejectReason.COLLISION, state=near_state)

    def test_nonofficial_floor_frontier_and_shelf_release_do_not_reject_safe_roots(self):
        frontier_state = self.state.clone()
        floor_support = _item(70, length=0.40, width=0.20, height=0.16)
        frontier_state.containers[0].placed.append(
            PlacedItem(floor_support, AABB.from_center_half((-0.48, 0.55, 0.128), (0.20, 0.10, 0.08)))
        )
        skewed = _proposal(self.item, position=(0.48, -0.20, _floor_position(self.item)[2]))
        self.assertIsInstance(
            self.mask.validate(frontier_state, self.pool, skewed),
            ValidatedRoot,
        )

        shelf_mask = ExactMask(SearchSettings())
        shelf_state = build_packing_state([_container_dict(shelf=True)])
        front = _proposal(self.item, position=(0.0, -0.30, _floor_position(self.item)[2]))
        self.assertIsInstance(
            shelf_mask.validate(shelf_state, self.pool, front),
            ValidatedRoot,
        )

    def test_shelf_and_axis_aligned_item_top_can_support_but_tilted_top_cannot(self):
        shelf_state = build_packing_state([_container_dict(shelf=True)])
        shelf_z = (
            shelf_state.containers[0].height / 2.0
            + shelf_state.containers[0].thickness
            + shelf_state.containers[0].buffer
        )
        shelf_proposal = _proposal(
            self.item,
            position=(
                0.0,
                0.35,
                shelf_z + self.settings.shelf_drop_gap + self.item.height / 2.0,
            ),
        )
        self.assertIsInstance(self.mask.validate(shelf_state, self.pool, shelf_proposal), ValidatedRoot)

        support = _item(72, length=0.50, width=0.50, height=0.20)
        support_box = AABB.from_center_half((0.0, 0.30, 0.14), (0.25, 0.25, 0.10))
        top_state = self.state.clone()
        top_state.containers[0].placed.append(PlacedItem(support, support_box))
        top = _proposal(self.item, position=(0.0, 0.30, support_box.maximum[2] + self.item.height / 2.0))
        self.assertIsInstance(self.mask.validate(top_state, self.pool, top), ValidatedRoot)
        self.assertAlmostEqual(
            self.mask.diagnose(top_state, self.pool, top).effective_lift, 0.08
        )

        tilted_state = self.state.clone()
        tilted_state.containers[0].placed.append(
            PlacedItem(support, AABB(support_box.minimum, support_box.maximum, axis_aligned=False))
        )
        self.assertRejected(top, RejectReason.SUPPORT_RATIO, state=tilted_state)

    def test_support_ratio_core_and_soft_threshold_are_separate_reasons(self):
        bottom = 0.30
        item = _item(80, length=0.40, width=0.40, height=0.12)
        pool = [item.to_dict()]
        state = self.state.clone()
        left = AABB.from_center_half((-0.1125, 0.30, 0.20), (0.0875, 0.20, 0.16))
        right = AABB.from_center_half((0.1125, 0.30, 0.20), (0.0875, 0.20, 0.16))
        support_item = _item(81)
        state.containers[0].placed.extend((PlacedItem(support_item, left), PlacedItem(support_item, right)))
        proposal = _proposal(item, position=(0.0, 0.30, 0.36 + item.height / 2.0))
        trace = self.assertRejected(proposal, RejectReason.CENTER_SUPPORT, state=state, pool=pool)
        self.assertGreaterEqual(trace.support_ratio, 0.75)

        narrow_state = self.state.clone()
        narrow = AABB.from_center_half((0.0, 0.30, 0.20), (0.12, 0.20, 0.16))
        narrow_state.containers[0].placed.append(PlacedItem(support_item, narrow))
        self.assertRejected(proposal, RejectReason.SUPPORT_RATIO, state=narrow_state, pool=pool)

        soft = _item(82, length=0.40, width=0.40, height=0.12, soft=True)
        soft_pool = [soft.to_dict()]
        support_80 = AABB.from_center_half((-0.04, 0.30, 0.20), (0.16, 0.20, 0.16))
        soft_state = self.state.clone()
        soft_state.containers[0].placed.append(PlacedItem(_item(83, soft=True), support_80))
        soft_proposal = _proposal(soft, position=(0.0, 0.30, 0.36 + soft.height / 2.0))
        self.assertRejected(soft_proposal, RejectReason.SUPPORT_RATIO, state=soft_state, pool=soft_pool)

    def test_support_from_different_heights_is_not_merged_into_a_false_platform(self):
        item = _item(84, length=0.40, width=0.40, height=0.12)
        pool = [item.to_dict()]
        state = self.state.clone()
        lower = AABB.from_center_half((-0.10, 0.30, 0.20), (0.10, 0.20, 0.16))
        higher = AABB.from_center_half((0.10, 0.30, 0.2025), (0.10, 0.20, 0.1625))
        state.containers[0].placed.extend(
            (PlacedItem(_item(85), lower), PlacedItem(_item(86), higher))
        )
        proposal = _proposal(
            item,
            position=(0.0, 0.30, float(higher.maximum[2]) + item.height / 2.0),
        )
        self.assertRejected(proposal, RejectReason.SUPPORT_RATIO, state=state, pool=pool)

    def test_priority_soft_and_combined_protection_rules_reject_wrong_column(self):
        cases = [
            (_item(90, prioritized=True), _item(91), "priority"),
            (_item(92, soft=True), _item(93), "soft"),
            (_item(94, prioritized=True, soft=True), _item(95, prioritized=True), "combined"),
        ]
        for support, upper, label in cases:
            with self.subTest(rule=label):
                state = self.state.clone()
                box = AABB.from_center_half((0.0, 0.30, 0.20), (0.25, 0.25, 0.16))
                state.containers[0].placed.append(PlacedItem(support, box))
                pool = [upper.to_dict()]
                proposal = _proposal(upper, position=(0.0, 0.30, 0.36 + upper.height / 2.0))
                self.assertRejected(proposal, RejectReason.PROTECTION, state=state, pool=pool)

    def test_priority_container_eligibility_uses_public_ordinal_not_raw_index(self):
        priority = _item(101, prioritized=True)
        pool = [priority.to_dict()]
        state = build_packing_state([
            _container_dict(index=99, offset_x=-2.0),
            _container_dict(index=3, offset_x=2.0, prioritized=True),
        ])
        self.assertRejected(
            _proposal(priority, container_index=0), RejectReason.CONTAINER_ELIGIBILITY,
            state=state, pool=pool,
        )
        self.assertIsInstance(
            self.mask.validate(state, pool, _proposal(priority, container_index=1)),
            ValidatedRoot,
        )

        # Ordinary-first is a catalog exposure policy, not a physical exact
        # predicate.  The deferred priority-container tier must remain capable
        # of producing a strict root when no ordinary root exists.
        normal = _item(103)
        normal_pool = [normal.to_dict()]
        self.assertIsInstance(
            self.mask.validate(
                state, normal_pool, _proposal(normal, container_index=1)
            ),
            ValidatedRoot,
        )

        malformed = self.state.clone()
        malformed.containers[0].ordinal = 4
        trace = self.mask.diagnose(
            malformed, self.pool, _proposal(self.item, container_index=4)
        )
        self.assertEqual(trace.first_reason, RejectReason.CONTAINER_ORDINAL)

    def test_effective_lift_transport_and_depth_map_failures_are_diagnosed(self):
        blocker_state = self.state.clone()
        blocker_state.containers[0].static_obstacles.append(
            AABB.from_center_half((0.0, -0.20, 0.128), (0.15, 0.12, 0.08))
        )
        self.assertRejected(_proposal(self.item), RejectReason.TRANSPORT, state=blocker_state)

        depth_state = self.state.clone()
        depth_state.containers[0].depth_map = np.ones((64, 64), dtype=np.float64) * 0.01
        model_obstacle = AABB.from_center_half((0.0, -0.10, 0.128), (0.10, 0.10, 0.08))
        depth_state.containers[0].placed.append(PlacedItem(_item(102), model_obstacle))
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.mask.transport_path_clear",
            return_value=True,
        ):
            self.assertRejected(_proposal(self.item), RejectReason.DEPTH_MAP, state=depth_state)

    def test_deadline_and_internal_exception_are_never_converted_to_acceptance(self):
        proposal = _proposal(self.item)
        trace = self.mask.diagnose(self.state, self.pool, proposal, deadline=time.perf_counter() - 1.0)
        self.assertEqual(trace.first_reason, RejectReason.DEADLINE)
        self.assertIsNone(self.mask.validate(self.state, self.pool, proposal, deadline=time.perf_counter() - 1.0))

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.mask.box_inside_planes",
            side_effect=RuntimeError("boom"),
        ):
            trace = self.mask.diagnose(self.state, self.pool, proposal)
            self.assertEqual(trace.first_reason, RejectReason.EXCEPTION)
            self.assertIn("RuntimeError", trace.detail)
            self.assertIsNone(self.mask.validate(self.state, self.pool, proposal))

    def test_step14_historical_actions_remain_collision_rejected(self):
        artifact = pathlib.Path(__file__).parent / "artifacts" / "task001_step14_control_failure.npz"
        observation, _metadata = load_observation_snapshot(artifact)
        state = build_packing_state(observation["container_list"], observation.get("depth_map"))
        pool = observation["pool_list"]
        old_last_resort = PlacementProposal(
            item_index=pool[4]["index"], pool_index=4, container_index=0, orientation=0,
            position=(0.0, 0.492000013589859, 0.17800000309944153), source="old-last-resort",
        )
        old_shadow = PlacementProposal(
            item_index=pool[3]["index"], pool_index=3, container_index=0, orientation=0,
            position=(-0.172, -0.2195, 0.193), source="public-29.7-shadow",
        )
        self.assertIsNone(self.mask.validate(state, pool, old_last_resort))
        self.assertIsNone(self.mask.validate(state, pool, old_shadow))
        self.assertEqual(
            self.mask.diagnose(state, pool, old_last_resort).first_reason,
            RejectReason.COLLISION,
        )
        self.assertEqual(
            self.mask.diagnose(state, pool, old_shadow).first_reason,
            RejectReason.COLLISION,
        )


if __name__ == "__main__":
    unittest.main()
