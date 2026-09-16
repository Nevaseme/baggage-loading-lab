import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('motion_test_source',ROOT/'source/__init__.py',submodule_search_locations=[str(ROOT/'source')])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from motion_test_source.motion import MotionStatePreview

class MotionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.preview=object.__new__(MotionStatePreview)
        self.preview.residual_gain=0.
        self.preview._frame=None
        self.preview.last_estimates={}
        self.state=dict(pos=[0.,0.,1.],orn=[0.,0.,0.,1.],linear=[.2,0.,-.1],angular=[0.,.3,0.])
        self.container=dict(index=0,packed_items=[dict(index=7,pos=[.04,0.,.9],orn=[0.,0.,0.,1.])])
        self.result=dict(steps=300,deadline_exceeded=False,_motion_frame=dict(container_index=0,states={7:self.state}))

    def test_only_committed_preview_influences_next_observation(self):
        self.assertEqual(self.preview._estimate(self.container),{})
        self.preview.accept(self.result)
        self.result['_motion_frame']['states'][7]['linear'][0]=99.
        self.assertEqual(self.preview._estimate(self.container)[7][0],[.2,0.,-.1])

    def test_partial_preview_cannot_be_committed(self):
        self.result['steps']=275
        with self.assertRaises(ValueError): self.preview.accept(self.result)
        self.assertIsNone(self.preview._frame)

    def test_new_episode_or_unexpected_item_set_drops_stale_velocity(self):
        self.preview.accept(self.result)
        self.container['packed_items']=[]
        self.assertEqual(self.preview._estimate(self.container),{})
        self.preview.reset()
        self.assertIsNone(self.preview._frame)

    def test_observation_only_saved_prediction_rejects_drop(self):
        evidence=json.loads((ROOT/'sequential-carry.json').read_text())
        previous=evidence['trials'][21]['preview']
        frame=previous['_motion_frame']
        frame['states']={int(key):value for key,value in frame['states'].items()}
        snapshot=json.loads((ROOT.parent/'native_candidate_packing/results/progressive-b-task001-seed42.snapshot.json').read_text())
        action=evidence['trials'][22]['action']
        with MotionStatePreview() as preview:
            preview.accept(previous)
            outcome=preview.evaluate(snapshot['container_list'][0],snapshot['pool_list'][action['item_idx']],action)
        self.assertEqual(outcome['steps'],300)
        self.assertFalse(outcome['safe'])
        self.assertEqual(outcome['inferred_velocity_count'],22)
        self.assertAlmostEqual(outcome['displacement'],.3214073768063727,places=5)
        self.assertLess(outcome['seconds'],8.)

if __name__=='__main__': unittest.main()
