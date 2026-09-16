import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


SOURCE = Path(__file__).resolve().parents[1] / 'source'
SPEC = importlib.util.spec_from_file_location(
    'offline_settling_test_package', SOURCE / '__init__.py',
    submodule_search_locations=[str(SOURCE)],
)
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)

from offline_settling_test_package.agent import Agent, NoValidAction  # noqa: E402
from offline_settling_test_package.preview import SettlingPreview  # noqa: E402


def container_fixture(*, packed_items=None):
    return {
        'index': 0, 'length': 2., 'width': 1.45, 'height': 1.61,
        'thickness': .04, 'buffer': 0., 'cut_x': .44,
        'center': [3., 0., .805], 'shelf': False,
        'packed_items': list(packed_items or []),
        'n_vecs': [[-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0],
                   [0, 0, -1], [0, 0, 1]],
        'points': [[2.04, 0, 0], [3.96, 0, 0], [3., -.685, 0],
                   [3., .685, 0], [3., 0, .04], [3., 0, 1.57]],
    }


def item_fixture(index=0):
    return {
        'index': index, 'length': .2, 'width': .2, 'height': .2,
        'mass': 1., 'is_soft': False, 'is_prioritized': False,
        'lateralFriction': .8, 'rollingFriction': .01,
        'spinningFriction': .01, 'restitution': 0., 'angularDamping': .8,
        'contactStiffness': 5000., 'contactDamping': 500.,
        'linearDamping': .8,
    }


class OfflineSettlingPlanTests(unittest.TestCase):
    def test_preview_can_return_all_settled_existing_poses(self):
        packed = dict(item_fixture(9), pos=[2.5, 0., .14], orn=[0., 0., 0., 1.])
        action = {
            'item_idx': 0, 'container_idx': 0,
            'place_pos': np.asarray([.35, 0., .15], dtype=np.float32),
            'orientation': 0,
        }
        with SettlingPreview() as preview:
            result = preview.evaluate(
                container_fixture(packed_items=[packed]), item_fixture(), action,
                steps=30, capture_final_state=True,
            )
        self.assertIn('final_packed_items', result)
        self.assertEqual([p['index'] for p in result['final_packed_items']], [9])
        self.assertEqual(len(result['final_packed_items'][0]['pos']), 3)
        self.assertEqual(len(result['final_packed_items'][0]['orn']), 4)

    def test_virtual_state_uses_settled_pose_for_existing_and_new_items(self):
        old = dict(item_fixture(9), pos=[2.5, 0., .14], orn=[0., 0., 0., 1.])
        container = container_fixture(packed_items=[old])
        item = item_fixture(4)
        action = {
            'item_idx': 0, 'container_idx': 0,
            'place_pos': np.asarray([.2, 0., .15], dtype=np.float32),
            'orientation': 0,
        }
        result = {
            'final_position': [3.2, .01, .149],
            'final_orientation': [.1, .2, .3, .9],
            'final_packed_items': [{
                'index': 9, 'pos': [2.51, .02, .141],
                'orn': [.01, .02, .03, .999],
            }],
        }
        Agent._apply_settled_state(container, item, action, result)
        self.assertEqual(container['packed_items'][0]['pos'], [2.51, .02, .141])
        self.assertEqual(container['packed_items'][0]['orn'], [.01, .02, .03, .999])
        self.assertEqual(container['packed_items'][1]['pos'], [3.2, .01, .149])
        self.assertEqual(container['packed_items'][1]['orn'], [.1, .2, .3, .9])

    def test_duplicate_profiles_are_represented_once(self):
        first, second = item_fixture(0), item_fixture(1)
        self.assertEqual(len(Agent._representatives([first, second])), 1)
        second['mass'] = 1.1
        self.assertEqual(len(Agent._representatives([first, second])), 2)

    def test_virtual_optimizer_returns_complete_order_and_pose_plan(self):
        class StubAgent(Agent):
            def _search_policy(self, observation):
                self._last_preview_result = {
                    'safe': True,
                    'final_position': [3.2, 0., .15],
                    'final_orientation': [0., 0., 0., 1.],
                    'final_packed_items': [],
                }
                return {
                    'item_idx': 0, 'container_idx': 0,
                    'place_pos': np.asarray([.2, 0., .15], dtype=np.float32),
                    'orientation': 0,
                }

        agent = StubAgent(str(SOURCE))
        agent.get_init_states({
            'optimize': True, 'lookahead_k': 1,
            'container_list': [container_fixture()],
        })
        agent.offline_budget_seconds = .2
        order = agent.optimize([item_fixture(0), item_fixture(1)])
        self.assertEqual(order, [0, 1])
        self.assertEqual(set(agent.offline_plan), {0, 1})
        self.assertEqual(agent.last_plan_stats['remaining_count'], 0)

    def test_policy_wrapper_has_a_recovery_result_after_search_miss(self):
        # The public wrapper only handles the typed planner miss.  Keep this
        # regression focused on that contract rather than hiding arbitrary
        # implementation errors.
        class TypedRecoveryAgent(Agent):
            def _search_policy(self, observation):
                raise NoValidAction('synthetic search miss')

            def _recover_action(self, observation):
                return {
                    'item_idx': 0, 'container_idx': 0,
                    'place_pos': np.asarray([0., 0., .15], dtype=np.float32),
                    'orientation': 0,
                }

        agent = TypedRecoveryAgent(str(SOURCE))
        action = agent.policy({
            'optimize': False, 'lookahead_k': 1,
            'pool_list': [item_fixture()],
            'container_list': [container_fixture()],
        })
        self.assertEqual(action['item_idx'], 0)
        self.assertEqual(action['container_idx'], 0)
        self.assertEqual(action['orientation'], 0)

    def test_all_rejected_recovery_does_not_return_unchecked_action(self):
        class RejectingAgent(Agent):
            def _authorize(self, action, observation, route):
                return None

        agent = RejectingAgent(str(SOURCE))
        observation = {
            'optimize': False, 'lookahead_k': 1,
            'pool_list': [item_fixture()],
            'container_list': [container_fixture()],
        }
        with self.assertRaises(NoValidAction):
            agent._recover_action(observation)


if __name__ == '__main__':
    unittest.main()
