"""Ensure the smoke check cannot confuse successful execution with completed packing."""
import copy
import unittest
from tools.cloud_smoke import tiny_tasks, validate_results


class CloudSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tasks = {key: {'agent': {'optimize': optimize, 'policy_timeout': 8,
                                    'optimization_timeout': 180},
                            'item_stream': {'item_list': [1, 2, 3], 'visible_pool': [9]},
                            'visualizer': {'vis': True}}
                      for key, optimize in [('000', True), ('001', False)]}
        self.results = {key: {'status': 'success', 'evaluation': {'num_placed_items': 1.0},
                              'place_states': dict(is_included=True, is_valid=True, is_placed_safe=True),
                              'time_results': {'policy': 1., 'optimization': 2.}}
                        for key in self.tasks}

    def test_tiny_tasks_preserve_original_and_modes(self):
        original = copy.deepcopy(self.tasks)
        tasks, modes = tiny_tasks(self.tasks)
        self.assertEqual(self.tasks, original)
        self.assertEqual(modes, {'000': 'A', '001': 'B'})
        self.assertEqual(tasks['001']['item_stream']['item_list'], [1, 2])
        self.assertEqual(tasks['001']['item_stream']['visible_pool'], [])

    def test_completed_tasks_pass(self):
        validate_results(self.results, self.tasks)

    def test_partial_or_missing_task_fails(self):
        for variant in ('partial', 'missing', 'invalid'):
            with self.subTest(variant=variant):
                rows = copy.deepcopy(self.results)
                if variant == 'partial':
                    rows['001']['evaluation']['num_placed_items'] = .5
                elif variant == 'missing':
                    del rows['001']
                else:
                    rows['001']['place_states']['is_valid'] = False
                with self.assertRaises(RuntimeError):
                    validate_results(rows, self.tasks)

    def test_timeout_or_nonfinite_timing_fails(self):
        for value in (9., float('nan')):
            rows = copy.deepcopy(self.results)
            rows['000']['time_results']['policy'] = value
            with self.assertRaises(RuntimeError):
                validate_results(rows, self.tasks)
