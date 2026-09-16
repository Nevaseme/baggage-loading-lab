from __future__ import annotations

import copy
import dataclasses
import json
import math
import sys
import time
import unittest
from pathlib import Path

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.portal_reserved_scaffold_dag.authorizer import (  # noqa: E402
    ActionProposal,
    AuthorizationError,
    AuthorizerProfile,
    _aabb_obb,
    _obb_separation,
    authorize_current,
    format_authorized_action,
    proposal_from_action,
)


SAFE_STATUS = {"is_included": True, "is_valid": True, "is_placed_safe": True}
RECOVERED_PLANE_STEPS = (0, 1, 2, 3, 5, 16, 17)


def _rectangular_container(
    *,
    center_x: float = 0.0,
    floor: float = 0.04,
    length: float = 2.0,
    width: float = 1.45,
    height: float = 1.61,
    packed_items: list[dict] | None = None,
    n_vecs: list[list[float]] | None = None,
    points: list[list[float]] | None = None,
    shelf: bool = False,
    index: int = 0,
) -> dict:
    if n_vecs is None:
        n_vecs = [
            [-1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 1.0],
        ]
    if points is None:
        points = [
            [center_x - length / 2.0 + 0.04, 0.0, 0.0],
            [center_x + length / 2.0 - 0.04, 0.0, 0.0],
            [center_x, -width / 2.0 + 0.04, 0.0],
            [center_x, width / 2.0 - 0.04, 0.0],
            [center_x, 0.0, floor],
            [center_x, 0.0, height - 0.04],
        ]
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": 0.04,
        "buffer": 0.0,
        "cut_x": 0.44,
        "cut_y": 0.4,
        "center": [center_x, 0.0, height / 2.0],
        "n_vecs": n_vecs,
        "points": points,
        "volume": length * width * height,
        "shelf": shelf,
        "require_shelf": shelf,
        "is_prioritized": False,
        "packed_items": list(packed_items or []),
    }


def _item(
    index: int = 7,
    *,
    length: float = 0.2,
    width: float = 0.2,
    height: float = 0.2,
    mass: float = 1.0,
    is_soft: bool = False,
    is_prioritized: bool = False,
) -> dict:
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "mass": mass,
        "is_soft": is_soft,
        "is_prioritized": is_prioritized,
    }


def _observation(
    *,
    item: dict | None = None,
    container: dict | None = None,
    pool: list[dict] | None = None,
) -> dict:
    return {
        "optimize": True,
        "lookahead_k": 1,
        "container_list": [container or _rectangular_container()],
        "pool_list": list(pool or [item or _item()]),
    }


def _proposal(
    observation: dict,
    *,
    position: tuple[float, float, float] = (0.0, 0.0, 0.15),
    orientation: int = 0,
    item_idx: int = 0,
    container_idx: int = 0,
    route: str = "historical",
) -> ActionProposal:
    return proposal_from_action(
        {
            "item_idx": item_idx,
            "container_idx": container_idx,
            "place_pos": np.asarray(position, dtype=np.float32),
            "orientation": orientation,
        },
        observation,
        route=route,
    )


