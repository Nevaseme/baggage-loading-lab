"""Authoritative, fail-closed exact validation mask for placement proposals.

Proposal generators may be approximate.  This module deliberately is not: a
``ValidatedRoot`` is issued only after the proposal, current ordered pool,
container ordinal/metadata, geometry, support, protection, ingress path and
depth observation have all been bound and checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Sequence

import numpy as np

from .geometry import (
    box_inside_planes,
    depth_map_path_clear,
    effective_transport_lift,
    oriented_dimensions,
    support_metrics,
    transport_path_clear,
)
from .model import (
    AABB,
    ContainerState,
    ItemSpec,
    PackingState,
    PlacementProposal,
    Rect,
    ValidatedRoot,
    _issue_validated_root,
)
from .settings import SearchSettings
from .state import state_fingerprint


class RejectReason(str, Enum):
    DEADLINE = "deadline"
    EXCEPTION = "exception"
    INVALID_STATE = "invalid_state"
    INVALID_POOL = "invalid_pool"
    ITEM_BINDING = "item_binding"
    CONTAINER_ORDINAL = "container_ordinal"
    CONTAINER_ELIGIBILITY = "container_eligibility"
    COLLISION = "collision_or_clearance"
    INCLUSION = "plane_inclusion"
    SUPPORT_RATIO = "support_ratio"
    CENTER_SUPPORT = "center_support"
    PROTECTION = "protection"
    TRANSPORT = "transport"
    DEPTH_MAP = "depth_map"


@dataclass(frozen=True)
class ValidationTrace:
    accepted: bool
    root: ValidatedRoot | None
    first_reason: RejectReason | None
    failed_predicates: tuple[RejectReason, ...] = ()
    support_ratio: float = 0.0
    required_support: float = 0.0
    min_clearance: float = 0.0
    effective_lift: float = 0.0
    detail: str = ""


class _Rejected(Exception):
    def __init__(self, reason: RejectReason, *, detail: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.detail = detail


class ExactMask:
    """Validate raw proposals and mint state-bound strict receipts."""

    def __init__(self, settings: SearchSettings | None = None) -> None:
        self.settings = settings or SearchSettings()
        self.profile_digest = self.settings.profile_digest()

    def validate(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        proposal: PlacementProposal,
        *,
        deadline: float | None = None,
    ) -> ValidatedRoot | None:
        """Return a freshly issued strict root, or ``None`` on any failure."""

        return self.diagnose(state, pool, proposal, deadline=deadline).root

    def revalidate(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        proposal: PlacementProposal,
        settings: SearchSettings,
    ) -> ValidatedRoot | None:
        """Agent callback: mint fresh evidence under the identical profile.

        The formatter intentionally does not accept a boolean.  It calls this
        method immediately before output and compares every receipt field with
        the earlier root.
        """

        if not isinstance(settings, SearchSettings):
            return None
        if settings.profile_digest() != self.profile_digest:
            return None
        return self.validate(state, pool, proposal)

    def diagnose(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        proposal: PlacementProposal,
        *,
        deadline: float | None = None,
    ) -> ValidationTrace:
        """Return a stable first-failure trace and never leak validator errors."""

        metrics = {
            "support_ratio": 0.0,
            "required_support": 0.0,
            "min_clearance": 0.0,
            "effective_lift": 0.0,
        }
        try:
            root = self._validate_exact(state, pool, proposal, deadline, metrics)
            return ValidationTrace(
                accepted=True,
                root=root,
                first_reason=None,
                failed_predicates=(),
                **metrics,
            )
        except _Rejected as rejection:
            return ValidationTrace(
                accepted=False,
                root=None,
                first_reason=rejection.reason,
                failed_predicates=(rejection.reason,),
                detail=rejection.detail,
                **metrics,
            )
        except Exception as error:  # fail closed; diagnostics remain printable
            reason = RejectReason.EXCEPTION
            return ValidationTrace(
                accepted=False,
                root=None,
                first_reason=reason,
                failed_predicates=(reason,),
                detail=f"{type(error).__name__}: {error}",
                **metrics,
            )

    @staticmethod
    def _check_deadline(deadline: float | None) -> None:
        if deadline is not None and time.perf_counter() >= float(deadline):
            raise _Rejected(RejectReason.DEADLINE)

    def _validate_exact(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        proposal: PlacementProposal,
        deadline: float | None,
        metrics: dict[str, float],
    ) -> ValidatedRoot:
        self._check_deadline(deadline)
        if not isinstance(state, PackingState) or not state.containers:
            raise _Rejected(RejectReason.INVALID_STATE)
        if not isinstance(proposal, PlacementProposal):
            raise _Rejected(RejectReason.ITEM_BINDING, detail="proposal type")
        if not isinstance(pool, Sequence) or isinstance(pool, (str, bytes)):
            raise _Rejected(RejectReason.INVALID_POOL)
        if proposal.pool_index >= len(pool):
            raise _Rejected(RejectReason.ITEM_BINDING, detail="pool ordinal")
        raw_item = pool[proposal.pool_index]
        if isinstance(raw_item, dict):
            try:
                item = ItemSpec.from_dict(raw_item)
            except (KeyError, TypeError, ValueError) as error:
                raise _Rejected(RejectReason.INVALID_POOL, detail=str(error)) from error
        elif isinstance(raw_item, ItemSpec):
            item = raw_item
        else:
            raise _Rejected(RejectReason.INVALID_POOL, detail="unsupported pool entry")
        if item.index != proposal.item_index:
            raise _Rejected(RejectReason.ITEM_BINDING, detail="item metadata index")

        ordinal_matches = [
            container for container in state.containers
            if container.ordinal == proposal.container_index
        ]
        if len(ordinal_matches) != 1:
            raise _Rejected(RejectReason.CONTAINER_ORDINAL)
        container = ordinal_matches[0]
        if proposal.container_index >= len(state.containers):
            raise _Rejected(RejectReason.CONTAINER_ORDINAL, detail="ordinal outside list")
        if state.containers[proposal.container_index] is not container:
            raise _Rejected(RejectReason.CONTAINER_ORDINAL, detail="non-canonical ordinal")
        self._check_container_eligibility(state, container, item)
        self._check_deadline(deadline)

        dimensions = np.asarray(
            oriented_dimensions(item.dimensions, proposal.orientation), dtype=np.float64
        )
        box = AABB.from_center_half(proposal.position, dimensions * 0.5)
        obstacles = [placed.box for placed in container.placed] + list(container.static_obstacles)
        floor_z = container.thickness + container.buffer
        # The shelf body is centred at H/2 + thickness/2, so its usable top is
        # H/2 + thickness.  Treating H/2 as the top both mis-models contact and
        # overlaps the physical shelf obstacle.
        shelf_top = container.height / 2.0 + container.thickness + container.buffer
        if any(self._collides_with_clearance(box, obstacle) for obstacle in obstacles):
            raise _Rejected(RejectReason.COLLISION)
        if not box_inside_planes(
            box.center,
            box.half,
            container.points,
            container.normals,
            self.settings.inclusion_margin,
        ):
            raise _Rejected(RejectReason.INCLUSION)
        self._check_deadline(deadline)

        support_layers = self._support_layers(container, box, floor_z, shelf_top)
        measured_layers = [
            (
                *support_metrics(
                    box.footprint, rectangles, self.settings.center_support_margin
                ),
                supporting_items,
            )
            for _height, rectangles, supporting_items in support_layers
        ]
        support_ratio = max((entry[0] for entry in measured_layers), default=0.0)
        required_support = (
            self.settings.soft_support_ratio if item.is_soft else self.settings.rigid_support_ratio
        )
        metrics["support_ratio"] = float(support_ratio)
        metrics["required_support"] = float(required_support)
        if support_ratio + 1e-9 < required_support:
            raise _Rejected(RejectReason.SUPPORT_RATIO)
        valid_layers = [
            entry for entry in measured_layers
            if entry[0] + 1e-9 >= required_support and entry[1]
        ]
        if not valid_layers:
            raise _Rejected(RejectReason.CENTER_SUPPORT)
        _accepted_ratio, _center_supported, supporting_items = max(
            valid_layers, key=lambda entry: entry[0]
        )

        column_items = [
            placed.item
            for placed in container.placed
            if placed.box.maximum[2] <= box.minimum[2] + self.settings.support_height_tolerance
            and box.footprint.intersection(placed.box.footprint) is not None
        ]
        if self._protection_violations(item, column_items or supporting_items):
            raise _Rejected(RejectReason.PROTECTION)

        lift = effective_transport_lift(
            bottom_z=float(box.minimum[2]),
            top_z=float(box.maximum[2]),
            resting_surfaces=(floor_z, shelf_top),
            ceiling_surfaces=(
                container.height / 2.0 + container.buffer,
                container.height + container.buffer - container.thickness,
            ),
            requested_lift=0.08,
            ceiling_margin=self.settings.path_clearance,
        )
        metrics["effective_lift"] = float(lift)
        half = box.half
        start_x_min = (
            -container.length / 2.0
            + container.thickness
            + container.cut_x
            + half[0]
            + 0.01
        )
        start_x_max = container.length / 2.0 - container.thickness - half[0] - 0.01
        if start_x_min > start_x_max:
            raise _Rejected(RejectReason.TRANSPORT, detail="item cannot enter door aperture")
        start_x = min(max(float(box.center[0]), start_x_min), start_x_max)
        if not transport_path_clear(
            box,
            obstacles,
            door_y=-container.width / 2.0 + half[1],
            start_x=start_x,
            lift=lift,
            clearance=self.settings.path_clearance,
        ):
            raise _Rejected(RejectReason.TRANSPORT)
        self._check_deadline(deadline)
        if container.depth_map is not None and not depth_map_path_clear(
            box,
            [placed.box for placed in container.placed],
            container.depth_map,
            container_length=container.length,
            container_width=container.width,
            container_height=container.height,
            container_center_z=container.center[2],
            start_x=start_x,
            lift=lift,
            clearance=self.settings.path_clearance,
            depth_tolerance=self.settings.depth_tolerance,
            minimum_blocking_pixels=self.settings.depth_min_blocking_pixels,
        ):
            raise _Rejected(RejectReason.DEPTH_MAP)

        min_clearance = self._minimum_horizontal_clearance(box, obstacles)
        metrics["min_clearance"] = min_clearance
        fingerprint = state_fingerprint(
            state,
            pool,
            proposal.pool_index,
            self.profile_digest,
        )
        self._check_deadline(deadline)
        return _issue_validated_root(
            proposal=proposal,
            box=box,
            state_fingerprint=fingerprint,
            item=item,
            profile_digest=self.profile_digest,
            pool=list(pool),
            selected_pool_index=proposal.pool_index,
            support_ratio=support_ratio,
            min_clearance=min_clearance,
            source=proposal.source,
            rule_violations=0,
            strict=True,
        )

    @staticmethod
    def _check_container_eligibility(
        state: PackingState, container: ContainerState, item: ItemSpec
    ) -> None:
        priority_containers = [entry for entry in state.containers if entry.is_prioritized]
        if item.is_prioritized and priority_containers and not container.is_prioritized:
            raise _Rejected(RejectReason.CONTAINER_ELIGIBILITY)

    def _collides_with_clearance(self, candidate: AABB, obstacle: AABB) -> bool:
        if (
            candidate.maximum[2] <= obstacle.minimum[2] + 1e-9
            or candidate.minimum[2] >= obstacle.maximum[2] - 1e-9
        ):
            return False
        clearance = self.settings.path_clearance
        separated_x = (
            candidate.maximum[0] + clearance <= obstacle.minimum[0]
            or obstacle.maximum[0] + clearance <= candidate.minimum[0]
        )
        separated_y = (
            candidate.maximum[1] + clearance <= obstacle.minimum[1]
            or obstacle.maximum[1] + clearance <= candidate.minimum[1]
        )
        return not (separated_x or separated_y)

    def _support_layers(
        self,
        container: ContainerState,
        box: AABB,
        floor_z: float,
        shelf_top: float,
    ) -> list[tuple[float, list[Rect], list[ItemSpec]]]:
        # Keep non-coplanar surfaces separate: unioning two nearby but unequal
        # tops can manufacture a support platform that does not physically
        # exist.  One millimetre admits settling noise without bridging steps.
        raw: list[tuple[float, Rect, ItemSpec | None]] = []
        bottom = float(box.minimum[2])
        tolerance = self.settings.support_height_tolerance
        if abs(bottom - floor_z) <= tolerance:
            raw.append(
                (floor_z, Rect(
                    -container.length / 2.0 + container.thickness,
                    container.length / 2.0 - container.thickness,
                    -container.width / 2.0 + container.thickness,
                    container.width / 2.0 - container.thickness,
                ), None)
            )
        if 0.0 <= bottom - shelf_top <= self.settings.shelf_drop_gap + tolerance:
            if container.shelf:
                raw.append(
                    (shelf_top, Rect(
                        -container.length / 2.0 + container.thickness / 2.0,
                        container.length / 2.0 - container.thickness / 2.0,
                        container.thickness,
                        container.width / 2.0 - container.thickness,
                    ), None)
                )
            raw.append(
                (shelf_top, Rect(
                    -container.length / 2.0 + container.thickness,
                    -container.length / 2.0 + container.thickness + container.cut_x,
                    -container.width / 2.0 + container.thickness,
                    container.width / 2.0 - container.thickness,
                ), None)
            )
        for placed in container.placed:
            if not placed.box.axis_aligned:
                continue
            if abs(bottom - float(placed.box.maximum[2])) <= tolerance:
                raw.append(
                    (
                        float(placed.box.maximum[2]),
                        placed.box.footprint,
                        placed.item
                        if box.footprint.intersection(placed.box.footprint) is not None
                        else None,
                    )
                )

        layers: list[tuple[float, list[Rect], list[ItemSpec]]] = []
        for height, rectangle, supporting_item in sorted(raw, key=lambda entry: entry[0]):
            target = next(
                (layer for layer in layers if abs(layer[0] - height) <= 0.001),
                None,
            )
            if target is None:
                target = (height, [], [])
                layers.append(target)
            target[1].append(rectangle)
            if supporting_item is not None:
                target[2].append(supporting_item)
        return layers

    @staticmethod
    def _protection_violations(item: ItemSpec, below: Sequence[ItemSpec]) -> int:
        violations = 0
        for lower in below:
            if lower.is_prioritized and not item.is_prioritized:
                violations += 1
            if lower.is_soft and not item.is_soft:
                violations += 1
        return violations

    @staticmethod
    def _minimum_horizontal_clearance(box: AABB, obstacles: Sequence[AABB]) -> float:
        distances: list[float] = []
        for obstacle in obstacles:
            if box.maximum[2] <= obstacle.minimum[2] or obstacle.maximum[2] <= box.minimum[2]:
                continue
            dx = max(
                obstacle.minimum[0] - box.maximum[0],
                box.minimum[0] - obstacle.maximum[0],
                0.0,
            )
            dy = max(
                obstacle.minimum[1] - box.maximum[1],
                box.minimum[1] - obstacle.maximum[1],
                0.0,
            )
            distances.append(math.hypot(dx, dy))
        return min(distances, default=1.0)


__all__ = ["ExactMask", "RejectReason", "ValidationTrace"]
