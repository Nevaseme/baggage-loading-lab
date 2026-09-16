"""Run exact-mask A/B/C agents in the official Gymnasium/PyBullet environment.

The runner is deliberately diagnostic and fail closed.  It validates every
public action before calling ``env.step`` and persists both successful and
failed runs atomically as JSON.  It does not add a fallback action or alter
production policy behavior.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Sequence

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]

from agents.support_extreme_fusion_beam_exact_mask.agent import (  # noqa: E402
    Agent,
    CandidateZeroError,
    NotReadyError,
    PlanningError,
)
from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    AdaptiveDenseRescueConfig,
    CatalogStats,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.fixed_quota import (  # noqa: E402
    BSearchTrace,
    FixedQuotaExactTwoPly,
)
from agents.support_extreme_fusion_beam_exact_mask.maxrects_regret import (  # noqa: E402
    MemoizedStreamingRegretProxySelector,
    RankObjective,
    RegretProxySelector,
    SelectionTrace,
)
from agents.support_extreme_fusion_beam_exact_mask.layered_proxy import (  # noqa: E402
    ProxyExposureOrder,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import (  # noqa: E402
    SearchSettings,
)
from agents.support_extreme_fusion_beam_exact_mask.transition import SimState  # noqa: E402
from tests.replay_support import save_observation_snapshot  # noqa: E402


STATUS_ORDER = ("is_included", "is_valid", "is_placed_safe")
AGENT_MODULE_PATH = "agents/support_extreme_fusion_beam_exact_mask/"
HISTORICAL_CONTROL_ALGORITHM = (
    "conservative_extreme_point_packing_historical_control"
)
HISTORICAL_CONTROL_SOURCE_SHA256 = (
    "EBE909962AB3A0722ABB5ED3E67A42DCEB64B116DD1F374C9EF739FDD3967F82"
)
RESULTS_ROOT = (SIMULATOR_ROOT / "results").resolve()


class ActionFormatError(RuntimeError):
    """Raised before physics when an agent action is not publicly well formed."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate support-extreme-fusion exact-mask A/B/C in official physics"
    )
    parser.add_argument("--task", choices=("000", "001"), required=True)
    parser.add_argument("--items", type=_positive_int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mode", choices=("auto", "A", "B", "C"), default="auto")
    parser.add_argument(
        "--b-planner",
        choices=(
            "beam",
            "one-ply",
            "fixed-two-ply",
            "maxrects-regret",
            "memoized-streaming-maxrects-regret",
            "memoized-stratified-maxrects-regret",
        ),
        default="beam",
        help="diagnostic mode-B planner route; one-ply reuses the exact C root rank",
    )
    parser.add_argument(
        "--candidate-rescue",
        choices=("legacy", "global-zero-adaptive-dense"),
        default="legacy",
        help="diagnostic candidate exposure; adaptive dense is explicit mode-B only",
    )
    parser.add_argument(
        "--a-candidate-rescue",
        choices=("legacy", "global-zero-adaptive-dense-12288"),
        default="legacy",
        help="diagnostic candidate exposure; 12288 dense rescue is explicit mode-A only",
    )
    parser.add_argument(
        "--a-order-fallback",
        choices=("original", "proxy-prefix"),
        default="original",
        help="diagnostic Mode-A order fallback; proxy-prefix never stores a plan",
    )
    parser.add_argument(
        "--a-order-source",
        choices=("agent", "historical-control-json"),
        default="agent",
        help="explicit Mode-A order evidence; historical JSON contributes order only",
    )
    parser.add_argument(
        "--a-order-json",
        type=Path,
        help="validated historical-control result inside simulator/results",
    )
    parser.add_argument(
        "--b-rank-objective",
        choices=("legacy", "continuation-survival"),
        default="legacy",
        help="diagnostic rank objective; effective only for explicit mode-B stratified rollout",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--snapshot-on-failure",
        type=Path,
        help="atomically save the pre-action observation for the first policy/physics failure",
    )
    return parser


def materialize_config(
    sample_config: dict[str, Any],
    task: str,
    items: int,
    mode: str,
) -> dict[str, Any]:
    if task not in ("000", "001") or task not in sample_config:
        raise ValueError("task must select sample task 000 or 001")
    if type(items) is not int or items <= 0:
        raise ValueError("items must be a positive integer")
    if mode not in ("auto", "A", "B", "C"):
        raise ValueError("mode must be auto, A, B, or C")
    config = copy.deepcopy(sample_config[task])
    item_stream = config["item_stream"]
    item_stream["item_list"] = list(item_stream["item_list"][:items])
    config.setdefault("visualizer", {})["vis"] = False
    config.setdefault("agent", {})
    if mode == "A":
        config["agent"]["optimize"] = True
    elif mode == "B":
        config["agent"]["optimize"] = False
        item_stream["look_ahead"] = max(2, int(item_stream.get("look_ahead", 2)))
    elif mode == "C":
        config["agent"]["optimize"] = False
        item_stream["look_ahead"] = 1
    return config


def _mode_init_state(init_state: dict[str, Any], requested_mode: str) -> dict[str, Any]:
    value = copy.deepcopy(init_state)
    if requested_mode == "A":
        value["optimize"] = True
    elif requested_mode == "B":
        value["optimize"] = False
        value["lookahead_k"] = max(2, int(value.get("lookahead_k", 2)))
    elif requested_mode == "C":
        value["optimize"] = False
        value["lookahead_k"] = 1
    return value


def _resolved_mode(init_state: dict[str, Any]) -> str:
    if bool(init_state.get("optimize", False)):
        return "A"
    return "B" if int(init_state.get("lookahead_k", 1)) > 1 else "C"


def action_format_is_valid(action: Any, observation: Any | None = None) -> bool:
    if not isinstance(action, dict):
        return False
    required_keys = {"item_idx", "container_idx", "place_pos", "orientation"}
    if set(action) != required_keys:
        return False
    if any(type(action[key]) is not int for key in ("item_idx", "container_idx", "orientation")):
        return False
    if action["item_idx"] < 0 or action["container_idx"] < 0:
        return False
    if observation is not None:
        if not isinstance(observation, dict):
            return False
        pool = observation.get("pool_list")
        containers = observation.get("container_list")
        if not isinstance(pool, Sequence) or isinstance(pool, (str, bytes)):
            return False
        if not isinstance(containers, Sequence) or isinstance(containers, (str, bytes)):
            return False
        if action["item_idx"] >= len(pool) or action["container_idx"] >= len(containers):
            return False
    if action["orientation"] not in range(6):
        return False
    try:
        position = np.asarray(action["place_pos"], dtype=np.float64)
    except (TypeError, ValueError):
        return False
    return position.shape == (3,) and bool(np.all(np.isfinite(position)))


def status_format_is_valid(status: Any) -> bool:
    return isinstance(status, dict) and all(
        key in status and type(status[key]) is bool for key in STATUS_ORDER
    )


def _serialize_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_idx": int(action["item_idx"]),
        "container_idx": int(action["container_idx"]),
        "place_pos": [float(value) for value in np.asarray(action["place_pos"]).reshape(3)],
        "orientation": int(action["orientation"]),
    }


