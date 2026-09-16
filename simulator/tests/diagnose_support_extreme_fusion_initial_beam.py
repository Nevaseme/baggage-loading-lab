"""Read-only Task13 diagnosis for the task001 initial B decision."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Any

from agents.support_extreme_fusion_beam_exact_mask.beam import (
    BeamNode,
    FutureSupportIngressBeam,
)
from agents.support_extreme_fusion_beam_exact_mask.catalog import StrictRootScanner
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState
from src.ground_handling.utils import aff, write_open_cut_corner_cup_obj


ROOT = Path(__file__).resolve().parents[2]
SIMULATOR = ROOT / "simulator"
RANK_NAMES = (
    "proven_count",
    "proven_volume",
    "future_covered_items",
    "future_covered_volume",
    "root_robustness",
    "scarcity_urgency",
    "compatible_support_capacity",
    "protection_compatible_capacity",
    "ingress_access",
    "largest_free_support",
    "negative_sliver_area",
    "low_mass_cog_goodness",
    "min_support_margin",
    "min_clearance_margin",
    "low_stack",
)


def _initial_case() -> tuple[Any, list[dict], dict]:
    config = json.loads(
        (SIMULATOR / "configs" / "sample_config.json").read_text(encoding="utf-8")
    )["001"]
    raw = dict(config["containers"]["container_list"][0])
    with tempfile.TemporaryDirectory() as directory:
        points, normals = write_open_cut_corner_cup_obj(
            str(Path(directory) / "task001-container.obj"),
            width=raw["length"],
            height=raw["height"],
            cut_x=raw["cut_x"],
            cut_y=raw["cut_y"],
            depth=raw["width"],
            wall=raw["thickness"],
            bottom=raw["thickness"],
        )
    rotation = (
        (1.0, 0.0, 0.0),
        (0.0, math.cos(math.pi / 2.0), -math.sin(math.pi / 2.0)),
        (0.0, math.sin(math.pi / 2.0), math.cos(math.pi / 2.0)),
    )
    center = (0.0, 0.0, raw["height"] / 2.0 + raw.get("buffer", 0.0))
    raw["center"] = center
    raw["points"] = aff(points, rotation, center)
    raw["n_vecs"] = aff(normals, rotation, (0.0, 0.0, 0.0))
    inner_length = raw["length"] - 2.0 * raw["thickness"]
    inner_width = raw["width"] - 2.0 * raw["thickness"]
    inner_height = raw["height"] - raw["thickness"] - raw.get("buffer", 0.0)
    base_volume = inner_length * inner_width * inner_height
    cut_volume = (
        0.5
        * (raw["cut_x"] - raw["thickness"])
        * (raw["cut_y"] - raw["thickness"])
        * inner_width
    )
    small_shelf_volume = raw["cut_x"] * raw["thickness"] * inner_width
    shelf_volume = inner_length * raw["thickness"] * (
        raw["width"] / 2.0 - 2.0 * raw["thickness"]
    )
    raw["volume"] = base_volume - cut_volume - small_shelf_volume - shelf_volume
    raw["shelf"] = bool(raw.pop("require_shelf"))
    pool = list(config["item_stream"]["item_list"][: config["item_stream"]["look_ahead"]])
    return build_packing_state([raw]), pool, raw


def _proposal(node_or_root: Any) -> dict[str, Any]:
    root = node_or_root.first_root if isinstance(node_or_root, BeamNode) else node_or_root
    proposal = root.proposal
    return {
        "pool_index": proposal.pool_index,
        "item_index": proposal.item_index,
        "container_index": proposal.container_index,
        "orientation": proposal.orientation,
        "position": [float(value) for value in proposal.position],
        "source": proposal.source,
    }


def _node_row(
    beam: FutureSupportIngressBeam, node: BeamNode, parent_catalog
) -> dict[str, Any]:
    return {
        "proposal": _proposal(node),
        "rank": {
            name: float(value) for name, value in zip(RANK_NAMES, beam._rank(node))
        },
        "features": asdict(node.features),
        "root_count_for_item": len(
            parent_catalog.for_pool(node.sequence[-1].selected_pool_index)
        ),
    }


class _TracingScanner:
    def __init__(self, scanner: StrictRootScanner, origin: float) -> None:
        self.scanner = scanner
        self.origin = origin
        self.calls: list[dict[str, Any]] = []

    def scan(self, state, pool, **kwargs):
        started = time.perf_counter()
        deadline = float(kwargs.get("deadline", started))
        catalog = self.scanner.scan(state, pool, **kwargs)
        finished = time.perf_counter()
        self.calls.append(
            {
                "start": started - self.origin,
                "finish": finished - self.origin,
                "seconds": finished - started,
                "deadline_remaining_at_start": deadline - started,
                "deadline_overrun_at_finish": max(0.0, finished - deadline),
                "pool_size": len(tuple(pool)),
                "roots": len(catalog),
                "per_pool_roots": list(catalog.stats.per_pool_roots),
                "exact_attempts": catalog.stats.exact_attempts,
                "deadline_reached": catalog.stats.deadline_reached,
            }
        )
        return catalog


class _TracingBeam(FutureSupportIngressBeam):
    def __init__(self, *args, trace_origin: float, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.trace_origin = trace_origin
        self.nodes: list[dict[str, Any]] = []
        self.incumbents: list[dict[str, Any]] = []

    def _extend(self, *args, **kwargs):
        started = time.perf_counter()
        node = super()._extend(*args, **kwargs)
        finished = time.perf_counter()
        if node is not None:
            self.nodes.append(
                {
                    "finish": finished - self.trace_origin,
                    "seconds": finished - started,
                    "depth": node.proven_count,
                    "first_root": _proposal(node),
                    "last_pool_index": node.sequence[-1].selected_pool_index,
                    "child_roots": len(node.catalog),
                    "rank": [float(value) for value in self._rank(node)],
                }
            )
        return node

    def _prefer(self, current, candidate):
        preferred = super()._prefer(current, candidate)
        if preferred is candidate and preferred is not current:
            self.incumbents.append(
                {
                    "time": time.perf_counter() - self.trace_origin,
                    "depth": candidate.proven_count,
                    "first_root": _proposal(candidate),
                    "rank": [float(value) for value in self._rank(candidate)],
                }
            )
        return preferred


def _sequence(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path.relative_to(ROOT)),
        "outcome": payload.get("outcome"),
        "safe_placements": payload.get("safe_placements"),
        "fill_score": payload.get("evaluation", {}).get("fill_score"),
        "policy_seconds": payload.get("policy_time_seconds"),
        "actions": [record["action"] for record in payload.get("records", ())],
    }


def diagnose() -> dict[str, Any]:
    state, pool, container = _initial_case()
    settings = SearchSettings()
    mask = ExactMask(settings)
    scanner = StrictRootScanner(settings, mask=mask)
    scan_started = time.perf_counter()
    catalog = scanner.scan(state, pool, deadline=scan_started + 5.45)
    scan_finished = time.perf_counter()

    beam = FutureSupportIngressBeam(scanner, mask, settings)
    sim = SimState.from_current(state, pool)
    one_edge_started = time.perf_counter()
    one_edge = beam._evaluate_catalog(
        sim,
        catalog,
        (),
        None,
        0.0,
        0.0,
        (),
        time.perf_counter() + 30.0,
        scan_child=False,
    )
    one_edge_finished = time.perf_counter()
    ordered = beam._ordered(one_edge)
    admitted = beam._ordered(beam._admit(one_edge))
    max_y = max(node.first_root.proposal.position[1] for node in one_edge)
    back_most = beam._ordered(
        [node for node in one_edge if node.first_root.proposal.position[1] >= max_y - 1e-7]
    )

    child_costs: list[dict[str, Any]] = []
    for node in admitted:
        started = time.perf_counter()
        child = scanner.scan(
            node.sim.packing,
            node.sim.pool,
            deadline=started + 5.3,
            breadth_rescue=False,
            allow_deferred=False,
            allow_rescue=False,
        )
        child_costs.append(
            {
                "proposal": _proposal(node),
                "seconds": time.perf_counter() - started,
                "roots": len(child),
                "exact_attempts": child.stats.exact_attempts,
                "deadline_reached": child.stats.deadline_reached,
            }
        )

    trace_origin = time.perf_counter()
    tracing_scanner = _TracingScanner(scanner, trace_origin)
    tracing_beam = _TracingBeam(
        tracing_scanner,
        mask,
        settings,
        trace_origin=trace_origin,
        beam_width=settings.bc_beam_width,
        max_depth=settings.bc_beam_depth,
        item_choices=settings.bc_item_choices,
        roots_per_item=settings.bc_roots_per_item,
    )
    selected = tracing_beam.choose_b(
        state,
        pool,
        catalog,
        trace_origin + settings.bc_search_limit_seconds,
    )
    trace_finished = time.perf_counter()

    results = SIMULATOR / "results" / "support_extreme_fusion"
    return {
        "case": {
            "task": "001",
            "pool_size": len(pool),
            "pool": [
                {
                    "pool_index": index,
                    "item_index": item["index"],
                    "dimensions": [item["length"], item["width"], item["height"]],
                    "volume": item["length"] * item["width"] * item["height"],
                    "mass": item["mass"],
                    "soft": bool(item.get("is_soft", False)),
                    "prioritized": bool(item.get("is_prioritized", False)),
                }
                for index, item in enumerate(pool)
            ],
            "container": {
                "length": container["length"],
                "width": container["width"],
                "height": container["height"],
                "shelf": container["shelf"],
            },
        },
        "initial_catalog": {
            "seconds": scan_finished - scan_started,
            "roots": len(catalog),
            "per_pool_roots": list(catalog.stats.per_pool_roots),
            "stage_attempts": dict(catalog.stats.stage_attempts),
            "stage_roots": dict(catalog.stats.stage_roots),
            "first_root_stage": list(catalog.stats.first_root_stage),
            "sources": dict(Counter(record.proposal.source for record in catalog)),
            "orientations": dict(
                sorted(Counter(record.orientation for record in catalog).items())
            ),
        },
        "one_edge": {
            "seconds": one_edge_finished - one_edge_started,
            "nodes": len(one_edge),
            "all_ranked": [_node_row(beam, node, catalog) for node in ordered],
            "top": [_node_row(beam, node, catalog) for node in ordered[:20]],
            "cheap_admitted": [
                _node_row(beam, node, catalog) for node in admitted
            ],
            "back_most_y": max_y,
            "back_most": [
                _node_row(beam, node, catalog) for node in back_most[:20]
            ],
        },
        "admitted_child_scan_costs": child_costs,
        "actual_beam_5_30": {
            "seconds": trace_finished - trace_origin,
            "selected": None if selected is None else _proposal(selected),
            "child_scans": tracing_scanner.calls,
            "node_counts_by_depth": dict(
                sorted(Counter(node["depth"] for node in tracing_beam.nodes).items())
            ),
            "deepest_proven_count": max(
                (node["depth"] for node in tracing_beam.nodes), default=0
            ),
            "nodes": tracing_beam.nodes,
            "incumbents": tracing_beam.incumbents,
        },
        "physical_sequences": {
            "e2": _sequence(results / "task001-b-seed42-e2.json"),
            "staged_beam": _sequence(results / "task001-b-seed42-staged.json"),
            "staged_one_ply": _sequence(results / "task001-b-one-ply-seed42.json"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
