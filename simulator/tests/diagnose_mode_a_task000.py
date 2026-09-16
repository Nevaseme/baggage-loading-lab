"""Non-physics Task22 diagnosis for the task000 Mode-A run."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import time
from typing import Any

from agents.support_extreme_fusion_beam_exact_mask.catalog import (
    AdaptiveDenseRescueConfig,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask
from agents.support_extreme_fusion_beam_exact_mask.mode_a_exact_compile import (
    StrictSkeletonCompiler,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_order_beam import (
    LayeredProxyOrderBeam,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (
    build_offline_occurrences,
)
from agents.support_extreme_fusion_beam_exact_mask.model import ItemSpec
from agents.support_extreme_fusion_beam_exact_mask.proposals import (
    ProposalSource,
    iter_fused_records,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState, apply_root
from tests.replay_support import load_observation_snapshot


def _root_row(root: Any) -> dict[str, Any]:
    proposal = root.proposal
    return {
        "pool_index": proposal.pool_index,
        "item_index": proposal.item_index,
        "container_index": proposal.container_index,
        "orientation": proposal.orientation,
        "position": list(proposal.position),
        "source": root.source,
        "support_ratio": root.support_ratio,
        "min_clearance": root.min_clearance,
    }


def analyze_order_beam(
    containers: list[dict[str, Any]],
    raw_items: list[dict[str, Any]],
    *,
    order_seconds: float = 82.0,
) -> dict[str, Any]:
    state = build_packing_state(containers)
    occurrences = build_offline_occurrences(raw_items)
    beam = LayeredProxyOrderBeam()
    seeds = beam.seed_orders(occurrences, raw_items)
    started = time.perf_counter()
    candidates = beam.search(state, occurrences, raw_items, started + order_seconds)
    elapsed = time.perf_counter() - started
    complete = tuple(value for value in candidates if value.complete)

    settings = SearchSettings()
    exact_mask = ExactMask(settings)
    scanner = StrictRootScanner(settings, mask=exact_mask)
    compiler = StrictSkeletonCompiler(settings, scanner, exact_mask)
    compiler_rows = []
    for ordinal, candidate in enumerate(complete):
        compile_started = time.perf_counter()
        plan = compiler.compile(
            state,
            raw_items,
            occurrences,
            candidate,
            compile_started + 30.0,
        )
        compiler_rows.append(
            {
                "candidate_ordinal": ordinal,
                "placed_count": candidate.placed_count,
                "elapsed_seconds": time.perf_counter() - compile_started,
                "published": plan is not None,
                "failure_reason": None if plan is not None else "compiler_returned_none",
            }
        )

    return {
        "elapsed_seconds": elapsed,
        "trace": asdict(beam.last_trace),
        "candidate_count": len(candidates),
        "complete_candidate_count": len(complete),
        "candidate_rows": [
            {
                "rank": rank,
                "complete": value.complete,
                "placed_count": value.placed_count,
                "placed_volume": value.placed_volume,
                "seed_lane": value.seed_lane,
                "prefix": [
                    occurrence.original_position
                    for occurrence in value.occurrence_order[:10]
                ],
                "skeleton_length": len(value.skeleton),
            }
            for rank, value in enumerate(candidates)
        ],
        "seeds": {
            "original": list(seeds[0]),
            "historical": list(seeds[1]),
            "descending_volume": list(seeds[2]),
        },
        "compiler_invocations": len(compiler_rows),
        "compiler_rows": compiler_rows,
        "optimize_fallback_reason": (
            "no_complete_proxy_candidate"
            if not complete
            else "all_complete_candidates_failed_strict_compile"
            if not any(row["published"] for row in compiler_rows)
            else None
        ),
    }


def analyze_step_snapshot(
    snapshot_path: Path,
    *,
    dense_raw_limit: int = 50_000,
) -> dict[str, Any]:
    observation, metadata = load_observation_snapshot(snapshot_path)
    state = build_packing_state(
        observation["container_list"], observation.get("depth_map")
    )
    raw_pool = list(observation["pool_list"])
    item0 = ItemSpec.from_dict(raw_pool[0])
    singleton = (item0,)
    settings = replace(
        SearchSettings(),
        normal_catalog_limit_seconds=30.0,
        zero_root_rescue_limit_seconds=30.0,
        raw_proposal_limit=max(8192, dense_raw_limit),
    )
    exact_mask = ExactMask(settings)
    scanner = StrictRootScanner(settings, mask=exact_mask)

    normal_started = time.perf_counter()
    normal = scanner.scan(
        state,
        singleton,
        deadline=normal_started + 30.0,
        allow_deferred=False,
        allow_rescue=False,
        advisory_proposals=(),
    )
    normal_elapsed = time.perf_counter() - normal_started

    dense_started = time.perf_counter()
    dense_records = tuple(
        iter_fused_records(
            state,
            item0,
            pool_index=0,
            deadline=dense_started + 60.0,
            family_subset=(ProposalSource.DENSE_SUPPORT_LATTICE,),
            settings=settings,
            raw_work_limit=dense_raw_limit,
        )
    )
    dense_rejections: Counter[str] = Counter()
    dense_roots = []
    for record in dense_records:
        if time.perf_counter() >= dense_started + 60.0:
            dense_rejections["diagnostic_deadline"] += 1
            break
        trace = exact_mask.diagnose(
            state, singleton, record.proposal, deadline=dense_started + 60.0
        )
        if not trace.accepted or trace.root is None:
            dense_rejections[
                trace.first_reason.value if trace.first_reason is not None else "unknown"
            ] += 1
            continue
        fresh = exact_mask.validate(
            state, singleton, record.proposal, deadline=dense_started + 60.0
        )
        if fresh is None:
            dense_rejections["fresh_validate_none"] += 1
            continue
        dense_roots.append(fresh)
    dense_elapsed = time.perf_counter() - dense_started

    adaptive_settings = settings
    adaptive_mask = ExactMask(adaptive_settings)
    adaptive_scanner = StrictRootScanner(
        adaptive_settings,
        mask=adaptive_mask,
        adaptive_dense_rescue=AdaptiveDenseRescueConfig(
            raw_work_limit=dense_raw_limit,
            covered_occurrence_target=1,
            output_reserve_seconds=0.0,
        ),
    )
    adaptive_started = time.perf_counter()
    adaptive = adaptive_scanner.scan(
        state,
        singleton,
        deadline=adaptive_started + 60.0,
        allow_deferred=False,
        allow_rescue=True,
        advisory_proposals=(),
    )
    adaptive_elapsed = time.perf_counter() - adaptive_started

    apply_results = []
    production_settings = SearchSettings()
    production_mask = ExactMask(production_settings)
    for root in tuple(normal.roots[:1]) + tuple(dense_roots[:1]) + tuple(adaptive.roots[:1]):
        try:
            production_root = production_mask.validate(
                state,
                singleton,
                root.proposal,
                deadline=time.perf_counter() + 10.0,
            )
            if production_root is None:
                raise RuntimeError("default-profile fresh validation returned no root")
            transition = apply_root(
                SimState(state, singleton, (0,)),
                production_root,
                production_settings,
                exact_revalidator=production_mask,
                deadline=time.perf_counter() + 10.0,
            )
        except Exception as error:
            apply_results.append(
                {"root": _root_row(root), "fresh_apply": False, "error": str(error)}
            )
        else:
            apply_results.append(
                {
                    "root": _root_row(root),
                    "fresh_apply": True,
                    "default_profile_revalidate": True,
                    "child_pool_size": len(transition.child.pool),
                }
            )

    return {
        "metadata": metadata,
        "pool_size": len(raw_pool),
        "item0_index": item0.index,
        "packed_count": sum(len(container.placed) for container in state.containers),
        "normal": {
            "elapsed_seconds": normal_elapsed,
            "roots": len(normal),
            "stats": asdict(normal.stats),
            "first_roots": [_root_row(root) for root in normal.roots[:5]],
        },
        "dense_direct": {
            "elapsed_seconds": dense_elapsed,
            "raw_records": len(dense_records),
            "roots": len(dense_roots),
            "rejection_counts": sorted(dense_rejections.items()),
            "first_roots": [_root_row(root) for root in dense_roots[:5]],
        },
        "adaptive": {
            "elapsed_seconds": adaptive_elapsed,
            "roots": len(adaptive),
            "stats": asdict(adaptive.stats),
            "first_roots": [_root_row(root) for root in adaptive.roots[:5]],
        },
        "fresh_apply_results": apply_results,
    }


def run_diagnosis(config_path: Path, snapshot_path: Path) -> dict[str, Any]:
    with config_path.open(encoding="utf-8") as stream:
        task = json.load(stream)["000"]
    saved_observation, _metadata = load_observation_snapshot(snapshot_path)
    initial_containers = copy.deepcopy(saved_observation["container_list"])
    for container in initial_containers:
        container["packed_items"] = []
    return {
        "scope": "non_physics_read_only_production_diagnosis",
        "order_beam": analyze_order_beam(
            initial_containers,
            task["item_stream"]["item_list"],
        ),
        "step11": analyze_step_snapshot(snapshot_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run_diagnosis(args.config, args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
