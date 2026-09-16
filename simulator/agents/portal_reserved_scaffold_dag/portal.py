"""Official-semantics-inspired Y-then-X portal conflicts.

Portal edges are planning dependencies only.  They identify a future sweep
that should be executed before a placement that would obstruct that sweep; the
Task 3 authorizer repeats the authoritative current-state swept check before an
action can be returned.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


_EPS = 1.0e-9
_TRANSPORT_MARGIN = 0.015


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _container_offset_x(container: Mapping[str, Any]) -> float:
    center = container.get("center", (0.0, 0.0, 0.0))
    if isinstance(center, Sequence) and not isinstance(center, (str, bytes)) and center:
        return _float(center[0])
    return 0.0


def _container_floor(container: Mapping[str, Any]) -> float:
    normals = container.get("n_vecs", ())
    points = container.get("points", ())
    try:
        for normal, point in zip(normals, points):
            if len(normal) >= 3 and len(point) >= 3:
                if _float(normal[2]) < -0.9 and abs(_float(normal[0])) < 0.1 and abs(_float(normal[1])) < 0.1:
                    return _float(point[2], _float(container.get("thickness"), 0.04))
    except (TypeError, ValueError):
        pass
    return _float(container.get("floor", container.get("thickness", 0.04)), 0.04)


def _dimensions(value: Any) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        if "dimensions" in value:
            return _dimensions(value["dimensions"])
        return (
            max(0.0, _float(value.get("length"))),
            max(0.0, _float(value.get("width"))),
            max(0.0, _float(value.get("height"))),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 3:
        return tuple(max(0.0, _float(component)) for component in value[:3])
    return (0.0, 0.0, 0.0)


def _center(value: Any) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        value = value.get("position", value.get("place_pos", value.get("pos", (0.0, 0.0, 0.0))))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 3:
        return tuple(_float(component) for component in value[:3])
    return (0.0, 0.0, 0.0)


def _placement_field(placement: Any, *names: str, default: Any = None) -> Any:
    if isinstance(placement, Mapping):
        for name in names:
            if name in placement:
                return placement[name]
    for name in names:
        if hasattr(placement, name):
            return getattr(placement, name)
    return default


def _placement_id(placement: Any) -> Any:
    return _placement_field(placement, "item_index", "item_idx", "index", default=None)


def _placement_container(placement: Any) -> int:
    value = _placement_field(placement, "container_idx", "container_index", "container_ordinal", default=0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _box(center: Sequence[float], dimensions: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    half = tuple(0.5 * max(0.0, _float(value)) for value in dimensions[:3])
    point = tuple(_float(value) for value in center[:3])
    return (
        point[0] - half[0], point[0] + half[0],
        point[1] - half[1], point[1] + half[1],
        point[2] - half[2], point[2] + half[2],
    )


def _overlap(first: Sequence[float], second: Sequence[float], margin: float = 0.0) -> bool:
    return not (
        first[1] + margin <= second[0] + _EPS
        or second[1] + margin <= first[0] + _EPS
        or first[3] + margin <= second[2] + _EPS
        or second[3] + margin <= first[2] + _EPS
        or first[5] + margin <= second[4] + _EPS
        or second[5] + margin <= first[4] + _EPS
    )


def official_portal_start_x(container: Mapping[str, Any], target_x: float, item_length: float) -> float:
    """Return the official clamped insertion X used by Y-then-X motion."""
    length = _float(container.get("length"), 0.0)
    thickness = _float(container.get("thickness"), 0.04)
    cut_x = _float(container.get("cut_x"), 0.0)
    half_x = max(0.0, _float(item_length)) * 0.5
    x_min = -length * 0.5 + thickness + cut_x + half_x + 0.01
    x_max = length * 0.5 - thickness - half_x - 0.01
    # Keep the expression as min(max(target, x_min), x_max), including the
    # inverted-interval case reviewed in Task 3.
    return min(max(_float(target_x), x_min), x_max)


def _effective_lift(container: Mapping[str, Any], center: Sequence[float], dimensions: Sequence[float]) -> float:
    floor = _container_floor(container)
    half_z = max(0.0, _float(dimensions[2])) * 0.5
    bottom = _float(center[2]) - half_z
    lift = 0.0 if 0.0 <= bottom - floor <= 0.05 else 0.08
    top = _float(center[2]) + half_z
    thickness = _float(container.get("thickness"), 0.04)
    height = _float(container.get("height"), 0.0)
    for ceiling in (floor + height * 0.5, floor + height - thickness):
        clearance = ceiling - top
        if 0.0 <= clearance < lift + 0.018:
            lift = max(0.0, clearance - 0.018 - 0.0005)
            break
    return lift


def official_y_then_x_sweep(
    container: Mapping[str, Any],
    center: Sequence[float],
    dimensions: Sequence[float],
    *,
    margin: float = _TRANSPORT_MARGIN,
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    """Return conservative AABBs for the official Y then X swept segments."""
    target = tuple(_float(value) for value in center[:3])
    dims = tuple(max(0.0, _float(value)) for value in dimensions[:3])
    half = tuple(value * 0.5 for value in dims)
    width = _float(container.get("width"), 0.0)
    path_center_z = target[2] + _effective_lift(container, target, dims)
    path_box = (path_center_z - half[2], path_center_z + half[2])
    start_x = official_portal_start_x(container, target[0], dims[0])
    y_front = -width * 0.5
    segment_y = (
        start_x - half[0] - margin,
        start_x + half[0] + margin,
        min(y_front, target[1]) - half[1] - margin,
        max(y_front, target[1]) + half[1] + margin,
        path_box[0] - margin,
        path_box[1] + margin,
    )
    segment_x = (
        min(start_x, target[0]) - half[0] - margin,
        max(start_x, target[0]) + half[0] + margin,
        target[1] - half[1] - margin,
        target[1] + half[1] + margin,
        path_box[0] - margin,
        path_box[1] + margin,
    )
    return segment_y, segment_x


def swept_conflict(
    container: Mapping[str, Any],
    blocker_center: Sequence[float],
    blocker_dimensions: Sequence[float],
    future_center: Sequence[float],
    future_dimensions: Sequence[float],
    *,
    margin: float = _TRANSPORT_MARGIN,
) -> bool:
    """Whether a settled blocker intersects a future official sweep."""
    blocker = _box(blocker_center, blocker_dimensions)
    return any(_overlap(segment, blocker, margin=0.0) for segment in official_y_then_x_sweep(container, future_center, future_dimensions, margin=margin))


@dataclass(frozen=True)
class PortalEdge:
    """Directed future-before-blocker dependency."""

    before: Any
    after: Any
    container_idx: int = 0
    reason: str = "future_sweep"
    sweep_axis: str = "Y_then_X"
    blocked_width: float = 0.0
    blocked_depth: float = 0.0
    required: bool = True

    @property
    def source(self) -> Any:
        return self.before

    @property
    def target(self) -> Any:
        return self.after

    @property
    def predecessor(self) -> Any:
        return self.before

    @property
    def successor(self) -> Any:
        return self.after

    def as_dict(self) -> dict[str, Any]:
        return {
            "before": self.before,
            "after": self.after,
            "container_idx": self.container_idx,
            "reason": self.reason,
            "sweep_axis": self.sweep_axis,
            "blocked_width": self.blocked_width,
            "blocked_depth": self.blocked_depth,
            "required": self.required,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


def build_portal_edges(
    placements: Sequence[Any],
    containers: Sequence[Mapping[str, Any]],
) -> list[PortalEdge]:
    """Construct deterministic precedence edges from official swept conflicts.

    If placement ``A`` intersects the future sweep of ``B``, the edge is
    ``B -> A``: the deeper/wider future intent must be handled before the
    entrance-side blocker.
    """
    normalized: list[tuple[Any, int, tuple[float, float, float], tuple[float, float, float]]] = []
    for placement in placements or ():
        container_idx = _placement_container(placement)
        if not 0 <= container_idx < len(containers):
            continue
        identifier = _placement_id(placement)
        if identifier is None:
            continue
        center = _center(_placement_field(placement, "position", "place_pos", "pos", default=placement))
        dimensions = _dimensions(placement)
        if dimensions == (0.0, 0.0, 0.0):
            dimensions = _dimensions(_placement_field(placement, "item", default={}))
        normalized.append((identifier, container_idx, center, dimensions))

    edges: dict[tuple[Any, Any, int], PortalEdge] = {}
    for blocker_index, (blocker_id, container_idx, blocker_center, blocker_dimensions) in enumerate(normalized):
        container = containers[container_idx]
        for future_id, future_container_idx, future_center, future_dimensions in normalized[blocker_index + 1:]:
            if future_container_idx != container_idx or future_id == blocker_id:
                continue
            if swept_conflict(container, blocker_center, blocker_dimensions, future_center, future_dimensions):
                key = (future_id, blocker_id, container_idx)
                edges[key] = PortalEdge(
                    before=future_id,
                    after=blocker_id,
                    container_idx=container_idx,
                    blocked_width=blocker_dimensions[0],
                    blocked_depth=blocker_center[1],
                )
            if swept_conflict(container, future_center, future_dimensions, blocker_center, blocker_dimensions):
                key = (blocker_id, future_id, container_idx)
                edges[key] = PortalEdge(
                    before=blocker_id,
                    after=future_id,
                    container_idx=container_idx,
                    blocked_width=future_dimensions[0],
                    blocked_depth=future_center[1],
                )

    return sorted(
        edges.values(),
        key=lambda edge: (str(edge.before), str(edge.after), edge.container_idx, edge.reason),
    )


def portal_capacity(
    container: Mapping[str, Any],
    placements: Sequence[Any] = (),
) -> tuple[float, float]:
    """Return a deterministic remaining width/depth proxy for ranking."""
    length = max(0.0, _float(container.get("length")))
    width = max(0.0, _float(container.get("width")))
    thickness = max(0.0, _float(container.get("thickness"), 0.04))
    occupied = 0.0
    deepest = -width * 0.5
    for placement in placements or ():
        center = _center(_placement_field(placement, "position", "place_pos", "pos", default=placement))
        dimensions = _dimensions(placement)
        occupied += dimensions[0] * dimensions[1]
        deepest = max(deepest, center[1] + dimensions[1] * 0.5)
    available_area = max(0.0, (length - 2.0 * thickness) * (width - 2.0 * thickness) - occupied)
    remaining_depth = max(0.0, width * 0.5 - deepest)
    return available_area, remaining_depth


# Descriptive aliases for callers that use “precedence” terminology.
build_portal_precedence_edges = build_portal_edges
official_swept_conflict = swept_conflict


__all__ = [
    "PortalEdge",
    "build_portal_edges",
    "build_portal_precedence_edges",
    "official_portal_start_x",
    "official_y_then_x_sweep",
    "portal_capacity",
    "swept_conflict",
    "official_swept_conflict",
]
