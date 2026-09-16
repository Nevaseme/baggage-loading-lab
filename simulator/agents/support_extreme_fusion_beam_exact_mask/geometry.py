from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np

from .model import AABB, Rect


ORIENTATION_PERMUTATIONS = (
    (0, 1, 2),
    (0, 2, 1),
    (2, 1, 0),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
)


def oriented_dimensions(dimensions: Sequence[float], orientation: int) -> tuple[float, float, float]:
    if len(dimensions) != 3:
        raise ValueError("dimensions must contain exactly three values")
    orientation = int(orientation)
    if orientation < 0 or orientation >= len(ORIENTATION_PERMUTATIONS):
        raise ValueError("orientation must be one of the six official orientations")
    permutation = ORIENTATION_PERMUTATIONS[orientation]
    return tuple(float(dimensions[i]) for i in permutation)


def quaternion_matrix(quaternion: Sequence[float]) -> np.ndarray:
    if len(quaternion) != 4:
        raise ValueError("quaternion must contain exactly four values")
    x, y, z, w = (float(value) for value in quaternion)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1e-15:
        return np.eye(3, dtype=np.float64)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def aabb_from_pose(
    world_center: Sequence[float],
    dimensions: Sequence[float],
    quaternion: Sequence[float],
    container_offset_x: float,
    *,
    alignment_tolerance_degrees: float = 5.0,
) -> AABB:
    rotation = quaternion_matrix(quaternion)
    local_center = np.asarray(tuple(world_center), dtype=np.float64).copy()
    if local_center.shape != (3,):
        raise ValueError("world_center must contain exactly three values")
    local_center[0] -= float(container_offset_x)
    half = np.abs(rotation) @ (np.asarray(tuple(dimensions), dtype=np.float64) * 0.5)
    if half.shape != (3,):
        raise ValueError("dimensions must contain exactly three values")
    alignment = np.min(np.max(np.abs(rotation), axis=0))
    axis_aligned = bool(alignment >= math.cos(math.radians(alignment_tolerance_degrees)))
    return AABB.from_center_half(local_center, half, axis_aligned=axis_aligned)


def box_inside_planes(
    center: Sequence[float],
    half: Sequence[float],
    points: np.ndarray,
    normals: np.ndarray,
    margin: float,
) -> bool:
    center_array = np.asarray(center, dtype=np.float64)
    half_array = np.asarray(half, dtype=np.float64)
    points_array = np.asarray(points, dtype=np.float64)
    normals_array = np.asarray(normals, dtype=np.float64)
    if center_array.shape != (3,) or half_array.shape != (3,):
        raise ValueError("center and half must each contain exactly three values")
    if points_array.ndim != 2 or points_array.shape[1] != 3 or normals_array.shape != points_array.shape:
        raise ValueError("points and normals must both have shape (n, 3)")
    plane_values = (
        np.sum(normals_array * (center_array - points_array), axis=1)
        + np.abs(normals_array) @ half_array
    )
    return bool(np.all(plane_values <= float(margin) + 1e-10))


def _union_area(rectangles: Sequence[Rect]) -> float:
    valid = [rect for rect in rectangles if rect.area > 0.0]
    if not valid:
        return 0.0
    xs = sorted({coordinate for rect in valid for coordinate in (rect.min_x, rect.max_x)})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (rect.min_y, rect.max_y)
            for rect in valid
            if rect.min_x < right and rect.max_x > left
        )
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start <= end:
                    end = max(end, next_end)
                else:
                    covered += end - start
                    start, end = next_start, next_end
            covered += end - start
        area += (right - left) * covered
    return area


def support_metrics(footprint: Rect, supports: Sequence[Rect], center_margin: float) -> tuple[float, bool]:
    clipped = [
        intersection
        for support in supports
        if (intersection := footprint.intersection(support)) is not None
    ]
    ratio = min(1.0, _union_area(clipped) / footprint.area) if footprint.area > 0.0 else 0.0
    cx = (footprint.min_x + footprint.max_x) * 0.5
    cy = (footprint.min_y + footprint.max_y) * 0.5
    core = Rect(cx - center_margin, cx + center_margin, cy - center_margin, cy + center_margin)
    core_clipped = [
        intersection
        for support in supports
        if (intersection := core.intersection(support)) is not None
    ]
    center_supported = core.area > 0.0 and _union_area(core_clipped) >= core.area - 1e-10
    return ratio, center_supported