def _first_failed_predicate(status: Any) -> str | None:
    if not status_format_is_valid(status):
        return "malformed_status"
    for key in STATUS_ORDER:
        if not status[key]:
            return key
    return None


def _packed_count(observation: Any) -> int:
    if not isinstance(observation, dict):
        return 0
    return sum(
        len(container.get("packed_items", ()))
        for container in observation.get("container_list", ())
        if isinstance(container, dict)
    )


def _timing_summary(values: Sequence[float]) -> dict[str, float | int]:
    finite = np.asarray([float(value) for value in values if math.isfinite(float(value))])
    if finite.size == 0:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": int(finite.size),
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
        "p99": float(np.percentile(finite, 99)),
        "max": float(np.max(finite)),
    }


def _exception_category(error: BaseException) -> str:
    if isinstance(error, CandidateZeroError):
        return "candidate_zero"
    if isinstance(error, PlanningError):
        return "planning_error"
    if isinstance(error, NotReadyError):
        return "not_ready"
    return "other_exception"


def _default_env_factory(config: dict[str, Any]):
    from src.ground_handling.env import GroundHandlingEnv

    return GroundHandlingEnv(config=config, verbose=False, render_mode=None)


def _default_agent_factory() -> Agent:
    return Agent(AGENT_MODULE_PATH)


class _BOnePlyBeamAdapter:
    """Runner-only adapter that replaces B continuation with exact one-ply rank."""

    def __init__(self, beam: Any) -> None:
        self._beam = beam

    def choose_b(self, state, pool, catalog, deadline):
        return self._beam.choose_c(state, pool, catalog, deadline)


class _BFixedTwoPlyBeamAdapter:
    """Runner-only B dispatch to the independently bounded exact planner."""

    def __init__(self, original_beam: Any, planner: FixedQuotaExactTwoPly) -> None:
        self._original_beam = original_beam
        self._planner = planner
        self._trace_revision = 0
        self._last_invoked_trace: BSearchTrace | None = None

    @property
    def last_trace(self) -> BSearchTrace:
        return self._last_invoked_trace or BSearchTrace()

    def choose_b(self, state, pool, catalog, deadline):
        self._trace_revision += 1
        self._last_invoked_trace = None
        selected = self._planner.choose_b(state, pool, catalog, deadline)
        trace = getattr(self._planner, "last_trace", None)
        self._last_invoked_trace = trace if isinstance(trace, BSearchTrace) else None
        return selected

    def choose_c(self, state, pool, catalog, deadline):
        return self._original_beam.choose_c(state, pool, catalog, deadline)


class _BMaxRectsRegretBeamAdapter:
    """Runner-only B dispatch to LayeredProxy regret ranking."""

    def __init__(
        self,
        original_beam: Any,
        scanner: Any,
        selector: RegretProxySelector,
    ) -> None:
        self._original_beam = original_beam
        self._scanner = scanner
        self._selector = selector
        self._trace_revision = 0
        self._last_invoked_trace: SelectionTrace | None = None

    @property
    def last_trace(self) -> SelectionTrace:
        return self._last_invoked_trace or SelectionTrace()

    def choose_b(self, state, pool, catalog, deadline):
        self._trace_revision += 1
        self._last_invoked_trace = None
        sim = SimState.from_current(state, pool)
        ranked = self._selector.select(sim, catalog, "B", deadline)
        if type(ranked) is not tuple:
            raise TypeError("maxrects-regret selector must return a root tuple")
        trace = getattr(self._selector, "last_trace", None)
        self._last_invoked_trace = trace if isinstance(trace, SelectionTrace) else None
        return ranked[0] if ranked else None

    def choose_c(self, state, pool, catalog, deadline):
        return self._original_beam.choose_c(state, pool, catalog, deadline)


