import importlib.util
import unittest
from pathlib import Path


class BenchmarkContractTests(unittest.TestCase):
    def test_terminal_rejection_is_distinct_from_placement_failure(self):
        terminal={'is_included':False,'is_valid':False,'is_placed_safe':False}
        self.assertEqual(self.module.failure_outcome(terminal,{'terminal_rejection':{'included':False}}),'terminal_rejection')
        self.assertEqual(self.module.failure_outcome(terminal,{}),'physical_failure')
        self.assertEqual(self.module.failure_outcome({'is_included':True,'is_placed_safe':False},{'terminal_rejection':{}}),'physical_failure')

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'tools' / 'benchmark.py'
        self.assertTrue(path.is_file(), 'benchmark runner is missing')
        spec = importlib.util.spec_from_file_location('benchmark_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.task = {'agent': {'optimize': True}, 'item_stream': {
            'look_ahead': 1, 'max_space': 1,
            'item_list': [{'index': i} for i in range(8)]},
            'visualizer': {'vis': True}}

    def test_mode_c_changes_both_stream_and_agent_without_mutating_source(self):
        result = self.module.configure_task(self.task, 'C', 5, 42, False)
        self.assertFalse(result['agent']['optimize'])
        self.assertEqual(result['item_stream']['look_ahead'], 1)
        self.assertEqual(len(result['item_stream']['item_list']), 5)
        self.assertEqual(len(self.task['item_stream']['item_list']), 8)
        self.assertTrue(self.task['visualizer']['vis'])

    def test_mode_b_has_at_least_three_visible_items(self):
        result = self.module.configure_task(self.task, 'B', None, 42, False)
        self.assertEqual(result['item_stream']['look_ahead'], 3)
        self.assertFalse(result['agent']['optimize'])

    def test_shuffle_is_reproducible_and_preserves_items(self):
        left = self.module.configure_task(self.task, 'B', None, 42, True)
        right = self.module.configure_task(self.task, 'B', None, 42, True)
        self.assertEqual(left, right)
        self.assertCountEqual(left['item_stream']['item_list'], self.task['item_stream']['item_list'])

    def test_duplicate_optimization_ids_are_rejected(self):
        self.assertFalse(self.module.valid_order([0, 1, 1], [0, 1, 2]))
        self.assertTrue(self.module.valid_order([2, 0, 1], [0, 1, 2]))

    def test_evaluation_and_cleanup_errors_do_not_erase_episode_result(self):
        class BrokenEnvironment:
            def evaluate(self):
                raise RuntimeError('evaluation failed')
            def close(self):
                raise RuntimeError('cleanup failed')
        record = {'outcome': 'completed', 'safe_placements': 8}
        self.module.finish_environment(BrokenEnvironment(), record)
        self.assertEqual(record['safe_placements'], 8)
        self.assertEqual(record['outcome'], 'evaluation_error')
        self.assertIn('close_error', record)

    def test_layout_summary_weights_mass_and_converts_container_offset(self):
        containers = [{'index': 4, 'center': [10, 0, 1], 'packed_items': [
            {'mass': 1, 'pos': [9, 0, 1], 'length': 1, 'width': 1, 'height': 1},
            {'mass': 3, 'pos': [11, 2, 3], 'length': 2, 'width': 1, 'height': 1}]}]
        result = self.module.layout_summary(containers)[0]
        self.assertEqual(result['mass_weighted_cog_world'], [10.5, 1.5, 2.5])
        self.assertEqual(result['mass_weighted_cog_local'], [.5, 1.5, 2.5])
        self.assertEqual(result['raw_packed_volume'], 3)

    def test_empty_layout_has_no_invented_cog(self):
        result = self.module.layout_summary([{'index': 0, 'packed_items': []}])[0]
        self.assertIsNone(result['mass_weighted_cog_world'])


if __name__ == '__main__':
    unittest.main()
