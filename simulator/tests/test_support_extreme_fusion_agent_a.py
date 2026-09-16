from __future__ import annotations

from collections import Counter
import pathlib
import sys
import time
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.agent import Agent  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mode_a_order_beam import (  # noqa: E402
    LayeredProxyOrderBeam,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (  # noqa: E402
    ModeAPlan,
    build_offline_occurrences,
)
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from tests.test_support_extreme_fusion_layered_proxy import (  # noqa: E402
    _container,
    _raw_item,
)


class ModeAAgentIntegrationTests(unittest.TestCase):
    @staticmethod
    def _compiled_fixture(raw):
        fixture = Agent("support_extreme_fusion_beam_exact_mask")
        fixture.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )
        fixture.optimize(list(raw))
        if type(fixture.mode_a_plan) is not ModeAPlan:
            raise AssertionError("fixture did not compile a complete ModeAPlan")
        state = build_packing_state([_container()])
        occurrences = build_offline_occurrences(raw)
        candidate = LayeredProxyOrderBeam(clock=lambda: 0.0).search(
            state, occurrences, raw, 100.0
        )[0]
        return candidate, fixture.mode_a_plan

    def test_repeated_init_clears_plan_and_fixes_modes(self):
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.mode_a_plan = object()
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )
        self.assertEqual(agent.mode, "A")
        self.assertIsNone(agent.mode_a_plan)
        agent.mode_a_plan = object()
        agent.get_init_states(
            {"optimize": False, "lookahead_k": 10, "container_list": [_container()]}
        )
        self.assertEqual(agent.mode, "B")
        self.assertIsNone(agent.mode_a_plan)
        agent.get_init_states(
            {"optimize": False, "lookahead_k": 1, "container_list": [_container()]}
        )
        self.assertEqual(agent.mode, "C")

    def test_real_small_optimize_publishes_complete_plan_and_permutation(self):
        raw = (_raw_item(9), _raw_item(4), _raw_item(7))
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container(shelf=True)]}
        )
        order = agent.optimize(list(raw))
        self.assertEqual(Counter(order), Counter(value["index"] for value in raw))
        self.assertIsNotNone(agent.mode_a_plan)
        self.assertEqual(len(agent.mode_a_plan.skeleton), len(raw))

    def test_duplicate_ids_remain_a_complete_output_occurrence_permutation(self):
        raw = (_raw_item(4), _raw_item(4))
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )
        order = agent.optimize(list(raw))
        self.assertEqual(order, [4, 4])
        self.assertEqual(len(order), 2)

    def test_order_beam_exception_returns_original_and_clears_plan(self):
        raw = [_raw_item(5), _raw_item(3)]
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )

        class RaisingBeam:
            def search(self, *args, **kwargs):
                raise RuntimeError("synthetic")

        agent.mode_a_order_beam = RaisingBeam()
        agent.mode_a_plan = object()
        self.assertEqual(agent.optimize(raw), [5, 3])
        self.assertIsNone(agent.mode_a_plan)

    def test_duck_typed_compiler_result_is_never_published(self):
        raw = (_raw_item(0),)
        candidate, _plan = self._compiled_fixture(raw)
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent._clock = lambda: 0.0
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )

        class DuckPlan:
            returned_order = (0,)

            def __post_init__(self):
                return None

        agent.mode_a_order_beam = type(
            "Beam", (), {"search": lambda self, *args: (candidate,)}
        )()
        agent.mode_a_compiler = type(
            "Compiler", (), {"compile": lambda self, *args: DuckPlan()}
        )()

        self.assertEqual(agent.optimize(list(raw)), [0])
        self.assertIsNone(agent.mode_a_plan)

    def test_optimize_fails_closed_at_each_absolute_boundary_and_nonfinite_clock(self):
        raw = (_raw_item(0),)
        candidate, plan = self._compiled_fixture(raw)

        class Beam:
            def __init__(self):
                self.calls = 0

            def search(self, *args):
                self.calls += 1
                return (candidate,)

        class Compiler:
            def compile(self, *args):
                return plan

        cases = (
            ("seed_equal", (0.0, 8.0)),
            ("post_compile_equal", (0.0, 0.0, 0.0, 138.0, 138.0, 138.0)),
            ("post_compile_nan", (0.0, 0.0, 0.0, float("nan"))),
            ("post_compile_inf", (0.0, 0.0, 0.0, float("inf"))),
            ("validation_equal", (0.0, 0.0, 0.0, 137.0, 145.0)),
            ("validation_nan", (0.0, 0.0, 0.0, 137.0, float("nan"))),
            ("validation_inf", (0.0, 0.0, 0.0, 137.0, float("inf"))),
            ("hard_equal", (0.0, 0.0, 0.0, 137.0, 144.0, 150.0)),
            ("hard_nan", (0.0, 0.0, 0.0, 137.0, 144.0, float("nan"))),
            ("hard_inf", (0.0, 0.0, 0.0, 137.0, 144.0, float("inf"))),
        )
        for name, values in cases:
            with self.subTest(name=name):
                agent = Agent("support_extreme_fusion_beam_exact_mask")
                iterator = iter(values)
                agent._clock = lambda iterator=iterator: float(next(iterator))
                agent.get_init_states(
                    {
                        "optimize": True,
                        "lookahead_k": 1,
                        "container_list": [_container()],
                    }
                )
                agent.mode_a_order_beam = Beam()
                agent.mode_a_compiler = Compiler()
                self.assertEqual(agent.optimize(list(raw)), [0])
                self.assertIsNone(agent.mode_a_plan)

    def test_late_scanner_and_late_repair_none_use_current_exact_incumbent(self):
        raw = (_raw_item(0),)
        containers = [_container()]
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": containers}
        )
        state = build_packing_state(containers)
        catalog = agent.scanner.scan(state, raw, deadline=time.perf_counter() + 5.0)
        self.assertTrue(catalog)

        class Scanner:
            def scan(self, *args, **kwargs):
                return catalog

        class Repair:
            def __init__(self, result, error_if_called=False):
                self.result = result
                self.error_if_called = error_if_called
                self.calls = 0

            def choose(self, *args):
                self.calls += 1
                if self.error_if_called:
                    raise AssertionError("late scanner must skip repair")
                return self.result

        for name, values, error_if_called in (
            ("late_scanner", (0.0, 5.31, 5.31, 5.31), True),
            ("late_repair", (0.0, 1.0, 5.31, 5.31, 5.31), False),
        ):
            with self.subTest(name=name):
                iterator = iter(values)
                agent._clock = lambda iterator=iterator: float(next(iterator))
                agent.scanner = Scanner()
                repair = Repair(None, error_if_called=error_if_called)
                agent.mode_a_repair = repair
                action = agent.policy(
                    {"container_list": containers, "pool_list": list(raw)}
                )
                self.assertEqual(action["item_idx"], catalog.roots[0].proposal.pool_index)
                self.assertEqual(repair.calls, 0 if error_if_called else 1)

    def test_absolute_order_and_compile_deadlines_are_forwarded(self):
        raw = (_raw_item(0),)
        state = build_packing_state([_container()])
        occurrences = build_offline_occurrences(raw)
        candidate = LayeredProxyOrderBeam(clock=lambda: 0.0).search(
            state, occurrences, raw, 100.0
        )[0]
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent._clock = lambda: 0.0
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )

        class Beam:
            def __init__(self):
                self.deadline = None

            def search(self, state, occurrences, raw_items, deadline):
                self.deadline = deadline
                return (candidate,)

        class Compiler:
            def __init__(self):
                self.deadline = None

            def compile(self, state, raw_items, occurrences, candidate, deadline):
                self.deadline = deadline
                return None

        beam = Beam()
        compiler = Compiler()
        agent.mode_a_order_beam = beam
        agent.mode_a_compiler = compiler
        self.assertEqual(agent.optimize(list(raw)), [0])
        self.assertEqual(beam.deadline, 82.0)
        self.assertEqual(compiler.deadline, 138.0)

    def test_real_mode_a_policy_uses_exact_formatter_schema(self):
        raw = (_raw_item(0),)
        containers = [_container(shelf=True)]
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": containers}
        )
        self.assertEqual(agent.optimize(list(raw)), [0])
        action = agent.policy(
            {"container_list": containers, "pool_list": list(raw)}
        )
        self.assertEqual(
            set(action), {"item_idx", "container_idx", "place_pos", "orientation"}
        )
        self.assertEqual(action["place_pos"].dtype, np.float32)
        self.assertEqual(action["place_pos"].shape, (3,))
        self.assertEqual(action["item_idx"], 0)


if __name__ == "__main__":
    unittest.main()
