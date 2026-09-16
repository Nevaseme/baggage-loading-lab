"""Regression: known discarded support basins remain usable within 96 queries."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

root=Path(__file__).resolve().parents[1]
source=root/'variants/basin_coverage'
spec=importlib.util.spec_from_file_location('basin_coverage_test',source/'__init__.py',submodule_search_locations=[str(source)])
package=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=package
spec.loader.exec_module(package)
from basin_coverage_test.agent import Agent
from basin_coverage_test.preview import SettlingPreview


class BasinCoverageRegression(unittest.TestCase):
    def check_snapshot(self,name,backfill):
        obs=json.loads((root/'results'/f'{name}.snapshot.json').read_text())
        agent=Agent(str(source))
        agent.backfill_weight=backfill
        action=agent.policy(obs)
        self.assertEqual(agent.max_candidate_checks,6500)
        self.assertEqual(agent.shortlist_limit,96)
        self.assertEqual(agent.max_authorizations,96)
        native=agent._native[action['container_idx']].check(obs['pool_list'][action['item_idx']],action)
        self.assertTrue(all(native[key] for key in ('included','target_clear','transport')),native)
        with SettlingPreview() as preview:
            result=preview.evaluate(obs['container_list'][action['container_idx']],obs['pool_list'][action['item_idx']],action)
        self.assertTrue(result['safe'],result)
        for validator in agent._native.values(): validator.close()

    def test_native_failure_state_keeps_feasible_basin(self):
        self.check_snapshot('native-b-task001-seed42',0.)

    def test_backfill_failure_state_keeps_feasible_basin(self):
        self.check_snapshot('native-backfill8-b-task001-seed42',8.)


if __name__=='__main__': unittest.main()
