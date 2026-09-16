"""Fixed-work exact two-ply planner for visible-pool mode B experiments."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time
from typing import Sequence

from .catalog import CatalogWorkQuota, RootCatalog, RootRecord, StrictRootScanner
from .features import FutureFeatures, compute_future_features
from .mask import ExactMask
from .model import ItemSpec, PackingState, ValidatedRoot
from .settings import SearchSettings
from .state import state_fingerprint
from .transition import SimPlacement, SimState, apply_root


@dataclass(frozen=True)
class BSearchTrace:
    stage1_edges: int = 0
    admitted_items: int = 0
    admitted_roots: int = 0
    child_scans: int = 0
    child_exact_attempts: int = 0
    child_covered_occurrences: int = 0
    second_edges: int = 0
    deepest_proven_count: int = 0
    deadline_reached: bool = False
    branch_exceptions: int = 0


@dataclass(frozen=True)
class _Node:
    sim: SimState
    first_root: ValidatedRoot
    sequence: tuple[SimPlacement, ...]
    proven_volume: float
    features: FutureFeatures
    scarcity_urgency: float
    stable_sequence_key: tuple
    catalog: RootCatalog

    @property
    def proven_count(self) -> int:
        return len(self.sequence)


class FixedQuotaExactTwoPly:
    """Admit cheaply, then spend bounded exact work on at most two plies."""

    def __init__(
        self,
        scanner: StrictRootScanner,
        mask: ExactMask,
        settings: SearchSettings | None = None,
        *,
        item_choices: int = 6,
        roots_per_item: int = 2,
        child_branches: int = 8,
        second_parent_choices: int = 4,
        second_item_choices: int = 3,
        coverage_quota: CatalogWorkQuota | None = None,
        protection_materiality: float = 0.01,
        clock=None,
    ) -> None:
        if scanner is None or not callable(
            getattr(scanner, "scan_coverage_fixed", None)
        ):
            raise TypeError("scanner must expose scan_coverage_fixed")
        if mask is None:
            raise TypeError("an exact revalidation mask is required")
        self.scanner = scanner
        self.mask = mask
        self.settings = settings or SearchSettings()
        if isinstance(mask, ExactMask) and mask.profile_digest != self.settings.profile_digest():
            raise ValueError("exact mask profile does not match planner settings")
        self.item_choices = max(1, int(item_choices))
        self.roots_per_item = max(1, int(roots_per_item))
        self.child_branches = max(1, int(child_branches))
        self.second_parent_choices = max(1, int(second_parent_choices))
        self.second_item_choices = max(1, int(second_item_choices))
        self.coverage_quota = coverage_quota or CatalogWorkQuota()
        if isinstance(protection_materiality, bool):
            raise ValueError("protection_materiality must be finite and positive")
        try:
            materiality = float(protection_materiality)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                "protection_materiality must be finite and positive"
            ) from error
        if not math.isfinite(materiality) or materiality <= 0.0:
            raise ValueError("protection_materiality must be finite and positive")
        self.protection_materiality = materiality
        self.clock = clock or time.perf_counter
        self.last_trace = BSearchTrace()

    def choose_b(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        root_catalog: RootCatalog,
        deadline: float,
    ) -> ValidatedRoot | None:
        if not isinstance(state, PackingState):
            raise TypeError("state must be a PackingState")
        if not isinstance(root_catalog, RootCatalog):
            raise TypeError("root_catalog must be a RootCatalog")
        if not math.isfinite(float(deadline)):
            raise ValueError("deadline must be finite")
        ordered_pool = tuple(pool)
        if not ordered_pool or not root_catalog:
            self.last_trace = BSearchTrace()
            return None

        parent = SimState.from_current(state, ordered_pool)
        current_records = self._current_records(root_catalog, parent)
        current_catalog = RootCatalog(current_records, root_catalog.stats)
        incumbent: _Node | None = None
        stage1: list[_Node] = []
        stage1_edges = branch_exceptions = 0

        # Establish the first exact incumbent before spending any child-scan
        # work.  Subsequent roots retain the hard deadline guard.
        for record in current_records:
            if incumbent is not None and self._expired(deadline):
                break
            try:
                node = self._extend(
                    parent,
                    current_catalog,
                    record,
                    (),
                    None,
                    0.0,
                    0.0,
                    (),
                    deadline,
                    RootCatalog.empty(max(0, len(parent.pool) - 1)),
                )
            except Exception:
                branch_exceptions += 1
                continue
            stage1_edges += 1
            stage1.append(node)
            incumbent = self._prefer(incumbent, node)

        admitted_groups = self._admitted_groups(stage1)
        admitted = [node for group in admitted_groups for node in group]
        branches = [group[0] for group in admitted_groups]
        branches.extend(group[1] for group in admitted_groups[:2] if len(group) > 1)
        branches = self._ordered(branches)[: self.child_branches]

        scanned: list[_Node] = []
        child_scans = 0
        child_exact_attempts = 0
        child_covered_occurrences = 0
        for node in branches:
            if self._expired(deadline):
                break
            try:
                child_catalog = self.scanner.scan_coverage_fixed(
                    node.sim.packing,
                    node.sim.pool,
                    deadline=deadline,
                    quota=self.coverage_quota,
                    allow_deferred=False,
                    allow_rescue=False,
                )
                child_scans += 1
                child_exact_attempts += child_catalog.stats.exact_attempts
                child_covered_occurrences += child_catalog.stats.fixed_pools_covered
                rescored = replace(
                    node,
                    catalog=child_catalog,
                    features=self._with_catalog_features(node, child_catalog),
                )
            except Exception:
                branch_exceptions += 1
                continue
            scanned.append(rescored)
            incumbent = self._prefer(incumbent, rescored)

        second_edges = 0
        for node in self._ordered(scanned)[: self.second_parent_choices]:
            if self._expired(deadline):
                break
            candidates = self._second_candidates(node)
            for record in candidates[: self.second_item_choices]:
                if self._expired(deadline):
                    break
                try:
                    child = self._extend(
                        node.sim,
                        node.catalog,
                        record,
                        node.sequence,
                        node.first_root,
                        node.proven_volume,
                        node.scarcity_urgency,
                        node.stable_sequence_key,
                        deadline,
                        RootCatalog.empty(max(0, len(node.sim.pool) - 1)),
                    )
                except Exception:
                    branch_exceptions += 1
                    continue
                second_edges += 1
                incumbent = self._prefer(incumbent, child)

        deepest = 0 if incumbent is None else max(
            [node.proven_count for node in stage1]
            + [2 if second_edges else 0]
        )
        self.last_trace = BSearchTrace(
            stage1_edges=stage1_edges,
            admitted_items=len(admitted_groups),
            admitted_roots=len(admitted),
            child_scans=child_scans,
            child_exact_attempts=child_exact_attempts,
            child_covered_occurrences=child_covered_occurrences,
            second_edges=second_edges,
            deepest_proven_count=deepest,
            deadline_reached=self._expired(deadline),
            branch_exceptions=branch_exceptions,
        )
        return None if incumbent is None else incumbent.first_root

    def _with_catalog_features(
        self, node: _Node, catalog: RootCatalog
    ) -> FutureFeatures:
        future = compute_future_features(
            node.sim,
            catalog=catalog,
            settings=self.settings,
        )
        return replace(
            future,
            min_support_margin=node.features.min_support_margin,
            min_clearance_margin=node.features.min_clearance_margin,
        )

    def _extend(
        self,
        parent: SimState,
        parent_catalog: RootCatalog,
        record: RootRecord,
        sequence: tuple[SimPlacement, ...],
        first_root: ValidatedRoot | None,
        proven_volume: float,
        scarcity_urgency: float,
        stable_sequence_key: tuple,
        deadline: float,
        child_catalog: RootCatalog,
    ) -> _Node:
        pool_index = record.pool_index
        if pool_index < 0 or pool_index >= len(parent.pool):
            raise ValueError("root pool occurrence is stale")
        selected_item = parent.pool[pool_index]
        placement = apply_root(
            parent,
            record.root,
            self.settings,
            exact_revalidator=self.mask,
            deadline=deadline,
        )
        state_features = compute_future_features(
            placement.child,
            catalog=None,
            settings=self.settings,
        )
        safety = compute_future_features(
            parent,
            catalog=parent_catalog,
            selected_root=record.root,
            settings=self.settings,
        )
        features = replace(
            state_features,
            min_support_margin=safety.min_support_margin,
            min_clearance_margin=safety.min_clearance_margin,
        )
        root_count = max(1, len(parent_catalog.for_pool(pool_index)))
        urgency = 1.0 / (1.0 + root_count)
        step_key = (
            placement.original_pool_position,
            record.item_index,
            record.container_index,
            record.orientation,
            tuple(round(value, 7) for value in record.proposal.position),
            record.proposal.source,
        )
        return _Node(
            sim=placement.child,
            first_root=record.root if first_root is None else first_root,
            sequence=sequence + (placement,),
            proven_volume=proven_volume + selected_item.volume,
            features=features,
            scarcity_urgency=scarcity_urgency + urgency,
            stable_sequence_key=stable_sequence_key + (step_key,),
            catalog=child_catalog,
        )

    def _current_records(
        self, catalog: RootCatalog, sim: SimState
    ) -> tuple[RootRecord, ...]:
        profile = self.settings.profile_digest()
        expected: dict[int, str] = {}
        result: list[RootRecord] = []
        for record in sorted(catalog.records, key=lambda value: value.stable_key):
            index = record.pool_index
            if not 0 <= index < len(sim.pool):
                continue
            root = record.root
            if (
                not root.strict
                or root.rule_violations != 0
                or root.profile_digest != profile
                or root.proposal.item_index != sim.pool[index].index
            ):
                continue
            if index not in expected:
                expected[index] = state_fingerprint(
                    sim.packing, sim.pool, index, profile
                )
            if root.state_fingerprint == expected[index]:
                result.append(record)
        return tuple(result)

    def _admitted_groups(self, nodes: Sequence[_Node]) -> list[list[_Node]]:
        groups: dict[int, list[_Node]] = {}
        for node in nodes:
            groups.setdefault(node.sequence[-1].selected_pool_index, []).append(node)
        ranked = [self._ordered(group)[: self.roots_per_item] for group in groups.values()]
        ranked.sort(key=lambda group: group[0].sequence[-1].selected_pool_index)
        ranked.sort(key=lambda group: self._rank(group[0]), reverse=True)
        return ranked[: self.item_choices]

    def _second_candidates(self, node: _Node) -> list[RootRecord]:
        current = self._current_records(node.catalog, node.sim)
        per_pool: dict[int, RootRecord] = {}
        for record in current:
            per_pool.setdefault(record.pool_index, record)
        records = list(per_pool.values())
        records.sort(key=lambda record: record.stable_key)
        records.sort(
            key=lambda record: (
                node.sim.pool[record.pool_index].volume,
                record.root.support_ratio,
                record.root.min_clearance,
            ),
            reverse=True,
        )
        return records

    def _rank(self, node: _Node) -> tuple[float, ...]:
        feature = node.features
        protection_bucket = math.floor(
            (feature.protection_compatible_capacity + 1.0e-12)
            / self.protection_materiality
        )
        return (
            float(node.proven_count),
            float(node.proven_volume),
            feature.future_covered_items,
            feature.future_covered_volume,
            feature.root_robustness,
            node.scarcity_urgency,
            float(protection_bucket),
            feature.ingress_access,
            feature.largest_free_support,
            -feature.sliver_area,
            feature.protection_compatible_capacity,
            feature.compatible_support_capacity,
            feature.low_mass_cog_goodness,
            feature.min_support_margin,
            feature.min_clearance_margin,
            feature.low_stack,
        )

    def _ordered(self, nodes: Sequence[_Node]) -> list[_Node]:
        ordered = sorted(nodes, key=lambda node: node.stable_sequence_key)
        ordered.sort(key=self._rank, reverse=True)
        return ordered

    def _prefer(self, current: _Node | None, candidate: _Node) -> _Node:
        if current is None:
            return candidate
        return self._ordered((current, candidate))[0]

    def _expired(self, deadline: float) -> bool:
        return float(self.clock()) >= float(deadline)


__all__ = ["BSearchTrace", "FixedQuotaExactTwoPly"]
