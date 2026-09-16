from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import time
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from tests.replay_support import load_observation_snapshot  # noqa: E402
from tests.run_historical_conservative_extreme_point_physics import (  # noqa: E402
    ALGORITHM_NAME,
    ARTIFACT_AGENT_PATH,
    ARTIFACT_PACKAGE_PATH,
    ARTIFACT_SOURCE_SHA256,
    artifact_metadata,
    build_parser,
    capture_artifact_snapshot,
    load_historical_agent_type,
    run_historical_episode,
    write_result_atomic,
)
from tests.test_run_support_extreme_fusion_physics import (  # noqa: E402
    SAFE,
    _SequenceClock,
    _action,
    _observation,
    _raw_config,
)


class _LifecycleEnv:
    def __init__(self, events, statuses) -> None:
        self.events = events
        self.statuses = tuple(dict(status) for status in statuses)
        self.observation = _observation(len(statuses))
        self.shm_depth_map = np.arange(16, dtype=np.float32).reshape(1, 4, 4)
        self.step_count = 0
        self.optimized_order = None

    def reset_settings(self):
        self.events.append("reset_settings")

    def reset_item_stream(self):
        self.events.append("reset_item_stream")

    def get_init_states(self):
        self.events.append("get_init_states")
        return {
            "optimize": False,
            "lookahead_k": 10,
            "container_list": copy.deepcopy(self.observation["container_list"]),
        }

    def get_info_for_optimization(self):
        self.events.append("get_info_for_optimization")
        return copy.deepcopy(self.observation["pool_list"])

    def set_item_order(self, order):
        self.events.append("set_item_order")
        expected = [item["index"] for item in self.observation["pool_list"]]
        if sorted(order) != sorted(expected):
            return False
        by_index = {item["index"]: item for item in self.observation["pool_list"]}
        self.observation["pool_list"] = [by_index[index] for index in order]
        self.optimized_order = list(order)
        return True

    def reset(self, seed=None):
        self.events.append(("reset", seed))
        return copy.deepcopy(self.observation), {}

    def step(self, action):
        self.events.append("step")
        status = self.statuses[self.step_count]
        self.step_count += 1
        if status == SAFE:
            selected = self.observation["pool_list"].pop(action["item_idx"])
            self.observation["container_list"][0]["packed_items"].append(selected)
        terminated = self.step_count >= len(self.statuses)
        return copy.deepcopy(self.observation), 0.0, terminated, False, {"status": status}

    def evaluate(self):
        self.events.append("evaluate")
        return {"fill_score": 1.25, "num_placed_items": 1.0}

    def close(self):
        self.events.append("close")


class _LifecycleAgent:
    def __init__(self, events, *, action=None, policy_error=None) -> None:
        self.events = events
        self.action = _action() if action is None else action
        self.policy_error = policy_error

    def get_init_states(self, state):
        self.events.append(("agent_init", bool(state["optimize"])))
        return True

    def optimize(self, items):
        self.events.append("optimize")
        return [int(item["index"]) for item in reversed(items)]

    def policy(self, observation):
        self.events.append("policy")
        if self.policy_error is not None:
            raise self.policy_error
        return self.action


