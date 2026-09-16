"""Deterministic, provenance-aware raw proposal families.

This module deliberately stops at *proposal generation*.  It does not import
the historical approximate candidate validator, scoring functions, or any
fallback action.  Callers must run every returned ``PlacementProposal``
through the package's strict exact mask before it can become a public action.

Coordinates are container-local.  ``build_packing_state`` has already
normalised the observed container points and placed boxes, so this module
never applies ``ContainerState.center[0]`` a second time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator, Sequence

import numpy as np

from .geometry import oriented_dimensions
from .model import AABB, ContainerState, ItemSpec, PackingState, PlacementProposal, Rect
from .settings import SearchSettings


class ProposalSource(str, Enum):
    """Named proposal families used in provenance strings and sidecars."""

    FLOOR_WALL_EXTREME = "floor_wall_extreme"
    RESERVED_SUPPORT_LATTICE = "reserved_support_lattice"
    OBSTACLE_FACE_EXTREME = "obstacle_face_extreme"
    SUPPORT_EDGE_FLUSH = "support_edge_flush"
    PLANE_DERIVED_EDGE = "plane_derived_edge"
    LEGACY_EXTREME_CROSS = "legacy_extreme_cross"
    FREE_RECTANGLE_BOUNDARY = "free_rectangle_boundary"
    DENSE_SUPPORT_LATTICE = "dense_support_lattice"

    # Lower-case aliases make the enum convenient for code that mirrors the
    # source names in the design document while retaining canonical values.
    floor_wall_extreme = FLOOR_WALL_EXTREME
    reserved_support_lattice = RESERVED_SUPPORT_LATTICE
    obstacle_face_extreme = OBSTACLE_FACE_EXTREME
    support_edge_flush = SUPPORT_EDGE_FLUSH
    plane_derived_edge = PLANE_DERIVED_EDGE
    legacy_extreme_cross = LEGACY_EXTREME_CROSS
    free_rectangle_boundary = FREE_RECTANGLE_BOUNDARY
    dense_support_lattice = DENSE_SUPPORT_LATTICE


_SOURCE_ORDER = (
    ProposalSource.FLOOR_WALL_EXTREME,
    ProposalSource.RESERVED_SUPPORT_LATTICE,
    ProposalSource.OBSTACLE_FACE_EXTREME,
    ProposalSource.SUPPORT_EDGE_FLUSH,
    ProposalSource.PLANE_DERIVED_EDGE,
    ProposalSource.LEGACY_EXTREME_CROSS,
    ProposalSource.FREE_RECTANGLE_BOUNDARY,
    ProposalSource.DENSE_SUPPORT_LATTICE,
)
_SOURCE_RANK = {source.value: rank for rank, source in enumerate(_SOURCE_ORDER)}


@dataclass(frozen=True)
class SupportSurface:
    """A horizontal surface on which a raw proposal may be reserved.

    ``rect`` and ``z`` are local coordinates.  ``key`` is intentionally
    stable across equivalent observations and is used only as provenance; it
    is not part of the proposal deduplication key.
    """

    key: str
    rect: Rect
    z: float


@dataclass(frozen=True)
class ProposalProvenance:
    """Sidecar retained by callers that need support/source provenance.

    The public iterator returns the immutable ``PlacementProposal`` for easy
    planner integration.  ``iter_fused_records`` exposes this richer sidecar
    without changing the existing model boundary.
    """

    sources: tuple[str, ...]
    support_sources: tuple[str, ...]
    support_levels: tuple[float, ...]


@dataclass(frozen=True)
class FusedProposal:
    proposal: PlacementProposal
    provenance: ProposalProvenance

    @property
    def sources(self) -> tuple[str, ...]:
        return self.provenance.sources

    @property
    def support_sources(self) -> tuple[str, ...]:
        return self.provenance.support_sources

    @property
    def support_levels(self) -> tuple[float, ...]:
        return self.provenance.support_levels


@dataclass(frozen=True)
class _CenterBounds:
    """Plane-aware center region at one support-derived candidate height."""

    min_x: float
    max_x: float
    min_y: float
    max_y: float
    constraints: tuple[tuple[float, float, float], ...] = ()
    constant_valid: bool = True

    @property
    def feasible(self) -> bool:
        return self.constant_valid and self.min_x <= self.max_x + 1e-10 and self.min_y <= self.max_y + 1e-10

    def with_rect(self, rect: Rect) -> "_CenterBounds | None":
        clipped = _CenterBounds(
            max(self.min_x, float(rect.min_x)),
            min(self.max_x, float(rect.max_x)),
            max(self.min_y, float(rect.min_y)),
            min(self.max_y, float(rect.max_y)),
            self.constraints,
            self.constant_valid,
        )
        return clipped if clipped.feasible else None

    def contains(self, x: float, y: float) -> bool:
        if not self.feasible or x < self.min_x - 1e-9 or x > self.max_x + 1e-9:
            return False
        if y < self.min_y - 1e-9 or y > self.max_y + 1e-9:
            return False
        return all(nx * x + ny * y <= rhs + 1e-9 for nx, ny, rhs in self.constraints)

    def x_interval_at_y(self, y: float) -> tuple[float, float] | None:
        if y < self.min_y - 1e-9 or y > self.max_y + 1e-9 or not self.constant_valid:
            return None
        left, right = self.min_x, self.max_x
        for nx, ny, rhs in self.constraints:
            residual = rhs - ny * y
            if nx > 1e-10:
                right = min(right, residual / nx)
            elif nx < -1e-10:
                left = max(left, residual / nx)
            elif ny * y > rhs + 1e-9:
                return None
        return (left, right) if left <= right + 1e-9 else None

    def y_interval_at_x(self, x: float) -> tuple[float, float] | None:
        if x < self.min_x - 1e-9 or x > self.max_x + 1e-9 or not self.constant_valid:
            return None
        front, back = self.min_y, self.max_y
        for nx, ny, rhs in self.constraints:
            residual = rhs - nx * x
            if ny > 1e-10:
                back = min(back, residual / ny)
            elif ny < -1e-10:
                front = max(front, residual / ny)
            elif nx * x > rhs + 1e-9:
                return None
        return (front, back) if front <= back + 1e-9 else None


@dataclass
class _MutableRecord:
    item_index: int
    pool_index: int
    container_index: int
    orientation: int
    position: tuple[float, float, float]
    sources: set[str]
    support_sources: set[str]
    support_levels: set[float]


def _container_ordinal(container: ContainerState) -> int:
    """Use runtime ordinal when the foundation model exposes one.

    Older foundation fixtures only carry ``index``; the fallback keeps this
    task importable while the explicit ordinal migration lands separately.
    """

    ordinal = getattr(container, "ordinal", None)
    if ordinal is not None:
        return int(ordinal)
    return int(container.index)


def _source_sort_key(value: str) -> tuple[int, str]:
    return (_SOURCE_RANK.get(value, len(_SOURCE_ORDER)), value)


def _round_position(position: Sequence[float]) -> tuple[float, float, float]:
    # A 0.1 mm (= 1e-4 m) key is intentionally separate from the emitted
    # coordinate.  The latter retains the deterministic float64 arithmetic.
    return tuple(float(value) for value in position)


def _position_key(
    item: ItemSpec,
    pool_index: int,
    container_index: int,
    orientation: int,
    position: Sequence[float],
) -> tuple[int, int, int, tuple[float, float, float]]:
    del item  # The pool position is the identity even when global IDs repeat.
    return (
        int(pool_index),
        int(container_index),
        int(orientation),
        tuple(round(float(value), 4) for value in position),
    )


def _rect(min_x: float, max_x: float, min_y: float, max_y: float) -> Rect | None:
    result = Rect(float(min_x), float(max_x), float(min_y), float(max_y))
    return result if result.area > 1e-12 else None


def _eligible_containers(
    state: PackingState,
    item: ItemSpec,
    *,
    deferred: bool = False,
) -> list[ContainerState]:
    containers = list(state.containers)
    designated = [container for container in containers if container.is_prioritized]
    ordinary = [container for container in containers if not container.is_prioritized]
    if item.is_prioritized and designated:
        return designated
    if not item.is_prioritized and ordinary:
        return designated if deferred else ordinary
    # If every container is designated, a normal item has no ordinary home;
    # preserving a candidate is preferable to silently returning no source.
    return [] if deferred else containers


def _bounds(
    container: ContainerState,
    half: np.ndarray,
    settings: SearchSettings,
) -> tuple[float, float, float, float] | None:
    # This is only the fallback rectangular envelope.  Transport clearance is
    # not a container inclusion margin: the strict plane mask permits the
    # legal 8--18 mm band and obstacle/path families add 18 mm separately.
    wall_clearance = max(-float(settings.inclusion_margin), 0.0)
    left = -float(container.length) / 2.0 + float(container.thickness) + wall_clearance + float(half[0])
    right = float(container.length) / 2.0 - float(container.thickness) - wall_clearance - float(half[0])
    front = -float(container.width) / 2.0 + float(container.thickness) + wall_clearance + float(half[1])
    back = float(container.width) / 2.0 - float(container.thickness) - wall_clearance - float(half[1])
    if left > right + 1e-12 or front > back + 1e-12:
        return None
    return (left, right, front, back)


def _plane_center_bounds(
    container: ContainerState,
    half: np.ndarray,
    z: float,
    settings: SearchSettings,
    fallback: tuple[float, float, float, float],
) -> _CenterBounds | None:
    """Solve container half-spaces for center bounds at a fixed z.

    Axis-aligned planes become exact scalar bounds (including the official
    negative inclusion margin).  Sloped/cut planes remain as two-dimensional
    inequalities; interval queries below intersect them at each sampled y/x.
    This single region is shared by every normal proposal family.
    """

    min_x, max_x, min_y, max_y = (float(value) for value in fallback)
    constraints: list[tuple[float, float, float]] = []
    constant_valid = True
    points = np.asarray(container.points, dtype=np.float64)
    normals = np.asarray(container.normals, dtype=np.float64)
    if points.ndim != 2 or normals.shape != points.shape:
        return _CenterBounds(min_x, max_x, min_y, max_y)
    for point, normal in zip(points, normals):
        if not np.all(np.isfinite(point)) or not np.all(np.isfinite(normal)):
            continue
        nx, ny, nz = (float(value) for value in normal)
        if float(np.linalg.norm(normal)) <= 1e-12:
            continue
        rhs = float(np.dot(normal, point)) + float(settings.inclusion_margin)
        rhs -= nz * float(z)
        rhs -= float(np.dot(np.abs(normal), half))
        if abs(nx) <= 1e-10 and abs(ny) <= 1e-10:
            # A horizontal plane constrains only z.  The exact mask owns
            # that feasibility check; ignoring it here avoids an incomplete
            # or legacy point/normal fixture erasing all x/y proposals.
            continue
        constraints.append((nx, ny, rhs))
        if abs(ny) <= 1e-10:
            bound = rhs / nx
            if nx > 0.0:
                max_x = min(max_x, bound)
            else:
                min_x = max(min_x, bound)
        elif abs(nx) <= 1e-10:
            bound = rhs / ny
            if ny > 0.0:
                max_y = min(max_y, bound)
            else:
                min_y = max(min_y, bound)
    result = _CenterBounds(min_x, max_x, min_y, max_y, tuple(constraints), constant_valid)
    return result if result.feasible else None


def _floor_surface(container: ContainerState) -> SupportSurface | None:
    x = -float(container.length) / 2.0 + float(container.thickness)
    X = float(container.length) / 2.0 - float(container.thickness)
    y = -float(container.width) / 2.0 + float(container.thickness)
    Y = float(container.width) / 2.0 - float(container.thickness)
    support = _rect(x, X, y, Y)
    if support is None:
        return None
    return SupportSurface("floor", support, float(container.thickness + container.buffer))


def _support_surfaces(container: ContainerState) -> list[SupportSurface]:
    """Return floor, shelves, and only axis-aligned placed-item tops."""

    result: list[SupportSurface] = []
    floor = _floor_surface(container)
    if floor is not None:
        result.append(floor)

    for obstacle_index, obstacle in enumerate(container.static_obstacles):
        support = _rect(
            float(obstacle.minimum[0]),
            float(obstacle.maximum[0]),
            float(obstacle.minimum[1]),
            float(obstacle.maximum[1]),
        )
        if support is None:
            continue
        label = "small_shelf" if obstacle_index == 0 else "shelf"
        result.append(SupportSurface(label, support, float(obstacle.maximum[2])))

    for placed in container.placed:
        # A tilted/near-tilted box remains an obstacle, never a support level.
        if not placed.box.axis_aligned:
            continue
        support = placed.box.footprint
        if support.area <= 1e-12:
            continue
        result.append(
            SupportSurface(
                f"placed_top:{int(placed.item.index)}",
                support,
                float(placed.box.maximum[2]),
            )
        )

    # Identical shelf reconstruction and observed support records should not
    # multiply the lattice.  Keep first-seen ordering for deterministic roots.
    unique: list[SupportSurface] = []
    seen: set[tuple[float, float, float, float, float]] = set()
    for surface in result:
        signature = (
            round(surface.rect.min_x, 7),
            round(surface.rect.max_x, 7),
            round(surface.rect.min_y, 7),
            round(surface.rect.max_y, 7),
            round(surface.z, 7),
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(surface)
    return unique


def _clip_center(
    position: Sequence[float],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float] | None:
    left, right, front, back = bounds
    x, y = float(position[0]), float(position[1])
    if x < left - 1e-10 or x > right + 1e-10 or y < front - 1e-10 or y > back + 1e-10:
        return None
    return (min(right, max(left, x)), min(back, max(front, y)))


def _surface_center_bounds(
    container: ContainerState,
    surface: SupportSurface,
    half: np.ndarray,
    legal_bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> _CenterBounds | None:
    # Keep the complete raw support rectangle.  The strict mask owns the
    # support-union/overhang decision; shrinking it here loses the old
    # 29.7-recall roots at support edges.
    region = _plane_center_bounds(
        container,
        half,
        _support_center_z(surface, float(half[2]), settings),
        settings,
        legal_bounds,
    )
    return region.with_rect(surface.rect) if region is not None else None


def _support_center_z(surface: SupportSurface, half_z: float, settings: SearchSettings) -> float:
    if surface.key == "floor":
        bottom = surface.z + float(settings.support_inset)
    elif surface.key in {"small_shelf", "shelf"}:
        bottom = surface.z + float(settings.shelf_drop_gap)
    else:
        # Aligned placed-item tops are exact contact levels.
        bottom = surface.z
    return float(bottom + half_z)


def _unique_orientations(item: ItemSpec) -> tuple[int, ...]:
    """Keep one official orientation for each distinct dimension triple."""

    seen: set[tuple[float, float, float]] = set()
    result: list[int] = []
    for orientation in range(6):
        dimensions = tuple(round(float(value), 12) for value in oriented_dimensions(item.dimensions, orientation))
        if dimensions in seen:
            continue
        seen.add(dimensions)
        result.append(orientation)
    return tuple(result)


def _grid_values(first: float, last: float, count: int) -> tuple[float, ...]:
    if count <= 1 or abs(last - first) <= 1e-12:
        return (float(first),)
    return tuple(float(value) for value in np.linspace(first, last, count, dtype=np.float64))


def _region_grid(bounds: _CenterBounds, count: int) -> Iterator[tuple[float, float]]:
    """Sample a rectangular lattice clipped by z-specific plane intervals."""

    for y in reversed(_grid_values(bounds.min_y, bounds.max_y, count)):
        interval = bounds.x_interval_at_y(y)
        if interval is None:
            continue
        for x in _grid_values(interval[0], interval[1], count):
            if bounds.contains(x, y):
                yield (x, y)


def _region_edge_points(bounds: _CenterBounds) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for y in (bounds.min_y, (bounds.min_y + bounds.max_y) * 0.5, bounds.max_y):
        interval = bounds.x_interval_at_y(y)
        if interval is None:
            continue
        left, right = interval
        points.extend(((left, y), ((left + right) * 0.5, y), (right, y)))
    return tuple(points)


def _safe_center(
    x: float,
    y: float,
    bounds: _CenterBounds,
) -> tuple[float, float] | None:
    if not bounds.contains(float(x), float(y)):
        return None
    return (float(x), float(y))


def _record(
    item: ItemSpec,
    pool_index: int,
    container: ContainerState,
    orientation: int,
    position: Sequence[float],
    source: ProposalSource,
    surface: SupportSurface | None,
) -> tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]:
    pos = _round_position(position)
    record = _MutableRecord(
        item_index=int(item.index),
        pool_index=int(pool_index),
        container_index=_container_ordinal(container),
        orientation=int(orientation),
        position=pos,
        sources={source.value},
        support_sources={surface.key} if surface is not None else set(),
        support_levels={round(float(surface.z), 7)} if surface is not None else set(),
    )
    return _position_key(item, pool_index, _container_ordinal(container), orientation, pos), record


def _merge(
    merged: dict[tuple[int, int, int, tuple[float, float, float]], _MutableRecord],
    record: tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord],
) -> None:
    key, incoming = record
    current = merged.get(key)
    if current is None:
        merged[key] = incoming
        return
    current.sources.update(incoming.sources)
    current.support_sources.update(incoming.support_sources)
    current.support_levels.update(incoming.support_levels)


def _iter_floor_wall(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    floor = next((surface for surface in surfaces if surface.key == "floor"), None)
    if floor is None:
        return
    region = _surface_center_bounds(container, floor, half, bounds, settings)
    if region is None:
        return
    # Door/front is yielded after back so planners naturally prefer deep roots.
    for y in (region.max_y, region.min_y):
        interval = region.x_interval_at_y(y)
        if interval is None:
            continue
        x_values = (interval[0], (interval[0] + interval[1]) * 0.5, interval[1])
        for x in x_values:
            yield _record(
                item,
                pool_index,
                container,
                orientation,
                (x, y, _support_center_z(floor, float(half[2]), settings)),
                ProposalSource.FLOOR_WALL_EXTREME,
                floor,
            )


def _iter_reserved_lattice(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    for surface in surfaces:
        center_bounds = _surface_center_bounds(container, surface, half, bounds, settings)
        if center_bounds is None:
            continue
        for x, y in _region_grid(center_bounds, 3):
            yield _record(
                item,
                pool_index,
                container,
                orientation,
                (x, y, _support_center_z(surface, float(half[2]), settings)),
                ProposalSource.RESERVED_SUPPORT_LATTICE,
                surface,
            )


def _obstacles(container: ContainerState) -> list[AABB]:
    # Every placed item, including a tilted one, is an obstacle.  Static
    # shelves/cutouts are also included for face sources.
    return [placed.box for placed in container.placed] + list(container.static_obstacles)


def _iter_obstacle_faces(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    for obstacle in _obstacles(container):
        x_faces = (
            float(obstacle.minimum[0]) - float(half[0]) - float(settings.path_clearance),
            float(obstacle.maximum[0]) + float(half[0]) + float(settings.path_clearance),
        )
        y_faces = (
            float(obstacle.minimum[1]) - float(half[1]) - float(settings.path_clearance),
            float(obstacle.maximum[1]) + float(half[1]) + float(settings.path_clearance),
        )
        x_samples = (x_faces[0], float(obstacle.center[0]), x_faces[1])
        y_samples = (y_faces[0], float(obstacle.center[1]), y_faces[1])
        for surface in surfaces:
            region = _surface_center_bounds(container, surface, half, bounds, settings)
            if region is None:
                continue
            left, right, front, back = region.min_x, region.max_x, region.min_y, region.max_y
            z = _support_center_z(surface, float(half[2]), settings)
            # X-face flush: vary Y over the face and its two door/back edges.
            for x in x_faces:
                for y in (y_samples + (back, front)):
                    center = _safe_center(x, y, region)
                    if center is not None:
                        yield _record(
                            item,
                            pool_index,
                            container,
                            orientation,
                            (center[0], center[1], z),
                            ProposalSource.OBSTACLE_FACE_EXTREME,
                            surface,
                        )
            # Door-side Y-face flush: vary X over the face and both walls.
            for y in y_faces:
                for x in (x_samples + (left, right)):
                    center = _safe_center(x, y, region)
                    if center is not None:
                        yield _record(
                            item,
                            pool_index,
                            container,
                            orientation,
                            (center[0], center[1], z),
                            ProposalSource.OBSTACLE_FACE_EXTREME,
                            surface,
                        )


def _iter_support_edges(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    for surface in surfaces:
        center_bounds = _surface_center_bounds(container, surface, half, bounds, settings)
        if center_bounds is None:
            continue
        edge_points = _region_edge_points(center_bounds)
        for x, y in edge_points:
            yield _record(
                item,
                pool_index,
                container,
                orientation,
                (x, y, _support_center_z(surface, float(half[2]), settings)),
                ProposalSource.SUPPORT_EDGE_FLUSH,
                surface,
            )


def _iter_plane_derived_edges(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    """Yield z-aware edges induced by non-axis-aligned container planes.

    The rectangular dimensions remain a cheap first envelope, but the
    simulator's plane representation can contain cut/sloped walls.  Solving
    each non-axis-aligned plane for x at representative y values (and vice
    versa) retains those edges in the raw catalog.  The exact mask remains
    authoritative for the final half-space inclusion decision.
    """

    points = np.asarray(container.points, dtype=np.float64)
    normals = np.asarray(container.normals, dtype=np.float64)
    if points.ndim != 2 or normals.shape != points.shape:
        return
    half_space_margin = float(settings.inclusion_margin)
    for point, normal in zip(points, normals):
        if not np.all(np.isfinite(point)) or not np.all(np.isfinite(normal)):
            continue
        if float(np.linalg.norm(normal)) <= 1e-12:
            continue
        nx, ny, nz = (float(value) for value in normal)
        if abs(nx) <= 1e-10 and abs(ny) <= 1e-10:
            continue
        plane_rhs = float(np.dot(normal, point)) + half_space_margin
        support_margin = float(np.dot(np.abs(normal), half))
        for surface in surfaces:
            region = _surface_center_bounds(container, surface, half, bounds, settings)
            if region is None:
                continue
            x_samples = (region.min_x, (region.min_x + region.max_x) * 0.5, region.max_x)
            y_samples = (region.min_y, (region.min_y + region.max_y) * 0.5, region.max_y)
            z = _support_center_z(surface, float(half[2]), settings)
            if abs(nx) > 1e-10:
                for y in y_samples:
                    x = (plane_rhs - ny * y - nz * z - support_margin) / nx
                    center = _safe_center(x, y, region)
                    if center is not None:
                        yield _record(
                            item,
                            pool_index,
                            container,
                            orientation,
                            (center[0], center[1], z),
                            ProposalSource.PLANE_DERIVED_EDGE,
                            surface,
                        )
            if abs(ny) > 1e-10:
                for x in x_samples:
                    y = (plane_rhs - nx * x - nz * z - support_margin) / ny
                    center = _safe_center(x, y, region)
                    if center is not None:
                        yield _record(
                            item,
                            pool_index,
                            container,
                            orientation,
                            (center[0], center[1], z),
                            ProposalSource.PLANE_DERIVED_EDGE,
                            surface,
                        )


def _iter_legacy_cross(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    left, right, front, back = bounds
    x_values: list[float] = [left, (left + right) * 0.5, right]
    y_values: list[float] = [front, (front + back) * 0.5, back]
    for obstacle in _obstacles(container):
        x_values.extend(
            (
                float(obstacle.minimum[0]) - float(half[0]) - float(settings.path_clearance),
                float(obstacle.center[0]),
                float(obstacle.maximum[0]) + float(half[0]) + float(settings.path_clearance),
            )
        )
        y_values.extend(
            (
                float(obstacle.minimum[1]) - float(half[1]) - float(settings.path_clearance),
                float(obstacle.center[1]),
                float(obstacle.maximum[1]) + float(half[1]) + float(settings.path_clearance),
            )
        )
    for surface in surfaces:
        region = _surface_center_bounds(container, surface, half, bounds, settings)
        if region is None:
            continue
        x_unique = sorted({round(value, 7) for value in x_values if region.min_x - 1e-9 <= value <= region.max_x + 1e-9})
        y_unique = sorted({round(value, 7) for value in y_values if region.min_y - 1e-9 <= value <= region.max_y + 1e-9}, reverse=True)
        z = _support_center_z(surface, float(half[2]), settings)
        for y in y_unique:
            for x in x_unique:
                if region.contains(x, y):
                    yield _record(
                        item,
                        pool_index,
                        container,
                        orientation,
                        (x, y, z),
                        ProposalSource.LEGACY_EXTREME_CROSS,
                        surface,
                    )


def _subtract_footprint(base: Rect, obstacle: Rect) -> list[Rect]:
    overlap = base.intersection(obstacle)
    if overlap is None:
        return [base]
    pieces: list[Rect] = []
    for candidate in (
        _rect(base.min_x, overlap.min_x, base.min_y, base.max_y),
        _rect(overlap.max_x, base.max_x, base.min_y, base.max_y),
        _rect(overlap.min_x, overlap.max_x, base.min_y, overlap.min_y),
        _rect(overlap.min_x, overlap.max_x, overlap.max_y, base.max_y),
    ):
        if candidate is not None:
            pieces.append(candidate)
    return pieces


def _free_support_rectangles(
    container: ContainerState,
    surface: SupportSurface,
) -> list[Rect]:
    """Return genuine rectangular free regions after footprint subtraction."""

    pieces = [surface.rect]
    for obstacle in _obstacles(container):
        # An object ending at this support plane is the support itself, not a
        # blocker.  Objects rising through/above the plane are blockers.
        if float(obstacle.minimum[2]) > surface.z + 1e-8:
            continue
        if float(obstacle.maximum[2]) <= surface.z + 1e-8:
            continue
        obstacle_rect = obstacle.footprint
        pieces = [piece for base in pieces for piece in _subtract_footprint(base, obstacle_rect)]
        if not pieces:
            break
    return pieces


def _iter_free_boundary(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    """Generate a small boundary set around free support rectangles.

    This is intentionally a rescue family.  It supplies a few free-space
    boundary roots without pretending that a dense grid is a normal planner
    primitive.
    """

    for surface in surfaces:
        for free_rect in _free_support_rectangles(container, surface):
            clipped = SupportSurface(surface.key, free_rect, surface.z)
            center_bounds = _surface_center_bounds(container, clipped, half, bounds, settings)
            if center_bounds is None:
                continue
            for x, y in _region_edge_points(center_bounds):
                yield _record(
                    item,
                    pool_index,
                    container,
                    orientation,
                    (x, y, _support_center_z(clipped, float(half[2]), settings)),
                    ProposalSource.FREE_RECTANGLE_BOUNDARY,
                    clipped,
                )


def _iter_dense_lattice(
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    for surface in surfaces:
        center_bounds = _surface_center_bounds(container, surface, half, bounds, settings)
        if center_bounds is None:
            continue
        for x, y in _region_grid(center_bounds, 11):
            yield _record(
                item,
                pool_index,
                container,
                orientation,
                (x, y, _support_center_z(surface, float(half[2]), settings)),
                ProposalSource.DENSE_SUPPORT_LATTICE,
                surface,
            )


def _family_iterator(
    source: ProposalSource,
    container: ContainerState,
    item: ItemSpec,
    pool_index: int,
    orientation: int,
    half: np.ndarray,
    surfaces: Sequence[SupportSurface],
    bounds: tuple[float, float, float, float],
    settings: SearchSettings,
) -> Iterable[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]:
    if source is ProposalSource.FLOOR_WALL_EXTREME:
        return _iter_floor_wall(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    if source is ProposalSource.RESERVED_SUPPORT_LATTICE:
        return _iter_reserved_lattice(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    if source is ProposalSource.OBSTACLE_FACE_EXTREME:
        return _iter_obstacle_faces(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    if source is ProposalSource.SUPPORT_EDGE_FLUSH:
        return _iter_support_edges(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    if source is ProposalSource.PLANE_DERIVED_EDGE:
        return _iter_plane_derived_edges(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    if source is ProposalSource.LEGACY_EXTREME_CROSS:
        return _iter_legacy_cross(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    if source is ProposalSource.FREE_RECTANGLE_BOUNDARY:
        return _iter_free_boundary(container, item, pool_index, orientation, half, surfaces, bounds, settings)
    return _iter_dense_lattice(container, item, pool_index, orientation, half, surfaces, bounds, settings)


def iter_fused_records(
    state: PackingState,
    item: ItemSpec | dict,
    pool_index: int = 0,
    *,
    deadline: float | None = None,
    rescue: bool = False,
    rescue_only: bool = False,
    deferred: bool = False,
    family_subset: Sequence[ProposalSource] | None = None,
    settings: SearchSettings | None = None,
    max_proposals: int | None = None,
    raw_work_limit: int | None = None,
    quantum: int | None = None,
    clock=time.perf_counter,
) -> Iterator[FusedProposal]:
    """Yield deterministic, deduplicated proposal records.

    ``deadline`` is an absolute monotonic-clock deadline.  If it has already
    expired, no work is performed.  ``rescue`` appends the two zero-root-only
    families; ``rescue_only`` emits just those families for diagnostics.
    ``family_subset`` gives a staged caller an explicit family sequence; an
    explicit sequence cannot be combined with either rescue selector.
    """

    if isinstance(item, dict):
        item = ItemSpec.from_dict(item)
    if not isinstance(item, ItemSpec):
        raise TypeError("item must be an ItemSpec or item dictionary")
    if not isinstance(state, PackingState):
        raise TypeError("state must be a PackingState")
    if settings is None:
        settings = SearchSettings()
    if deadline is not None and float(clock()) >= float(deadline):
        return
    if max_proposals is not None and int(max_proposals) <= 0:
        return
    if raw_work_limit is None:
        raw_work_limit = settings.raw_proposal_limit
    if int(raw_work_limit) <= 0:
        return
    quantum = max(1, int(settings.proposal_quantum if quantum is None else quantum))

    merged: dict[tuple[int, int, int, tuple[float, float, float]], _MutableRecord] = {}
    if family_subset is None:
        families = (
            (
                ProposalSource.FREE_RECTANGLE_BOUNDARY,
                ProposalSource.DENSE_SUPPORT_LATTICE,
            )
            if rescue_only
            else (
                ProposalSource.FLOOR_WALL_EXTREME,
                ProposalSource.RESERVED_SUPPORT_LATTICE,
                ProposalSource.OBSTACLE_FACE_EXTREME,
                ProposalSource.SUPPORT_EDGE_FLUSH,
                ProposalSource.PLANE_DERIVED_EDGE,
                ProposalSource.LEGACY_EXTREME_CROSS,
            )
            + (
                (ProposalSource.FREE_RECTANGLE_BOUNDARY, ProposalSource.DENSE_SUPPORT_LATTICE)
                if rescue
                else ()
            )
        )
    else:
        if rescue or rescue_only:
            raise ValueError("family_subset cannot be combined with rescue or rescue_only")
        if isinstance(family_subset, (str, bytes)):
            raise TypeError("family_subset must contain ProposalSource values")
        ordered_families: list[ProposalSource] = []
        for source in family_subset:
            if not isinstance(source, ProposalSource):
                raise TypeError("family_subset must contain ProposalSource values")
            if source not in ordered_families:
                ordered_families.append(source)
        families = tuple(ordered_families)

    work: list[Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]] = []
    eligible_containers = _eligible_containers(state, item, deferred=deferred)
    # Interleave container work at the outer scheduling boundary.  A
    # container-major list would still starve later containers under a small
    # raw cap even though the iterator loop itself is round-robin.
    for orientation in _unique_orientations(item):
        for family in families:
            for container in eligible_containers:
                surfaces = _support_surfaces(container)
                dimensions = np.asarray(oriented_dimensions(item.dimensions, orientation), dtype=np.float64)
                half = dimensions * 0.5
                bounds = _bounds(container, half, settings)
                if bounds is None:
                    continue
                work.append(
                    iter(
                        _family_iterator(
                            family,
                            container,
                            item,
                            pool_index,
                            orientation,
                            half,
                            surfaces,
                            bounds,
                            settings,
                        )
                    )
                )

    # Round-robin small quanta prevent an early container/orientation family
    # from exhausting the global raw budget before later units receive a
    # chance.  The merged map is emitted even when the deadline interrupts a
    # pass, so callers retain deterministic partial work.
    active = list(work)
    raw_count = 0
    while active:
        if deadline is not None and float(clock()) >= float(deadline):
            break
        next_active: list[Iterator[tuple[tuple[int, int, int, tuple[float, float, float]], _MutableRecord]]] = []
        stop = False
        for iterator in active:
            exhausted = False
            for _ in range(quantum):
                if deadline is not None and float(clock()) >= float(deadline):
                    stop = True
                    break
                if raw_work_limit is not None and raw_count >= int(raw_work_limit):
                    stop = True
                    break
                try:
                    record = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                _merge(merged, record)
                raw_count += 1
                if max_proposals is not None and len(merged) >= int(max_proposals):
                    stop = True
                    break
            if not exhausted and not stop:
                next_active.append(iterator)
            if stop:
                break
        if stop:
            break
        if len(next_active) == len(active):
            active = next_active
        else:
            active = next_active

    records = sorted(
        merged.values(),
        key=lambda value: (
            int(value.container_index),
            int(value.orientation),
            -float(value.position[1]),
            float(value.position[2]),
            abs(float(value.position[0])),
            float(value.position[0]),
            float(value.position[1]),
        ),
    )
    for value in records:
        sources = tuple(sorted(value.sources, key=_source_sort_key))
        provenance = ProposalProvenance(
            sources=sources,
            support_sources=tuple(sorted(value.support_sources)),
            support_levels=tuple(sorted(value.support_levels)),
        )
        proposal = PlacementProposal(
            item_index=value.item_index,
            pool_index=value.pool_index,
            container_index=value.container_index,
            orientation=value.orientation,
            position=value.position,
            source="|".join(sources),
        )
        yield FusedProposal(proposal=proposal, provenance=provenance)


def iter_fused_proposals(
    state: PackingState,
    item: ItemSpec | dict,
    pool_index: int = 0,
    **kwargs,
) -> Iterator[PlacementProposal]:
    """Yield only raw proposals; exact validation belongs to the caller."""

    for record in iter_fused_records(state, item, pool_index, **kwargs):
        yield record.proposal


def generate_fused_proposals(
    state: PackingState,
    item: ItemSpec | dict,
    pool_index: int = 0,
    **kwargs,
) -> list[PlacementProposal]:
    """List convenience wrapper for integrations and small tests."""

    return list(iter_fused_proposals(state, item, pool_index, **kwargs))


__all__ = [
    "FusedProposal",
    "ProposalProvenance",
    "ProposalSource",
    "SupportSurface",
    "generate_fused_proposals",
    "iter_fused_proposals",
    "iter_fused_records",
]
