"""Use the remaining preview budget on another cargo type after a failed drop."""
import json
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.benchmark import load_agent


class DiverseReleaseTests(unittest.TestCase):
    def test_recovery_with_full_motion_preview_within_policy_budget(self):
        source=Path(__file__).parent/'variants/diverse_release/agent.py'
        Agent=load_agent(source)
        Motion=__import__(Agent.__module__.rsplit('.',1)[0]+'.motion',fromlist=['MotionStatePreview']).MotionStatePreview
        agent=Agent(str(source.parent))
        evidence=json.loads((ROOT/'experiments/motion_state_preview/sequential-carry.json').read_text())
        previous=evidence['trials'][21]['preview']
        previous['_motion_frame']['states']={int(k):v for k,v in previous['_motion_frame']['states'].items()}
        obs=json.loads((ROOT/'experiments/native_candidate_packing/results/progressive-b-task001-seed42.snapshot.json').read_text())
        agent._preview=Motion()
        agent._preview.accept(previous)
        try:
            action=agent.policy(obs)
            self.assertEqual(action['item_idx'],0)
            self.assertEqual(agent.last_diagnostics['selected_stage'],'raised')
            result=agent.last_diagnostics['previews'][-1]
            self.assertEqual(result['steps'],300)
            self.assertTrue(result['safe'])
            self.assertEqual(result['lost_volume'],0.)
            self.assertLess(agent.last_diagnostics['elapsed'],7.2)
            self.assertEqual(len(agent._preview._frame['states']),23)
        finally:
            for validator in agent._native.values(): validator.close()
            agent._preview.close()


if __name__=='__main__': unittest.main()
