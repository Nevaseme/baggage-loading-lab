import pathlib
import sys
import time
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.ems import (  # noqa: E402
    EMS,
    ProxyAction,
    ProxyState,
    _prune_spaces,
    _proxy_path_clear,
    _split_ems,
    apply_action,
    build_proxy_state,
    propose_actions,
    state_key,
)
from agents.highscore.model import AABB, ItemSpec, PlacedItem, Rect  # noqa: E402
from agents.highscore.state import build_packing_state  # noqa: E402


def _container_dict(*, shelf=False):
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": 0,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (0.0, 0.0, height / 2),
        "points": [
            [length / 2 - thickness, 0.0, 0.0],
            [-length / 2 + thickness, 0.0, 0.0],
            [0.0, width / 2 - thickness, 0.0],
            [0.0, -width / 2 + thickness, 0.0],
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
        "volume": 4.0,
        "shelf": shelf,
        "packed_items": [],
    }


def _item(index=1, *, prioritized=False, soft=False):
    return ItemSpec(index=index, length=0.75, width=0.30, height=0.20,
                    is_prioritized=prioritized, is_soft=soft)


def _rect_union_area(rectangles):
    xs = sorted({value for rect in rectangles for value in (rect.min_x, rect.max_x)})
    ys = sorted({value for rect in rectangles for value in (rect.min_y, rect.max_y)})
    return sum(
        (right - left) * (back - front)
        for left, right in zip(xs, xs[1:])
        for front, back in zip(ys, ys[1:])
        if any(
            rect.min_x <= left and rect.max_x >= right
            and rect.min_y <= front and rect.max_y >= back
            for rect in rectangles
        )
    )


class EMSSplitTests(unittest.TestCase):
    def test_split_returns_nondominated_maximal_spaces_covering_free_area(self):
        space = EMS(Rect(0.0, 2.0, 0.0, 2.0), 0.0, 1.0, 0, (False, False))
        residuals = _split_ems(space, Rect(0.5, 1.5, 0.5, 1.5))

        self.assertEqual(
            {candidate.rect for candidate in residuals},
            {
                Rect(0.0, 0.5, 0.0, 2.0),
                Rect(1.5, 2.0, 0.0, 2.0),
                Rect(0.0, 2.0, 0.0, 0.5),
                Rect(0.0, 2.0, 1.5, 2.0),
            },
        )
        footprint = Rect(0.5, 1.5, 0.5, 1.5)
        self.assertTrue(all(candidate.rect.intersection(footprint) is None for candidate in residuals))
        self.assertFalse(any(
            first.rect.min_x <= second.rect.min_x
            and first.rect.max_x >= second.rect.max_x
            and first.rect.min_y <= second.rect.min_y
            and first.rect.max_y >= second.rect.max_y
            for first in residuals for second in residuals if first is not second
        ))
        self.assertAlmostEqual(_rect_union_area([candidate.rect for candidate in residuals]), 3.0)
        self.assertEqual(set(_prune_spaces(list(residuals))), set(residuals))

    def test_prune_removes_a_directly_contained_space(self):
        outer = EMS(Rect(0.0, 2.0, 0.0, 2.0), 0.0, 1.0, 0, (False, False))
        inner = EMS(Rect(0.5, 1.5, 0.5, 1.5), 0.0, 1.0, 0, (False, False))
        self.assertEqual(_prune_spaces([inner, outer]), (outer,))

    def test_boundary_touch_is_not_collision_but_sub_millimetre_overlap_is(self):
        state = ProxyState(
            spaces=(EMS(Rect(0.0, 2.0, 0.0, 1.0), 0.0, 1.0, 0, (False, False)),),
            boxes=(AABB.from_center_half((0.5, 0.5, 0.1), (0.5, 0.5, 0.1)),),
            placed_ids=(9,),
        )
        item = ItemSpec(index=2, length=0.5, width=1.0, height=0.2)
        touching = ProxyAction(item, 0, 0, 0,
                               AABB.from_center_half((1.25, 0.5, 0.1), (0.25, 0.5, 0.1)), (0, 0))
        overlapping = ProxyAction(item, 0, 0, 0,
                                  AABB.from_center_half((1.2495, 0.5, 0.1), (0.25, 0.5, 0.1)), (0, 0))

        self.assertIsNotNone(apply_action(state, touching, clearance=0.0))
        self.assertIsNone(apply_action(state, overlapping, clearance=0.0))


