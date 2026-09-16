"""Read-only Task18d diagnosis for MaxRects-Regret candidate exhaustion.

This script never steps a physics environment.  It replays saved observations,
runs the current exact mask/proposal machinery, and profiles analytical selector
work.  Output is written atomically so a partial diagnostic cannot masquerade
as a completed result.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, Sequence
from unittest.mock import patch

from agents.support_extreme_fusion_beam_exact_mask.catalog import (
    CatalogStats,
    RootCatalog,
    RootRecord,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import LayeredProxy
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (
    RegretProxySelector,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (
    ProposalSource,
    iter_fused_records,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState
from tests.diagnose_support_extreme_fusion_initial_beam import _initial_case
from tests.replay_support import load_observation_snapshot


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "simulator" / "results" / "support_extreme_fusion"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def summarize_run(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records", ())
    timings = [
        float(value["policy_seconds"])
        for value in records
        if isinstance(value, dict) and "policy_seconds" in value
    ]
    if not timings:
        timings = [float(value) for value in payload.get("policy_times", ())]
    diagnostic = payload.get("diagnostic", {})
    traces = (
        diagnostic.get("b_search_traces", ())
        if isinstance(diagnostic, dict)
        else ()
    )
    if not traces:
        traces = payload.get("planner_diagnostics", ())
    trace_rows = [value.get("trace", value) for value in traces if isinstance(value, dict)]
    exception = payload.get("exception")
    exception_step = exception.get("step") if isinstance(exception, dict) else None
    reported_timing = payload.get("policy_time_seconds", {})
    if isinstance(reported_timing, dict) and "count" in reported_timing:
        policy_count = int(reported_timing.get("count", 0))
        policy_p50 = float(reported_timing.get("p50", 0.0))
        policy_p95 = float(reported_timing.get("p95", 0.0))
        policy_p99 = float(reported_timing.get("p99", 0.0))
        policy_max = float(reported_timing.get("max", 0.0))
    else:
        policy_count = len(timings)
        policy_p50 = _percentile(timings, 0.50)
        policy_p95 = _percentile(timings, 0.95)
        policy_p99 = _percentile(timings, 0.99)
        policy_max = max(timings, default=0.0)
    return {
        "status": payload.get("outcome", payload.get("status")),
        "failure_step": payload.get(
            "first_failure_step", payload.get("failure_step", exception_step)
        )
        if payload.get("first_failure_step") is not None
        else exception_step,
        "safe_placements": int(payload.get("safe_placements", 0)),
        "final_packed_count": int(payload.get("final_packed_count", 0)),
        "exception": exception,
        "policy_count": policy_count,
        "policy_p50": policy_p50,
        "policy_p95": policy_p95,
        "policy_p99": policy_p99,
        "policy_max": policy_max,
        "selector_deadline_steps": sum(
            bool(row.get("deadline_reached")) for row in trace_rows
        ),
        "selector_node_quota_steps": sum(
            bool(row.get("node_quota_exhausted")) for row in trace_rows
        ),
        "selector_fit_quota_steps": sum(
            bool(row.get("fit_quota_exhausted")) for row in trace_rows
        ),
        "selector_candidate_quota_steps": sum(
            bool(row.get("candidate_quota_exhausted")) for row in trace_rows
        ),
        "selector_trace_by_step": [
            {
                "step": row.get("step", ordinal),
                "nodes": int(row.get("nodes", 0)),
                "fit_tests": int(row.get("fit_tests", 0)),
                "candidates": int(row.get("candidates", 0)),
                "deepest": int(row.get("deepest", 0)),
                "deadline_reached": bool(row.get("deadline_reached", False)),
                "node_quota_exhausted": bool(row.get("node_quota_exhausted", False)),
                "fit_quota_exhausted": bool(row.get("fit_quota_exhausted", False)),
                "candidate_quota_exhausted": bool(
                    row.get("candidate_quota_exhausted", False)
                ),
            }
            for ordinal, row in enumerate(trace_rows)
        ],
        "evaluation": payload.get("evaluation", {}),
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    offset = (len(ordered) - 1) * float(quantile)
    lower = int(math.floor(offset))
    upper = int(math.ceil(offset))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (offset - lower)


def classify_exhaustion(
    default_scans: Sequence[dict[str, Any]],
    dense_sweep: Sequence[dict[str, Any]],
) -> str:
    if not default_scans:
        return "insufficient_evidence"
    if any(int(row.get("root_count", 0)) > 0 for row in default_scans):
        return "not_reproduced"
    if any(bool(row.get("deadline_reached")) for row in default_scans):
        return "default_scan_deadline"
    if any(int(row.get("accepted", 0)) > 0 for row in dense_sweep):
        return "candidate_exposure_cap"
    return "exact_candidate_exhaustion_unresolved"


def _stats_dict(stats: CatalogStats) -> dict[str, Any]:
    value = asdict(stats)
    value["rejection_counts"] = dict(stats.rejection_counts)
    value["stage_attempts"] = dict(stats.stage_attempts)
    value["stage_roots"] = dict(stats.stage_roots)
    return value


def _root_row(record: RootRecord) -> dict[str, Any]:
    proposal = record.proposal
    return {
        "pool_index": record.pool_index,
        "item_index": record.item_index,
        "container_index": record.container_index,
        "orientation": record.orientation,
        "position": [float(value) for value in proposal.position],
        "pass_name": record.pass_name,
        "sources": list(record.provenance.sources),
        "support_ratio": float(record.root.support_ratio),
        "min_clearance": float(record.root.min_clearance),
        "stable_key": list(record.stable_key),
    }


def scan_repeats(
    observation: dict,
    *,
    repeats: int,
    seconds: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for repeat in range(repeats):
        started = time.perf_counter()
        state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        built = time.perf_counter()
        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)
        catalog = scanner.scan(
            state,
            observation["pool_list"],
            deadline=started + seconds,
        )
        finished = time.perf_counter()
        rows.append(
            {
                "repeat": repeat,
                "build_seconds": built - started,
                "scan_seconds": finished - built,
                "total_seconds": finished - started,
                "root_count": len(catalog),
                "deadline_reached": catalog.stats.deadline_reached,
                "stats": _stats_dict(catalog.stats),
                "roots": [_root_row(record) for record in catalog.records],
            }
        )
    return rows


def dense_exact_sweep(
    state,
    pool: Sequence[dict],
    *,
    raw_limits: Iterable[int],
) -> list[dict[str, Any]]:
    settings = SearchSettings()
    mask = ExactMask(settings)
    rows: list[dict[str, Any]] = []
    for raw_limit in raw_limits:
        started = time.perf_counter()
        generated = accepted = 0
        per_pool: list[dict[str, Any]] = []
        rejection: Counter[str] = Counter()
        for pool_index, item in enumerate(pool):
            fused_values = tuple(
                iter_fused_records(
                    state,
                    item,
                    pool_index,
                    family_subset=(ProposalSource.DENSE_SUPPORT_LATTICE,),
                    settings=settings,
                    raw_work_limit=int(raw_limit),
                )
            )
            pool_accepted = 0
            first_accepted_ordinal: int | None = None
            for ordinal, fused in enumerate(fused_values):
                trace = mask.diagnose(state, pool, fused.proposal)
                if trace.accepted:
                    pool_accepted += 1
                    accepted += 1
                    if first_accepted_ordinal is None:
                        first_accepted_ordinal = ordinal
                else:
                    reason = trace.first_reason.value if trace.first_reason else "unknown"
                    rejection[reason] += 1
            generated += len(fused_values)
            per_pool.append(
                {
                    "pool_index": pool_index,
                    "generated": len(fused_values),
                    "accepted": pool_accepted,
                    "first_accepted_sorted_ordinal": first_accepted_ordinal,
                }
            )
        rows.append(
            {
                "raw_work_limit": int(raw_limit),
                "elapsed_seconds": time.perf_counter() - started,
                "generated": generated,
                "accepted": accepted,
                "per_pool": per_pool,
                "rejections": dict(sorted(rejection.items())),
            }
        )
    return rows


def dense_root_catalog(
    state,
    pool: Sequence[dict],
    *,
    raw_limit: int = 4096,
    per_pool_cap: int = 8,
    global_cap: int = 64,
) -> RootCatalog:
    """Build a diagnostic dense-only exact catalog without changing production."""

    settings = SearchSettings()
    mask = ExactMask(settings)
    records: list[RootRecord] = []
    per_pool_raw = [0] * len(pool)
    per_pool_roots = [0] * len(pool)
    rejections: Counter[str] = Counter()
    exact_attempts = 0
    for pool_index, item in enumerate(pool):
        if len(records) >= global_cap:
            break
        fused_values = iter_fused_records(
            state,
            item,
            pool_index,
            family_subset=(ProposalSource.DENSE_SUPPORT_LATTICE,),
            settings=settings,
            raw_work_limit=raw_limit,
        )
        for ordinal, fused in enumerate(fused_values):
            per_pool_raw[pool_index] += 1
            exact_attempts += 1
            trace = mask.diagnose(state, pool, fused.proposal)
            if not trace.accepted or trace.root is None:
                reason = trace.first_reason.value if trace.first_reason else "unknown"
                rejections[reason] += 1
                continue
            records.append(RootRecord(trace.root, fused.provenance, "diagnostic_dense", ordinal))
            per_pool_roots[pool_index] += 1
            if per_pool_roots[pool_index] >= per_pool_cap or len(records) >= global_cap:
                break
    stats = CatalogStats(
        raw_examined=sum(per_pool_raw),
        exact_attempts=exact_attempts,
        accepted_roots=len(records),
        rescue_roots=len(records),
        per_pool_raw=tuple(per_pool_raw),
        per_pool_roots=tuple(per_pool_roots),
        rejection_counts=tuple(sorted(rejections.items())),
        passes_completed=("diagnostic_dense",),
        stage_attempts=(("diagnostic.dense", exact_attempts),),
        stage_roots=(("diagnostic.dense", len(records)),),
        first_root_stage=tuple(
            "diagnostic.dense" if count else None for count in per_pool_roots
        ),
    )
    return RootCatalog(tuple(records), stats)


class StageProfiler:
    """Aggregate selector timings/work without mutating its outputs."""

    def __init__(self) -> None:
        self.phase = "idle"
        self.depth = 0
        self.lineage = -1
        self.totals: defaultdict[str, dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "seconds": 0.0, "outputs": 0}
        )
        self.by_depth_lineage: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.scheduling: list[dict[str, Any]] = []

    @property
    def context_key(self) -> str:
        return f"depth{self.depth}:lineage{self.lineage}"

    def add(self, name: str, seconds: float, outputs: int = 0) -> None:
        row = self.totals[name]
        row["calls"] += 1
        row["seconds"] += float(seconds)
        row["outputs"] += int(outputs)
        context = self.by_depth_lineage[self.context_key]
        context[f"{name}_calls"] += 1
        context[f"{name}_outputs"] += int(outputs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "totals": {
                name: {
                    "calls": int(value["calls"]),
                    "seconds": float(value["seconds"]),
                    "outputs": int(value["outputs"]),
                }
                for name, value in sorted(self.totals.items())
            },
            "by_depth_lineage": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.by_depth_lineage.items())
            },
            "scheduling": self.scheduling,
        }


class ProfilingProxy:
    def __init__(self, delegate: LayeredProxy, profiler: StageProfiler) -> None:
        self.delegate = delegate
        self.profiler = profiler

    def from_sim_state(self, sim):
        started = time.perf_counter()
        value = self.delegate.from_sim_state(sim)
        self.profiler.add("from_sim_state", time.perf_counter() - started, 1)
        return value

    def metrics(self, state):
        started = time.perf_counter()
        value = self.delegate.metrics(state)
        self.profiler.add("metrics", time.perf_counter() - started, 1)
        return value

    def enumerate_candidates(self, state, occurrence, work, quota):
        started = time.perf_counter()
        value = self.delegate.enumerate_candidates(state, occurrence, work, quota)
        fit_delta = value.work.fit_tests - work.fit_tests
        candidate_delta = value.work.candidates - work.candidates
        self.profiler.add(
            "enumerate_item", time.perf_counter() - started, len(value.candidates)
        )
        context = self.profiler.by_depth_lineage[self.profiler.context_key]
        context["fit_tests"] += fit_delta
        context["candidates"] += candidate_delta
        return value

    def apply(self, state, candidate):
        started = time.perf_counter()
        value = self.delegate.apply(state, candidate)
        self.profiler.add("proxy_apply", time.perf_counter() - started, 1)
        return value


class ProfilingSelector(RegretProxySelector):
    def __init__(self, *args, profiler: StageProfiler, **kwargs) -> None:
        self.profiler = profiler
        super().__init__(*args, **kwargs)

    def _analyze(self, node, work, deadline, local_quota):
        old = (self.profiler.phase, self.profiler.depth, self.profiler.lineage)
        self.profiler.phase = "analyze"
        self.profiler.depth = node.depth
        self.profiler.lineage = node.lineage_id
        started = time.perf_counter()
        try:
            result = super()._analyze(node, work, deadline, local_quota)
            self.profiler.add("analyze_node", time.perf_counter() - started, len(result[1]))
            return result
        finally:
            self.profiler.phase, self.profiler.depth, self.profiler.lineage = old

    def _fair_prune(self, nodes):
        started = time.perf_counter()
        result = super()._fair_prune(nodes)
        self.profiler.add("fair_prune", time.perf_counter() - started, len(result))
        self.profiler.scheduling.append(
            {
                "input_nodes": len(nodes),
                "output_nodes": len(result),
                "input_by_depth": dict(Counter(str(node.depth) for node in nodes)),
                "output_by_depth": dict(Counter(str(node.depth) for node in result)),
                "output_by_lineage": dict(
                    Counter(str(node.lineage_id) for node in result)
                ),
            }
        )
        return result


def profile_selector(
    state,
    pool: Sequence[dict],
    catalog: RootCatalog,
    *,
    seconds: float,
) -> dict[str, Any]:
    settings = SearchSettings()
    mask = ExactMask(settings)
    profiler = StageProfiler()
    proxy = ProfilingProxy(LayeredProxy(), profiler)
    selector = ProfilingSelector(mask, settings=settings, proxy=proxy, profiler=profiler)
    sim = SimState.from_current(state, pool)

    import agents.support_extreme_fusion_beam_exact_mask.layered_proxy as proxy_module
    import agents.support_extreme_fusion_beam_exact_mask.maxrects_regret as selector_module

    real_apply_root = selector_module.apply_root
    real_proxy_rectangles = proxy_module.maximal_empty_rectangles
    real_selector_rectangles = selector_module.maximal_empty_rectangles

    def timed_apply_root(*args, **kwargs):
        started = time.perf_counter()
        value = real_apply_root(*args, **kwargs)
        profiler.add("depth0_fresh_apply", time.perf_counter() - started, 1)
        return value

    def timed_proxy_rectangles(*args, **kwargs):
        started = time.perf_counter()
        value = real_proxy_rectangles(*args, **kwargs)
        profiler.add("maximal_rectangles", time.perf_counter() - started, len(value))
        return value

    def timed_selector_rectangles(*args, **kwargs):
        started = time.perf_counter()
        value = real_selector_rectangles(*args, **kwargs)
        profiler.add("rank_maximal_rectangles", time.perf_counter() - started, len(value))
        return value

    started = time.perf_counter()
    with ExitStack() as stack:
        stack.enter_context(patch.object(selector_module, "apply_root", timed_apply_root))
        stack.enter_context(
            patch.object(proxy_module, "maximal_empty_rectangles", timed_proxy_rectangles)
        )
        stack.enter_context(
            patch.object(selector_module, "maximal_empty_rectangles", timed_selector_rectangles)
        )
        ranked = selector.select(sim, catalog, "B", started + seconds)
    elapsed = time.perf_counter() - started
    selected = None
    if ranked:
        selected_record = next(
            record for record in catalog.records if record.root is ranked[0]
        )
        selected = _root_row(selected_record)
    return {
        "elapsed_seconds": elapsed,
        "input_root_count": len(catalog),
        "returned_root_count": len(ranked),
        "selected": selected,
        "trace": asdict(selector.last_trace),
        "profile": profiler.as_dict(),
    }


def _case_from_snapshot(path: Path):
    observation, metadata = load_observation_snapshot(path)
    state = build_packing_state(
        observation["container_list"], observation.get("depth_map")
    )
    return state, observation["pool_list"], metadata


def reproduce_case(
    name: str,
    state,
    pool: Sequence[dict],
    *,
    repeats: int,
    seconds: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for repeat in range(repeats):
        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)
        started = time.perf_counter()
        catalog = scanner.scan(state, pool, deadline=started + seconds)
        after_scan = time.perf_counter()
        if catalog and after_scan < started + seconds:
            selector = RegretProxySelector(mask, settings=settings)
            ranked = selector.select(
                SimState.from_current(state, pool), catalog, "B", started + seconds
            )
            raw_trace = selector.last_trace
            trace = {
                "nodes": raw_trace.nodes,
                "fit_tests": raw_trace.fit_tests,
                "candidates": raw_trace.candidates,
                "deepest": raw_trace.deepest,
                "deadline_reached": raw_trace.deadline_reached,
                "node_quota_exhausted": raw_trace.node_quota_exhausted,
                "fit_quota_exhausted": raw_trace.fit_quota_exhausted,
                "candidate_quota_exhausted": raw_trace.candidate_quota_exhausted,
                "invalid_lineages": raw_trace.invalid_lineages,
                "branch_exceptions": raw_trace.branch_exceptions,
                "lineage_count": len(raw_trace.root_lineages),
                "predicted_count": raw_trace.predicted_count,
                "predicted_volume": raw_trace.predicted_volume,
                "largest_free_region": raw_trace.largest_free_region,
                "top_ranked_key": list(raw_trace.ranked_keys[0])
                if raw_trace.ranked_keys
                else None,
            }
        else:
            ranked = ()
            trace = None
        chosen = None
        if ranked:
            record = next(record for record in catalog.records if record.root is ranked[0])
            chosen = _root_row(record)
        rows.append(
            {
                "repeat": repeat,
                "catalog_roots": len(catalog),
                "scan_seconds": after_scan - started,
                "total_seconds": time.perf_counter() - started,
                "scan_deadline": catalog.stats.deadline_reached,
                "chosen": chosen,
                "selector_trace": trace,
            }
        )
    signatures = [
        None
        if row["chosen"] is None
        else (
            row["chosen"]["pool_index"],
            row["chosen"]["container_index"],
            row["chosen"]["orientation"],
            tuple(row["chosen"]["position"]),
        )
        for row in rows
    ]
    return {
        "name": name,
        "pool_size": len(pool),
        "repeats": rows,
        "deterministic_choice": len(set(map(repr, signatures))) == 1,
    }


def diagnose(
    run_json: Path,
    failure_snapshot: Path,
    step8_snapshot: Path,
    *,
    scan_repetitions: int = 3,
    replay_repetitions: int = 2,
    replay_seconds: float = 2.0,
    dense_limits: Sequence[int] = (256, 1024, 2048, 3072, 4096),
) -> dict[str, Any]:
    run_payload = json.loads(Path(run_json).read_text(encoding="utf-8"))
    observation, failure_metadata = load_observation_snapshot(failure_snapshot)
    state = build_packing_state(
        observation["container_list"], observation.get("depth_map")
    )
    pool = observation["pool_list"]
    default_scans = scan_repeats(
        observation,
        repeats=scan_repetitions,
        seconds=SearchSettings().bc_planning_limit_seconds,
    )
    dense_sweep = dense_exact_sweep(state, pool, raw_limits=dense_limits)
    diagnostic_catalog = dense_root_catalog(state, pool)
    selector_profile = profile_selector(
        state,
        pool,
        diagnostic_catalog,
        seconds=SearchSettings().bc_search_limit_seconds,
    )

    initial_state, initial_pool, _ = _initial_case()
    step8_state, step8_pool, step8_metadata = _case_from_snapshot(step8_snapshot)
    replay = {
        "initial": reproduce_case(
            "initial",
            initial_state,
            initial_pool,
            repeats=replay_repetitions,
            seconds=replay_seconds,
        ),
        "step8": reproduce_case(
            "step8",
            step8_state,
            step8_pool,
            repeats=replay_repetitions,
            seconds=replay_seconds,
        ),
        "step15": reproduce_case(
            "step15", state, pool, repeats=replay_repetitions, seconds=5.45
        ),
    }
    classification = classify_exhaustion(default_scans, dense_sweep)
    return {
        "schema": "support-extreme-fusion-task18d-v1",
        "generated_at_unix": time.time(),
        "sources": {
            "run_json": str(Path(run_json).resolve()),
            "run_json_sha256": sha256_file(run_json),
            "failure_snapshot": str(Path(failure_snapshot).resolve()),
            "failure_snapshot_sha256": sha256_file(failure_snapshot),
            "step8_snapshot": str(Path(step8_snapshot).resolve()),
            "step8_snapshot_sha256": sha256_file(step8_snapshot),
        },
        "run": summarize_run(run_payload),
        "failure_metadata": failure_metadata,
        "step8_metadata": step8_metadata,
        "placed_items_at_snapshot": sum(
            len(container.get("packed_items", ()))
            for container in observation["container_list"]
        ),
        "pool_size_at_snapshot": len(pool),
        "authoritative_exact_exhaustion": {
            "classification": classification,
            "default_scans": default_scans,
            "dense_sweep": dense_sweep,
            "diagnostic_dense_catalog": {
                "roots": len(diagnostic_catalog),
                "stats": _stats_dict(diagnostic_catalog.stats),
                "records": [_root_row(record) for record in diagnostic_catalog.records],
            },
        },
        "selector_stage_profile": selector_profile,
        "frozen_replay": replay,
        "interpretation": {
            "terminal_cause": classification,
            "terminal_selector_invoked": False,
            "exact_mask_relaxation_supported": False,
            "ranked_single_factor_hypotheses": [
                "increase dense-rescue raw exposure only when the strict catalog is globally empty",
                "make zero-root dense exposure adaptive and stop after the first exact root per occurrence",
                "add earlier-state future-support avoidance only after candidate-exposure recovery is measured",
            ],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-json",
        type=Path,
        default=RESULTS / "task001-b-maxrects-regret-seed42.json",
    )
    parser.add_argument(
        "--failure-snapshot",
        type=Path,
        default=RESULTS / "task001-b-maxrects-regret-seed42-failure.npz",
    )
    parser.add_argument(
        "--step8-snapshot",
        type=Path,
        default=RESULTS / "task001-b-seed42-failure.npz",
    )
    parser.add_argument("--scan-repetitions", type=int, default=3)
    parser.add_argument("--replay-repetitions", type=int, default=2)
    parser.add_argument("--replay-seconds", type=float, default=2.0)
    parser.add_argument(
        "--dense-limits", type=int, nargs="+", default=[256, 1024, 2048, 3072, 4096]
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = diagnose(
        args.run_json,
        args.failure_snapshot,
        args.step8_snapshot,
        scan_repetitions=max(1, args.scan_repetitions),
        replay_repetitions=max(1, args.replay_repetitions),
        replay_seconds=max(0.1, float(args.replay_seconds)),
        dense_limits=tuple(sorted(set(args.dense_limits))),
    )
    atomic_write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "classification": result["authoritative_exact_exhaustion"]["classification"],
        "sha256": sha256_file(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
