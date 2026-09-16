from __future__ import annotations

import copy
from collections import Counter
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    HISTORICAL_CONTROL_ALGORITHM,
    HISTORICAL_CONTROL_SOURCE_SHA256,
    _a_order_source_settings,
    _load_historical_control_order,
    build_parser,
    run_episode,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.agent import Agent  # noqa: E402


HISTORICAL_JSON = (
    SIMULATOR_ROOT
    / "results"
    / "support_extreme_fusion"
    / "task000-a-historical-conservative-extreme-point-control-seed42.json"
)
SAFE = {"is_included": True, "is_valid": True, "is_placed_safe": True}


def _sample_items():
    with (SIMULATOR_ROOT / "configs" / "sample_config.json").open(
        encoding="utf-8"
    ) as stream:
        return copy.deepcopy(json.load(stream)["000"]["item_stream"]["item_list"])


class _OrderEnv:
    def __init__(self, items):
        self.items = copy.deepcopy(items)
        self.events = []
        self.shm_depth_map = np.zeros((1, 4, 4), dtype=np.float32)
        self.observation = {
            "container_list": [{"index": 0, "packed_items": []}],
            "pool_list": copy.deepcopy(items),
        }
        self.optimized_order = None

    def reset_settings(self):
        self.events.append("reset_settings")

    def reset_item_stream(self):
        self.events.append("reset_item_stream")

    def get_init_states(self):
        return {
            "optimize": False,
            "lookahead_k": 1,
            "container_list": copy.deepcopy(self.observation["container_list"]),
        }

    def get_info_for_optimization(self):
        self.events.append("get_info_for_optimization")
        return copy.deepcopy(self.items)

    def set_item_order(self, order):
        self.events.append("set_item_order")
        if Counter(order) != Counter(item["index"] for item in self.items):
            return False
        by_index = {item["index"]: item for item in self.items}
        self.observation["pool_list"] = [copy.deepcopy(by_index[index]) for index in order]
        self.optimized_order = list(order)
        return True

    def reset(self, seed=None):
        self.events.append(("reset", seed))
        return copy.deepcopy(self.observation), {}

    def step(self, action):
        self.events.append("step")
        return copy.deepcopy(self.observation), 0.0, True, False, {"status": SAFE}

    def evaluate(self):
        return {"fill_score": 0.0, "num_placed_items": 0.0}

    def close(self):
        self.events.append("close")


class _OrderAgent:
    def __init__(self):
        self.settings = SearchSettings()
        self.mode_a_plan = object()
        self.mode_a_order_fallback_trace = {"selected_depth": 99, "seed_lane": 99}
        self.optimize_calls = 0

    def get_init_states(self, _state):
        return True

    def optimize(self, _items):
        self.optimize_calls += 1
        raise AssertionError("historical order source must bypass current optimize")

    def policy(self, _observation):
        return {
            "item_idx": 0,
            "container_idx": 0,
            "place_pos": np.asarray((0.0, 0.0, 0.2), dtype=np.float32),
            "orientation": 0,
        }


