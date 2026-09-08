"""Conservative support-grid recovery for positions missed by extreme points."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Sequence

import numpy as np

from .model import AABB, Rect


_SUPPORT_PREFIX_CACHE: OrderedDict[
    tuple[Rect, tuple[Rect, ...], float], tuple[np.ndarray, int, int]
] = OrderedDict()
_SUPPORT_PREFIX_CACHE_LIMIT = 64


def _union_area(rectangles: Sequence[Rect]) -> float:
    if not rectangles:
        return 0.0
    x_values = sorted(
        {coordinate for rectangle in rectangles for coordinate in (rectangle.min_x, rectangle.max_x)}
    )
    area = 0.0
    for left, right in zip(x_values, x_values[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (rectangle.min_y, rectangle.max_y)
            for rectangle in rectangles
            if rectangle.min_x < right and rectangle.max_x > left
        )
        covered_y = 0.0
        if intervals:
            current_min, current_max = intervals[0]
            for interval_min, interval_max in intervals[1:]:
                if interval_min <= current_max:
                    current_max = max(current_max, interval_max)
                else:
                    covered_y += current_max - current_min
                    current_min, current_max = interval_min, interval_max
            covered_y += current_max - current_min
        area += (right - left) * covered_y
    return area


def _cell_fully_supported(cell: Rect, supports: Sequence[Rect]) -> bool:
    intersections = [intersection for support in supports if (intersection := cell.intersection(support))]
    return _union_area(intersections) + 1e-10 >= cell.area


def _rectangle_sum(prefix: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> int:
    return int(prefix[y1, x1] - prefix[y0, x1] - prefix[y1, x0] + prefix[y0, x0])


def _support_prefix(
    supports: Sequence[Rect],
    bounds: Rect,
    step: float,
    deadline: float | None,
) -> tuple[np.ndarray, int, int] | None:
    key = (bounds, tuple(supports), float(step))
    cached = _SUPPORT_PREFIX_CACHE.get(key)
    if cached is not None:
        _SUPPORT_PREFIX_CACHE.move_to_end(key)
        return cached
    columns = max(1, int(math.ceil((bounds.max_x - bounds.min_x) / step)))
    rows = max(1, int(math.ceil((bounds.max_y - bounds.min_y) / step)))
    unsupported = np.ones((rows, columns), dtype=np.int32)
    for row in range(rows):
        if deadline is not None and time.perf_counter() >= deadline:
            return None
        cell_min_y = bounds.min_y + row * step
        cell_max_y = min(bounds.max_y, cell_min_y + step)
        for column in range(columns):
            cell_min_x = bounds.min_x + column * step
            cell_max_x = min(bounds.max_x, cell_min_x + step)
            cell = Rect(cell_min_x, cell_max_x, cell_min_y, cell_max_y)
            unsupported[row, column] = 0 if _cell_fully_supported(cell, supports) else 1
    result = (
        np.pad(unsupported, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1),
        rows,
        columns,
    )
    _SUPPORT_PREFIX_CACHE[key] = result
    _SUPPORT_PREFIX_CACHE.move_to_end(key)
    while len(_SUPPORT_PREFIX_CACHE) > _SUPPORT_PREFIX_CACHE_LIMIT:
        _SUPPORT_PREFIX_CACHE.popitem(last=False)
    return result


def grid_recovery_centres(
    supports: Sequence[Rect],
    bounds: Rect,
    obstacles: Sequence[AABB],
    half: np.ndarray,
    bottom_z: float,
    step: float,
    clearance: float,
    limit: int,
    deadline: float | None,
) -> list[tuple[float, float]]:
    """Return supported, collision-free grid centres, back-to-front.

    This is a proposal generator. The caller must still apply the official
    inclusion, support, protection and swept-path checks.
    """

    if limit <= 0 or step <= 0.0 or bounds.area <= 0.0:
        return []
    if deadline is not None and time.perf_counter() >= deadline:
        return []
    half = np.asarray(half, dtype=np.float64)
    if half.shape != (3,) or np.any(half <= 0.0):
        return []
    minimum_x = bounds.min_x + float(half[0])
    maximum_x = bounds.max_x - float(half[0])
    minimum_y = bounds.min_y + float(half[1])
    maximum_y = bounds.max_y - float(half[1])
    if minimum_x > maximum_x or minimum_y > maximum_y:
        return []

    support_grid = _support_prefix(supports, bounds, step, deadline)
    if support_grid is None:
        return []
    prefix, rows, columns = support_grid

    x_count = int(math.floor((maximum_x - minimum_x) / step + 1e-9)) + 1
    y_count = int(math.floor((maximum_y - minimum_y) / step + 1e-9)) + 1
    xs = [minimum_x + index * step for index in range(x_count)]
    ys = [maximum_y - index * step for index in range(y_count)]
    midpoint_x = (bounds.min_x + bounds.max_x) * 0.5
    xs.sort(key=lambda value: (abs(value - midpoint_x), value))

    candidate_top = bottom_z + float(half[2]) * 2.0
    overlapping_obstacles = [
        obstacle
        for obstacle in obstacles
        if candidate_top > obstacle.minimum[2] + 1e-9
        and obstacle.maximum[2] > bottom_z + 1e-9
    ]
    results: list[tuple[float, float]] = []
    for y in ys:
        row_results: list[tuple[float, float]] = []
        for x in xs:
            if deadline is not None and time.perf_counter() >= deadline:
                return results
            footprint_min_x = x - float(half[0])
            footprint_max_x = x + float(half[0])
            footprint_min_y = y - float(half[1])
            footprint_max_y = y + float(half[1])
            x0 = max(0, int(math.floor((footprint_min_x - bounds.min_x) / step + 1e-9)))
            x1 = min(columns, int(math.ceil((footprint_max_x - bounds.min_x) / step - 1e-9)))
            y0 = max(0, int(math.floor((footprint_min_y - bounds.min_y) / step + 1e-9)))
            y1 = min(rows, int(math.ceil((footprint_max_y - bounds.min_y) / step - 1e-9)))
            if x0 >= x1 or y0 >= y1 or _rectangle_sum(prefix, x0, x1, y0, y1):
                continue
            blocked = any(
                footprint_max_x > obstacle.minimum[0] - clearance + 1e-9
                and obstacle.maximum[0] + clearance > footprint_min_x + 1e-9
                and footprint_max_y > obstacle.minimum[1] - clearance + 1e-9
                and obstacle.maximum[1] + clearance > footprint_min_y + 1e-9
                for obstacle in overlapping_obstacles
            )
            if blocked:
                continue
            obstacle_clearance = min(
                (
                    math.hypot(
                        max(
                            float(obstacle.minimum[0]) - footprint_max_x,
                            footprint_min_x - float(obstacle.maximum[0]),
                            0.0,
                        ),
                        max(
                            float(obstacle.minimum[1]) - footprint_max_y,
                            footprint_min_y - float(obstacle.maximum[1]),
                            0.0,
                        ),
                    )
                    for obstacle in overlapping_obstacles
                ),
                default=float("inf"),
            )
            row_results.append((obstacle_clearance, float(x)))
        row_results.sort(
            key=lambda result: (-result[0], abs(result[1] - midpoint_x), result[1])
        )
        for _, x in row_results:
            results.append((round(x, 10), round(float(y), 10)))
            if len(results) >= limit:
                return results
    return results