def _swept_box(start: np.ndarray, end: np.ndarray, half: np.ndarray) -> AABB:
    return AABB(np.minimum(start, end) - half, np.maximum(start, end) + half)


def transport_path_clear(
    candidate: AABB,
    obstacles: Iterable[AABB],
    *,
    door_y: float,
    start_x: float,
    lift: float,
    clearance: float,
) -> bool:
    half = candidate.half
    target = candidate.center.copy()
    start = np.array((start_x, door_y - half[1], target[2] + lift), dtype=np.float64)
    y_end = np.array((start_x, target[1], target[2] + lift), dtype=np.float64)
    x_end = np.array((target[0], target[1], target[2] + lift), dtype=np.float64)
    sweeps = (_swept_box(start, y_end, half), _swept_box(y_end, x_end, half))
    for obstacle in obstacles:
        expanded = obstacle.expanded(clearance)
        if any(sweep.intersects(expanded) for sweep in sweeps):
            return False
    return True


def effective_transport_lift(
    *,
    bottom_z: float,
    top_z: float,
    resting_surfaces: Sequence[float],
    ceiling_surfaces: Sequence[float],
    requested_lift: float = 0.08,
    ceiling_margin: float = 0.018,
) -> float:
    lift = float(requested_lift)
    if any(0.0 <= bottom_z - surface <= 0.05 for surface in resting_surfaces):
        return 0.0
    for surface in ceiling_surfaces:
        clearance = float(surface) - float(top_z)
        if 0.0 <= clearance < lift + ceiling_margin:
            lift = max(0.0, clearance - ceiling_margin - 0.0005)
            break
    return lift


def depth_map_path_clear(
    candidate: AABB,
    obstacles: Sequence[AABB],
    depth_map: np.ndarray,
    *,
    container_length: float,
    container_width: float,
    container_height: float,
    container_center_z: float,
    start_x: float,
    lift: float,
    clearance: float,
    depth_tolerance: float = 0.15,
    minimum_blocking_pixels: int = 2,
) -> bool:
    image = np.asarray(depth_map, dtype=np.float64)
    if image.ndim != 2 or image.size == 0 or not np.any(image > 0.0):
        return True
    height, width = image.shape
    target_aspect = width / max(height, 1)
    container_aspect = container_length / max(container_height, 1e-9)
    if container_aspect > target_aspect:
        physical_width = container_length
        physical_height = container_length / target_aspect
    else:
        physical_height = container_height
        physical_width = container_height * target_aspect

    columns = np.arange(width, dtype=np.float64)
    rows = np.arange(height, dtype=np.float64)
    xs = -physical_width / 2.0 + (columns + 0.5) * physical_width / width
    zs = container_center_z + physical_height / 2.0 - (rows + 0.5) * physical_height / height
    half = candidate.half
    x_min = min(float(start_x), float(candidate.center[0])) - half[0] + clearance
    x_max = max(float(start_x), float(candidate.center[0])) + half[0] - clearance
    z_min = float(candidate.minimum[2] + lift + clearance)
    z_max = float(candidate.maximum[2] + lift - clearance)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if z_min > z_max:
        z_min, z_max = z_max, z_min
    selected_columns = np.flatnonzero((xs >= x_min) & (xs <= x_max))
    selected_rows = np.flatnonzero((zs >= z_min) & (zs <= z_max))
    if not len(selected_columns) or not len(selected_rows):
        return True

    door_y = -container_width / 2.0
    blocking_pixels = 0
    for row in selected_rows:
        z = zs[row]
        for column in selected_columns:
            observed_depth = image[row, column]
            if not np.isfinite(observed_depth) or observed_depth <= 1e-4:
                continue
            x = xs[column]
            model_depths = [
                float(obstacle.minimum[1] - door_y)
                for obstacle in obstacles
                if obstacle.minimum[0] - clearance <= x <= obstacle.maximum[0] + clearance
                and obstacle.minimum[2] - clearance <= z <= obstacle.maximum[2] + clearance
            ]
            if model_depths and observed_depth + depth_tolerance < min(model_depths):
                blocking_pixels += 1
                if blocking_pixels >= max(1, int(minimum_blocking_pixels)):
                    return False
    return True

