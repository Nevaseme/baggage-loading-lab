"""Replay a saved observation through the production candidate generator."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulator.agents.highscore.candidates import CandidateGenerator  # noqa: E402
from simulator.agents.highscore.model import ItemSpec  # noqa: E402
from simulator.agents.highscore.scoring import CandidateScorer  # noqa: E402
from simulator.agents.highscore.settings import SearchSettings  # noqa: E402
from simulator.agents.highscore.state import build_packing_state  # noqa: E402
from simulator.tests.replay_support import load_observation_snapshot  # noqa: E402


def analyze_snapshot(path: Path, seconds: float) -> dict:
    observation, metadata = load_observation_snapshot(path)
    state = build_packing_state(
        observation["container_list"], observation.get("depth_map")
    )
    generator = CandidateGenerator(SearchSettings())
    scorer = CandidateScorer(SearchSettings())
    started = time.perf_counter()
    deadline = started + max(0.0, float(seconds))
    candidate_counts: list[dict] = []
    pool_list = observation.get("pool_list", [])
    any_budget_exhausted = False
    for pool_index, raw_item in enumerate(pool_list):
        now = time.perf_counter()
        remaining_items = len(pool_list) - pool_index
        fair_share = max(0.0, deadline - now) / max(1, remaining_items)
        item_deadline = now + fair_share
        item_started = time.perf_counter()
        candidates = generator.generate(
            state,
            ItemSpec.from_dict(raw_item),
            pool_index,
            deadline=item_deadline,
            allow_rule_violations=False,
        )
        for candidate in candidates:
            scorer.score(state, candidate)
        best = max(
            candidates,
            key=lambda candidate: (
                candidate.secondary_score,
                candidate.support_ratio,
                candidate.position[1],
                -candidate.position[2],
            ),
            default=None,
        )
        best_action = (
            {
                "item_idx": int(best.pool_index),
                "container_idx": int(best.container_index),
                "place_pos": [float(value) for value in best.position],
                "orientation": int(best.orientation),
            }
            if best is not None
            else None
        )
        budget_exhausted = time.perf_counter() >= item_deadline
        any_budget_exhausted = any_budget_exhausted or budget_exhausted
        candidate_counts.append(
            {
                "pool_index": pool_index,
                "item_index": int(raw_item["index"]),
                "safe_candidates": len(candidates),
                "best_action": best_action,
                "budget_exhausted": budget_exhausted,
                "seconds": time.perf_counter() - item_started,
            }
        )
    pool_size = len(pool_list)
    return {
        "snapshot": str(Path(path).resolve()),
        "metadata": metadata,
        "pool_size": pool_size,
        "candidate_counts": candidate_counts,
        "timed_out": any_budget_exhausted,
        "elapsed_seconds": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    print(json.dumps(analyze_snapshot(args.snapshot, args.seconds), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
