import pathlib
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.candidates import CandidateGenerator  # noqa: E402
from agents.highscore.catalog import build_root_catalog  # noqa: E402
from agents.highscore.ems import ProxyAction, build_proxy_state, propose_actions  # noqa: E402
from agents.highscore.geometry import transport_path_clear  # noqa: E402
from agents.highscore.model import AABB, ItemSpec  # noqa: E402
from agents.highscore.settings import SearchSettings  # noqa: E402
from agents.highscore.state import build_packing_state  # noqa: E402


def _container_dict(*, index=0, offset_x=0.0, shelf=False, packed=None, prioritized=False):
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (offset_x, 0.0, height / 2),
        "points": [
            [offset_x + length / 2 - thickness, 0.0, 0.0],
            [offset_x - length / 2 + thickness, 0.0, 0.0],
            [offset_x, width / 2 - thickness, 0.0],
            [offset_x, -width / 2 + thickness, 0.0],
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
        "volume": 4.0,
        "shelf": shelf,
        "is_prioritized": prioritized,
        "packed_items": packed or [],
    }


def _item(index=1, *, length=0.5, width=0.4, height=0.24, prioritized=False, soft=False):
    return ItemSpec(
        index=index,
        length=length,
        width=width,
        height=height,
        is_prioritized=prioritized,
        is_soft=soft,
    )


def _packed_item(index, *, pos, length=0.5, width=0.4, height=0.24, prioritized=False, soft=False):
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "mass": 10.0,
        "is_prioritized": prioritized,
        "is_soft": soft,
        "belongs_to": 0,
        "pos": pos,
        "orn": (0.0, 0.0, 0.0, 1.0),
    }


def _as_proposal(candidate):
    return ProxyAction(
        item=candidate.item,
        pool_index=candidate.pool_index,
        container_index=candidate.container_index,
        orientation=candidate.orientation,
        box=candidate.box,
        support_key=(candidate.container_index, 0),
    )


