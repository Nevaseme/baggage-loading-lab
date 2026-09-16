from __future__ import annotations

import math
import time
from typing import Iterable, Sequence

import numpy as np

from .geometry import (
    box_inside_planes,
    depth_map_path_clear,
    effective_transport_lift,
    oriented_dimensions,
    support_metrics,
    transport_path_clear,
)
from .free_space import grid_recovery_centres
from .ingress import build_frontier, candidate_x_intervals
from .model import AABB, Candidate, ContainerState, ItemSpec, PackingState, Rect
from .scoring import protection_rule_violations
from .settings import SearchSettings
from .ems import ProxyAction


def _dedupe(values: Iterable[float], limit: int, *, reverse: bool = False) -> list[float]:
    unique = sorted({round(float(value), 6) for value in values}, reverse=reverse)
    if len(unique) <= limit:
        return unique
    # Preserve both walls while favoring central coordinates.
    edges = [unique[0], unique[-1]]
    middle = sorted(unique[1:-1], key=abs)[: max(0, limit - 2)]
    return sorted(set(edges + middle), reverse=reverse)


def _overlap_xy(first: AABB, second: AABB, tolerance: float = 1e-9) -> bool:
    return bool(
        first.maximum[0] > second.minimum[0] + tolerance
        and second.maximum[0] > first.minimum[0] + tolerance
        and first.maximum[1] > second.minimum[1] + tolerance
        and second.maximum[1] > first.minimum[1] + tolerance
    )


def _collides_with_clearance(candidate: AABB, obstacle: AABB, clearance: float) -> bool:
    if candidate.maximum[2] <= obstacle.minimum[2] + 1e-6 or obstacle.maximum[2] <= candidate.minimum[2] + 1e-6:
        return False
    tolerance = 1e-9
    return bool(
        candidate.maximum[0] + clearance > obstacle.minimum[0] + tolerance
        and obstacle.maximum[0] > candidate.minimum[0] - clearance + tolerance
        and candidate.maximum[1] + clearance > obstacle.minimum[1] + tolerance
        and obstacle.maximum[1] > candidate.minimum[1] - clearance + tolerance
    )


