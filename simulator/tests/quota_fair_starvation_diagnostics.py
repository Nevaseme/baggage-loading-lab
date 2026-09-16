"""Non-production instrumentation for exact-root catalog starvation.

The catalog itself remains the source of truth.  This module wraps the
collaborators used by that catalog and records what the unchanged loop did;
it deliberately does not contain a second copy of the catalog algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Sequence

from agents.highscore import catalog as _catalog
from agents.highscore import ems as _ems
from agents.highscore.catalog import RootAction
from agents.highscore.scoring import CandidateScorer


@dataclass(frozen=True)
class CatalogTraceRow:
    pool_index: int
    item_index: int
    urgency: float
    proposal_count: int
    validated_count: int
    accepted_root_count: int
    start_time: float | None
    end_time: float | None
    stop_reason: str


@dataclass(frozen=True)
class CatalogTrace:
    roots: tuple[RootAction, ...]
    rows: tuple[CatalogTraceRow, ...]
    production_start: float
    catalog_deadline: float
    observed_catalog_budget_seconds: float


@dataclass(frozen=True)
class ProbeMeasurement:
    pool_index: int
    exact_root_found: bool
    time_to_first_exact_root: float | None
    measured_elapsed_seconds: float
    proposals_exhausted: bool


@dataclass(frozen=True)
class ProbeClassification:
    measurement: ProbeMeasurement
    fair_share_seconds: float
    recoverable: bool


@dataclass
class _PositionRecord:
    pool_index: int
    item_index: int
    urgency: float
    proposal_count: int = 0
    validated_count: int = 0
    accepted_root_count: int = 0
    start_time: float | None = None
    end_time: float | None = None
    proposal_end_time: float | None = None
    proposal_completed_normally: bool = False
    item_deadline: float | None = None
    checkpoint_events: list[tuple[float, int, int]] = field(default_factory=list)


class _ClockProxy:
    """The catalog module's clock collaborator, not the process clock."""

    def __init__(self, real_clock: Any, records: list[_PositionRecord], active: list[int | None], accepted_events: list[tuple[int, float]], values: list[float]):
        self._real_clock = real_clock
        self._records = records
        self._active = active
        self._accepted_events = accepted_events
        self._values = values

    def perf_counter(self) -> float:
        value = float(self._real_clock())
        self._values.append(value)
        pool_index = self._active[0]
        if pool_index is not None:
            record = self._records[pool_index]
            record.checkpoint_events.append(
                (value, len(self._accepted_events), record.accepted_root_count)
            )
        return value


class _GeneratorProxy:
    def __init__(self, generator: Any, validate: Any):
        self._generator = generator
        self._validate = validate

    def validate_proposal(self, state: Any, action: Any, *args: Any, **kwargs: Any) -> Any:
        pool_index = getattr(action, "pool_index", None)
        if isinstance(pool_index, int) and 0 <= pool_index < len(self._records):
            record = self._records[pool_index]
            record.validated_count += 1
        else:
            record = None
        try:
            candidate = self._validate(state, action, *args, **kwargs)
            if candidate is not None:
                self._exact_action_ids.add(id(action))
            return candidate
        finally:
            if record is not None:
                now = float(self._clock())
                record.end_time = now

    def __getattr__(self, name: str) -> Any:
        return getattr(self._generator, name)

    # These attributes are installed by trace_production_catalog.  Keeping
    # them on the proxy avoids changing CandidateGenerator or its interface.
    _records: list[_PositionRecord]
    _exact_action_ids: set[int]
    _clock: Any


def _stop_at_checkpoint(
    record: _PositionRecord,
    *,
    checkpoint: tuple[float, int, int] | None,
    catalog_deadline: float,
    settings: Any,
) -> str | None:
    """Apply the production inner-loop condition order to one checkpoint."""
    if checkpoint is None:
        return None
    now, total_roots, accepted_for_item = checkpoint
    if record.item_deadline is not None and now >= record.item_deadline:
        return "unknown"  # item deadline is intentionally not global evidence
    if now >= catalog_deadline:
        return "catalog_deadline"
    if accepted_for_item >= settings.ems_exact_roots_per_item:
        return "per_item_quota"
    if total_roots >= settings.ems_root_catalog_limit:
        return "global_cap"
    return None


