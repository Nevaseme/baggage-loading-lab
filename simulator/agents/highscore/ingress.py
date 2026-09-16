from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .model import AABB, ContainerState


_EPSILON = 1e-6


@dataclass(frozen=True)
class XFrontier:
    min_x: float
    max_x: float
    front_y: float


def maximum_free_opening(
    blocked: Sequence[tuple[float, float]],
    left: float,
    right: float,
) -> float:
    """Return the widest unblocked X opening inside the supplied walls."""
    if right <= left:
        return 0.0

    clipped = []
    for start, end in blocked:
        minimum = max(left, min(float(start), float(end)))
        maximum = min(right, max(float(start), float(end)))
        if maximum > minimum:
            clipped.append((minimum, maximum))
    clipped.sort()

    merged: list[tuple[float, float]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))

    widest = 0.0
    cursor = left
    for start, end in merged:
        widest = max(widest, start - cursor)
        cursor = max(cursor, end)
    return max(widest, right - cursor)


def build_frontier(
    container: ContainerState,
    bottom_z: float,
    top_z: float,
    clearance: float,
    height_tolerance: float,
) -> tuple[XFrontier, ...]:
    """Build the nearest ingress Y boundary for each continuous X interval."""
    del clearance  # The skyline records physical faces; callers apply clearance to placements.
    usable_left = -container.length * 0.5 + container.thickness
    usable_right = container.length * 0.5 - container.thickness
    usable_back = container.width * 0.5 - container.thickness
    if usable_right <= usable_left:
        return ()

    obstacles = [*container.static_obstacles, *(placed.box for placed in container.placed)]
    participating: list[AABB] = []
    for obstacle in obstacles:
        if (
            float(obstacle.maximum[2]) < bottom_z - height_tolerance
            or float(obstacle.minimum[2]) > top_z + height_tolerance
        ):
            continue
        if (
            float(obstacle.maximum[0]) <= usable_left + _EPSILON
            or float(obstacle.minimum[0]) >= usable_right - _EPSILON
        ):
            continue
        participating.append(obstacle)

    x_faces = [usable_left, usable_right]
    for obstacle in participating:
        x_faces.extend(
            (
                max(usable_left, float(obstacle.minimum[0])),
                min(usable_right, float(obstacle.maximum[0])),
            )
        )
    x_faces.sort()
    unique_faces: list[float] = []
    for face in x_faces:
        if not unique_faces or face - unique_faces[-1] > _EPSILON:
            unique_faces.append(face)

    elementary: list[XFrontier] = []
    for min_x, max_x in zip(unique_faces, unique_faces[1:]):
        if max_x - min_x <= _EPSILON:
            continue
        front_y = usable_back
        for obstacle in participating:
            if (
                float(obstacle.minimum[0]) < max_x - _EPSILON
                and float(obstacle.maximum[0]) > min_x + _EPSILON
            ):
                front_y = min(front_y, float(obstacle.minimum[1]))
        elementary.append(XFrontier(min_x, max_x, front_y))

    merged: list[XFrontier] = []
    for segment in elementary:
        if merged and abs(merged[-1].front_y - segment.front_y) <= _EPSILON:
            previous = merged[-1]
            merged[-1] = XFrontier(previous.min_x, segment.max_x, previous.front_y)
        else:
            merged.append(segment)
    return tuple(merged)


def candidate_x_intervals(
    frontier: Sequence[XFrontier],
    footprint_width: float,
    left: float,
    right: float,
) -> tuple[tuple[float, float], ...]:
    """Propose deterministic ingress X starts with their limiting back Y."""
    width = float(footprint_width)
    if width <= 0.0 or width > right - left:
        return ()

    starts = [left, right - width]
    for segment in frontier:
        starts.extend(
            (
                segment.min_x,
                segment.max_x - width,
                (segment.min_x + segment.max_x - width) * 0.5,
            )
        )
    starts.sort()
    unique_starts: list[float] = []
    for start in starts:
        if start < left or start + width > right:
            continue
        if not unique_starts or start - unique_starts[-1] > _EPSILON:
            unique_starts.append(start)

    fits: list[tuple[float, float]] = []
    for start in unique_starts:
        end = start + width
        overlapping = [
            segment.front_y
            for segment in frontier
            if segment.min_x < end and segment.max_x > start
        ]
        if overlapping:
            fits.append((start, min(overlapping)))
    return tuple(fits)
