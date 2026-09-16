from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

try:
    from tests.run_step14_forensics import (  # noqa: E402
        action_sequence_hash,
        atomic_write_json,
        compare_action_sequences,
        classify_failure,
        first_action_divergence,
        _invoke_diagnostic,
        _stable_candidate_key,
        action_format_is_valid,
        RouteCapture,
        run_forensic_episode,
        run_three_mode_task,
        main as forensic_main,
        status_is_safe,
    )
except ModuleNotFoundError:
    from run_step14_forensics import (  # type: ignore  # noqa: E402
        action_sequence_hash,
        atomic_write_json,
        compare_action_sequences,
        classify_failure,
        first_action_divergence,
        _invoke_diagnostic,
        _stable_candidate_key,
        action_format_is_valid,
        RouteCapture,
        run_forensic_episode,
        run_three_mode_task,
        main as forensic_main,
        status_is_safe,
    )


class _FakeEnv:
    def __init__(self, events: list[dict] | None = None) -> None:
        self.events = list(events or [{"is_included": True, "is_valid": True, "is_placed_safe": True}])
        self.step_calls: list[dict] = []
        self.order: list[str] = []
        self.closed = False
        self.shm_depth_map = None

    def reset_settings(self) -> None:
        self.order.append("reset_settings")

    def reset_item_stream(self) -> None:
        self.order.append("reset_item_stream")

    def get_init_states(self) -> dict:
        self.order.append("get_init_states")
        return {"lookahead_k": 1, "container_list": []}

    def reset(self, seed: int | None = None):
        self.order.append("reset")
        return ({"pool_list": [{"index": 10}], "container_list": []}, {})

    def step(self, action: dict):
        self.order.append("step")
        self.step_calls.append(copy.deepcopy(action))
        status = self.events.pop(0) if self.events else {"is_included": True, "is_valid": True, "is_placed_safe": True}
        terminated = not self.events
        return ({"pool_list": [{"index": 10}], "container_list": []}, 0.0, terminated, False, {"status": status})

    def close(self) -> None:
        self.closed = True
        self.order.append("close")


class _FakePlanner:
    def choose_mpc(self, state, pool, *, deadline, seed):
        return None


class _FakeAgent:
    def __init__(self) -> None:
        self.planner = _FakePlanner()
        self.settings = SimpleNamespace()
        self.calls: list[str] = []

    def get_init_states(self, value):
        self.calls.append("get_init_states")
        return True

    def _depth_aware_emergency(self, state, pool, deadline):
        self.calls.append("emergency")
        return None

    def _deterministic_last_resort(self, observation, pool):
        self.calls.append("last_resort")
        return {
            "item_idx": 0,
            "container_idx": 0,
            "place_pos": np.asarray([0.0, 0.0, 0.0], dtype=np.float32),
            "orientation": 0,
        }

    def policy(self, observation):
        self.calls.append("policy")
        return self._deterministic_last_resort(observation, observation.get("pool_list", []))


