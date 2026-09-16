"""Deterministic B/C beam search over strict exact-root catalogs."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time
from typing import Sequence

from .catalog import RootCatalog, RootRecord, StrictRootScanner
from .features import FutureFeatures, compute_future_features
from .mask import ExactMask
from .model import ItemSpec, PackingState, ValidatedRoot
from .settings import SearchSettings
from .state import state_fingerprint
from .transition import SimPlacement, SimState, apply_root


@dataclass(frozen=True)
class BeamNode:
    """One immutable, exactly proven analytical search node."""

    sim: SimState
    first_root: ValidatedRoot
    sequence: tuple[SimPlacement, ...]
    proven_count: int
    proven_volume: float
    features: FutureFeatures
    scarcity_urgency: float
    stable_sequence_key: tuple
    catalog: RootCatalog

    def __post_init__(self) -> None:
        if not isinstance(self.sim, SimState):
            raise TypeError("sim must be a SimState")
        if not isinstance(self.first_root, ValidatedRoot):
            raise TypeError("first_root must be a ValidatedRoot")
        if type(self.sequence) is not tuple or not self.sequence:
            raise ValueError("sequence must be a non-empty tuple")
        if type(self.proven_count) is not int or self.proven_count != len(self.sequence):
            raise ValueError("proven_count must equal the exact sequence length")
        if not math.isfinite(float(self.proven_volume)) or self.proven_volume < 0.0:
            raise ValueError("proven_volume must be finite and non-negative")
        if not math.isfinite(float(self.scarcity_urgency)) or self.scarcity_urgency < 0.0:
            raise ValueError("scarcity_urgency must be finite and non-negative")
        if type(self.stable_sequence_key) is not tuple:
            raise ValueError("stable_sequence_key must be a tuple")
        if not isinstance(self.catalog, RootCatalog):
            raise TypeError("catalog must be a RootCatalog")


class FutureSupportIngressBeam:
    """Short deterministic beam for visible-pool modes B and C.

    Raw proposals never enter this class.  Every edge starts with a catalog
    ``ValidatedRoot`` and is applied only after fresh exact revalidation by
    :func:`apply_root`.
    """

    def __init__(
        self,
        scanner: StrictRootScanner,
        mask: ExactMask,
        settings: SearchSettings | None = None,
        *,
        beam_width: int = 20,
        max_depth: int = 4,
        item_choices: int = 6,
        roots_per_item: int = 2,
        clock=None,
    ) -> None:
        if scanner is None or not callable(getattr(scanner, "scan", None)):
            raise TypeError("scanner must expose scan(state, pool, ...)")
        if mask is None:
            raise TypeError("an exact revalidation mask is required")
        self.scanner = scanner
        self.mask = mask
        self.settings = settings or SearchSettings()
        if isinstance(mask, ExactMask) and mask.profile_digest != self.settings.profile_digest():
            raise ValueError("exact mask profile does not match beam settings")
        self.beam_width = max(1, int(beam_width))
        self.max_depth = max(1, int(max_depth))
        self.item_choices = max(1, int(item_choices))
        self.roots_per_item = max(1, int(roots_per_item))
        self.clock = clock or time.perf_counter

    def choose_b(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        root_catalog: RootCatalog,
        deadline: float,
    ) -> ValidatedRoot | None:
        """Return the original depth-zero root of the best proven B branch."""

        parent = self._inputs(state, pool, root_catalog, deadline)
        if parent is None:
            return None
        depth_limit = min(self.max_depth, len(parent.pool))
        incumbent: BeamNode | None = None
        evaluated = self._evaluate_catalog(
            parent,
            root_catalog,
            (),
            None,
            0.0,
            0.0,
            (),
            deadline,
            scan_child=True,
        )
        for node in evaluated:
            incumbent = self._prefer(incumbent, node)
        frontier = self._prune(self._admit(evaluated))

        for _depth in range(1, depth_limit):
            if not frontier or self._expired(deadline):
                break
            next_frontier: list[BeamNode] = []
            stop = False
            for parent_node in frontier:
                if self._expired(deadline):
                    stop = True
                    break
                if not parent_node.sim.pool or not parent_node.catalog:
                    continue
                evaluated = self._evaluate_catalog(
                    parent_node.sim,
                    parent_node.catalog,
                    parent_node.sequence,
                    parent_node.first_root,
                    parent_node.proven_volume,
                    parent_node.scarcity_urgency,
                    parent_node.stable_sequence_key,
                    deadline,
                    scan_child=True,
                )
                for node in evaluated:
                    incumbent = self._prefer(incumbent, node)
                next_frontier.extend(self._admit(evaluated))
                if self._expired(deadline):
                    stop = True
                    break
            if stop and not next_frontier:
                break
            frontier = self._prune(next_frontier)
        return None if incumbent is None else incumbent.first_root

    def choose_c(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        root_catalog: RootCatalog,
        deadline: float,
    ) -> ValidatedRoot | None:
        """Rank depth-zero exact roots without scanning any continuation."""

        parent = self._inputs(state, pool, root_catalog, deadline)
        if parent is None:
            return None
        incumbent: BeamNode | None = None
        # Mode C has one visible occurrence.  Evaluate the complete strict
        # catalog rather than introducing a B-mode per-item branching cap.
        for record in self._current_records(root_catalog, parent):
            if self._expired(deadline):
                break
            node = self._extend(
                parent,
                root_catalog,
                record,
                (),
                None,
                0.0,
                0.0,
                (),
                deadline,
                scan_child=False,
            )
            if node is not None:
                incumbent = self._prefer(incumbent, node)
        return None if incumbent is None else incumbent.first_root

    def _inputs(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        catalog: RootCatalog,
        deadline: float,
    ) -> SimState | None:
        if not isinstance(state, PackingState):
            raise TypeError("state must be a PackingState")
        if not isinstance(catalog, RootCatalog):
            raise TypeError("root_catalog must be a RootCatalog")
        if not math.isfinite(float(deadline)):
            raise ValueError("deadline must be finite")
        ordered = tuple(pool)
        if not ordered or not catalog:
            return None
        return SimState.from_current(state, ordered)

    def _current_records(self, catalog: RootCatalog, sim: SimState) -> tuple[RootRecord, ...]:
        """Cheaply discard stale records before they consume evaluation time.

        This is only an admission guard.  Every surviving edge still goes
        through ``apply_root`` and a fresh exact-mask receipt comparison.
        """

        profile_digest = self.settings.profile_digest()
        expected_fingerprints: dict[int, str] = {}
        current: list[RootRecord] = []
        for record in sorted(catalog.records, key=lambda value: value.stable_key):
            pool_index = record.pool_index
            if pool_index < 0 or pool_index >= len(sim.pool):
                continue
            root = record.root
            if (
                not root.strict
                or root.rule_violations != 0
                or root.profile_digest != profile_digest
                or record.item_index != sim.pool[pool_index].index
            ):
                continue
            expected = expected_fingerprints.get(pool_index)
            if expected is None:
                expected = state_fingerprint(
                    sim.packing,
                    sim.pool,
                    pool_index,
                    profile_digest,
                )
                expected_fingerprints[pool_index] = expected
            if root.state_fingerprint == expected:
                current.append(record)
        return tuple(current)

    def _evaluate_catalog(
        self,
        parent: SimState,
        parent_catalog: RootCatalog,
        sequence: tuple[SimPlacement, ...],
        first_root: ValidatedRoot | None,
        proven_volume: float,
        scarcity_urgency: float,
        stable_sequence_key: tuple,
        deadline: float,
        *,
        scan_child: bool,
    ) -> list[BeamNode]:
        nodes: list[BeamNode] = []
        current_records = self._current_records(parent_catalog, parent)
        current_catalog = RootCatalog(current_records, parent_catalog.stats)
        for record in current_records:
            if self._expired(deadline):
                break
            node = self._extend(
                parent,
                current_catalog,
                record,
                sequence,
                first_root,
                proven_volume,
                scarcity_urgency,
                stable_sequence_key,
                deadline,
                scan_child=scan_child,
            )
            if node is not None:
                nodes.append(node)
        return nodes

    def _admit(self, nodes: Sequence[BeamNode]) -> list[BeamNode]:
        """Apply item/root branching caps only after exact one-edge ranking."""

        grouped: dict[int, list[BeamNode]] = {}
        for node in nodes:
            grouped.setdefault(node.sequence[-1].selected_pool_index, []).append(node)

        ranked_groups: list[tuple[int, list[BeamNode]]] = []
        for pool_index, group in grouped.items():
            ranked_groups.append(
                (pool_index, self._ordered(group)[: self.roots_per_item])
            )
        ranked_groups.sort(key=lambda entry: entry[0])
        ranked_groups.sort(key=lambda entry: self._rank(entry[1][0]), reverse=True)

        admitted: list[BeamNode] = []
        for _pool_index, group in ranked_groups[: self.item_choices]:
            admitted.extend(group)
        return admitted

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
        *,
        scan_child: bool,
    ) -> BeamNode | None:
        try:
            pool_index = record.pool_index
            if pool_index < 0 or pool_index >= len(parent.pool):
                return None
            selected_item = parent.pool[pool_index]
            placement = apply_root(
                parent,
                record.root,
                self.settings,
                exact_revalidator=self.mask,
                deadline=deadline,
            )
            child_catalog = RootCatalog.empty(len(placement.child.pool))
            if scan_child and placement.child.pool:
                try:
                    child_catalog = self.scanner.scan(
                        placement.child.packing,
                        placement.child.pool,
                        deadline=deadline,
                        breadth_rescue=False,
                        allow_deferred=False,
                        allow_rescue=False,
                    )
                    child_catalog = RootCatalog(
                        tuple(
                            child_record
                            for child_record in child_catalog.records
                            if child_record.pass_name == "normal"
                        ),
                        child_catalog.stats,
                    )
                except Exception:
                    child_catalog = RootCatalog.empty(len(placement.child.pool))

            child_features = compute_future_features(
                placement.child,
                catalog=child_catalog if scan_child else None,
                settings=self.settings,
            )
            safety = compute_future_features(
                parent,
                catalog=parent_catalog,
                selected_root=record.root,
                settings=self.settings,
            )
            features = replace(
                child_features,
                min_support_margin=safety.min_support_margin,
                min_clearance_margin=safety.min_clearance_margin,
            )
            root_count = len(parent_catalog.for_pool(pool_index))
            urgency = 1.0 / (1.0 + root_count)
            step_key = (
                placement.original_pool_position,
                record.item_index,
                record.container_index,
                record.orientation,
                tuple(round(value, 7) for value in record.proposal.position),
                record.proposal.source,
            )
            next_sequence = sequence + (placement,)
            return BeamNode(
                sim=placement.child,
                first_root=record.root if first_root is None else first_root,
                sequence=next_sequence,
                proven_count=len(next_sequence),
                proven_volume=proven_volume + selected_item.volume,
                features=features,
                scarcity_urgency=scarcity_urgency + urgency,
                stable_sequence_key=stable_sequence_key + (step_key,),
                catalog=child_catalog,
            )
        except Exception:
            return None

    def _rank(self, node: BeamNode) -> tuple[float, ...]:
        feature = node.features
        return (
            float(node.proven_count),
            float(node.proven_volume),
            feature.future_covered_items,
            feature.future_covered_volume,
            feature.root_robustness,
            node.scarcity_urgency,
            feature.compatible_support_capacity,
            feature.protection_compatible_capacity,
            feature.ingress_access,
            feature.largest_free_support,
            -feature.sliver_area,
            feature.low_mass_cog_goodness,
            feature.min_support_margin,
            feature.min_clearance_margin,
            feature.low_stack,
        )

    def _prune(self, nodes: Sequence[BeamNode]) -> list[BeamNode]:
        return self._ordered(nodes)[: self.beam_width]

    def _ordered(self, nodes: Sequence[BeamNode]) -> list[BeamNode]:
        # First establish the ascending deterministic tie order, then rely on
        # Python's stable sort for descending lexicographic quality.
        ordered = sorted(nodes, key=lambda node: node.stable_sequence_key)
        ordered.sort(key=self._rank, reverse=True)
        return ordered

    def _prefer(self, current: BeamNode | None, candidate: BeamNode) -> BeamNode:
        if current is None:
            return candidate
        return self._prune((current, candidate))[0]

    def _expired(self, deadline: float) -> bool:
        return float(self.clock()) >= float(deadline)


__all__ = ["BeamNode", "FutureSupportIngressBeam"]