class ValidateProposalTests(unittest.TestCase):
    def setUp(self):
        self.settings = SearchSettings(extra_margins=(0.0,), front_floor_release_fill=0.0)
        self.generator = CandidateGenerator(self.settings)

    def _assert_matches_existing_validation(self, state, item, predicate):
        generated = self.generator.generate(state, item, pool_index=3)
        original = next(candidate for candidate in generated if predicate(candidate))

        validated = self.generator.validate_proposal(state, _as_proposal(original))

        self.assertIsNotNone(validated)
        self.assertEqual(validated.orientation, original.orientation)
        self.assertEqual(validated.pool_index, original.pool_index)
        self.assertEqual(validated.container_index, original.container_index)
        np.testing.assert_allclose(validated.box.minimum, original.box.minimum)
        np.testing.assert_allclose(validated.box.maximum, original.box.maximum)
        self.assertAlmostEqual(validated.support_ratio, original.support_ratio)
        self.assertEqual(validated.rule_violations, original.rule_violations)
        self.assertAlmostEqual(validated.min_clearance, original.min_clearance)

    def test_validate_proposal_matches_existing_floor_shelf_and_stack_validation(self):
        item = _item()
        floor_state = build_packing_state([_container_dict()])
        self._assert_matches_existing_validation(
            floor_state,
            item,
            lambda candidate: candidate.box.minimum[2] < 0.06,
        )

        shelf_state = build_packing_state([_container_dict(shelf=True)])
        self._assert_matches_existing_validation(
            shelf_state,
            item,
            lambda candidate: candidate.box.minimum[2] > 0.85,
        )

        stack_state = build_packing_state([
            _container_dict(packed=[_packed_item(2, pos=(0.0, 0.35, 0.16))])
        ])
        stack_top = stack_state.containers[0].placed[0].box.maximum[2]
        self._assert_matches_existing_validation(
            stack_state,
            item,
            lambda candidate: abs(candidate.box.minimum[2] - stack_top) < 1e-9,
        )

    def test_validate_proposal_rejects_collision_and_rule_violations(self):
        packed = _packed_item(2, pos=(0.0, 0.35, 0.16), prioritized=True, soft=True)
        state = build_packing_state([_container_dict(packed=[packed])])
        floor_item = _item(3)
        floor_candidate = next(
            candidate
            for candidate in self.generator.generate(state, floor_item, pool_index=0)
            if candidate.box.minimum[2] < 0.06
        )
        collision = ProxyAction(
            item=floor_item,
            pool_index=0,
            container_index=0,
            orientation=floor_candidate.orientation,
            box=AABB.from_center_half(
                state.containers[0].placed[0].box.center,
                floor_candidate.box.half,
            ),
            support_key=(0, 0),
        )
        self.assertIsNone(self.generator.validate_proposal(state, collision))

        protected_top = state.containers[0].placed[0].box.maximum[2]
        rigid = _item(4)
        prohibited_stack = ProxyAction(
            item=rigid,
            pool_index=1,
            container_index=0,
            orientation=0,
            box=AABB.from_center_half((0.0, 0.35, protected_top + rigid.height / 2),
                                      (rigid.length / 2, rigid.width / 2, rigid.height / 2)),
            support_key=(0, 0),
        )
        self.assertIsNone(self.generator.validate_proposal(state, prohibited_stack))

    def test_validate_proposal_rejects_unsupported_swept_path_and_depth_map_proposals(self):
        state = build_packing_state([_container_dict()])
        item = _item(5)
        valid = self.generator.generate(state, item, pool_index=0)[0]
        action = _as_proposal(valid)
        unsupported = ProxyAction(
            item,
            0,
            0,
            valid.orientation,
            AABB.from_center_half(
                (valid.position[0], valid.position[1], valid.position[2] + 0.05),
                valid.box.half,
            ),
            (0, 0),
        )
        self.assertIsNone(self.generator.validate_proposal(state, unsupported))

        centre_floor = next(
            candidate
            for candidate in self.generator.generate(state, item, pool_index=0)
            if candidate.orientation == 0
            and abs(candidate.position[0]) < 1e-9
            and candidate.position[1] > 0.0
            and candidate.box.minimum[2] < 0.06
        )
        path_action = _as_proposal(centre_floor)
        blocker = AABB.from_center_half(
            (
                float(centre_floor.box.maximum[0]) + 0.015 + 0.05,
                -0.2,
                centre_floor.position[2],
            ),
            (0.05, 0.05, float(centre_floor.box.half[2])),
        )
        self.assertTrue(
            transport_path_clear(
                centre_floor.box,
                [blocker],
                door_y=-0.75 + float(centre_floor.box.half[1]),
                start_x=0.0,
                lift=0.0,
                clearance=0.0,
            )
        )
        self.assertFalse(
            transport_path_clear(
                centre_floor.box,
                [blocker],
                door_y=-0.75 + float(centre_floor.box.half[1]),
                start_x=0.0,
                lift=0.0,
                clearance=self.settings.path_clearance,
            )
        )
        path_state = build_packing_state([_container_dict()])
        path_state.containers[0].static_obstacles.append(blocker)
        self.assertIsNone(self.generator.validate_proposal(path_state, path_action))

        state.containers[0].depth_map = np.zeros((64, 64), dtype=np.float32)
        with patch("agents.highscore.candidates.depth_map_path_clear", return_value=False) as depth_check:
            self.assertIsNone(self.generator.validate_proposal(state, action))
        depth_check.assert_called_once()

    def test_validate_proposal_rejects_non_integer_and_out_of_range_orientations(self):
        state = build_packing_state([_container_dict()])
        item = _item(6)
        valid = self.generator.generate(state, item, pool_index=0)[0]

        for invalid_orientation in (-1, 6, "0"):
            with self.subTest(orientation=invalid_orientation):
                invalid = ProxyAction(
                    item=valid.item,
                    pool_index=valid.pool_index,
                    container_index=valid.container_index,
                    orientation=invalid_orientation,
                    box=valid.box,
                    support_key=(0, 0),
                )
                self.assertIsNone(self.generator.validate_proposal(state, invalid))


