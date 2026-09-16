"""The official environment must retain packing on explicit search exhaustion."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'simulator'))
from src.ground_handling.env import GroundHandlingEnv


class TerminalProtocolTests(unittest.TestCase):
    def test_rejection_preserves_partial_score_without_spawning(self):
        spec=importlib.util.spec_from_file_location('terminal_under_test',Path(__file__).with_name('terminal.py'))
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        record=json.loads((ROOT/'experiments/fair_candidate_packing/results/baseline-b-task001-seed42.json').read_text())
        env=GroundHandlingEnv(record['config'],verbose=False)
        try:
            env.reset_settings(); env.reset_item_stream()
            obs,_=env.reset(seed=42)
            action=record['records'][0]['action'].copy()
            action['place_pos']=np.asarray(action['place_pos'],dtype=np.float32)
            obs,_,done,_,info=env.step(action)
            self.assertFalse(done)
            self.assertTrue(info['status']['is_placed_safe'])
            before=env.evaluate()
            terminal,proof=module.terminal_rejection(obs)
            self.assertFalse(proof['included'])
            valid,_,_=env.validator.check_action(terminal,env.config['action'],len(obs['container_list']),len(obs['pool_list']))
            self.assertTrue(valid)
            _,_,done,truncated,info=env.step(terminal)
            self.assertTrue(done)
            self.assertFalse(truncated)
            self.assertFalse(info['status']['is_included'])
            self.assertEqual(before,env.evaluate())
        finally: env.close()


if __name__=='__main__': unittest.main()