class Step14ForensicsTests(unittest.TestCase):
    def test_action_format_requires_exact_shape_finite_values_and_integer_indices(self) -> None:
        valid = {
            "item_idx": 0,
            "container_idx": np.int64(1),
            "place_pos": np.asarray([0.0, 0.2, 0.3], dtype=np.float32),
            "orientation": 5,
        }
        self.assertTrue(action_format_is_valid(valid))
        for invalid in (
            {**valid, "item_idx": 0.0},
            {**valid, "orientation": True},
            {**valid, "place_pos": np.asarray([[0.0, 0.2, 0.3]])},
            {**valid, "place_pos": np.asarray([0.0, np.nan, 0.3])},
            {**valid, "place_pos": np.asarray([0.0, np.inf, 0.3])},
        ):
            self.assertFalse(action_format_is_valid(invalid), invalid)

    def test_action_hash_is_order_stable_and_divergence_reports_first_step(self) -> None:
        first = [
            {"item_idx": 0, "container_idx": 0, "place_pos": [1.0, 2.0, 3.0], "orientation": 0},
            {"item_idx": 1, "container_idx": 0, "place_pos": [1.0, 2.0, 3.0], "orientation": 1},
        ]
        second = copy.deepcopy(first)
        second[1]["orientation"] = 2
        self.assertEqual(action_sequence_hash(first), action_sequence_hash(copy.deepcopy(first)))
        comparison = compare_action_sequences(first, second)
        self.assertEqual(comparison["first_divergent_step"], 1)
        self.assertEqual(first_action_divergence(first, second), 1)
        self.assertNotEqual(comparison["left_hash"], comparison["right_hash"])

    def test_missing_status_predicates_are_not_treated_as_safe(self) -> None:
        self.assertFalse(status_is_safe({}))
        self.assertFalse(status_is_safe({"is_included": True, "is_valid": True}))
        self.assertTrue(status_is_safe({
            "is_included": True,
            "is_valid": True,
            "is_placed_safe": True,
            "unrelated_diagnostic": False,
        }))
        result = {
            "first_failure_step": 0,
            "records": [{
                "action": {"item_idx": 0, "container_idx": 0, "place_pos": [0.0, 0.0, 0.0], "orientation": 0},
                "action_format_valid": True,
                "route": "unknown",
                "status": {"is_included": True, "is_valid": True, "is_placed_safe": None},
                "status_format_valid": False,
            }],
        }
        self.assertEqual(classify_failure(result), "format_failure")

    def test_diagnostic_signature_is_inspected_and_internal_type_error_is_not_retried(self) -> None:
        calls = []

        def diagnose(observation, *, observation_id, phase):
            calls.append((observation_id, phase))
            raise TypeError("inside callback")

        with self.assertRaisesRegex(TypeError, "inside callback"):
            _invoke_diagnostic(diagnose, {}, observation_id="x", phase="trace")
        self.assertEqual(calls, [("x", "trace")])

    def test_stable_candidate_key_does_not_use_runtime_object_identity(self) -> None:
        def candidate():
            return SimpleNamespace(
                pool_index=2,
                container_index=1,
                orientation=3,
                position=(0.1, 0.2, 0.3),
                item=SimpleNamespace(index=17),
                box=SimpleNamespace(minimum=np.asarray([0.0, 0.1, 0.2]), maximum=np.asarray([0.2, 0.3, 0.4])),
            )

        self.assertEqual(_stable_candidate_key(candidate()), _stable_candidate_key(candidate()))

    def test_shadow_route_capture_restores_live_planner_alias(self) -> None:
        import agents.highscore.planner as planner_module

        original = planner_module.build_root_catalog
        agent = _FakeAgent()
        with RouteCapture(agent):
            self.assertIsNot(planner_module.build_root_catalog, original)
        self.assertIs(planner_module.build_root_catalog, original)
        self.assertNotIn("choose_mpc", agent.planner.__dict__)

    def test_shadow_route_capture_rolls_back_when_instance_wrapper_install_fails(self) -> None:
        import agents.highscore.planner as planner_module

        class FailingAgent(_FakeAgent):
            fail_install = False

            def __setattr__(self, name, value):
                if name == "_depth_aware_emergency" and getattr(self, "fail_install", False):
                    raise RuntimeError("fixture install failure")
                super().__setattr__(name, value)

        original = planner_module.build_root_catalog
        agent = FailingAgent()
        agent.fail_install = True
        with self.assertRaisesRegex(RuntimeError, "fixture install failure"):
            RouteCapture(agent).__enter__()
        self.assertIs(planner_module.build_root_catalog, original)
        self.assertNotIn("choose_mpc", agent.planner.__dict__)
        self.assertNotIn("_deterministic_last_resort", agent.__dict__)

    def test_false_status_writes_partial_json_and_diagnostics_run_after_step_on_copy(self) -> None:
        env = _FakeEnv([
            {"is_included": True, "is_valid": False, "is_placed_safe": False},
        ])
        agent = _FakeAgent()
        order: list[str] = []
        seen: list[dict] = []

        def diagnose(observation, *, observation_id, phase):
            order.append("diagnose")
            self.assertEqual(order[:2], ["step", "diagnose"])
            seen.append(copy.deepcopy(observation))
            observation["pool_list"].append({"index": 999})
            return {"observation_id": observation_id, "phase": phase, "rows": []}

        original_step = env.step

        def step(action):
            order.append("step")
            return original_step(action)

        env.step = step
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "control.json"
            result = run_forensic_episode(
                env,
                agent,
                mode="trace_probe",
                seed=42,
                output_path=output,
                snapshot_dir=root / "snapshots",
                diagnose_fn=diagnose,
                max_steps=3,
            )
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["first_failure_step"], 0)
            self.assertEqual(payload["records"][0]["status"], {
                "is_included": True,
                "is_valid": False,
                "is_placed_safe": False,
            })
            self.assertEqual(result["failure_classification"], "unchecked_last_resort_transport_defect")
            self.assertEqual(len(list((root / "snapshots").glob("*.npz"))), 1)
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[0]["pool_list"], [{"index": 10}])
            self.assertEqual(seen[1]["pool_list"], [{"index": 10}])

    def test_control_does_not_run_diagnostics_and_route_capture_marks_last_resort(self) -> None:
        env = _FakeEnv()
        agent = _FakeAgent()
        called = []
        with tempfile.TemporaryDirectory() as directory:
            result = run_forensic_episode(
                env,
                agent,
                mode="control",
                output_path=Path(directory) / "control.json",
                snapshot_dir=Path(directory) / "snapshots",
                diagnose_fn=lambda *args, **kwargs: called.append(True),
                max_steps=1,
            )
        self.assertFalse(called)
        self.assertEqual(result["records"][0]["route"], "deterministic_last_resort")
        self.assertEqual(result["records"][0]["route_provenance"], "diagnostic_shadow_replay")
        self.assertFalse(result["records"][0]["authoritative_candidate_present"])
        self.assertNotIn("_deterministic_last_resort", agent.__dict__)
        self.assertNotIn("choose_mpc", agent.planner.__dict__)
        self.assertFalse(result["records"][0]["post_policy_exact_validation"].get("pending", False))
        self.assertTrue(env.closed)

    def test_control_runs_shadow_validation_after_environment_close(self) -> None:
        env = _FakeEnv()
        agent = _FakeAgent()
        order = env.order

        def validate(observation, action, events, shadow_agent):
            order.append("validate")
            self.assertIn("close", order)
            return {"diagnostic_only": True, "checked": True, "accepted": False, "reason": "fixture"}

        with tempfile.TemporaryDirectory() as directory:
            result = run_forensic_episode(
                env,
                agent,
                mode="control",
                output_path=Path(directory) / "control.json",
                snapshot_dir=Path(directory) / "snapshots",
                shadow_validator=validate,
                max_steps=1,
            )
        self.assertEqual(result["records"][0]["post_policy_exact_validation"]["reason"], "fixture")
        self.assertEqual(result["env_step_calls"], 1)
        self.assertEqual(result["safe_placement_count"], 1)
        self.assertEqual(result["completed_steps"], 1)
        self.assertEqual(result["attempted_policy_records"], 1)
        self.assertEqual(result["final_packed_items"], 0)

    def test_physical_policy_is_unwrapped_in_every_arm_and_collision_stdout_is_recorded(self) -> None:
        class InspectingAgent(_FakeAgent):
            def policy(self, observation):
                self.assert_unwrapped()
                return super().policy(observation)

            def assert_unwrapped(self):
                if "_deterministic_last_resort" in self.__dict__ or "choose_mpc" in self.planner.__dict__:
                    raise AssertionError("physical agent was wrapped")

        class CollisionEnv(_FakeEnv):
            def step(self, action):
                print("collision: fixture bodies")
                return super().step(action)

        for mode in ("control", "trace", "trace_probe"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                result = run_forensic_episode(
                    CollisionEnv(),
                    InspectingAgent(),
                    mode=mode,
                    output_path=Path(directory) / f"{mode}.json",
                    snapshot_dir=Path(directory) / "snapshots",
                    shadow_agent_factory=_FakeAgent,
                    max_steps=1,
                )
                self.assertEqual(
                    result["records"][0]["collision_telemetry"]["stdout_collision_lines"],
                    ["collision: fixture bodies"],
                )
                self.assertTrue(result["records"][0]["collision_telemetry"]["available"])

    def test_trace_and_probe_receive_distinct_deep_copies(self) -> None:
        env = _FakeEnv()
        agent = _FakeAgent()
        received: list[tuple[str, int]] = []

        def diagnose(observation, *, observation_id, phase):
            received.append((phase, id(observation)))
            observation["pool_list"].append({"index": 100 + len(received)})
            return {"phase": phase}

        with tempfile.TemporaryDirectory() as directory:
            result = run_forensic_episode(
                env,
                agent,
                mode="trace_probe",
                output_path=Path(directory) / "trace.json",
                snapshot_dir=Path(directory) / "snapshots",
                diagnose_fn=diagnose,
                max_steps=1,
            )
        self.assertEqual([phase for phase, _ in received], ["trace", "probe"])
        self.assertNotEqual(received[0][1], received[1][1])
        self.assertEqual(result["records"][0]["diagnostics"]["trace"], {"phase": "trace"})
        self.assertEqual(result["records"][0]["diagnostics"]["probe"], {"phase": "probe"})

    def test_all_physical_steps_finish_before_saved_snapshot_diagnostics(self) -> None:
        env = _FakeEnv([
            {"is_included": True, "is_valid": True, "is_placed_safe": True},
            {"is_included": True, "is_valid": True, "is_placed_safe": True},
        ])
        agent = _FakeAgent()
        order: list[str] = []
        original_step = env.step

        def step(action):
            order.append(f"step{len(env.step_calls)}")
            return original_step(action)

        env.step = step
        original_policy = agent.policy

        def policy(observation):
            order.append(f"policy{len(env.step_calls)}")
            return original_policy(observation)

        agent.policy = policy

        def diagnose(observation, *, observation_id, phase):
            order.append(f"diagnose{observation_id.removeprefix('step-')}" )
            return {"phase": phase}

        with tempfile.TemporaryDirectory() as directory:
            result = run_forensic_episode(
                env,
                agent,
                mode="trace_probe",
                output_path=Path(directory) / "trace.json",
                snapshot_dir=Path(directory) / "snapshots",
                diagnose_fn=diagnose,
                shadow_agent_factory=_FakeAgent,
                max_steps=2,
            )
        self.assertIsNone(result["first_failure_step"])
        self.assertEqual(order[:4], ["policy0", "step0", "policy1", "step1"])
        self.assertEqual(order[4:], ["diagnose0000", "diagnose0000", "diagnose0001", "diagnose0001"])

    def test_canonical_failure_classification_prioritizes_diagnostic_interference(self) -> None:
        control = {"first_failure_step": None, "records": []}
        traced = {"first_failure_step": 0, "records": [{"route": "mpc", "status": {"is_valid": False}}]}
        comparison = {"first_divergent_step": 0}
        self.assertEqual(
            classify_failure(traced, comparison=comparison, control_result=control),
            "diagnostic_interference",
        )

    def test_three_mode_task_uses_fresh_env_and_agent_and_writes_pairwise_summary(self) -> None:
        created_envs = []
        created_agents = []

        def env_factory(config):
            env = _FakeEnv()
            created_envs.append((env, copy.deepcopy(config)))
            return env

        def agent_factory():
            agent = _FakeAgent()
            created_agents.append(agent)
            return agent

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run_three_mode_task(
                {"fixture": {"nested": [1]}},
                env_factory=env_factory,
                agent_factory=agent_factory,
                configure_agent_fn=lambda agent: agent,
                task="001",
                seed=42,
                max_steps=1,
                output_path=root / "summary.json",
                snapshot_root=root / "snapshots",
            )
            self.assertTrue((root / "summary.json").exists())
        self.assertEqual(len(created_envs), 3)
        self.assertGreaterEqual(len(created_agents), 6)  # physical + shadow per arm
        self.assertEqual([row[1] for row in created_envs], [{"fixture": {"nested": [1]}}] * 3)
        self.assertEqual(set(summary["modes"]), {"control", "trace", "trace_probe"})
        self.assertEqual(
            set(summary["pairwise"]),
            {"control__trace", "control__trace_probe", "trace__trace_probe"},
        )
        self.assertTrue(summary["complete"])
        self.assertTrue(summary["success"])
        self.assertEqual(summary["failed_modes"], [])

    def test_three_mode_summary_fails_when_factory_raises_but_keeps_partial_modes(self) -> None:
        calls = 0

        def env_factory(config):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("factory failed")
            return _FakeEnv()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run_three_mode_task(
                {},
                env_factory=env_factory,
                agent_factory=_FakeAgent,
                configure_agent_fn=lambda agent: agent,
                task="001",
                seed=42,
                max_steps=1,
                output_path=root / "summary.json",
                snapshot_root=root / "snapshots",
            )
            on_disk = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        self.assertFalse(summary["complete"])
        self.assertFalse(summary["success"])
        self.assertEqual(summary["failed_modes"], ["trace"])
        self.assertEqual(set(on_disk["modes"]), set(("control", "trace", "trace_probe")))
        self.assertIn("runner_error", on_disk["modes"]["trace"])
        self.assertIn("control__trace", on_disk["pairwise"])

    def test_three_mode_summary_fails_when_episode_returns_runner_error_and_main_is_nonzero(self) -> None:
        class ResetFailureEnv(_FakeEnv):
            def reset(self, seed=None):
                raise RuntimeError("reset failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = run_three_mode_task(
                {},
                env_factory=lambda config: ResetFailureEnv(),
                agent_factory=_FakeAgent,
                configure_agent_fn=lambda agent: agent,
                task="001",
                seed=42,
                max_steps=1,
                output_path=root / "summary.json",
                snapshot_root=root / "snapshots",
            )
            with patch(
                "tests.run_step14_forensics.run_real_three_mode_task",
                return_value=summary,
            ):
                exit_code = forensic_main([
                    "--output", str(root / "cli.json"),
                    "--snapshot-dir", str(root / "cli-snapshots"),
                ])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["failed_modes"], ["control", "trace", "trace_probe"])
        self.assertEqual(exit_code, 1)

    def test_no_collision_evidence_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_forensic_episode(
                _FakeEnv(),
                _FakeAgent(),
                mode="control",
                output_path=Path(directory) / "control.json",
                snapshot_dir=Path(directory) / "snapshots",
                shadow_agent_factory=_FakeAgent,
                max_steps=1,
            )
        telemetry = result["records"][0]["collision_telemetry"]
        self.assertFalse(telemetry["available"])
        self.assertEqual(telemetry["source"], "environment_info+validator_stdout")
        self.assertEqual(telemetry["reason"], "no_collision_or_contact_evidence")


if __name__ == "__main__":
    unittest.main()
