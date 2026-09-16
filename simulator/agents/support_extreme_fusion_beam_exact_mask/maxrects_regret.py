"""Fixed-work Layered MaxRects regret rollout over strict depth-zero roots.

Only roots already owned by the current exact catalog can leave this module.
All descendants are immutable analytical proxy values used solely for ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
import time
from typing import Sequence

from .catalog import RootCatalog, RootRecord
from .layered_proxy import (
    CheckedProxyTransition,
    LayeredProxy,
    LayeredProxyState,
    OccurrenceKey,
    ProxyCandidate,
    ProxyMetrics,
    ProxyOccurrence,
    ProxyExposureOrder,
    ProxyTopologyCache,
    ProxyWork,
    ProxyWorkQuota,
    maximal_empty_rectangles,
)
from .mask import ExactMask
from .model import ItemSpec, ValidatedRoot
from .settings import SearchSettings
from .transition import SimState, apply_root


_EPS = 1.0e-12


class RankObjective(str, Enum):
    """Non-profile proxy ranking objective."""

    LEGACY = "legacy"
    CERTIFIED_CONTINUATION_SURVIVAL = "certified_continuation_survival"


@dataclass(frozen=True)
class ContinuationAudit:
    """Occurrence-complete continuation evidence for one rollout node."""

    total_occurrences: int
    audited_occurrences: int
    option_occurrences: int
    option_volume: float
    zero_option_occurrences: int
    minimum_options_all: int
    complete: bool

    def __post_init__(self) -> None:
        integer_fields = (
            self.total_occurrences,
            self.audited_occurrences,
            self.option_occurrences,
            self.zero_option_occurrences,
            self.minimum_options_all,
        )
        if any(type(value) is not int or value < 0 for value in integer_fields):
            raise ValueError("continuation audit counts must be non-negative exact ints")
        if type(self.complete) is not bool:
            raise TypeError("continuation audit complete must be an exact bool")
        volume = float(self.option_volume)
        if not math.isfinite(volume) or volume < 0.0:
            raise ValueError("continuation audit option_volume must be finite and non-negative")
        if self.audited_occurrences > self.total_occurrences:
            raise ValueError("audited occurrence count exceeds total")
        if self.option_occurrences + self.zero_option_occurrences != self.audited_occurrences:
            raise ValueError("audited occurrence partition is inconsistent")
        if self.complete != (self.audited_occurrences == self.total_occurrences):
            raise ValueError("complete must exactly describe occurrence coverage")


@dataclass(frozen=True)
class SelectionTrace:
    root_lineages: tuple[tuple, ...] = ()
    nodes: int = 0
    fit_tests: int = 0
    candidates: int = 0
    deepest: int = 0
    node_quota_exhausted: bool = False
    fit_quota_exhausted: bool = False
    candidate_quota_exhausted: bool = False
    deadline_reached: bool = False
    invalid_lineages: int = 0
    branch_exceptions: int = 0
    expanded_occurrences: tuple[int, ...] = ()
    expanded_lineages: tuple[int, ...] = ()
    ranked_keys: tuple[tuple, ...] = ()
    predicted_count: int = 0
    predicted_volume: float = 0.0
    largest_free_region: float = 0.0
    duplicate_checks_avoided: int = 0
    topology_cache_hits: int = 0
    committed_children: int = 0
    completed_partial_level: bool = False
    exposure_by_support_source: tuple[tuple[str, int], ...] = ()
    exposure_by_orientation: tuple[tuple[int, int], ...] = ()
    zero_candidate_nodes: int = 0


@dataclass(frozen=True)
class _RolloutNode:
    proxy_state: LayeredProxyState
    first_root: ValidatedRoot
    root_key: tuple
    lineage_id: int
    depth: int
    placed_count: int
    placed_volume: float
    metrics: ProxyMetrics
    remaining_fit_count: int
    remaining_fit_volume: float
    minimum_nonzero_options: int
    cumulative_backness: float
    stable_sequence_key: tuple
    continuation_audit: ContinuationAudit | None = None


@dataclass(frozen=True)
class _CandidateChoice:
    candidate: ProxyCandidate
    cost: float
    stable_key: tuple


@dataclass(frozen=True)
class _ItemPlan:
    occurrence: ProxyOccurrence
    choices: tuple[_CandidateChoice, ...]
    regret: float

    @property
    def feasible_count(self) -> int:
        return len(self.choices)


@dataclass(frozen=True)
class _CheckedCandidateChoice:
    transition: CheckedProxyTransition
    cost: float
    stable_key: tuple

    @property
    def candidate(self) -> ProxyCandidate:
        return self.transition.candidate


@dataclass(frozen=True)
class _CheckedItemPlan:
    occurrence: ProxyOccurrence
    choices: tuple[_CheckedCandidateChoice, ...]
    regret: float

    @property
    def feasible_count(self) -> int:
        return len(self.choices)


class RegretProxySelector:
    """Rank original strict roots using deterministic proxy-only rollout."""

    def __init__(
        self,
        mask: ExactMask,
        *,
        proxy: LayeredProxy | None = None,
        settings: SearchSettings | None = None,
        max_lineages: int = 24,
        max_depth: int = 12,
        beam_width: int = 32,
        max_nodes: int = 768,
        max_fit_tests: int = 96_000,
        items_per_node: int = 4,
        placements_per_item: int = 3,
        children_per_node: int = 12,
        analysis_fit_quantum: int = 128,
        occurrence_fit_quantum: int = 8,
        protection_materiality: float = 0.01,
        clock=None,
    ) -> None:
        if not isinstance(mask, ExactMask):
            raise TypeError("mask must be an ExactMask")
        self.settings = settings or SearchSettings()
        if mask.profile_digest != self.settings.profile_digest():
            raise ValueError("exact mask profile does not match selector settings")
        self.mask = mask
        self.proxy = proxy or LayeredProxy()
        self.max_lineages = self._positive_int(max_lineages, "max_lineages")
        self.max_depth = self._positive_int(max_depth, "max_depth")
        self.beam_width = self._positive_int(beam_width, "beam_width")
        self.items_per_node = self._positive_int(items_per_node, "items_per_node")
        self.placements_per_item = self._positive_int(
            placements_per_item, "placements_per_item"
        )
        self.children_per_node = self._positive_int(
            children_per_node, "children_per_node"
        )
        self.analysis_fit_quantum = self._positive_int(
            analysis_fit_quantum, "analysis_fit_quantum"
        )
        self.occurrence_fit_quantum = self._positive_int(
            occurrence_fit_quantum, "occurrence_fit_quantum"
        )
        nodes = self._positive_int(max_nodes, "max_nodes")
        fit_tests = self._positive_int(max_fit_tests, "max_fit_tests")
        self.proxy_quota = ProxyWorkQuota(
            max_nodes=nodes,
            max_fit_tests=fit_tests,
            max_candidates=fit_tests,
        )
        if isinstance(protection_materiality, bool):
            raise ValueError("protection_materiality must be finite and positive")
        materiality = float(protection_materiality)
        if not math.isfinite(materiality) or materiality <= 0.0:
            raise ValueError("protection_materiality must be finite and positive")
        self.protection_materiality = materiality
        self.clock = clock or time.perf_counter
        self.last_trace = SelectionTrace()

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive exact int")
        return value

    def select(
        self,
        sim: SimState,
        catalog: RootCatalog,
        mode: str,
        deadline: float,
    ) -> tuple[ValidatedRoot, ...]:
        if not isinstance(sim, SimState):
            raise TypeError("sim must be a SimState")
        if not isinstance(catalog, RootCatalog):
            raise TypeError("catalog must be a RootCatalog")
        normalized_mode = str(mode).upper()
        if normalized_mode not in {"B", "C"}:
            raise ValueError("mode must be B or C")
        if not math.isfinite(float(deadline)):
            raise ValueError("deadline must be finite")

        work = ProxyWork()
        nodes: list[_RolloutNode] = []
        root_keys: list[tuple] = []
        invalid = branch_exceptions = 0
        deadline_reached = False
        seen_roots: set[tuple] = set()
        for record in self._fair_root_records(catalog.records):
            if len(nodes) >= self.max_lineages or work.nodes >= self.proxy_quota.max_nodes:
                break
            if self._expired(deadline):
                deadline_reached = True
                break
            identity = (record.root.state_fingerprint, record.root.proposal_key)
            if identity in seen_roots:
                continue
            seen_roots.add(identity)
            try:
                placement = apply_root(
                    sim,
                    record.root,
                    self.settings,
                    exact_revalidator=self.mask,
                    deadline=deadline,
                )
                if self._expired(deadline):
                    deadline_reached = True
                    break
                proxy_state = self.proxy.from_sim_state(placement.child)
                metrics = self.proxy.metrics(proxy_state)
                if self._expired(deadline):
                    deadline_reached = True
                    break
                work = work.consume_node(self.proxy_quota)
            except Exception:
                invalid += 1
                if self._expired(deadline):
                    deadline_reached = True
                    break
                continue
            item = sim.pool[placement.selected_pool_index]
            root_key = record.stable_key
            lineage_id = len(nodes)
            node = _RolloutNode(
                proxy_state=proxy_state,
                first_root=record.root,
                root_key=root_key,
                lineage_id=lineage_id,
                depth=1,
                placed_count=1,
                placed_volume=float(item.volume),
                metrics=metrics,
                remaining_fit_count=0,
                remaining_fit_volume=0.0,
                minimum_nonzero_options=0,
                cumulative_backness=self._root_backness(sim, record),
                stable_sequence_key=(root_key,),
            )
            nodes.append(node)
            root_keys.append(root_key)

        if not nodes:
            self.last_trace = self._trace(
                work,
                (),
                root_keys,
                invalid,
                branch_exceptions,
                (),
                (),
                deadline_reached or self._expired(deadline),
                0,
            )
            return ()

        best_by_lineage = {node.lineage_id: node for node in nodes}
        expanded_occurrences: list[int] = []
        expanded_lineages: list[int] = []
        frontier = self._fair_prune(nodes)

        if normalized_mode == "B":
            for _level in range(1, min(self.max_depth, len(sim.pool))):
                if not frontier or work.quota_exhausted(self.proxy_quota):
                    break
                analyzed: list[tuple[_RolloutNode, tuple[_ItemPlan, ...]]] = []
                analysis_order = self._fair_node_order(frontier)
                for analysis_index, node in enumerate(analysis_order):
                    if self._expired(deadline):
                        deadline_reached = True
                        break
                    local_quota = self._analysis_quota(
                        work,
                        len(analysis_order) - analysis_index,
                    )
                    try:
                        updated, plans, work, analyze_exceptions = self._analyze(
                            node,
                            work,
                            deadline,
                            local_quota,
                        )
                    except Exception:
                        branch_exceptions += 1
                        continue
                    branch_exceptions += analyze_exceptions
                    expanded_lineages.append(node.lineage_id)
                    if plans:
                        expanded_occurrences.extend(
                            plan.occurrence.key.original_position
                            for plan in plans[: self.items_per_node]
                        )
                    analyzed.append((updated, plans))
                    best_by_lineage[updated.lineage_id] = self._prefer(
                        best_by_lineage[updated.lineage_id], updated
                    )
                if deadline_reached:
                    break
                child_queues: dict[int, list[tuple[_RolloutNode, _CandidateChoice, ProxyOccurrence]]] = {}
                for node, plans in analyzed:
                    queued: list[tuple[_RolloutNode, _CandidateChoice, ProxyOccurrence]] = []
                    for plan in plans[: self.items_per_node]:
                        for choice in plan.choices[: self.placements_per_item]:
                            queued.append((node, choice, plan.occurrence))
                    child_queues.setdefault(node.lineage_id, []).extend(
                        queued[: self.children_per_node]
                    )
                children: list[_RolloutNode] = []
                for parent, choice, occurrence in self._round_robin_children(child_queues):
                    if work.nodes >= self.proxy_quota.max_nodes:
                        break
                    if self._expired(deadline):
                        deadline_reached = True
                        break
                    try:
                        child_state = self.proxy.apply(parent.proxy_state, choice.candidate)
                        child_metrics = self.proxy.metrics(child_state)
                        if self._expired(deadline):
                            deadline_reached = True
                            break
                        work = work.consume_node(self.proxy_quota)
                        child = _RolloutNode(
                            proxy_state=child_state,
                            first_root=parent.first_root,
                            root_key=parent.root_key,
                            lineage_id=parent.lineage_id,
                            depth=parent.depth + 1,
                            placed_count=parent.placed_count + 1,
                            placed_volume=parent.placed_volume + occurrence.item.volume,
                            metrics=child_metrics,
                            remaining_fit_count=0,
                            remaining_fit_volume=0.0,
                            minimum_nonzero_options=0,
                            cumulative_backness=(
                                parent.cumulative_backness
                                + self._candidate_backness(parent.proxy_state, choice.candidate)
                            ),
                            stable_sequence_key=(
                                parent.stable_sequence_key + (choice.stable_key,)
                            ),
                        )
                    except Exception:
                        branch_exceptions += 1
                        continue
                    children.append(child)
                    best_by_lineage[child.lineage_id] = self._prefer(
                        best_by_lineage[child.lineage_id], child
                    )
                frontier = self._fair_prune(children)
                if deadline_reached:
                    break

        ranked_nodes = self._ordered(tuple(best_by_lineage.values()))
        ranked_roots = tuple(node.first_root for node in ranked_nodes)
        ranked_keys = tuple(node.root_key for node in ranked_nodes)
        self.last_trace = self._trace(
            work,
            ranked_keys,
            root_keys,
            invalid,
            branch_exceptions,
            expanded_occurrences,
            expanded_lineages,
            deadline_reached or self._expired(deadline),
            max((node.depth for node in best_by_lineage.values()), default=0),
            ranked_nodes[0] if ranked_nodes else None,
        )
        return ranked_roots

    def _trace(
        self,
        work: ProxyWork,
        ranked_keys: Sequence[tuple],
        root_keys: Sequence[tuple],
        invalid: int,
        branch_exceptions: int,
        expanded_occurrences: Sequence[int],
        expanded_lineages: Sequence[int],
        deadline_reached: bool,
        deepest: int,
        best_node: _RolloutNode | None = None,
        *,
        duplicate_checks_avoided: int = 0,
        topology_cache_hits: int = 0,
        committed_children: int = 0,
        completed_partial_level: bool = False,
        exposure_by_support_source: Sequence[tuple[str, int]] = (),
        exposure_by_orientation: Sequence[tuple[int, int]] = (),
        zero_candidate_nodes: int = 0,
    ) -> SelectionTrace:
        return SelectionTrace(
            root_lineages=tuple(root_keys),
            nodes=work.nodes,
            fit_tests=work.fit_tests,
            candidates=work.candidates,
            deepest=deepest,
            node_quota_exhausted=work.nodes >= self.proxy_quota.max_nodes,
            fit_quota_exhausted=work.fit_tests >= self.proxy_quota.max_fit_tests,
            candidate_quota_exhausted=(
                work.candidates >= self.proxy_quota.max_candidates
            ),
            deadline_reached=bool(deadline_reached),
            invalid_lineages=invalid,
            branch_exceptions=branch_exceptions,
            expanded_occurrences=tuple(expanded_occurrences),
            expanded_lineages=tuple(expanded_lineages),
            ranked_keys=tuple(ranked_keys),
            predicted_count=0 if best_node is None else best_node.placed_count,
            predicted_volume=0.0 if best_node is None else best_node.placed_volume,
            largest_free_region=(
                0.0 if best_node is None else best_node.metrics.largest_free_region
            ),
            duplicate_checks_avoided=int(duplicate_checks_avoided),
            topology_cache_hits=int(topology_cache_hits),
            committed_children=int(committed_children),
            completed_partial_level=bool(completed_partial_level),
            exposure_by_support_source=tuple(exposure_by_support_source),
            exposure_by_orientation=tuple(exposure_by_orientation),
            zero_candidate_nodes=int(zero_candidate_nodes),
        )

    def _analyze(
        self,
        node: _RolloutNode,
        work: ProxyWork,
        deadline: float,
        local_quota: ProxyWorkQuota,
    ) -> tuple[_RolloutNode, tuple[_ItemPlan, ...], ProxyWork, int]:
        plans: list[_ItemPlan] = []
        current = work
        exceptions = 0
        for occurrence in sorted(
            node.proxy_state.remaining,
            key=lambda value: value.key,
        ):
            if self._expired(deadline) or current.quota_exhausted(local_quota):
                break
            call_quota = replace(
                local_quota,
                max_fit_tests=min(
                    local_quota.max_fit_tests,
                    current.fit_tests + self.occurrence_fit_quantum,
                ),
                max_candidates=min(
                    local_quota.max_candidates,
                    current.candidates + self.occurrence_fit_quantum,
                ),
            )
            try:
                batch = self.proxy.enumerate_candidates(
                    node.proxy_state,
                    occurrence.key,
                    current,
                    call_quota,
                )
            except Exception:
                exceptions += 1
                continue
            current = batch.work
            choices: list[_CandidateChoice] = []
            for candidate in batch.candidates:
                if self._expired(deadline):
                    break
                try:
                    child_state = self.proxy.apply(node.proxy_state, candidate)
                    after = self.proxy.metrics(child_state)
                    stable = self._candidate_key(candidate)
                    choices.append(
                        _CandidateChoice(
                            candidate,
                            self._local_cost(
                                node.proxy_state,
                                node.metrics,
                                after,
                                candidate,
                            ),
                            stable,
                        )
                    )
                except Exception:
                    exceptions += 1
                    continue
            choices.sort(key=lambda value: (value.cost, value.stable_key))
            if choices:
                regret = (
                    math.inf
                    if len(choices) == 1
                    else max(0.0, choices[1].cost - choices[0].cost)
                )
                plans.append(_ItemPlan(occurrence, tuple(choices), regret))

        feasible_count = len(plans)
        feasible_volume = sum(plan.occurrence.item.volume for plan in plans)
        minimum = min((plan.feasible_count for plan in plans), default=0)
        updated = replace(
            node,
            remaining_fit_count=feasible_count,
            remaining_fit_volume=feasible_volume,
            minimum_nonzero_options=minimum,
        )
        plans.sort(key=lambda plan: plan.occurrence.key)
        plans.sort(key=lambda plan: plan.occurrence.item.volume, reverse=True)
        plans.sort(key=lambda plan: plan.feasible_count)
        plans.sort(key=lambda plan: plan.regret, reverse=True)
        plans.sort(key=lambda plan: plan.feasible_count == 1, reverse=True)
        return updated, tuple(plans), current, exceptions

    def _analysis_quota(
        self,
        work: ProxyWork,
        remaining_nodes: int,
    ) -> ProxyWorkQuota:
        count = max(1, int(remaining_nodes))
        remaining_fit = max(0, self.proxy_quota.max_fit_tests - work.fit_tests)
        remaining_candidates = max(
            0,
            self.proxy_quota.max_candidates - work.candidates,
        )
        fit_share = (
            min(self.analysis_fit_quantum, max(1, remaining_fit // count))
            if remaining_fit
            else 0
        )
        candidate_share = (
            max(1, remaining_candidates // count) if remaining_candidates else 0
        )
        return ProxyWorkQuota(
            max_nodes=self.proxy_quota.max_nodes,
            max_fit_tests=max(work.fit_tests + fit_share, 1),
            max_candidates=max(work.candidates + candidate_share, 1),
            max_rectangles_per_patch=self.proxy_quota.max_rectangles_per_patch,
        )

    def _local_cost(
        self,
        state: LayeredProxyState,
        before: ProxyMetrics,
        after: ProxyMetrics,
        candidate: ProxyCandidate,
    ) -> float:
        container = state.containers[candidate.container_ordinal]
        area_waste, short_waste, long_waste = self._maxrect_waste(
            container,
            candidate,
        )
        ingress_loss = max(0.0, before.ingress_access - after.ingress_access)
        protection_loss = max(
            0.0,
            before.protection_compatible_capacity
            - after.protection_compatible_capacity,
        )
        stack_cost = max(0.0, 1.0 - after.low_stack)
        backness = self._candidate_backness(state, candidate)
        value = (
            3.0 * area_waste
            + 0.50 * short_waste
            + 0.25 * long_waste
            + 2.0 * ingress_loss
            + 2.0 * protection_loss
            + 0.50 * stack_cost
            - 0.25 * backness
        )
        return float(value) if math.isfinite(float(value)) else math.inf

    @staticmethod
    def _checked_local_cost(transition: CheckedProxyTransition) -> float:
        area_waste, short_waste, long_waste = transition.maxrect_waste
        ingress_loss, protection_loss, stack_cost, backness = (
            transition.local_cost_inputs
        )
        value = (
            3.0 * area_waste
            + 0.50 * short_waste
            + 0.25 * long_waste
            + 2.0 * ingress_loss
            + 2.0 * protection_loss
            + 0.50 * stack_cost
            - 0.25 * backness
        )
        return float(value) if math.isfinite(float(value)) else math.inf

    @staticmethod
    def _maxrect_waste(container, candidate: ProxyCandidate) -> tuple[float, float, float]:
        box = candidate.box.footprint
        dx = max(_EPS, box.max_x - box.min_x)
        dy = max(_EPS, box.max_y - box.min_y)
        fallback = container.inner_floor
        rectangles = []
        supports = getattr(container, "supports", ())
        boxes = getattr(container, "boxes", ())
        for patch in supports:
            if abs(float(candidate.box.minimum[2]) - patch.placement_bottom) > 0.001:
                continue
            if patch.footprint.intersection(box) is None:
                continue
            blockers = tuple(
                value.box.footprint
                for value in boxes
                if value.box.maximum[2] > patch.height + _EPS
                and value.box.minimum[2] <= patch.placement_bottom + 0.001
                and patch.footprint.intersection(value.box.footprint) is not None
            )
            rectangles.extend(
                rectangle
                for rectangle in maximal_empty_rectangles(
                    patch.footprint,
                    blockers,
                    limit=128,
                )
                if rectangle.min_x <= box.min_x + _EPS
                and rectangle.max_x >= box.max_x - _EPS
                and rectangle.min_y <= box.min_y + _EPS
                and rectangle.max_y >= box.max_y - _EPS
            )
        if not rectangles:
            rectangles = [fallback]
        values = []
        for rectangle in rectangles:
            width = max(_EPS, rectangle.max_x - rectangle.min_x)
            length = max(_EPS, rectangle.max_y - rectangle.min_y)
            waste_x = max(0.0, width - dx) / width
            waste_y = max(0.0, length - dy) / length
            values.append(
                (
                    max(0.0, rectangle.area - box.area) / max(_EPS, rectangle.area),
                    min(waste_x, waste_y),
                    max(waste_x, waste_y),
                )
            )
        return min(values)

    def _rank(self, node: _RolloutNode) -> tuple[float, ...]:
        metrics = node.metrics
        protection_bucket = math.floor(
            (metrics.protection_compatible_capacity + _EPS)
            / self.protection_materiality
        )
        scarcity = (
            -float(node.minimum_nonzero_options)
            if node.minimum_nonzero_options > 0
            else -1.0e9
        )
        return (
            float(node.placed_count),
            float(node.placed_volume),
            float(node.remaining_fit_count),
            float(node.remaining_fit_volume),
            scarcity,
            float(protection_bucket),
            metrics.ingress_access,
            metrics.largest_free_region,
            -metrics.sliver_area,
            metrics.low_mass_cog_goodness,
            metrics.low_stack,
            node.first_root.support_ratio,
            node.first_root.min_clearance,
            node.cumulative_backness,
        )

    def _ordered(self, nodes: Sequence[_RolloutNode]) -> list[_RolloutNode]:
        ordered = sorted(nodes, key=lambda node: node.stable_sequence_key)
        ordered.sort(key=self._rank, reverse=True)
        return ordered

    def _prefer(self, current: _RolloutNode, candidate: _RolloutNode) -> _RolloutNode:
        return self._ordered((current, candidate))[0]

    def _fair_prune(self, nodes: Sequence[_RolloutNode]) -> list[_RolloutNode]:
        ordered = self._ordered(nodes)
        first: list[_RolloutNode] = []
        rest: list[_RolloutNode] = []
        seen: set[int] = set()
        for node in ordered:
            if node.lineage_id in seen:
                rest.append(node)
            else:
                seen.add(node.lineage_id)
                first.append(node)
        return (first + rest)[: self.beam_width]

    def _fair_node_order(self, nodes: Sequence[_RolloutNode]) -> tuple[_RolloutNode, ...]:
        return tuple(self._fair_prune(nodes))

    @staticmethod
    def _round_robin_children(queues):
        ordered = {key: list(queues[key]) for key in sorted(queues)}
        result = []
        while ordered:
            empty = []
            for key in tuple(sorted(ordered)):
                values = ordered[key]
                if values:
                    result.append(values.pop(0))
                if not values:
                    empty.append(key)
            for key in empty:
                ordered.pop(key, None)
        return tuple(result)

    @staticmethod
    def _candidate_key(candidate: ProxyCandidate) -> tuple:
        return (
            candidate.occurrence.original_position,
            candidate.item_index,
            candidate.container_ordinal,
            candidate.orientation,
            tuple(round(float(value), 8) for value in candidate.position),
            candidate.anchor,
        )

    @staticmethod
    def _candidate_backness(
        state: LayeredProxyState,
        candidate: ProxyCandidate,
    ) -> float:
        floor = state.containers[candidate.container_ordinal].inner_floor
        span = max(_EPS, floor.max_y - floor.min_y)
        return min(1.0, max(0.0, (candidate.position[1] - floor.min_y) / span))

    @staticmethod
    def _root_backness(sim: SimState, record: RootRecord) -> float:
        container = sim.packing.containers[record.container_index]
        minimum = -container.width / 2.0 + container.thickness
        maximum = container.width / 2.0 - container.thickness
        span = max(_EPS, maximum - minimum)
        return min(
            1.0,
            max(0.0, (record.proposal.position[1] - minimum) / span),
        )

    @staticmethod
    def _fair_root_records(records: Sequence[RootRecord]) -> tuple[RootRecord, ...]:
        by_pool: dict[int, list[RootRecord]] = {}
        for record in records:
            by_pool.setdefault(record.pool_index, []).append(record)
        scheduled: dict[int, list[RootRecord]] = {}
        for pool_index, values in by_pool.items():
            by_family: dict[tuple[int, int], list[RootRecord]] = {}
            for record in sorted(values, key=lambda value: value.stable_key):
                by_family.setdefault(
                    (record.container_index, record.orientation), []
                ).append(record)
            family_values: list[RootRecord] = []
            while by_family:
                empty = []
                for family in tuple(sorted(by_family)):
                    group = by_family[family]
                    family_values.append(group.pop(0))
                    if not group:
                        empty.append(family)
                for family in empty:
                    by_family.pop(family, None)
            scheduled[pool_index] = family_values
        result: list[RootRecord] = []
        while scheduled:
            empty = []
            for pool_index in tuple(sorted(scheduled)):
                values = scheduled[pool_index]
                result.append(values.pop(0))
                if not values:
                    empty.append(pool_index)
            for pool_index in empty:
                scheduled.pop(pool_index, None)
        return tuple(result)

    def _expired(self, deadline: float) -> bool:
        try:
            now = float(self.clock())
        except Exception:
            return True
        return not math.isfinite(now) or now >= float(deadline)


class MemoizedStreamingRegretProxySelector(RegretProxySelector):
    """Same fixed-work policy with checked previews and streaming checkpoints."""

    def __init__(
        self,
        mask: ExactMask,
        *,
        exposure_order: ProxyExposureOrder = ProxyExposureOrder.LEGACY_NESTED,
        rank_objective: RankObjective = RankObjective.LEGACY,
        **kwargs,
    ) -> None:
        if type(exposure_order) is not ProxyExposureOrder:
            raise TypeError("exposure_order must be exact ProxyExposureOrder")
        if type(rank_objective) is not RankObjective:
            raise TypeError("rank_objective must be exact RankObjective")
        super().__init__(mask, **kwargs)
        self.exposure_order = exposure_order
        self.rank_objective = rank_objective

    def _rank(self, node: _RolloutNode) -> tuple[float, ...]:
        if self.rank_objective is RankObjective.LEGACY:
            return super()._rank(node)
        audit = node.continuation_audit
        if audit is None or not audit.complete:
            return (-math.inf,) * 14
        metrics = node.metrics
        protection_bucket = math.floor(
            (metrics.protection_compatible_capacity + _EPS)
            / self.protection_materiality
        )
        robustness = (
            2
            if audit.total_occurrences == 0
            else min(2, audit.minimum_options_all)
        )
        return (
            float(node.placed_count + audit.option_occurrences),
            float(robustness),
            float(node.placed_volume + audit.option_volume),
            float(node.placed_count),
            float(node.placed_volume),
            float(protection_bucket),
            metrics.ingress_access,
            metrics.largest_free_region,
            -metrics.sliver_area,
            metrics.low_mass_cog_goodness,
            metrics.low_stack,
            node.first_root.support_ratio,
            node.first_root.min_clearance,
            node.cumulative_backness,
        )

    def select(
        self,
        sim: SimState,
        catalog: RootCatalog,
        mode: str,
        deadline: float,
    ) -> tuple[ValidatedRoot, ...]:
        if not isinstance(sim, SimState):
            raise TypeError("sim must be a SimState")
        if not isinstance(catalog, RootCatalog):
            raise TypeError("catalog must be a RootCatalog")
        normalized_mode = str(mode).upper()
        if normalized_mode not in {"B", "C"}:
            raise ValueError("mode must be B or C")
        if not math.isfinite(float(deadline)):
            raise ValueError("deadline must be finite")

        topology_cache = ProxyTopologyCache()
        work = ProxyWork()
        nodes: list[_RolloutNode] = []
        root_keys: list[tuple] = []
        invalid = branch_exceptions = 0
        deadline_reached = False
        duplicate_checks_avoided = 0
        committed_children = 0
        completed_partial_level = False
        exposure_sources: dict[str, int] = {}
        exposure_orientations: dict[int, int] = {}
        zero_candidate_nodes = 0
        seen_roots: set[tuple] = set()
        for record in self._fair_root_records(catalog.records):
            if len(nodes) >= self.max_lineages or work.nodes >= self.proxy_quota.max_nodes:
                break
            if self._expired(deadline):
                deadline_reached = True
                break
            identity = (record.root.state_fingerprint, record.root.proposal_key)
            if identity in seen_roots:
                continue
            seen_roots.add(identity)
            try:
                placement = apply_root(
                    sim,
                    record.root,
                    self.settings,
                    exact_revalidator=self.mask,
                    deadline=deadline,
                )
                if self._expired(deadline):
                    deadline_reached = True
                    break
                proxy_state = self.proxy.from_sim_state(placement.child)
                metrics = self.proxy.metrics(
                    proxy_state, topology_cache=topology_cache
                )
                if self._expired(deadline):
                    deadline_reached = True
                    break
                work = work.consume_node(self.proxy_quota)
            except Exception:
                invalid += 1
                if self._expired(deadline):
                    deadline_reached = True
                    break
                continue
            item = sim.pool[placement.selected_pool_index]
            root_key = record.stable_key
            lineage_id = len(nodes)
            nodes.append(
                _RolloutNode(
                    proxy_state=proxy_state,
                    first_root=record.root,
                    root_key=root_key,
                    lineage_id=lineage_id,
                    depth=1,
                    placed_count=1,
                    placed_volume=float(item.volume),
                    metrics=metrics,
                    remaining_fit_count=0,
                    remaining_fit_volume=0.0,
                    minimum_nonzero_options=0,
                    cumulative_backness=self._root_backness(sim, record),
                    stable_sequence_key=(root_key,),
                    continuation_audit=(
                        ContinuationAudit(0, 0, 0, 0.0, 0, 0, True)
                        if (
                            self.rank_objective
                            is RankObjective.CERTIFIED_CONTINUATION_SURVIVAL
                            and not proxy_state.remaining
                        )
                        else None
                    ),
                )
            )
            root_keys.append(root_key)

        if not nodes:
            self.last_trace = self._trace(
                work,
                (),
                root_keys,
                invalid,
                branch_exceptions,
                (),
                (),
                deadline_reached or self._expired(deadline),
                0,
                duplicate_checks_avoided=duplicate_checks_avoided,
                topology_cache_hits=topology_cache.hits,
            )
            return ()

        best_by_lineage = {node.lineage_id: node for node in nodes}
        survival_objective = (
            self.rank_objective
            is RankObjective.CERTIFIED_CONTINUATION_SURVIVAL
        )
        published_cohort: tuple[_RolloutNode, ...] = tuple(nodes)
        deepest_seen = max((node.depth for node in nodes), default=0)
        expanded_occurrences: list[int] = []
        expanded_lineages: list[int] = []
        frontier = self._fair_prune(nodes)

        if normalized_mode == "B":
            for _level in range(1, min(self.max_depth, len(sim.pool))):
                if not frontier or work.quota_exhausted(self.proxy_quota):
                    break
                child_queues: dict[
                    int,
                    list[
                        tuple[
                            _RolloutNode,
                            _CheckedCandidateChoice,
                            ProxyOccurrence,
                        ]
                    ],
                ] = {}
                children: list[_RolloutNode] = []
                analysis_order = self._fair_node_order(frontier)
                cohort_updates: list[_RolloutNode] = []
                cohort_closed = True
                for analysis_index, node in enumerate(analysis_order):
                    if self._expired(deadline):
                        deadline_reached = True
                        completed_partial_level = completed_partial_level or bool(children)
                        cohort_closed = False
                        break
                    local_quota = self._analysis_quota(
                        work,
                        len(analysis_order) - analysis_index,
                    )
                    try:
                        (
                            updated,
                            plans,
                            work,
                            analyze_exceptions,
                            previews,
                            exposure_rows,
                            zero_candidate_node,
                        ) = self._analyze_checked(
                            node,
                            work,
                            deadline,
                            local_quota,
                            topology_cache,
                        )
                    except Exception:
                        branch_exceptions += 1
                        cohort_closed = False
                        continue
                    expired_after_analysis = self._expired(deadline)
                    branch_exceptions += analyze_exceptions
                    duplicate_checks_avoided += previews
                    for source, orientation in exposure_rows:
                        exposure_sources[source] = exposure_sources.get(source, 0) + 1
                        exposure_orientations[orientation] = (
                            exposure_orientations.get(orientation, 0) + 1
                        )
                    zero_candidate_nodes += int(zero_candidate_node)
                    if expired_after_analysis:
                        deadline_reached = True
                        completed_partial_level = completed_partial_level or bool(children)
                        cohort_closed = False
                        break
                    cohort_updates.append(updated)
                    if (
                        survival_objective
                        and (
                            updated.continuation_audit is None
                            or not updated.continuation_audit.complete
                        )
                    ):
                        cohort_closed = False
                    expanded_lineages.append(node.lineage_id)
                    if plans:
                        expanded_occurrences.extend(
                            plan.occurrence.key.original_position
                            for plan in plans[: self.items_per_node]
                        )
                    if not survival_objective:
                        best_by_lineage[updated.lineage_id] = self._prefer(
                            best_by_lineage[updated.lineage_id], updated
                        )
                    queued: list[
                        tuple[_RolloutNode, _CheckedCandidateChoice, ProxyOccurrence]
                    ] = []
                    for plan in plans[: self.items_per_node]:
                        for choice in plan.choices[: self.placements_per_item]:
                            queued.append((updated, choice, plan.occurrence))
                    queue = queued[: self.children_per_node]
                    if queue:
                        first = queue.pop(0)
                        child, work, failed = self._commit_checked_child(
                            first[0],
                            first[1],
                            first[2],
                            work,
                            topology_cache,
                        )
                        branch_exceptions += int(failed)
                        if child is not None:
                            children.append(child)
                            deepest_seen = max(deepest_seen, child.depth)
                            committed_children += 1
                            duplicate_checks_avoided += 1
                            if not survival_objective:
                                best_by_lineage[child.lineage_id] = self._prefer(
                                    best_by_lineage[child.lineage_id], child
                                )
                    if queue:
                        child_queues.setdefault(updated.lineage_id, []).extend(queue)
                    if self._expired(deadline):
                        deadline_reached = True
                        completed_partial_level = completed_partial_level or bool(children)
                        cohort_closed = False
                        break

                if not deadline_reached:
                    for parent, choice, occurrence in self._round_robin_children(
                        child_queues
                    ):
                        if work.nodes >= self.proxy_quota.max_nodes:
                            break
                        if self._expired(deadline):
                            deadline_reached = True
                            completed_partial_level = completed_partial_level or bool(children)
                            break
                        child, work, failed = self._commit_checked_child(
                            parent,
                            choice,
                            occurrence,
                            work,
                            topology_cache,
                        )
                        branch_exceptions += int(failed)
                        if child is None:
                            continue
                        children.append(child)
                        deepest_seen = max(deepest_seen, child.depth)
                        committed_children += 1
                        duplicate_checks_avoided += 1
                        if not survival_objective:
                            best_by_lineage[child.lineage_id] = self._prefer(
                                best_by_lineage[child.lineage_id], child
                            )
                if (
                    survival_objective
                    and cohort_closed
                    and len(cohort_updates) == len(analysis_order)
                ):
                    published_cohort = tuple(cohort_updates)
                frontier = self._fair_prune(children)
                if deadline_reached:
                    break

        rank_pool = (
            published_cohort
            if survival_objective
            else tuple(best_by_lineage.values())
        )
        ranked_nodes = self._ordered(rank_pool)
        ranked_roots = tuple(node.first_root for node in ranked_nodes)
        ranked_keys = tuple(node.root_key for node in ranked_nodes)
        self.last_trace = self._trace(
            work,
            ranked_keys,
            root_keys,
            invalid,
            branch_exceptions,
            expanded_occurrences,
            expanded_lineages,
            deadline_reached or self._expired(deadline),
            deepest_seen,
            ranked_nodes[0] if ranked_nodes else None,
            duplicate_checks_avoided=duplicate_checks_avoided,
            topology_cache_hits=topology_cache.hits,
            committed_children=committed_children,
            completed_partial_level=completed_partial_level,
            exposure_by_support_source=tuple(sorted(exposure_sources.items())),
            exposure_by_orientation=tuple(sorted(exposure_orientations.items())),
            zero_candidate_nodes=zero_candidate_nodes,
        )
        return ranked_roots

    def _analyze_checked(
        self,
        node: _RolloutNode,
        work: ProxyWork,
        deadline: float,
        local_quota: ProxyWorkQuota,
        topology_cache: ProxyTopologyCache,
    ) -> tuple[
        _RolloutNode,
        tuple[_CheckedItemPlan, ...],
        ProxyWork,
        int,
        int,
        tuple[tuple[str, int], ...],
        bool,
    ]:
        plans: list[_CheckedItemPlan] = []
        current = work
        exceptions = 0
        preview_count = 0
        exposure_rows: list[tuple[str, int]] = []
        total_occurrences = len(node.proxy_state.remaining)
        audited_occurrences = 0
        option_occurrences = 0
        option_volume = 0.0
        zero_option_occurrences = 0
        audited_option_counts: list[int] = []
        for occurrence in sorted(node.proxy_state.remaining, key=lambda value: value.key):
            if (
                self._expired(deadline)
                or current.fit_tests >= local_quota.max_fit_tests
                or current.candidates >= local_quota.max_candidates
            ):
                break
            call_quota = replace(
                local_quota,
                max_fit_tests=min(
                    local_quota.max_fit_tests,
                    current.fit_tests + self.occurrence_fit_quantum,
                ),
                max_candidates=min(
                    local_quota.max_candidates,
                    current.candidates + self.occurrence_fit_quantum,
                ),
            )
            try:
                batch = self.proxy.preview_candidates(
                    node.proxy_state,
                    occurrence.key,
                    current,
                    call_quota,
                    node.metrics,
                    topology_cache,
                    exposure_order=self.exposure_order,
                )
            except Exception:
                exceptions += 1
                continue
            current = batch.work
            choices: list[_CheckedCandidateChoice] = []
            for transition in batch.transitions:
                preview_count += 1
                exposure_rows.append(
                    (
                        transition.candidate.support_source,
                        transition.candidate.orientation,
                    )
                )
                stable = self._candidate_key(transition.candidate)
                choices.append(
                    _CheckedCandidateChoice(
                        transition,
                        self._checked_local_cost(transition),
                        stable,
                    )
                )
            choices.sort(key=lambda value: (value.cost, value.stable_key))
            if self.rank_objective is RankObjective.CERTIFIED_CONTINUATION_SURVIVAL:
                audited_occurrences += 1
                audited_option_counts.append(len(choices))
                if choices:
                    option_occurrences += 1
                    option_volume += float(occurrence.item.volume)
                else:
                    zero_option_occurrences += 1
            if choices:
                regret = (
                    math.inf
                    if len(choices) == 1
                    else max(0.0, choices[1].cost - choices[0].cost)
                )
                plans.append(_CheckedItemPlan(occurrence, tuple(choices), regret))

        update_fields = dict(
            remaining_fit_count=len(plans),
            remaining_fit_volume=sum(plan.occurrence.item.volume for plan in plans),
            minimum_nonzero_options=min(
                (plan.feasible_count for plan in plans), default=0
            ),
        )
        if self.rank_objective is RankObjective.CERTIFIED_CONTINUATION_SURVIVAL:
            update_fields["continuation_audit"] = ContinuationAudit(
                total_occurrences=total_occurrences,
                audited_occurrences=audited_occurrences,
                option_occurrences=option_occurrences,
                option_volume=option_volume,
                zero_option_occurrences=zero_option_occurrences,
                minimum_options_all=min(audited_option_counts, default=0),
                complete=audited_occurrences == total_occurrences,
            )
        updated = replace(node, **update_fields)
        plans.sort(key=lambda plan: plan.occurrence.key)
        plans.sort(key=lambda plan: plan.occurrence.item.volume, reverse=True)
        plans.sort(key=lambda plan: plan.feasible_count)
        plans.sort(key=lambda plan: plan.regret, reverse=True)
        plans.sort(key=lambda plan: plan.feasible_count == 1, reverse=True)
        return (
            updated,
            tuple(plans),
            current,
            exceptions,
            preview_count,
            tuple(exposure_rows),
            preview_count == 0,
        )

    def _commit_checked_child(
        self,
        parent: _RolloutNode,
        choice: _CheckedCandidateChoice,
        occurrence: ProxyOccurrence,
        work: ProxyWork,
        topology_cache: ProxyTopologyCache,
    ) -> tuple[_RolloutNode | None, ProxyWork, bool]:
        if work.nodes >= self.proxy_quota.max_nodes:
            return None, work, False
        try:
            child_state, child_metrics = self.proxy.commit_transition(
                parent.proxy_state,
                choice.transition,
                topology_cache,
            )
            current = work.consume_node(self.proxy_quota)
            child = _RolloutNode(
                proxy_state=child_state,
                first_root=parent.first_root,
                root_key=parent.root_key,
                lineage_id=parent.lineage_id,
                depth=parent.depth + 1,
                placed_count=parent.placed_count + 1,
                placed_volume=parent.placed_volume + occurrence.item.volume,
                metrics=child_metrics,
                remaining_fit_count=0,
                remaining_fit_volume=0.0,
                minimum_nonzero_options=0,
                cumulative_backness=(
                    parent.cumulative_backness
                    + self._candidate_backness(parent.proxy_state, choice.candidate)
                ),
                stable_sequence_key=parent.stable_sequence_key
                + (choice.stable_key,),
            )
            return child, current, False
        except Exception:
            return None, work, True


__all__ = [
    "ContinuationAudit",
    "MemoizedStreamingRegretProxySelector",
    "RankObjective",
    "RegretProxySelector",
    "SelectionTrace",
]
