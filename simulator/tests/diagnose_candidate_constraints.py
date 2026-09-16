"""Identify which conservative checks eliminate candidates in a saved snapshot.

This diagnostic never changes production settings or submission code.  It reruns
one selected pool item while bypassing individual checks, then reruns cumulative
bypasses to expose cases where more than one check is binding.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulator.agents.highscore.candidates import CandidateGenerator  # noqa: E402
from simulator.agents.highscore.geometry import transport_path_clear as _transport_path_clear  # noqa: E402
from simulator.agents.highscore.model import ItemSpec  # noqa: E402
from simulator.agents.highscore.settings import SearchSettings  # noqa: E402
from simulator.agents.highscore.state import build_packing_state  # noqa: E402
from simulator.tests.replay_support import load_observation_snapshot  # noqa: E402


CHECKS = (
    "floor_balance",
    "collision",
    "inclusion",
    "support",
    "protection",
    "transport",
    "depth",
)


def _official_margin_transport(*args, **kwargs):
    kwargs["clearance"] = 0.015
    return _transport_path_clear(*args, **kwargs)


def _run(path: Path, pool_index: int, bypasses: set[str], seconds: float) -> dict:
    observation, metadata = load_observation_snapshot(path)
    state = build_packing_state(
        observation["container_list"], observation.get("depth_map")
    )
    raw_item = observation["pool_list"][pool_index]
    settings = SearchSettings()
    generator = CandidateGenerator(settings)
    started = time.perf_counter()
    with ExitStack() as stack:
        if "floor_balance" in bypasses:
            stack.enter_context(
                patch.object(CandidateGenerator, "_floor_frontier_balanced", return_value=True)
            )
        if "collision" in bypasses:
            stack.enter_context(
                patch("simulator.agents.highscore.candidates._collides_with_clearance", return_value=False)
            )
        if "inclusion" in bypasses:
            stack.enter_context(
                patch("simulator.agents.highscore.candidates.box_inside_planes", return_value=True)
            )
        if "support" in bypasses:
            stack.enter_context(
                patch("simulator.agents.highscore.candidates.support_metrics", return_value=(1.0, True))
            )
        if "protection" in bypasses:
            stack.enter_context(
                patch("simulator.agents.highscore.candidates.protection_rule_violations", return_value=0)
            )
        if "transport" in bypasses:
            stack.enter_context(
                patch("simulator.agents.highscore.candidates.transport_path_clear", return_value=True)
            )
        elif "transport_015" in bypasses:
            stack.enter_context(
                patch(
                    "simulator.agents.highscore.candidates.transport_path_clear",
                    side_effect=_official_margin_transport,
                )
            )
        if "depth" in bypasses:
            stack.enter_context(
                patch("simulator.agents.highscore.candidates.depth_map_path_clear", return_value=True)
            )
        candidates = generator.generate(
            state,
            ItemSpec.from_dict(raw_item),
            pool_index,
            deadline=started + seconds,
            allow_rule_violations=False,
        )
    return {
        "snapshot": str(path.resolve()),
        "failed_step": metadata.get("failed_step"),
        "pool_index": pool_index,
        "item_index": raw_item["index"],
        "bypasses": sorted(bypasses),
        "candidates": len(candidates),
        "elapsed_seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--pool-index", type=int, default=0)
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()

    results = [_run(args.snapshot, args.pool_index, set(), args.seconds)]
    results.extend(
        _run(args.snapshot, args.pool_index, {check}, args.seconds)
        for check in CHECKS
    )
    results.append(
        _run(args.snapshot, args.pool_index, {"transport_015"}, args.seconds)
    )
    cumulative: set[str] = set()
    for check in CHECKS:
        cumulative.add(check)
        results.append(_run(args.snapshot, args.pool_index, cumulative, args.seconds))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