class HistoricalConservativeExtremePointRunnerTests(unittest.TestCase):
    @staticmethod
    def _fixture_agent(directory, *, init_body="return True", optimize_body=None,
                       policy_body=None):
        if optimize_body is None:
            optimize_body = "return [int(item['index']) for item in item_list]"
        if policy_body is None:
            policy_body = (
                "return {'item_idx': 0, 'container_idx': 0, "
                "'place_pos': np.asarray((0.0, 0.0, 0.2), dtype=np.float32), "
                "'orientation': 0}"
            )
        source = (
            "import numpy as np\n"
            "import pathlib\n"
            "import time\n"
            "class Agent:\n"
            "    def __init__(self, module_path):\n"
            "        self.module_path = module_path\n"
            "    def get_init_states(self, init_states):\n"
            f"        {init_body}\n"
            "    def optimize(self, item_list):\n"
            f"        {optimize_body}\n"
            "    def policy(self, observation):\n"
            f"        {policy_body}\n"
        )
        package = pathlib.Path(directory) / "historical_fixture"
        package.mkdir()
        path = package / "agent.py"
        path.write_text(source, encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        return path, digest

    @staticmethod
    def _timeout_config(*, init=8.0, optimization=8.0, policy=8.0):
        config = _raw_config()
        config["agent"] = {
            "optimize": True,
            "init_timeout": init,
            "optimization_timeout": optimization,
            "policy_timeout": policy,
        }
        return config

    def test_parser_is_fixed_to_task000_mode_a_control(self):
        args = build_parser().parse_args(["--output", "result.json"])
        self.assertEqual(args.task, "000")
        self.assertEqual(args.items, 41)
        self.assertEqual(args.seed, 42)
        self.assertEqual(args.output, pathlib.Path("result.json"))
        self.assertEqual(ALGORITHM_NAME, "conservative_extreme_point_packing_historical_control")

    def test_loader_is_isolated_and_verifies_untouched_public_interface(self):
        expected = hashlib.sha256(ARTIFACT_AGENT_PATH.read_bytes()).hexdigest().upper()
        self.assertEqual(expected, ARTIFACT_SOURCE_SHA256)
        prior_agent_module = sys.modules.get("agent")
        agent_type = load_historical_agent_type()
        self.assertEqual(sys.modules.get("agent"), prior_agent_module)
        self.assertNotIn(agent_type.__module__, sys.modules)
        instance = agent_type(str(ARTIFACT_PACKAGE_PATH))
        for name in ("get_init_states", "optimize", "policy"):
            self.assertTrue(callable(getattr(instance, name)))
        metadata = artifact_metadata()
        self.assertEqual(metadata["algorithm_name"], ALGORITHM_NAME)
        self.assertEqual(metadata["source_sha256"], ARTIFACT_SOURCE_SHA256)
        self.assertEqual(metadata["package_path"], ARTIFACT_PACKAGE_PATH.as_posix())
        self.assertEqual(metadata["agent_path"], ARTIFACT_AGENT_PATH.as_posix())
        self.assertTrue(metadata["historical_source_untouched"])

    def test_loader_uses_exact_source_bytes_and_ignores_existing_misleading_pyc(self):
        with tempfile.TemporaryDirectory() as directory:
            source, digest = self._fixture_agent(
                directory,
                policy_body="return {'marker': 'source-bytes'}",
            )
            pycache = source.parent / "__pycache__"
            pycache.mkdir()
            misleading = pycache / "agent.cpython-312.pyc"
            misleading.write_bytes(b"not a real pyc and must never be read")
            before = capture_artifact_snapshot(source, digest)
            agent_type = load_historical_agent_type(source, digest)
            agent = agent_type(str(source.parent))
            self.assertEqual(agent.policy({}), {"marker": "source-bytes"})
            after = capture_artifact_snapshot(source, digest)
            self.assertEqual(before.manifest, after.manifest)
            self.assertEqual(
                tuple(sorted(path.relative_to(source.parent).as_posix()
                             for path in source.parent.rglob("*"))),
                ("__pycache__", "__pycache__/agent.cpython-312.pyc", "agent.py"),
            )

    def test_init_optimization_and_policy_timeouts_stop_worker_and_physics(self):
        cases = (
            ("init", "time.sleep(0.25); return True", None, None),
            ("optimization", "return True", "while True: time.sleep(1.0)", None),
            ("policy", "return True", None, "time.sleep(0.25); return {'item_idx': 0}"),
        )
        for stage, init_body, optimize_body, policy_body in cases:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                source, digest = self._fixture_agent(
                    directory,
                    init_body=init_body,
                    optimize_body=optimize_body,
                    policy_body=policy_body,
                )
                events = []
                env = _LifecycleEnv(events, [SAFE])
                snapshot = pathlib.Path(directory) / f"{stage}.npz"
                started = time.perf_counter()
                result = run_historical_episode(
                    self._timeout_config(
                        init=0.05 if stage == "init" else 8.0,
                        optimization=0.05 if stage == "optimization" else 8.0,
                        policy=0.05 if stage == "policy" else 8.0,
                    ),
                    requested_items=1,
                    seed=42,
                    env_factory=lambda _config, env=env: env,
                    artifact_agent_path=source,
                    expected_source_sha256=digest,
                    snapshot_on_failure=snapshot,
                )
                self.assertLess(time.perf_counter() - started, 12.0)
                self.assertEqual(result["outcome"], f"{stage}_timeout")
                self.assertEqual(result["exception"]["category"], f"{stage}_timeout")
                self.assertEqual(result["historical_worker"]["timeout_stage"], stage)
                self.assertTrue(result["historical_worker"]["closed"])
                self.assertNotIn("step", events)
                self.assertTrue(snapshot.is_file())
                _observation_value, metadata = load_observation_snapshot(snapshot)
                self.assertEqual(metadata["failure_kind"], "agent_timeout")
                self.assertEqual(metadata["timeout_stage"], stage)

    def test_worker_exception_is_bounded_and_never_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            source, digest = self._fixture_agent(
                directory,
                policy_body="raise ValueError('fixture policy failure')",
            )
            events = []
            env = _LifecycleEnv(events, [SAFE])
            started = time.perf_counter()
            result = run_historical_episode(
                self._timeout_config(),
                requested_items=1,
                seed=42,
                env_factory=lambda _config: env,
                artifact_agent_path=source,
                expected_source_sha256=digest,
            )
            self.assertLess(time.perf_counter() - started, 2.0)
            self.assertEqual(result["outcome"], "other_exception")
            self.assertEqual(result["exception"]["type"], "HistoricalWorkerError")
            self.assertTrue(result["historical_worker"]["closed"])
            self.assertNotIn("step", events)

    def test_source_or_artifact_file_mutation_is_rejected_before_step(self):
        mutations = (
            "pathlib.Path(__file__).write_text('mutated', encoding='utf-8')",
            "(pathlib.Path(__file__).parent / 'new-file.txt').write_text('new')",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                policy = (
                    f"{mutation}; return {{'item_idx': 0, 'container_idx': 0, "
                    "'place_pos': np.asarray((0.0, 0.0, 0.2), dtype=np.float32), "
                    "'orientation': 0}"
                )
                source, digest = self._fixture_agent(directory, policy_body=policy)
                events = []
                env = _LifecycleEnv(events, [SAFE])
                result = run_historical_episode(
                    self._timeout_config(),
                    requested_items=1,
                    seed=42,
                    env_factory=lambda _config, env=env: env,
                    artifact_agent_path=source,
                    expected_source_sha256=digest,
                )
                self.assertEqual(result["outcome"], "artifact_mutation")
                self.assertEqual(
                    result["exception"]["type"], "HistoricalArtifactMutationError"
                )
                self.assertFalse(
                    result["historical_artifact"]["historical_source_untouched"]
                )
                self.assertFalse(result["historical_artifact_integrity"]["unchanged"])
                self.assertNotIn("step", events)

    def test_official_mode_a_lifecycle_and_timing_are_preserved(self):
        events = []
        env = _LifecycleEnv(events, [SAFE, SAFE])
        agent = _LifecycleAgent(events)
        result = run_historical_episode(
            _raw_config(),
            requested_items=2,
            seed=42,
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
            clock=_SequenceClock((0.0, 0.25, 1.0, 1.1, 2.0, 2.2)),
        )
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["optimized_order"], [1, 0])
        self.assertAlmostEqual(result["optimize_time_seconds"], 0.25)
        self.assertAlmostEqual(result["policy_time_seconds"]["max"], 0.2)
        optimize_at = events.index("optimize")
        set_at = events.index("set_item_order")
        reset_stream_at = events.index("reset_item_stream", set_at)
        reset_at = events.index(("reset", 42))
        self.assertLess(optimize_at, set_at)
        self.assertLess(set_at, reset_stream_at)
        self.assertLess(reset_stream_at, reset_at)
        self.assertEqual(result["agent_module"], "historical_file_isolated")
        self.assertEqual(result["algorithm_name"], ALGORITHM_NAME)
        self.assertEqual(result["historical_artifact"], artifact_metadata())

    def test_policy_exception_saves_compatible_atomic_snapshot(self):
        events = []
        env = _LifecycleEnv(events, [SAFE])
        agent = _LifecycleAgent(events, policy_error=RuntimeError("historical boom"))
        with tempfile.TemporaryDirectory() as directory:
            snapshot = pathlib.Path(directory) / "failure.npz"
            result = run_historical_episode(
                _raw_config(),
                requested_items=1,
                seed=42,
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                clock=_SequenceClock((0.0, 0.1, 1.0, 1.2)),
                snapshot_on_failure=snapshot,
            )
            self.assertEqual(result["outcome"], "other_exception")
            self.assertEqual(result["exception"]["type"], "RuntimeError")
            self.assertTrue(snapshot.is_file())
            observation, metadata = load_observation_snapshot(snapshot)
            self.assertIn("depth_map", observation)
            self.assertEqual(metadata["failure_kind"], "policy_exception")
            self.assertEqual(result["failure_snapshot"]["path"], str(snapshot.resolve()))
            self.assertEqual(len(result["failure_snapshot"]["sha256"]), 64)

    def test_malformed_historical_action_never_reaches_physics(self):
        events = []
        env = _LifecycleEnv(events, [SAFE])
        malformed = {**_action(), "item_idx": 9}
        agent = _LifecycleAgent(events, action=malformed)
        result = run_historical_episode(
            _raw_config(),
            requested_items=1,
            seed=42,
            env_factory=lambda _config: env,
            agent_factory=lambda: agent,
            clock=_SequenceClock((0.0, 0.1, 1.0, 1.1)),
        )
        self.assertEqual(result["outcome"], "other_exception")
        self.assertEqual(result["exception"]["type"], "ActionFormatError")
        self.assertNotIn("step", events)

    def test_json_materialization_is_atomic_and_records_artifact(self):
        payload = {
            "algorithm_name": ALGORITHM_NAME,
            "historical_artifact": artifact_metadata(),
            "outcome": "success",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "nested" / "result.json"
            write_result_atomic(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