class ProxySupportTests(unittest.TestCase):
    def test_floor_placed_footprint_is_removed_only_from_its_base_layer(self):
        packing = build_packing_state([_container_dict()])
        box = AABB.from_center_half((-0.75, 0.0, 0.148), (0.10, 0.10, 0.10))
        packing.containers[0].placed.append(PlacedItem(_item(50), box))

        proxy = build_proxy_state(packing, clearance=0.018)
        floor_spaces = [space for space in proxy.spaces if abs(space.bottom_z - 0.048) < 1e-9]
        shelf_spaces = [space for space in proxy.spaces if abs(space.bottom_z - 0.862) < 1e-9]

        self.assertTrue(floor_spaces)
        self.assertTrue(all(space.rect.intersection(box.footprint) is None for space in floor_spaces))
        self.assertTrue(any(abs(space.bottom_z - 0.248) < 1e-9 for space in proxy.spaces))
        self.assertTrue(any(space.rect.intersection(box.footprint) is not None for space in shelf_spaces))

    def test_shelf_placed_footprint_is_removed_only_from_shelf_layer(self):
        packing = build_packing_state([_container_dict(shelf=True)])
        box = AABB.from_center_half((0.30, 0.30, 0.962), (0.10, 0.10, 0.10))
        packing.containers[0].placed.append(PlacedItem(_item(51), box))

        proxy = build_proxy_state(packing, clearance=0.018)
        shelf_spaces = [space for space in proxy.spaces if abs(space.bottom_z - 0.862) < 1e-9]
        floor_spaces = [space for space in proxy.spaces if abs(space.bottom_z - 0.048) < 1e-9]

        self.assertTrue(shelf_spaces)
        self.assertTrue(all(space.rect.intersection(box.footprint) is None for space in shelf_spaces))
        self.assertTrue(any(abs(space.bottom_z - 1.062) < 1e-9 for space in proxy.spaces))
        self.assertTrue(any(space.rect.intersection(box.footprint) is not None for space in floor_spaces))

    def test_tilted_item_removes_its_base_footprint_without_adding_top_support(self):
        packing = build_packing_state([_container_dict()])
        box = AABB.from_center_half(
            (0.30, 0.20, 0.148), (0.10, 0.10, 0.10), axis_aligned=False
        )
        packing.containers[0].placed.append(PlacedItem(_item(52), box))

        proxy = build_proxy_state(packing, clearance=0.018)
        floor_spaces = [space for space in proxy.spaces if abs(space.bottom_z - 0.048) < 1e-9]

        self.assertTrue(all(space.rect.intersection(box.footprint) is None for space in floor_spaces))
        self.assertFalse(any(abs(space.bottom_z - 0.248) < 1e-9 for space in proxy.spaces))

    def test_nearby_but_unsupported_height_does_not_subtract_floor_layer(self):
        packing = build_packing_state([_container_dict()])
        box = AABB.from_center_half((0.30, 0.20, 0.155), (0.10, 0.10, 0.10))
        packing.containers[0].placed.append(PlacedItem(_item(53), box))

        proxy = build_proxy_state(packing, clearance=0.018)
        floor_spaces = [space for space in proxy.spaces if abs(space.bottom_z - 0.048) < 1e-9]

        self.assertTrue(any(space.rect.intersection(box.footprint) is not None for space in floor_spaces))

    def test_build_proxy_state_keeps_floor_shelf_and_aligned_top_supports_separate(self):
        packing = build_packing_state([_container_dict(shelf=True)])
        container = packing.containers[0]
        aligned = _item(10, prioritized=True)
        container.placed.append(
            PlacedItem(aligned, AABB.from_center_half((0.45, 0.0, 0.30), (0.20, 0.20, 0.10)))
        )
        tilted = _item(11, soft=True)
        container.placed.append(
            PlacedItem(tilted, AABB.from_center_half((-0.45, 0.0, 0.30), (0.20, 0.20, 0.10), axis_aligned=False))
        )

        proxy = build_proxy_state(packing, clearance=0.008)
        bottoms = {round(space.bottom_z, 3) for space in proxy.spaces}
        self.assertIn(0.048, bottoms)
        self.assertIn(0.862, bottoms)
        self.assertIn(0.400, bottoms)
        self.assertEqual(len(proxy.boxes), 4)  # two packed items and both shelf obstacles
        self.assertTrue(any(space.protection == (True, False) and abs(space.bottom_z - 0.400) < 1e-9
                            for space in proxy.spaces))
        self.assertFalse(any(space.rect.max_x < 0.0 and abs(space.bottom_z - 0.408) < 1e-9
                             for space in proxy.spaces))

    def test_build_proxy_state_preserves_candidate_transport_metadata(self):
        proxy = build_proxy_state(build_packing_state([_container_dict(shelf=True)]), clearance=0.008)
        self.assertEqual(proxy.door_planes, ((0, -0.75),))
        self.assertEqual(proxy.entrance_ranges[0][0], 0)
        self.assertAlmostEqual(proxy.entrance_ranges[0][1], -0.55)
        self.assertAlmostEqual(proxy.entrance_ranges[0][2], 0.95)
        self.assertEqual(proxy.resting_surfaces[0][0], 0)
        self.assertAlmostEqual(proxy.resting_surfaces[0][1][0], 0.04)
        self.assertAlmostEqual(proxy.resting_surfaces[0][1][1], 0.84)
        self.assertEqual(proxy.ceiling_surfaces[0][0], 0)
        self.assertAlmostEqual(proxy.ceiling_surfaces[0][1][0], 0.8)
        self.assertAlmostEqual(proxy.ceiling_surfaces[0][1][1], 1.56)

    def test_support_levels_are_independent_of_eighteen_millimetre_path_clearance(self):
        packing = build_packing_state([_container_dict(shelf=True)])
        container = packing.containers[0]
        container.placed.append(
            PlacedItem(_item(31), AABB.from_center_half((0.45, 0.0, 0.30), (0.20, 0.20, 0.10)))
        )
        proxy = build_proxy_state(packing, clearance=0.018)

        self.assertTrue(any(abs(space.bottom_z - 0.048) < 1e-9 for space in proxy.spaces))
        self.assertTrue(any(abs(space.bottom_z - 0.862) < 1e-9 for space in proxy.spaces))
        self.assertTrue(any(abs(space.bottom_z - 0.400) < 1e-9 for space in proxy.spaces))
        actions = propose_actions(proxy, ItemSpec(index=32, length=0.2, width=0.2, height=0.2), 0,
                                  limit=20, deadline=time.perf_counter() + 1.0)
        self.assertTrue(any(abs(action.box.minimum[2] - 0.048) < 1e-9 for action in actions))

    def test_shelf_gaps_cannot_support_a_bridging_box(self):
        state = ProxyState(
            spaces=(
                EMS(Rect(-0.5, -0.05, -0.5, 0.5), 0.3, 1.0, 0, (False, False)),
                EMS(Rect(0.05, 0.5, -0.5, 0.5), 0.3, 1.0, 0, (False, False)),
            ), boxes=(), placed_ids=(),
        )
        actions = propose_actions(state, ItemSpec(index=3, length=0.6, width=0.6, height=0.6), 0,
                                  limit=20, deadline=time.perf_counter() + 1.0)
        self.assertFalse(actions)


