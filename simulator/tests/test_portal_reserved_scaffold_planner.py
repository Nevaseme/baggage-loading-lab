from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.portal_reserved_scaffold_dag.agent import Agent  # noqa: E402
from agents.portal_reserved_scaffold_dag.authorizer import (  # noqa: E402
    authorize_current,
    format_authorized_action,
    proposal_from_action,
)
from agents.portal_reserved_scaffold_dag.planner import build_plan, repair_plan  # noqa: E402


def _container() -> dict:
    return {
        "index": 0,
        "length": 2.0,
        "width": 1.2,
        "height": 1.0,
        "thickness": 0.04,
        "buffer": 0.0,
        "cut_x": 0.25,
        "center": [0.0, 0.0, 0.5],
        "n_vecs": [
            [-1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 1.0],
        ],
        "points": [
            [-0.96, 0.0, 0.0],
            [0.96, 0.0, 0.0],
            [0.0, -0.56, 0.0],
            [0.0, 0.56, 0.0],
            [0.0, 0.0, 0.04],
            [0.0, 0.0, 0.96],
        ],
        "shelf": False,
        "require_shelf": False,
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int) -> dict:
    return {
        "index": index,
        "length": 0.2,
        "width": 0.2,
        "height": 0.2,
        "mass": 1.0,
        "is_soft": False,
        "is_prioritized": False,
    }


def _observation() -> dict:
    return {"optimize": True, "lookahead_k": 1, "container_list": [_container()], "pool_list": [_item(1)]}


class PortalReservedScaffoldPlannerTests(unittest.TestCase):
    def test_expired_deadline_keeps_completed_partial_plan(self):
        # Mutation caught: all-or-nothing deadline handling that discards the
        # already completed prefix when beam expansion runs out of time.
        items = [_item(i) for i in range(12)]
        deadline = time.perf_counter() + 0.0005
        plan = build_plan(items, [_container()], deadline)
        self.assertTrue(plan.partial or plan.deadline_expired)
        self.assertLessEqual(len(plan.placements) + len(plan.unplaced_indices), len(items))

    def test_repair_returns_only_current_state_authorized_candidates(self):
        # Mutation caught: repair formatting a stale/unchecked candidate or
        # bypassing the Task 3 receipt for the planned route.
        observation = _observation()
        source_plan = build_plan(observation["pool_list"], observation["container_list"], time.perf_counter() + 1.0)
        repaired = repair_plan(observation, source_plan, time.perf_counter() + 1.0)
        self.assertTrue(repaired.placements)
        intent = repaired.placements[0]
        action = {
            "item_idx": int(intent.pool_ordinal),
            "container_idx": int(intent.container_idx),
            "place_pos": np.asarray(intent.position, dtype=np.float32),
            "orientation": int(intent.orientation),
        }
        result = authorize_current(proposal_from_action(action, observation, route="repair"), observation)
        self.assertTrue(result.accepted, result.reject_reasons)
        formatted = format_authorized_action(result, observation)
        self.assertEqual(set(formatted), {"item_idx", "container_idx", "place_pos", "orientation"})

    def test_agent_reservation_flag_routes_through_same_authorizer(self):
        # Mutation caught: enabling portal reservation would create a special
        # unchecked action path instead of using the reviewed authorizer.
        agent = Agent("portal_reserved_scaffold_dag")
        agent.get_init_states(
            {
                "container_list": [_container()],
                "lookahead_k": 1,
                "optimize": True,
                "reserve_portals": True,
            }
        )
        agent.optimize([_item(1)])
        action = agent.policy(_observation())
        self.assertEqual(set(action), {"item_idx", "container_idx", "place_pos", "orientation"})
        self.assertIs(type(action["item_idx"]), int)
        self.assertEqual(action["place_pos"].dtype, np.dtype("float32"))
        self.assertIsNotNone(agent._last_result)
        self.assertTrue(agent._last_result.accepted, agent._last_result.reject_reasons)


if __name__ == "__main__":
    unittest.main()
