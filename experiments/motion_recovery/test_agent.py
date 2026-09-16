"""Selected-only motion commitment and episode reset integration regressions."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock
import numpy as np

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('motion_recovery_test_source',ROOT/'source/__init__.py',submodule_search_locations=[str(ROOT/'source')])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from motion_recovery_test_source.agent import Agent

def close(agent):
    if agent._preview is not None: agent._preview.close()
    for validator in agent._native.values(): validator.close()

class IntegrationTests(unittest.TestCase):
    def test_rejected_preview_never_commits_selected_preview_commits_once(self):
        agent=Agent(str(ROOT/'source'))
        rejected=dict(safe=False,steps=300,lost_volume=0.,deadline_exceeded=False)
        selected=dict(safe=True,steps=300,lost_volume=0.,deadline_exceeded=False,_motion_frame={'selected':True})
        agent._preview=Mock()
        agent._preview.evaluate.side_effect=[rejected,selected]
        validator=Mock()
        validator.check.return_value=dict(included=True,target_clear=True,transport=True,deadline_exceeded=False)
        agent._native={0:validator}
        agent._policy_deadline=time.perf_counter()+8.
        agent._native_outcomes={}
        agent._failed_supports=set()
        agent._release_details={}
        agent._support_items=lambda *_:frozenset()
        agent.last_diagnostics=dict(authorizations=0,rejections={},previews=[])
        observation=dict(container_list=[{}],pool_list=[{}])
        first=dict(item_idx=0,container_idx=0,orientation=0,place_pos=np.asarray([0.,0.,1.],dtype=np.float32))
        second=dict(first,orientation=1)
        self.assertIsNone(agent._authorize(first,observation,'test'))
        agent._preview.accept.assert_not_called()
        accepted=agent._authorize(second,observation,'test')
        self.assertIsNotNone(accepted)
        agent._preview.accept.assert_not_called()
        agent._commit_action(accepted)
        agent._preview.accept.assert_called_once_with(selected)
        self.assertNotIn('_motion_frame',agent.last_diagnostics['previews'][-1])
        with self.assertRaises(RuntimeError): agent._commit_action(first)

    def test_new_episode_clears_motion_and_preserves_c_query_budget(self):
        agent=Agent(str(ROOT/'source'))
        agent._preview=Mock()
        old_validator=Mock()
        agent._native={0:old_validator}
        agent._pending_motion_result={'stale':True}
        self.assertTrue(agent.get_init_states(dict(lookahead_k=1,optimize=False,container_list=[])))
        self.assertTrue(agent.prefer_historical_action)
        self.assertEqual(agent.max_authorizations,384)
        self.assertEqual(agent.policy_seconds,7.2)
        agent._preview.reset.assert_called_once()
        old_validator.close.assert_called_once()
        self.assertIsNone(agent._pending_motion_result)
        self.assertEqual(agent._native,{})
        agent.get_init_states(dict(lookahead_k=10,optimize=False,container_list=[]))
        self.assertFalse(agent.prefer_historical_action)
        agent.get_init_states(dict(lookahead_k=1,optimize=True,container_list=[]))
        self.assertFalse(agent.prefer_historical_action)
        self.assertEqual(agent.max_authorizations,384)

    def test_returned_first_action_is_native_valid_and_commits_complete_frame(self):
        observation=json.loads((ROOT.parent/'native_candidate_packing/results/native-b-task001-seed42.snapshot.json').read_text())
        for container in observation['container_list']: container['packed_items']=[]
        agent=Agent(str(ROOT/'source'))
        agent.get_init_states(observation)
        try:
            action=agent.policy(observation)
            actual=agent._native[action['container_idx']].check(observation['pool_list'][action['item_idx']],action)
            self.assertTrue(all(actual[key] for key in ('included','target_clear','transport')))
            self.assertTrue(agent.last_diagnostics['previews'][-1]['safe'])
            self.assertEqual(agent.last_diagnostics['previews'][-1]['steps'],300)
            self.assertIsNone(agent._pending_motion_result)
            self.assertIn(observation['pool_list'][action['item_idx']]['index'],agent._preview._frame['states'])
            self.assertLess(agent.last_diagnostics['elapsed'],8.)
        finally: close(agent)

if __name__=='__main__': unittest.main()
