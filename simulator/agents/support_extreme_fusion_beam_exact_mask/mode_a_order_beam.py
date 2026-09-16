"""Fixed-work offline LayeredProxy order beam for Mode A.

This module produces analytical order/skeleton candidates only.  It cannot
mint exact receipts or public actions and is intentionally not Agent-wired.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time
from typing import Any, Sequence

from .layered_proxy import (
    LayeredProxy,
    LayeredProxyState,
    ProxyCandidate,
    ProxyExposureOrder,
    ProxyMetrics,
    ProxyOccurrence,
    ProxyTopologyCache,
    ProxyWork,
    ProxyWorkQuota,
)
from .mode_a_seeds import historical_static_order_seed
from .mode_a_types import (
    OfflineOccurrence,
    SkeletonIntent,
    SupportKind,
    _validate_occurrence_sequence,
    build_offline_occurrences,
)
from .model import ItemSpec, PackingState, _item_signature
from .transition import SimState


_EPS = 1.0e-12


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive exact int")
    return value


def _finite_float(value: object, name: str, *, nonnegative: bool = False) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ValueError(f"{name} must be an exact finite float")
    if nonnegative and value < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True)
class ModeAOrderBeamSettings:
    beam_width: int = 24
    max_nodes: int = 20_000
    max_fit_tests: int = 250_000
    max_checked_transitions: int = 80_000
    max_rectangles_per_patch: int = 128
    max_item_choices: int = 6
    max_placements_per_item: int = 4
    per_preview_fit_quantum: int = 64
    protection_materiality: float = 0.01

    def __post_init__(self) -> None:
        for name in (
            "beam_width",
            "max_nodes",
            "max_fit_tests",
            "max_checked_transitions",
            "max_rectangles_per_patch",
            "max_item_choices",
            "max_placements_per_item",
            "per_preview_fit_quantum",
        ):
            _positive_int(getattr(self, name), name)
        _finite_float(
            self.protection_materiality,
            "protection_materiality",
            nonnegative=True,
        )
        if self.protection_materiality <= 0.0:
            raise ValueError("protection_materiality must be positive")


@dataclass(frozen=True)
class ModeAOrderBeamTrace:
    nodes: int = 0
    fit_tests: int = 0
    checked_transitions: int = 0
    rectangle_limit: int = 128
    deepest: int = 0
    completed_candidates: int = 0
    deadline_reached: bool = False
    node_quota_exhausted: bool = False
    fit_quota_exhausted: bool = False
    transition_quota_exhausted: bool = False
    branch_exceptions: int = 0

    def __post_init__(self) -> None:
        for name in (
            "nodes",
            "fit_tests",
            "checked_transitions",
            "deepest",
            "completed_candidates",
            "branch_exceptions",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative exact int")
        _positive_int(self.rectangle_limit, "rectangle_limit")
        for name in (
            "deadline_reached",
            "node_quota_exhausted",
            "fit_quota_exhausted",
            "transition_quota_exhausted",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact bool")


@dataclass(frozen=True)
class ProxyOrderCandidate:
    occurrence_order: tuple[OfflineOccurrence, ...]
    skeleton: tuple[SkeletonIntent, ...]
    placed_count: int
    placed_volume: float
    min_alternatives: int
    support_margin: float
    clearance_margin: float
    metrics: ProxyMetrics
    seed_discrepancies: int
    complete: bool
    seed_lane: int

    def __post_init__(self) -> None:
        if type(self.occurrence_order) is not tuple or any(
            type(value) is not OfflineOccurrence for value in self.occurrence_order
        ):
            raise TypeError("occurrence_order must be an exact occurrence tuple")
        positions = tuple(value.original_position for value in self.occurrence_order)
        if CounterLike(positions) != CounterLike(range(len(positions))):
            raise ValueError("occurrence_order must be a full occurrence permutation")
        canonical = tuple(
            sorted(self.occurrence_order, key=lambda value: value.original_position)
        )
        _validate_occurrence_sequence(canonical)
        if type(self.skeleton) is not tuple or any(
            type(value) is not SkeletonIntent for value in self.skeleton
        ):
            raise TypeError("skeleton must be an exact SkeletonIntent tuple")
        if type(self.placed_count) is not int or not 0 <= self.placed_count <= len(positions):
            raise ValueError("placed_count is outside the full occurrence order")
        if len(self.skeleton) != self.placed_count:
            raise ValueError("skeleton length must equal placed_count")
        if tuple(value.occurrence for value in self.skeleton) != self.occurrence_order[: self.placed_count]:
            raise ValueError("skeleton must follow the placed order prefix")
        authoritative = {
            value.original_position: value for value in self.occurrence_order
        }
        for intent in self.skeleton:
            for supporter in intent.supporter_occurrences:
                expected = authoritative.get(supporter.original_position)
                if expected is None or expected.stable_key != supporter.stable_key:
                    raise ValueError("skeleton supporter is not authoritative")
        _finite_float(self.placed_volume, "placed_volume", nonnegative=True)
        if type(self.min_alternatives) is not int or self.min_alternatives < 0:
            raise ValueError("min_alternatives must be a non-negative exact int")
        if self.placed_count and self.min_alternatives < 1:
            raise ValueError("placed candidates require at least one alternative")
        _finite_float(self.support_margin, "support_margin")
        _finite_float(self.clearance_margin, "clearance_margin")
        if type(self.metrics) is not ProxyMetrics:
            raise TypeError("metrics must be an exact ProxyMetrics")
        if any(
            type(value) is not float or not math.isfinite(value)
            for value in vars(self.metrics).values()
        ):
            raise ValueError("metrics must contain exact finite floats")
        if type(self.seed_discrepancies) is not int or self.seed_discrepancies < 0:
            raise ValueError("seed_discrepancies must be a non-negative exact int")
        if type(self.complete) is not bool or self.complete != (
            self.placed_count == len(self.occurrence_order)
        ):
            raise ValueError("complete must exactly describe placed coverage")
        if type(self.seed_lane) is not int or self.seed_lane not in range(3):
            raise ValueError("seed_lane must be an exact int in range(3)")

    @property
    def stable_key(self) -> tuple:
        return (
            tuple(value.stable_key for value in self.occurrence_order),
            tuple(value.stable_key for value in self.skeleton),
            self.placed_count,
            self.placed_volume,
            self.min_alternatives,
            self.support_margin,
            self.clearance_margin,
            tuple(vars(self.metrics).values()),
            self.seed_discrepancies,
            self.complete,
            self.seed_lane,
        )


def CounterLike(values: Sequence[int]) -> tuple[int, ...]:
    """Canonical tiny multiset representation without mutable containers."""

    return tuple(sorted(values))


@dataclass(frozen=True)
class _OrderNode:
    state: LayeredProxyState
    metrics: ProxyMetrics
    authoritative: tuple[OfflineOccurrence, ...]
    seed_lane: int
    seed_order: tuple[int, ...]
    placed: tuple[OfflineOccurrence, ...]
    skeleton: tuple[SkeletonIntent, ...]
    placed_volume: float
    min_alternatives: int
    support_margin: float
    clearance_margin: float
    seed_discrepancies: int
    last_support_source: str
    last_container: int
    stable_sequence: tuple


class LayeredProxyOrderBeam:
    """Occurrence-safe fixed-work beam over checked LayeredProxy transitions."""

    def __init__(
        self,
        *,
        proxy: LayeredProxy | None = None,
        settings: ModeAOrderBeamSettings | None = None,
        clock=None,
    ) -> None:
        self.proxy = proxy or LayeredProxy()
        if not isinstance(self.proxy, LayeredProxy):
            raise TypeError("proxy must be a LayeredProxy")
        self.settings = settings or ModeAOrderBeamSettings()
        if type(self.settings) is not ModeAOrderBeamSettings:
            raise TypeError("settings must be exact ModeAOrderBeamSettings")
        self.clock = clock or time.perf_counter
        self.last_trace = ModeAOrderBeamTrace(
            rectangle_limit=self.settings.max_rectangles_per_patch
        )

    def orientation_count(self, item: ItemSpec) -> int:
        return len(self.proxy.orientation_options(item))

    def seed_orders(
        self,
        occurrences: tuple[OfflineOccurrence, ...],
        raw_items: Sequence[dict[str, Any]],
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        occurrences = _validate_occurrence_sequence(occurrences)
        historical = historical_static_order_seed(raw_items, occurrences)
        items = self._items(raw_items, occurrences)
        original = tuple(range(len(occurrences)))
        volume = tuple(
            value.original_position
            for value in sorted(
                occurrences,
                key=lambda occurrence: (
                    -items[occurrence.original_position].volume,
                    -max(
                        items[occurrence.original_position].length
                        * items[occurrence.original_position].width,
                        items[occurrence.original_position].length
                        * items[occurrence.original_position].height,
                        items[occurrence.original_position].width
                        * items[occurrence.original_position].height,
                    ),
                    occurrence.original_position,
                ),
            )
        )
        return original, historical, volume

    def choice_occurrences(
        self,
        occurrences: tuple[OfflineOccurrence, ...],
        raw_items: Sequence[dict[str, Any]],
        seeds: tuple[tuple[int, ...], ...],
        *,
        available_positions: set[int] | None = None,
        proxy_state: LayeredProxyState | None = None,
        deadline: float | None = None,
    ) -> tuple[OfflineOccurrence, ...]:
        items = self._items(raw_items, occurrences)
        return self._choice_occurrences_with_items(
            occurrences,
            items,
            seeds,
            available_positions=available_positions,
            proxy_state=proxy_state,
            deadline=deadline,
        )

    def _choice_occurrences_with_items(
        self,
        occurrences: tuple[OfflineOccurrence, ...],
        items: tuple[ItemSpec, ...],
        seeds: tuple[tuple[int, ...], ...],
        *,
        available_positions: set[int] | None,
        proxy_state: LayeredProxyState | None,
        deadline: float | None,
    ) -> tuple[OfflineOccurrence, ...]:
        allowed = (
            {value.original_position for value in occurrences}
            if available_positions is None
            else set(available_positions)
        )
        remaining = {
            value.original_position: value
            for value in occurrences
            if value.original_position in allowed
        }
        eligible = tuple(remaining.values())
        selected: list[OfflineOccurrence] = []

        def add(position: int) -> None:
            value = remaining.get(position)
            if value is not None and value not in selected:
                selected.append(value)

        for seed in seeds:
            for position in seed:
                if self._deadline_hit(deadline):
                    return tuple(selected[: self.settings.max_item_choices])
                if position in remaining:
                    add(position)
                    break
        scarce_rows = []
        for value in eligible:
            if self._deadline_hit(deadline):
                return tuple(selected[: self.settings.max_item_choices])
            estimate = self._estimated_option_count(
                items[value.original_position], proxy_state, deadline
            )
            if estimate is None:
                return tuple(selected[: self.settings.max_item_choices])
            scarce_rows.append(
                (
                    estimate,
                    self.orientation_count(items[value.original_position]),
                    -items[value.original_position].volume,
                    value.original_position,
                    value,
                )
            )
        scarce = [row[-1] for row in sorted(scarce_rows, key=lambda row: row[:-1])]
        if scarce:
            add(scarce[0].original_position)
        special_rows = []
        for value in eligible:
            if self._deadline_hit(deadline):
                return tuple(selected[: self.settings.max_item_choices])
            special_rows.append((
                -int(
                    items[value.original_position].is_prioritized
                    and items[value.original_position].is_soft
                ),
                -int(items[value.original_position].is_soft),
                -int(items[value.original_position].is_prioritized),
                value.original_position,
                value,
            ))
        special = [row[-1] for row in sorted(special_rows, key=lambda row: row[:-1])]
        if special and (
            items[special[0].original_position].is_soft
            or items[special[0].original_position].is_prioritized
        ):
            add(special[0].original_position)
        large_rows = []
        for value in eligible:
            if self._deadline_hit(deadline):
                return tuple(selected[: self.settings.max_item_choices])
            large_rows.append((
                -max(
                    items[value.original_position].length
                    * items[value.original_position].width,
                    items[value.original_position].length
                    * items[value.original_position].height,
                    items[value.original_position].width
                    * items[value.original_position].height,
                ),
                self.orientation_count(items[value.original_position]),
                -items[value.original_position].volume,
                value.original_position,
                value,
            ))
        large = [row[-1] for row in sorted(large_rows, key=lambda row: row[:-1])]
        if large:
            add(large[0].original_position)
        for value in eligible:
            add(value.original_position)
            if len(selected) >= self.settings.max_item_choices:
                break
        return tuple(selected[: self.settings.max_item_choices])

    def search(
        self,
        initial_state: PackingState,
        occurrences: tuple[OfflineOccurrence, ...],
        raw_items: Sequence[dict[str, Any]],
        deadline: float,
    ) -> tuple[ProxyOrderCandidate, ...]:
        if not isinstance(initial_state, PackingState):
            raise TypeError("initial_state must be a PackingState")
        if not math.isfinite(float(deadline)):
            raise ValueError("deadline must be finite")
        if self._expired(deadline):
            self.last_trace = ModeAOrderBeamTrace(
                rectangle_limit=self.settings.max_rectangles_per_patch,
                deadline_reached=True,
            )
            return ()
        occurrences = _validate_occurrence_sequence(occurrences)
        items = self._items(raw_items, occurrences)
        seeds = self.seed_orders(occurrences, raw_items)
        sim = SimState(
            initial_state,
            tuple(items[position] for position in range(len(items))),
            tuple(range(len(items))),
        )
        state = self.proxy.from_sim_state(sim)
        cache = ProxyTopologyCache()
        metrics = self.proxy.metrics(state, topology_cache=cache)
        quota = ProxyWorkQuota(
            max_nodes=self.settings.max_nodes,
            max_fit_tests=self.settings.max_fit_tests,
            max_candidates=self.settings.max_checked_transitions,
            max_rectangles_per_patch=self.settings.max_rectangles_per_patch,
        )
        work = ProxyWork()
        frontier: list[_OrderNode] = []
        exceptions = 0
        for lane, seed in enumerate(seeds):
            if work.nodes >= quota.max_nodes:
                break
            work = work.consume_node(quota)
            frontier.append(
                _OrderNode(
                    state,
                    metrics,
                    occurrences,
                    lane,
                    seed,
                    (),
                    (),
                    0.0,
                    0,
                    0.0,
                    0.0,
                    0,
                    "seed",
                    -1,
                    (("seed", lane),),
                )
            )
        if not frontier:
            return ()

        completed: list[_OrderNode] = []
        latest: list[_OrderNode] = list(frontier)
        deepest = 0
        deadline_reached = self._expired(deadline)
        while frontier and not deadline_reached and not work.quota_exhausted(quota):
            children: list[_OrderNode] = []
            for node in self._fair_nodes(frontier):
                if self._expired(deadline):
                    deadline_reached = True
                    break
                choices = self._choice_occurrences_with_items(
                    occurrences,
                    items,
                    seeds,
                    available_positions={
                        value.key.original_position for value in node.state.remaining
                    },
                    proxy_state=node.state,
                    deadline=deadline,
                )
                for occurrence in choices:
                    if self._expired(deadline) or work.quota_exhausted(quota):
                        deadline_reached = self._expired(deadline)
                        break
                    proxy_occurrence = self._proxy_occurrence(node.state, occurrence)
                    try:
                        call_quota = replace(
                            quota,
                            max_fit_tests=min(
                                quota.max_fit_tests,
                                work.fit_tests
                                + self.settings.per_preview_fit_quantum,
                            ),
                            max_candidates=min(
                                quota.max_candidates,
                                work.candidates
                                + self.settings.max_placements_per_item,
                            ),
                        )
                        batch = self.proxy.preview_candidates(
                            node.state,
                            proxy_occurrence.key,
                            work,
                            call_quota,
                            node.metrics,
                            cache,
                            exposure_order=(
                                ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION
                            ),
                        )
                    except Exception:
                        exceptions += 1
                        continue
                    work = batch.work
                    if self._expired(deadline):
                        deadline_reached = True
                        break
                    alternatives = len(batch.transitions)
                    for transition in batch.transitions[
                        : self.settings.max_placements_per_item
                    ]:
                        if self._expired(deadline) or work.nodes >= quota.max_nodes:
                            deadline_reached = self._expired(deadline)
                            break
                        try:
                            child_state, child_metrics = self.proxy.commit_transition(
                                node.state, transition, cache
                            )
                            work = work.consume_node(quota)
                            intent = self._intent(
                                node,
                                transition.candidate,
                                occurrence,
                                max(1, alternatives),
                                occurrences,
                            )
                            child = self._child(
                                node,
                                child_state,
                                child_metrics,
                                intent,
                                items[occurrence.original_position],
                            )
                        except Exception:
                            exceptions += 1
                            continue
                        children.append(child)
                        deepest = max(deepest, len(child.placed))
                        if not child.state.remaining:
                            completed.append(child)
                if deadline_reached or work.quota_exhausted(quota):
                    break
            if children:
                latest = children
            frontier = [
                node for node in self._fair_nodes(children)
                if node.state.remaining
            ][: self.settings.beam_width]
            if not children:
                break

        node_pool = completed if completed else latest
        candidates = tuple(
            self._to_candidate(node) for node in node_pool
        )
        ranked = self.rank_candidates(candidates)
        unique: list[ProxyOrderCandidate] = []
        seen: set[tuple] = set()
        for candidate in ranked:
            if candidate.stable_key in seen:
                continue
            seen.add(candidate.stable_key)
            unique.append(candidate)
            if len(unique) >= self.settings.beam_width:
                break
        self.last_trace = ModeAOrderBeamTrace(
            nodes=work.nodes,
            fit_tests=work.fit_tests,
            checked_transitions=work.candidates,
            rectangle_limit=self.settings.max_rectangles_per_patch,
            deepest=deepest,
            completed_candidates=len(completed),
            deadline_reached=deadline_reached or self._expired(deadline),
            node_quota_exhausted=work.nodes >= quota.max_nodes,
            fit_quota_exhausted=work.fit_tests >= quota.max_fit_tests,
            transition_quota_exhausted=work.candidates >= quota.max_candidates,
            branch_exceptions=exceptions,
        )
        return tuple(unique)

    def rank_candidates(
        self, candidates: Sequence[ProxyOrderCandidate]
    ) -> tuple[ProxyOrderCandidate, ...]:
        values = list(candidates)
        values.sort(key=lambda value: value.stable_key)
        values.sort(key=self._candidate_rank, reverse=True)
        return tuple(values)

    def _candidate_rank(self, value: ProxyOrderCandidate) -> tuple:
        metrics = value.metrics
        protection_bucket = math.floor(
            (metrics.protection_compatible_capacity + _EPS)
            / self.settings.protection_materiality
        )
        return (
            int(value.complete),
            value.placed_count,
            value.placed_volume,
            min(3, value.min_alternatives),
            value.support_margin,
            value.clearance_margin,
            protection_bucket,
            metrics.ingress_access,
            metrics.largest_free_region,
            -metrics.sliver_area,
            metrics.low_mass_cog_goodness,
            metrics.low_stack,
            -value.seed_discrepancies,
        )

    def _fair_nodes(self, nodes: Sequence[_OrderNode]) -> tuple[_OrderNode, ...]:
        ordered = sorted(nodes, key=lambda value: value.stable_sequence)
        ordered.sort(key=lambda value: self._candidate_rank(self._to_candidate(value)), reverse=True)
        selected: list[_OrderNode] = []
        selected_ids: set[int] = set()
        for field in ("seed_lane", "last_support_source", "last_container"):
            values = sorted({getattr(node, field) for node in ordered}, key=repr)
            for target in values:
                match = next(
                    (
                        node
                        for node in ordered
                        if getattr(node, field) == target
                        and id(node) not in selected_ids
                    ),
                    None,
                )
                if match is not None:
                    selected.append(match)
                    selected_ids.add(id(match))
                    if len(selected) >= self.settings.beam_width:
                        return tuple(selected)
        selected.extend(node for node in ordered if id(node) not in selected_ids)
        return tuple(selected[: self.settings.beam_width])

    def _to_candidate(
        self,
        node: _OrderNode,
    ) -> ProxyOrderCandidate:
        remaining_positions = {
            value.key.original_position for value in node.state.remaining
        }
        seed_rank = {position: rank for rank, position in enumerate(node.seed_order)}
        tail = tuple(
            sorted(
                (
                    node.authoritative[position]
                    for position in remaining_positions
                ),
                key=lambda value: (
                    seed_rank.get(value.original_position, len(seed_rank)),
                    value.original_position,
                ),
            )
        )
        order = node.placed + tail
        return ProxyOrderCandidate(
            occurrence_order=order,
            skeleton=node.skeleton,
            placed_count=len(node.placed),
            placed_volume=float(node.placed_volume),
            min_alternatives=node.min_alternatives,
            support_margin=float(node.support_margin),
            clearance_margin=float(node.clearance_margin),
            metrics=node.metrics,
            seed_discrepancies=node.seed_discrepancies,
            complete=not node.state.remaining,
            seed_lane=node.seed_lane,
        )

    def _child(
        self,
        parent: _OrderNode,
        state: LayeredProxyState,
        metrics: ProxyMetrics,
        intent: SkeletonIntent,
        item: ItemSpec,
    ) -> _OrderNode:
        expected = next(
            (
                position
                for position in parent.seed_order
                if any(value.key.original_position == position for value in parent.state.remaining)
            ),
            intent.occurrence.original_position,
        )
        discrepancy = int(expected != intent.occurrence.original_position)
        return _OrderNode(
            state=state,
            metrics=metrics,
            authoritative=parent.authoritative,
            seed_lane=parent.seed_lane,
            seed_order=parent.seed_order,
            placed=parent.placed + (intent.occurrence,),
            skeleton=parent.skeleton + (intent,),
            placed_volume=parent.placed_volume + item.volume,
            min_alternatives=(
                intent.alternative_count
                if not parent.skeleton
                else min(parent.min_alternatives, intent.alternative_count)
            ),
            support_margin=(
                intent.support_margin
                if not parent.skeleton
                else min(parent.support_margin, intent.support_margin)
            ),
            clearance_margin=(
                intent.clearance_margin
                if not parent.skeleton
                else min(parent.clearance_margin, intent.clearance_margin)
            ),
            seed_discrepancies=parent.seed_discrepancies + discrepancy,
            last_support_source=intent.support_kind.value,
            last_container=intent.container_ordinal,
            stable_sequence=parent.stable_sequence + (intent.stable_key,),
        )

    def _intent(
        self,
        parent: _OrderNode,
        candidate: ProxyCandidate,
        occurrence: OfflineOccurrence,
        alternatives: int,
        authoritative: tuple[OfflineOccurrence, ...],
    ) -> SkeletonIntent:
        source = candidate.support_source
        if "proxy_top" in source:
            kind = SupportKind.PROXY_TOP
        elif "placed_top" in source:
            kind = SupportKind.PLACED_TOP
        elif "shelf" in source:
            kind = SupportKind.SHELF
        else:
            kind = SupportKind.FLOOR
        supporters: list[OfflineOccurrence] = []
        bottom = float(candidate.box.minimum[2])
        container = parent.state.containers[candidate.container_ordinal]
        for value in container.boxes:
            if (
                value.is_proxy
                and value.occurrence is not None
                and abs(float(value.box.maximum[2]) - bottom) <= 0.002
                and value.box.footprint.intersection(candidate.box.footprint) is not None
            ):
                supporters.append(authoritative[value.occurrence.original_position])
        supporters.sort(key=lambda value: value.stable_key)
        return SkeletonIntent(
            occurrence=occurrence,
            container_ordinal=candidate.container_ordinal,
            orientation=candidate.orientation,
            local_position=tuple(float(value) for value in candidate.position),
            support_kind=kind,
            supporter_occurrences=tuple(supporters),
            alternative_count=alternatives,
            support_margin=float(candidate.support_ratio),
            clearance_margin=float(candidate.min_clearance),
        )

    @staticmethod
    def _proxy_occurrence(
        state: LayeredProxyState, occurrence: OfflineOccurrence
    ) -> ProxyOccurrence:
        matches = tuple(
            value
            for value in state.remaining
            if value.key.original_position == occurrence.original_position
            and value.key.item_index == occurrence.item_index
            and _item_signature(value.item) == occurrence.item_signature
        )
        if len(matches) != 1:
            raise ValueError("offline occurrence is stale or ambiguous")
        return matches[0]

    def _estimated_option_count(
        self,
        item: ItemSpec,
        state: LayeredProxyState | None,
        deadline: float | None,
    ) -> int | None:
        if self._deadline_hit(deadline):
            return None
        orientations = self.proxy.orientation_options(item)
        if state is None:
            return len(orientations)
        count = 0
        for container in state.containers:
            if self._deadline_hit(deadline):
                return None
            for patch in container.supports:
                if self._deadline_hit(deadline):
                    return None
                patch_width = patch.footprint.max_x - patch.footprint.min_x
                patch_length = patch.footprint.max_y - patch.footprint.min_y
                for _orientation, dimensions in orientations:
                    if self._deadline_hit(deadline):
                        return None
                    if (
                        dimensions[0] <= patch_width + _EPS
                        and dimensions[1] <= patch_length + _EPS
                        and patch.placement_bottom + dimensions[2]
                        <= container.inner_ceiling + _EPS
                    ):
                        count += 1
        return count

    def _deadline_hit(self, deadline: float | None) -> bool:
        return deadline is not None and self._expired(deadline)

    @staticmethod
    def _items(
        raw_items: Sequence[dict[str, Any]],
        occurrences: tuple[OfflineOccurrence, ...],
    ) -> tuple[ItemSpec, ...]:
        canonical = build_offline_occurrences(raw_items)
        if tuple(value.stable_key for value in canonical) != tuple(
            value.stable_key for value in occurrences
        ):
            raise ValueError("raw items do not match authoritative occurrences")
        return tuple(ItemSpec.from_dict(value) for value in raw_items)

    def _expired(self, deadline: float) -> bool:
        try:
            now = float(self.clock())
        except Exception:
            return True
        return not math.isfinite(now) or now >= deadline


__all__ = [
    "LayeredProxyOrderBeam",
    "ModeAOrderBeamSettings",
    "ModeAOrderBeamTrace",
    "ProxyOrderCandidate",
]
