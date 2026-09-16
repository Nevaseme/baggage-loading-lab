"""Pure, bounded future-space features for analytical search nodes.

The functions in this module only read immutable simulation inputs.  They do
not generate proposals, validate actions, or issue validation receipts.  A
higher value is better for every field except ``root_scarcity``,
``fragmentation``, and ``sliver_area``, which are urgency/penalty features.
In particular, ``low_mass_cog_goodness`` is explicitly directional: 1 means
low and 0 means near the container ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

from .catalog import RootCatalog
from .geometry import oriented_dimensions
from .model import ContainerState, ItemSpec, Rect, ValidatedRoot
from .settings import SearchSettings
from .state import state_fingerprint
from .transition import SimState


_EPSILON = 1.0e-12


def _bounded(value: float, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    if not math.isfinite(result):
        return float(default)
    return min(1.0, max(0.0, result))


@dataclass(frozen=True)
class FutureFeatures:
    """Finite normalized planner features.

    Coverage, robustness, capacity, access, low-CoG, margins, and low-stack
    are goodness values.  Rarity, fragmentation, and sliver area are
    non-negative costs for the beam ranker.
    """

    future_covered_items: float = 0.0
    future_covered_volume: float = 0.0
    root_robustness: float = 0.0
    root_scarcity: float = 0.0
    compatible_support_capacity: float = 0.0
    protection_compatible_capacity: float = 0.0
    largest_free_support: float = 0.0
    ingress_access: float = 0.0
    fragmentation: float = 0.0
    sliver_area: float = 0.0
    low_mass_cog_goodness: float = 1.0
    min_support_margin: float = 0.0
    min_clearance_margin: float = 0.0
    low_stack: float = 1.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _bounded(getattr(self, name)))


@dataclass(frozen=True)
class _Surface:
    container: ContainerState
    height: float
    base: Rect
    lower: ItemSpec | None
    bottom_offset: float
    layer_tolerance: float


def _inner_floor(container: ContainerState) -> Rect:
    return Rect(
        -container.length / 2.0 + container.thickness,
        container.length / 2.0 - container.thickness,
        -container.width / 2.0 + container.thickness,
        container.width / 2.0 - container.thickness,
    )


def _support_surfaces(
    containers: Sequence[ContainerState],
    settings: SearchSettings,
) -> tuple[_Surface, ...]:
    surfaces: list[_Surface] = []
    layer_tolerance = min(0.001, settings.support_height_tolerance)
    for container in containers:
        floor_z = container.thickness + container.buffer
        surfaces.append(
            _Surface(
                container,
                floor_z,
                _inner_floor(container),
                None,
                max(0.0, -settings.inclusion_margin),
                layer_tolerance,
            )
        )
        for obstacle in container.static_obstacles:
            if obstacle.axis_aligned:
                surfaces.append(
                    _Surface(
                        container,
                        float(obstacle.maximum[2]),
                        obstacle.footprint,
                        None,
                        settings.shelf_drop_gap,
                        layer_tolerance,
                    )
                )
        for placed in container.placed:
            if placed.box.axis_aligned:
                surfaces.append(
                    _Surface(
                        container,
                        float(placed.box.maximum[2]),
                        placed.box.footprint,
                        placed.item,
                        0.0,
                        layer_tolerance,
                    )
                )
    return tuple(surfaces)


def _protection_compatible(upper: ItemSpec, lower: ItemSpec | None) -> bool:
    if lower is None:
        return True
    return (
        (not lower.is_prioritized or upper.is_prioritized)
        and (not lower.is_soft or upper.is_soft)
    )


def _orientation_options(items: Iterable[ItemSpec]) -> tuple[tuple[float, float, float], ...]:
    unique = {
        oriented_dimensions(item.dimensions, orientation)
        for item in items
        for orientation in range(6)
    }
    # Only Pareto-minimal shapes matter for the question "can at least one
    # remaining occurrence fit here?".  This keeps exact cell coverage cheap
    # even for a large visible pool.
    options = tuple(sorted(unique))
    return tuple(
        option
        for option in options
        if not any(
            other != option
            and all(other[axis] <= option[axis] + _EPSILON for axis in range(3))
            for other in options
        )
    )


def _surface_grid(
    surface: _Surface,
) -> tuple[tuple[float, ...], tuple[float, ...], list[list[bool]], list[list[float]]]:
    base = surface.base
    obstacles = tuple(
        (placed.box, True) for placed in surface.container.placed
    ) + tuple((obstacle, False) for obstacle in surface.container.static_obstacles)
    relevant = tuple(
        (box, is_placed, intersection)
        for box, is_placed in obstacles
        if box.maximum[2] > surface.height + _EPSILON
        if (intersection := base.intersection(box.footprint)) is not None
    )
    xs = tuple(
        sorted(
            {base.min_x, base.max_x}
            | {coordinate for _, _, rect in relevant for coordinate in (rect.min_x, rect.max_x)}
        )
    )
    ys = tuple(
        sorted(
            {base.min_y, base.max_y}
            | {coordinate for _, _, rect in relevant for coordinate in (rect.min_y, rect.max_y)}
        )
    )
    inner_ceiling = surface.container.height - surface.container.thickness
    free: list[list[bool]] = []
    headroom: list[list[float]] = []
    expected_bottom = surface.height + surface.bottom_offset
    for bottom, top in zip(ys, ys[1:]):
        row_free: list[bool] = []
        row_headroom: list[float] = []
        y = (bottom + top) * 0.5
        for left, right in zip(xs, xs[1:]):
            x = (left + right) * 0.5
            blocked = False
            ceiling = inner_ceiling
            for box, is_placed, footprint in relevant:
                if not (
                    footprint.min_x - _EPSILON <= x <= footprint.max_x + _EPSILON
                    and footprint.min_y - _EPSILON <= y <= footprint.max_y + _EPSILON
                ):
                    continue
                same_layer = is_placed and abs(
                    float(box.minimum[2]) - expected_bottom
                ) <= surface.layer_tolerance
                crosses_plane = float(box.minimum[2]) <= surface.height + _EPSILON
                if same_layer or crosses_plane:
                    blocked = True
                    break
                ceiling = min(ceiling, float(box.minimum[2]))
            row_free.append(not blocked)
            row_headroom.append(max(0.0, ceiling - expected_bottom) if not blocked else 0.0)
        free.append(row_free)
        headroom.append(row_headroom)
    return xs, ys, free, headroom


def _mark_coverable(
    xs: Sequence[float],
    ys: Sequence[float],
    free: Sequence[Sequence[bool]],
    headroom: Sequence[Sequence[float]],
    options: Sequence[tuple[float, float, float]],
) -> tuple[list[list[bool]], float]:
    rows = len(free)
    columns = len(free[0]) if rows else 0
    difference = [[0 for _ in range(columns + 1)] for _ in range(rows + 1)]
    largest = 0.0
    for row_start in range(rows):
        common_free = [True] * columns
        common_headroom = [math.inf] * columns
        for row_end in range(row_start, rows):
            for column in range(columns):
                common_free[column] = common_free[column] and bool(free[row_end][column])
                common_headroom[column] = min(
                    common_headroom[column], float(headroom[row_end][column])
                )
            span_y = ys[row_end + 1] - ys[row_start]
            for length, width, item_height in options:
                if width > span_y + _EPSILON:
                    continue
                column = 0
                while column < columns:
                    while column < columns and not (
                        common_free[column]
                        and common_headroom[column] + _EPSILON >= item_height
                    ):
                        column += 1
                    start = column
                    while column < columns and (
                        common_free[column]
                        and common_headroom[column] + _EPSILON >= item_height
                    ):
                        column += 1
                    if start == column or xs[column] - xs[start] + _EPSILON < length:
                        continue
                    largest = max(largest, (xs[column] - xs[start]) * span_y)
                    # O(1) rectangle mark; materialize coverage once after all
                    # row bands and orientation options have been examined.
                    difference[row_start][start] += 1
                    difference[row_start][column] -= 1
                    difference[row_end + 1][start] -= 1
                    difference[row_end + 1][column] += 1
    covered = [[False for _ in range(columns)] for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            if row:
                difference[row][column] += difference[row - 1][column]
            if column:
                difference[row][column] += difference[row][column - 1]
            if row and column:
                difference[row][column] -= difference[row - 1][column - 1]
            covered[row][column] = difference[row][column] > 0
    return covered, largest


def _largest_geometric_rectangle(
    xs: Sequence[float],
    ys: Sequence[float],
    free: Sequence[Sequence[bool]],
) -> float:
    rows = len(free)
    columns = len(free[0]) if rows else 0
    largest = 0.0
    for row_start in range(rows):
        common = [True] * columns
        for row_end in range(row_start, rows):
            for column in range(columns):
                common[column] = common[column] and bool(free[row_end][column])
            column = 0
            while column < columns:
                while column < columns and not common[column]:
                    column += 1
                start = column
                while column < columns and common[column]:
                    column += 1
                if start < column:
                    largest = max(
                        largest,
                        (xs[column] - xs[start]) * (ys[row_end + 1] - ys[row_start]),
                    )
    return largest


def _surface_features(
    sim_state: SimState,
    settings: SearchSettings,
) -> tuple[float, float, float, float, float]:
    containers = sim_state.packing.containers
    pool = sim_state.pool
    surfaces = _support_surfaces(containers, settings)
    reference_area = sum(_inner_floor(container).area for container in containers)
    if reference_area <= _EPSILON:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    # Count every available plane once in the capacity denominator.  Unlike a
    # floor-only denominator this cannot saturate when a new top is created:
    # replacing low floor area with a higher plane therefore correctly loses
    # vertical capacity, and protection-compatible tops remain measurable.
    capacity_reference = sum(surface.base.area for surface in surfaces)

    compatible_area = 0.0
    protected_area = 0.0
    free_area = 0.0
    unusable_area = 0.0
    largest = 0.0
    geometric_largest = 0.0
    ordinary_options = _orientation_options(pool)
    for surface in surfaces:
        floor_z = surface.container.thickness + surface.container.buffer
        inner_ceiling = surface.container.height - surface.container.thickness
        usable_height = max(_EPSILON, inner_ceiling - floor_z)
        xs, ys, free, headroom = _surface_grid(surface)
        compatible_cells, fit_largest = _mark_coverable(
            xs, ys, free, headroom, ordinary_options
        )
        protected_options = _orientation_options(
            item for item in pool if _protection_compatible(item, surface.lower)
        )
        protected_cells, _ = _mark_coverable(
            xs, ys, free, headroom, protected_options
        )
        largest = max(largest, fit_largest)
        geometric_largest = max(
            geometric_largest, _largest_geometric_rectangle(xs, ys, free)
        )
        for row, (bottom, top) in enumerate(zip(ys, ys[1:])):
            for column, (left, right) in enumerate(zip(xs, xs[1:])):
                if not free[row][column]:
                    continue
                area = (right - left) * (top - bottom)
                free_area += area
                weight = _bounded(headroom[row][column] / usable_height)
                if compatible_cells[row][column]:
                    compatible_area += area * weight
                elif pool:
                    unusable_area += area
                if protected_cells[row][column]:
                    protected_area += area * weight

    if not pool:
        compatible = protected = 1.0
        sliver = 0.0
    else:
        compatible = compatible_area / max(capacity_reference, _EPSILON)
        protected = protected_area / max(capacity_reference, _EPSILON)
        sliver = unusable_area / max(free_area, _EPSILON)
    fragmentation = 0.0 if free_area <= _EPSILON else 1.0 - geometric_largest / free_area
    return (
        _bounded(compatible),
        _bounded(protected),
        _bounded(largest / reference_area),
        _bounded(fragmentation),
        _bounded(sliver),
    )


def _ingress_access(sim_state: SimState, settings: SearchSettings) -> float:
    if not sim_state.packing.containers:
        return 0.0
    if not sim_state.pool:
        return 1.0
    best_access = 0.0
    for span_x, span_y, span_z in _orientation_options(sim_state.pool):
        lane_total = 0
        lane_open = 0
        for container in sim_state.packing.containers:
            inner = _inner_floor(container)
            floor_z = container.thickness + container.buffer
            inner_ceiling = container.height - container.thickness
            if (
                inner.area <= _EPSILON
                or span_x > inner.max_x - inner.min_x + _EPSILON
                or span_z > inner_ceiling - floor_z + _EPSILON
            ):
                continue
            lane_count = 32
            door_y = inner.min_y
            lateral_margin = span_x * 0.5 + settings.path_clearance
            front_depth = max(0.25, span_y + 2.0 * settings.path_clearance)
            transport_top = floor_z + span_z + 0.08 + settings.path_clearance
            obstacles = tuple(placed.box for placed in container.placed) + tuple(
                container.static_obstacles
            )
            for ordinal in range(lane_count):
                x = inner.min_x + (ordinal + 0.5) * (inner.max_x - inner.min_x) / lane_count
                blocked = any(
                    obstacle.minimum[0] - lateral_margin <= x <= obstacle.maximum[0] + lateral_margin
                    and obstacle.minimum[1] <= door_y + front_depth
                    and obstacle.maximum[1] >= door_y - settings.path_clearance
                    and obstacle.minimum[2] <= transport_top
                    and obstacle.maximum[2] >= floor_z
                    for obstacle in obstacles
                )
                lane_total += 1
                lane_open += int(not blocked)
        if lane_total:
            best_access = max(best_access, lane_open / lane_total)
    return _bounded(best_access)


def _state_stability(sim_state: SimState) -> tuple[float, float]:
    weighted_height = 0.0
    total_mass = 0.0
    highest_fraction = 0.0
    for container in sim_state.packing.containers:
        floor_z = container.thickness + container.buffer
        inner_ceiling = container.height - container.thickness
        usable_height = max(_EPSILON, inner_ceiling - floor_z)
        for placed in container.placed:
            normalized_center = _bounded((float(placed.box.center[2]) - floor_z) / usable_height)
            mass = max(0.0, float(placed.item.mass))
            weighted_height += mass * normalized_center
            total_mass += mass
            highest_fraction = max(
                highest_fraction,
                _bounded((float(placed.box.maximum[2]) - floor_z) / usable_height),
            )
    cog_goodness = 1.0 if total_mass <= _EPSILON else 1.0 - weighted_height / total_mass
    return _bounded(cog_goodness, 1.0), _bounded(1.0 - highest_fraction, 1.0)


def _root_margin(root: ValidatedRoot, pool: Sequence[ItemSpec], settings: SearchSettings) -> tuple[float, float]:
    pool_index = root.proposal.pool_index
    if pool_index < 0 or pool_index >= len(pool):
        return 0.0, 0.0
    required = (
        settings.soft_support_ratio
        if pool[pool_index].is_soft
        else settings.rigid_support_ratio
    )
    support = (root.support_ratio - required) / max(_EPSILON, 1.0 - required)
    clearance = root.min_clearance / max(_EPSILON, settings.path_clearance)
    return _bounded(support), _bounded(clearance)


def _root_matches_node(
    root: ValidatedRoot,
    sim_state: SimState,
    profile_digest: str,
) -> bool:
    index = root.proposal.pool_index
    if not (
        0 <= index < len(sim_state.pool)
        and root.strict
        and root.rule_violations == 0
        and root.profile_digest == profile_digest
        and root.proposal.item_index == sim_state.pool[index].index
    ):
        return False
    expected = state_fingerprint(
        sim_state.packing,
        sim_state.pool,
        index,
        profile_digest,
    )
    return root.state_fingerprint == expected


def _catalog_features(
    sim_state: SimState,
    catalog: RootCatalog | None,
    settings: SearchSettings,
) -> tuple[float, float, float, float, tuple[float, ...], tuple[float, ...]]:
    pool_size = len(sim_state.pool)
    if catalog is None:
        return (1.0, 1.0, 1.0, 0.0, (), ()) if pool_size == 0 else (0.0, 0.0, 0.0, 1.0, (), ())
    if not isinstance(catalog, RootCatalog):
        raise TypeError("catalog must be a RootCatalog or None")
    per_pool: list[list[ValidatedRoot]] = [[] for _ in range(pool_size)]
    profile_digest = settings.profile_digest()
    expected_fingerprints: dict[int, str] = {}
    for record in catalog.records:
        root = record.root
        index = root.proposal.pool_index
        if not (0 <= index < pool_size):
            continue
        expected = expected_fingerprints.get(index)
        if expected is None:
            expected = state_fingerprint(
                sim_state.packing,
                sim_state.pool,
                index,
                profile_digest,
            )
            expected_fingerprints[index] = expected
        if (
            root.strict
            and root.rule_violations == 0
            and root.profile_digest == profile_digest
            and root.proposal.item_index == sim_state.pool[index].index
            and root.state_fingerprint == expected
        ):
            per_pool[index].append(root)
    covered = tuple(index for index, roots in enumerate(per_pool) if roots)
    item_coverage = len(covered) / max(1, pool_size)
    total_volume = sum(item.volume for item in sim_state.pool)
    covered_volume = sum(sim_state.pool[index].volume for index in covered)
    volume_coverage = (
        1.0
        if pool_size == 0
        else (
            covered_volume / total_volume
            if total_volume > 0.0
            else item_coverage
        )
    )
    support_margins: list[float] = []
    clearance_margins: list[float] = []
    best_robustness: list[float] = []
    rarity_values: list[float] = []
    for roots in per_pool:
        rarity_values.append(1.0 / (1.0 + len(roots)))
        if not roots:
            best_robustness.append(0.0)
            continue
        margins = tuple(_root_margin(root, sim_state.pool, settings) for root in roots)
        support_margins.extend(margin[0] for margin in margins)
        clearance_margins.extend(margin[1] for margin in margins)
        best_robustness.append(max(min(margin) for margin in margins))
    robustness = (
        sum(best_robustness) / len(best_robustness)
        if best_robustness
        else (1.0 if pool_size == 0 else 0.0)
    )
    rarity = sum(rarity_values) / max(1, len(rarity_values))
    return (
        _bounded(item_coverage if pool_size else 1.0),
        _bounded(volume_coverage),
        _bounded(robustness),
        _bounded(rarity),
        tuple(support_margins),
        tuple(clearance_margins),
    )


def compute_future_features(
    sim_state: SimState,
    *,
    catalog: RootCatalog | None = None,
    selected_root: ValidatedRoot | None = None,
    settings: SearchSettings | None = None,
) -> FutureFeatures:
    """Compute deterministic normalized features without changing inputs."""

    if not isinstance(sim_state, SimState):
        raise TypeError("sim_state must be a SimState")
    profile = settings or SearchSettings()
    if not isinstance(profile, SearchSettings):
        raise TypeError("settings must be SearchSettings or None")
    if selected_root is not None and not isinstance(selected_root, ValidatedRoot):
        raise TypeError("selected_root must be a ValidatedRoot or None")

    (
        item_coverage,
        volume_coverage,
        robustness,
        rarity,
        catalog_support,
        catalog_clearance,
    ) = _catalog_features(sim_state, catalog, profile)
    compatible, protected, largest, fragmentation, sliver = _surface_features(
        sim_state, profile
    )
    cog_goodness, low_stack = _state_stability(sim_state)
    if selected_root is not None:
        if _root_matches_node(selected_root, sim_state, profile.profile_digest()):
            support_margin, clearance_margin = _root_margin(
                selected_root, sim_state.pool, profile
            )
        else:
            support_margin = clearance_margin = 0.0
    else:
        support_margin = min(catalog_support, default=0.0)
        clearance_margin = min(catalog_clearance, default=0.0)

    return FutureFeatures(
        future_covered_items=item_coverage,
        future_covered_volume=volume_coverage,
        root_robustness=robustness,
        root_scarcity=rarity,
        compatible_support_capacity=compatible,
        protection_compatible_capacity=protected,
        largest_free_support=largest,
        ingress_access=_ingress_access(sim_state, profile),
        fragmentation=fragmentation,
        sliver_area=sliver,
        low_mass_cog_goodness=cog_goodness,
        min_support_margin=support_margin,
        min_clearance_margin=clearance_margin,
        low_stack=low_stack,
    )


__all__ = ["FutureFeatures", "compute_future_features"]
