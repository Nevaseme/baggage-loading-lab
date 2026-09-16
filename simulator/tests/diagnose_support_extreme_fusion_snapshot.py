"""Read-only exact-root/beam diagnostics for one saved failure snapshot."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
import time
from typing import Any

from agents.support_extreme_fusion_beam_exact_mask.beam import FutureSupportIngressBeam
from agents.support_extreme_fusion_beam_exact_mask.catalog import RootCatalog, StrictRootScanner
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState, apply_root
from tests.replay_support import load_observation_snapshot


def _record_summary(record) -> dict[str, Any]:
    return {
        "pool_index": record.pool_index,
        "item_index": record.item_index,
        "container_index": record.container_index,
        "orientation": record.orientation,
        "position": list(record.proposal.position),
        "pass_name": record.pass_name,
        "proposal_source": record.proposal.source,
        "sources": list(record.provenance.sources),
        "support_sources": list(record.provenance.support_sources),
        "support_levels": list(record.provenance.support_levels),
        "support_ratio": record.root.support_ratio,
        "min_clearance": record.root.min_clearance,
    }


def _catalog_summary(catalog: RootCatalog, elapsed: float) -> dict[str, Any]:
    records = [_record_summary(record) for record in catalog.records]
    return {
        "elapsed_seconds": elapsed,
        "root_count": len(records),
        "roots_per_pool": dict(Counter(str(record["pool_index"]) for record in records)),
        "roots_per_pass": dict(Counter(record["pass_name"] for record in records)),
        "roots_per_orientation": dict(
            Counter(str(record["orientation"]) for record in records)
        ),
        "roots_per_container": dict(
            Counter(str(record["container_index"]) for record in records)
        ),
        "roots_per_source": dict(
            Counter(source for record in records for source in record["sources"])
        ),
        "stats": asdict(catalog.stats),
        "records": records,
    }


def _scan(
    state,
    pool,
    settings: SearchSettings,
    *,
    seconds: float,
    allow_rescue: bool,
) -> tuple[StrictRootScanner, ExactMask, RootCatalog, dict[str, Any]]:
    mask = ExactMask(settings)
    scanner = StrictRootScanner(settings, mask=mask)
    started = time.perf_counter()
    catalog = scanner.scan(
        state,
        pool,
        deadline=started + seconds,
        allow_rescue=allow_rescue,
    )
    elapsed = time.perf_counter() - started
    return scanner, mask, catalog, _catalog_summary(catalog, elapsed)


def _trace_edges(state, pool, settings, scanner, mask, catalog) -> dict[str, Any]:
    beam = FutureSupportIngressBeam(
        scanner,
        mask,
        settings,
        beam_width=settings.bc_beam_width,
        max_depth=settings.bc_beam_depth,
        item_choices=settings.bc_item_choices,
        roots_per_item=settings.bc_roots_per_item,
    )
    sim = SimState.from_current(state, pool)
    current = beam._current_records(catalog, sim)
    edges: list[dict[str, Any]] = []
    for record in current:
        edge: dict[str, Any] = {
            "root": _record_summary(record),
            "apply_ok": False,
            "child_normal_roots": None,
        }
        try:
            placement = apply_root(
                sim,
                record.root,
                settings,
                exact_revalidator=mask,
                deadline=time.perf_counter() + 60.0,
            )
            edge["apply_ok"] = True
            child_started = time.perf_counter()
            child_catalog = scanner.scan(
                placement.child.packing,
                placement.child.pool,
                deadline=child_started + 10.0,
                breadth_rescue=False,
                allow_deferred=False,
                allow_rescue=False,
            )
            edge["child_scan_seconds"] = time.perf_counter() - child_started
            edge["child_normal_roots"] = len(child_catalog)
            edge["child_roots_per_pool"] = list(child_catalog.stats.per_pool_roots)
            edge["child_rejections"] = dict(child_catalog.stats.rejection_counts)
        except Exception as error:
            edge["exception"] = f"{type(error).__name__}: {error}"
        edges.append(edge)
    return {
        "catalog_roots": len(catalog),
        "current_binding_roots": len(current),
        "apply_ok_roots": sum(bool(edge["apply_ok"]) for edge in edges),
        "edges": edges,
    }


def diagnose(snapshot: Path, *, repeats: int, generous_seconds: float) -> dict[str, Any]:
    observation, metadata = load_observation_snapshot(snapshot)
    pool = observation["pool_list"]
    build_started = time.perf_counter()
    state = build_packing_state(
        observation["container_list"], observation.get("depth_map")
    )
    build_seconds = time.perf_counter() - build_started
    default = SearchSettings()
    report: dict[str, Any] = {
        "snapshot": str(snapshot.resolve()),
        "metadata": metadata,
        "state_build_seconds": build_seconds,
        "pool": [
            {
                "pool_index": index,
                "item_index": item["index"],
                "dimensions": [item["length"], item["width"], item["height"]],
                "soft": bool(item.get("is_soft", False)),
                "prioritized": bool(item.get("is_prioritized", False)),
            }
            for index, item in enumerate(pool)
        ],
        "placed_items": sum(
            len(container.get("packed_items", ()))
            for container in observation["container_list"]
        ),
        "online_repeats": [],
    }

    last_scan = None
    for repeat in range(repeats):
        policy_started = time.perf_counter()
        repeated_state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        mask = ExactMask(default)
        scanner = StrictRootScanner(default, mask=mask)
        scan_started = time.perf_counter()
        catalog = scanner.scan(
            repeated_state,
            pool,
            deadline=policy_started + default.bc_planning_limit_seconds,
        )
        scan_finished = time.perf_counter()
        beam = FutureSupportIngressBeam(
            scanner,
            mask,
            default,
            beam_width=default.bc_beam_width,
            max_depth=default.bc_beam_depth,
            item_choices=default.bc_item_choices,
            roots_per_item=default.bc_roots_per_item,
        )
        before_beam = time.perf_counter()
        root = beam.choose_b(
            repeated_state,
            pool,
            catalog,
            policy_started + default.bc_search_limit_seconds,
        )
        finished = time.perf_counter()
        row = _catalog_summary(catalog, scan_finished - scan_started)
        row.update(
            {
                "repeat": repeat,
                "policy_elapsed_before_beam": before_beam - policy_started,
                "beam_budget_remaining_at_entry": (
                    policy_started + default.bc_search_limit_seconds - before_beam
                ),
                "beam_seconds": finished - before_beam,
                "beam_returned_root": root is not None,
                "total_seconds": finished - policy_started,
            }
        )
        report["online_repeats"].append(row)
        last_scan = (scanner, mask, catalog)

    _, _, normal_catalog, normal_summary = _scan(
        state,
        pool,
        default,
        seconds=default.bc_planning_limit_seconds,
        allow_rescue=False,
    )
    report["default_normal_only"] = normal_summary

    generous = replace(
        default,
        normal_catalog_limit_seconds=float(generous_seconds),
        zero_root_rescue_limit_seconds=float(generous_seconds) * 2.0,
        bc_search_limit_seconds=float(generous_seconds) * 2.0,
        bc_planning_limit_seconds=float(generous_seconds) * 2.0,
        bc_policy_hard_limit_seconds=float(generous_seconds) * 2.0 + 1.0,
    )
    generous_scanner, generous_mask, generous_catalog, generous_summary = _scan(
        state,
        pool,
        generous,
        seconds=float(generous_seconds) * 2.0,
        allow_rescue=True,
    )
    report["generous_scan"] = generous_summary
    report["generous_edge_trace"] = _trace_edges(
        state,
        pool,
        generous,
        generous_scanner,
        generous_mask,
        generous_catalog,
    )

    if last_scan is not None:
        report["last_online_edge_trace"] = _trace_edges(
            state, pool, default, *last_scan
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--generous-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(
        args.snapshot,
        repeats=max(1, args.repeats),
        generous_seconds=max(1.0, args.generous_seconds),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
