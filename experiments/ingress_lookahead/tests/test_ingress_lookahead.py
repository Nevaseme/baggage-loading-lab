import importlib.util
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np


SOURCE = Path(__file__).resolve().parents[1] / 'source'
SPEC = importlib.util.spec_from_file_location(
    'ingress_lookahead_test_package', SOURCE / '__init__.py',
    submodule_search_locations=[str(SOURCE)],
)
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)

from ingress_lookahead_test_package.agent import Agent  # noqa: E402
from ingress_lookahead_test_package import agent as agent_module  # noqa: E402
from ingress_lookahead_test_package.native import NativeValidator  # noqa: E402


def container_fixture():
    return {
        'index': 0, 'length': 2., 'width': 1.45, 'height': 1.61,
        'thickness': .04, 'buffer': 0., 'cut_x': .44,
        'center': [3., 0., .805], 'shelf': False, 'packed_items': [],
        'n_vecs': [[-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0],
                   [0, 0, -1], [0, 0, 1]],
        'points': [[2.04, 0, 0], [3.96, 0, 0], [3., -.685, 0],
                   [3., .685, 0], [3., 0, .04], [3., 0, 1.57]],
    }


def item_fixture(index, *, length=.2, width=.2, height=.2):
    return {
        'index': index, 'length': length, 'width': width, 'height': height,
        'mass': 1., 'is_soft': False, 'is_prioritized': False,
        'lateralFriction': .8, 'rollingFriction': .01,
        'spinningFriction': .01, 'restitution': 0., 'angularDamping': .8,
        'contactStiffness': 5000., 'contactDamping': 500.,
        'linearDamping': .8,
    }


def action(item_idx, x):
    return {
        'item_idx': item_idx, 'container_idx': 0,
        'orientation': 0,
        'place_pos': np.asarray([x, .5, .148], dtype=np.float32),
    }