class CandidateGenerator:
    def __init__(self, settings: SearchSettings):
        self.settings = settings

    def _monotone_base_positions(
        self,
        container: ContainerState,
        half: np.ndarray,
        bottom_z: float,
        extra_margin: float,
    ) -> list[tuple[float, float, float]]:
        inset = -self.settings.inclusion_margin
        wall_margin = max(inset, self.settings.path_clearance)
        left = -container.length / 2.0 + container.thickness + wall_margin
        right = container.length / 2.0 - container.thickness - wall_margin
        front = -container.width / 2.0 + container.thickness + wall_margin
        back = container.width / 2.0 - container.thickness - wall_margin
        footprint_width = 2.0 * float(half[0])
        top_z = bottom_z + 2.0 * float(half[2])
        frontier = build_frontier(
            container,
            bottom_z,
            top_z,
            self.settings.path_clearance,
            self.settings.support_height_tolerance,
        )

        positions: set[tuple[float, float, float]] = set()
        for start_x, back_limit_y in candidate_x_intervals(
            frontier,
            footprint_width,
            left,
            right,
        ):
            center_x = start_x + float(half[0])
            center_y = (
                back_limit_y
                - self.settings.path_clearance
                - extra_margin
                - float(half[1])
            )
            center_z = bottom_z + float(half[2])
            if (
                center_x - half[0] < left - 1e-9
                or center_x + half[0] > right + 1e-9
                or center_y - half[1] < front - 1e-9
                or center_y + half[1] > back + 1e-9
            ):
                continue
            positions.add(
                (
                    round(float(center_x), 6),
                    round(float(center_y), 6),
                    round(float(center_z), 6),
                )
            )
        return sorted(
            positions,
            key=lambda position: (
                -position[1],
                position[2],
                abs(position[0]),
                position[0],
            ),
        )

    def generate(
        self,
        state: PackingState,
        item: ItemSpec,
        pool_index: int,
        *,
        deadline: float | None = None,
        allow_rule_violations: bool = False,
    ) -> list[Candidate]:
        designated = [container.index for container in state.containers if container.is_prioritized]
        eligible = list(state.containers)
        if item.is_prioritized and designated:
            eligible = [container for container in eligible if container.is_prioritized]
        elif not item.is_prioritized and any(not container.is_prioritized for container in eligible):
            eligible = [container for container in eligible if not container.is_prioritized]

        all_candidates: list[Candidate] = []
        for relaxation_index, extra_margin in enumerate(self.settings.extra_margins):
            required_support = (
                self.settings.soft_support_relaxations[relaxation_index]
                if item.is_soft
                else self.settings.rigid_support_relaxations[relaxation_index]
            )
            for container in eligible:
                all_candidates.extend(
                    self._generate_for_container(
                        container,
                        item,
                        pool_index,
                        extra_margin,
                        required_support,
                        deadline,
                        allow_rule_violations,
                        use_local_grid=False,
                    )
                )
                if deadline is not None and time.perf_counter() >= deadline:
                    break
            if all_candidates or (deadline is not None and time.perf_counter() >= deadline):
                break
        if not all_candidates and (deadline is None or time.perf_counter() < deadline):
            relaxation_index = len(self.settings.extra_margins) - 1
            required_support = (
                self.settings.soft_support_relaxations[relaxation_index]
                if item.is_soft
                else self.settings.rigid_support_relaxations[relaxation_index]
            )
            for container in eligible:
                all_candidates.extend(
                    self._generate_for_container(
                        container,
                        item,
                        pool_index,
                        0.0,
                        required_support,
                        deadline,
                        allow_rule_violations,
                        use_local_grid=True,
                    )
                )
                if deadline is not None and time.perf_counter() >= deadline:
                    break
        if not all_candidates and (deadline is None or time.perf_counter() < deadline):
            relaxation_index = len(self.settings.extra_margins) - 1
            required_support = (
                self.settings.soft_support_relaxations[relaxation_index]
                if item.is_soft
                else self.settings.rigid_support_relaxations[relaxation_index]
            )
            for container in eligible:
                all_candidates.extend(
                    self._generate_recovery_for_container(
                        container,
                        item,
                        pool_index,
                        required_support,
                        deadline,
                        allow_rule_violations,
                    )
                )
                if deadline is not None and time.perf_counter() >= deadline:
                    break
        return all_candidates

    def validate_proposal(
        self,
        state: PackingState,
        action: ProxyAction,
        *,
        allow_rule_violations: bool = False,
    ) -> Candidate | None:
        """Exact-check one compressed proposal using the normal candidate validator."""
        if type(action.orientation) is not int or not 0 <= action.orientation < 6:
            return None
        container = next(
            (candidate for candidate in state.containers if candidate.index == action.container_index),
            None,
        )
        if container is None:
            return None

        designated = [candidate.index for candidate in state.containers if candidate.is_prioritized]
        if action.item.is_prioritized and designated and not container.is_prioritized:
            return None
        if (
            not action.item.is_prioritized
            and any(not candidate.is_prioritized for candidate in state.containers)
            and container.is_prioritized
        ):
            return None

        dimensions = np.asarray(
            oriented_dimensions(action.item.dimensions, action.orientation), dtype=np.float64
        )
        if not np.allclose(action.box.dimensions, dimensions, rtol=0.0, atol=1e-8):
            return None

        obstacles = [placed.box for placed in container.placed] + container.static_obstacles
        floor_z = container.thickness + container.buffer
        shelf_top = container.height / 2.0 + container.thickness + container.buffer
        current_fill_ratio = sum(placed.item.volume for placed in container.placed) / max(
            container.volume, 1e-9
        )
        relaxation_index = 0
        required_support = (
            self.settings.soft_support_relaxations[relaxation_index]
            if action.item.is_soft
            else self.settings.rigid_support_relaxations[relaxation_index]
        )
        return self._validate_position(
            container=container,
            item=action.item,
            pool_index=action.pool_index,
            orientation=action.orientation,
            box=action.box,
            obstacles=obstacles,
            floor_z=floor_z,
            shelf_top=shelf_top,
            current_fill_ratio=current_fill_ratio,
            extra_margin=self.settings.extra_margins[relaxation_index],
            required_support=required_support,
            allow_rule_violations=allow_rule_violations,
        )

    def _generate_for_container(
        self,
        container: ContainerState,
        item: ItemSpec,
        pool_index: int,
        extra_margin: float,
        required_support: float,
        deadline: float | None,
        allow_rule_violations: bool,
        use_local_grid: bool,
    ) -> list[Candidate]:
        results: list[Candidate] = []
        obstacles = [placed.box for placed in container.placed] + container.static_obstacles
        floor_z = container.thickness + container.buffer
        shelf_top = container.height / 2.0 + container.thickness + container.buffer
        current_fill_ratio = sum(placed.item.volume for placed in container.placed) / max(
            container.volume, 1e-9
        )

        for orientation in range(6):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            dimensions = np.asarray(oriented_dimensions(item.dimensions, orientation), dtype=np.float64)
            half = dimensions * 0.5
            inset = -self.settings.inclusion_margin
            wall_margin = max(inset, self.settings.path_clearance)
            left = -container.length / 2.0 + container.thickness + half[0] + wall_margin
            right = container.length / 2.0 - container.thickness - half[0] - wall_margin
            front = -container.width / 2.0 + container.thickness + half[1] + wall_margin
            back = container.width / 2.0 - container.thickness - half[1] - wall_margin
            if left > right or front > back:
                continue

            x_values: list[float] = [left + extra_margin, right - extra_margin, 0.0]
            y_values: list[float] = [back - extra_margin, front + extra_margin]
            z_values: list[float] = [floor_z + inset + half[2]]
            base_bottoms: list[float] = [floor_z + inset]
            for placed in container.placed:
                box = placed.box
                x_values.extend(
                    [
                        box.minimum[0] - half[0] - self.settings.path_clearance - extra_margin,
                        box.maximum[0] + half[0] + self.settings.path_clearance + extra_margin,
                        float(box.center[0]),
                    ]
                )
                y_values.extend(
                    [
                        box.minimum[1] - half[1] - self.settings.path_clearance - extra_margin,
                        box.maximum[1] + half[1] + self.settings.path_clearance + extra_margin,
                        float(box.center[1]),
                    ]
                )
                if placed.box.axis_aligned:
                    z_values.append(float(box.maximum[2] + half[2]))
            for obstacle in container.static_obstacles:
                x_values.extend(
                    [
                        obstacle.minimum[0] - half[0] - self.settings.path_clearance - extra_margin,
                        obstacle.maximum[0] + half[0] + self.settings.path_clearance + extra_margin,
                    ]
                )
                y_values.extend(
                    [
                        obstacle.minimum[1] - half[1] - self.settings.path_clearance - extra_margin,
                        obstacle.maximum[1] + half[1] + self.settings.path_clearance + extra_margin,
                    ]
                )
                z_values.append(float(obstacle.maximum[2] + inset + half[2]))
                base_bottoms.append(float(obstacle.maximum[2] + inset))
            if container.shelf:
                z_values.append(shelf_top + self.settings.shelf_drop_gap + half[2])
                base_bottoms.append(shelf_top + self.settings.shelf_drop_gap)
            if use_local_grid:
                step = self.settings.local_grid_step
                x_values.extend(value + offset for value in tuple(x_values) for offset in (-step, step))
                y_values.extend(value + offset for value in tuple(y_values) for offset in (-step, step))

            coordinate_limit = (
                self.settings.fallback_coordinate_limit
                if use_local_grid
                else self.settings.coordinate_limit
            )
            xs = _dedupe((x for x in x_values if left <= x <= right), coordinate_limit)
            ys = _dedupe((y for y in y_values if front <= y <= back), coordinate_limit, reverse=True)
            zs = _dedupe(z_values, coordinate_limit)

            orientation_count = 0
            orientation_full = False
            monotone_bottoms: set[float] = set()
            monotone_positions: set[tuple[float, float, float]] = set()
            if self.settings.use_monotone_ingress:
                proposals = [
                    position
                    for bottom_z in sorted({round(value, 6) for value in base_bottoms})
                    for position in self._monotone_base_positions(
                        container,
                        half,
                        bottom_z,
                        extra_margin,
                    )
                ]
                proposals = sorted(
                    set(proposals),
                    key=lambda position: (
                        -position[1],
                        position[2],
                        abs(position[0]),
                        position[0],
                    ),
                )
                for x, y, z in proposals:
                    if deadline is not None and time.perf_counter() >= deadline:
                        return results
                    candidate = self._validate_position(
                        container=container,
                        item=item,
                        pool_index=pool_index,
                        orientation=orientation,
                        box=AABB.from_center_half((x, y, z), half),
                        obstacles=obstacles,
                        floor_z=floor_z,
                        shelf_top=shelf_top,
                        current_fill_ratio=current_fill_ratio,
                        extra_margin=extra_margin,
                        required_support=required_support,
                        allow_rule_violations=allow_rule_violations,
                    )
                    if candidate is None:
                        continue
                    results.append(candidate)
                    orientation_count += 1
                    monotone_bottoms.add(round(float(candidate.box.minimum[2]), 6))
                    monotone_positions.add(
                        tuple(round(float(value), 6) for value in candidate.position)
                    )
                    if orientation_count >= self.settings.candidates_per_orientation:
                        orientation_full = True
                        break
            for z in zs:
                bottom_key = round(float(z - half[2]), 6)
                base_level_suppressed = (
                    self.settings.use_monotone_ingress
                    and bottom_key in monotone_bottoms
                )
                for y in ys:
                    for x in xs:
                        if orientation_full:
                            break
                        box = AABB.from_center_half((x, y, z), half)
                        if base_level_suppressed and not any(
                            placed.box.axis_aligned
                            and round(float(placed.box.maximum[2]), 6) == bottom_key
                            and box.footprint.intersection(placed.box.footprint) is not None
                            for placed in container.placed
                        ):
                            continue
                        if (
                            self.settings.use_monotone_ingress
                            and (round(float(x), 6), round(float(y), 6), round(float(z), 6))
                            in monotone_positions
                        ):
                            continue
                        if deadline is not None and time.perf_counter() >= deadline:
                            return results
                        candidate = self._validate_position(
                            container=container,
                            item=item,
                            pool_index=pool_index,
                            orientation=orientation,
                            box=box,
                            obstacles=obstacles,
                            floor_z=floor_z,
                            shelf_top=shelf_top,
                            current_fill_ratio=current_fill_ratio,
                            extra_margin=extra_margin,
                            required_support=required_support,
                            allow_rule_violations=allow_rule_violations,
                        )
                        if candidate is None:
                            continue
                        results.append(candidate)
                        orientation_count += 1
                        if orientation_count >= self.settings.candidates_per_orientation:
                            orientation_full = True
                            break
                    if orientation_full:
                        break
                if orientation_full:
                    break
        return results

    def _generate_recovery_for_container(
        self,
        container: ContainerState,
        item: ItemSpec,
        pool_index: int,
        required_support: float,
        deadline: float | None,
        allow_rule_violations: bool,
    ) -> list[Candidate]:
        results: list[Candidate] = []
        obstacles = [placed.box for placed in container.placed] + container.static_obstacles
        floor_z = container.thickness + container.buffer
        shelf_top = container.height / 2.0 + container.thickness + container.buffer
        current_fill_ratio = sum(placed.item.volume for placed in container.placed) / max(
            container.volume, 1e-9
        )
        inset = -self.settings.inclusion_margin
        wall_margin = max(inset, self.settings.path_clearance)
        bounds = Rect(
            -container.length / 2.0 + container.thickness + wall_margin,
            container.length / 2.0 - container.thickness - wall_margin,
            -container.width / 2.0 + container.thickness + wall_margin,
            container.width / 2.0 - container.thickness - wall_margin,
        )
        support_bottoms = {round(floor_z + inset, 6)}
        if container.shelf:
            support_bottoms.add(round(shelf_top + self.settings.shelf_drop_gap, 6))
        support_bottoms.update(
            round(float(obstacle.maximum[2]) + inset, 6)
            for obstacle in container.static_obstacles
        )
        support_bottoms.update(
            round(float(placed.box.maximum[2]), 6)
            for placed in container.placed
            if placed.box.axis_aligned
        )

        ordered_bottoms = sorted(support_bottoms)
        for orientation in range(6):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            dimensions = np.asarray(
                oriented_dimensions(item.dimensions, orientation), dtype=np.float64
            )
            half = dimensions * 0.5
            orientation_count = 0
            proposal_budget = self.settings.recovery_candidate_limit
            for level_index, bottom_z in enumerate(ordered_bottoms):
                if deadline is not None and time.perf_counter() >= deadline:
                    return results
                if proposal_budget <= 0:
                    break
                dummy = AABB.from_center_half(
                    (
                        (bounds.min_x + bounds.max_x) * 0.5,
                        (bounds.min_y + bounds.max_y) * 0.5,
                        bottom_z + half[2],
                    ),
                    (
                        max(1e-6, (bounds.max_x - bounds.min_x) * 0.5),
                        max(1e-6, (bounds.max_y - bounds.min_y) * 0.5),
                        half[2],
                    ),
                )
                support_rects, _ = self._supports(container, dummy, floor_z, shelf_top)
                if not support_rects:
                    continue
                remaining_levels = len(ordered_bottoms) - level_index
                level_limit = max(1, proposal_budget // max(1, remaining_levels))
                centres = grid_recovery_centres(
                    supports=support_rects,
                    bounds=bounds,
                    obstacles=obstacles,
                    half=half,
                    bottom_z=bottom_z,
                    step=self.settings.recovery_grid_step,
                    clearance=self.settings.path_clearance,
                    limit=level_limit,
                    deadline=deadline,
                )
                proposal_budget -= len(centres)
                for x, y in centres:
                    if deadline is not None and time.perf_counter() >= deadline:
                        return results
                    candidate = self._validate_position(
                        container=container,
                        item=item,
                        pool_index=pool_index,
                        orientation=orientation,
                        box=AABB.from_center_half((x, y, bottom_z + half[2]), half),
                        obstacles=obstacles,
                        floor_z=floor_z,
                        shelf_top=shelf_top,
                        current_fill_ratio=current_fill_ratio,
                        extra_margin=0.0,
                        required_support=required_support,
                        allow_rule_violations=allow_rule_violations,
                    )
                    if candidate is None:
                        continue
                    results.append(candidate)
                    orientation_count += 1
                    if (
                        orientation_count
                        >= self.settings.recovery_candidates_per_orientation
                    ):
                        break
                if (
                    orientation_count
                    >= self.settings.recovery_candidates_per_orientation
                ):
                    break
        return results

    def _validate_position(
        self,
        *,
        container: ContainerState,
        item: ItemSpec,
        pool_index: int,
        orientation: int,
        box: AABB,
        obstacles: Sequence[AABB],
        floor_z: float,
        shelf_top: float,
        current_fill_ratio: float,
        extra_margin: float,
        required_support: float,
        allow_rule_violations: bool,
    ) -> Candidate | None:
        if (
            box.minimum[2] <= floor_z + self.settings.support_height_tolerance
            and not self._floor_frontier_balanced(container, box, floor_z)
        ):
            return None
        if (
            container.shelf
            and current_fill_ratio < self.settings.front_floor_release_fill
            and box.minimum[2] <= floor_z + self.settings.support_height_tolerance
            and box.minimum[1] < 0.0
        ):
            return None
        clearance = self.settings.path_clearance + extra_margin
        if any(_collides_with_clearance(box, obstacle, clearance) for obstacle in obstacles):
            return None
        if not box_inside_planes(
            box.center,
            box.half,
            container.points,
            container.normals,
            self.settings.inclusion_margin,
        ):
            return None

        support_rects, supporting_items = self._supports(container, box, floor_z, shelf_top)
        support_ratio, center_supported = support_metrics(
            box.footprint,
            support_rects,
            self.settings.center_support_margin,
        )
        if support_ratio + 1e-9 < required_support or not center_supported:
            return None
        column_items = [
            placed.item
            for placed in container.placed
            if placed.box.maximum[2] <= box.minimum[2] + self.settings.support_height_tolerance
            and box.footprint.intersection(placed.box.footprint) is not None
        ]
        violations = protection_rule_violations(item, column_items or supporting_items)
        if violations and not allow_rule_violations:
            return None

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
        half = box.half
        start_x_min = (
            -container.length / 2.0
            + container.thickness
            + container.cut_x
            + half[0]
            + 0.01
        )
        start_x_max = container.length / 2.0 - container.thickness - half[0] - 0.01
        start_x = min(max(float(box.center[0]), start_x_min), start_x_max)
        if not transport_path_clear(
            box,
            obstacles,
            door_y=-container.width / 2.0 + half[1],
            start_x=start_x,
            lift=lift,
            clearance=clearance,
        ):
            return None
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
            clearance=clearance,
            depth_tolerance=self.settings.depth_tolerance,
            minimum_blocking_pixels=self.settings.depth_min_blocking_pixels,
        ):
            return None

        return Candidate(
            item=item,
            pool_index=pool_index,
            container_index=container.index,
            orientation=orientation,
            position=tuple(float(value) for value in box.center),
            box=box,
            support_ratio=support_ratio,
            min_clearance=self._minimum_horizontal_clearance(box, obstacles),
            rule_violations=violations,
        )

    def _floor_frontier_balanced(
        self,
        container: ContainerState,
        candidate: AABB,
        floor_z: float,
    ) -> bool:
        floor_boxes = [
            placed.box
            for placed in container.placed
            if placed.box.minimum[2]
            <= floor_z + self.settings.support_height_tolerance
        ]
        if not floor_boxes:
            return True
        usable_left = -container.length / 2.0 + container.thickness + container.cut_x
        usable_right = container.length / 2.0 - container.thickness
        span = max(0.0, usable_right - usable_left)
        lane_xs = (usable_left + span * 0.25, usable_left + span * 0.75)
        back = container.width / 2.0 - container.thickness
        frontiers: list[float] = []
        candidate_lanes: list[int] = []
        for lane_index, lane_x in enumerate(lane_xs):
            occupied = [
                float(box.minimum[1])
                for box in floor_boxes
                if box.minimum[0] <= lane_x <= box.maximum[0]
            ]
            frontier = min(occupied, default=back)
            if candidate.minimum[0] <= lane_x <= candidate.maximum[0]:
                frontier = min(frontier, float(candidate.minimum[1]))
                candidate_lanes.append(lane_index)
            frontiers.append(frontier)
        if not candidate_lanes:
            nearest = min(range(len(lane_xs)), key=lambda index: abs(lane_xs[index] - candidate.center[0]))
            frontiers[nearest] = min(frontiers[nearest], float(candidate.minimum[1]))
        return max(frontiers) - min(frontiers) <= self.settings.lane_frontier_skew + 1e-9

    def _supports(
        self,
        container: ContainerState,
        box: AABB,
        floor_z: float,
        shelf_top: float,
    ) -> tuple[list[Rect], list[ItemSpec]]:
        supports: list[Rect] = []
        supporting_items: list[ItemSpec] = []
        bottom = float(box.minimum[2])
        tolerance = self.settings.support_height_tolerance
        inner = Rect(
            -container.length / 2.0 + container.thickness,
            container.length / 2.0 - container.thickness,
            -container.width / 2.0 + container.thickness,
            container.width / 2.0 - container.thickness,
        )
        if abs(bottom - floor_z) <= tolerance:
            supports.append(inner)
        if 0.0 <= bottom - shelf_top <= self.settings.shelf_drop_gap + tolerance:
            if container.shelf:
                supports.append(
                    Rect(
                        -container.length / 2.0 + container.thickness / 2.0,
                        container.length / 2.0 - container.thickness / 2.0,
                        container.thickness,
                        container.width / 2.0 - container.thickness,
                    )
                )
            supports.append(
                Rect(
                    -container.length / 2.0 + container.thickness,
                    -container.length / 2.0 + container.thickness + container.cut_x,
                    -container.width / 2.0 + container.thickness,
                    container.width / 2.0 - container.thickness,
                )
            )
        for placed in container.placed:
            if not placed.box.axis_aligned:
                continue
            if abs(bottom - float(placed.box.maximum[2])) <= tolerance:
                supports.append(placed.box.footprint)
                if box.footprint.intersection(placed.box.footprint) is not None:
                    supporting_items.append(placed.item)
        return supports, supporting_items

    @staticmethod
    def _minimum_horizontal_clearance(box: AABB, obstacles: Sequence[AABB]) -> float:
        distances: list[float] = []
        for obstacle in obstacles:
            if box.maximum[2] <= obstacle.minimum[2] or obstacle.maximum[2] <= box.minimum[2]:
                continue
            dx = max(obstacle.minimum[0] - box.maximum[0], box.minimum[0] - obstacle.maximum[0], 0.0)
            dy = max(obstacle.minimum[1] - box.maximum[1], box.minimum[1] - obstacle.maximum[1], 0.0)
            distances.append(math.hypot(dx, dy))
        return min(distances, default=1.0)
