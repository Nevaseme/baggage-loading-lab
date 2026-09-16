"""Controlled release is a validated fallback and preserves early choices."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import numpy as np

root=Path(__file__).resolve().parent
native_root=root.parent/'native_candidate_packing'


def load(name,directory):
    spec=importlib.util.spec_from_file_location(name,directory/'__init__.py',submodule_search_locations=[str(directory)])
    package=importlib.util.module_from_spec(spec)
    sys.modules[name]=package
    spec.loader.exec_module(package)
    return __import__(name+'.agent',fromlist=['Agent'])


control=load('controlled_drop_control',native_root/'variants/progressive_recovery')
treatment=load('controlled_drop_treatment',root/'source')


def close(agent):
    for validator in agent._native.values(): validator.close()
    if agent._preview is not None: agent._preview.close()


class ControlledDropPolicyTests(unittest.TestCase):
    def test_progressive22_gets_a_complete_validated_drop_under_budget(self):
        obs=json.loads((native_root/'results/progressive-b-task001-seed42.snapshot.json').read_text())
        agent=treatment.Agent(str(root/'source'))
        action=agent.policy(obs)
        self.assertEqual(agent.last_diagnostics['selected_stage'],'raised')
        self.assertGreater(agent.last_diagnostics['selected_drop'],0.)
        self.assertLess(agent.last_diagnostics['elapsed'],5.2)
        trial=agent.last_diagnostics['previews'][-1]
        self.assertTrue(trial['safe'])
        self.assertEqual(trial['steps'],300)
        self.assertEqual(trial['lost_volume'],0.)
        native=agent._native[action['container_idx']].check(obs['pool_list'][action['item_idx']],action)
        self.assertTrue(all(native[key] for key in ('included','target_clear','transport')))
        landing=agent._release_landings[agent._action_key(action)]
        self.assertFalse(agent._native_outcomes[agent._action_key(landing)]['transport'])
        close(agent)

    def test_three_safe_early_choices_remain_unchanged(self):
        result=json.loads((native_root/'results/native-b-task001-seed42.json').read_text())
        obs=json.loads((native_root/'results/native-b-task001-seed42.snapshot.json').read_text())
        for container in obs['container_list']: container['packed_items']=[]
        pending=copy.deepcopy(result['config']['item_stream']['item_list'])
        obs['pool_list'],pending=pending[:10],pending[10:]
        baseline=control.Agent(str(native_root/'variants/progressive_recovery'))
        candidate=treatment.Agent(str(root/'source'))
        for _ in range(3):
            expected=baseline.policy(obs)
            actual=candidate.policy(obs)
            for key in ('item_idx','container_idx','orientation'):
                self.assertEqual(actual[key],expected[key])
            np.testing.assert_array_equal(actual['place_pos'],expected['place_pos'])
            self.assertEqual(candidate.last_diagnostics.get('selected_drop',0.),0.)
            cargo=obs['pool_list'].pop(actual['item_idx'])
            control.h._virtual_add_item(obs['container_list'][actual['container_idx']],cargo,actual)
            if pending: obs['pool_list'].append(pending.pop(0))
        close(baseline)
        close(candidate)


if __name__=='__main__': unittest.main()