class RootCatalogTests(unittest.TestCase):
    def setUp(self):
        self.settings = SearchSettings(
            extra_margins=(0.0,),
            front_floor_release_fill=0.0,
            ems_proxy_actions_per_item=12,
            ems_exact_roots_per_item=2,
            ems_root_catalog_limit=3,
            ems_root_budget_seconds=1.0,
        )
        self.state = build_packing_state([_container_dict()])
        self.generator = CandidateGenerator(self.settings)

    def test_catalog_contains_only_exact_validated_successors_for_multiple_items(self):
        pool = (_item(10), _item(11, length=0.45, width=0.35, height=0.20))
        roots = build_root_catalog(
            self.state,
            pool,
            self.generator,
            self.settings,
            deadline=time.perf_counter() + 1.0,
        )

        self.assertTrue(roots)
        self.assertGreaterEqual({root.candidate.pool_index for root in roots}, {0, 1})
        self.assertLessEqual(len(roots), self.settings.ems_root_catalog_limit)
        for root in roots:
            exact = self.generator.validate_proposal(self.state, root.proxy_action)
            self.assertIsNotNone(exact)
            self.assertEqual(root.candidate, exact)
            self.assertIsNotNone(root.next_state)
            self.assertEqual(root.next_state.placed_ids[-1], root.candidate.item.index)

    def test_other_container_blocker_does_not_remove_empty_container_roots(self):
        state = build_packing_state(
            [
                _container_dict(index=0),
                _container_dict(index=1, offset_x=3.0),
            ]
        )
        state.containers[0].static_obstacles.append(
            AABB.from_center_half((0.0, 0.0, 0.80), (0.96, 0.71, 0.76))
        )
        item = _item(30)
        settings = SearchSettings(
            extra_margins=(0.0,),
            front_floor_release_fill=0.0,
            ems_proxy_actions_per_item=24,
            ems_exact_roots_per_item=6,
            ems_root_catalog_limit=12,
            ems_root_budget_seconds=1.0,
        )
        generator = CandidateGenerator(settings)

        roots = build_root_catalog(
            state,
            (item,),
            generator,
            settings,
            deadline=time.perf_counter() + 1.0,
        )

        container_one_roots = [root for root in roots if root.candidate.container_index == 1]
        self.assertTrue(container_one_roots)
        for root in container_one_roots:
            self.assertEqual(root.proxy_action.container_index, 1)
            self.assertEqual(root.next_state.box_containers[-1], 1)

        valid_other_container = container_one_roots[0].proxy_action
        same_local_position_in_blocked_container = ProxyAction(
            item=valid_other_container.item,
            pool_index=valid_other_container.pool_index,
            container_index=0,
            orientation=valid_other_container.orientation,
            box=valid_other_container.box,
            support_key=(0, 0),
        )
        self.assertIsNone(
            generator.validate_proposal(state, same_local_position_in_blocked_container)
        )

    def test_catalog_is_deterministic_and_respects_per_item_exact_limit(self):
        pool = (_item(10), _item(11, length=0.45, width=0.35, height=0.20))
        first = build_root_catalog(
            self.state, pool, self.generator, self.settings, deadline=time.perf_counter() + 1.0
        )
        second = build_root_catalog(
            self.state, pool, self.generator, self.settings, deadline=time.perf_counter() + 1.0
        )

        def key(root):
            return (
                root.candidate.pool_index,
                root.candidate.container_index,
                root.candidate.orientation,
                tuple(round(value, 6) for value in root.candidate.position),
            )

        self.assertEqual([key(root) for root in first], [key(root) for root in second])
        self.assertTrue(
            all(
                sum(root.candidate.pool_index == pool_index for root in first)
                <= self.settings.ems_exact_roots_per_item
                for pool_index in range(len(pool))
            )
        )

    def test_catalog_gives_each_item_a_fair_absolute_proposal_deadline(self):
        pool = (_item(10), _item(11))
        proxy = build_proxy_state(
            self.state,
            self.settings.path_clearance,
            support_inset=-self.settings.inclusion_margin,
            shelf_drop_gap=self.settings.shelf_drop_gap,
        )
        action = propose_actions(
            proxy, pool[0], 0, limit=1, deadline=time.perf_counter() + 1.0
        )[0]
        observed_deadlines = []

        def record_proposals(_proxy, item, pool_index, *, limit, deadline):
            observed_deadlines.append((item.index, pool_index, limit, deadline))
            return [
                ProxyAction(
                    item=item,
                    pool_index=pool_index,
                    container_index=action.container_index,
                    orientation=action.orientation,
                    box=action.box,
                    support_key=action.support_key,
                )
            ]

        with patch("agents.highscore.catalog.propose_actions", side_effect=record_proposals):
            build_root_catalog(
                self.state,
                pool,
                self.generator,
                self.settings,
                deadline=time.perf_counter() + 1.0,
            )

        self.assertEqual([(index, limit) for _, index, limit, _ in observed_deadlines], [(0, 12), (1, 12)])
        self.assertLess(observed_deadlines[0][3], observed_deadlines[1][3])

    def test_catalog_preserves_earlier_roots_when_a_validator_raises_or_deadline_expires(self):
        pool = (_item(10), _item(11))
        proxy = build_proxy_state(
            self.state,
            self.settings.path_clearance,
            support_inset=-self.settings.inclusion_margin,
            shelf_drop_gap=self.settings.shelf_drop_gap,
        )
        actions = propose_actions(proxy, pool[0], 0, limit=12, deadline=time.perf_counter() + 1.0)
        actions = [
            action for action in actions
            if self.generator.validate_proposal(self.state, action) is not None
        ][:2]

        class ThrowingGenerator(CandidateGenerator):
            def __init__(self, settings):
                super().__init__(settings)
                self.calls = 0

            def validate_proposal(self, state, action, *, allow_rule_violations=False):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("synthetic validator failure")
                return super().validate_proposal(
                    state, action, allow_rule_violations=allow_rule_violations
                )

        def fixed_proposals(_proxy, item, pool_index, *, limit, deadline):
            if pool_index:
                return []
            return [
                ProxyAction(item, pool_index, proposal.container_index, proposal.orientation, proposal.box,
                            proposal.support_key)
                for proposal in actions
            ]

        with patch("agents.highscore.catalog.propose_actions", side_effect=fixed_proposals):
            roots = build_root_catalog(
                self.state,
                pool,
                ThrowingGenerator(self.settings),
                self.settings,
                deadline=time.perf_counter() + 1.0,
            )

        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].candidate.pool_index, 0)

    def test_catalog_returns_earlier_validated_root_when_fake_clock_reaches_deadline(self):
        pool = (_item(10),)
        proxy = build_proxy_state(
            self.state,
            self.settings.path_clearance,
            support_inset=-self.settings.inclusion_margin,
            shelf_drop_gap=self.settings.shelf_drop_gap,
        )
        actions = propose_actions(proxy, pool[0], 0, limit=12, deadline=time.perf_counter() + 1.0)
        actions = [
            action for action in actions
            if self.generator.validate_proposal(self.state, action) is not None
        ][:2]

        with (
            patch("agents.highscore.catalog.propose_actions", return_value=actions),
            patch("agents.highscore.catalog.time.perf_counter", side_effect=(0.0, 0.0, 0.0, 1.0)),
        ):
            roots = build_root_catalog(
                self.state,
                pool,
                self.generator,
                self.settings,
                deadline=1.0,
            )

        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].candidate.pool_index, 0)

    def test_item_validation_stops_at_fair_deadline_and_later_item_still_runs(self):
        pool = (_item(20), _item(21))
        proxy = build_proxy_state(
            self.state,
            self.settings.path_clearance,
            support_inset=-self.settings.inclusion_margin,
            shelf_drop_gap=self.settings.shelf_drop_gap,
        )
        proposals_by_pool = {}
        for pool_index, item in enumerate(pool):
            proposals_by_pool[pool_index] = [
                ProxyAction(
                    item=item,
                    pool_index=pool_index,
                    container_index=action.container_index,
                    orientation=action.orientation,
                    box=action.box,
                    support_key=action.support_key,
                )
                for action in propose_actions(
                    proxy, item, pool_index, limit=12, deadline=time.perf_counter() + 1.0
                )
                if self.generator.validate_proposal(self.state, action) is not None
            ][:2]
        self.assertEqual([len(proposals_by_pool[index]) for index in range(2)], [2, 2])

        validated_pool_indices = []

        class TrackingGenerator(CandidateGenerator):
            def validate_proposal(self, state, action, *, allow_rule_violations=False):
                validated_pool_indices.append(action.pool_index)
                return super().validate_proposal(
                    state, action, allow_rule_violations=allow_rule_violations
                )

        with (
            patch(
                "agents.highscore.catalog.propose_actions",
                side_effect=lambda _proxy, _item, pool_index, **_kwargs: (
                    proposals_by_pool[pool_index] if pool_index == 0 else proposals_by_pool[pool_index][:1]
                ),
            ),
            patch(
                "agents.highscore.catalog.time.perf_counter",
                side_effect=(0.0, 0.0, 0.40, 0.60, 0.60, 0.70),
            ),
        ):
            roots = build_root_catalog(
                self.state,
                pool,
                TrackingGenerator(self.settings),
                self.settings,
                deadline=1.0,
            )

        self.assertEqual(validated_pool_indices, [0, 1])
        self.assertEqual({root.candidate.pool_index for root in roots}, {0, 1})


if __name__ == "__main__":
    unittest.main()
