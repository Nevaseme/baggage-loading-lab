from __future__ import annotations

import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.agent import (  # noqa: E402
    CandidateZeroError,
    NotReadyError,
    PlanningError,
)
from agents.support_extreme_fusion_beam_exact_mask.fixed_quota import BSearchTrace  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    SelectionTrace,
)
from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    ProxyExposureOrder,
)
from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    _install_candidate_rescue,
    _install_b_planner,
    action_format_is_valid,
    atomic_write_json,
    build_parser,
    materialize_config,
    run_episode,
    status_format_is_valid,
)
from tests.replay_support import load_observation_snapshot  # noqa: E402


SAFE = {"is_included": True, "is_valid": True, "is_placed_safe": True}


def _raw_config() -> dict:
    return {
        "agent": {"optimize": False},
        "item_stream": {
            "look_ahead": 10,
            "item_list": [
                {"index": index, "length": 0.2, "width": 0.2, "height": 0.2, "mass": 1.0}
                for index in range(4)
            ],
        },
        "visualizer": {"vis": True},
    }


def _observation(pool_size: int = 3) -> dict:
    return {
        "container_list": [{"index": 0, "packed_items": []}],
        "pool_list": [
            {"index": index, "length": 0.2, "width": 0.2, "height": 0.2, "mass": 1.0}
            for index in range(pool_size)
        ],
    }


def _action(item_idx: int = 0) -> dict:
    return {
        "item_idx": item_idx,
        "container_idx": 0,
        "place_pos": np.asarray((0.0, 0.0, 0.2), dtype=np.float32),
        "orientation": 0,
    }


class _FakeEnv:
    def __init__(self, statuses, *, evaluation=None) -> None:
        self.statuses = [dict(status) for status in statuses]
        self.evaluation_value = evaluation or {"fill_score": 12.5, "num_placed_items": 1.0}
        self.observation = _observation(len(statuses))
        self.shm_depth_map = np.arange(16, dtype=np.float32).reshape(1, 4, 4)
        self.reset_settings_called = False
        self.reset_item_stream_called = False
        self.reset_item_stream_calls = 0
        self.optimized_order = None
        self.optimization_items_requested = 0
        self.closed = False
        self.step_actions: list[dict] = []
        self.seed = None

    def reset_settings(self):
        self.reset_settings_called = True

    def reset_item_stream(self):
        self.reset_item_stream_called = True
        self.reset_item_stream_calls += 1

    def get_info_for_optimization(self):
        self.optimization_items_requested += 1
        return copy.deepcopy(self.observation["pool_list"])

    def set_item_order(self, order):
        expected = [item["index"] for item in self.observation["pool_list"]]
        if not isinstance(order, list) or sorted(order) != sorted(expected):
            return False
        by_index = {item["index"]: item for item in self.observation["pool_list"]}
        self.observation["pool_list"] = [by_index[index] for index in order]
        self.optimized_order = list(order)
        return True

    def get_init_states(self):
        return {
            "optimize": False,
            "lookahead_k": 10,
            "container_list": copy.deepcopy(self.observation["container_list"]),
        }

    def reset(self, seed=None):
        self.seed = seed
        return copy.deepcopy(self.observation), {}

    def step(self, action):
        self.step_actions.append(action)
        status = self.statuses[len(self.step_actions) - 1]
        if status == SAFE:
            selected = self.observation["pool_list"].pop(action["item_idx"])
            self.observation["container_list"][0]["packed_items"].append(selected)
        terminated = len(self.step_actions) >= len(self.statuses)
        return copy.deepcopy(self.observation), 0.0, terminated, False, {"status": status}

    def evaluate(self):
        return copy.deepcopy(self.evaluation_value)

    def close(self):
        self.closed = True


class _FakeAgent:
    def __init__(self, actions=None, *, error=None) -> None:
        self.actions = list(actions or [_action()])
        self.error = error
        self.init_state = None
        self.depth_copies: list[np.ndarray] = []
        self.optimize_inputs: list[list[dict]] = []
        self.mode_a_plan = None

    def get_init_states(self, value):
        self.init_state = copy.deepcopy(value)
        return True

    def policy(self, observation):
        self.depth_copies.append(observation["depth_map"])
        if self.error is not None:
            raise self.error
        return self.actions[len(self.depth_copies) - 1]

    def optimize(self, item_list):
        self.optimize_inputs.append(copy.deepcopy(item_list))
        return [int(item["index"]) for item in reversed(item_list)]


class _SequenceClock:
    def __init__(self, values) -> None:
        self.values = iter(values)

    def __call__(self):
        return float(next(self.values))