class _AdaptiveScannerRecorder:
    """Runner-only scanner proxy retaining the first catalog of each policy."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self._capture_next = False
        self._initial_stats: CatalogStats | None = None

    def begin_policy(self) -> None:
        self._capture_next = True
        self._initial_stats = None

    def consume_initial_stats(self) -> CatalogStats | None:
        value = self._initial_stats
        self._initial_stats = None
        self._capture_next = False
        return value

    def scan(self, *args, **kwargs):
        catalog = self.delegate.scan(*args, **kwargs)
        if self._capture_next and self._initial_stats is None:
            stats = getattr(catalog, "stats", None)
            if isinstance(stats, CatalogStats):
                self._initial_stats = stats
            self._capture_next = False
        return catalog

    def scan_coverage_fixed(self, *args, **kwargs):
        return self.delegate.scan_coverage_fixed(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


def _install_candidate_rescue(
    agent: Any,
    *,
    requested_mode: str,
    resolved_mode: str,
    candidate_rescue: str,
) -> bool:
    if candidate_rescue not in ("legacy", "global-zero-adaptive-dense"):
        raise ValueError(
            "candidate_rescue must be legacy or global-zero-adaptive-dense"
        )
    if not (
        candidate_rescue == "global-zero-adaptive-dense"
        and requested_mode == "B"
        and resolved_mode == "B"
    ):
        return False
    settings = getattr(agent, "settings", None)
    exact_mask = getattr(agent, "exact_mask", None)
    original_scanner = getattr(agent, "scanner", None)
    beam = getattr(agent, "beam", None)
    if settings is None or exact_mask is None or original_scanner is None or beam is None:
        raise TypeError(
            "adaptive dense diagnostics require Agent scanner/beam/exact_mask/settings"
        )
    scanner = StrictRootScanner(
        settings,
        mask=exact_mask,
        adaptive_dense_rescue=AdaptiveDenseRescueConfig(),
    )
    recording = _AdaptiveScannerRecorder(scanner)
    agent.scanner = recording
    if hasattr(beam, "scanner"):
        beam.scanner = recording
    return True


def _candidate_rescue_settings(
    candidate_rescue: str,
    *,
    effective: bool = False,
) -> dict[str, Any]:
    if candidate_rescue not in ("legacy", "global-zero-adaptive-dense"):
        raise ValueError(
            "candidate_rescue must be legacy or global-zero-adaptive-dense"
        )
    enabled = bool(
        effective and candidate_rescue == "global-zero-adaptive-dense"
    )
    base = {
        "requested": candidate_rescue,
        "effective": (
            "global-zero-adaptive-dense" if enabled else "legacy"
        ),
        "enabled": enabled,
    }
    if not enabled:
        return base
    config = AdaptiveDenseRescueConfig()
    return {
        **base,
        "raw_work_limit": config.raw_work_limit,
        "covered_occurrence_target": config.covered_occurrence_target,
        "output_reserve_seconds": config.output_reserve_seconds,
    }


def _install_a_candidate_rescue(
    agent: Any,
    *,
    requested_mode: str,
    resolved_mode: str,
    a_candidate_rescue: str,
) -> bool:
    allowed = ("legacy", "global-zero-adaptive-dense-12288")
    if a_candidate_rescue not in allowed:
        raise ValueError(
            "a_candidate_rescue must be legacy or "
            "global-zero-adaptive-dense-12288"
        )
    if not (
        a_candidate_rescue == "global-zero-adaptive-dense-12288"
        and requested_mode == "A"
        and resolved_mode == "A"
    ):
        return False
    settings = getattr(agent, "settings", None)
    exact_mask = getattr(agent, "exact_mask", None)
    original_scanner = getattr(agent, "scanner", None)
    if settings is None or exact_mask is None or original_scanner is None:
        raise TypeError(
            "mode-A adaptive dense diagnostics require Agent "
            "scanner/exact_mask/settings"
        )
    scanner = StrictRootScanner(
        settings,
        mask=exact_mask,
        adaptive_dense_rescue=AdaptiveDenseRescueConfig(
            raw_work_limit=12_288,
            covered_occurrence_target=8,
            output_reserve_seconds=0.75,
        ),
    )
    agent.scanner = _AdaptiveScannerRecorder(scanner)
    return True


def _a_candidate_rescue_settings(
    a_candidate_rescue: str,
    *,
    effective: bool = False,
) -> dict[str, Any]:
    allowed = ("legacy", "global-zero-adaptive-dense-12288")
    if a_candidate_rescue not in allowed:
        raise ValueError(f"unsupported a_candidate_rescue: {a_candidate_rescue}")
    enabled = bool(
        effective
        and a_candidate_rescue == "global-zero-adaptive-dense-12288"
    )
    base = {
        "requested": a_candidate_rescue,
        "effective": (
            "global-zero-adaptive-dense-12288" if enabled else "legacy"
        ),
        "enabled": enabled,
    }
    if not enabled:
        return base
    config = AdaptiveDenseRescueConfig(
        raw_work_limit=12_288,
        covered_occurrence_target=8,
        output_reserve_seconds=0.75,
    )
    return {
        **base,
        "raw_work_limit": config.raw_work_limit,
        "covered_occurrence_target": config.covered_occurrence_target,
        "output_reserve_seconds": config.output_reserve_seconds,
    }


def _install_a_order_fallback(
    agent: Any,
    *,
    requested_mode: str,
    resolved_mode: str,
    a_order_fallback: str,
) -> bool:
    if a_order_fallback not in ("original", "proxy-prefix"):
        raise ValueError("a_order_fallback must be original or proxy-prefix")
    enabled = bool(
        a_order_fallback == "proxy-prefix"
        and requested_mode == "A"
        and resolved_mode == "A"
    )
    if not enabled:
        return False
    settings = getattr(agent, "settings", None)
    if not isinstance(settings, SearchSettings):
        raise TypeError("Mode-A proxy-prefix diagnostics require SearchSettings")
    agent.settings = replace(
        settings, mode_a_proxy_prefix_order_fallback=True
    )
    return True


def _a_order_fallback_settings(
    a_order_fallback: str,
    *,
    effective: bool = False,
) -> dict[str, Any]:
    if a_order_fallback not in ("original", "proxy-prefix"):
        raise ValueError(f"unsupported a_order_fallback: {a_order_fallback}")
    enabled = bool(effective and a_order_fallback == "proxy-prefix")
    return {
        "requested": a_order_fallback,
        "effective": "proxy-prefix" if enabled else "original",
        "enabled": enabled,
    }


def _a_order_source_settings(
    a_order_source: str,
    a_order_json: Path | str | None,
    *,
    effective: bool = False,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if a_order_source not in ("agent", "historical-control-json"):
        raise ValueError(f"unsupported a_order_source: {a_order_source}")
    enabled = bool(effective and a_order_source == "historical-control-json")
    result = {
        "requested": a_order_source,
        "requested_order_json": None if a_order_json is None else str(a_order_json),
        "effective": "historical-control-json" if enabled else "agent",
        "enabled": enabled,
    }
    if enabled and evidence is not None:
        result.update(copy.deepcopy(evidence))
    return result


def _load_historical_control_order(
    path: Path | str,
    *,
    expected_order: Sequence[int],
    task: str,
    requested_items: int,
    seed: int,
    results_root: Path | str = RESULTS_ROOT,
) -> tuple[list[int], dict[str, Any]]:
    candidate = Path(path).resolve(strict=True)
    allowed_root = Path(results_root).resolve(strict=True)
    try:
        candidate.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError("historical order JSON must be inside simulator/results") from error
    if not candidate.is_file():
        raise ValueError("historical order JSON must be a regular file")
    data = candidate.read_bytes()
    order_file_sha256 = hashlib.sha256(data).hexdigest().upper()
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as error:
        raise ValueError("historical order JSON is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("historical order JSON must contain an object")
    exact_fields = {
        "task": str(task),
        "requested_items": int(requested_items),
        "effective_items": int(requested_items),
        "seed": int(seed),
        "requested_mode": "A",
        "resolved_mode": "A",
        "algorithm_name": HISTORICAL_CONTROL_ALGORITHM,
    }
    for key, expected in exact_fields.items():
        value = payload.get(key)
        if type(value) is not type(expected) or value != expected:
            raise ValueError(f"historical order JSON field mismatch: {key}")
    artifact = payload.get("historical_artifact")
    if not isinstance(artifact, dict):
        raise ValueError("historical order JSON has no artifact evidence")
    if artifact.get("source_sha256") != HISTORICAL_CONTROL_SOURCE_SHA256:
        raise ValueError("historical order artifact source SHA-256 mismatch")
    if artifact.get("historical_source_untouched") is not True:
        raise ValueError("historical order artifact is not marked untouched")
    order = payload.get("optimized_order")
    expected_values = list(expected_order)
    if (
        type(order) is not list
        or any(type(value) is not int for value in order)
        or len(order) != len(expected_values)
        or Counter(order) != Counter(expected_values)
    ):
        raise ValueError("historical optimized_order is not the current complete permutation")
    return list(order), {
        "order_file_path": str(candidate),
        "order_file_sha256": order_file_sha256,
        "algorithm_name": HISTORICAL_CONTROL_ALGORITHM,
        "artifact_source_sha256": HISTORICAL_CONTROL_SOURCE_SHA256,
        "historical_source_untouched": True,
    }


def _b_planner_settings(
    b_planner: str,
    *,
    effective: bool = False,
) -> dict[str, Any]:
    allowed = (
        "beam",
        "one-ply",
        "fixed-two-ply",
        "maxrects-regret",
        "memoized-streaming-maxrects-regret",
        "memoized-stratified-maxrects-regret",
    )
    if b_planner not in allowed:
        raise ValueError(f"unsupported b_planner: {b_planner}")
    effective_planner = b_planner if effective else "beam"
    return {
        "requested": b_planner,
        "effective": effective_planner,
        "enabled": effective_planner != "beam",
    }


def _b_rank_objective_settings(
    b_rank_objective: str,
    *,
    effective: bool = False,
) -> dict[str, Any]:
    if b_rank_objective not in ("legacy", "continuation-survival"):
        raise ValueError(f"unsupported b_rank_objective: {b_rank_objective}")
    enabled = bool(effective and b_rank_objective == "continuation-survival")
    return {
        "requested": b_rank_objective,
        "effective": "continuation-survival" if enabled else "legacy",
        "enabled": enabled,
    }


def _begin_adaptive_scan_trace(agent: Any) -> None:
    scanner = getattr(agent, "scanner", None)
    if isinstance(scanner, _AdaptiveScannerRecorder):
        scanner.begin_policy()


def _take_adaptive_scan_trace(agent: Any, step: int) -> dict[str, Any] | None:
    scanner = getattr(agent, "scanner", None)
    if not isinstance(scanner, _AdaptiveScannerRecorder):
        return None
    stats = scanner.consume_initial_stats()
    if not isinstance(stats, CatalogStats):
        return None
    return {"step": int(step), **asdict(stats)}


def _install_b_planner(
    agent: Any,
    *,
    requested_mode: str,
    resolved_mode: str,
    b_planner: str,
    b_rank_objective: str = "legacy",
) -> Any:
    if b_rank_objective not in ("legacy", "continuation-survival"):
        raise ValueError(
            "b_rank_objective must be legacy or continuation-survival"
        )
    if b_planner not in (
        "beam",
        "one-ply",
        "fixed-two-ply",
        "maxrects-regret",
        "memoized-streaming-maxrects-regret",
        "memoized-stratified-maxrects-regret",
    ):
        raise ValueError(
            "b_planner must be beam, one-ply, fixed-two-ply, maxrects-regret, "
            "memoized-streaming-maxrects-regret, or "
            "memoized-stratified-maxrects-regret"
        )
    if (
        b_planner == "one-ply"
        and requested_mode == "B"
        and resolved_mode == "B"
    ):
        beam = getattr(agent, "beam", None)
        if beam is None or not callable(getattr(beam, "choose_c", None)):
            raise TypeError("mode-B one-ply diagnostics require an Agent beam.choose_c")
        agent.beam = _BOnePlyBeamAdapter(beam)
    elif (
        b_planner == "fixed-two-ply"
        and requested_mode == "B"
        and resolved_mode == "B"
    ):
        beam = getattr(agent, "beam", None)
        scanner = getattr(agent, "scanner", None)
        exact_mask = getattr(agent, "exact_mask", None)
        settings = getattr(agent, "settings", None)
        if beam is None or scanner is None or exact_mask is None or settings is None:
            raise TypeError(
                "mode-B fixed-two-ply diagnostics require Agent beam/scanner/exact_mask/settings"
            )
        planner = FixedQuotaExactTwoPly(scanner, exact_mask, settings)
        agent.beam = _BFixedTwoPlyBeamAdapter(beam, planner)
    elif (
        b_planner in {
            "maxrects-regret",
            "memoized-streaming-maxrects-regret",
            "memoized-stratified-maxrects-regret",
        }
        and requested_mode == "B"
        and resolved_mode == "B"
    ):
        beam = getattr(agent, "beam", None)
        scanner = getattr(agent, "scanner", None)
        exact_mask = getattr(agent, "exact_mask", None)
        settings = getattr(agent, "settings", None)
        if beam is None or scanner is None or exact_mask is None or settings is None:
            raise TypeError(
                "mode-B maxrects-regret diagnostics require Agent "
                "beam/scanner/exact_mask/settings"
            )
        if b_planner == "memoized-stratified-maxrects-regret":
            selector_kwargs = {
                "settings": settings,
                "exposure_order": (
                    ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION
                ),
            }
            if b_rank_objective == "continuation-survival":
                selector_kwargs["rank_objective"] = (
                    RankObjective.CERTIFIED_CONTINUATION_SURVIVAL
                )
            selector = MemoizedStreamingRegretProxySelector(
                exact_mask, **selector_kwargs
            )
        else:
            selector_type = (
                MemoizedStreamingRegretProxySelector
                if b_planner == "memoized-streaming-maxrects-regret"
                else RegretProxySelector
            )
            selector = selector_type(exact_mask, settings=settings)
        agent.beam = _BMaxRectsRegretBeamAdapter(beam, scanner, selector)
    return agent


def _b_trace_revision(agent: Any) -> int | None:
    revision = getattr(getattr(agent, "beam", None), "_trace_revision", None)
    return revision if type(revision) is int and revision >= 0 else None


def _b_search_trace(
    agent: Any,
    step: int,
    previous_revision: int | None,
) -> dict[str, Any] | None:
    beam = getattr(agent, "beam", None)
    revision = _b_trace_revision(agent)
    if previous_revision is None or revision is None or revision <= previous_revision:
        return None
    trace = getattr(beam, "_last_invoked_trace", None)
    if not isinstance(trace, (BSearchTrace, SelectionTrace)):
        return None
    return {"step": int(step), **asdict(trace)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _save_failure_snapshot_atomic(
    path: Path | str,
    observation: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, str]:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".npz.tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
        save_observation_snapshot(
            temporary_path,
            copy.deepcopy(observation),
            copy.deepcopy(metadata),
        )
        with temporary_path.open("rb+") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        return {"path": str(target), "sha256": _sha256_file(target)}
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _capture_failure_snapshot(
    result: dict[str, Any],
    path: Path | str | None,
    observation: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    if path is None or result.get("failure_snapshot") is not None:
        return
    try:
        result["failure_snapshot"] = _save_failure_snapshot_atomic(
            path, observation, metadata
        )
    except Exception as error:
        result["snapshot_error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }


def run_episode(
    config: dict[str, Any],
    *,
    task: str,
    requested_items: int,
    seed: int,
    requested_mode: str,
    b_planner: str = "beam",
    b_rank_objective: str = "legacy",
    candidate_rescue: str = "legacy",
    a_candidate_rescue: str = "legacy",
    a_order_fallback: str = "original",
    a_order_source: str = "agent",
    a_order_json: Path | str | None = None,
    a_order_results_root: Path | str = RESULTS_ROOT,
    env_factory: Callable[[dict[str, Any]], Any] = _default_env_factory,
    agent_factory: Callable[[], Any] = _default_agent_factory,
    clock: Callable[[], float] = time.perf_counter,
    snapshot_on_failure: Path | str | None = None,
) -> dict[str, Any]:
    effective_items = min(
        int(requested_items), len(config.get("item_stream", {}).get("item_list", ()))
    )
    result: dict[str, Any] = {
        "task": str(task),
        "requested_items": int(requested_items),
        "effective_items": effective_items,
        "seed": int(seed),
        "requested_mode": str(requested_mode),
        "b_planner": str(b_planner),
        "b_planner_settings": _b_planner_settings(b_planner),
        "b_rank_objective": str(b_rank_objective),
        "b_rank_objective_settings": _b_rank_objective_settings(
            b_rank_objective
        ),
        "candidate_rescue": str(candidate_rescue),
        "candidate_rescue_settings": _candidate_rescue_settings(candidate_rescue),
        "a_candidate_rescue": str(a_candidate_rescue),
        "a_candidate_rescue_settings": _a_candidate_rescue_settings(
            a_candidate_rescue
        ),
        "a_order_fallback": str(a_order_fallback),
        "a_order_fallback_settings": _a_order_fallback_settings(
            a_order_fallback
        ),
        "a_order_source": str(a_order_source),
        "a_order_source_settings": _a_order_source_settings(
            a_order_source, a_order_json
        ),
        "mode_a_order_fallback_trace": None,
        "resolved_mode": None,
        "agent_module": "agents.support_extreme_fusion_beam_exact_mask.agent",
        "outcome": "other_exception",
        "all_safe": False,
        "completed_steps": 0,
        "safe_placements": 0,
        "first_failure_step": None,
        "first_failure_predicate": None,
        "first_failure_status": None,
        "terminated": False,
        "truncated": False,
        "final_packed_count": 0,
        "evaluation": {"fill_score": None, "num_placed_items": None},
        "policy_time_seconds": _timing_summary(()),
        "optimize_time_seconds": 0.0,
        "optimized_order": None,
        "mode_a_plan_trace": None,
        "exception": None,
        "failure_snapshot": None,
        "diagnostic": {"b_search_traces": [], "adaptive_dense_scans": []},
        "records": [],
    }
    env = None
    observation: dict[str, Any] | None = None
    last_pre_action_observation: dict[str, Any] | None = None
    policy_times: list[float] = []
    try:
        env = env_factory(config)
        env.reset_settings()
        env.reset_item_stream()
        init_state = _mode_init_state(env.get_init_states(), requested_mode)
        result["resolved_mode"] = _resolved_mode(init_state)
        historical_order_effective = bool(
            a_order_source == "historical-control-json"
            and requested_mode == "A"
            and result["resolved_mode"] == "A"
        )
        result["a_order_source_settings"] = _a_order_source_settings(
            a_order_source,
            a_order_json,
            effective=historical_order_effective,
        )
        agent = agent_factory()
        if not agent.get_init_states(init_state):
            raise RuntimeError("Agent.get_init_states returned false")
        candidate_rescue_effective = _install_candidate_rescue(
            agent,
            requested_mode=requested_mode,
            resolved_mode=result["resolved_mode"],
            candidate_rescue=candidate_rescue,
        )
        result["candidate_rescue_settings"] = _candidate_rescue_settings(
            candidate_rescue, effective=candidate_rescue_effective
        )
        a_candidate_rescue_effective = _install_a_candidate_rescue(
            agent,
            requested_mode=requested_mode,
            resolved_mode=result["resolved_mode"],
            a_candidate_rescue=a_candidate_rescue,
        )
        result["a_candidate_rescue_settings"] = _a_candidate_rescue_settings(
            a_candidate_rescue, effective=a_candidate_rescue_effective
        )
        a_order_fallback_effective = _install_a_order_fallback(
            agent,
            requested_mode=requested_mode,
            resolved_mode=result["resolved_mode"],
            a_order_fallback=a_order_fallback,
        )
        result["a_order_fallback_settings"] = _a_order_fallback_settings(
            a_order_fallback, effective=a_order_fallback_effective
        )
        _install_b_planner(
            agent,
            requested_mode=requested_mode,
            resolved_mode=result["resolved_mode"],
            b_planner=b_planner,
            b_rank_objective=b_rank_objective,
        )
        result["b_planner_settings"] = _b_planner_settings(
            b_planner,
            effective=(
                requested_mode == "B" and result["resolved_mode"] == "B"
            ),
        )
        result["b_rank_objective_settings"] = _b_rank_objective_settings(
            b_rank_objective,
            effective=(
                requested_mode == "B"
                and result["resolved_mode"] == "B"
                and b_planner == "memoized-stratified-maxrects-regret"
            ),
        )
        if result["resolved_mode"] == "A":
            optimization_items = env.get_info_for_optimization()
            expected_order = [int(item["index"]) for item in optimization_items]
            optimize_started = float(clock())
            order_evidence: dict[str, Any] | None = None
            if historical_order_effective:
                if a_order_json is None:
                    raise ValueError(
                        "historical-control-json requires --a-order-json"
                    )
                optimized_order, order_evidence = _load_historical_control_order(
                    a_order_json,
                    expected_order=expected_order,
                    task=str(task),
                    requested_items=int(requested_items),
                    seed=int(seed),
                    results_root=a_order_results_root,
                )
                setattr(agent, "mode_a_plan", None)
                setattr(agent, "mode_a_order_fallback_trace", None)
            else:
                optimized_order = agent.optimize(optimization_items)
            optimize_completed = float(clock())
            if not math.isfinite(optimize_started) or not math.isfinite(optimize_completed):
                raise RuntimeError("optimization clock returned a non-finite value")
            result["optimize_time_seconds"] = max(
                0.0, optimize_completed - optimize_started
            )
            if (
                not isinstance(optimized_order, list)
                or any(type(value) is not int for value in optimized_order)
                or Counter(optimized_order) != Counter(expected_order)
            ):
                raise ActionFormatError("optimizer returned an invalid complete permutation")
            result["optimized_order"] = list(optimized_order)
            if historical_order_effective:
                result["a_order_source_settings"] = _a_order_source_settings(
                    a_order_source,
                    a_order_json,
                    effective=True,
                    evidence=order_evidence,
                )
            fallback_trace = getattr(agent, "mode_a_order_fallback_trace", None)
            if (
                isinstance(fallback_trace, dict)
                and set(fallback_trace) == {"selected_depth", "seed_lane"}
                and all(type(value) is int for value in fallback_trace.values())
            ):
                result["mode_a_order_fallback_trace"] = dict(fallback_trace)
            if not env.set_item_order(optimized_order):
                raise ActionFormatError("environment rejected the optimized item order")
            plan = getattr(agent, "mode_a_plan", None)
            trace = getattr(plan, "trace", None)
            if trace is not None:
                result["mode_a_plan_trace"] = asdict(trace)
            env.reset_item_stream()
        observation, _reset_info = env.reset(seed=seed)

        while result["safe_placements"] < effective_items:
            if result["terminated"] or result["truncated"]:
                break
            if not isinstance(observation, dict):
                raise RuntimeError("environment observation must be a dictionary")
            observation["depth_map"] = np.asarray(env.shm_depth_map).copy()
            pre_action_observation = copy.deepcopy(observation)
            last_pre_action_observation = pre_action_observation
            trace_revision = _b_trace_revision(agent)
            _begin_adaptive_scan_trace(agent)
            policy_started = float(clock())
            try:
                action = agent.policy(observation)
            except Exception as error:
                policy_elapsed = max(0.0, float(clock()) - policy_started)
                policy_times.append(policy_elapsed)
                adaptive_trace = _take_adaptive_scan_trace(
                    agent, len(result["records"])
                )
                if adaptive_trace is not None:
                    result["diagnostic"]["adaptive_dense_scans"].append(
                        adaptive_trace
                    )
                if b_planner in (
                    "fixed-two-ply",
                    "maxrects-regret",
                    "memoized-streaming-maxrects-regret",
                    "memoized-stratified-maxrects-regret",
                ):
                    trace = _b_search_trace(
                        agent, len(result["records"]), trace_revision
                    )
                    if trace is not None:
                        result["diagnostic"]["b_search_traces"].append(trace)
                _capture_failure_snapshot(
                    result,
                    snapshot_on_failure,
                    pre_action_observation,
                    {
                        "task": str(task),
                        "seed": int(seed),
                        "requested_mode": str(requested_mode),
                        "resolved_mode": result["resolved_mode"],
                        "step": len(result["records"]),
                        "failure_kind": "policy_exception",
                        "exception_category": _exception_category(error),
                        "exception_type": type(error).__name__,
                        "exception_message": str(error),
                    },
                )
                raise
            policy_elapsed = max(0.0, float(clock()) - policy_started)
            policy_times.append(policy_elapsed)
            adaptive_trace = _take_adaptive_scan_trace(
                agent, len(result["records"])
            )
            if adaptive_trace is not None:
                result["diagnostic"]["adaptive_dense_scans"].append(
                    adaptive_trace
                )
            if b_planner in (
                "fixed-two-ply",
                "maxrects-regret",
                "memoized-streaming-maxrects-regret",
                "memoized-stratified-maxrects-regret",
            ):
                trace = _b_search_trace(
                    agent, len(result["records"]), trace_revision
                )
                if trace is not None:
                    result["diagnostic"]["b_search_traces"].append(trace)
            if not action_format_is_valid(action, observation):
                raise ActionFormatError("agent returned a malformed or non-finite action")

            next_observation, _reward, terminated, truncated, info = env.step(action)
            status = info.get("status") if isinstance(info, dict) else None
            status_well_formed = status_format_is_valid(status)
            serialized_status = dict(status) if isinstance(status, dict) else status
            step_index = len(result["records"])
            result["records"].append(
                {
                    "step": step_index,
                    "policy_seconds": policy_elapsed,
                    "action": _serialize_action(action),
                    "status": serialized_status,
                    "status_well_formed": status_well_formed,
                    "terminated": bool(terminated),
                    "truncated": bool(truncated),
                }
            )
            result["completed_steps"] = len(result["records"])
            result["terminated"] = bool(terminated)
            result["truncated"] = bool(truncated)
            observation = next_observation
            failed_predicate = _first_failed_predicate(status)
            if failed_predicate is not None:
                result["outcome"] = "physical_failure"
                result["first_failure_step"] = step_index
                result["first_failure_predicate"] = failed_predicate
                result["first_failure_status"] = serialized_status
                _capture_failure_snapshot(
                    result,
                    snapshot_on_failure,
                    pre_action_observation,
                    {
                        "task": str(task),
                        "seed": int(seed),
                        "requested_mode": str(requested_mode),
                        "resolved_mode": result["resolved_mode"],
                        "step": step_index,
                        "failure_kind": "physical_failure",
                        "failed_predicate": failed_predicate,
                        "status": serialized_status,
                        "action": _serialize_action(action),
                    },
                )
                break
            result["safe_placements"] += 1

        if result["outcome"] != "physical_failure":
            if result["safe_placements"] >= effective_items:
                result["outcome"] = "success"
                result["all_safe"] = True
            else:
                result["outcome"] = "physical_failure"
                result["first_failure_step"] = max(0, result["completed_steps"] - 1)
                stop_predicate = (
                    "truncated" if result["truncated"] else "early_termination"
                )
                result["first_failure_predicate"] = stop_predicate
                if last_pre_action_observation is not None:
                    last_record = result["records"][-1] if result["records"] else {}
                    result["first_failure_status"] = last_record.get("status")
                    _capture_failure_snapshot(
                        result,
                        snapshot_on_failure,
                        last_pre_action_observation,
                        {
                            "task": str(task),
                            "seed": int(seed),
                            "requested_mode": str(requested_mode),
                            "resolved_mode": result["resolved_mode"],
                            "step": result["first_failure_step"],
                            "failure_kind": "physical_failure",
                            "failed_predicate": stop_predicate,
                            "status": last_record.get("status"),
                            "action": last_record.get("action"),
                        },
                    )
    except Exception as error:
        result["outcome"] = _exception_category(error)
        result["all_safe"] = False
        result["exception"] = {
            "category": result["outcome"],
            "type": type(error).__name__,
            "message": str(error),
            "step": len(result["records"]),
        }
    finally:
        result["policy_time_seconds"] = _timing_summary(policy_times)
        result["final_packed_count"] = _packed_count(observation)
        if env is not None:
            try:
                evaluation = env.evaluate()
                if isinstance(evaluation, dict):
                    result["evaluation"] = copy.deepcopy(evaluation)
                    result["evaluation"].setdefault("fill_score", None)
                    result["evaluation"].setdefault("num_placed_items", None)
                else:
                    raise TypeError("env.evaluate returned a non-dictionary")
            except Exception as error:
                result["evaluation_error"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
                if result["outcome"] == "success":
                    result["outcome"] = "other_exception"
                    result["all_safe"] = False
                    result["exception"] = {
                        "category": "other_exception",
                        "type": type(error).__name__,
                        "message": f"evaluation failed: {error}",
                        "step": len(result["records"]),
                    }
            try:
                env.close()
            except Exception as error:
                result["close_error"] = {"type": type(error).__name__, "message": str(error)}
    return result


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def atomic_write_json(path: Path | str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(payload, stream, indent=2, sort_keys=True, default=_json_default)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _minimal_failure(args: argparse.Namespace, error: BaseException) -> dict[str, Any]:
    category = _exception_category(error)
    return {
        "task": args.task,
        "requested_items": args.items,
        "seed": args.seed,
        "requested_mode": args.mode,
        "b_planner": args.b_planner,
        "b_planner_settings": _b_planner_settings(args.b_planner),
        "b_rank_objective": args.b_rank_objective,
        "b_rank_objective_settings": _b_rank_objective_settings(
            args.b_rank_objective
        ),
        "candidate_rescue": args.candidate_rescue,
        "candidate_rescue_settings": _candidate_rescue_settings(
            args.candidate_rescue
        ),
        "a_candidate_rescue": args.a_candidate_rescue,
        "a_candidate_rescue_settings": _a_candidate_rescue_settings(
            args.a_candidate_rescue
        ),
        "a_order_fallback": args.a_order_fallback,
        "a_order_fallback_settings": _a_order_fallback_settings(
            args.a_order_fallback
        ),
        "a_order_source": args.a_order_source,
        "a_order_source_settings": _a_order_source_settings(
            args.a_order_source, args.a_order_json
        ),
        "mode_a_order_fallback_trace": None,
        "outcome": category,
        "all_safe": False,
        "completed_steps": 0,
        "safe_placements": 0,
        "exception": {
            "category": category,
            "type": type(error).__name__,
            "message": str(error),
            "step": 0,
        },
        "records": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with (SIMULATOR_ROOT / "configs" / "sample_config.json").open(
            encoding="utf-8"
        ) as stream:
            sample_config = json.load(stream)
        config = materialize_config(sample_config, args.task, args.items, args.mode)
        result = run_episode(
            config,
            task=args.task,
            requested_items=args.items,
            seed=args.seed,
            requested_mode=args.mode,
            b_planner=args.b_planner,
            b_rank_objective=args.b_rank_objective,
            candidate_rescue=args.candidate_rescue,
            a_candidate_rescue=args.a_candidate_rescue,
            a_order_fallback=args.a_order_fallback,
            a_order_source=args.a_order_source,
            a_order_json=args.a_order_json,
            snapshot_on_failure=args.snapshot_on_failure,
        )
    except Exception as error:
        result = _minimal_failure(args, error)
    atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))
    return 0 if result.get("outcome") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
