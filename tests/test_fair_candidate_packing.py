"""Regression coverage for fair search and validated exhaustion."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / "experiments/fair_candidate_packing/source"
spec = importlib.util.spec_from_file_location("fair_candidate_test_package", SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from fair_candidate_test_package.agent import Agent, NoValidAction


def item(index=0, size=0.3, pos=None):
    result = dict(index=index, length=size, width=size, height=size, mass=4.0,
                  is_soft=False, is_prioritized=False)
    if pos is not None:
        result.update(pos=pos, orn=[0., 0., 0., 1.])
    return result


def container(index, full=False):
    offset = index * 3.0
    result = dict(index=index, length=2., width=2., height=2., thickness=.04,
                  buffer=.01, cut_x=.3, cut_y=.3, center=[offset, 0., 1.01],
                  is_prioritized=False, require_shelf=False, shelf=False,
                  packed_items=[])
    result['n_vecs'] = [[-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]]
    result['points'] = [[offset-.96,0,0],[offset+.96,0,0],[offset,-.96,0],
                        [offset,.96,0],[offset,0,.05],[offset,0,1.97]]
    if full:
        result['packed_items'] = [item(99, 1.9, [offset, 0., 1.])]
    return result


def observation(containers):
    return dict(optimize=False, lookahead_k=1, pool_list=[item()], container_list=containers)


class FairCandidatePackingTests(unittest.TestCase):
    def test_settling_preview_accepts_stable_floor_and_deadline_fails_closed(self):
        from fair_candidate_test_package.preview import SettlingPreview
        action = dict(item_idx=0, container_idx=0, orientation=0, place_pos=np.asarray([0., .3, .208], dtype=np.float32))
        with SettlingPreview() as preview:
            result = preview.evaluate(container(0), item(), action)
            expired = preview.evaluate(container(0), item(), action, deadline=0.)
        self.assertTrue(result['safe'], result)
        self.assertEqual(result['steps'], 300)
        self.assertFalse(expired['safe'])
        self.assertTrue(expired['deadline_exceeded'])

    def test_settling_preview_rejects_known_physical_failure(self):
        snapshot = SOURCE.parent / 'results/aligned-b-task001-seed42.snapshot.json'
        result_file = SOURCE.parent / 'results/aligned-b-task001-seed42.json'
        if not snapshot.exists() or not result_file.exists():
            self.skipTest('Physical experiment snapshot is not available')
        obs = json.loads(snapshot.read_text())
        action = json.loads(result_file.read_text())['records'][-1]['action']
        from fair_candidate_test_package.preview import SettlingPreview
        with SettlingPreview() as preview:
            result = preview.evaluate(obs['container_list'][action['container_idx']],
                                      obs['pool_list'][action['item_idx']], action)
        print(json.dumps(dict(failed_snapshot_prediction=result)))
        self.assertFalse(result['safe'])

    def test_failed_physics_snapshot_recovers_a_valid_candidate(self):
        snapshot = SOURCE.parent / 'results/fair-b-task001-seed42.snapshot.json'
        if not snapshot.exists():
            self.skipTest('Physical experiment snapshot is not available')
        obs = json.loads(snapshot.read_text())
        control = Agent(str(SOURCE))
        control.use_support_candidates = False
        with self.assertRaises(NoValidAction):
            control.policy(obs)
        agent = Agent(str(SOURCE))
        action = agent.policy(obs)
        from fair_candidate_test_package.authorizer import authorize_current, proposal_from_action
        checked = authorize_current(proposal_from_action(action, obs, route='snapshot', source_key='snapshot'), obs)
        self.assertTrue(checked.accepted, checked.reject_reasons)
        self.assertLess(agent.last_diagnostics['elapsed'], 6.)
        print(json.dumps(dict(snapshot=str(snapshot.name), control=control.last_diagnostics,
                              treatment=agent.last_diagnostics,
                              action={key: value.tolist() if hasattr(value, 'tolist') else value
                                      for key, value in action.items()},
                              support_ratio=checked.settling_evidence['support_ratio'],
                              transport_clearance=checked.hard_evidence['transport_min_clearance'])))

    def test_later_container_is_searched_before_first_consumes_budget(self):
        agent = Agent(str(SOURCE))
        agent.max_candidate_checks = 6
        action = agent.policy(observation([container(0, True), container(1)]))
        self.assertEqual(action['container_idx'], 1)
        self.assertEqual(action['place_pos'].dtype, np.float32)
        self.assertGreaterEqual(agent.last_diagnostics['combinations_visited'], 2)

    def test_exhaustion_never_returns_unchecked_fallback(self):
        agent = Agent(str(SOURCE))
        agent.max_candidate_checks = 30
        with self.assertRaises(NoValidAction):
            agent.policy(observation([container(0, True)]))

    def test_returned_action_has_current_state_authorization(self):
        agent = Agent(str(SOURCE))
        obs = observation([container(0)])
        action = agent.policy(obs)
        from fair_candidate_test_package.authorizer import authorize_current, proposal_from_action
        result = authorize_current(proposal_from_action(action, obs, route='test', source_key='test'), obs)
        self.assertTrue(result.accepted, result.reject_reasons)

    def test_initialize_and_optimize_keep_historical_interface(self):
        agent = Agent(str(SOURCE))
        self.assertTrue(agent.get_init_states(dict(optimize=True, lookahead_k=1, container_list=[])))
        cargo = [item(7), item(3)]
        self.assertEqual(sorted(agent.optimize(cargo)), [3, 7])


if __name__ == '__main__':
    unittest.main()
