from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
import pathlib
import sys
import unittest


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.agent import Agent  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (  # noqa: E402
    ModeAPlan,
    build_offline_occurrences,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import (  # noqa: E402
    SearchSettings,
)
from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    _a_order_fallback_settings,
    _install_a_candidate_rescue,
    _install_a_order_fallback,
    build_parser,
    run_episode,
)
from tests.test_run_support_extreme_fusion_physics import (  # noqa: E402
    SAFE,
    _FakeAgent,
    _FakeEnv,
    _SequenceClock,
    _action,
    _raw_config,
)
from tests.test_support_extreme_fusion_layered_proxy import (  # noqa: E402
    _container,
    _raw_item,
)
from tests.test_support_extreme_fusion_mode_a_order_beam import (  # noqa: E402
    _candidate,
)


class _Beam:
    def __init__(self, candidates):
        self.candidates = tuple(candidates)

    def search(self, *_args):
        return self.candidates


class ModeAProxyPrefixFallbackTests(unittest.TestCase):
    def _agent(self, raw, candidate, *, enabled):
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )
        agent.settings = replace(
            agent.settings, mode_a_proxy_prefix_order_fallback=enabled
        )
        agent._clock = lambda: 0.0
        agent.mode_a_order_beam = _Beam(() if candidate is None else (candidate,))
        return agent

    def test_default_false_preserves_original_and_profile_digest(self):
        raw = (_raw_item(10), _raw_item(20), _raw_item(30))
        occurrences = build_offline_occurrences(raw)
        candidate = _candidate(
            (occurrences[2], occurrences[0], occurrences[1]),
            placed_count=1,
            placed_volume=0.01,
            complete=False,
        )
        agent = self._agent(raw, candidate, enabled=False)
        self.assertFalse(SearchSettings().mode_a_proxy_prefix_order_fallback)
        self.assertEqual(
            SearchSettings().profile_digest(),
            replace(
                SearchSettings(), mode_a_proxy_prefix_order_fallback=True
            ).profile_digest(),
        )
        self.assertEqual(agent.optimize(list(raw)), [10, 20, 30])
        self.assertIsNone(agent.mode_a_plan)
        self.assertIsNone(agent.mode_a_order_fallback_trace)

    def test_enabled_returns_authoritative_full_partial_order_without_plan(self):
        raw = (_raw_item(10), _raw_item(20), _raw_item(30))
        occurrences = build_offline_occurrences(raw)
        ordered = (occurrences[2], occurrences[0], occurrences[1])
        candidate = _candidate(
            ordered, placed_count=1, placed_volume=0.01, complete=False
        )
        agent = self._agent(raw, candidate, enabled=True)
        self.assertEqual(agent.optimize(list(raw)), [30, 10, 20])
        self.assertIsNone(agent.mode_a_plan)
        self.assertEqual(
            agent.mode_a_order_fallback_trace,
            {"selected_depth": 1, "seed_lane": 0},
        )

    def test_duplicate_ids_remain_complete_occurrences_and_stale_is_rejected(self):
        raw = (_raw_item(4), _raw_item(4), _raw_item(8))
        occurrences = build_offline_occurrences(raw)
        valid = _candidate(
            (occurrences[1], occurrences[2], occurrences[0]),
            placed_count=1,
            placed_volume=0.01,
            complete=False,
        )
        agent = self._agent(raw, valid, enabled=True)
        order = agent.optimize(list(raw))
        self.assertEqual(order, [4, 8, 4])
        self.assertEqual(Counter(order), Counter((4, 4, 8)))

        stale_raw = list(raw)
        stale_raw[1] = {**stale_raw[1], "mass": 99.0}
        stale_occurrences = build_offline_occurrences(stale_raw)
        stale = _candidate(
            (stale_occurrences[1], stale_occurrences[2], stale_occurrences[0]),
            placed_count=1,
            placed_volume=0.01,
            complete=False,
        )
        agent = self._agent(raw, stale, enabled=True)
        self.assertEqual(agent.optimize(list(raw)), [4, 4, 8])
        self.assertIsNone(agent.mode_a_order_fallback_trace)

    def test_empty_partial_and_twenty_repeats_are_fail_closed_and_deterministic(self):
        raw = (_raw_item(1), _raw_item(2), _raw_item(3))
        occurrences = build_offline_occurrences(raw)
        candidate = _candidate(
            (occurrences[1], occurrences[0], occurrences[2]),
            placed_count=1,
            placed_volume=0.01,
            complete=False,
        )
        outputs = []
        traces = []
        for _ in range(20):
            agent = self._agent(raw, candidate, enabled=True)
            outputs.append(agent.optimize(list(raw)))
            traces.append(agent.mode_a_order_fallback_trace)
        self.assertEqual(outputs, [[2, 1, 3]] * 20)
        self.assertEqual(traces, [{"selected_depth": 1, "seed_lane": 0}] * 20)
        empty = self._agent(raw, None, enabled=True)
        self.assertEqual(empty.optimize(list(raw)), [1, 2, 3])
        self.assertIsNone(empty.mode_a_order_fallback_trace)

    def test_partial_authority_validation_must_finish_before_final_deadline(self):
        raw = (_raw_item(1), _raw_item(2), _raw_item(3))
        occurrences = build_offline_occurrences(raw)
        candidate = _candidate(
            (occurrences[1], occurrences[0], occurrences[2]),
            placed_count=1,
            placed_volume=0.01,
            complete=False,
        )
        for label, boundary in (
            ("equal", 145.0),
            ("nan", float("nan")),
            ("positive_inf", float("inf")),
            ("negative_inf", -float("inf")),
        ):
            with self.subTest(label=label):
                values = iter((0.0, 0.0, 0.0, boundary, 149.0))
                agent = self._agent(raw, candidate, enabled=True)
                agent._clock = lambda values=values: float(next(values))
                self.assertEqual(agent.optimize(list(raw)), [1, 2, 3])
                self.assertIsNone(agent.mode_a_order_fallback_trace)

    def test_full_compiled_plan_has_precedence_over_ranked_partial(self):
        raw = (_raw_item(0),)
        fixture = Agent("support_extreme_fusion_beam_exact_mask")
        fixture.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [_container()]}
        )
        fixture.optimize(list(raw))
        self.assertIs(type(fixture.mode_a_plan), ModeAPlan)
        plan = fixture.mode_a_plan
        occurrences = build_offline_occurrences(raw)
        partial = _candidate(
            occurrences,
            placed_count=0,
            placed_volume=0.0,
            complete=False,
        )
        complete = replace(partial, skeleton=plan.skeleton, placed_count=1,
                           placed_volume=raw[0]["length"] * raw[0]["width"] * raw[0]["height"],
                           min_alternatives=1, complete=True)
        agent = self._agent(raw, partial, enabled=True)
        agent.mode_a_order_beam = _Beam((complete, partial))
        agent.mode_a_compiler = type(
            "Compiler", (), {"compile": lambda self, *_args: plan}
        )()
        self.assertEqual(agent.optimize(list(raw)), [0])
        self.assertIs(agent.mode_a_plan, plan)
        self.assertIsNone(agent.mode_a_order_fallback_trace)

    def test_frozen_task000_prefix_diverges_at_step_zero_without_plan(self):
        with pathlib.Path("simulator/configs/sample_config.json").open(
            encoding="utf-8"
        ) as stream:
            raw = tuple(json.load(stream)["000"]["item_stream"]["item_list"])
        occurrences = build_offline_occurrences(raw)
        prefix = (3, 17, 21, 33, 1, 28, 5, 2)
        positions = prefix + tuple(index for index in range(41) if index not in prefix)
        ordered = tuple(occurrences[index] for index in positions)
        candidate = _candidate(
            ordered,
            placed_count=8,
            placed_volume=0.713725,
            complete=False,
        )
        candidate = replace(candidate, seed_lane=1)
        agent = self._agent(raw, candidate, enabled=True)
        order = agent.optimize(list(raw))
        self.assertEqual(order[:8], list(prefix))
        self.assertNotEqual(order, list(range(41)))
        self.assertIsNone(agent.mode_a_plan)
        self.assertEqual(
            agent.mode_a_order_fallback_trace,
            {"selected_depth": 8, "seed_lane": 1},
        )

    def test_runner_flag_is_explicit_a_only_and_metadata_truthful(self):
        parser = build_parser()
        default = parser.parse_args(
            ["--task", "000", "--mode", "A", "--output", "result.json"]
        )
        self.assertEqual(default.a_order_fallback, "original")
        explicit = parser.parse_args(
            [
                "--task", "000", "--mode", "A",
                "--a-order-fallback", "proxy-prefix",
                "--output", "result.json",
            ]
        )
        self.assertEqual(explicit.a_order_fallback, "proxy-prefix")
        for requested, resolved, expected in (
            ("A", "A", True),
            ("auto", "A", False),
            ("B", "B", False),
            ("C", "C", False),
        ):
            agent = type("AgentDouble", (), {"settings": SearchSettings()})()
            enabled = _install_a_order_fallback(
                agent,
                requested_mode=requested,
                resolved_mode=resolved,
                a_order_fallback="proxy-prefix",
            )
            self.assertIs(enabled, expected)
            self.assertIs(
                agent.settings.mode_a_proxy_prefix_order_fallback, expected
            )
            metadata = _a_order_fallback_settings(
                "proxy-prefix", effective=enabled
            )
            self.assertIs(metadata["enabled"], expected)
            self.assertEqual(
                metadata["effective"], "proxy-prefix" if expected else "original"
            )

    def test_a_adaptive_rescue_and_proxy_prefix_flags_install_independently(self):
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        self.assertTrue(
            _install_a_candidate_rescue(
                agent,
                requested_mode="A",
                resolved_mode="A",
                a_candidate_rescue="global-zero-adaptive-dense-12288",
            )
        )
        adaptive_scanner = agent.scanner
        self.assertTrue(
            _install_a_order_fallback(
                agent,
                requested_mode="A",
                resolved_mode="A",
                a_order_fallback="proxy-prefix",
            )
        )
        self.assertIs(agent.scanner, adaptive_scanner)
        self.assertTrue(agent.settings.mode_a_proxy_prefix_order_fallback)

    def test_runner_records_selected_depth_and_seed_without_plan(self):
        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.settings = SearchSettings()

            def optimize(self, item_list):
                order = super().optimize(item_list)
                self.mode_a_plan = None
                self.mode_a_order_fallback_trace = {
                    "selected_depth": 8,
                    "seed_lane": 1,
                }
                return order

        result = run_episode(
            _raw_config(),
            task="000",
            requested_items=1,
            seed=42,
            requested_mode="A",
            a_order_fallback="proxy-prefix",
            env_factory=lambda _config: _FakeEnv([SAFE]),
            agent_factory=AgentDouble,
            clock=_SequenceClock((0.0, 0.1, 1.0, 1.1)),
        )
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(
            result["a_order_fallback_settings"],
            {
                "requested": "proxy-prefix",
                "effective": "proxy-prefix",
                "enabled": True,
            },
        )
        self.assertEqual(
            result["mode_a_order_fallback_trace"],
            {"selected_depth": 8, "seed_lane": 1},
        )
        self.assertIsNone(result["mode_a_plan_trace"])


if __name__ == "__main__":
    unittest.main()
