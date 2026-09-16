from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    RankObjective,
    SelectionTrace,
)
from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    _b_rank_objective_settings,
    _install_b_planner,
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


class ContinuationSurvivalRunnerTests(unittest.TestCase):
    def test_parser_exposes_legacy_default_and_explicit_survival(self):
        parser = build_parser()
        default = parser.parse_args(["--task", "001", "--output", "x.json"])
        survival = parser.parse_args(
            [
                "--task",
                "001",
                "--output",
                "x.json",
                "--b-rank-objective",
                "continuation-survival",
            ]
        )

        self.assertEqual(default.b_rank_objective, "legacy")
        self.assertEqual(survival.b_rank_objective, "continuation-survival")

    def test_explicit_b_stratified_installs_survival_objective_only(self):
        selector = type("Selector", (), {"last_trace": SelectionTrace()})()
        agent = type(
            "AgentDouble",
            (),
            {
                "beam": object(),
                "scanner": object(),
                "exact_mask": object(),
                "settings": object(),
            },
        )()
        with patch(
            "tests.run_support_extreme_fusion_physics."
            "MemoizedStreamingRegretProxySelector",
            return_value=selector,
        ) as constructor:
            _install_b_planner(
                agent,
                requested_mode="B",
                resolved_mode="B",
                b_planner="memoized-stratified-maxrects-regret",
                b_rank_objective="continuation-survival",
            )

        self.assertIs(agent.beam._selector, selector)
        self.assertIs(
            constructor.call_args.kwargs["rank_objective"],
            RankObjective.CERTIFIED_CONTINUATION_SURVIVAL,
        )

    def test_non_stratified_or_non_explicit_b_never_enables_objective(self):
        self.assertEqual(
            _b_rank_objective_settings(
                "continuation-survival", effective=False
            ),
            {
                "requested": "continuation-survival",
                "effective": "legacy",
                "enabled": False,
            },
        )
        for requested_mode, resolved_mode in (("C", "C"), ("A", "A"), ("auto", "B")):
            agent = type(
                "AgentDouble",
                (),
                {
                    "beam": object(),
                    "scanner": object(),
                    "exact_mask": object(),
                    "settings": object(),
                },
            )()
            with patch(
                "tests.run_support_extreme_fusion_physics."
                "MemoizedStreamingRegretProxySelector"
            ) as constructor:
                _install_b_planner(
                    agent,
                    requested_mode=requested_mode,
                    resolved_mode=resolved_mode,
                    b_planner="memoized-stratified-maxrects-regret",
                    b_rank_objective="continuation-survival",
                )
            constructor.assert_not_called()

    def test_result_records_requested_and_effective_objective_truthfully(self):
        selector = type("Selector", (), {"last_trace": SelectionTrace()})()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()

        with patch(
            "tests.run_support_extreme_fusion_physics."
            "MemoizedStreamingRegretProxySelector",
            return_value=selector,
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                b_planner="memoized-stratified-maxrects-regret",
                b_rank_objective="continuation-survival",
                env_factory=lambda _config: _FakeEnv([SAFE]),
                agent_factory=AgentDouble,
                clock=_SequenceClock((0.0, 0.1)),
            )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["b_rank_objective"], "continuation-survival")
        self.assertEqual(
            result["b_rank_objective_settings"],
            {
                "requested": "continuation-survival",
                "effective": "continuation-survival",
                "enabled": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