class PortalReservedScaffoldAuthorizerTests(unittest.TestCase):
    def test_safe_rectangular_proposal_is_authorized_and_formats_official_action(self):
        # Catches an authorizer that never binds an action to the current state
        # or returns Python lists instead of the official float32 action type.
        observation = _observation()
        result = authorize_current(_proposal(observation), observation)
        self.assertTrue(result.accepted, result.reject_reasons)
        action = format_authorized_action(result, observation)
        self.assertEqual(set(action), {"item_idx", "container_idx", "place_pos", "orientation"})
        self.assertIs(type(action["item_idx"]), int)
        self.assertIs(type(action["container_idx"]), int)
        self.assertIs(type(action["orientation"]), int)
        self.assertEqual(action["place_pos"].dtype, np.dtype("float32"))
        self.assertEqual(action["place_pos"].tobytes(), result.proposal.position_f32_le)

    def test_captured_task000_recalls_at_least_24_of_25_and_rejects_step_25(self):
        # Catches changing a diagnostic replay into a step-number special case
        # and catches a shield that rejects the historical safe prefix wholesale.
        snapshot_dir = SIMULATOR_ROOT / "results" / "portal_reserved_scaffold" / "historical-task000-snapshots"
        if not snapshot_dir.is_dir():
            self.skipTest("Task 2 captured corpus is not materialized")
        from tests.replay_support import load_observation_snapshot

        accepted = []
        for step in range(26):
            observation, metadata = load_observation_snapshot(snapshot_dir / f"step-{step:03d}.npz")
            proposal = proposal_from_action(metadata["action"], observation, route="historical")
            result = authorize_current(proposal, observation)
            accepted.append(result.accepted)
            if step == 25:
                self.assertFalse(result.accepted, result.hard_evidence)
                self.assertIn("transport", result.reject_reasons)
        self.assertGreaterEqual(sum(accepted[:25]), 24)
        self.assertFalse(accepted[25])

    def test_recovered_plane_margin_steps_are_accepted(self):
        # Catches retaining the old -0.008 AABB plane gate for recovered steps.
        snapshot_dir = SIMULATOR_ROOT / "results" / "portal_reserved_scaffold" / "historical-task000-snapshots"
        if not snapshot_dir.is_dir():
            self.skipTest("Task 2 captured corpus is not materialized")
        from tests.replay_support import load_observation_snapshot

        for step in RECOVERED_PLANE_STEPS:
            observation, metadata = load_observation_snapshot(snapshot_dir / f"step-{step:03d}.npz")
            result = authorize_current(
                proposal_from_action(metadata["action"], observation, route="historical"),
                observation,
            )
            self.assertTrue(result.hard_evidence["plane_inclusion"], (step, result.hard_evidence))

    def test_float32_plane_margin_is_strict_for_every_axis_plane(self):
        # Catches adding a tolerance around the official -0.005 m inclusion
        # margin; expected positions are hand-derived at -5.0001/-4.9999 mm
        # after the proposal's float32 canonicalization.
        planes = [
            ((-1.0, 0.0, 0.0), (-0.5, 0.0, 0.0), (-0.3949999, 0.0, 0.15), (-0.3950001, 0.0, 0.15)),
            ((1.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.3949999, 0.0, 0.15), (0.3950001, 0.0, 0.15)),
            ((0.0, -1.0, 0.0), (0.0, -0.5, 0.0), (0.0, -0.3949999, 0.15), (0.0, -0.3950001, 0.15)),
            ((0.0, 1.0, 0.0), (0.0, 0.5, 0.0), (0.0, 0.3949999, 0.15), (0.0, 0.3950001, 0.15)),
            ((0.0, 0.0, -1.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.1050001), (0.0, 0.0, 0.1049999)),
            ((0.0, 0.0, 1.0), (0.0, 0.0, 0.5), (0.0, 0.0, 0.3949999), (0.0, 0.0, 0.3950001)),
        ]
        for normal, point, inside, outside in planes:
            n_vecs = [list(normal)]
            points = [list(point)]
            c = _rectangular_container(n_vecs=n_vecs, points=points)
            # Only the selected plane is relevant in this synthetic boundary.
            obs_inside = _observation(container=c)
            obs_outside = _observation(container=c)
            ri = authorize_current(_proposal(obs_inside, position=inside), obs_inside)
            ro = authorize_current(_proposal(obs_outside, position=outside), obs_outside)
            self.assertTrue(ri.hard_evidence["plane_inclusion"], (normal, ri.hard_evidence))
            self.assertFalse(ro.hard_evidence["plane_inclusion"], (normal, ro.hard_evidence))
            self.assertLessEqual(ri.hard_evidence["plane_max_dot"], -0.0050001 + 3.0e-8)
            self.assertGreaterEqual(ro.hard_evidence["plane_max_dot"], -0.0049999 - 3.0e-8)

    def test_cut_plane_and_world_local_conversion_with_nonzero_container_offset(self):
        # Catches dropping the diagonal cut plane or subtracting a container X
        # offset twice when observations contain world-space plane points.
        c = _rectangular_container(center_x=2.5)
        obs = _observation(container=c)
        result = authorize_current(_proposal(obs, position=(2.5, 0.0, 0.15)), obs)
        self.assertTrue(result.accepted, result.reject_reasons)
        local_points = copy.deepcopy(c["points"])
        for point in local_points:
            point[0] -= 2.5
        c_local = copy.deepcopy(c)
        c_local["points"] = local_points
        result_local = authorize_current(
            _proposal(_observation(container=c_local), position=(2.5, 0.0, 0.15)),
            _observation(container=c_local),
        )
        self.assertTrue(result_local.accepted, result_local.reject_reasons)

    def test_transport_contact_margin_is_15_mm_and_equality_is_conservative(self):
        # Catches use of the current 18 mm AABB proxy and verifies the official
        # 0.01 m sample/contact boundary, including equality rejection.
        def with_obstacle(gap: float) -> dict:
            obstacle = {
                **_item(index=99, length=0.2, width=0.2, height=0.2),
                "pos": [0.2 + gap, 0.0, 0.15],
                "orn": [0.0, 0.0, 0.0, 1.0],
                "belongs_to": 0,
            }
            return _observation(container=_rectangular_container(packed_items=[obstacle]))

        for gap, expected in ((0.015001, True), (0.015, False), (0.014999, False)):
            obs = with_obstacle(gap)
            result = authorize_current(_proposal(obs), obs)
            self.assertEqual(result.hard_evidence["transport"], expected, (gap, result.hard_evidence))

    def test_door_clamp_lift_and_ceiling_clip_are_reported(self):
        # Catches using target X for the first path segment and ignoring the
        # official resting-surface/effective-lift/ceiling clipping sequence.
        c = _rectangular_container()
        obs = _observation(container=c, item=_item(length=0.4, width=0.4, height=0.4))
        for position in ((0.8, 0.0, 0.25), (0.0, 0.0, 0.33), (0.0, 0.0, 1.4)):
            result = authorize_current(_proposal(obs, position=position), obs)
            self.assertIn("effective_lift", result.settling_evidence)
            self.assertIn("start_x", result.hard_evidence["transport_detail"])

    def test_effective_lift_has_zero_default_and_ceiling_clipped_partial_values(self):
        # Catches collapsing the official lift sequence into one constant or
        # skipping the ceiling-margin partial-lift branch.
        container = _rectangular_container()
        observation = _observation(container=container)
        resting = authorize_current(_proposal(observation, position=(0.0, 0.0, 0.14)), observation)
        default_lift = authorize_current(_proposal(observation, position=(0.0, 0.0, 0.5)), observation)
        partial_lift = authorize_current(_proposal(observation, position=(0.0, 0.0, 0.635)), observation)
        self.assertAlmostEqual(resting.settling_evidence["effective_lift"], 0.0, places=7)
        self.assertAlmostEqual(default_lift.settling_evidence["effective_lift"], 0.08, places=7)
        # Exact result for the hand literal after float32 target
        # canonicalization and the official ceiling-margin calculation.
        expected_partial_lift = 0.05150000953674323
        self.assertEqual(partial_lift.settling_evidence["effective_lift"], expected_partial_lift)

    def test_diagonal_cut_plane_float32_boundary_uses_hand_literal_one_e_minus_seven_m(self):
        # Catches replacing the true diagonal cut plane with an axis-aligned
        # proxy.  The two hand literals differ by exactly 1e-7 m around the
        # official margin after float32 canonicalization.
        normal = [-0.70710677, 0.0, -0.70710677]
        point = [-0.96, 0.0, 0.41769]
        container = _rectangular_container(n_vecs=[normal], points=[point])
        inside_observation = _observation(container=container)
        outside_observation = _observation(container=copy.deepcopy(container))
        inside = authorize_current(
            _proposal(inside_observation, position=(-0.96, 0.0, 0.62476110)),
            inside_observation,
        )
        outside = authorize_current(
            _proposal(outside_observation, position=(-0.96, 0.0, 0.62476100)),
            outside_observation,
        )
        self.assertLess(inside.hard_evidence["plane_max_dot"], -0.005)
        self.assertGreater(outside.hard_evidence["plane_max_dot"], -0.005)
        self.assertAlmostEqual(inside.hard_evidence["plane_max_dot"], -0.0050000412, delta=2.0e-8)
        self.assertAlmostEqual(outside.hard_evidence["plane_max_dot"], -0.0049999569, delta=2.0e-8)

    def test_orientation_four_small_shelf_and_tilted_obb_do_not_use_broad_aabb(self):
        # Catches the historical broad world-AABB shortcut, especially for a
        # settled tilted item whose oriented contact geometry leaves a path.
        tilted = {
            **_item(index=88, length=0.6, width=0.2, height=0.2),
            "pos": [0.0, 0.0, 0.45],
            "orn": [0.0, 0.0, math.sin(math.pi / 8.0), math.cos(math.pi / 8.0)],
            "belongs_to": 0,
        }
        c = _rectangular_container(packed_items=[tilted])
        item = _item(length=0.2, width=0.3, height=0.4)
        obs = _observation(item=item, container=c)
        result = authorize_current(_proposal(obs, position=(0.7, 0.0, 0.25), orientation=4), obs)
        self.assertTrue(result.hard_evidence["transport"], result.hard_evidence)

    def test_target_penetration_rejects_but_contact_and_nearness_are_risk_evidence(self):
        # Catches a hard 15–18 mm target-nearness gate and catches silently
        # accepting an actual positive-volume placement overlap.
        contact = {
            **_item(index=88, length=0.2, width=0.2, height=0.2),
            "pos": [0.215, 0.0, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        obs_contact = _observation(container=_rectangular_container(packed_items=[contact]))
        contact_result = authorize_current(_proposal(obs_contact), obs_contact)
        self.assertTrue(contact_result.hard_evidence["target_penetration"] is False)
        self.assertIn("target_clearance", contact_result.hard_evidence)
        penetrating = copy.deepcopy(contact)
        penetrating["pos"][0] = 0.19
        obs_penetrating = _observation(container=_rectangular_container(packed_items=[penetrating]))
        penetrating_result = authorize_current(_proposal(obs_penetrating), obs_penetrating)
        self.assertFalse(penetrating_result.accepted)
        self.assertIn("target_penetration", penetrating_result.reject_reasons)

    def test_settling_risk_features_do_not_become_hard_validity(self):
        # Catches the old 75/90% support, 2 cm core, protection, and depth
        # gates being copied into the official validity decision.
        support = {
            **_item(index=88, length=0.2, width=0.2, height=0.2),
            "pos": [0.14, 0.0, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        c = _rectangular_container(packed_items=[support], shelf=True)
        obs = _observation(container=c, item=_item(is_soft=False, is_prioritized=False))
        result = authorize_current(_proposal(obs, position=(0.0, 0.0, 0.364)), obs)
        self.assertNotIn("support_ratio", result.reject_reasons)
        self.assertNotIn("center_support", result.reject_reasons)
        self.assertNotIn("protection", result.reject_reasons)
        self.assertNotIn("depth_map", result.reject_reasons)

    def test_drop_boundary_and_no_landing_surface_are_the_only_settling_rejections(self):
        # Catches a non-strict 0.3 m comparison and catches treating a
        # free-floating target as safe merely because it is inside the planes.
        for z, should_reject in ((0.400001, True), (0.399999, False)):
            obs = _observation(container=_rectangular_container(floor=0.0))
            result = authorize_current(_proposal(obs, position=(0.0, 0.0, z)), obs)
            self.assertEqual("predicted_drop" in result.reject_reasons, should_reject)
        no_floor = _rectangular_container(
            n_vecs=[[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 1.0, 0.0]],
            points=[[-0.96, 0.0, 0.0], [0.96, 0.0, 0.0], [0.0, -0.685, 0.0], [0.0, 0.685, 0.0]],
        )
        obs = _observation(container=no_floor)
        result = authorize_current(_proposal(obs), obs)
        self.assertFalse(result.accepted)
        self.assertIn("no_landing_surface", result.reject_reasons)

    def test_state_fingerprint_makes_reordered_and_changed_state_authorizations_stale(self):
        # Catches hashing only the selected item or dimensions and omitting
        # pool order, duplicate occurrences, packed raw poses/quaternions, and
        # container metadata/profile semantics.
        obs = _observation(pool=[_item(7), _item(7, width=0.21)])
        proposal = _proposal(obs, item_idx=0)
        result = authorize_current(proposal, obs)
        self.assertTrue(result.accepted)
        changed = copy.deepcopy(obs)
        changed["pool_list"] = list(reversed(changed["pool_list"]))
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, changed)
        changed = copy.deepcopy(obs)
        packed = {
            **_item(index=88),
            "pos": [0.7, 0.4, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        changed["container_list"][0]["packed_items"] = [packed]
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, changed)
        changed = copy.deepcopy(obs)
        changed["container_list"][0]["index"] = 5
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, changed)
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, obs, profile=AuthorizerProfile(transport_contact_margin=0.016))

    def test_fingerprint_makes_packed_pose_quaternion_and_container_ordinal_stale_independently(self):
        # Catches hashing only packed dimensions and selected metadata rather
        # than each raw pose/quaternion and the ordered container occurrence.
        packed = {
            **_item(index=88),
            "pos": [0.7, 0.4, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        base_container = _rectangular_container(packed_items=[packed], index=10)
        second_container = _rectangular_container(center_x=3.0, index=11)
        observation = _observation(container=base_container)
        observation["container_list"] = [base_container, second_container]
        result = authorize_current(_proposal(observation, container_idx=0), observation)
        self.assertTrue(result.accepted, result.reject_reasons)

        changed_pose = copy.deepcopy(observation)
        changed_pose["container_list"][0]["packed_items"][0]["pos"][0] += 0.001
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, changed_pose)

        changed_quaternion = copy.deepcopy(observation)
        changed_quaternion["container_list"][0]["packed_items"][0]["orn"] = [
            0.0,
            0.70710677,
            0.0,
            0.70710677,
        ]
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, changed_quaternion)

        reordered_containers = copy.deepcopy(observation)
        reordered_containers["container_list"] = list(reversed(reordered_containers["container_list"]))
        with self.assertRaises(AuthorizationError):
            format_authorized_action(result, reordered_containers)

    def test_result_copy_forgery_and_unaccepted_result_cannot_format(self):
        # Catches using a boolean or dataclass equality as an authorization
        # receipt, which would permit copy/replace/forged results to format.
        obs = _observation()
        result = authorize_current(_proposal(obs), obs)
        self.assertTrue(result.accepted)
        for forged in (
            copy.copy(result),
            dataclasses.replace(result),
            AuthorizationResultForTest(result),
        ):
            with self.assertRaises(AuthorizationError):
                format_authorized_action(forged, obs)
        rejected = authorize_current(_proposal(obs, position=(0.0, 0.0, 0.0)), obs)
        self.assertFalse(rejected.accepted)
        with self.assertRaises(AuthorizationError):
            format_authorized_action(rejected, obs)
        with self.assertRaises(AuthorizationError):
            format_authorized_action(True, obs)

    def test_invalid_types_nan_overflow_orientation_and_expired_deadline_fail_closed(self):
        # Catches bool-as-int coercion, NumPy integer coercion, non-finite or
        # float32-overflow positions, invalid orientations, and stale deadlines.
        obs = _observation()
        invalid_actions = [
            {"item_idx": True, "container_idx": 0, "place_pos": [0.0, 0.0, 0.15], "orientation": 0},
            {"item_idx": np.int64(0), "container_idx": 0, "place_pos": [0.0, 0.0, 0.15], "orientation": 0},
            {"item_idx": 0, "container_idx": 0, "place_pos": [math.nan, 0.0, 0.15], "orientation": 0},
            {"item_idx": 0, "container_idx": 0, "place_pos": [math.inf, 0.0, 0.15], "orientation": 0},
            {"item_idx": 0, "container_idx": 0, "place_pos": [1e40, 0.0, 0.15], "orientation": 0},
            {"item_idx": 0, "container_idx": 0, "place_pos": [0.0, 0.0, 0.15], "orientation": 6},
        ]
        for action in invalid_actions:
            proposal = proposal_from_action(action, obs, route="historical", allow_invalid=True)
            result = authorize_current(proposal, obs)
            self.assertFalse(result.accepted, (action, result))
            self.assertTrue(result.reject_reasons)
        expired = authorize_current(_proposal(obs), obs, deadline=time.perf_counter() - 1.0)
        self.assertFalse(expired.accepted)
        self.assertIn("deadline", expired.reject_reasons)

    def test_route_labels_share_one_authorizer_and_cannot_bypass_rejection(self):
        # Catches route-specific emergency/repair bypasses; all labels must use
        # the current-state hard authorizer.
        obs = _observation()
        obstacle = {
            **_item(index=88),
            "pos": [0.0, 0.0, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        obs["container_list"][0]["packed_items"] = [obstacle]
        for route in ("historical", "planned", "repair", "emergency"):
            result = authorize_current(_proposal(obs, route=route), obs)
            self.assertFalse(result.accepted, (route, result.reject_reasons))
            with self.assertRaises(AuthorizationError):
                format_authorized_action(result, obs)

    def test_inverted_door_bounds_use_the_official_clamp_and_reject_start_collision(self):
        # The official expression is min(max(target_x, x_min), x_max), even
        # when x_min > x_max.  The old branch skipped the clamp and missed the
        # obstacle at the resulting official start coordinate.
        item = _item(length=1.0, width=0.2, height=0.2)
        obstacle = {
            **_item(index=99, length=0.3, width=0.2, height=0.2),
            "pos": [0.85, 0.0, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        container = _rectangular_container(length=1.5, packed_items=[obstacle])
        container["cut_x"] = 0.45
        observation = _observation(item=item, container=container)
        result = authorize_current(_proposal(observation, position=(-0.1, 0.0, 0.15)), observation)
        self.assertAlmostEqual(result.hard_evidence["transport_detail"]["start_x"], 0.2, places=12)
        self.assertFalse(result.hard_evidence["transport"], result.hard_evidence)
        self.assertIn("transport", result.reject_reasons)

    def test_action_position_range_is_hard_validated_after_float32_canonicalization(self):
        # 200.0 is representable as float32, but outside the official action
        # range and must not reach geometry or env.step.
        observation = _observation()
        proposal = proposal_from_action(
            {
                "item_idx": 0,
                "container_idx": 0,
                "place_pos": np.asarray([200.0, 0.0, 0.15], dtype=np.float32),
                "orientation": 0,
            },
            observation,
        )
        result = authorize_current(proposal, observation)
        self.assertFalse(result.accepted)
        self.assertIn("action_position_range", result.reject_reasons)
        for value, outside in ((-100.0, False), (100.0, False), (-100.00001, True), (100.00001, True)):
            boundary_proposal = proposal_from_action(
                {
                    "item_idx": 0,
                    "container_idx": 0,
                    "place_pos": np.asarray([value, 0.0, 0.15], dtype=np.float32),
                    "orientation": 0,
                },
                observation,
            )
            boundary_result = authorize_current(boundary_proposal, observation)
            self.assertEqual("action_position_range" in boundary_result.reject_reasons, outside, value)

    def test_obb_separation_is_exact_euclidean_distance_with_intersection_zero(self):
        # Hand-derived AABB fixtures exercise the closest edge/vertex feature,
        # strict 15 mm transport threshold, and positive-volume intersection.
        first = _aabb_obb((0.0, 0.0, 0.0), (0.1, 0.1, 0.1))
        diagonal = _aabb_obb((0.211, 0.211, 0.0), (0.1, 0.1, 0.1))
        equality = _aabb_obb((0.215, 0.0, 0.0), (0.1, 0.1, 0.1))
        near = _aabb_obb((0.214999, 0.0, 0.0), (0.1, 0.1, 0.1))
        overlap = _aabb_obb((0.19, 0.0, 0.0), (0.1, 0.1, 0.1))
        self.assertAlmostEqual(_obb_separation(first, diagonal), math.sqrt(0.011**2 + 0.011**2), places=12)
        self.assertGreater(_obb_separation(first, diagonal), 0.015)
        self.assertAlmostEqual(_obb_separation(first, equality), 0.015, places=12)
        self.assertAlmostEqual(_obb_separation(first, near), 0.014999, places=12)
        self.assertEqual(_obb_separation(first, overlap), 0.0)

    def test_diagonal_euclidean_transport_gap_over_15_mm_passes(self):
        # Catches an axis-wise/AABB transport shortcut: two 11 mm component
        # gaps have a 15.556 mm Euclidean clearance and must pass 15 mm.
        obstacle = {
            **_item(index=99, length=0.2, width=0.2, height=0.2),
            "pos": [0.211, 0.211, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        observation = _observation(container=_rectangular_container(packed_items=[obstacle]))
        result = authorize_current(_proposal(observation), observation)
        self.assertTrue(result.accepted, result.reject_reasons)
        self.assertGreater(result.hard_evidence["target_clearance"], 0.015)
        self.assertGreater(result.hard_evidence["transport_min_clearance"], 0.015)

    def test_settling_uses_four_cm_drop_and_highest_14_mm_support_without_a_three_cm_gate(self):
        # Lower overlap surfaces are legal landing candidates.  A 4 cm drop is
        # below the 0.3 m displacement limit, and a 14 mm support gap is not a
        # hard invalidity.
        support = {
            **_item(index=88, length=0.201, width=0.2, height=0.2, mass=5.0, is_soft=True, is_prioritized=True),
            "pos": [0.0, 0.0, 0.1],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        container = _rectangular_container(floor=0.0, packed_items=[support])
        item = _item(length=0.3, width=0.2, height=0.2, mass=2.0)
        observation = _observation(item=item, container=container)
        result = authorize_current(_proposal(observation, position=(0.0, 0.0, 0.314)), observation)
        self.assertTrue(result.accepted, result.reject_reasons)
        self.assertAlmostEqual(result.settling_evidence["predicted_drop"], 0.014, delta=2.0e-7)
        self.assertAlmostEqual(result.settling_evidence["support_ratio"], 0.67, places=2)
        self.assertAlmostEqual(result.settling_evidence["supporter_load"], 5.0, places=9)

        floor_observation = _observation(
            item=_item(length=0.2, width=0.2, height=0.2),
            container=_rectangular_container(floor=0.0),
        )
        four_cm = authorize_current(_proposal(floor_observation, position=(0.0, 0.0, 0.14)), floor_observation)
        self.assertTrue(four_cm.accepted, four_cm.reject_reasons)
        self.assertAlmostEqual(four_cm.settling_evidence["predicted_drop"], 0.04, delta=2.0e-7)

    def test_protection_load_and_depth_diagnostics_change_with_observable_inputs_without_hard_gating(self):
        # Risk diagnostics must expose supporter attributes and an available
        # depth proxy, while remaining separate from official hard validity.
        support = {
            **_item(index=88, length=0.201, width=0.2, height=0.2, mass=5.0, is_soft=True, is_prioritized=True),
            "pos": [0.0, 0.0, 0.1],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        container = _rectangular_container(floor=0.0, packed_items=[support])
        item = _item(length=0.3, width=0.2, height=0.2, mass=2.0, is_soft=False, is_prioritized=False)
        observation = _observation(item=item, container=container)
        observation["depth_map"] = np.full((2, 2), 0.314, dtype=np.float32)
        result = authorize_current(_proposal(observation, position=(0.0, 0.0, 0.314)), observation)
        self.assertTrue(result.accepted, result.reject_reasons)
        self.assertTrue(result.score_evidence["protection_violation"])
        self.assertTrue(result.score_evidence["hard_on_soft_violation"])
        self.assertTrue(result.score_evidence["hard_on_priority_violation"])
        self.assertTrue(result.score_evidence["depth_map_consistent"])
        self.assertEqual(result.settling_evidence["supporter_load"], 5.0)

        changed_support = copy.deepcopy(observation)
        changed_support["container_list"][0]["packed_items"][0]["mass"] = 10.0
        changed_support["depth_map"] = np.full((2, 2), 10.0, dtype=np.float32)
        changed_result = authorize_current(
            _proposal(changed_support, position=(0.0, 0.0, 0.314)),
            changed_support,
        )
        self.assertTrue(changed_result.accepted, changed_result.reject_reasons)
        self.assertEqual(changed_result.settling_evidence["supporter_load"], 10.0)
        self.assertFalse(changed_result.score_evidence["depth_map_consistent"])

    def test_fingerprint_covers_all_container_metadata_packed_keys_and_depth_arrays(self):
        # Every observable metadata key, ordered packed occurrence, and depth
        # array participates in freshness; volume-only fingerprints are stale.
        observation = _observation()
        observation["depth_map"] = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        result = authorize_current(_proposal(observation), observation)
        self.assertTrue(result.accepted, result.reject_reasons)
        mutations = []
        changed = copy.deepcopy(observation)
        changed["container_list"][0]["volume"] += 0.1
        mutations.append(changed)
        changed = copy.deepcopy(observation)
        changed["container_list"][0]["observable_probe"] = {"enabled": True}
        mutations.append(changed)
        changed = copy.deepcopy(observation)
        changed["depth_map"][0, 0] = 99.0
        mutations.append(changed)
        packed = {
            **_item(index=88),
            "pos": [0.7, 0.4, 0.15],
            "orn": [0.0, 0.0, 0.0, 1.0],
            "belongs_to": 0,
        }
        changed = copy.deepcopy(observation)
        changed["container_list"][0]["packed_items"] = [packed]
        mutations.append(changed)
        for mutated in mutations:
            with self.assertRaises(AuthorizationError):
                format_authorized_action(result, mutated)


class AuthorizationResultForTest:
    """A type-distinct forge used without importing private receipt helpers."""

    def __init__(self, source):
        for field in dataclasses.fields(source):
            object.__setattr__(self, field.name, getattr(source, field.name))


if __name__ == "__main__":
    unittest.main()