class ProxyActionTests(unittest.TestCase):
    def test_boxes_only_block_actions_in_their_own_container(self):
        spaces = (
            EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 0.6, 0, (False, False)),
            EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 0.6, 1, (False, False)),
        )
        blocker = AABB.from_center_half((0.0, 0.0, 0.1), (0.49, 0.49, 0.1))
        item = ItemSpec(index=40, length=0.2, width=0.2, height=0.2)
        other_container_blocked = ProxyState(
            spaces=spaces, boxes=(blocker,), placed_ids=(9,), box_containers=(0,),
        )
        same_container_blocked = ProxyState(
            spaces=spaces, boxes=(blocker,), placed_ids=(9,), box_containers=(1,),
        )

        other_actions = propose_actions(
            other_container_blocked, item, 0, limit=80, deadline=time.perf_counter() + 1.0
        )
        same_actions = propose_actions(
            same_container_blocked, item, 0, limit=80, deadline=time.perf_counter() + 1.0
        )
        self.assertTrue(any(action.container_index == 1 for action in other_actions))
        self.assertFalse(any(action.container_index == 1 for action in same_actions))

        action = next(action for action in other_actions if action.container_index == 1)
        self.assertIsNotNone(apply_action(other_container_blocked, action, clearance=0.0))
        same_action = ProxyAction(
            item, 0, 1, action.orientation, action.box, (1, 1)
        )
        self.assertIsNone(apply_action(same_container_blocked, same_action, clearance=0.0))

    def test_transport_path_ignores_other_container_blocker_but_rejects_same_container(self):
        space = EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.2, 1.0, 1, (False, False))
        candidate = AABB.from_center_half((0.0, 0.4, 0.3), (0.1, 0.1, 0.1))
        blocker = AABB.from_center_half((0.0, -0.4, 0.3), (0.1, 0.1, 0.1))
        metadata = dict(
            door_planes=((1, -0.75),), entrance_ranges=((1, -0.5, 0.5),),
            resting_surfaces=((1, (0.04, 0.84)),), ceiling_surfaces=((1, (0.8, 1.56)),),
        )
        other = ProxyState(
            spaces=(space,), boxes=(blocker,), placed_ids=(), box_containers=(0,), **metadata
        )
        same = ProxyState(
            spaces=(space,), boxes=(blocker,), placed_ids=(), box_containers=(1,), **metadata
        )
        self.assertTrue(_proxy_path_clear(candidate, space, other, 0.0))
        self.assertFalse(_proxy_path_clear(candidate, space, same, 0.0))

    def test_transport_path_starts_at_physical_door_not_support_edge(self):
        space = EMS(Rect(-0.5, 0.5, 0.0, 0.5), 0.2, 1.0, 0, (False, False))
        candidate = AABB.from_center_half((0.0, 0.4, 0.3), (0.1, 0.1, 0.1))
        blocker = AABB.from_center_half((0.0, -0.4, 0.3), (0.1, 0.1, 0.1))
        physical = ProxyState(
            spaces=(space,), boxes=(blocker,), placed_ids=(),
            door_planes=((0, -0.75),), entrance_ranges=((0, -0.5, 0.5),),
            resting_surfaces=((0, (0.04, 0.84)),), ceiling_surfaces=((0, (0.8, 1.56)),),
        )
        synthetic = ProxyState(spaces=(space,), boxes=(blocker,), placed_ids=())
        self.assertFalse(_proxy_path_clear(candidate, space, physical, 0.0))
        self.assertTrue(_proxy_path_clear(candidate, space, synthetic, 0.0))

    def test_transport_path_uses_effective_lift_to_reject_lift_only_blocker(self):
        space = EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.2, 1.0, 0, (False, False))
        candidate = AABB.from_center_half((0.0, 0.4, 0.3), (0.1, 0.1, 0.1))
        blocker = AABB.from_center_half((0.0, -0.2, 0.47), (0.1, 0.1, 0.02))
        state = ProxyState(
            spaces=(space,), boxes=(blocker,), placed_ids=(),
            door_planes=((0, -0.75),), entrance_ranges=((0, -0.5, 0.5),),
            resting_surfaces=((0, (0.04, 0.84)),), ceiling_surfaces=((0, (0.8, 1.56)),),
        )
        self.assertFalse(_proxy_path_clear(candidate, space, state, 0.0))

    def test_transport_path_rejects_an_item_that_cannot_fit_entry_x_bounds(self):
        space = EMS(Rect(-1.0, 1.0, -0.5, 0.5), 0.2, 1.0, 0, (False, False))
        candidate = AABB.from_center_half((0.0, 0.2, 0.3), (0.4, 0.1, 0.1))
        state = ProxyState(
            spaces=(space,), boxes=(), placed_ids=(),
            door_planes=((0, -0.75),), entrance_ranges=((0, -0.1, 0.1),),
            resting_surfaces=((0, (0.04,)),), ceiling_surfaces=((0, (1.56,)),),
        )
        self.assertFalse(_proxy_path_clear(candidate, space, state, 0.0))

    def test_proposals_cover_six_orientations_and_sort_low_height_increase_first(self):
        state = ProxyState(
            spaces=(EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False)),),
            boxes=(), placed_ids=(),
        )
        actions = propose_actions(state, _item(), 4, limit=48, deadline=time.perf_counter() + 1.0)

        self.assertEqual({action.orientation for action in actions}, set(range(6)))
        increases = [float(action.box.maximum[2] - state.spaces[0].bottom_z) for action in actions]
        self.assertEqual(increases, sorted(increases))
        self.assertTrue(any(action.box.minimum[0] <= -0.49 and action.box.maximum[0] >= 0.24
                            for action in actions if action.orientation == 0))

    def test_proposals_reject_protected_support_and_expanded_collisions(self):
        protected = ProxyState(
            spaces=(EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (True, True)),),
            boxes=(), placed_ids=(),
        )
        self.assertFalse(propose_actions(protected, _item(), 0, limit=20, deadline=time.perf_counter() + 1.0))
        self.assertTrue(propose_actions(protected, _item(prioritized=True, soft=True), 0,
                                        limit=20, deadline=time.perf_counter() + 1.0))

        blocked = ProxyState(
            spaces=(EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False)),),
            boxes=(AABB.from_center_half((0.0, 0.0, 0.1), (0.499, 0.499, 0.1)),), placed_ids=(8,),
        )
        self.assertFalse(propose_actions(blocked, _item(), 0, limit=20, deadline=time.perf_counter() + 1.0))

    def test_proposals_reject_a_one_millimetre_gap_inside_state_clearance(self):
        state = ProxyState(
            spaces=(EMS(Rect(0.0, 0.5, 0.0, 0.5), 0.0, 0.6, 0, (False, False)),),
            boxes=(AABB.from_center_half((0.601, 0.25, 0.05), (0.1, 0.25, 0.05)),),
            placed_ids=(8,),
            clearance=0.002,
        )
        item = ItemSpec(index=4, length=0.5, width=0.5, height=0.1)
        actions = propose_actions(state, item, 0, limit=20, deadline=time.perf_counter() + 1.0)
        self.assertFalse(any(np.isclose(action.box.maximum[0], 0.5) for action in actions))

    def test_eighteen_millimetre_path_clearance_rejects_a_ten_millimetre_gap(self):
        state = ProxyState(
            spaces=(EMS(Rect(0.0, 0.5, 0.0, 0.5), 0.0, 0.6, 0, (False, False)),),
            boxes=(AABB.from_center_half((0.61, 0.25, 0.05), (0.1, 0.25, 0.05)),),
            placed_ids=(8,), clearance=0.018,
        )
        actions = propose_actions(state, ItemSpec(index=33, length=0.5, width=0.5, height=0.1), 0,
                                  limit=20, deadline=time.perf_counter() + 1.0)
        self.assertFalse(any(np.isclose(action.box.maximum[0], 0.5) for action in actions))

    def test_proposals_reject_a_blocker_on_only_the_x_leg_of_the_transport_path(self):
        state = ProxyState(
            spaces=(EMS(Rect(-1.0, 1.0, -1.0, 1.0), 0.0, 0.5, 0, (False, False)),),
            boxes=(AABB.from_center_half((0.0, 0.9, 0.1), (0.1, 0.1, 0.1)),),
            placed_ids=(8,),
            entrance_ranges=((0, -0.9, -0.7),),
            door_planes=((0, -1.0),),
            resting_surfaces=((0, (0.0,)),),
            ceiling_surfaces=((0, (1.0,)),),
        )
        item = ItemSpec(index=5, length=0.2, width=0.2, height=0.2)
        actions = propose_actions(state, item, 0, limit=80, deadline=time.perf_counter() + 1.0)
        self.assertFalse(any(np.isclose(action.box.center[0], 0.9) and np.isclose(action.box.center[1], 0.9)
                             for action in actions))

    def test_apply_action_is_immutable_and_state_key_is_quantized_and_deterministic(self):
        state = ProxyState(
            spaces=(EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False)),),
            boxes=(), placed_ids=(),
        )
        action = propose_actions(state, _item(), 3, limit=1, deadline=time.perf_counter() + 1.0)[0]
        successor = apply_action(state, action, clearance=0.008)

        self.assertIsNotNone(successor)
        self.assertEqual(state.placed_ids, ())
        self.assertEqual(successor.placed_ids, (1,))
        jittered = ProxyState(
            spaces=tuple(
                EMS(Rect(space.rect.min_x + 0.0001, space.rect.max_x + 0.0001,
                         space.rect.min_y, space.rect.max_y), space.bottom_z, space.max_height,
                    space.container_index, space.protection)
                for space in successor.spaces
            ), boxes=successor.boxes, placed_ids=successor.placed_ids,
            clearance=successor.clearance,
            entrance_ranges=successor.entrance_ranges,
            door_planes=successor.door_planes,
            resting_surfaces=successor.resting_surfaces,
            ceiling_surfaces=successor.ceiling_surfaces,
            box_containers=successor.box_containers,
        )
        self.assertEqual(state_key(successor, (5, 6)), state_key(jittered, (5, 6)))

    def test_successor_top_support_has_no_clearance_induced_vertical_gap(self):
        state = ProxyState(
            spaces=(EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False)),),
            boxes=(), placed_ids=(), clearance=0.018,
            door_planes=((0, -0.75),), entrance_ranges=((0, -0.5, 0.5),),
            resting_surfaces=((0, (0.0,)),), ceiling_surfaces=((0, (1.0,)),),
        )
        first = propose_actions(state, ItemSpec(index=34, length=0.2, width=0.2, height=0.2), 0,
                                limit=1, deadline=time.perf_counter() + 1.0)[0]
        successor = apply_action(state, first, clearance=0.018)
        self.assertIsNotNone(successor)
        self.assertTrue(any(abs(space.bottom_z - first.box.maximum[2]) < 1e-9
                            for space in successor.spaces))
        stacked = propose_actions(successor, ItemSpec(index=35, length=0.2, width=0.2, height=0.2), 0,
                                  limit=30, deadline=time.perf_counter() + 1.0)
        self.assertTrue(any(abs(action.box.minimum[2] - first.box.maximum[2]) < 1e-9 for action in stacked))

    def test_apply_action_uses_stronger_argument_clearance_for_container_walls(self):
        support = EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False))
        state = ProxyState(
            spaces=(support,), boxes=(), placed_ids=(), clearance=0.0,
            container_bounds=((0, Rect(-0.5, 0.5, -0.5, 0.5)),),
        )
        item = ItemSpec(index=36, length=0.2, width=0.2, height=0.2)
        action = ProxyAction(
            item=item, pool_index=0, container_index=0, orientation=0,
            box=AABB.from_center_half((-0.4, 0.0, 0.1), (0.1, 0.1, 0.1)),
            support_key=(0, 0),
        )

        self.assertIsNotNone(apply_action(state, action, clearance=0.0))
        self.assertIsNone(apply_action(state, action, clearance=0.018))

    def test_proxy_boxes_do_not_alias_source_or_action_arrays(self):
        packing = build_packing_state([_container_dict()])
        source = AABB.from_center_half((0.5, 0.1, 0.2), (0.1, 0.1, 0.1))
        packing.containers[0].placed.append(PlacedItem(_item(20), source))
        proxy = build_proxy_state(packing, clearance=0.008)
        before_source_mutation = state_key(proxy, ())
        source.minimum[0] = -99.0
        self.assertEqual(state_key(proxy, ()), before_source_mutation)

        state = ProxyState(
            spaces=(EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False)),),
            boxes=(), placed_ids=(),
        )
        action = propose_actions(state, _item(), 0, limit=1, deadline=time.perf_counter() + 1.0)[0]
        successor = apply_action(state, action, clearance=0.0)
        before_action_mutation = state_key(successor, ())
        action.box.minimum[0] = -99.0
        self.assertEqual(state_key(successor, ()), before_action_mutation)

    def test_state_key_distinguishes_clearance_and_transport_metadata(self):
        space = EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.0, 1.0, 0, (False, False))
        base = ProxyState(
            spaces=(space,), boxes=(), placed_ids=(), clearance=0.008,
            door_planes=((0, -0.75),), entrance_ranges=((0, -0.5, 0.5),),
            resting_surfaces=((0, (0.04, 0.84)),), ceiling_surfaces=((0, (0.8, 1.56)),),
        )
        changed_clearance = ProxyState(
            spaces=(space,), boxes=(), placed_ids=(), clearance=0.018,
            door_planes=base.door_planes, entrance_ranges=base.entrance_ranges,
            resting_surfaces=base.resting_surfaces, ceiling_surfaces=base.ceiling_surfaces,
        )
        changed_entry = ProxyState(
            spaces=(space,), boxes=(), placed_ids=(), clearance=base.clearance,
            door_planes=base.door_planes, entrance_ranges=((0, -0.4, 0.5),),
            resting_surfaces=base.resting_surfaces, ceiling_surfaces=base.ceiling_surfaces,
        )
        self.assertNotEqual(state_key(base, ()), state_key(changed_clearance, ()))
        self.assertNotEqual(state_key(base, ()), state_key(changed_entry, ()))

    def test_state_key_distinguishes_support_parameters(self):
        space = EMS(Rect(-0.5, 0.5, -0.5, 0.5), 0.048, 1.0, 0, (False, False))
        base = ProxyState(spaces=(space,), boxes=(), placed_ids=(), support_inset=0.008, shelf_drop_gap=0.022)
        changed_inset = ProxyState(spaces=(space,), boxes=(), placed_ids=(), support_inset=0.018, shelf_drop_gap=0.022)
        changed_shelf_gap = ProxyState(spaces=(space,), boxes=(), placed_ids=(), support_inset=0.008, shelf_drop_gap=0.030)
        self.assertNotEqual(state_key(base, ()), state_key(changed_inset, ()))
        self.assertNotEqual(state_key(base, ()), state_key(changed_shelf_gap, ()))


if __name__ == "__main__":
    unittest.main()
