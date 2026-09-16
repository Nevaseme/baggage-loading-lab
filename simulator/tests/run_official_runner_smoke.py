"""Exercise the official multiprocessing/time-limit runner on a tiny task."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from src.ground_handling.app import EvaluationApp


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with (root / "configs" / "sample_config.json").open(encoding="utf-8") as stream:
        task = copy.deepcopy(json.load(stream)["001"])
    task["item_stream"]["item_list"] = task["item_stream"]["item_list"][:4]
    task["item_stream"]["look_ahead"] = 4
    task["agent"]["optimize"] = False
    task["visualizer"]["vis"] = False

    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        config_path = temp / "config.json"
        config_path.write_text(json.dumps({"smoke": task}), encoding="utf-8")
        app = EvaluationApp(
            config_path=str(config_path),
            module_path="agents/highscore/",
            agent_module="agents.highscore.agent",
            agent_class="Agent",
            result_dir=str(temp),
            result_fname="result.json",
        )
        app.run(render_mode=None, verbose=False)
        result = json.loads((temp / "result.json").read_text(encoding="utf-8"))["smoke"]
        print(json.dumps(result, indent=2))
        safe = result.get("place_states") == {
            "is_included": True,
            "is_valid": True,
            "is_placed_safe": True,
        }
        complete = result.get("evaluation", {}).get("num_placed_items") == 1.0
        fast = result.get("time_results", {}).get("policy", 99.0) < 6.0
        return 0 if result.get("status") == "success" and safe and complete and fast else 1


if __name__ == "__main__":
    raise SystemExit(main())