class HistoricalControlOrderSourceTests(unittest.TestCase):
    def test_parser_default_and_explicit_route(self):
        parser = build_parser()
        default = parser.parse_args(
            ["--task", "000", "--mode", "A", "--output", "result.json"]
        )
        self.assertEqual(default.a_order_source, "agent")
        self.assertIsNone(default.a_order_json)
        explicit = parser.parse_args(
            [
                "--task", "000", "--mode", "A",
                "--a-order-source", "historical-control-json",
                "--a-order-json", str(HISTORICAL_JSON),
                "--output", "result.json",
            ]
        )
        self.assertEqual(explicit.a_order_source, "historical-control-json")
        self.assertEqual(explicit.a_order_json, HISTORICAL_JSON)

    def test_real_control_json_is_exact_immutable_order_evidence(self):
        items = _sample_items()
        expected = [int(item["index"]) for item in items]
        order, metadata = _load_historical_control_order(
            HISTORICAL_JSON,
            expected_order=expected,
            task="000",
            requested_items=41,
            seed=42,
        )
        self.assertEqual(order[:10], [3, 5, 17, 21, 9, 11, 33, 19, 20, 22])
        self.assertEqual(Counter(order), Counter(expected))
        self.assertEqual(metadata["algorithm_name"], HISTORICAL_CONTROL_ALGORITHM)
        self.assertEqual(metadata["artifact_source_sha256"], HISTORICAL_CONTROL_SOURCE_SHA256)
        self.assertEqual(
            metadata["order_file_sha256"],
            hashlib.sha256(HISTORICAL_JSON.read_bytes()).hexdigest().upper(),
        )

    def test_validation_rejects_outside_path_and_every_authority_mismatch(self):
        original = json.loads(HISTORICAL_JSON.read_bytes())
        items = _sample_items()
        expected = [int(item["index"]) for item in items]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            outside = root.parent / "outside-order.json"
            outside.write_text(json.dumps(original), encoding="utf-8")
            try:
                with self.assertRaises(ValueError):
                    _load_historical_control_order(
                        outside,
                        expected_order=expected,
                        task="000",
                        requested_items=41,
                        seed=42,
                        results_root=root,
                    )
            finally:
                outside.unlink(missing_ok=True)

            mutations = (
                ("task", "001"),
                ("requested_items", 40),
                ("effective_items", 40),
                ("seed", 7),
                ("algorithm_name", "wrong"),
            )
            for key, value in mutations:
                with self.subTest(key=key):
                    payload = copy.deepcopy(original)
                    payload[key] = value
                    path = root / f"{key}.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        _load_historical_control_order(
                            path,
                            expected_order=expected,
                            task="000",
                            requested_items=41,
                            seed=42,
                            results_root=root,
                        )

            nested_mutations = (
                ("source", {**original["historical_artifact"], "source_sha256": "0" * 64}),
                ("untouched", {**original["historical_artifact"], "historical_source_untouched": False}),
            )
            for name, artifact in nested_mutations:
                payload = copy.deepcopy(original)
                payload["historical_artifact"] = artifact
                path = root / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _load_historical_control_order(
                        path, expected_order=expected, task="000",
                        requested_items=41, seed=42, results_root=root,
                    )

            for name, order in (
                ("bool", [True] + original["optimized_order"][1:]),
                ("missing", original["optimized_order"][:-1]),
                ("duplicate", original["optimized_order"][:-1] + [original["optimized_order"][0]]),
            ):
                payload = copy.deepcopy(original)
                payload["optimized_order"] = order
                path = root / f"order-{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _load_historical_control_order(
                        path, expected_order=expected, task="000",
                        requested_items=41, seed=42, results_root=root,
                    )

    def test_explicit_a_replaces_only_order_and_clears_plan(self):
        items = _sample_items()
        config = {
            "agent": {"optimize": True},
            "item_stream": {"look_ahead": 1, "item_list": copy.deepcopy(items)},
        }
        env = _OrderEnv(items)
        agent = _OrderAgent()
        result = run_episode(
            config,
            task="000",
            requested_items=41,
            seed=42,
            requested_mode="A",
            a_order_source="historical-control-json",
            a_order_json=HISTORICAL_JSON,
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
        )
        evidence = json.loads(HISTORICAL_JSON.read_bytes())
        self.assertEqual(result["optimized_order"], evidence["optimized_order"])
        self.assertEqual(env.optimized_order, evidence["optimized_order"])
        self.assertEqual(result["optimized_order"][0], 3)
        self.assertEqual(items[0]["index"], 0)
        self.assertEqual(agent.optimize_calls, 0)
        self.assertIsNone(agent.mode_a_plan)
        self.assertIsNone(agent.mode_a_order_fallback_trace)
        self.assertTrue(result["a_order_source_settings"]["enabled"])
        self.assertEqual(
            result["a_order_source_settings"]["order_file_sha256"],
            hashlib.sha256(HISTORICAL_JSON.read_bytes()).hexdigest().upper(),
        )

    def test_invalid_explicit_a_fails_before_reset_or_physics(self):
        items = _sample_items()
        config = {
            "agent": {"optimize": True},
            "item_stream": {"look_ahead": 1, "item_list": copy.deepcopy(items)},
        }
        env = _OrderEnv(items)
        agent = _OrderAgent()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            payload = json.loads(HISTORICAL_JSON.read_bytes())
            payload["seed"] = 99
            invalid = root / "invalid.json"
            invalid.write_text(json.dumps(payload), encoding="utf-8")
            result = run_episode(
                config,
                task="000",
                requested_items=41,
                seed=42,
                requested_mode="A",
                a_order_source="historical-control-json",
                a_order_json=invalid,
                a_order_results_root=root,
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
            )
        self.assertEqual(result["outcome"], "other_exception")
        self.assertEqual(result["exception"]["type"], "ValueError")
        self.assertNotIn("set_item_order", env.events)
        self.assertNotIn(("reset", 42), env.events)
        self.assertNotIn("step", env.events)

    def test_non_explicit_a_routes_ignore_order_json_and_keep_metadata_disabled(self):
        settings = _a_order_source_settings(
            "historical-control-json", str(HISTORICAL_JSON), effective=False
        )
        self.assertEqual(settings["requested"], "historical-control-json")
        self.assertEqual(settings["effective"], "agent")
        self.assertFalse(settings["enabled"])
        self.assertNotIn("order_file_sha256", settings)

    def test_adaptive_dense_install_is_independent_from_historical_order(self):
        items = _sample_items()
        config = {
            "agent": {"optimize": True},
            "item_stream": {"look_ahead": 1, "item_list": copy.deepcopy(items)},
        }
        env = _OrderEnv(items)
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.optimize = lambda _items: self.fail("current optimizer must be bypassed")
        agent.policy = lambda _observation: {
            "item_idx": 0,
            "container_idx": 0,
            "place_pos": np.asarray((0.0, 0.0, 0.2), dtype=np.float32),
            "orientation": 0,
        }
        result = run_episode(
            config,
            task="000",
            requested_items=41,
            seed=42,
            requested_mode="A",
            a_candidate_rescue="global-zero-adaptive-dense-12288",
            a_order_source="historical-control-json",
            a_order_json=HISTORICAL_JSON,
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
        )
        self.assertTrue(result["a_order_source_settings"]["enabled"])
        self.assertTrue(result["a_candidate_rescue_settings"]["enabled"])
        self.assertIsNone(agent.mode_a_plan)
        self.assertIsNone(agent.mode_a_order_fallback_trace)


if __name__ == "__main__":
    unittest.main()