class IngressLookaheadTests(unittest.TestCase):
    def test_future_probe_avoids_immediate_greedy_blocker(self):
        current = item_fixture(0)
        future = item_fixture(1, length=.3, width=.3, height=.2)
        observation = {
            'pool_list': [current, future],
            'container_list': [container_fixture()],
            'optimize': False,
        }
        greedy = action(0, 0.)
        ingress_safe = action(0, .4)
        candidates = [((100., 0., 0., 0., 0., 0., 0.), greedy),
                      ((99., 0., 0., 0., 0., 0., 0.), ingress_safe)]

        class FixtureAgent(Agent):
            def _future_fit(self, item, containers, deadline):
                # The virtual candidate is already present when this probe
                # runs.  The greedy x=3.0 placement closes the only future
                # basin; x=3.4 leaves it open.
                placed_x = float(containers[0]['packed_items'][-1]['pos'][0])
                return (placed_x > 3.2, 1)

        agent = FixtureAgent(str(SOURCE))
        agent.mode = 'B'
        agent._policy_deadline = time.perf_counter() + 8.
        agent._native = {}
        agent.last_diagnostics = {}
        ranked_before = sorted(candidates, key=lambda pair: pair[0], reverse=True)
        ranked_after = agent._lookahead_rank(candidates, observation)
        try:
            self.assertEqual(float(ranked_before[0][1]['place_pos'][0]), 0.)
            self.assertAlmostEqual(float(ranked_after[0][1]['place_pos'][0]), .4)
            stats = agent.last_diagnostics['lookahead']
            self.assertEqual(stats['candidates_scored'], 2)
        finally:
            for validator in agent._native.values():
                validator.close()

    def test_future_fit_uses_native_validator_with_world_offset(self):
        agent = Agent(str(SOURCE))
        fit, checks = agent._future_fit(
            item_fixture(1), [container_fixture()],
            time.perf_counter() + 2.,
        )
        self.assertTrue(fit)
        self.assertGreater(checks, 0)

    def test_future_fit_has_global_cap_and_fair_stream_start(self):
        agent = Agent(str(SOURCE))
        agent.lookahead_points_per_type = 6
        agent._prefilter = lambda *_: (False, 0., 0.)
        seen = []

        def infinite_points(_container, dims, _packed, max_points=300):
            seen.append(tuple(dims))
            while True:
                yield (0., 0., .2)

        with patch.object(agent_module, 'mixed_points', side_effect=infinite_points):
            fit, checks = agent._future_fit(
                item_fixture(1, length=.2, width=.3, height=.4),
                [container_fixture()],
                time.perf_counter() + 1.,
            )
        self.assertIsNone(fit)
        self.assertEqual(checks, 6)
        self.assertEqual(len(seen), 6)
        self.assertEqual(len(set(seen)), 6)
        self.assertTrue(agent._future_probe_detail['unknown'])
        self.assertFalse(agent._future_probe_detail['complete'])
        self.assertEqual(agent._future_probe_detail['status'], 'unknown')

    def test_future_fit_timeout_after_proof_is_partial_true(self):
        agent = Agent(str(SOURCE))
        agent.lookahead_points_per_type = 6
        agent.lookahead_valid_limit = 99
        agent._prefilter = lambda *_: (True, 1., .1)

        class Validator:
            calls = 0

            def __init__(self, _container):
                pass

            def check(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return dict(included=True, target_clear=True, transport=True,
                                deadline_exceeded=False)
                return dict(included=True, target_clear=True, transport=False,
                            deadline_exceeded=True)

            def close(self):
                pass

        def two_points(_container, _dims, _packed, max_points=300):
            yield (0., 0., .2)
            yield (.1, 0., .2)

        with patch.object(agent_module, 'NativeValidator', Validator), \
                patch.object(agent_module, 'mixed_points', two_points):
            fit, checks = agent._future_fit(
                item_fixture(1), [container_fixture()],
                time.perf_counter() + 1.,
            )
        self.assertTrue(fit)
        self.assertEqual(checks, 2)
        self.assertFalse(agent._future_probe_detail['unknown'])
        self.assertFalse(agent._future_probe_detail['complete'])
        self.assertEqual(agent._future_probe_detail['status'], 'proven_partial')

    def test_local_action_is_translated_to_offset_container_world(self):
        container = container_fixture()
        item = item_fixture(1)
        proposed = action(0, .2)
        Agent._virtual_add(container, item, proposed)
        self.assertAlmostEqual(container['packed_items'][0]['pos'][0], 3.2)
        with NativeValidator(container_fixture()) as validator:
            result = validator.check(item, proposed)
        self.assertTrue(all(result[key] for key in
                            ('included', 'target_clear', 'transport')), result)

    def test_future_types_are_deduplicated_but_selected_item_is_removed(self):
        pool = [item_fixture(0), item_fixture(1), item_fixture(2, length=.3)]
        future = Agent._future_types(pool, 0)
        self.assertEqual([item['index'] for item in future], [1, 2])

    def test_single_item_pool_keeps_c_path_out_of_lookahead(self):
        agent = Agent(str(SOURCE))
        observation = {'pool_list': [item_fixture(0)], 'container_list': [container_fixture()]}
        candidates = [((1., 0., 0.), action(0, 0.))]
        agent._policy_deadline = time.perf_counter() + 1.
        self.assertIs(agent._lookahead_rank(candidates, observation), candidates)

    def test_modes_are_fixed_at_initialization_and_c_keeps_wide_recovery(self):
        agent = Agent(str(SOURCE))
        containers = [container_fixture()]

        agent.get_init_states(dict(optimize=False, lookahead_k=1,
                                    container_list=containers))
        self.assertEqual(agent.mode, 'C')
        self.assertTrue(agent._historical_prefix_enabled)
        self.assertFalse(agent._lookahead_allowed([item_fixture(0), item_fixture(1)]))
        self.assertEqual(agent.max_authorizations, 384)

        agent.get_init_states(dict(optimize=False, lookahead_k=10,
                                    container_list=containers))
        self.assertEqual(agent.mode, 'B')
        self.assertFalse(agent._historical_prefix_enabled)
        # B remains B after visibility shrinks to one item.
        self.assertTrue(agent._lookahead_allowed([item_fixture(0)]))
        self.assertEqual(agent.max_authorizations, 96)

        agent.get_init_states(dict(optimize=True, lookahead_k=1,
                                    container_list=containers))
        self.assertEqual(agent.mode, 'A')
        self.assertTrue(agent._lookahead_allowed([item_fixture(0), item_fixture(1)]))
        self.assertFalse(agent._historical_prefix_enabled)

    def test_lookahead_deadline_is_shared_and_reserves_preview(self):
        agent = Agent(str(SOURCE))
        agent.mode = 'B'
        agent._policy_deadline = time.perf_counter() + 8.
        first = agent._ensure_lookahead_deadline()
        second = agent._ensure_lookahead_deadline()
        self.assertEqual(first, second)
        self.assertLessEqual(first, agent._policy_deadline - 3.)

    def test_unknown_future_probe_is_neutral_and_unclaimed(self):
        class UnknownAgent(Agent):
            def _future_fit(self, item, containers, deadline):
                self._future_probe_detail = {
                    'valid_insertions': 0, 'valid_basins': 0,
                    'unknown': True, 'complete': False, 'status': 'unknown',
                }
                return None, 1

        agent = UnknownAgent(str(SOURCE))
        agent.mode = 'B'
        agent._policy_deadline = time.perf_counter() + 8.
        agent.last_diagnostics = {}
        candidates = [((10., 0., 0.), action(0, .2))]
        observation = {
            'pool_list': [item_fixture(0), item_fixture(1)],
            'container_list': [container_fixture()],
        }
        try:
            ranked = agent._lookahead_rank(candidates, observation)
            record = agent.last_diagnostics['lookahead']['candidate_scores'][0]
            self.assertEqual(float(ranked[0][0][0]), 10.)
            self.assertTrue(record['unknown'])
            self.assertIsNone(record['survivors'])
            self.assertIsNone(record['missing'])
            self.assertEqual(record['status'], 'unknown')
            self.assertEqual(agent.last_diagnostics['lookahead']['candidates_scored'], 0)
        finally:
            for validator in agent._native.values():
                validator.close()


if __name__ == '__main__':
    unittest.main()
