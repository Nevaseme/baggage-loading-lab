"""Run a short, real-PyBullet regression without changing the sample config."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.agent import Agent
from agents.highscore.model import ItemSpec
from agents.highscore.planner import Planner
from agents.highscore.state import build_packing_state
from tests.replay_support import save_observation_snapshot


class PhysicsSmokeCliTests(unittest.TestCase):
    def test_help_exposes_algorithm_selection_flags(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--help"],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--monotone-ingress", completed.stdout)
        self.assertIn("--geometry-rescue", completed.stdout)
        self.assertIn("--mpc-mcts-ems", completed.stdout)

    def test_parser_defaults_and_configuration_replace_all_experiment_flags(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual((args.monotone_ingress, args.geometry_rescue, args.mpc_mcts_ems), ("off", "off", "off"))
        agent = Agent("agents/highscore/")
        original_planner = agent.planner
        args = build_parser().parse_args([
            "--monotone-ingress", "on", "--geometry-rescue", "on", "--mpc-mcts-ems", "on"
        ])
        configure_agent(agent, args)
        self.assertTrue(agent.settings.use_monotone_ingress)
        self.assertTrue(agent.settings.use_geometry_rescue)
        self.assertTrue(agent.settings.use_mpc_mcts_ems)
        self.assertIsNot(agent.planner, original_planner)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="001")
    parser.add_argument("--items", type=int, default=6)
    parser.add_argument("--optimize-seconds", type=float, default=0.0)
    parser.add_argument(
        "--monotone-ingress",
        choices=("on", "off"),
        default="off",
    )
    parser.add_argument(
        "--geometry-rescue",
        choices=("on", "off"),
        default="off",
    )
    parser.add_argument(
        "--mpc-mcts-ems",
        choices=("on", "off"),
        default="off",
    )
    parser.add_argument(
        "--snapshot-on-failure",
        type=Path,
        help="write the pre-action observation to this .npz file on failure",
    )
    parser.add_argument(
        "--rescue-without-depth",
        action="store_true",
        help="when policy falls back, try geometry-only candidates before stepping",
    )
    return parser


def configure_agent(agent: Agent, args: argparse.Namespace) -> None:
    agent.settings = replace(
        agent.settings,
        use_monotone_ingress=args.monotone_ingress == "on",
        use_geometry_rescue=args.geometry_rescue == "on",
        use_mpc_mcts_ems=args.mpc_mcts_ems == "on",
    )
    agent.planner = Planner(agent.settings)


def main() -> int:
    args = build_parser().parse_args()

    root = Path(__file__).resolve().parents[1]
    with (root / "configs" / "sample_config.json").open(encoding="utf-8") as stream:
        all_config = json.load(stream)
    config = copy.deepcopy(all_config[args.task])
    config["item_stream"]["item_list"] = config["item_stream"]["item_list"][: args.items]
    config["item_stream"]["look_ahead"] = min(
        config["item_stream"]["look_ahead"], args.items
    )
    config["agent"]["optimize"] = False
    config["visualizer"]["vis"] = False

    from src.ground_handling.env import GroundHandlingEnv

    env = GroundHandlingEnv(config=config, verbose=False, render_mode=None)
    agent = Agent("agents/highscore/")
    configure_agent(agent, args)
    records: list[dict] = []
    try:
        env.reset_settings()
        env.reset_item_stream()
        if not agent.get_init_states(env.get_init_states()):
            raise RuntimeError("get_init_states returned false")
        optimized_order = None
        optimize_elapsed = 0.0
        if args.optimize_seconds > 0.0:
            agent.settings = replace(
                agent.settings, optimize_limit_seconds=args.optimize_seconds
            )
            agent.planner = Planner(agent.settings)
            optimize_started = time.perf_counter()
            optimized_order = agent.optimize(env.get_info_for_optimization())
            optimize_elapsed = time.perf_counter() - optimize_started
            if not env.set_item_order(optimized_order):
                raise RuntimeError("optimizer returned an invalid permutation")
            env.reset_item_stream()
        observation, _ = env.reset(seed=42)
        terminated = False
        truncated = False
        while not (terminated or truncated):
            # The production runner attaches this shared buffer in the agent process.
            observation["depth_map"] = env.shm_depth_map.copy()
            started = time.perf_counter()
            action = agent.policy(observation)
            elapsed = time.perf_counter() - started
            rescued_without_depth = False
            if args.rescue_without_depth:
                raw_pool = list(observation.get("pool_list", []))
                pool = [ItemSpec.from_dict(raw_item) for raw_item in raw_pool]
                fallback = agent._deterministic_last_resort(observation, pool)
                is_fallback = (
                    action["item_idx"] == fallback["item_idx"]
                    and action["container_idx"] == fallback["container_idx"]
                    and action["orientation"] == fallback["orientation"]
                    and np.allclose(action["place_pos"], fallback["place_pos"])
                )
                if is_fallback:
                    rescue_state = build_packing_state(
                        observation["container_list"], None
                    )
                    rescue_deadline = time.perf_counter() + 5.0
                    rescue_candidates = []
                    for pool_index, item in enumerate(pool):
                        item_started = time.perf_counter()
                        remaining_items = len(pool) - pool_index
                        fair_share = max(0.0, rescue_deadline - item_started) / max(
                            1, remaining_items
                        )
                        generated = agent.planner.generator.generate(
                            rescue_state,
                            item,
                            pool_index,
                            deadline=item_started + fair_share,
                            allow_rule_violations=True,
                        )
                        for candidate in generated:
                            agent.planner.scorer.score(rescue_state, candidate)
                        rescue_candidates.extend(generated)
                        if time.perf_counter() >= rescue_deadline:
                            break
                    if rescue_candidates:
                        rescued = max(
                            rescue_candidates,
                            key=lambda candidate: (
                                -candidate.rule_violations,
                                candidate.secondary_score,
                                candidate.support_ratio,
                                candidate.min_clearance,
                            ),
                        )
                        action = agent._format_action(
                            rescued.pool_index,
                            rescued.container_index,
                            rescued.position,
                            rescued.orientation,
                        )
                        rescued_without_depth = True
            pre_observation = observation
            observation, _, terminated, truncated, info = env.step(action)
            records.append(
                {
                    "action": {
                        "item_idx": action["item_idx"],
                        "container_idx": action["container_idx"],
                        "place_pos": action["place_pos"].tolist(),
                        "orientation": action["orientation"],
                    },
                    "elapsed": elapsed,
                    "rescued_without_depth": rescued_without_depth,
                    "status": info.get("status", {}),
                }
            )
            if not all(info.get("status", {}).values()):
                if args.snapshot_on_failure is not None:
                    save_observation_snapshot(
                        args.snapshot_on_failure,
                        pre_observation,
                        {
                            "task": args.task,
                            "requested_items": args.items,
                            "failed_step": len(records) - 1,
                            "status": info.get("status", {}),
                            "action": records[-1]["action"],
                        },
                    )
                diagnostic_state = build_packing_state(
                    pre_observation["container_list"], pre_observation.get("depth_map")
                )
                diagnostics = []
                for pool_index, raw_item in enumerate(pre_observation["pool_list"]):
                    diagnostic_started = time.perf_counter()
                    generated = agent.planner.generator.generate(
                        diagnostic_state,
                        ItemSpec.from_dict(raw_item),
                        pool_index,
                        deadline=time.perf_counter() + 5.0,
                        allow_rule_violations=True,
                    )
                    diagnostics.append(
                        {
                            "pool_index": pool_index,
                            "item_index": raw_item["index"],
                            "candidates": len(generated),
                            "seconds": time.perf_counter() - diagnostic_started,
                        }
                    )
                records[-1]["candidate_diagnostics"] = diagnostics
        result = {
            "task": args.task,
            "requested_items": args.items,
            "monotone_ingress": args.monotone_ingress,
            "geometry_rescue": args.geometry_rescue,
            "mpc_mcts_ems": args.mpc_mcts_ems,
            "completed_steps": len(records),
            "terminated": terminated,
            "truncated": truncated,
            "all_safe": all(
                all(record["status"].values()) for record in records
            ),
            "max_policy_seconds": max((record["elapsed"] for record in records), default=0.0),
            "optimize_seconds": optimize_elapsed,
            "optimized_order": optimized_order,
            "evaluation": env.evaluate(),
            "records": records,
        }
        print(json.dumps(result, indent=2))
        return 0 if result["all_safe"] and len(records) == args.items else 1
    finally:
        env.close()


if __name__ == "__main__":
    raise SystemExit(main())
