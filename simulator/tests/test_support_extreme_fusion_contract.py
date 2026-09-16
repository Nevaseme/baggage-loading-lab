from __future__ import annotations

import dataclasses
import unittest

import numpy as np

from agents.support_extreme_fusion_beam_exact_mask.agent import (
    Agent,
    CandidateZeroError,
    NotReadyError,
    PlanningError,
)
from agents.support_extreme_fusion_beam_exact_mask.geometry import (
    aabb_from_pose,
    box_inside_planes,
    oriented_dimensions,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (
    AABB,
    Candidate,
    ContainerState,
    ItemSpec,
    PlacementProposal,
    PlacedItem,
    ValidatedRoot,
    _issue_validated_root,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import iter_fused_proposals
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings
from agents.support_extreme_fusion_beam_exact_mask.state import (
    build_packing_state,
    state_fingerprint,
)


def _container(*, index: int = 0, prioritized: bool = False) -> dict:
    # A simple rectangular container plane set.  The local state builder must
    # preserve the simulator's world-x to local-x normalization.
    points = np.asarray(
        [
            [-0.5, -0.5, 0.0],
            [0.5, -0.5, 0.0],
            [-0.5, 0.5, 0.0],
            [-0.5, -0.5, 1.0],
        ],
        dtype=np.float64,
    )
    normals = np.asarray(
        [
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 1.0],
            [-1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
        ],
        dtype=np.float64,
    )
    return {
        "index": index,
        "length": 1.0,
        "width": 1.0,
        "height": 1.0,
        "thickness": 0.02,
        "cut_x": 0.2,
        "cut_y": 0.0,
        "center": (2.0, 0.0, 0.5),
        "points": points + np.asarray((2.0, 0.0, 0.0)),
        "n_vecs": normals,
        "volume": 1.0,
        "is_prioritized": prioritized,
        "shelf": False,
        "packed_items": [],
    }


def _item(index: int = 4) -> ItemSpec:
    return ItemSpec(index=index, length=0.2, width=0.3, height=0.1, mass=2.0)


class SupportExtremeFusionContractTests(unittest.TestCase):
    def test_model_types_are_frozen_at_the_boundary(self) -> None:
        proposal = PlacementProposal(
            item_index=4,
            pool_index=0,
            container_index=0,
            orientation=0,
            position=(0.0, 0.0, 0.08),
        )
        self.assertTrue(dataclasses.is_dataclass(proposal))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            proposal.orientation = 1  # type: ignore[misc]

        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint="state-0",
            item=_item(),
            profile_digest=SearchSettings().profile_digest(),
            pool=[_item().to_dict()],
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            root.support_ratio = 0.5  # type: ignore[misc]


    def test_state_builder_and_fingerprint_are_local_and_deterministic(self) -> None:
        raw = _container()
        raw["packed_items"] = [
            {
                "index": 9,
                "length": 0.2,
                "width": 0.2,
                "height": 0.2,
                "pos": (2.0, 0.0, 0.12),
                "orn": (0.0, 0.0, 0.0, 1.0),
            }
        ]
        state = build_packing_state([raw])
        self.assertAlmostEqual(float(state.containers[0].placed[0].box.center[0]), 0.0)
        self.assertEqual(state_fingerprint(state), state_fingerprint(state.clone()))
        self.assertTrue(state.containers[0].placed[0].box.axis_aligned)


    def test_geometry_contract_keeps_official_six_orientation_dimensions(self) -> None:
        dimensions = (0.2, 0.3, 0.4)
        self.assertEqual(len({oriented_dimensions(dimensions, i) for i in range(6)}), 6)
        box = aabb_from_pose(
            (2.0, 0.0, 0.2),
            dimensions,
            (0.0, 0.0, 0.0, 1.0),
            2.0,
        )
        self.assertAlmostEqual(float(box.center[0]), 0.0)
        self.assertTrue(np.allclose(box.dimensions, dimensions))


    def test_formatter_requires_current_validated_root_and_never_raw_proposal(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        state = build_packing_state([_container()])
        proposal = PlacementProposal(
            item_index=4,
            pool_index=0,
            container_index=0,
            orientation=0,
            position=(0.0, 0.0, 0.08),
        )
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        profile = SearchSettings()
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=state_fingerprint(
                state, [_item().to_dict()], 0, profile.profile_digest()
            ),
            item=_item(),
            profile_digest=profile.profile_digest(),
            pool=[_item().to_dict()],
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        agent.install_exact_revalidator(lambda *_args: root)
        action = agent.format_validated_action(root, state, [_item().to_dict()])
        self.assertEqual(action["item_idx"], 0)
        self.assertEqual(action["container_idx"], 0)
        self.assertEqual(action["orientation"], 0)
        self.assertEqual(action["place_pos"].dtype, np.float32)
        self.assertEqual(action["place_pos"].shape, (3,))

        with self.assertRaisesRegex(ValueError, "state fingerprint"):
            agent.format_validated_action(
                _issue_validated_root(
                    proposal=proposal,
                    box=box,
                    state_fingerprint="stale",
                    item=_item(),
                    profile_digest=profile.profile_digest(),
                    pool=[_item().to_dict()],
                    selected_pool_index=0,
                    support_ratio=1.0,
                    min_clearance=0.03,
                ),
                state,
                [_item().to_dict()],
            )
        with self.assertRaisesRegex(TypeError, "ValidatedRoot"):
            agent.format_validated_action(proposal, state, [_item().to_dict()])  # type: ignore[arg-type]

    def test_validated_root_cannot_be_forged_or_relaxed(self) -> None:
        proposal = PlacementProposal(4, 0, 0, 0, (0.0, 0.0, 0.08))
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        with self.assertRaises(TypeError):
            ValidatedRoot(
                proposal=proposal,
                box=box,
                state_fingerprint="state",
                profile_digest=SearchSettings().profile_digest(),
                item_signature=(4,),
                proposal_key=(4, 0, 0, 0, (0.0, 0.0, 0.08)),
            )
        with self.assertRaises(ValueError):
            _issue_validated_root(
                proposal=proposal,
                box=box,
                state_fingerprint="state",
                item=_item(),
                profile_digest=SearchSettings().profile_digest(),
                pool=[_item().to_dict()],
                selected_pool_index=0,
                support_ratio=1.0,
                min_clearance=0.03,
                rule_violations=1,
            )

    def test_aabb_arrays_are_read_only_and_clone_isolation_is_deep(self) -> None:
        box = AABB.from_center_half((0.0, 0.0, 0.1), (0.1, 0.1, 0.1))
        with self.assertRaises(ValueError):
            box.minimum[0] = -1.0
        state = build_packing_state([_container()])
        state.containers[0].static_obstacles = [box]
        cloned = state.clone()
        self.assertIsNot(cloned.containers[0].static_obstacles[0], state.containers[0].static_obstacles[0])
        self.assertIsNot(cloned.containers[0].points, state.containers[0].points)

    def test_proposal_and_aabb_reject_nonfinite_or_invalid_integer_boundaries(self) -> None:
        with self.assertRaises(ValueError):
            PlacementProposal(True, 0, 0, 0, (0.0, 0.0, 0.0))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            PlacementProposal(1, 0, 0, 0, (0.0, float("nan"), 0.0))
        with self.assertRaises(ValueError):
            AABB(np.asarray((1.0, 0.0, 0.0)), np.asarray((0.0, 1.0, 1.0)))

    def test_formatter_rejects_pool_reorder_and_item_mutation(self) -> None:
        state = build_packing_state([_container()])
        profile = SearchSettings()
        pool = [_item(index=4).to_dict(), _item(index=9).to_dict()]
        proposal = PlacementProposal(4, 0, 0, 0, (0.0, 0.0, 0.08))
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=state_fingerprint(state, pool, 0, profile.profile_digest()),
            item=_item(index=4),
            profile_digest=profile.profile_digest(),
            pool=pool,
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.install_exact_revalidator(lambda *_args: root)
        with self.assertRaises(ValueError):
            agent.format_validated_action(root, state, list(reversed(pool)))
        mutated = list(pool)
        mutated[0] = dict(mutated[0], width=0.31)
        with self.assertRaises(ValueError):
            agent.format_validated_action(root, state, mutated)

    def test_formatter_requires_ordered_pool_and_installed_exact_verifier(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        state = build_packing_state([_container()])
        pool = [_item(index=4).to_dict()]
        proposal = PlacementProposal(4, 0, 0, 0, (0.0, 0.0, 0.08))
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        profile = SearchSettings()
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=state_fingerprint(state, pool, 0, profile.profile_digest()),
            item=_item(index=4),
            profile_digest=profile.profile_digest(),
            pool=pool,
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        with self.assertRaises(ValueError):
            agent.format_validated_action(root, state, None)  # type: ignore[arg-type]
        with self.assertRaises(NotReadyError):
            agent.format_validated_action(root, state, pool)

    def test_formatter_rejects_boolean_exact_revalidation_results(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        state = build_packing_state([_container()])
        pool = [_item(index=4).to_dict()]
        profile = SearchSettings()
        proposal = PlacementProposal(4, 0, 0, 0, (0.0, 0.0, 0.08))
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=state_fingerprint(state, pool, 0, profile.profile_digest()),
            item=_item(index=4),
            profile_digest=profile.profile_digest(),
            pool=pool,
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        for result in (True, False, None):
            agent.install_exact_revalidator(lambda *_args, result=result: result)
            with self.assertRaises(NotReadyError):
                agent.format_validated_action(root, state, pool)

    def test_dataclasses_replace_receipt_cannot_emit_without_exact_revalidation(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        state = build_packing_state([_container()])
        pool = [_item(index=4).to_dict()]
        profile = SearchSettings()
        proposal = PlacementProposal(4, 0, 0, 0, (0.0, 0.0, 0.08))
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=state_fingerprint(state, pool, 0, profile.profile_digest()),
            item=_item(index=4),
            profile_digest=profile.profile_digest(),
            pool=pool,
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        forged = dataclasses.replace(root, support_ratio=0.0)
        agent.install_exact_revalidator(lambda *_args: root)
        with self.assertRaises(ValueError):
            agent.format_validated_action(forged, state, pool)

    def test_aabb_cannot_reenable_write_flag(self) -> None:
        box = AABB.from_center_half((0.0, 0.0, 0.1), (0.1, 0.1, 0.1))
        with self.assertRaises(ValueError):
            box.minimum.setflags(write=True)

    def test_raw_identity_values_are_not_coerced(self) -> None:
        raw = _item(index=4).to_dict()
        raw["index"] = True
        with self.assertRaises(ValueError):
            ItemSpec.from_dict(raw)
        raw = _item(index=4).to_dict()
        raw["index"] = 4.5
        with self.assertRaises(ValueError):
            ItemSpec.from_dict(raw)
        raw = _item(index=4).to_dict()
        raw["belongs_to"] = True
        with self.assertRaises(ValueError):
            ItemSpec.from_dict(raw)
        malformed_container = _container(index=0)
        malformed_container["index"] = 0.5
        with self.assertRaises(ValueError):
            build_packing_state([malformed_container])

    def test_formatter_rejects_arbitrary_profile_string_and_bad_ordinal(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        state = build_packing_state([_container(index=17)])
        pool = [_item(index=4).to_dict()]
        profile = SearchSettings()
        proposal = PlacementProposal(4, 0, 0, 0, (0.0, 0.0, 0.08))
        box = AABB.from_center_half(proposal.position, (0.1, 0.15, 0.05))
        root = _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=state_fingerprint(state, pool, 0, profile.profile_digest()),
            item=_item(index=4),
            profile_digest=profile.profile_digest(),
            pool=pool,
            selected_pool_index=0,
            support_ratio=1.0,
            min_clearance=0.03,
        )
        with self.assertRaises(TypeError):
            agent.format_validated_action(root, state, pool, "forged-profile")  # type: ignore[call-arg]
        bad_proposal = dataclasses.replace(proposal, container_index=1)
        bad_root = dataclasses.replace(root, proposal=bad_proposal)
        with self.assertRaises((ValueError, NotReadyError)):
            agent.format_validated_action(bad_root, state, pool)

    def test_normal_items_have_ordinary_then_deferred_priority_proposals(self) -> None:
        state = build_packing_state([_container(index=10), _container(index=20, prioritized=True)])
        item = _item(index=4)
        ordinary = list(iter_fused_proposals(state, item, 0))
        deferred = list(iter_fused_proposals(state, item, 0, deferred=True))
        self.assertEqual({p.container_index for p in ordinary}, {0})
        self.assertEqual({p.container_index for p in deferred}, {1})


    def test_uninitialized_stays_not_ready_while_initialized_routes_fail_closed(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        item = {
            "index": 4,
            "length": 0.2,
            "width": 0.3,
            "height": 0.1,
            "mass": 2.0,
        }
        with self.assertRaises(NotReadyError):
            agent.policy({"pool_list": [item]})
        agent.get_init_states({"container_list": [_container()], "lookahead_k": 1})
        try:
            action = agent.policy({"container_list": [_container()], "pool_list": [item]})
        except (CandidateZeroError, PlanningError):
            pass
        else:
            self.assertEqual(
                set(action), {"item_idx", "container_idx", "place_pos", "orientation"}
            )
            self.assertEqual(action["place_pos"].dtype, np.float32)
            self.assertEqual(action["place_pos"].shape, (3,))
        self.assertEqual(agent.optimize([item]), [4])


if __name__ == "__main__":
    unittest.main()