class SupportExtremeFusionPhysicsRunnerTests(unittest.TestCase):
    def test_parser_exposes_bounded_official_cli(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--task", "001", "--items", "7", "--seed", "19", "--mode", "B",
                "--output", "run.json", "--snapshot-on-failure", "failure.npz",
            ]
        )
        self.assertEqual((args.task, args.items, args.seed, args.mode), ("001", 7, 19, "B"))
        self.assertEqual(args.output, pathlib.Path("run.json"))
        self.assertEqual(args.snapshot_on_failure, pathlib.Path("failure.npz"))
        self.assertEqual(args.b_planner, "beam")
        self.assertEqual(args.candidate_rescue, "legacy")
        adaptive = parser.parse_args(
            [
                "--task", "001", "--mode", "B",
                "--candidate-rescue", "global-zero-adaptive-dense",
                "--output", "adaptive.json",
            ]
        )
        self.assertEqual(adaptive.candidate_rescue, "global-zero-adaptive-dense")
        one_ply = parser.parse_args(
            [
                "--task", "001", "--mode", "B", "--b-planner", "one-ply",
                "--output", "one-ply.json",
            ]
        )
        self.assertEqual(one_ply.b_planner, "one-ply")
        fixed = parser.parse_args(
            [
                "--task", "001", "--mode", "B", "--b-planner", "fixed-two-ply",
                "--output", "fixed.json",
            ]
        )
        self.assertEqual(fixed.b_planner, "fixed-two-ply")
        maxrects = parser.parse_args(
            [
                "--task", "001", "--mode", "B", "--b-planner", "maxrects-regret",
                "--output", "maxrects.json",
            ]
        )
        self.assertEqual(maxrects.b_planner, "maxrects-regret")
        streaming = parser.parse_args(
            [
                "--task", "001", "--mode", "B",
                "--b-planner", "memoized-streaming-maxrects-regret",
                "--output", "streaming.json",
            ]
        )
        self.assertEqual(
            streaming.b_planner, "memoized-streaming-maxrects-regret"
        )
        stratified = parser.parse_args(
            [
                "--task", "001", "--output", "result.json",
                "--b-planner", "memoized-stratified-maxrects-regret",
            ]
        )
        self.assertEqual(
            stratified.b_planner, "memoized-stratified-maxrects-regret"
        )
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--task", "999", "--output", "x.json"])
            with self.assertRaises(SystemExit):
                parser.parse_args(["--task", "000", "--items", "0", "--output", "x.json"])

    def test_b_one_ply_delegates_choose_b_to_choose_c_with_full_pool(self) -> None:
        sentinel = object()

        class RecordingBeam:
            def __init__(self):
                self.choose_b_calls = 0
                self.choose_c_args = None

            def choose_b(self, *_args, **_kwargs):
                self.choose_b_calls += 1
                raise AssertionError("original B beam must not run")

            def choose_c(self, *args):
                self.choose_c_args = args
                return sentinel

        original = RecordingBeam()
        agent = type("AgentDouble", (), {"beam": original, "mode": "B"})()
        _install_b_planner(
            agent,
            requested_mode="B",
            resolved_mode="B",
            b_planner="one-ply",
        )
        state = object()
        pool = tuple(object() for _ in range(40))
        catalog = object()
        deadline = 12.5

        selected = agent.beam.choose_b(state, pool, catalog, deadline)

        self.assertIs(selected, sentinel)
        self.assertEqual(original.choose_b_calls, 0)
        self.assertIs(original.choose_c_args[0], state)
        self.assertIs(original.choose_c_args[1], pool)
        self.assertEqual(len(original.choose_c_args[1]), 40)
        self.assertIs(original.choose_c_args[2], catalog)
        self.assertEqual(original.choose_c_args[3], deadline)
        self.assertEqual(agent.mode, "B")

    def test_adaptive_candidate_rescue_is_explicit_b_only_and_rebinds_beam(self) -> None:
        class Beam:
            def __init__(self, scanner):
                self.scanner = scanner

        settings = object()
        mask = object()
        for requested, resolved, flag, expected in (
            ("B", "B", "global-zero-adaptive-dense", True),
            ("auto", "B", "global-zero-adaptive-dense", False),
            ("C", "C", "global-zero-adaptive-dense", False),
            ("A", "A", "global-zero-adaptive-dense", False),
            ("B", "B", "legacy", False),
        ):
            original_scanner = object()
            agent = type(
                "AgentDouble",
                (),
                {
                    "settings": settings,
                    "exact_mask": mask,
                    "scanner": original_scanner,
                    "beam": Beam(original_scanner),
                },
            )()
            with patch(
                "tests.run_support_extreme_fusion_physics.StrictRootScanner"
            ) as factory:
                replacement = object()
                factory.return_value = replacement
                installed = _install_candidate_rescue(
                    agent,
                    requested_mode=requested,
                    resolved_mode=resolved,
                    candidate_rescue=flag,
                )
            self.assertIs(installed, expected)
            if expected:
                self.assertIs(agent.scanner.delegate, replacement)
                self.assertIs(agent.beam.scanner, agent.scanner)
                factory.assert_called_once()
            else:
                self.assertIs(agent.scanner, original_scanner)
                self.assertIs(agent.beam.scanner, original_scanner)
                factory.assert_not_called()

    def test_runner_records_adaptive_setting_and_initial_scan_stats(self) -> None:
        from agents.support_extreme_fusion_beam_exact_mask.catalog import (
            CatalogStats,
            RootCatalog,
        )

        stats = CatalogStats(
            adaptive_dense_activated=True,
            adaptive_dense_raw_generated=4096,
            adaptive_dense_exact_attempts=300,
            adaptive_dense_covered_occurrences=1,
            adaptive_dense_early_stop=False,
            adaptive_dense_deadline_reached=False,
        )

        class ScannerDouble:
            def scan(self, *_args, **_kwargs):
                return RootCatalog((), stats)

            def scan_coverage_fixed(self, *_args, **_kwargs):
                return RootCatalog.empty()

        class BeamDouble:
            def __init__(self, scanner):
                self.scanner = scanner

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.settings = object()
                self.exact_mask = object()
                self.scanner = object()
                self.beam = BeamDouble(self.scanner)

            def policy(self, observation):
                self.scanner.scan(object(), observation["pool_list"])
                return super().policy(observation)

        env = _FakeEnv([SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics.StrictRootScanner",
            return_value=ScannerDouble(),
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                candidate_rescue="global-zero-adaptive-dense",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.1)),
            )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["candidate_rescue"], "global-zero-adaptive-dense")
        self.assertEqual(
            result["candidate_rescue_settings"],
            {
                "requested": "global-zero-adaptive-dense",
                "effective": "global-zero-adaptive-dense",
                "enabled": True,
                "raw_work_limit": 4096,
                "covered_occurrence_target": 8,
                "output_reserve_seconds": 0.75,
            },
        )
        rows = result["diagnostic"]["adaptive_dense_scans"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["step"], 0)
        self.assertEqual(rows[0]["adaptive_dense_raw_generated"], 4096)

    def test_runner_records_adaptive_request_as_ineffective_outside_explicit_b(self) -> None:
        for requested_mode, expected_resolved in (
            ("C", "C"),
            ("auto", "B"),
            ("A", "A"),
        ):
            with self.subTest(requested_mode=requested_mode):
                env = _FakeEnv([SAFE])
                result = run_episode(
                    _raw_config(),
                    task="001",
                    requested_items=1,
                    seed=42,
                    requested_mode=requested_mode,
                    candidate_rescue="global-zero-adaptive-dense",
                    env_factory=lambda _config, env=env: env,
                    agent_factory=lambda: _FakeAgent([_action()]),
                    clock=_SequenceClock((0.0, 0.1)),
                )

                self.assertEqual(result["candidate_rescue"], "global-zero-adaptive-dense")
                self.assertEqual(result["resolved_mode"], expected_resolved)
                self.assertEqual(
                    result["candidate_rescue_settings"],
                    {
                        "requested": "global-zero-adaptive-dense",
                        "effective": "legacy",
                        "enabled": False,
                    },
                )
                self.assertEqual(result["diagnostic"]["adaptive_dense_scans"], [])

    def test_one_ply_does_not_wrap_c_a_or_default_beam(self) -> None:
        for requested_mode, resolved_mode, planner in (
            ("C", "C", "one-ply"),
            ("A", "A", "one-ply"),
            ("B", "B", "beam"),
            ("auto", "B", "one-ply"),
            ("C", "C", "fixed-two-ply"),
            ("A", "A", "fixed-two-ply"),
            ("auto", "B", "fixed-two-ply"),
            ("C", "C", "maxrects-regret"),
            ("A", "A", "maxrects-regret"),
            ("auto", "B", "maxrects-regret"),
            ("C", "C", "memoized-streaming-maxrects-regret"),
            ("A", "A", "memoized-streaming-maxrects-regret"),
            ("auto", "B", "memoized-streaming-maxrects-regret"),
            ("C", "C", "memoized-stratified-maxrects-regret"),
            ("A", "A", "memoized-stratified-maxrects-regret"),
            ("auto", "B", "memoized-stratified-maxrects-regret"),
        ):
            with self.subTest(mode=requested_mode, planner=planner):
                original = object()
                agent = type(
                    "AgentDouble", (), {"beam": original, "mode": resolved_mode}
                )()
                _install_b_planner(
                    agent,
                    requested_mode=requested_mode,
                    resolved_mode=resolved_mode,
                    b_planner=planner,
                )
                self.assertIs(agent.beam, original)
                self.assertEqual(agent.mode, resolved_mode)

    def test_stratified_planner_json_distinguishes_requested_from_effective_route(self) -> None:
        planner = "memoized-stratified-maxrects-regret"
        for requested_mode, expected_resolved in (
            ("C", "C"),
            ("A", "A"),
            ("auto", "B"),
        ):
            with self.subTest(mode=requested_mode):
                env = _FakeEnv([SAFE])
                result = run_episode(
                    _raw_config(),
                    task="001",
                    requested_items=1,
                    seed=42,
                    requested_mode=requested_mode,
                    b_planner=planner,
                    env_factory=lambda _config, env=env: env,
                    agent_factory=lambda: _FakeAgent([_action()]),
                    clock=_SequenceClock((0.0, 0.1)),
                )

                self.assertEqual(result["b_planner"], planner)
                self.assertEqual(result["resolved_mode"], expected_resolved)
                self.assertEqual(
                    result["b_planner_settings"],
                    {
                        "requested": planner,
                        "effective": "beam",
                        "enabled": False,
                    },
                )

    def test_b_fixed_two_ply_uses_agent_exact_components_and_full_pool(self) -> None:
        sentinel = object()

        class RecordingPlanner:
            def __init__(self):
                self.args = None
                self.last_trace = BSearchTrace(stage1_edges=40, child_scans=8)

            def choose_b(self, *args):
                self.args = args
                return sentinel

        planner = RecordingPlanner()
        scanner, exact_mask, settings = object(), object(), object()
        original_beam = object()
        agent = type(
            "AgentDouble",
            (),
            {
                "beam": original_beam,
                "scanner": scanner,
                "exact_mask": exact_mask,
                "settings": settings,
                "mode": "B",
            },
        )()
        with patch(
            "tests.run_support_extreme_fusion_physics.FixedQuotaExactTwoPly",
            return_value=planner,
        ) as factory:
            _install_b_planner(
                agent,
                requested_mode="B",
                resolved_mode="B",
                b_planner="fixed-two-ply",
            )

        state = object()
        pool = tuple(object() for _ in range(40))
        catalog = object()
        deadline = 5.30
        selected = agent.beam.choose_b(state, pool, catalog, deadline)

        self.assertIs(selected, sentinel)
        factory.assert_called_once_with(scanner, exact_mask, settings)
        self.assertEqual(planner.args, (state, pool, catalog, deadline))
        self.assertEqual(len(planner.args[1]), 40)
        self.assertIs(agent.beam._original_beam, original_beam)
        self.assertEqual(agent.mode, "B")

    def test_b_maxrects_regret_uses_exact_components_full_pool_and_original_root(self) -> None:
        first_root = object()
        second_root = object()

        class RecordingSelector:
            def __init__(self):
                self.args = None
                self.last_trace = SelectionTrace(predicted_count=2)

            def select(self, *args):
                self.args = args
                return (first_root, second_root)

        selector = RecordingSelector()
        scanner, exact_mask, settings = object(), object(), object()
        original_beam = object()
        agent = type(
            "AgentDouble",
            (),
            {
                "beam": original_beam,
                "scanner": scanner,
                "exact_mask": exact_mask,
                "settings": settings,
                "mode": "B",
            },
        )()
        sim = object()
        state = object()
        pool = tuple(object() for _ in range(40))
        catalog = object()
        deadline = 5.30
        with patch(
            "tests.run_support_extreme_fusion_physics.RegretProxySelector",
            return_value=selector,
        ) as factory, patch(
            "tests.run_support_extreme_fusion_physics.SimState.from_current",
            return_value=sim,
        ) as from_current:
            _install_b_planner(
                agent,
                requested_mode="B",
                resolved_mode="B",
                b_planner="maxrects-regret",
            )
            selected = agent.beam.choose_b(state, pool, catalog, deadline)

        self.assertIs(selected, first_root)
        self.assertNotIsInstance(selected, dict)
        factory.assert_called_once_with(exact_mask, settings=settings)
        from_current.assert_called_once_with(state, pool)
        self.assertEqual(selector.args, (sim, catalog, "B", deadline))
        self.assertEqual(len(pool), 40)
        self.assertIs(agent.beam._original_beam, original_beam)
        self.assertIs(agent.beam._scanner, scanner)
        self.assertEqual(agent.mode, "B")

    def test_b_memoized_streaming_route_keeps_full_pool_and_original_root(self) -> None:
        first_root = object()

        class RecordingSelector:
            def __init__(self):
                self.args = None
                self.last_trace = SelectionTrace(
                    predicted_count=3,
                    duplicate_checks_avoided=12,
                    committed_children=4,
                )

            def select(self, *args):
                self.args = args
                return (first_root,)

        selector = RecordingSelector()
        scanner, exact_mask, settings = object(), object(), object()
        original_beam = object()
        agent = type(
            "AgentDouble",
            (),
            {
                "beam": original_beam,
                "scanner": scanner,
                "exact_mask": exact_mask,
                "settings": settings,
                "mode": "B",
            },
        )()
        sim = object()
        state = object()
        pool = tuple(object() for _ in range(40))
        catalog = object()
        deadline = 5.30
        with patch(
            "tests.run_support_extreme_fusion_physics."
            "MemoizedStreamingRegretProxySelector",
            return_value=selector,
        ) as factory, patch(
            "tests.run_support_extreme_fusion_physics.SimState.from_current",
            return_value=sim,
        ) as from_current:
            _install_b_planner(
                agent,
                requested_mode="B",
                resolved_mode="B",
                b_planner="memoized-streaming-maxrects-regret",
            )
            selected = agent.beam.choose_b(state, pool, catalog, deadline)

        self.assertIs(selected, first_root)
        factory.assert_called_once_with(exact_mask, settings=settings)
        from_current.assert_called_once_with(state, pool)
        self.assertEqual(selector.args, (sim, catalog, "B", deadline))
        self.assertEqual(len(pool), 40)
        self.assertIs(agent.beam._scanner, scanner)
        self.assertEqual(agent.mode, "B")

    def test_b_memoized_stratified_route_sets_only_exposure_order(self) -> None:
        root = object()
        selector = type(
            "Selector",
            (),
            {"select": lambda self, *_args: (root,), "last_trace": SelectionTrace()},
        )()
        scanner, exact_mask, settings = object(), object(), object()
        agent = type(
            "AgentDouble",
            (),
            {
                "beam": object(),
                "scanner": scanner,
                "exact_mask": exact_mask,
                "settings": settings,
                "mode": "B",
            },
        )()
        with patch(
            "tests.run_support_extreme_fusion_physics."
            "MemoizedStreamingRegretProxySelector",
            return_value=selector,
        ) as factory, patch(
            "tests.run_support_extreme_fusion_physics.SimState.from_current",
            return_value=object(),
        ):
            _install_b_planner(
                agent,
                requested_mode="B",
                resolved_mode="B",
                b_planner="memoized-stratified-maxrects-regret",
            )
            selected = agent.beam.choose_b(object(), tuple(object() for _ in range(40)), object(), 5.3)

        self.assertIs(selected, root)
        factory.assert_called_once_with(
            exact_mask,
            settings=settings,
            exposure_order=ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION,
        )
        self.assertIs(agent.beam._scanner, scanner)

    def test_maxrects_trace_is_serialized_after_successful_policy_call(self) -> None:
        root = object()

        class Selector:
            def __init__(self):
                self.last_trace = SelectionTrace()

            def select(self, sim, catalog, mode, deadline):
                del sim, catalog, mode, deadline
                self.last_trace = SelectionTrace(
                    root_lineages=((0, 6, 0, 0),),
                    nodes=48,
                    fit_tests=1_000,
                    candidates=320,
                    deepest=2,
                    predicted_count=2,
                    predicted_volume=0.125,
                    largest_free_region=0.253,
                    exposure_by_support_source=(("floor", 12), ("shelf", 4)),
                    exposure_by_orientation=((0, 8), (1, 8)),
                    zero_candidate_nodes=3,
                )
                return (root,)

        selector = Selector()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()
                self.mode = "B"

            def policy(self, observation):
                self.depth_copies.append(observation["depth_map"])
                self.beam.choose_b(object(), tuple(observation["pool_list"]), object(), 5.3)
                return self.actions[0]

        env = _FakeEnv([SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics.RegretProxySelector",
            return_value=selector,
        ), patch(
            "tests.run_support_extreme_fusion_physics.SimState.from_current",
            return_value=object(),
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                b_planner="maxrects-regret",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.2)),
            )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["b_planner"], "maxrects-regret")
        self.assertEqual(len(result["diagnostic"]["b_search_traces"]), 1)
        trace = result["diagnostic"]["b_search_traces"][0]
        self.assertEqual(trace["step"], 0)
        self.assertEqual(trace["nodes"], 48)
        self.assertEqual(trace["predicted_count"], 2)
        self.assertEqual(trace["largest_free_region"], 0.253)
        self.assertEqual(trace["exposure_by_support_source"], (("floor", 12), ("shelf", 4)))
        self.assertEqual(trace["exposure_by_orientation"], ((0, 8), (1, 8)))
        self.assertEqual(trace["zero_candidate_nodes"], 3)
        self.assertEqual(len(env.step_actions), 1)
        self.assertIs(env.step_actions[0], agent.actions[0])

    def test_stratified_streaming_trace_is_serialized_without_bypassing_policy(self) -> None:
        root = object()

        class Selector:
            def __init__(self):
                self.last_trace = SelectionTrace()

            def select(self, sim, catalog, mode, deadline):
                del sim, catalog, mode, deadline
                self.last_trace = SelectionTrace(
                    nodes=5,
                    candidates=6,
                    predicted_count=2,
                    exposure_by_support_source=(("floor", 5), ("shelf", 1)),
                    exposure_by_orientation=((0, 2), (1, 2), (2, 2)),
                    zero_candidate_nodes=4,
                )
                return (root,)

        selector = Selector()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()
                self.mode = "B"

            def policy(self, observation):
                self.depth_copies.append(observation["depth_map"])
                self.beam.choose_b(
                    object(), tuple(observation["pool_list"]), object(), 5.3
                )
                return self.actions[0]

        env = _FakeEnv([SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics."
            "MemoizedStreamingRegretProxySelector",
            return_value=selector,
        ), patch(
            "tests.run_support_extreme_fusion_physics.SimState.from_current",
            return_value=object(),
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                b_planner="memoized-stratified-maxrects-regret",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.2)),
            )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(
            result["b_planner"], "memoized-stratified-maxrects-regret"
        )
        self.assertEqual(
            result["b_planner_settings"],
            {
                "requested": "memoized-stratified-maxrects-regret",
                "effective": "memoized-stratified-maxrects-regret",
                "enabled": True,
            },
        )
        traces = result["diagnostic"]["b_search_traces"]
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["exposure_by_support_source"], (("floor", 5), ("shelf", 1)))
        self.assertEqual(traces[0]["exposure_by_orientation"], ((0, 2), (1, 2), (2, 2)))
        self.assertEqual(traces[0]["zero_candidate_nodes"], 4)
        self.assertEqual(len(env.step_actions), 1)
        self.assertIs(env.step_actions[0], agent.actions[0])

    def test_maxrects_exception_clears_previous_trace_and_never_relabels_it(self) -> None:
        root = object()

        class Selector:
            def __init__(self):
                self.calls = 0
                self.last_trace = SelectionTrace()

            def select(self, *_args):
                self.calls += 1
                if self.calls == 1:
                    self.last_trace = SelectionTrace(nodes=7, predicted_count=2)
                    return (root,)
                raise RuntimeError("synthetic selector failure")

        selector = Selector()
        agent = type(
            "AgentDouble",
            (),
            {
                "beam": object(),
                "scanner": object(),
                "exact_mask": object(),
                "settings": object(),
                "mode": "B",
            },
        )()
        with patch(
            "tests.run_support_extreme_fusion_physics.RegretProxySelector",
            return_value=selector,
        ), patch(
            "tests.run_support_extreme_fusion_physics.SimState.from_current",
            return_value=object(),
        ):
            _install_b_planner(
                agent,
                requested_mode="B",
                resolved_mode="B",
                b_planner="maxrects-regret",
            )
            self.assertIs(agent.beam.choose_b(object(), (object(),), object(), 5.3), root)
            with self.assertRaises(RuntimeError):
                agent.beam.choose_b(object(), (object(),), object(), 5.3)

        self.assertEqual(agent.beam._trace_revision, 2)
        self.assertIsNone(agent.beam._last_invoked_trace)

    def test_fixed_two_ply_trace_is_serialized_under_diagnostic(self) -> None:
        class Planner:
            def __init__(self):
                self.last_trace = BSearchTrace()

            def choose_b(self, state, pool, catalog, deadline):
                del state, pool, catalog, deadline
                self.last_trace = BSearchTrace(
                    stage1_edges=12,
                    admitted_items=6,
                    child_scans=8,
                    child_exact_attempts=31,
                    second_edges=9,
                    deepest_proven_count=2,
                )
                return object()

        planner = Planner()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()
                self.mode = "B"

            def policy(self, observation):
                self.depth_copies.append(observation["depth_map"])
                self.beam.choose_b(object(), tuple(observation["pool_list"]), object(), 5.30)
                return self.actions[0]

        env = _FakeEnv([SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics.FixedQuotaExactTwoPly",
            return_value=planner,
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                b_planner="fixed-two-ply",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.2)),
            )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["b_planner"], "fixed-two-ply")
        self.assertEqual(
            result["diagnostic"]["b_search_traces"],
            [
                {
                    "step": 0,
                    "stage1_edges": 12,
                    "admitted_items": 6,
                    "admitted_roots": 0,
                    "child_scans": 8,
                    "child_exact_attempts": 31,
                    "child_covered_occurrences": 0,
                    "second_edges": 9,
                    "deepest_proven_count": 2,
                    "deadline_reached": False,
                    "branch_exceptions": 0,
                }
            ],
        )

    def test_fixed_trace_is_omitted_when_deadline_incumbent_skips_choose_b(self) -> None:
        planner = type("Planner", (), {"last_trace": BSearchTrace()})()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()
                self.mode = "B"

        env = _FakeEnv([SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics.FixedQuotaExactTwoPly",
            return_value=planner,
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                b_planner="fixed-two-ply",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.1)),
            )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["diagnostic"]["b_search_traces"], [])

    def test_fixed_trace_survives_formatter_exception_after_choose_b(self) -> None:
        class Planner:
            def __init__(self):
                self.last_trace = BSearchTrace()

            def choose_b(self, *_args):
                self.last_trace = BSearchTrace(
                    stage1_edges=5,
                    child_scans=2,
                    deepest_proven_count=1,
                )
                return object()

        planner = Planner()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()
                self.mode = "B"

            def policy(self, observation):
                self.depth_copies.append(observation["depth_map"])
                self.beam.choose_b(object(), tuple(observation["pool_list"]), object(), 5.3)
                raise PlanningError("synthetic formatter failure")

        env = _FakeEnv([SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics.FixedQuotaExactTwoPly",
            return_value=planner,
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=1,
                seed=42,
                requested_mode="B",
                b_planner="fixed-two-ply",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.1)),
            )

        self.assertEqual(result["outcome"], "planning_error")
        self.assertEqual(len(result["diagnostic"]["b_search_traces"]), 1)
        self.assertEqual(result["diagnostic"]["b_search_traces"][0]["step"], 0)
        self.assertEqual(result["diagnostic"]["b_search_traces"][0]["stage1_edges"], 5)

    def test_fixed_planner_exception_does_not_relabel_previous_trace(self) -> None:
        class Planner:
            def __init__(self):
                self.last_trace = BSearchTrace()
                self.calls = 0

            def choose_b(self, *_args):
                self.calls += 1
                if self.calls == 1:
                    self.last_trace = BSearchTrace(
                        stage1_edges=7,
                        child_scans=3,
                        deepest_proven_count=1,
                    )
                    return object()
                raise RuntimeError("synthetic planner failure")

        planner = Planner()

        class AgentDouble(_FakeAgent):
            def __init__(self):
                super().__init__([_action(), _action()])
                self.scanner = object()
                self.exact_mask = object()
                self.settings = object()
                self.beam = object()
                self.mode = "B"

            def policy(self, observation):
                self.depth_copies.append(observation["depth_map"])
                self.beam.choose_b(object(), tuple(observation["pool_list"]), object(), 5.3)
                return self.actions[len(self.depth_copies) - 1]

        env = _FakeEnv([SAFE, SAFE])
        agent = AgentDouble()
        with patch(
            "tests.run_support_extreme_fusion_physics.FixedQuotaExactTwoPly",
            return_value=planner,
        ):
            result = run_episode(
                _raw_config(),
                task="001",
                requested_items=2,
                seed=42,
                requested_mode="B",
                b_planner="fixed-two-ply",
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.1, 1.0, 1.1)),
            )

        self.assertEqual(result["outcome"], "other_exception")
        self.assertEqual(
            [(trace["step"], trace["stage1_edges"]) for trace in result["diagnostic"]["b_search_traces"]],
            [(0, 7)],
        )

    def test_materialization_is_deep_and_mode_overrides_only_copy(self) -> None:
        source = {"001": _raw_config()}
        original = copy.deepcopy(source)
        b_config = materialize_config(source, "001", 2, "B")
        self.assertEqual(source, original)
        self.assertEqual(len(b_config["item_stream"]["item_list"]), 2)
        self.assertFalse(b_config["agent"]["optimize"])
        self.assertGreater(b_config["item_stream"]["look_ahead"], 1)
        self.assertFalse(b_config["visualizer"]["vis"])

        c_config = materialize_config(source, "001", 2, "C")
        self.assertFalse(c_config["agent"]["optimize"])
        self.assertEqual(c_config["item_stream"]["look_ahead"], 1)
        a_config = materialize_config(source, "001", 2, "A")
        self.assertTrue(a_config["agent"]["optimize"])

    def test_success_steps_once_per_action_and_records_official_fields(self) -> None:
        env = _FakeEnv([SAFE, SAFE])
        agent = _FakeAgent([_action(), _action()])
        result = run_episode(
            _raw_config(),
            task="001",
            requested_items=2,
            seed=23,
            requested_mode="B",
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
            clock=_SequenceClock((0.0, 0.5, 1.0, 2.0)),
        )
        self.assertEqual(result["outcome"], "success")
        self.assertTrue(result["all_safe"])
        self.assertEqual(result["completed_steps"], 2)
        self.assertEqual(result["safe_placements"], 2)
        self.assertEqual(result["final_packed_count"], 2)
        self.assertEqual(result["evaluation"]["fill_score"], 12.5)
        self.assertEqual(result["evaluation"]["num_placed_items"], 1.0)
        self.assertEqual(result["b_planner"], "beam")
        self.assertEqual(len(env.step_actions), 2)
        self.assertEqual(result["records"][0]["status"], SAFE)
        self.assertTrue(
            np.allclose(
                result["records"][0]["action"]["place_pos"],
                [0.0, 0.0, 0.2],
                rtol=0.0,
                atol=1e-7,
            )
        )
        self.assertTrue(env.reset_settings_called and env.reset_item_stream_called and env.closed)
        self.assertEqual(env.seed, 23)
        self.assertTrue(all(depth is not env.shm_depth_map for depth in agent.depth_copies))
        self.assertTrue(all(np.array_equal(depth, env.shm_depth_map) for depth in agent.depth_copies))

    def test_mode_a_runs_official_optimize_order_reset_flow_and_records_timing(self) -> None:
        env = _FakeEnv([SAFE, SAFE])
        agent = _FakeAgent([_action(), _action()])
        result = run_episode(
            _raw_config(),
            task="000",
            requested_items=2,
            seed=23,
            requested_mode="A",
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
            clock=_SequenceClock((10.0, 10.25, 11.0, 11.1, 12.0, 12.2)),
        )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["resolved_mode"], "A")
        self.assertEqual(result["optimized_order"], [1, 0])
        self.assertEqual(result["optimize_time_seconds"], 0.25)
        self.assertEqual(result["mode_a_plan_trace"], None)
        self.assertEqual(env.optimization_items_requested, 1)
        self.assertEqual(env.optimized_order, [1, 0])
        self.assertEqual(env.reset_item_stream_calls, 2)
        self.assertEqual([item["index"] for item in agent.optimize_inputs[0]], [0, 1])
        self.assertTrue(agent.init_state["optimize"])

    def test_mode_a_official_lifecycle_event_order_is_fixed(self) -> None:
        events = []

        class OrderedEnv(_FakeEnv):
            def reset_settings(self):
                events.append("reset_settings")
                return super().reset_settings()

            def reset_item_stream(self):
                events.append("reset_item_stream")
                return super().reset_item_stream()

            def get_init_states(self):
                events.append("get_init_states")
                return super().get_init_states()

            def get_info_for_optimization(self):
                events.append("get_info_for_optimization")
                return super().get_info_for_optimization()

            def set_item_order(self, order):
                events.append("set_item_order")
                return super().set_item_order(order)

            def reset(self, seed=None):
                events.append("reset")
                return super().reset(seed=seed)

        class OrderedAgent(_FakeAgent):
            def get_init_states(self, value):
                events.append("agent_get_init_states")
                return super().get_init_states(value)

            def optimize(self, item_list):
                events.append("optimize")
                return super().optimize(item_list)

        result = run_episode(
            _raw_config(),
            task="000",
            requested_items=1,
            seed=5,
            requested_mode="A",
            env_factory=lambda _config: OrderedEnv([SAFE]),
            agent_factory=lambda: OrderedAgent([_action()]),
            clock=_SequenceClock((0.0, 0.1, 1.0, 1.1)),
        )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(
            events[:9],
            [
                "reset_settings",
                "reset_item_stream",
                "get_init_states",
                "agent_get_init_states",
                "get_info_for_optimization",
                "optimize",
                "set_item_order",
                "reset_item_stream",
                "reset",
            ],
        )

    def test_episode_records_one_ply_without_changing_b_init_mode(self) -> None:
        class BeamDouble:
            def choose_c(self, *_args):
                return object()

        class BAgent(_FakeAgent):
            def __init__(self):
                super().__init__([_action()])
                self.mode = None
                self.beam = BeamDouble()

            def get_init_states(self, value):
                result = super().get_init_states(value)
                self.mode = "B" if value["lookahead_k"] > 1 else "C"
                return result

        env = _FakeEnv([SAFE])
        agent = BAgent()
        result = run_episode(
            _raw_config(),
            task="001",
            requested_items=1,
            seed=23,
            requested_mode="B",
            b_planner="one-ply",
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
            clock=_SequenceClock((0.0, 0.1)),
        )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["b_planner"], "one-ply")
        self.assertEqual(result["resolved_mode"], "B")
        self.assertEqual(agent.mode, "B")
        self.assertGreater(agent.init_state["lookahead_k"], 1)
        self.assertEqual(len(env.step_actions), 1)

    def test_physical_failure_stops_at_first_false_predicate(self) -> None:
        failed = {"is_included": True, "is_valid": False, "is_placed_safe": False}
        env = _FakeEnv([SAFE, failed, SAFE])
        agent = _FakeAgent([_action(), _action(), _action()])
        result = run_episode(
            _raw_config(), task="000", requested_items=3, seed=1, requested_mode="C",
            env_factory=lambda _config: env, agent_factory=lambda: agent,
            clock=_SequenceClock((0.0, 0.1, 1.0, 1.2)),
        )
        self.assertEqual(result["outcome"], "physical_failure")
        self.assertEqual(result["completed_steps"], 2)
        self.assertEqual(result["safe_placements"], 1)
        self.assertEqual(result["first_failure_step"], 1)
        self.assertEqual(result["first_failure_predicate"], "is_valid")
        self.assertEqual(result["first_failure_status"], failed)
        self.assertEqual(len(env.step_actions), 2)

    def test_policy_exception_categories_are_saved_without_step(self) -> None:
        cases = (
            (CandidateZeroError("zero"), "candidate_zero"),
            (PlanningError("plan"), "planning_error"),
            (NotReadyError("A"), "not_ready"),
            (RuntimeError("boom"), "other_exception"),
        )
        for error, expected in cases:
            with self.subTest(category=expected):
                env = _FakeEnv([SAFE])
                agent = _FakeAgent(error=error)
                result = run_episode(
                    _raw_config(), task="001", requested_items=1, seed=2,
                    requested_mode="A" if expected == "not_ready" else "B",
                    env_factory=lambda _config, env=env: env,
                    agent_factory=lambda agent=agent: agent,
                    clock=_SequenceClock(
                        (0.0, 0.1, 1.0, 1.25)
                        if expected == "not_ready"
                        else (0.0, 0.25)
                    ),
                )
                self.assertEqual(result["outcome"], expected)
                self.assertEqual(result["completed_steps"], 0)
                self.assertEqual(result["exception"]["type"], type(error).__name__)
                self.assertEqual(len(env.step_actions), 0)
                self.assertTrue(env.closed)

    def test_percentiles_are_literal_and_empty_safe(self) -> None:
        env = _FakeEnv([SAFE, SAFE, SAFE, SAFE])
        agent = _FakeAgent([_action(), _action(), _action(), _action()])
        result = run_episode(
            _raw_config(), task="001", requested_items=4, seed=3, requested_mode="B",
            env_factory=lambda _config: env, agent_factory=lambda: agent,
            clock=_SequenceClock((0.0, 1.0, 10.0, 12.0, 20.0, 23.0, 30.0, 34.0)),
        )
        timing = result["policy_time_seconds"]
        self.assertEqual(timing["count"], 4)
        self.assertAlmostEqual(timing["p50"], 2.5)
        self.assertAlmostEqual(timing["p95"], 3.85)
        self.assertAlmostEqual(timing["p99"], 3.97)
        self.assertAlmostEqual(timing["max"], 4.0)

        empty = run_episode(
            _raw_config(), task="001", requested_items=1, seed=3, requested_mode="B",
            env_factory=lambda _config: _FakeEnv([SAFE]),
            agent_factory=lambda: _FakeAgent(error=CandidateZeroError("zero")),
            clock=_SequenceClock((0.0, 0.0)),
        )["policy_time_seconds"]
        self.assertEqual(empty, {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0})

    def test_runner_rejects_bad_action_and_malformed_status(self) -> None:
        invalid_actions = (
            {**_action(), "item_idx": True},
            {**_action(), "place_pos": np.asarray((0.0, np.nan, 0.2))},
            {**_action(), "place_pos": np.asarray((0.0, 0.2))},
            {**_action(), "item_idx": 99},
            {**_action(), "container_idx": 99},
            {**_action(), "unexpected": "field"},
        )
        for action in invalid_actions:
            self.assertFalse(action_format_is_valid(action, _observation(1)))
        self.assertTrue(action_format_is_valid(_action(), _observation(1)))
        self.assertTrue(status_format_is_valid(SAFE))
        self.assertFalse(status_format_is_valid({"is_included": True}))
        self.assertFalse(status_format_is_valid({**SAFE, "is_valid": 1}))

        for action in invalid_actions:
            env = _FakeEnv([SAFE])
            result = run_episode(
                _raw_config(), task="001", requested_items=1, seed=4, requested_mode="C",
                env_factory=lambda _config, env=env: env,
                agent_factory=lambda action=action: _FakeAgent([action]),
                clock=_SequenceClock((0.0, 0.1)),
            )
            self.assertEqual(result["outcome"], "other_exception")
            self.assertEqual(result["completed_steps"], 0)
            self.assertEqual(len(env.step_actions), 0)

        malformed_env = _FakeEnv([{"is_included": True}])
        malformed = run_episode(
            _raw_config(), task="001", requested_items=1, seed=4, requested_mode="C",
            env_factory=lambda _config: malformed_env,
            agent_factory=lambda: _FakeAgent([_action()]),
            clock=_SequenceClock((0.0, 0.1)),
        )
        self.assertEqual(malformed["outcome"], "physical_failure")
        self.assertEqual(malformed["first_failure_predicate"], "malformed_status")
        self.assertFalse(malformed["records"][0]["status_well_formed"])

    def test_atomic_json_replaces_complete_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "nested" / "result.json"
            payload = {"status": "success", "records": [{"step": 0}]}
            with patch("tests.run_support_extreme_fusion_physics.os.replace", wraps=__import__("os").replace) as replace:
                atomic_write_json(target, payload)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
            self.assertEqual(replace.call_count, 1)
            source, destination = replace.call_args.args
            self.assertEqual(pathlib.Path(destination), target)
            self.assertEqual(pathlib.Path(source).parent, target.parent)
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_candidate_zero_saves_atomic_pre_policy_snapshot_and_hash(self) -> None:
        class _MutatingZeroAgent(_FakeAgent):
            def policy(self, observation):
                self.depth_copies.append(observation["depth_map"])
                observation["pool_list"].clear()
                raise CandidateZeroError("strict root zero")

        with tempfile.TemporaryDirectory() as directory:
            snapshot = pathlib.Path(directory) / "snapshots" / "candidate-zero.npz"
            env = _FakeEnv([SAFE])
            agent = _MutatingZeroAgent()
            real_replace = __import__("os").replace
            with patch(
                "tests.run_support_extreme_fusion_physics.os.replace", wraps=real_replace
            ) as replace:
                result = run_episode(
                    _raw_config(), task="001", requested_items=1, seed=42,
                    requested_mode="B", env_factory=lambda _config: env,
                    agent_factory=lambda: agent, clock=_SequenceClock((0.0, 0.1)),
                    snapshot_on_failure=snapshot,
                )
            self.assertEqual(result["outcome"], "candidate_zero")
            self.assertTrue(snapshot.is_file())
            self.assertEqual(replace.call_count, 1)
            source, destination = replace.call_args.args
            self.assertEqual(pathlib.Path(source).parent, snapshot.parent)
            self.assertEqual(pathlib.Path(destination), snapshot)
            expected_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            self.assertEqual(result["failure_snapshot"]["sha256"], expected_hash)
            self.assertEqual(result["failure_snapshot"]["path"], str(snapshot.resolve()))
            saved_observation, metadata = load_observation_snapshot(snapshot)
            self.assertEqual(len(saved_observation["pool_list"]), 1)
            self.assertTrue(np.array_equal(saved_observation["depth_map"], env.shm_depth_map))
            self.assertEqual(metadata["failure_kind"], "policy_exception")
            self.assertEqual(metadata["exception_type"], "CandidateZeroError")
            self.assertEqual(metadata["step"], 0)

    def test_physical_failure_saves_pre_action_snapshot_but_success_does_not(self) -> None:
        failed = {"is_included": True, "is_valid": False, "is_placed_safe": False}
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            failure_path = root / "physical.npz"
            env = _FakeEnv([SAFE, failed])
            result = run_episode(
                _raw_config(), task="001", requested_items=2, seed=7,
                requested_mode="B", env_factory=lambda _config: env,
                agent_factory=lambda: _FakeAgent([_action(), _action()]),
                clock=_SequenceClock((0.0, 0.1, 1.0, 1.1)),
                snapshot_on_failure=failure_path,
            )
            self.assertEqual(result["outcome"], "physical_failure")
            self.assertTrue(failure_path.is_file())
            saved_observation, metadata = load_observation_snapshot(failure_path)
            self.assertEqual(len(saved_observation["container_list"][0]["packed_items"]), 1)
            self.assertEqual(len(saved_observation["pool_list"]), 1)
            self.assertEqual(metadata["failure_kind"], "physical_failure")
            self.assertEqual(metadata["failed_predicate"], "is_valid")
            self.assertEqual(metadata["step"], 1)
            self.assertEqual(
                result["failure_snapshot"]["sha256"],
                hashlib.sha256(failure_path.read_bytes()).hexdigest(),
            )

            success_path = root / "success-must-not-exist.npz"
            success = run_episode(
                _raw_config(), task="001", requested_items=1, seed=7,
                requested_mode="C", env_factory=lambda _config: _FakeEnv([SAFE]),
                agent_factory=lambda: _FakeAgent([_action()]),
                clock=_SequenceClock((0.0, 0.1)),
                snapshot_on_failure=success_path,
            )
            self.assertEqual(success["outcome"], "success")
            self.assertIsNone(success["failure_snapshot"])
            self.assertFalse(success_path.exists())

    def test_early_termination_and_truncation_save_last_pre_action_snapshot(self) -> None:
        class _ForcedStopEnv(_FakeEnv):
            def __init__(self, *, truncated: bool) -> None:
                super().__init__([SAFE])
                self.force_truncated = truncated

            def step(self, action):
                observation, reward, _terminated, _truncated, info = super().step(action)
                return (
                    observation,
                    reward,
                    not self.force_truncated,
                    self.force_truncated,
                    info,
                )

        with tempfile.TemporaryDirectory() as directory:
            for truncated, predicate in ((False, "early_termination"), (True, "truncated")):
                with self.subTest(predicate=predicate):
                    snapshot = pathlib.Path(directory) / f"{predicate}.npz"
                    result = run_episode(
                        _raw_config(), task="001", requested_items=2, seed=9,
                        requested_mode="B",
                        env_factory=lambda _config, truncated=truncated: _ForcedStopEnv(
                            truncated=truncated
                        ),
                        agent_factory=lambda: _FakeAgent([_action()]),
                        clock=_SequenceClock((0.0, 0.1)),
                        snapshot_on_failure=snapshot,
                    )
                    self.assertEqual(result["outcome"], "physical_failure")
                    self.assertEqual(result["first_failure_predicate"], predicate)
                    self.assertEqual(result["first_failure_step"], 0)
                    self.assertTrue(snapshot.is_file())
                    saved_observation, metadata = load_observation_snapshot(snapshot)
                    self.assertEqual(len(saved_observation["pool_list"]), 1)
                    self.assertEqual(metadata["failure_kind"], "physical_failure")
                    self.assertEqual(metadata["failed_predicate"], predicate)
                    self.assertEqual(metadata["step"], 0)


if __name__ == "__main__":
    unittest.main()
