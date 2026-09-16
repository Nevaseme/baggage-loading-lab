from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SIMULATOR = ROOT / "simulator"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIMULATOR))

from agents.highscore.agent import Agent
from agents.highscore.ems import ProxyAction
from agents.highscore.model import AABB, ItemSpec
from agents.highscore.planner import Planner
from agents.highscore.state import build_packing_state
from simulator.tests.replay_support import load_observation_snapshot


def main() -> None:
    observation, metadata = load_observation_snapshot(
        SIMULATOR / "tests" / "artifacts" / "task001_step14_control_failure.npz"
    )
    agent = Agent(str(SIMULATOR / "agents" / "highscore"))
    agent.settings = replace(agent.settings, use_mpc_mcts_ems=True)
    agent.planner = Planner(agent.settings)
    calls: list[dict[str, object]] = []

    original_mpc = agent.planner.choose_mpc
    original_emergency = agent._depth_aware_emergency
    original_last_resort = agent._deterministic_last_resort

    def choose_mpc(*args, **kwargs):
        value = original_mpc(*args, **kwargs)
        calls.append({"route": "mpc", "candidate": value is not None})
        return value

    def emergency(*args, **kwargs):
        value = original_emergency(*args, **kwargs)
        calls.append({"route": "emergency_depth", "candidate": value is not None})
        return value

    def last_resort(*args, **kwargs):
        value = original_last_resort(*args, **kwargs)
        calls.append({"route": "deterministic_last_resort", "candidate": False})
        return value

    agent.planner.choose_mpc = choose_mpc
    agent._depth_aware_emergency = emergency
    agent._deterministic_last_resort = last_resort
    action = agent.policy(observation)
    state = build_packing_state(observation["container_list"], observation.get("depth_map"))
    item = ItemSpec.from_dict(observation["pool_list"][action["item_idx"]])
    dimensions = agent._orientation_dimensions(item, action["orientation"])
    box = AABB.from_center_half(
        action["place_pos"], tuple(float(value) / 2.0 for value in dimensions)
    )
    proposal = ProxyAction(
        item=item,
        pool_index=action["item_idx"],
        container_index=action["container_idx"],
        orientation=action["orientation"],
        box=box,
        support_key=(action["container_idx"], 0),
    )
    strict = agent.planner.generator.validate_proposal(state, proposal)
    relaxed = agent.planner.generator.validate_proposal(
        state, proposal, allow_rule_violations=True
    )
    legacy_path = (
        ROOT
        / "submit"
        / "Conservative Extreme-Point Packing_score29.7"
        / "high_score"
        / "agent.py"
    )
    spec = importlib.util.spec_from_file_location("scored_29_7_agent", legacy_path)
    assert spec is not None and spec.loader is not None
    legacy_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy_module)
    legacy_agent = legacy_module.Agent(str(legacy_path.parent))
    legacy_action = legacy_agent.policy(observation)
    legacy_item = ItemSpec.from_dict(observation["pool_list"][legacy_action["item_idx"]])
    legacy_dimensions = agent._orientation_dimensions(legacy_item, legacy_action["orientation"])
    legacy_proposal = ProxyAction(
        item=legacy_item,
        pool_index=legacy_action["item_idx"],
        container_index=legacy_action["container_idx"],
        orientation=legacy_action["orientation"],
        box=AABB.from_center_half(
            legacy_action["place_pos"],
            tuple(float(value) / 2.0 for value in legacy_dimensions),
        ),
        support_key=(legacy_action["container_idx"], 0),
    )
    legacy_strict = agent.planner.generator.validate_proposal(state, legacy_proposal)
    payload = {
        "metadata": metadata,
        "calls": calls,
        "shadow_exact_validation": {
            "strict": strict is not None,
            "allow_rule_violations": relaxed is not None,
        },
        "scored_29_7_shadow": {
            "action": {
                "item_idx": int(legacy_action["item_idx"]),
                "container_idx": int(legacy_action["container_idx"]),
                "place_pos": np.asarray(legacy_action["place_pos"]).tolist(),
                "orientation": int(legacy_action["orientation"]),
            },
            "strict": legacy_strict is not None,
        },
        "action": {
            "item_idx": action["item_idx"],
            "container_idx": action["container_idx"],
            "place_pos": action["place_pos"].tolist(),
            "orientation": action["orientation"],
        },
    }
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
