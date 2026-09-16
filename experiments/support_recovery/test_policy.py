"""Saved-state regression for bounded support recovery."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).parent / 'source'


class RecoveryTests(unittest.TestCase):
    def test_native_valid_full_preview_after_strict_exhaustion(self):
        spec = importlib.util.spec_from_file_location('support_recovery_test', SOURCE/'__init__.py',
                                                       submodule_search_locations=[str(SOURCE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        Agent = __import__('support_recovery_test.agent', fromlist=['Agent']).Agent
        observation = json.loads((ROOT/'experiments/native_candidate_packing/results/'
                                  'progressive-historical-queries384-c-task001-shuffle17.snapshot.json').read_text())
        agent = Agent(str(SOURCE))
        agent._historical_prefix_active = False
        try:
            action = agent.policy(observation)
            self.assertEqual(agent.last_diagnostics['recovery_stage'], 'relaxed_support')
            self.assertTrue(agent.last_diagnostics['previews'][-1]['safe'])
            self.assertEqual(agent.last_diagnostics['previews'][-1]['steps'], 300)
            self.assertLess(agent.last_diagnostics['total_elapsed'], agent.total_policy_seconds)
            check = agent._native[action['container_idx']].check(observation['pool_list'][action['item_idx']],action)
            self.assertTrue(all(check[k] for k in ('included','target_clear','transport')))
            self.assertFalse(agent._relaxed_support)
            self.assertEqual(agent.shortlist_limit,96)
        finally:
            for validator in agent._native.values(): validator.close()
            if agent._preview is not None: agent._preview.close()


if __name__ == '__main__': unittest.main()
