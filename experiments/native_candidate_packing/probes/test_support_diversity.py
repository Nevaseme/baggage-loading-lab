"""A different physical supporter gets a full trial after a tower fails."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

root=Path(__file__).resolve().parents[1]
source=root/'variants/support_diverse_preview'
spec=importlib.util.spec_from_file_location('support_diversity_test',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from support_diversity_test.agent import Agent


class SupportDiversityRegression(unittest.TestCase):
    def test_known_failed_support_does_not_consume_all_preview_budget(self):
        obs=json.loads((root/'results/basin-preview-b-task001-seed42.snapshot.json').read_text())
        agent=Agent(str(source))
        agent.use_settling_preview=True
        action=agent.policy(obs)
        self.assertLess(agent.last_diagnostics['elapsed'],5.2)
        trials=agent.last_diagnostics['previews']
        self.assertFalse(trials[0]['safe'])
        self.assertTrue(trials[-1]['safe'])
        self.assertEqual(trials[-1]['steps'],300)
        self.assertNotEqual(trials[0]['support_items'],trials[-1]['support_items'])
        native=agent._native[action['container_idx']].check(obs['pool_list'][action['item_idx']],action)
        self.assertTrue(all(native[k] for k in ('included','target_clear','transport')))
        for validator in agent._native.values(): validator.close()
        agent._preview.close()


if __name__=='__main__': unittest.main()