def _final_outer_reason(
    now: float,
    *,
    total_roots: int,
    catalog_deadline: float,
    settings: Any,
) -> str | None:
    # build_root_catalog checks its outer stop conditions in this order.
    if now >= catalog_deadline:
        return "catalog_deadline"
    if total_roots >= settings.ems_root_catalog_limit:
        return "global_cap"
    return None


def trace_production_catalog(
    state: Any,
    pool: Sequence[Any],
    generator: Any,
    settings: Any,
    *,
    deadline: float,
) -> CatalogTrace:
    """Trace one unchanged ``build_root_catalog`` call.

    Only references held by ``agents.highscore.catalog`` are replaced, and
    every replacement is restored even when production raises.
    """
    records = [
        _PositionRecord(
            pool_index=index,
            item_index=int(item.index),
            urgency=float(CandidateScorer.item_urgency(item, state.containers)),
        )
        for index, item in enumerate(pool)
    ]
    active: list[int | None] = [None]
    clock_values: list[float] = []
    accepted_events: list[tuple[int, float]] = []
    exact_action_ids: set[int] = set()
    real_clock = _catalog.time.perf_counter
    real_catalog = _catalog.build_root_catalog
    real_propose = _catalog.propose_actions
    real_apply = _catalog.apply_action

    # A wrapper may need to find records even when a fixture uses a custom
    # action object.  Pool index is the authoritative identity when present.
    def record_for_action(action: Any) -> _PositionRecord | None:
        index = getattr(action, "pool_index", None)
        if isinstance(index, int) and 0 <= index < len(records):
            return records[index]
        return None

    def traced_propose(proxy_state: Any, item: Any, pool_index: int, *, limit: int, deadline: float) -> Any:
        record = records[pool_index]
        active[0] = pool_index
        if record.start_time is None:
            record.start_time = float(real_clock())
        record.item_deadline = float(deadline)
        try:
            proposals = real_propose(proxy_state, item, pool_index, limit=limit, deadline=deadline)
            record.proposal_count += len(proposals)
            record.proposal_completed_normally = True
            return proposals
        finally:
            now = float(real_clock())
            record.proposal_end_time = now
            record.end_time = now

    def traced_apply(proxy_state: Any, action: Any, clearance: float) -> Any:
        record = record_for_action(action)
        try:
            successor = real_apply(proxy_state, action, clearance)
        finally:
            now = float(real_clock())
            if record is not None:
                record.end_time = now
        if successor is not None and id(action) in exact_action_ids and record is not None:
            record.accepted_root_count += 1
            accepted_events.append((record.pool_index, float(record.end_time)))
        return successor

    validating = _GeneratorProxy(generator, generator.validate_proposal)
    validating._records = records
    validating._exact_action_ids = exact_action_ids
    validating._clock = real_clock
    clock_proxy = _ClockProxy(real_clock, records, active, accepted_events, clock_values)

    original_time = _catalog.time
    try:
        _catalog.propose_actions = traced_propose
        _catalog.apply_action = traced_apply
        _catalog.time = clock_proxy
        roots = real_catalog(state, pool, validating, settings, deadline=deadline)
    finally:
        _catalog.propose_actions = real_propose
        _catalog.apply_action = real_apply
        _catalog.time = original_time

    if not clock_values:
        # A production implementation should always read its clock, including
        # an empty pool.  Keep the error explicit rather than inventing timing.
        raise AssertionError("production catalog did not expose a clock reading")
    if len(accepted_events) != len(roots):
        raise AssertionError(
            "catalog tracing invariant failed: accepted apply events do not match roots"
        )

    production_start = clock_values[0]
    catalog_deadline = min(
        float(deadline),
        production_start + max(0.0, float(settings.ems_root_budget_seconds)),
    )
    visited = [record.pool_index for record in records if record.start_time is not None]
    cutoff = max(visited, default=-1)
    final_outer = _final_outer_reason(
        clock_values[-1],
        total_roots=len(accepted_events),
        catalog_deadline=catalog_deadline,
        settings=settings,
    )

    rows: list[CatalogTraceRow] = []
    for record in records:
        reason: str | None = None
        if record.accepted_root_count >= settings.ems_exact_roots_per_item:
            reason = "per_item_quota"
        elif (
            record.start_time is not None
            and record.proposal_completed_normally
            and record.validated_count == record.proposal_count
            and record.end_time is not None
            and record.item_deadline is not None
            and record.end_time < record.item_deadline
            and record.end_time < catalog_deadline
        ):
            reason = "proposal_exhausted"
        else:
            checkpoint = next(
                (
                    event
                    for event in record.checkpoint_events
                    if record.end_time is not None and event[0] > record.end_time
                ),
                None,
            )
            reason = _stop_at_checkpoint(
                record,
                checkpoint=checkpoint,
                catalog_deadline=catalog_deadline,
                settings=settings,
            )
            if reason == "unknown":
                reason = "unknown"
            if reason is None and record.start_time is None and record.pool_index > cutoff:
                reason = final_outer
        if reason is None and record.start_time is None:
            reason = "not_visited"
        if reason is None:
            reason = "unknown"
        rows.append(
            CatalogTraceRow(
                pool_index=record.pool_index,
                item_index=record.item_index,
                urgency=record.urgency,
                proposal_count=record.proposal_count,
                validated_count=record.validated_count,
                accepted_root_count=record.accepted_root_count,
                start_time=record.start_time,
                end_time=record.end_time,
                stop_reason=reason,
            )
        )

    return CatalogTrace(
        roots=tuple(roots),
        rows=tuple(rows),
        production_start=production_start,
        catalog_deadline=catalog_deadline,
        observed_catalog_budget_seconds=max(0.0, catalog_deadline - production_start),
    )


