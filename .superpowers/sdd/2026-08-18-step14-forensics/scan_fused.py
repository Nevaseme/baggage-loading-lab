from __future__ import annotations

from pathlib import Path
import json
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SIMULATOR = ROOT / "simulator"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SIMULATOR))

from agents.highscore.candidates import CandidateGenerator
from agents.highscore.ems import ProxyAction
from agents.highscore.geometry import oriented_dimensions
from agents.highscore.model import AABB, ItemSpec
from agents.highscore.settings import SearchSettings as StrictSettings
from agents.highscore.state import build_packing_state as build_strict_state
from agents.support_extreme_fusion_beam_exact_mask.proposals import iter_fused_records
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state as build_fusion_state
from simulator.tests.replay_support import load_observation_snapshot


def scan() -> list[dict[str, object]]:
    observation, _ = load_observation_snapshot(
        SIMULATOR / "tests" / "artifacts" / "task001_step14_control_failure.npz"
    )
    strict_state = build_strict_state(observation["container_list"], observation["depth_map"])
    fusion_state = build_fusion_state(observation["container_list"], observation["depth_map"])
    validator = CandidateGenerator(StrictSettings())
    results: list[dict[str, object]] = []
    for pool_index, raw_item in enumerate(observation["pool_list"]):
        item = ItemSpec.from_dict(raw_item)
        started = time.perf_counter()
        deadline = started + 5.0
        raw_count = 0
        strict_count = 0
        rescue_raw_count = 0
        rescue_strict_count = 0
        accepted: list[dict[str, object]] = []
        sources: dict[str, int] = {}
        for fused in iter_fused_records(
            fusion_state,
            raw_item,
            pool_index,
            deadline=deadline,
            rescue=True,
            max_proposals=2500,
        ):
            raw_count += 1
            for source in fused.provenance.sources:
                sources[source] = sources.get(source, 0) + 1
            proposal = fused.proposal
            dimensions = oriented_dimensions(item.dimensions, proposal.orientation)
            action = ProxyAction(
                item=item,
                pool_index=pool_index,
                container_index=proposal.container_index,
                orientation=proposal.orientation,
                box=AABB.from_center_half(
                    proposal.position, np.asarray(dimensions, dtype=np.float64) * 0.5
                ),
                support_key=(proposal.container_index, -1),
            )
            candidate = validator.validate_proposal(strict_state, action)
            if candidate is not None:
                strict_count += 1
                if len(accepted) < 5:
                    accepted.append(
                        {
                            "orientation": proposal.orientation,
                            "position": list(proposal.position),
                            "sources": list(fused.provenance.sources),
                        }
                    )
        if strict_count == 0:
            for fused in iter_fused_records(
                fusion_state,
                raw_item,
                pool_index,
                deadline=deadline,
                rescue_only=True,
                max_proposals=2500,
            ):
                rescue_raw_count += 1
                proposal = fused.proposal
                dimensions = oriented_dimensions(item.dimensions, proposal.orientation)
                action = ProxyAction(
                    item=item,
                    pool_index=pool_index,
                    container_index=proposal.container_index,
                    orientation=proposal.orientation,
                    box=AABB.from_center_half(
                        proposal.position, np.asarray(dimensions, dtype=np.float64) * 0.5
                    ),
                    support_key=(proposal.container_index, -1),
                )
                candidate = validator.validate_proposal(strict_state, action)
                if candidate is not None:
                    rescue_strict_count += 1
                    if len(accepted) < 5:
                        accepted.append(
                            {
                                "orientation": proposal.orientation,
                                "position": list(proposal.position),
                                "sources": list(fused.provenance.sources),
                            }
                        )
        results.append(
            {
                "pool_index": pool_index,
                "item_index": raw_item["index"],
                "raw_count": raw_count,
                "strict_count": strict_count,
                "rescue_raw_count": rescue_raw_count,
                "rescue_strict_count": rescue_strict_count,
                "accepted": accepted,
                "source_counts": sources,
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
    return results


if __name__ == "__main__":
    print(json.dumps(scan(), sort_keys=True))
