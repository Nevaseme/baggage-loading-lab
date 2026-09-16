import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

source=Path(__file__).resolve().parent/'source'
spec=importlib.util.spec_from_file_location('native_candidate_test',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from native_candidate_test.agent import Agent,NoValidAction
from native_candidate_test.native import NativeValidator


def fixture(full=False):
    item=dict(index=0,length=.2,width=.2,height=.2,mass=1.,is_soft=False,is_prioritized=False)
    c=dict(index=0,length=2.,width=1.45,height=1.61,thickness=.04,buffer=0.,cut_x=.44,
           center=[3.,0.,.805],shelf=False,packed_items=[],
           n_vecs=[[-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]],
           points=[[2.04,0,0],[3.96,0,0],[3.,-.685,0],[3.,.685,0],[3.,0,.04],[3.,0,1.57]])
    if full:
        c['packed_items']=[dict(item,index=1,length=1.9,width=1.4,height=1.5,pos=[3.,0.,.79],orn=[0.,0.,0.,1.])]
    return dict(optimize=False,lookahead_k=1,pool_list=[item],container_list=[c])


class NativeCandidateTests(unittest.TestCase):
    def test_returned_action_passes_native_current_state_checks(self):
        obs=fixture()
        agent=Agent(str(source))
        action=agent.policy(obs)
        self.assertEqual(action['place_pos'].dtype,np.float32)
        self.assertLess(abs(float(action['place_pos'][0])),1.)
        with NativeValidator(obs['container_list'][0]) as validator:
            result=validator.check(obs['pool_list'][0],action)
        self.assertTrue(all(result[k] for k in ('included','target_clear','transport')),result)
        for validator in agent._native.values(): validator.close()

    def test_full_container_has_no_unchecked_fallback(self):
        agent=Agent(str(source))
        agent.max_candidate_checks=30
        with self.assertRaises(NoValidAction): agent.policy(fixture(True))
        for validator in agent._native.values(): validator.close()

    def test_public_initialization_and_ordering(self):
        agent=Agent(str(source))
        self.assertTrue(agent.get_init_states(dict(optimize=True,lookahead_k=1,container_list=[])))
        self.assertEqual(agent.optimize(fixture()['pool_list']),[0])


if __name__=='__main__': unittest.main()
