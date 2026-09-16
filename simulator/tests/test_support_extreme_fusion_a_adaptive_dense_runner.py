from __future__ import annotations

import pathlib
import sys
import time
import unittest
from unittest.mock import patch


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.agent import Agent  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    AdaptiveDenseRescueConfig,
    CatalogStats,
    RootCatalog,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.state import (  # noqa: E402
    build_packing_state,
)
from agents.support_extreme_fusion_beam_exact_mask.transition import (  # noqa: E402
    SimState,
    apply_root,
)
from tests.replay_support import load_observation_snapshot  # noqa: E402
from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    _a_candidate_rescue_settings,
    _install_a_candidate_rescue,
    build_parser,
    run_episode,
)
from tests.test_run_support_extreme_fusion_physics import (  # noqa: E402
    _FakeAgent,
    _FakeEnv,
    _SequenceClock,
    _action,
    _raw_config,
    SAFE,
)


class ModeAAdaptiveDenseRunnerTests(unittest.TestCase):
    def test_cli_default_and_descriptive_a_only_route(self):
        parser = build_parser()
        default = parser.parse_args(
            ["--task", "000", "--mode", "A", "--output", "result.json"]
        )
        self.assertEqual(default.a_candidate_rescue, "legacy")
        enabled = parser.parse_args(
            [
                "--task", "000", "--mode", "A",
                "--a-candidate-rescue", "global-zero-adaptive-dense-12288",
                "--output", "result.json",
            ]
        )
        self.assertEqual(
            enabled.a_candidate_rescue, "global-zero-adaptive-dense-12288"
        )

    def test_install_is_explicit_requested_and_resolved_a_only(self):
        for requested, resolved, flag, expected in (
            ("A", "A", "global-zero-adaptive-dense-12288", True),
            ("auto", "A", "global-zero-adaptive-dense-12288", False),
            ("B", "B", "global-zero-adaptive-dense-12288", False),
            ("C", "C", "global-zero-adaptive-dense-12288", False),
            ("A", "A", "legacy", False),
        ):
            original = object()
            agent = type(
                "AgentDouble",
                (),
                {"settings": object(), "exact_mask": object(), "scanner": original},
            )()
            with patch(
                "tests.run_support_extreme_fusion_physics.StrictRootScanner"
            ) as factory:
                replacement = object()
                factory.return_value = replacement
                installed = _install_a_candidate_rescue(
                    agent,
                    requested_mode=requested,
                    resolved_mode=resolved,
                    a_candidate_rescue=flag,
                )
            self.assertIs(installed, expected)
            if expected:
                self.assertIs(agent.scanner.delegate, replacement)
                config = factory.call_args.kwargs["adaptive_dense_rescue"]
                self.assertEqual(config.raw_work_limit, 12_288)
                self.assertEqual(config.covered_occurrence_target, 8)
                self.assertEqual(config.output_reserve_seconds, 0.75)
            else:
                self.assertIs(agent.scanner, original)
                factory.assert_not_called()

    def test_settings_metadata_separates_requested_and_effective(self):
        self.assertEqual(
            _a_candidate_rescue_settings(
                "global-zero-adaptive-dense-12288", effective=False
            ),
            {
                "requested": "global-zero-adaptive-dense-12288",
                "effective": "legacy",
                "enabled": False,
            },
        )
        self.assertEqual(
            _a_candidate_rescue_settings(
                "global-zero-adaptive-dense-12288", effective=True
            ),
            {
                "requested": "global-zero-adaptive-dense-12288",
                "effective": "global-zero-adaptive-dense-12288",
                "enabled": True,
                "raw_work_limit": 12_288,
                "covered_occurrence_target": 8,
                "output_reserve_seconds": 0.75,
            },
        )

    def test_frozen_step11_legacy_zero_a_route_finds_current_fresh_root(self):
        observation, _metadata = load_observation_snapshot(
            pathlib.Path(
                "simulator/results/support_extreme_fusion/"
                "task000-a-layered-proxy-order-beam-exact-skeleton-repair-"
                "seed42-failure.npz"
            )
        )
        pool = tuple(observation["pool_list"])
        state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        legacy = agent.scanner.scan(
            state,
            pool,
            deadline=time.perf_counter() + 4.4,
            allow_deferred=True,
            allow_rescue=True,
        )
        self.assertEqual(len(legacy), 0)

        installed = _install_a_candidate_rescue(
            agent,
            requested_mode="A",
            resolved_mode="A",
            a_candidate_rescue="global-zero-adaptive-dense-12288",
        )
        self.assertTrue(installed)
        started = time.perf_counter()
        rescued = agent.scanner.scan(
            state,
            pool,
            deadline=started + 4.4,
            allow_deferred=True,
            allow_rescue=True,
        )
        elapsed = time.perf_counter() - started
        self.assertGreaterEqual(len(rescued), 1)
        self.assertTrue(rescued.stats.adaptive_dense_activated)
        self.assertLess(elapsed, 3.65)
        for root in rescued.roots:
            child = apply_root(
                SimState.from_current(state, pool),
                root,
                agent.settings,
                exact_revalidator=agent.exact_mask,
                deadline=time.perf_counter() + 1.0,
            )
            self.assertEqual(len(child.child.pool), len(pool) - 1)

    def test_runner_json_records_effective_a_route_and_initial_scan_stats(self):
        stats = CatalogStats(
            adaptive_dense_activated=True,
            adaptive_dense_raw_generated=9196,
            adaptive_dense_exact_attempts=4520,
            adaptive_dense_covered_occurrences=1,
            adaptive_dense_early_stop=True,
        )

        class ScannerDouble:
            def scan(self, *_args, **_kwargs):
                return RootCatalog((), stats)

            def scan_coverage_fixed(self, *_args, **_kwargs):
                return RootCatalog.empty()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.settings = object()
                self.exact_mask = object()
                self.scanner = object()

            def policy(self, observation):
                self.scanner.scan(object(), observation["pool_list"])
                return super().policy(observation)

        with patch(
            "tests.run_support_extreme_fusion_physics.StrictRootScanner",
            return_value=ScannerDouble(),
        ):
            result = run_episode(
                _raw_config(),
                task="000",
                requested_items=1,
                seed=42,
                requested_mode="A",
                a_candidate_rescue="global-zero-adaptive-dense-12288",
                env_factory=lambda _config: _FakeEnv([SAFE]),
                agent_factory=AgentDouble,
                clock=_SequenceClock((0.0, 0.1, 1.0, 1.1)),
            )
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(
            result["a_candidate_rescue_settings"]["effective"],
            "global-zero-adaptive-dense-12288",
        )
        self.assertTrue(result["a_candidate_rescue_settings"]["enabled"])
        self.assertEqual(
            result["diagnostic"]["adaptive_dense_scans"][0][
                "adaptive_dense_exact_attempts"
            ],
            4520,
        )


if __name__ == "__main__":
    unittest.main()
