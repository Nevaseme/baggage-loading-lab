"""Preserve narrow decisions when safe; widen only after bounded rejection."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import numpy as np

root=Path(__file__).resolve().parents[1]


def load(name,directory):
    spec=importlib.util.spec_from_file_location(name,directory/'__init__.py',submodule_search_locations=[str(directory)])
    package=importlib.util.module_from_spec(spec)
    sys.modules[name]=package
    spec.loader.exec_module(package)
    return __import__(name+'.agent',fromlist=['Agent'])


control=load('progressive_control',root/'source')
treatment=load('progressive_treatment',root/'variants/progressive_recovery')


def close(agent):
    for validator in agent._native.values(): validator.close()
    if agent._preview is not None: agent._preview.close()


class ProgressiveRecoveryTests(unittest.TestCase):
    def test_original_native_failure_is_recovered_with_full_preview(self):
        obs=json.loads((root/'results/native-b-task001-seed42.snapshot.json').read_text())
        agent=treatment.Agent(str(root/'variants/progressive_recovery'))
        action=agent.policy(obs)
        self.assertEqual(agent.last_diagnostics['selected_stage'],'wide')
        self.assertLess(agent.last_diagnostics['elapsed'],5.2)
        self.assertTrue(agent.last_diagnostics['previews'][-1]['safe'])
        self.assertEqual(agent.last_diagnostics['previews'][-1]['steps'],300)
        native=agent._native[action['container_idx']].check(obs['pool_list'][action['item_idx']],action)
        self.assertTrue(all(native[key] for key in ('included','target_clear','transport')))
        close(agent)

    def test_three_safe_narrow_decisions_are_preserved(self):
        result=json.loads((root/'results/native-b-task001-seed42.json').read_text())
        obs=json.loads((root/'results/native-b-task001-seed42.snapshot.json').read_text())
        for container in obs['container_list']: container['packed_items']=[]
        pending=copy.deepcopy(result['config']['item_stream']['item_list'])
        obs['pool_list']=pending[:10]
        pending=pending[10:]
        baseline=control.Agent(str(root/'source'))
        progressive=treatment.Agent(str(root/'variants/progressive_recovery'))
        for _ in range(3):
            expected=baseline.policy(obs)
            actual=progressive.policy(obs)
            for key in ('item_idx','container_idx','orientation'):
                self.assertEqual(actual[key],expected[key])
            np.testing.assert_array_equal(actual['place_pos'],expected['place_pos'])
            self.assertEqual(progressive.last_diagnostics['selected_stage'],'narrow')
            self.assertTrue(progressive.last_diagnostics['previews'][-1]['safe'])
            cargo=obs['pool_list'].pop(actual['item_idx'])
            control.h._virtual_add_item(obs['container_list'][actual['container_idx']],cargo,actual)
            if pending: obs['pool_list'].append(pending.pop(0))
        close(baseline)
        close(progressive)


if __name__=='__main__': unittest.main()
