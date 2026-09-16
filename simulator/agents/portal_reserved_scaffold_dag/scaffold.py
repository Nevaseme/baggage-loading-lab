"""Small, deterministic support scaffolds used by the portal planner.

The objects in this module are deliberately proposal-side data.  They describe
where a placement *could* sit; they do not validate or format an official
action.  The current-state authorizer remains the only action boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping, Sequence


_EPS = 1.0e-9


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


def _floor_height(container: Mapping[str, Any]) -> float:
    normals = container.get("n_vecs", ())
    points = container.get("points", ())
    try:
        for normal, point in zip(normals, points):
            if len(normal) >= 3 and len(point) >= 3:
                if _float(normal[2]) < -0.9 and abs(_float(normal[0])) < 0.1 and abs(_float(normal[1])) < 0.1:
                    return _float(point[2], _float(container.get("thickness"), 0.04) + 0.01)
    except (TypeError, ValueError):
        pass
    return _float(container.get("floor", container.get("thickness", 0.04)), 0.04)


def _interior_rect(container: Mapping[str, Any]) -> tuple[float, float, float, float]:
    length = max(0.0, _float(container.get("length"), 0.0))
    width = max(0.0, _float(container.get("width"), 0.0))
    thickness = max(0.0, _float(container.get("thickness"), 0.04))
    return (
        -length * 0.5 + thickness,
        length * 0.5 - thickness,
        -width * 0.5 + thickness,
        width * 0.5 - thickness,
    )


def _quaternion_abs_rotation(quaternion: Sequence[Any]) -> tuple[tuple[float, float, float], ...] | None:
    if len(quaternion) != 4:
        return None
    x, y, z, w = (_float(value) for value in quaternion)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= _EPS:
        return None
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return (
        (abs(1.0 - 2.0 * (y * y + z * z)), abs(2.0 * (x * y - z * w)), abs(2.0 * (x * z + y * w))),
        (abs(2.0 * (x * y + z * w)), abs(1.0 - 2.0 * (x * x + z * z)), abs(2.0 * (y * z - x * w))),
        (abs(2.0 * (x * z - y * w)), abs(2.0 * (y * z + x * w)), abs(1.0 - 2.0 * (x * x + y * y))),
    )


def _item_extents(item: Mapping[str, Any]) -> tuple[float, float, float]:
    half = (
        0.5 * max(0.0, _float(item.get("length"))),
        0.5 * max(0.0, _float(item.get("width"))),
        0.5 * max(0.0, _float(item.get("height"))),
    )
    quaternion = item.get("orn")
    if isinstance(quaternion, Sequence) and not isinstance(quaternion, (str, bytes)):
        rotation = _quaternion_abs_rotation(quaternion)
        if rotation is not None:
            return tuple(
                sum(rotation[axis][component] * half[component] for component in range(3))
                for axis in range(3)
            )
    return half


def _item_center_local(item: Mapping[str, Any], container: Mapping[str, Any]) -> tuple[float, float, float] | None:
    position = item.get("pos", item.get("position"))
    if not isinstance(position, Sequence) or isinstance(position, (str, bytes)) or len(position) < 3:
        return None
    return (
        _float(position[0]) - _container_offset_x(container),
        _float(position[1]),
        _float(position[2]),
    )


def _item_tags(item: Mapping[str, Any]) -> frozenset[str]:
    tags: set[str] = set()
    if bool(item.get("is_soft", False)):
        tags.add("soft")
    if bool(item.get("is_prioritized", False)):
        tags.add("priority")
    if _float(item.get("mass"), 0.0) >= 12.0:
        tags.add("heavy")
    return frozenset(tags)


def _portal_rect(container: Mapping[str, Any], support_rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    # The portal is represented in local X/Y coordinates.  Keeping this as a
    # rectangle makes the planner's conflict test deterministic and cheap; the
    # official swept Y-then-X check is performed later by the authorizer.
    interior = _interior_rect(container)
    return (
        max(interior[0], support_rect[0]),
        min(interior[1], support_rect[1]),
        interior[2],
        interior[3],
    )


@dataclass(frozen=True)
class ScaffoldSlot:
    """A support surface and its remaining geometric/protection capacity."""

    slot_id: str
    container_idx: int
    kind: str
    support_rect: tuple[float, float, float, float]
    support_height: float
    admissible_footprints: tuple[tuple[float, float], ...]
    cumulative_load: float = 0.0
    headroom: float = math.inf
    protection_tags: frozenset[str] = field(default_factory=frozenset)
    ingress_portal: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    supporter_index: int | None = None
    capacity: float = math.inf

    def __post_init__(self) -> None:
        rect = tuple(_float(value) for value in self.support_rect[:4])
        if len(rect) != 4:
            raise ValueError("support_rect must contain four coordinates")
        if rect[0] > rect[1] or rect[2] > rect[3]:
            raise ValueError("support_rect bounds must be ordered")
        object.__setattr__(self, "support_rect", rect)
        object.__setattr__(self, "support_height", _float(self.support_height))
        object.__setattr__(self, "admissible_footprints", tuple(tuple(_float(v) for v in pair[:2]) for pair in self.admissible_footprints))
        object.__setattr__(self, "cumulative_load", max(0.0, _float(self.cumulative_load)))
        object.__setattr__(self, "headroom", max(0.0, _float(self.headroom, math.inf)))
        object.__setattr__(self, "protection_tags", frozenset(str(tag) for tag in self.protection_tags))
        object.__setattr__(self, "ingress_portal", tuple(_float(value) for value in self.ingress_portal[:4]))

    @property
    def container_index(self) -> int:
        return self.container_idx

    @property
    def support_min(self) -> tuple[float, float]:
        return self.support_rect[:2]

    @property
    def support_max(self) -> tuple[float, float]:
        return self.support_rect[2:]

    @property
    def footprints(self) -> tuple[tuple[float, float], ...]:
        return self.admissible_footprints

    @property
    def load(self) -> float:
        return self.cumulative_load

    @property
    def portal(self) -> tuple[float, float, float, float]:
        return self.ingress_portal

    @property
    def supporter(self) -> int | None:
        return self.supporter_index

    def accepts_footprint(self, length: float, width: float) -> bool:
        length = abs(_float(length))
        width = abs(_float(width))
        if not self.admissible_footprints:
            return (self.support_rect[1] - self.support_rect[0] + _EPS >= length and
                    self.support_rect[3] - self.support_rect[2] + _EPS >= width)
        return any(
            (footprint[0] + _EPS >= length and footprint[1] + _EPS >= width)
            or (footprint[0] + _EPS >= width and footprint[1] + _EPS >= length)
            for footprint in self.admissible_footprints
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "container_idx": self.container_idx,
            "kind": self.kind,
            "support_rect": self.support_rect,
            "support_height": self.support_height,
            "admissible_footprints": self.admissible_footprints,
            "cumulative_load": self.cumulative_load,
            "headroom": self.headroom,
            "protection_tags": tuple(sorted(self.protection_tags)),
            "ingress_portal": self.ingress_portal,
            "supporter_index": self.supporter_index,
            "capacity": self.capacity,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


def _slot(
    *,
    slot_id: str,
    container_idx: int,
    kind: str,
    container: Mapping[str, Any],
    support_rect: tuple[float, float, float, float],
    support_height: float,
    footprint: tuple[float, float],
    cumulative_load: float = 0.0,
    protection_tags: frozenset[str] = frozenset(),
    supporter_index: int | None = None,
) -> ScaffoldSlot:
    top = _floor_height(container) + max(0.0, _float(container.get("height"), 0.0))
    headroom = max(0.0, top - support_height)
    return ScaffoldSlot(
        slot_id=slot_id,
        container_idx=container_idx,
        kind=kind,
        support_rect=support_rect,
        support_height=support_height,
        admissible_footprints=(footprint,),
        cumulative_load=cumulative_load,
        headroom=headroom,
        protection_tags=protection_tags,
        ingress_portal=_portal_rect(container, support_rect),
        supporter_index=supporter_index,
    )


def build_scaffold_slots(
    items: Iterable[Mapping[str, Any]] | None,
    containers: Sequence[Mapping[str, Any]],
) -> list[ScaffoldSlot]:
    """Extract floor, shelf, settled item-top, and optional planned slots.

    ``items`` is accepted for symmetry with the planner; only settled items in
    each container contribute support surfaces.  A caller may pass planned
    item dictionaries with ``pos``/``position`` and ``planned=True`` to expose
    an item-top surface for a subsequent repair pass.
    """
    del items  # settled geometry is sourced from the container snapshots
    slots: list[ScaffoldSlot] = []
    for container_idx, container in enumerate(containers or ()):
        if not isinstance(container, Mapping):
            continue
        interior = _interior_rect(container)
        floor = _floor_height(container)
        container_length = max(0.0, _float(container.get("length"), 0.0))
        container_width = max(0.0, _float(container.get("width"), 0.0))
        container_height = max(0.0, _float(container.get("height"), 0.0))
        default_footprint = (container_length, container_width)
        slots.append(
            _slot(
                slot_id=f"c{container_idx}:floor",
                container_idx=container_idx,
                kind="floor",
                container=container,
                support_rect=interior,
                support_height=floor,
                footprint=default_footprint,
            )
        )

        if bool(container.get("shelf", False) or container.get("require_shelf", False)):
            thickness = max(0.0, _float(container.get("thickness"), 0.04))
            shelf_top = floor + container_height * 0.5
            cut_x = max(0.0, _float(container.get("cut_x"), 0.0))
            small_rect = (
                interior[0],
                min(interior[1], interior[0] + cut_x),
                interior[2],
                interior[3],
            )
            slots.append(
                _slot(
                    slot_id=f"c{container_idx}:shelf-small",
                    container_idx=container_idx,
                    kind="shelf",
                    container=container,
                    support_rect=small_rect,
                    support_height=shelf_top,
                    footprint=(max(0.0, small_rect[1] - small_rect[0]), max(0.0, small_rect[3] - small_rect[2])),
                    cumulative_load=1.0e9,
                    protection_tags=frozenset({"shelf", "rigid"}),
                )
            )
            main_rect = (
                interior[0],
                interior[1],
                max(interior[2], thickness),
                interior[3],
            )
            slots.append(
                _slot(
                    slot_id=f"c{container_idx}:shelf-main",
                    container_idx=container_idx,
                    kind="shelf",
                    container=container,
                    support_rect=main_rect,
                    support_height=shelf_top,
                    footprint=(max(0.0, main_rect[1] - main_rect[0]), max(0.0, main_rect[3] - main_rect[2])),
                    cumulative_load=1.0e9,
                    protection_tags=frozenset({"shelf", "rigid"}),
                )
            )

        packed = container.get("packed_items", ())
        for packed_ordinal, packed_item in enumerate(packed if isinstance(packed, Sequence) else ()):
            if not isinstance(packed_item, Mapping):
                continue
            center = _item_center_local(packed_item, container)
            extents = _item_extents(packed_item)
            if center is None or any(value <= _EPS for value in extents):
                continue
            rect = (
                center[0] - extents[0],
                center[0] + extents[0],
                center[1] - extents[1],
                center[1] + extents[1],
            )
            packed_index = packed_item.get("index")
            try:
                supporter_index = int(packed_index) if packed_index is not None else None
            except (TypeError, ValueError):
                supporter_index = None
            slots.append(
                _slot(
                    slot_id=f"c{container_idx}:item-top:{packed_ordinal}",
                    container_idx=container_idx,
                    kind="item_top",
                    container=container,
                    support_rect=rect,
                    support_height=center[2] + extents[2],
                    footprint=(max(0.0, 2.0 * extents[0]), max(0.0, 2.0 * extents[1])),
                    cumulative_load=max(0.0, _float(packed_item.get("mass"), 0.0)),
                    protection_tags=_item_tags(packed_item),
                    supporter_index=supporter_index,
                )
            )

    return slots


# Descriptive aliases used by downstream experiments.
extract_scaffold_slots = build_scaffold_slots
build_scaffold = build_scaffold_slots


__all__ = ["ScaffoldSlot", "build_scaffold_slots", "build_scaffold", "extract_scaffold_slots"]