def measure_pool_position(
    state: Any,
    pool: Sequence[Any],
    pool_index: int,
    generator: Any,
    settings: Any,
    *,
    probe_budget_seconds: float,
) -> ProbeMeasurement:
    """Independently probe one pool position using exact production checks."""
    if pool_index < 0 or pool_index >= len(pool):
        raise IndexError(pool_index)
    started = time.perf_counter()
    probe_deadline = started + max(0.0, float(probe_budget_seconds))
    proxy_state = _ems.build_proxy_state(
        state,
        settings.path_clearance,
        support_inset=max(0.0, -settings.inclusion_margin),
        shelf_drop_gap=settings.shelf_drop_gap,
    )
    proposals_exhausted = True
    try:
        proposals = _catalog.propose_actions(
            proxy_state,
            pool[pool_index],
            pool_index,
            limit=settings.ems_proxy_actions_per_item,
            deadline=probe_deadline,
        )
    except Exception:
        elapsed = max(0.0, time.perf_counter() - started)
        return ProbeMeasurement(pool_index, False, None, elapsed, False)

    for action in proposals:
        if time.perf_counter() >= probe_deadline:
            proposals_exhausted = False
            break
        try:
            candidate = generator.validate_proposal(state, action)
            if candidate is None:
                continue
            successor = _catalog.apply_action(proxy_state, action, settings.path_clearance)
        except Exception:
            continue
        if successor is None:
            continue
        elapsed = max(0.0, time.perf_counter() - started)
        return ProbeMeasurement(pool_index, True, elapsed, elapsed, False)

    elapsed = max(0.0, time.perf_counter() - started)
    if started + elapsed >= probe_deadline:
        proposals_exhausted = False
    return ProbeMeasurement(pool_index, False, None, elapsed, proposals_exhausted)


def classify_probe(measurement: ProbeMeasurement, *, fair_share_seconds: float) -> ProbeClassification:
    fair_share = max(0.0, float(fair_share_seconds))
    recoverable = bool(
        measurement.exact_root_found
        and measurement.time_to_first_exact_root is not None
        and measurement.time_to_first_exact_root <= fair_share
    )
    return ProbeClassification(measurement, fair_share, recoverable)
