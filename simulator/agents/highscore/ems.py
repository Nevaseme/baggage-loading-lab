"""Deterministic, compressed support-layer state for EMS search.

The proxy deliberately models only axis-aligned settled geometry.  It is a
conservative search aid: any candidate returned here is revalidated by the
normal placement generator before it reaches the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from .geometry import effective_transport_lift, oriented_dimensions, transport_path_clear
from .model import AABB, ItemSpec, PackingState, Rect


_EPSILON = 1e-9
_SHELF_DROP_GAP = 0.022
_SUPPORT_HEIGHT_TOLERANCE = 0.012


@dataclass(frozen=True)
class EMS:
    rect: Rect
    bottom_z: float
    max_height: float
    container_index: int
    protection: tuple[bool, bool]


@dataclass(frozen=True)
class ProxyAction:
    item: ItemSpec
    pool_index: int
    container_index: int
    orientation: int
    box: AABB
    support_key: tuple[int, int]


@dataclass
class ProxyState:
    spaces: tuple[EMS, ...]
    boxes: tuple[AABB, ...]
    placed_ids: tuple[int, ...]
    clearance: float = 0.0
    entrance_ranges: tuple[tuple[int, float, float], ...] = ()
    door_planes: tuple[tuple[int, float], ...] = ()
    resting_surfaces: tuple[tuple[int, tuple[float, ...]], ...] = ()
    ceiling_surfaces: tuple[tuple[int, tuple[float, ...]], ...] = ()
    support_inset: float = 0.008
    shelf_drop_gap: float = _SHELF_DROP_GAP
    container_bounds: tuple[tuple[int, Rect], ...] = ()
    box_containers: tuple[int, ...] = ()


def _rect_contains(outer: Rect, inner: Rect) -> bool:
    return (
        outer.min_x <= inner.min_x + _EPSILON
        and outer.max_x >= inner.max_x - _EPSILON
        and outer.min_y <= inner.min_y + _EPSILON
        and outer.max_y >= inner.max_y - _EPSILON
    )


def _split_ems(space: EMS, footprint: Rect) -> tuple[EMS, ...]:
    """Split one support rectangle around a footprint, retaining only area."""
    intersection = space.rect.intersection(footprint)
    if intersection is None:
        return (space,)
    candidates = (
        Rect(space.rect.min_x, intersection.min_x, space.rect.min_y, space.rect.max_y),
        Rect(intersection.max_x, space.rect.max_x, space.rect.min_y, space.rect.max_y),
        Rect(space.rect.min_x, space.rect.max_x, space.rect.min_y, intersection.min_y),
        Rect(space.rect.min_x, space.rect.max_x, intersection.max_y, space.rect.max_y),
    )
    return tuple(
        EMS(rect, space.bottom_z, space.max_height, space.container_index, space.protection)
        for rect in candidates
        if rect.area > _EPSILON
    )


def _space_sort_key(space: EMS) -> tuple:
    return (
        space.container_index,
        space.bottom_z,
        space.max_height,
        space.rect.min_x,
        space.rect.min_y,
        space.rect.max_x,
        space.rect.max_y,
        space.protection,
    )


def _prune_spaces(spaces: list[EMS]) -> tuple[EMS, ...]:
    """Remove an EMS wholly dominated by another at the same support layer."""
    ordered = sorted(spaces, key=_space_sort_key)
    kept: list[EMS] = []
    for candidate in ordered:
        if candidate.rect.area <= _EPSILON:
            continue
        if any(
            other.container_index == candidate.container_index
            and abs(other.bottom_z - candidate.bottom_z) <= _EPSILON
            and abs(other.max_height - candidate.max_height) <= _EPSILON
            and other.protection == candidate.protection
            and other.rect != candidate.rect
            and _rect_contains(other.rect, candidate.rect)
            for other in ordered
        ):
            continue
        kept.append(candidate)
    return tuple(kept)


def _support_space(
    rect: Rect,
    bottom_z: float,
    max_height: float,
    container_index: int,
    protection: tuple[bool, bool] = (False, False),
) -> EMS | None:
    if rect.area <= _EPSILON or bottom_z >= max_height - _EPSILON:
        return None
    return EMS(
        rect=rect,
        bottom_z=float(np.float64(bottom_z)),
        max_height=float(np.float64(max_height)),
        container_index=container_index,
        protection=protection,
    )


def _copy_box(box: AABB) -> AABB:
    """Detach proxy geometry from mutable NumPy arrays owned by observations."""
    return AABB(
        np.asarray(box.minimum, dtype=np.float64).copy(),
        np.asarray(box.maximum, dtype=np.float64).copy(),
        box.axis_aligned,
    )


def build_proxy_state(
    state: PackingState,
    clearance: float,
    *,
    support_inset: float = 0.008,
    shelf_drop_gap: float = _SHELF_DROP_GAP,
) -> ProxyState:
    """Build floor, shelf, and settled-item support layers from packed state."""
    path_clearance = max(0.0, float(clearance))
    inset = max(0.0, float(support_inset))
    drop_gap = max(0.0, float(shelf_drop_gap))
    spaces: list[EMS] = []
    boxes: list[AABB] = []
    box_containers: list[int] = []
    placed_ids: list[int] = []
    entrance_ranges: list[tuple[int, float, float]] = []
    door_planes: list[tuple[int, float]] = []
    resting_surfaces: list[tuple[int, tuple[float, ...]]] = []
    ceiling_surfaces: list[tuple[int, tuple[float, ...]]] = []
    container_bounds: list[tuple[int, Rect]] = []
    for container in state.containers:
        floor_z = container.thickness + container.buffer
        ceiling_z = container.height - container.thickness
        shelf_top = container.height / 2.0 + container.thickness + container.buffer
        entrance_ranges.append(
            (
                container.index,
                -container.length / 2.0 + container.thickness + container.cut_x + 0.01,
                container.length / 2.0 - container.thickness - 0.01,
            )
        )
        door_planes.append((container.index, -container.width / 2.0))
        resting_surfaces.append((container.index, (floor_z, shelf_top)))
        ceiling_surfaces.append(
            (
                container.index,
                (container.height / 2.0 + container.buffer, container.height + container.buffer - container.thickness),
            )
        )
        inner = Rect(
            -container.length / 2.0 + container.thickness,
            container.length / 2.0 - container.thickness,
            -container.width / 2.0 + container.thickness,
            container.width / 2.0 - container.thickness,
        )
        container_bounds.append((container.index, inner))
        floor = _support_space(inner, floor_z + inset, ceiling_z, container.index)
        if floor is not None:
            spaces.append(floor)

        shelf_bottom = shelf_top + drop_gap
        if container.shelf:
            main_shelf = _support_space(
                Rect(
                    -container.length / 2.0 + container.thickness / 2.0,
                    container.length / 2.0 - container.thickness / 2.0,
                    container.thickness,
                    container.width / 2.0 - container.thickness,
                ),
                shelf_bottom,
                ceiling_z,
                container.index,
            )
            if main_shelf is not None:
                spaces.append(main_shelf)
        small_shelf = _support_space(
            Rect(
                -container.length / 2.0 + container.thickness,
                -container.length / 2.0 + container.thickness + container.cut_x,
                -container.width / 2.0 + container.thickness,
                container.width / 2.0 - container.thickness,
            ),
            shelf_bottom,
            ceiling_z,
            container.index,
        )
        if small_shelf is not None:
            spaces.append(small_shelf)

        boxes.extend(_copy_box(box) for box in container.static_obstacles)
        box_containers.extend(container.index for _ in container.static_obstacles)
        for placed in container.placed:
            boxes.append(_copy_box(placed.box))
            box_containers.append(container.index)
            placed_ids.append(placed.item.index)

        floor_support_z = floor_z + inset
        for placed in sorted(
            container.placed,
            key=lambda current: (
                float(current.box.minimum[2]),
                current.item.index,
            ),
        ):
            bottom_z = float(placed.box.minimum[2])
            updated_spaces: list[EMS] = []
            for space in spaces:
                same_container = space.container_index == container.index
                is_floor_layer = (
                    same_container
                    and abs(space.bottom_z - floor_support_z) <= _EPSILON
                )
                is_shelf_layer = (
                    same_container
                    and abs(space.bottom_z - shelf_bottom) <= _EPSILON
                )
                matching_floor = (
                    is_floor_layer
                    and abs(bottom_z - floor_z) <= _SUPPORT_HEIGHT_TOLERANCE
                )
                shelf_delta = bottom_z - shelf_top
                matching_shelf = (
                    is_shelf_layer
                    and -_EPSILON <= shelf_delta <= drop_gap + _SUPPORT_HEIGHT_TOLERANCE
                )
                matching_placed_top = (
                    same_container
                    and not is_floor_layer
                    and not is_shelf_layer
                    and abs(space.bottom_z - bottom_z) <= _SUPPORT_HEIGHT_TOLERANCE
                )
                if matching_floor or matching_shelf or matching_placed_top:
                    updated_spaces.extend(_split_ems(space, placed.box.footprint))
                else:
                    updated_spaces.append(space)
            spaces = list(_prune_spaces(updated_spaces))
            if not placed.box.axis_aligned:
                continue
            top = _support_space(
                placed.box.footprint,
                float(placed.box.maximum[2]),
                ceiling_z,
                container.index,
                (placed.item.is_prioritized, placed.item.is_soft),
            )
            if top is not None:
                spaces.append(top)
    return ProxyState(
        _prune_spaces(spaces),
        tuple(boxes),
        tuple(placed_ids),
        clearance=path_clearance,
        entrance_ranges=tuple(entrance_ranges),
        door_planes=tuple(door_planes),
        resting_surfaces=tuple(resting_surfaces),
        ceiling_surfaces=tuple(ceiling_surfaces),
        support_inset=inset,
        shelf_drop_gap=drop_gap,
        container_bounds=tuple(container_bounds),
        box_containers=tuple(box_containers),
    )


def _compatible(item: ItemSpec, protection: tuple[bool, bool]) -> bool:
    priority_protected, soft_protected = protection
    return (not priority_protected or item.is_prioritized) and (not soft_protected or item.is_soft)


def _intersects_any(box: AABB, boxes: tuple[AABB, ...], clearance: float) -> bool:
    for obstacle in boxes:
        if (
            box.maximum[2] <= obstacle.minimum[2] + _EPSILON
            or obstacle.maximum[2] <= box.minimum[2] + _EPSILON
        ):
            continue
        if (
            box.maximum[0] + clearance > obstacle.minimum[0] + _EPSILON
            and obstacle.maximum[0] > box.minimum[0] - clearance + _EPSILON
            and box.maximum[1] + clearance > obstacle.minimum[1] + _EPSILON
            and obstacle.maximum[1] > box.minimum[1] - clearance + _EPSILON
        ):
            return True
    return False


def _container_boxes(state: ProxyState, container_index: int) -> tuple[AABB, ...]:
    """Select local-coordinate boxes for one container, preserving legacy states."""
    if len(state.box_containers) != len(state.boxes):
        return state.boxes
    return tuple(
        box
        for box, tagged_container in zip(state.boxes, state.box_containers)
        if tagged_container == container_index
    )


def _inside_container_clearance(
    box: AABB,
    state: ProxyState,
    container_index: int,
    clearance: float,
) -> bool:
    """Apply path/collision clearance to walls without changing support Z levels."""
    bounds = next(
        (rect for index, rect in state.container_bounds if index == container_index),
        None,
    )
    if bounds is None:
        return True
    inset = max(0.0, float(clearance))
    usable = Rect(
        bounds.min_x + inset,
        bounds.max_x - inset,
        bounds.min_y + inset,
        bounds.max_y - inset,
    )
    return usable.area > _EPSILON and _rect_contains(usable, box.footprint)


def _proxy_path_clear(box: AABB, space: EMS, state: ProxyState, clearance: float) -> bool:
    """Conservatively reserve the official Y-then-X insertion corridor."""
    half = box.half
    entrance = next(
        ((minimum, maximum) for container_index, minimum, maximum in state.entrance_ranges
         if container_index == space.container_index),
        None,
    )
    door_y = next(
        (value for container_index, value in state.door_planes if container_index == space.container_index),
        None,
    )
    resting = next(
        (values for container_index, values in state.resting_surfaces if container_index == space.container_index),
        (),
    )
    ceilings = next(
        (values for container_index, values in state.ceiling_surfaces if container_index == space.container_index),
        (),
    )
    if entrance is None or door_y is None:
        # Synthetic unit-test states have no physical container metadata.
        entrance = (space.rect.min_x, space.rect.max_x)
        door_y = space.rect.min_y
        lift = 0.0
    else:
        lift = effective_transport_lift(
            bottom_z=float(box.minimum[2]),
            top_z=float(box.maximum[2]),
            resting_surfaces=resting,
            ceiling_surfaces=ceilings,
        )
    low = entrance[0] + float(half[0])
    high = entrance[1] - float(half[0])
    if low > high:
        return False
    start_x = min(max(float(box.center[0]), low), high)
    return transport_path_clear(
        box,
        _container_boxes(state, space.container_index),
        door_y=door_y,
        start_x=start_x,
        lift=lift,
        clearance=clearance,
    )


def _action_key(action: ProxyAction) -> tuple[int, int, int, int, int, int, int]:
    values = (*action.box.minimum, *action.box.maximum)
    return (action.container_index, *(int(round(float(value) / 0.001)) for value in values))


def propose_actions(
    state: ProxyState,
    item: ItemSpec,
    pool_index: int,
    *,
    limit: int,
    deadline: float,
) -> list[ProxyAction]:
    """Return deterministic, supported placements over six official rotations."""
    if limit <= 0 or time.perf_counter() >= deadline:
        return []
    proposals: list[tuple[tuple, ProxyAction]] = []
    seen: set[tuple[int, int, int, int, int, int, int]] = set()
    for space_index, space in enumerate(state.spaces):
        if time.perf_counter() >= deadline:
            break
        if not _compatible(item, space.protection):
            continue
        for orientation in range(6):
            if time.perf_counter() >= deadline:
                break
            dimensions = np.asarray(oriented_dimensions(item.dimensions, orientation), dtype=np.float64)
            half = dimensions * 0.5
            if (
                dimensions[0] > space.rect.max_x - space.rect.min_x + _EPSILON
                or dimensions[1] > space.rect.max_y - space.rect.min_y + _EPSILON
                or space.bottom_z + dimensions[2] > space.max_height + _EPSILON
            ):
                continue
            xs = (space.rect.min_x + half[0], space.rect.max_x - half[0],
                  (space.rect.min_x + space.rect.max_x) * 0.5)
            ys = (space.rect.min_y + half[1], space.rect.max_y - half[1],
                  (space.rect.min_y + space.rect.max_y) * 0.5)
            for y in ys:
                if time.perf_counter() >= deadline:
                    break
                for x in xs:
                    if time.perf_counter() >= deadline:
                        break
                    box = AABB.from_center_half((x, y, space.bottom_z + half[2]), half)
                    if not _rect_contains(space.rect, box.footprint):
                        continue
                    if (
                        not _inside_container_clearance(
                            box, state, space.container_index, state.clearance
                        )
                        or
                        _intersects_any(
                            box,
                            _container_boxes(state, space.container_index),
                            state.clearance,
                        )
                        or not _proxy_path_clear(box, space, state, state.clearance)
                    ):
                        continue
                    action = ProxyAction(
                        item,
                        pool_index,
                        space.container_index,
                        orientation,
                        _copy_box(box),
                        (space.container_index, space_index),
                    )
                    key = _action_key(action)
                    if key in seen:
                        continue
                    seen.add(key)
                    residual = space.rect.area - box.footprint.area
                    order = (
                        float(box.maximum[2]),
                        -residual,
                        space.container_index,
                        orientation,
                        float(box.center[1]),
                        float(box.center[0]),
                    )
                    proposals.append((order, action))
    proposals.sort(key=lambda value: value[0])
    return [action for _, action in proposals[:limit]]


def _matching_support(state: ProxyState, action: ProxyAction) -> EMS | None:
    container_index, space_index = action.support_key
    if space_index < 0 or space_index >= len(state.spaces):
        return None
    space = state.spaces[space_index]
    if space.container_index != container_index or action.container_index != container_index:
        return None
    return space


def apply_action(state: ProxyState, action: ProxyAction, clearance: float) -> ProxyState | None:
    """Return an immutable successor, or ``None`` when the action is infeasible."""
    support = _matching_support(state, action)
    if support is None or not _compatible(action.item, support.protection):
        return None
    dimensions = np.asarray(oriented_dimensions(action.item.dimensions, action.orientation), dtype=np.float64)
    if not np.allclose(action.box.dimensions, dimensions, rtol=0.0, atol=1e-8):
        return None
    effective_clearance = max(state.clearance, max(0.0, float(clearance)))
    if (
        abs(float(action.box.minimum[2]) - support.bottom_z) > _EPSILON
        or not _rect_contains(support.rect, action.box.footprint)
        or not _inside_container_clearance(
            action.box, state, action.container_index, effective_clearance
        )
        or float(action.box.maximum[2]) > support.max_height + _EPSILON
        or _intersects_any(
            action.box,
            _container_boxes(state, action.container_index),
            effective_clearance,
        )
        or not _proxy_path_clear(action.box, support, state, effective_clearance)
    ):
        return None

    next_spaces: list[EMS] = []
    for space in state.spaces:
        if (
            space.container_index == action.container_index
            and abs(space.bottom_z - support.bottom_z) <= _EPSILON
        ):
            next_spaces.extend(_split_ems(space, action.box.footprint))
        else:
            next_spaces.append(space)
    top = _support_space(
        action.box.footprint,
        float(action.box.maximum[2]),
        support.max_height,
        action.container_index,
        (action.item.is_prioritized, action.item.is_soft),
    )
    if top is not None:
        next_spaces.append(top)
    return ProxyState(
        spaces=_prune_spaces(next_spaces),
        boxes=tuple(_copy_box(box) for box in state.boxes) + (_copy_box(action.box),),
        placed_ids=state.placed_ids + (action.item.index,),
        clearance=effective_clearance,
        entrance_ranges=state.entrance_ranges,
        door_planes=state.door_planes,
        resting_surfaces=state.resting_surfaces,
        ceiling_surfaces=state.ceiling_surfaces,
        support_inset=state.support_inset,
        shelf_drop_gap=state.shelf_drop_gap,
        container_bounds=state.container_bounds,
        box_containers=(
            state.box_containers + (action.container_index,)
            if len(state.box_containers) == len(state.boxes)
            else ()
        ),
    )


def state_key(
    state: ProxyState,
    remaining_ids: tuple[int, ...],
    quantum: float = 0.01,
) -> tuple:
    """Canonical quantized key for transposition lookup, not feasibility."""
    if quantum <= 0.0:
        raise ValueError("quantum must be positive")
    quantize = lambda value: int(round(float(value) / quantum))
    spaces = tuple(sorted(
        (
            space.container_index,
            quantize(space.rect.min_x), quantize(space.rect.max_x),
            quantize(space.rect.min_y), quantize(space.rect.max_y),
            quantize(space.bottom_z), quantize(space.max_height),
            space.protection,
        )
        for space in state.spaces
    ))
    tagged_boxes = (
        state.box_containers
        if len(state.box_containers) == len(state.boxes)
        else tuple(-1 for _ in state.boxes)
    )
    boxes = tuple(sorted(
        (
            container_index,
            *(quantize(value) for value in box.minimum),
            *(quantize(value) for value in box.maximum),
            box.axis_aligned,
        )
        for box, container_index in zip(state.boxes, tagged_boxes)
    ))
    transport = (
        quantize(state.clearance),
        quantize(state.support_inset),
        quantize(state.shelf_drop_gap),
        tuple(sorted((index, quantize(value)) for index, value in state.door_planes)),
        tuple(sorted(
            (index, quantize(minimum), quantize(maximum))
            for index, minimum, maximum in state.entrance_ranges
        )),
        tuple(sorted(
            (index, tuple(quantize(value) for value in values))
            for index, values in state.resting_surfaces
        )),
        tuple(sorted(
            (index, tuple(quantize(value) for value in values))
            for index, values in state.ceiling_surfaces
        )),
        tuple(sorted(
            (index, quantize(rect.min_x), quantize(rect.max_x), quantize(rect.min_y), quantize(rect.max_y))
            for index, rect in state.container_bounds
        )),
    )
    return (tuple(sorted(remaining_ids)), tuple(sorted(state.placed_ids)), spaces, boxes, transport)
