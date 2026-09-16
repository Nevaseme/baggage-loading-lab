"""Pure immutable layered MaxRects proxy geometry.

The proxy is analytical ranking data only.  It models support layers,
protection columns, conservative ingress, and fixed work accounting without
constructing public simulator output.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import math
import struct
from typing import Callable, Iterable, Sequence

import numpy as np

from .geometry import (
    box_inside_planes,
    effective_transport_lift,
    oriented_dimensions,
    support_metrics,
    transport_path_clear,
)
from .model import AABB, ItemSpec, Rect
from .transition import SimState


_EPS = 1.0e-10
_PATCH_PROBE_BOUNDARY = object()


class ProxyExposureOrder(str, Enum):
    LEGACY_NESTED = "legacy_nested"
    STRATIFIED_LAYER_ORIENTATION = "stratified_layer_orientation"


@dataclass(frozen=True, order=True)
class ProtectionTag:
    prioritized: bool = False
    soft: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "prioritized", bool(self.prioritized))
        object.__setattr__(self, "soft", bool(self.soft))

    def allows(self, upper: "ProtectionTag") -> bool:
        if not isinstance(upper, ProtectionTag):
            return False
        return (
            (not self.prioritized or upper.prioritized)
            and (not self.soft or upper.soft)
        )

    @classmethod
    def from_item(cls, item: ItemSpec) -> "ProtectionTag":
        return cls(item.is_prioritized, item.is_soft)


@dataclass(frozen=True, order=True)
class OccurrenceKey:
    original_position: int
    item_index: int

    def __post_init__(self) -> None:
        if type(self.original_position) is not int or self.original_position < 0:
            raise ValueError("original_position must be an exact non-negative int")
        if type(self.item_index) is not int or self.item_index < 0:
            raise ValueError("item_index must be an exact non-negative int")


@dataclass(frozen=True)
class ProxyOccurrence:
    key: OccurrenceKey
    item: ItemSpec


@dataclass(frozen=True)
class SupportPatch:
    container_ordinal: int
    height: float
    footprint: Rect
    placement_offset: float
    tag: ProtectionTag | None
    source: str

    @property
    def placement_bottom(self) -> float:
        return float(self.height + self.placement_offset)


@dataclass(frozen=True)
class ProxyBox:
    box: AABB
    item: ItemSpec | None
    tag: ProtectionTag | None
    occurrence: OccurrenceKey | None
    is_proxy: bool = False


@dataclass(frozen=True)
class ProxyContainer:
    ordinal: int
    length: float
    width: float
    height: float
    thickness: float
    buffer: float
    cut_x: float
    center_z: float
    is_prioritized: bool
    points: tuple[tuple[float, float, float], ...]
    normals: tuple[tuple[float, float, float], ...]
    supports: tuple[SupportPatch, ...]
    boxes: tuple[ProxyBox, ...]

    @property
    def inner_floor(self) -> Rect:
        return Rect(
            -self.length / 2.0 + self.thickness,
            self.length / 2.0 - self.thickness,
            -self.width / 2.0 + self.thickness,
            self.width / 2.0 - self.thickness,
        )

    @property
    def inner_ceiling(self) -> float:
        return self.height + self.buffer - self.thickness


@dataclass(frozen=True)
class ProxyWorkQuota:
    max_nodes: int = 768
    max_fit_tests: int = 96_000
    max_candidates: int = 512
    max_rectangles_per_patch: int = 128

    def __post_init__(self) -> None:
        for name in (
            "max_nodes",
            "max_fit_tests",
            "max_candidates",
            "max_rectangles_per_patch",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive exact int")


@dataclass(frozen=True)
class ProxyWork:
    nodes: int = 0
    fit_tests: int = 0
    candidates: int = 0

    def __post_init__(self) -> None:
        for name in ("nodes", "fit_tests", "candidates"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be an exact non-negative int")

    def consume_node(self, quota: ProxyWorkQuota) -> "ProxyWork":
        if self.nodes >= quota.max_nodes:
            raise RuntimeError("proxy node quota exhausted")
        return replace(self, nodes=self.nodes + 1)

    def consume_fit(self, quota: ProxyWorkQuota) -> "ProxyWork":
        if self.fit_tests >= quota.max_fit_tests:
            raise RuntimeError("proxy fit-test quota exhausted")
        return replace(self, fit_tests=self.fit_tests + 1)

    def consume_candidate(self, quota: ProxyWorkQuota) -> "ProxyWork":
        if self.candidates >= quota.max_candidates:
            raise RuntimeError("proxy candidate quota exhausted")
        return replace(self, candidates=self.candidates + 1)

    def quota_exhausted(self, quota: ProxyWorkQuota) -> bool:
        return (
            self.nodes >= quota.max_nodes
            or self.fit_tests >= quota.max_fit_tests
            or self.candidates >= quota.max_candidates
        )


@dataclass(frozen=True)
class ProxyCandidate:
    occurrence: OccurrenceKey
    item_index: int
    container_ordinal: int
    orientation: int
    position: tuple[float, float, float]
    box: AABB
    support_ratio: float
    min_clearance: float
    anchor: str
    support_source: str
    state_fingerprint: str


@dataclass(frozen=True)
class ProxyCandidateBatch:
    candidates: tuple[ProxyCandidate, ...]
    work: ProxyWork
    attempted_fit_tests: int


@dataclass(frozen=True)
class _ProxyFitSpec:
    container_ordinal: int
    patch_index: int
    orientation: int
    position: tuple[float, float, float]
    anchor: str


@dataclass(frozen=True)
class ProxyMetrics:
    ingress_access: float
    largest_free_region: float
    sliver_area: float
    low_mass_cog_goodness: float
    low_stack: float
    compatible_support_capacity: float
    protection_compatible_capacity: float


_CHECKED_TRANSITION_TOKEN = object()
_CACHE_ISSUANCE_AUTHORITY = object()


@dataclass(frozen=True)
class CheckedProxyTransition:
    """One state-bound proxy transition issued during a single select call."""

    parent_fingerprint: str
    candidate: ProxyCandidate
    child_state: "LayeredProxyState"
    child_metrics: ProxyMetrics
    maxrect_waste: tuple[float, float, float]
    local_cost_inputs: tuple[float, float, float, float]
    _proof: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._proof is not _CHECKED_TRANSITION_TOKEN:
            raise TypeError("checked transitions are issued only by LayeredProxy")
        if type(self.parent_fingerprint) is not str or not self.parent_fingerprint:
            raise ValueError("parent fingerprint must be non-empty")
        if type(self.candidate) is not ProxyCandidate:
            raise TypeError("candidate must be a ProxyCandidate")
        if type(self.child_state) is not LayeredProxyState:
            raise TypeError("child_state must be a LayeredProxyState")
        if type(self.child_metrics) is not ProxyMetrics:
            raise TypeError("child_metrics must be ProxyMetrics")
        values = (*self.maxrect_waste, *self.local_cost_inputs)
        if len(self.maxrect_waste) != 3 or len(self.local_cost_inputs) != 4:
            raise ValueError("checked transition metric tuples have fixed shapes")
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("checked transition metrics must be finite")


@dataclass(frozen=True)
class CheckedProxyCandidateBatch:
    transitions: tuple[CheckedProxyTransition, ...]
    work: ProxyWork
    attempted_fit_tests: int


class ProxyTopologyCache:
    """Select-local cache for exact state/support/obstacle topology values."""

    def __init__(self) -> None:
        self._rectangles: dict[tuple, tuple[Rect, ...]] = {}
        self.__issuance_capability = object()
        self._issued: dict[
            int, tuple[CheckedProxyTransition, tuple, object, "ProxyTopologyCache"]
        ] = {}
        self.hits = 0
        self.misses = 0

    def __repr__(self) -> str:
        return (
            "ProxyTopologyCache("
            f"hits={self.hits}, misses={self.misses}, issued={len(self._issued)})"
        )

    def __copy__(self):
        raise TypeError("ProxyTopologyCache is select-local and cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("ProxyTopologyCache is select-local and cannot be deep-copied")

    def __reduce__(self):
        raise TypeError("ProxyTopologyCache cannot be serialized")

    def __reduce_ex__(self, _protocol):
        raise TypeError("ProxyTopologyCache cannot be serialized")

    def rectangles(
        self,
        key: tuple,
        factory: Callable[[], tuple[Rect, ...]],
    ) -> tuple[Rect, ...]:
        if type(key) is not tuple:
            raise TypeError("topology cache keys must be exact tuples")
        if key in self._rectangles:
            self.hits += 1
            return self._rectangles[key]
        value = tuple(factory())
        self._rectangles[key] = value
        self.misses += 1
        return value

    def _capability(self, authority: object) -> object:
        if authority is not _CACHE_ISSUANCE_AUTHORITY:
            raise TypeError("cache issuance capability is module-private")
        return self.__issuance_capability

    def _accept_issued(
        self,
        transition: CheckedProxyTransition,
        seal: object,
        authority: object,
    ) -> None:
        if authority is not _CACHE_ISSUANCE_AUTHORITY:
            raise TypeError("cache registration is module-private")
        if type(transition) is not CheckedProxyTransition:
            raise TypeError("only exact checked transitions can be issued")
        if (
            getattr(transition, "_issuer_capability", None)
            is not self.__issuance_capability
            or getattr(transition, "_issuer_seal", None) is not seal
        ):
            raise ValueError("transition receipt is not bound to this cache")
        self._issued[id(transition)] = (
            transition,
            _transition_signature(transition),
            seal,
            self,
        )

    def owns_unchanged(self, transition: CheckedProxyTransition) -> bool:
        if type(transition) is not CheckedProxyTransition:
            return False
        issued = self._issued.get(id(transition))
        return bool(
            issued is not None
            and issued[0] is transition
            and issued[1] == _transition_signature(transition)
            and issued[2] is getattr(transition, "_issuer_seal", None)
            and issued[3] is self
            and getattr(transition, "_issuer_capability", None)
            is self.__issuance_capability
        )


def _candidate_signature(candidate: ProxyCandidate) -> tuple:
    if type(candidate) is not ProxyCandidate:
        raise TypeError("checked candidate must have exact ProxyCandidate type")
    if type(candidate.occurrence) is not OccurrenceKey:
        raise TypeError("checked candidate occurrence has the wrong type")
    for name in ("item_index", "container_ordinal", "orientation"):
        if type(getattr(candidate, name)) is not int:
            raise TypeError(f"checked candidate {name} must be an exact int")
    if (
        type(candidate.position) is not tuple
        or len(candidate.position) != 3
        or any(type(value) is not float for value in candidate.position)
    ):
        raise TypeError("checked candidate position must be an exact float tuple")
    if type(candidate.box) is not AABB:
        raise TypeError("checked candidate box must have exact AABB type")
    for vector in (candidate.box.minimum, candidate.box.maximum):
        if (
            type(vector) is not np.ndarray
            or vector.dtype != np.dtype(np.float64)
            or vector.shape != (3,)
            or not vector.flags.c_contiguous
            or vector.flags.writeable
        ):
            raise TypeError("checked candidate AABB vector violates its exact contract")
    if type(candidate.box.axis_aligned) is not bool:
        raise TypeError("checked candidate alignment must be an exact bool")
    for name in ("support_ratio", "min_clearance"):
        if type(getattr(candidate, name)) is not float:
            raise TypeError(f"checked candidate {name} must be an exact float")
    for name in ("anchor", "support_source", "state_fingerprint"):
        if type(getattr(candidate, name)) is not str:
            raise TypeError(f"checked candidate {name} must be an exact str")
    return (
        candidate.occurrence,
        candidate.item_index,
        candidate.container_ordinal,
        candidate.orientation,
        candidate.position,
        tuple(float(value) for value in candidate.box.minimum),
        tuple(float(value) for value in candidate.box.maximum),
        candidate.box.axis_aligned,
        candidate.support_ratio,
        candidate.min_clearance,
        candidate.anchor,
        candidate.support_source,
        candidate.state_fingerprint,
    )


def _transition_signature(transition: CheckedProxyTransition) -> tuple:
    if type(transition) is not CheckedProxyTransition:
        raise TypeError("checked transition must have exact type")
    if type(transition.parent_fingerprint) is not str:
        raise TypeError("checked transition parent fingerprint must be exact str")
    if type(transition.child_state) is not LayeredProxyState:
        raise TypeError("checked transition child state has the wrong type")
    if type(transition.child_state.fingerprint) is not str:
        raise TypeError("checked transition child fingerprint must be exact str")
    if type(transition.child_metrics) is not ProxyMetrics:
        raise TypeError("checked transition metrics have the wrong type")
    metric_values = tuple(vars(transition.child_metrics).values())
    if any(type(value) is not float for value in metric_values):
        raise TypeError("checked transition metrics must be exact floats")
    for name, values, expected in (
        ("maxrect_waste", transition.maxrect_waste, 3),
        ("local_cost_inputs", transition.local_cost_inputs, 4),
    ):
        if (
            type(values) is not tuple
            or len(values) != expected
            or any(type(value) is not float for value in values)
        ):
            raise TypeError(f"checked transition {name} violates its exact tuple contract")
    return (
        transition.parent_fingerprint,
        _candidate_signature(transition.candidate),
        transition.child_state.fingerprint,
        _state_digest(
            transition.child_state.containers,
            transition.child_state.remaining,
        ),
        metric_values,
        transition.maxrect_waste,
        transition.local_cost_inputs,
        transition._proof is _CHECKED_TRANSITION_TOKEN,
    )


def _issue_checked_transition(
    *,
    topology_cache: ProxyTopologyCache,
    parent_fingerprint: str,
    candidate: ProxyCandidate,
    child_state: "LayeredProxyState",
    child_metrics: ProxyMetrics,
    maxrect_waste: tuple[float, float, float],
    local_cost_inputs: tuple[float, float, float, float],
) -> CheckedProxyTransition:
    """Atomically construct and bind one receipt to its select-local cache."""

    if type(topology_cache) is not ProxyTopologyCache:
        raise TypeError("checked receipt issuer must be exact ProxyTopologyCache")
    transition = CheckedProxyTransition(
        parent_fingerprint=parent_fingerprint,
        candidate=candidate,
        child_state=child_state,
        child_metrics=child_metrics,
        maxrect_waste=maxrect_waste,
        local_cost_inputs=local_cost_inputs,
        _proof=_CHECKED_TRANSITION_TOKEN,
    )
    seal = object()
    object.__setattr__(
        transition,
        "_issuer_capability",
        topology_cache._capability(_CACHE_ISSUANCE_AUTHORITY),
    )
    object.__setattr__(transition, "_issuer_seal", seal)
    topology_cache._accept_issued(
        transition,
        seal,
        _CACHE_ISSUANCE_AUTHORITY,
    )
    return transition


def _float_tuple(array: np.ndarray) -> tuple[tuple[float, float, float], ...]:
    value = np.asarray(array, dtype=np.float64)
    return tuple(tuple(float(component) for component in row) for row in value)


def _intersection(first: Rect, second: Rect) -> Rect | None:
    return first.intersection(second)


def _union_area(rectangles: Sequence[Rect]) -> float:
    valid = tuple(rect for rect in rectangles if rect.area > 0.0)
    if not valid:
        return 0.0
    xs = sorted({value for rect in valid for value in (rect.min_x, rect.max_x)})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted(
            (rect.min_y, rect.max_y)
            for rect in valid
            if rect.min_x < right - _EPS and rect.max_x > left + _EPS
        )
        if not intervals:
            continue
        start, end = intervals[0]
        covered = 0.0
        for next_start, next_end in intervals[1:]:
            if next_start <= end + _EPS:
                end = max(end, next_end)
            else:
                covered += end - start
                start, end = next_start, next_end
        covered += end - start
        area += (right - left) * covered
    return area


def maximal_empty_rectangles(
    base: Rect,
    blockers: Sequence[Rect],
    *,
    limit: int = 128,
) -> tuple[Rect, ...]:
    """Reconstruct maximal free rectangles from obstacle coordinates.

    Row-band union avoids treating artificial cell boundaries as physical
    partitions.  The result is deterministic and capped.
    """

    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive exact int")
    clipped = tuple(
        intersection
        for blocker in blockers
        if (intersection := _intersection(base, blocker)) is not None
    )
    xs = tuple(sorted({base.min_x, base.max_x} | {
        coordinate for rect in clipped for coordinate in (rect.min_x, rect.max_x)
    }))
    ys = tuple(sorted({base.min_y, base.max_y} | {
        coordinate for rect in clipped for coordinate in (rect.min_y, rect.max_y)
    }))
    if len(xs) < 2 or len(ys) < 2:
        return ()
    free = [
        [
            not any(
                rect.min_x < xs[column + 1] - _EPS
                and rect.max_x > xs[column] + _EPS
                and rect.min_y < ys[row + 1] - _EPS
                and rect.max_y > ys[row] + _EPS
                for rect in clipped
            )
            for column in range(len(xs) - 1)
        ]
        for row in range(len(ys) - 1)
    ]
    found: set[Rect] = set()
    columns = len(xs) - 1
    for row_start in range(len(ys) - 1):
        common = [True] * columns
        for row_end in range(row_start, len(ys) - 1):
            for column in range(columns):
                common[column] = common[column] and free[row_end][column]
            column = 0
            while column < columns:
                while column < columns and not common[column]:
                    column += 1
                start = column
                while column < columns and common[column]:
                    column += 1
                if start < column:
                    found.add(
                        Rect(xs[start], xs[column], ys[row_start], ys[row_end + 1])
                    )
    values = sorted(found, key=lambda rect: (-rect.area, rect.min_y, rect.min_x, rect.max_y, rect.max_x))
    maximal = [
        rect
        for rect in values
        if not any(
            other != rect
            and other.min_x <= rect.min_x + _EPS
            and other.max_x >= rect.max_x - _EPS
            and other.min_y <= rect.min_y + _EPS
            and other.max_y >= rect.max_y - _EPS
            for other in values
        )
    ]
    return tuple(maximal[:limit])


def _state_digest(
    containers: Sequence[ProxyContainer],
    remaining: Sequence[ProxyOccurrence],
) -> str:
    digest = hashlib.sha256()

    def marker(value: bytes) -> None:
        digest.update(struct.pack("!I", len(value)))
        digest.update(value)

    def integer(value: int) -> None:
        if type(value) is not int:
            raise TypeError("canonical digest integers must be exact ints")
        marker(b"int")
        digest.update(struct.pack("!q", int(value)))

    def number(value: float) -> None:
        if type(value) is not float:
            raise TypeError("canonical digest numbers must be exact Python floats")
        marker(b"float64")
        digest.update(struct.pack("!d", value))

    def boolean(value: bool) -> None:
        if type(value) is not bool:
            raise TypeError("canonical digest booleans must be exact bools")
        marker(b"bool")
        digest.update(b"\x01" if value else b"\x00")

    def text(value: str) -> None:
        if type(value) is not str:
            raise TypeError("canonical digest text must be exact str")
        marker(b"str")
        encoded = value.encode("utf-8")
        integer(len(encoded))
        digest.update(encoded)

    def optional(value: object, writer: Callable[[object], None]) -> None:
        if value is None:
            marker(b"none")
            return
        marker(b"some")
        writer(value)

    def coordinates(value: tuple[float, ...], expected: int, name: str) -> None:
        if type(value) is not tuple:
            raise TypeError(f"{name} must be an exact tuple")
        marker(name.encode("ascii"))
        integer(len(value))
        if len(value) != expected:
            raise ValueError(f"{name} must contain {expected} values")
        for component in value:
            number(component)

    def protection_tag(value: object) -> None:
        if type(value) is not ProtectionTag:
            raise TypeError("protection tag has the wrong type")
        marker(b"ProtectionTag")
        boolean(value.prioritized)
        boolean(value.soft)

    def occurrence_key(value: object) -> None:
        if type(value) is not OccurrenceKey:
            raise TypeError("occurrence key has the wrong type")
        marker(b"OccurrenceKey")
        integer(value.original_position)
        integer(value.item_index)

    def rectangle(value: object) -> None:
        if type(value) is not Rect:
            raise TypeError("rectangle has the wrong type")
        marker(b"Rect")
        number(value.min_x)
        number(value.max_x)
        number(value.min_y)
        number(value.max_y)

    def aabb(value: object) -> None:
        if type(value) is not AABB:
            raise TypeError("AABB has the wrong type")
        marker(b"AABB")
        for name, vector in ((b"minimum", value.minimum), (b"maximum", value.maximum)):
            marker(name)
            if type(vector) is not np.ndarray:
                raise TypeError("canonical AABB vectors must be exact ndarrays")
            if vector.dtype != np.dtype(np.float64):
                raise TypeError("canonical AABB vectors must use float64 dtype")
            if vector.shape != (3,) or not vector.flags.c_contiguous:
                raise ValueError("canonical AABB vectors must be C-contiguous shape (3,)")
            if vector.flags.writeable:
                raise ValueError("canonical AABB vectors must be read-only")
            integer(3)
            for component in vector:
                number(float(component))
        boolean(value.axis_aligned)

    def item_spec(value: object) -> None:
        if type(value) is not ItemSpec:
            raise TypeError("item has the wrong type")
        marker(b"ItemSpec")
        integer(value.index)
        number(value.length)
        number(value.width)
        number(value.height)
        number(value.mass)
        boolean(value.is_prioritized)
        boolean(value.is_soft)
        optional(value.belongs_to, lambda item: integer(item))
        optional(value.pos, lambda item: coordinates(item, 3, "position"))
        optional(value.orn, lambda item: coordinates(item, 4, "orientation"))

    def support_patch(value: object) -> None:
        if type(value) is not SupportPatch:
            raise TypeError("support patch has the wrong type")
        marker(b"SupportPatch")
        integer(value.container_ordinal)
        number(value.height)
        rectangle(value.footprint)
        number(value.placement_offset)
        optional(value.tag, protection_tag)
        text(value.source)

    def proxy_box(value: object) -> None:
        if type(value) is not ProxyBox:
            raise TypeError("proxy box has the wrong type")
        marker(b"ProxyBox")
        aabb(value.box)
        optional(value.item, item_spec)
        optional(value.tag, protection_tag)
        optional(value.occurrence, occurrence_key)
        boolean(value.is_proxy)

    if type(containers) is not tuple:
        raise TypeError("proxy containers must be an exact tuple")
    if type(remaining) is not tuple:
        raise TypeError("remaining occurrences must be an exact tuple")
    integer(len(containers))
    for container in containers:
        if type(container) is not ProxyContainer:
            raise TypeError("proxy container has the wrong type")
        marker(b"ProxyContainer")
        integer(container.ordinal)
        for value in (
            container.length,
            container.width,
            container.height,
            container.thickness,
            container.buffer,
            container.cut_x,
            container.center_z,
        ):
            number(value)
        boolean(container.is_prioritized)
        for name, rows in ((b"points", container.points), (b"normals", container.normals)):
            marker(name)
            if type(rows) is not tuple:
                raise TypeError("container geometry rows must be exact tuples")
            integer(len(rows))
            for row in rows:
                if type(row) is not tuple:
                    raise TypeError("container geometry row must be an exact tuple")
                integer(len(row))
                for value in row:
                    number(value)
        if type(container.supports) is not tuple:
            raise TypeError("container supports must be an exact tuple")
        if type(container.boxes) is not tuple:
            raise TypeError("container boxes must be an exact tuple")
        integer(len(container.supports))
        for patch in container.supports:
            support_patch(patch)
        integer(len(container.boxes))
        for value in container.boxes:
            proxy_box(value)
    integer(len(remaining))
    for occurrence in remaining:
        if type(occurrence) is not ProxyOccurrence:
            raise TypeError("remaining occurrence has the wrong type")
        marker(b"ProxyOccurrence")
        occurrence_key(occurrence.key)
        item_spec(occurrence.item)
    return digest.hexdigest()


@dataclass(frozen=True)
class LayeredProxyState:
    containers: tuple[ProxyContainer, ...]
    remaining: tuple[ProxyOccurrence, ...]
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if type(self.containers) is not tuple or type(self.remaining) is not tuple:
            raise ValueError("proxy state collections must be tuples")
        if type(self.fingerprint) is not str:
            raise TypeError("proxy state fingerprint must be an exact str")
        expected = _state_digest(self.containers, self.remaining)
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("proxy state fingerprint does not match contents")
        object.__setattr__(self, "fingerprint", expected)


class LayeredProxy:
    """Deterministic layered proxy engine with fixed analytical work."""

    def __init__(
        self,
        *,
        inclusion_margin: float = -0.008,
        horizontal_clearance: float = 0.018,
        floor_offset: float = 0.008,
        shelf_offset: float = 0.022,
        rigid_support_ratio: float = 0.75,
        soft_support_ratio: float = 0.90,
        center_core_margin: float = 0.02,
    ) -> None:
        values = (
            inclusion_margin,
            horizontal_clearance,
            floor_offset,
            shelf_offset,
            rigid_support_ratio,
            soft_support_ratio,
            center_core_margin,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("proxy geometry parameters must be finite")
        self.inclusion_margin = float(inclusion_margin)
        self.horizontal_clearance = float(horizontal_clearance)
        self.floor_offset = float(floor_offset)
        self.shelf_offset = float(shelf_offset)
        self.rigid_support_ratio = float(rigid_support_ratio)
        self.soft_support_ratio = float(soft_support_ratio)
        self.center_core_margin = float(center_core_margin)

    def from_sim_state(self, sim: SimState) -> LayeredProxyState:
        if not isinstance(sim, SimState):
            raise TypeError("sim must be a SimState")
        containers: list[ProxyContainer] = []
        for ordinal, source in enumerate(sim.packing.containers):
            floor = SupportPatch(
                ordinal,
                source.thickness + source.buffer,
                Rect(
                    -source.length / 2.0 + source.thickness,
                    source.length / 2.0 - source.thickness,
                    -source.width / 2.0 + source.thickness,
                    source.width / 2.0 - source.thickness,
                ),
                self.floor_offset,
                None,
                "floor",
            )
            supports: list[SupportPatch] = [floor]
            boxes: list[ProxyBox] = []
            for obstacle in source.static_obstacles:
                copied = AABB(obstacle.minimum.copy(), obstacle.maximum.copy(), obstacle.axis_aligned)
                boxes.append(ProxyBox(copied, None, None, None, False))
                if copied.axis_aligned:
                    supports.append(
                        SupportPatch(
                            ordinal,
                            float(copied.maximum[2]),
                            copied.footprint,
                            self.shelf_offset,
                            None,
                            "shelf",
                        )
                    )
            for placed in source.placed:
                copied = AABB(
                    placed.box.minimum.copy(),
                    placed.box.maximum.copy(),
                    placed.box.axis_aligned,
                )
                tag = ProtectionTag.from_item(placed.item)
                boxes.append(ProxyBox(copied, placed.item, tag, None, False))
                if copied.axis_aligned:
                    supports.append(
                        SupportPatch(
                            ordinal,
                            float(copied.maximum[2]),
                            copied.footprint,
                            0.0,
                            tag,
                            "placed_top",
                        )
                    )
            containers.append(
                ProxyContainer(
                    ordinal=ordinal,
                    length=source.length,
                    width=source.width,
                    height=source.height,
                    thickness=source.thickness,
                    buffer=source.buffer,
                    cut_x=source.cut_x,
                    center_z=source.center[2],
                    is_prioritized=source.is_prioritized,
                    points=_float_tuple(source.points),
                    normals=_float_tuple(source.normals),
                    supports=tuple(supports),
                    boxes=tuple(boxes),
                )
            )
        remaining = tuple(
            ProxyOccurrence(
                OccurrenceKey(original_position, item.index),
                item,
            )
            for original_position, item in zip(
                sim.original_pool_positions, sim.pool
            )
        )
        return LayeredProxyState(tuple(containers), remaining)

    @staticmethod
    def orientation_options(item: ItemSpec) -> tuple[tuple[int, tuple[float, float, float]], ...]:
        if not isinstance(item, ItemSpec):
            raise TypeError("item must be an ItemSpec")
        seen: set[tuple[float, float, float]] = set()
        result: list[tuple[int, tuple[float, float, float]]] = []
        for orientation in range(6):
            dimensions = oriented_dimensions(item.dimensions, orientation)
            key = tuple(round(value, 12) for value in dimensions)
            if key in seen:
                continue
            seen.add(key)
            result.append((orientation, dimensions))
        return tuple(result)

    @staticmethod
    def _occurrence(state: LayeredProxyState, key: OccurrenceKey) -> ProxyOccurrence:
        matches = tuple(value for value in state.remaining if value.key == key)
        if len(matches) != 1:
            raise ValueError("occurrence key is stale or ambiguous")
        return matches[0]

    def enumerate_candidates(
        self,
        state: LayeredProxyState,
        key: OccurrenceKey,
        work: ProxyWork,
        quota: ProxyWorkQuota,
        *,
        exposure_order: ProxyExposureOrder = ProxyExposureOrder.LEGACY_NESTED,
    ) -> ProxyCandidateBatch:
        candidates, current, attempted, _transitions = self._enumerate_values(
            state, key, work, quota, None, None, exposure_order
        )
        return ProxyCandidateBatch(candidates, current, attempted)

    def preview_candidates(
        self,
        state: LayeredProxyState,
        key: OccurrenceKey,
        work: ProxyWork,
        quota: ProxyWorkQuota,
        before_metrics: ProxyMetrics,
        topology_cache: ProxyTopologyCache,
        *,
        exposure_order: ProxyExposureOrder = ProxyExposureOrder.LEGACY_NESTED,
    ) -> CheckedProxyCandidateBatch:
        if type(state) is not LayeredProxyState:
            raise TypeError("state must be exact LayeredProxyState")
        if type(state.fingerprint) is not str:
            raise TypeError("state fingerprint must be an exact str")
        if _state_digest(state.containers, state.remaining) != state.fingerprint:
            raise ValueError("state fingerprint does not match contents")
        if type(key) is not OccurrenceKey:
            raise TypeError("key must be exact OccurrenceKey")
        if type(work) is not ProxyWork:
            raise TypeError("work must be exact ProxyWork")
        if type(quota) is not ProxyWorkQuota:
            raise TypeError("quota must be exact ProxyWorkQuota")
        for name in ("nodes", "fit_tests", "candidates"):
            value = getattr(work, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"work {name} must be an exact non-negative int")
        for name in (
            "max_nodes",
            "max_fit_tests",
            "max_candidates",
            "max_rectangles_per_patch",
        ):
            value = getattr(quota, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"quota {name} must be an exact positive int")
        if type(before_metrics) is not ProxyMetrics:
            raise TypeError("before_metrics must be ProxyMetrics")
        if any(
            type(value) is not float or not math.isfinite(value)
            for value in vars(before_metrics).values()
        ):
            raise ValueError("before_metrics must contain exact finite floats")
        if type(topology_cache) is not ProxyTopologyCache:
            raise TypeError("topology_cache must be select-local ProxyTopologyCache")
        if type(exposure_order) is not ProxyExposureOrder:
            raise TypeError("exposure_order must be exact ProxyExposureOrder")
        _candidates, current, attempted, transitions = self._enumerate_values(
            state,
            key,
            work,
            quota,
            before_metrics,
            topology_cache,
            exposure_order,
        )
        return CheckedProxyCandidateBatch(transitions, current, attempted)

    def _enumerate_values(
        self,
        state: LayeredProxyState,
        key: OccurrenceKey,
        work: ProxyWork,
        quota: ProxyWorkQuota,
        before_metrics: ProxyMetrics | None,
        topology_cache: ProxyTopologyCache | None,
        exposure_order: ProxyExposureOrder,
    ) -> tuple[
        tuple[ProxyCandidate, ...],
        ProxyWork,
        int,
        tuple[CheckedProxyTransition, ...],
    ]:
        if type(exposure_order) is not ProxyExposureOrder:
            raise TypeError("exposure_order must be exact ProxyExposureOrder")
        if exposure_order is ProxyExposureOrder.STRATIFIED_LAYER_ORIENTATION:
            return self._enumerate_stratified_values(
                state,
                key,
                work,
                quota,
                before_metrics,
                topology_cache,
            )
        occurrence = self._occurrence(state, key)
        current = work
        started = work.fit_tests
        candidates: list[ProxyCandidate] = []
        transitions: list[CheckedProxyTransition] = []
        seen: set[tuple] = set()
        exhausted = False
        for container in state.containers:
            for patch_index, patch in enumerate(container.supports):
                bottom = patch.placement_bottom
                same_layer_blockers = tuple(
                    box.box.footprint
                    for box in container.boxes
                    if box.box.maximum[2] > patch.height + _EPS
                    and box.box.minimum[2] <= bottom + 0.001
                    and patch.footprint.intersection(box.box.footprint) is not None
                )
                rectangles = self._topology_rectangles(
                    state,
                    container,
                    patch,
                    same_layer_blockers,
                    quota.max_rectangles_per_patch,
                    topology_cache,
                )
                for orientation, dimensions in self.orientation_options(occurrence.item):
                    dx, dy, dz = dimensions
                    for rectangle in rectangles:
                        inset = max(0.0, -self.inclusion_margin)
                        if dx + 2.0 * inset > rectangle.max_x - rectangle.min_x + _EPS or dy + 2.0 * inset > rectangle.max_y - rectangle.min_y + _EPS:
                            continue
                        anchors = (
                            ("back", (rectangle.min_x + rectangle.max_x) * 0.5, rectangle.max_y - dy / 2.0 - inset),
                            ("front", (rectangle.min_x + rectangle.max_x) * 0.5, rectangle.min_y + dy / 2.0 + inset),
                            ("left", rectangle.min_x + dx / 2.0 + inset, (rectangle.min_y + rectangle.max_y) * 0.5),
                            ("right", rectangle.max_x - dx / 2.0 - inset, (rectangle.min_y + rectangle.max_y) * 0.5),
                            ("back_left", rectangle.min_x + dx / 2.0 + inset, rectangle.max_y - dy / 2.0 - inset),
                            ("back_right", rectangle.max_x - dx / 2.0 - inset, rectangle.max_y - dy / 2.0 - inset),
                            ("front_left", rectangle.min_x + dx / 2.0 + inset, rectangle.min_y + dy / 2.0 + inset),
                            ("front_right", rectangle.max_x - dx / 2.0 - inset, rectangle.min_y + dy / 2.0 + inset),
                        )
                        for anchor, x, y in anchors:
                            if current.fit_tests >= quota.max_fit_tests or current.candidates >= quota.max_candidates:
                                exhausted = True
                                break
                            position = (x, y, bottom + dz / 2.0)
                            candidate_key = (
                                container.ordinal,
                                orientation,
                                tuple(round(value, 8) for value in position),
                            )
                            if candidate_key in seen:
                                continue
                            seen.add(candidate_key)
                            current = current.consume_fit(quota)
                            candidate = self._check(
                                state,
                                occurrence,
                                container.ordinal,
                                orientation,
                                position,
                                anchor,
                                patch_index,
                            )
                            if candidate is None:
                                continue
                            current = current.consume_candidate(quota)
                            candidates.append(candidate)
                            if topology_cache is not None and before_metrics is not None:
                                transitions.append(
                                    self._build_checked_transition(
                                        state,
                                        candidate,
                                        before_metrics,
                                        topology_cache,
                                    )
                                )
                        if exhausted:
                            break
                    if exhausted:
                        break
                if exhausted:
                    break
            if exhausted:
                break
        if not exhausted:
            ordering = lambda value: (
                value.container_ordinal,
                value.orientation,
                -value.position[1],
                value.position[0],
                value.anchor,
            )
            candidates.sort(key=ordering)
            transitions.sort(key=lambda value: ordering(value.candidate))
        return (
            tuple(candidates),
            current,
            current.fit_tests - started,
            tuple(transitions),
        )

    def _enumerate_stratified_values(
        self,
        state: LayeredProxyState,
        key: OccurrenceKey,
        work: ProxyWork,
        quota: ProxyWorkQuota,
        before_metrics: ProxyMetrics | None,
        topology_cache: ProxyTopologyCache | None,
    ) -> tuple[
        tuple[ProxyCandidate, ...],
        ProxyWork,
        int,
        tuple[CheckedProxyTransition, ...],
    ]:
        occurrence = self._occurrence(state, key)
        source_rank = {
            "floor": 0,
            "shelf": 1,
            "placed_top": 2,
            "proxy_top": 3,
        }
        orientation_values = self.orientation_options(occurrence.item)
        orientation_rank = {
            orientation: rank
            for rank, (orientation, _dimensions) in enumerate(orientation_values)
        }
        grouped: dict[
            tuple[int, str, int],
            list[
                tuple[
                    ProxyContainer,
                    int,
                    SupportPatch,
                    int,
                    tuple[float, float, float],
                ]
            ],
        ] = {}
        container_rank: dict[int, int] = {}
        for rank, container in enumerate(state.containers):
            container_rank[container.ordinal] = rank
            for patch_index, patch in enumerate(container.supports):
                for orientation, dimensions in orientation_values:
                    bucket = (container.ordinal, patch.source, orientation)
                    grouped.setdefault(bucket, []).append(
                        (
                            container,
                            patch_index,
                            patch,
                            orientation,
                            dimensions,
                        )
                    )

        topology_probe_limit = max(0, quota.max_fit_tests - work.fit_tests)
        topology_probes = 0

        def bucket_order(bucket: tuple[int, str, int]) -> tuple:
            container_ordinal, source, orientation = bucket
            c_rank = container_rank[container_ordinal]
            s_rank = source_rank.get(source, len(source_rank))
            o_rank = orientation_rank[orientation]
            return (
                c_rank + s_rank + o_rank,
                o_rank,
                s_rank,
                c_rank,
                container_ordinal,
                source,
                orientation,
            )

        def specs(entries):
            nonlocal topology_probes
            for (
                container,
                patch_index,
                patch,
                orientation,
                dimensions,
            ) in entries:
                if topology_probes >= topology_probe_limit:
                    return
                topology_probes += 1
                dx, dy, dz = dimensions
                bottom = patch.placement_bottom
                same_layer_blockers = tuple(
                    box.box.footprint
                    for box in container.boxes
                    if box.box.maximum[2] > patch.height + _EPS
                    and box.box.minimum[2] <= bottom + 0.001
                    and patch.footprint.intersection(box.box.footprint) is not None
                )
                rectangles = self._topology_rectangles(
                    state,
                    container,
                    patch,
                    same_layer_blockers,
                    quota.max_rectangles_per_patch,
                    topology_cache,
                )
                for rectangle in rectangles:
                    inset = max(0.0, -self.inclusion_margin)
                    if (
                        dx + 2.0 * inset
                        > rectangle.max_x - rectangle.min_x + _EPS
                        or dy + 2.0 * inset
                        > rectangle.max_y - rectangle.min_y + _EPS
                    ):
                        continue
                    anchors = (
                        ("back", (rectangle.min_x + rectangle.max_x) * 0.5, rectangle.max_y - dy / 2.0 - inset),
                        ("front", (rectangle.min_x + rectangle.max_x) * 0.5, rectangle.min_y + dy / 2.0 + inset),
                        ("left", rectangle.min_x + dx / 2.0 + inset, (rectangle.min_y + rectangle.max_y) * 0.5),
                        ("right", rectangle.max_x - dx / 2.0 - inset, (rectangle.min_y + rectangle.max_y) * 0.5),
                        ("back_left", rectangle.min_x + dx / 2.0 + inset, rectangle.max_y - dy / 2.0 - inset),
                        ("back_right", rectangle.max_x - dx / 2.0 - inset, rectangle.max_y - dy / 2.0 - inset),
                        ("front_left", rectangle.min_x + dx / 2.0 + inset, rectangle.min_y + dy / 2.0 + inset),
                        ("front_right", rectangle.max_x - dx / 2.0 - inset, rectangle.min_y + dy / 2.0 + inset),
                    )
                    for anchor, x, y in anchors:
                        yield _ProxyFitSpec(
                            container.ordinal,
                            patch_index,
                            orientation,
                            (x, y, bottom + dz / 2.0),
                            anchor,
                        )
                yield _PATCH_PROBE_BOUNDARY

        active = [
            (bucket, iter(specs(grouped[bucket])))
            for bucket in sorted(grouped, key=bucket_order)
        ]
        current = work
        started = work.fit_tests
        candidates: list[ProxyCandidate] = []
        transitions: list[CheckedProxyTransition] = []
        seen: set[tuple] = set()
        exhausted = False
        while active and not exhausted:
            next_active = []
            for bucket, iterator in active:
                if (
                    current.fit_tests >= quota.max_fit_tests
                    or current.candidates >= quota.max_candidates
                ):
                    exhausted = True
                    break
                spec = None
                reached_patch_boundary = False
                while True:
                    try:
                        value = next(iterator)
                    except StopIteration:
                        break
                    if value is _PATCH_PROBE_BOUNDARY:
                        reached_patch_boundary = True
                        break
                    candidate_key = (
                        value.container_ordinal,
                        value.orientation,
                        tuple(round(component, 8) for component in value.position),
                    )
                    if candidate_key in seen:
                        continue
                    seen.add(candidate_key)
                    spec = value
                    break
                if spec is None:
                    if reached_patch_boundary:
                        next_active.append((bucket, iterator))
                    continue
                next_active.append((bucket, iterator))
                current = current.consume_fit(quota)
                candidate = self._check(
                    state,
                    occurrence,
                    spec.container_ordinal,
                    spec.orientation,
                    spec.position,
                    spec.anchor,
                    spec.patch_index,
                )
                if candidate is None:
                    continue
                current = current.consume_candidate(quota)
                candidates.append(candidate)
                if topology_cache is not None and before_metrics is not None:
                    transitions.append(
                        self._build_checked_transition(
                            state,
                            candidate,
                            before_metrics,
                            topology_cache,
                        )
                    )
            active = next_active

        if not exhausted:
            ordering = lambda value: (
                value.container_ordinal,
                value.orientation,
                -value.position[1],
                value.position[0],
                value.anchor,
            )
            candidates.sort(key=ordering)
            transitions.sort(key=lambda value: ordering(value.candidate))
        return (
            tuple(candidates),
            current,
            current.fit_tests - started,
            tuple(transitions),
        )

    @staticmethod
    def _topology_rectangles(
        state: LayeredProxyState,
        container: ProxyContainer,
        patch: SupportPatch,
        blockers: Sequence[Rect],
        limit: int,
        topology_cache: ProxyTopologyCache | None,
    ) -> tuple[Rect, ...]:
        key = (
            state.fingerprint,
            container.ordinal,
            patch.height,
            patch.placement_offset,
            patch.source,
            tuple(vars(patch.footprint).values()),
            tuple(tuple(vars(value).values()) for value in blockers),
            int(limit),
        )
        factory = lambda: maximal_empty_rectangles(
            patch.footprint, blockers, limit=limit
        )
        return factory() if topology_cache is None else topology_cache.rectangles(key, factory)

    def _build_checked_transition(
        self,
        state: LayeredProxyState,
        candidate: ProxyCandidate,
        before_metrics: ProxyMetrics,
        topology_cache: ProxyTopologyCache,
    ) -> CheckedProxyTransition:
        child = self._materialize_candidate(state, candidate)
        after = self.metrics(child, topology_cache=topology_cache)
        waste = self.maxrect_waste(state, candidate, topology_cache=topology_cache)
        ingress_loss = max(0.0, before_metrics.ingress_access - after.ingress_access)
        protection_loss = max(
            0.0,
            before_metrics.protection_compatible_capacity
            - after.protection_compatible_capacity,
        )
        stack_cost = max(0.0, 1.0 - after.low_stack)
        floor = state.containers[candidate.container_ordinal].inner_floor
        span = max(_EPS, floor.max_y - floor.min_y)
        backness = min(
            1.0,
            max(0.0, (candidate.position[1] - floor.min_y) / span),
        )
        return _issue_checked_transition(
            topology_cache=topology_cache,
            parent_fingerprint=state.fingerprint,
            candidate=candidate,
            child_state=child,
            child_metrics=after,
            maxrect_waste=waste,
            local_cost_inputs=(
                ingress_loss,
                protection_loss,
                stack_cost,
                backness,
            ),
        )

    def check_candidate(
        self,
        state: LayeredProxyState,
        key: OccurrenceKey,
        container_ordinal: int,
        orientation: int,
        position: Sequence[float],
        work: ProxyWork,
        quota: ProxyWorkQuota,
    ) -> tuple[ProxyCandidate | None, ProxyWork]:
        occurrence = self._occurrence(state, key)
        current = work.consume_fit(quota)
        candidate = self._check(
            state,
            occurrence,
            int(container_ordinal),
            int(orientation),
            tuple(float(value) for value in position),
            "manual",
            None,
        )
        if candidate is not None:
            current = current.consume_candidate(quota)
        return candidate, current

    def _check(
        self,
        state: LayeredProxyState,
        occurrence: ProxyOccurrence,
        container_ordinal: int,
        orientation: int,
        position: tuple[float, float, float],
        anchor: str,
        patch_index: int | None,
    ) -> ProxyCandidate | None:
        if not 0 <= container_ordinal < len(state.containers):
            return None
        container = state.containers[container_ordinal]
        if occurrence.item.is_prioritized and any(value.is_prioritized for value in state.containers) and not container.is_prioritized:
            return None
        dimensions = oriented_dimensions(occurrence.item.dimensions, orientation)
        half = np.asarray(dimensions, dtype=np.float64) * 0.5
        if len(position) != 3 or not np.all(np.isfinite(position)):
            return None
        box = AABB.from_center_half(position, half)
        if not box_inside_planes(
            box.center,
            box.half,
            np.asarray(container.points, dtype=np.float64),
            np.asarray(container.normals, dtype=np.float64),
            self.inclusion_margin,
        ):
            return None
        obstacles = tuple(value.box for value in container.boxes)
        if any(self._collides(box, obstacle) for obstacle in obstacles):
            return None

        layers: list[tuple[SupportPatch, ...]] = []
        for patch in container.supports:
            if abs(float(box.minimum[2]) - patch.placement_bottom) > 0.001:
                continue
            target = next(
                (
                    group
                    for group in layers
                    if abs(group[0].placement_bottom - patch.placement_bottom) <= 0.001
                ),
                None,
            )
            if target is None:
                layers.append((patch,))
            else:
                index = layers.index(target)
                layers[index] = target + (patch,)
        upper_tag = ProtectionTag.from_item(occurrence.item)
        column_tags = tuple(
            value.tag
            for value in container.boxes
            if value.tag is not None
            and value.box.maximum[2] <= box.minimum[2] + 0.001
            and box.footprint.intersection(value.box.footprint) is not None
        )
        if any(not tag.allows(upper_tag) for tag in column_tags):
            return None
        accepted_ratio = 0.0
        accepted_source = ""
        for group in layers:
            intersecting = tuple(
                patch
                for patch in group
                if box.footprint.intersection(patch.footprint) is not None
            )
            if any(
                patch.tag is not None and not patch.tag.allows(upper_tag)
                for patch in intersecting
            ):
                continue
            ratio, core = support_metrics(
                box.footprint,
                tuple(patch.footprint for patch in intersecting),
                self.center_core_margin,
            )
            required = self.soft_support_ratio if occurrence.item.is_soft else self.rigid_support_ratio
            if ratio + _EPS >= required and core and ratio >= accepted_ratio:
                accepted_ratio = ratio
                accepted_source = "+".join(sorted({patch.source for patch in intersecting}))
        if not accepted_source:
            return None

        resting = tuple(
            patch.height
            for patch in container.supports
            if patch.source in {"floor", "shelf"}
        )
        lift = effective_transport_lift(
            bottom_z=float(box.minimum[2]),
            top_z=float(box.maximum[2]),
            resting_surfaces=resting,
            ceiling_surfaces=(container.inner_ceiling,),
            requested_lift=0.08,
            ceiling_margin=self.horizontal_clearance,
        )
        start_min = (
            -container.length / 2.0
            + container.thickness
            + container.cut_x
            + half[0]
            + 0.01
        )
        start_max = container.length / 2.0 - container.thickness - half[0] - 0.01
        if start_min > start_max:
            return None
        start_x = min(max(float(box.center[0]), start_min), start_max)
        if not transport_path_clear(
            box,
            obstacles,
            door_y=-container.width / 2.0 + half[1],
            start_x=start_x,
            lift=lift,
            clearance=self.horizontal_clearance,
        ):
            return None
        clearance = self._minimum_clearance(box, obstacles)
        return ProxyCandidate(
            occurrence=occurrence.key,
            item_index=occurrence.item.index,
            container_ordinal=container_ordinal,
            orientation=orientation,
            position=tuple(float(value) for value in position),
            box=box,
            support_ratio=accepted_ratio,
            min_clearance=clearance,
            anchor=anchor,
            support_source=accepted_source,
            state_fingerprint=state.fingerprint,
        )

    def _collides(self, candidate: AABB, obstacle: AABB) -> bool:
        if (
            candidate.maximum[2] <= obstacle.minimum[2] + _EPS
            or candidate.minimum[2] >= obstacle.maximum[2] - _EPS
        ):
            return False
        margin = self.horizontal_clearance
        separated_x = (
            candidate.maximum[0] + margin <= obstacle.minimum[0]
            or obstacle.maximum[0] + margin <= candidate.minimum[0]
        )
        separated_y = (
            candidate.maximum[1] + margin <= obstacle.minimum[1]
            or obstacle.maximum[1] + margin <= candidate.minimum[1]
        )
        return not (separated_x or separated_y)

    @staticmethod
    def _minimum_clearance(candidate: AABB, obstacles: Sequence[AABB]) -> float:
        distances: list[float] = []
        for obstacle in obstacles:
            if candidate.maximum[2] <= obstacle.minimum[2] or obstacle.maximum[2] <= candidate.minimum[2]:
                continue
            dx = max(
                float(obstacle.minimum[0] - candidate.maximum[0]),
                float(candidate.minimum[0] - obstacle.maximum[0]),
            )
            dy = max(
                float(obstacle.minimum[1] - candidate.maximum[1]),
                float(candidate.minimum[1] - obstacle.maximum[1]),
            )
            distances.append(max(dx, dy, 0.0))
        return min(distances, default=1.0)

    def apply(
        self,
        state: LayeredProxyState,
        candidate: ProxyCandidate,
    ) -> LayeredProxyState:
        if not isinstance(state, LayeredProxyState) or not isinstance(candidate, ProxyCandidate):
            raise TypeError("state and candidate must be proxy values")
        if candidate.state_fingerprint != state.fingerprint:
            raise ValueError("candidate is stale or foreign")
        occurrence = self._occurrence(state, candidate.occurrence)
        if occurrence.item.index != candidate.item_index:
            raise ValueError("candidate item binding does not match occurrence")
        try:
            fresh = self._check(
                state,
                occurrence,
                candidate.container_ordinal,
                candidate.orientation,
                candidate.position,
                candidate.anchor,
                None,
            )
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError("candidate failed fresh proxy validation") from error
        if fresh is None or not self._same_candidate(candidate, fresh):
            raise ValueError("candidate does not match fresh proxy validation")
        return self._materialize_candidate(state, fresh)

    def commit_transition(
        self,
        state: LayeredProxyState,
        transition: CheckedProxyTransition,
        topology_cache: ProxyTopologyCache,
    ) -> tuple[LayeredProxyState, ProxyMetrics]:
        """Commit issued preview data without another geometry or metric pass."""

        if type(state) is not LayeredProxyState:
            raise TypeError("state must be LayeredProxyState")
        if type(transition) is not CheckedProxyTransition:
            raise TypeError("transition must be CheckedProxyTransition")
        if type(topology_cache) is not ProxyTopologyCache:
            raise TypeError("topology_cache must be ProxyTopologyCache")
        if (
            type(state.fingerprint) is not str
            or type(transition.parent_fingerprint) is not str
            or type(transition.child_state.fingerprint) is not str
            or type(transition.candidate.state_fingerprint) is not str
        ):
            raise TypeError("all transition fingerprints must be exact str")
        if (
            transition._proof is not _CHECKED_TRANSITION_TOKEN
            or transition.parent_fingerprint != state.fingerprint
            or transition.candidate.state_fingerprint != state.fingerprint
            or _state_digest(state.containers, state.remaining) != state.fingerprint
            or _state_digest(
                transition.child_state.containers,
                transition.child_state.remaining,
            )
            != transition.child_state.fingerprint
            or not topology_cache.owns_unchanged(transition)
        ):
            raise ValueError("foreign, stale, or altered checked transition")
        return transition.child_state, transition.child_metrics

    def _materialize_candidate(
        self,
        state: LayeredProxyState,
        candidate: ProxyCandidate,
    ) -> LayeredProxyState:
        if candidate.state_fingerprint != state.fingerprint:
            raise ValueError("candidate is stale or foreign")
        occurrence = self._occurrence(state, candidate.occurrence)
        if occurrence.item.index != candidate.item_index:
            raise ValueError("candidate item binding does not match occurrence")
        if not 0 <= candidate.container_ordinal < len(state.containers):
            raise ValueError("candidate container ordinal is out of range")
        containers = list(state.containers)
        container = containers[candidate.container_ordinal]
        tag = ProtectionTag.from_item(occurrence.item)
        proxy_box = ProxyBox(candidate.box, occurrence.item, tag, occurrence.key, True)
        top = SupportPatch(
            container.ordinal,
            float(candidate.box.maximum[2]),
            candidate.box.footprint,
            0.0,
            tag,
            "proxy_top",
        )
        containers[candidate.container_ordinal] = replace(
            container,
            boxes=container.boxes + (proxy_box,),
            supports=container.supports + (top,),
        )
        remaining = tuple(value for value in state.remaining if value.key != occurrence.key)
        return LayeredProxyState(tuple(containers), remaining)

    @staticmethod
    def _same_candidate(first: ProxyCandidate, second: ProxyCandidate) -> bool:
        return (
            first.occurrence == second.occurrence
            and type(first.item_index) is int
            and first.item_index == second.item_index
            and type(first.container_ordinal) is int
            and first.container_ordinal == second.container_ordinal
            and type(first.orientation) is int
            and first.orientation == second.orientation
            and first.position == second.position
            and np.array_equal(first.box.minimum, second.box.minimum)
            and np.array_equal(first.box.maximum, second.box.maximum)
            and first.box.axis_aligned == second.box.axis_aligned
            and first.support_ratio == second.support_ratio
            and first.min_clearance == second.min_clearance
            and first.anchor == second.anchor
            and first.support_source == second.support_source
            and first.state_fingerprint == second.state_fingerprint
        )

    def maxrect_waste(
        self,
        state: LayeredProxyState,
        candidate: ProxyCandidate,
        *,
        topology_cache: ProxyTopologyCache | None = None,
    ) -> tuple[float, float, float]:
        container = state.containers[candidate.container_ordinal]
        box = candidate.box.footprint
        dx = max(_EPS, box.max_x - box.min_x)
        dy = max(_EPS, box.max_y - box.min_y)
        rectangles: list[Rect] = []
        for patch in container.supports:
            if abs(float(candidate.box.minimum[2]) - patch.placement_bottom) > 0.001:
                continue
            if patch.footprint.intersection(box) is None:
                continue
            blockers = tuple(
                value.box.footprint
                for value in container.boxes
                if value.box.maximum[2] > patch.height + _EPS
                and value.box.minimum[2] <= patch.placement_bottom + 0.001
                and patch.footprint.intersection(value.box.footprint) is not None
            )
            rectangles.extend(
                rectangle
                for rectangle in self._topology_rectangles(
                    state,
                    container,
                    patch,
                    blockers,
                    128,
                    topology_cache,
                )
                if rectangle.min_x <= box.min_x + _EPS
                and rectangle.max_x >= box.max_x - _EPS
                and rectangle.min_y <= box.min_y + _EPS
                and rectangle.max_y >= box.max_y - _EPS
            )
        if not rectangles:
            rectangles = [container.inner_floor]
        values = []
        for rectangle in rectangles:
            width = max(_EPS, rectangle.max_x - rectangle.min_x)
            length = max(_EPS, rectangle.max_y - rectangle.min_y)
            waste_x = max(0.0, width - dx) / width
            waste_y = max(0.0, length - dy) / length
            values.append(
                (
                    max(0.0, rectangle.area - box.area)
                    / max(_EPS, rectangle.area),
                    min(waste_x, waste_y),
                    max(waste_x, waste_y),
                )
            )
        return min(values)

    def metrics(
        self,
        state: LayeredProxyState,
        *,
        topology_cache: ProxyTopologyCache | None = None,
    ) -> ProxyMetrics:
        total_floor = sum(container.inner_floor.area for container in state.containers)
        largest = 0.0
        free_area = 0.0
        compatible = 0.0
        protected = 0.0
        for container in state.containers:
            for patch in container.supports:
                bottom = patch.placement_bottom
                blockers = tuple(
                    value.box.footprint
                    for value in container.boxes
                    if value.box.maximum[2] > patch.height + _EPS
                    and value.box.minimum[2] <= bottom + 0.001
                    and patch.footprint.intersection(value.box.footprint) is not None
                )
                rectangles = self._topology_rectangles(
                    state,
                    container,
                    patch,
                    blockers,
                    128,
                    topology_cache,
                )
                patch_free = _union_area(rectangles)
                free_area += patch_free
                largest = max(largest, max((rect.area for rect in rectangles), default=0.0))
                compatible_rectangles: list[Rect] = []
                protected_rectangles: list[Rect] = []
                for rectangle in rectangles:
                    ceiling = container.inner_ceiling
                    for value in container.boxes:
                        if value.box.maximum[2] <= bottom + _EPS:
                            continue
                        if rectangle.intersection(value.box.footprint) is None:
                            continue
                        ceiling = min(
                            ceiling,
                            bottom
                            if value.box.minimum[2] <= bottom + _EPS
                            else float(value.box.minimum[2]),
                        )
                    headroom = max(0.0, ceiling - bottom)
                    fitting = tuple(
                        remaining
                        for remaining in state.remaining
                        if any(
                            dimensions[0] <= rectangle.max_x - rectangle.min_x + _EPS
                            and dimensions[1] <= rectangle.max_y - rectangle.min_y + _EPS
                            and dimensions[2] <= headroom + _EPS
                            for _, dimensions in self.orientation_options(remaining.item)
                        )
                    )
                    if fitting or not state.remaining:
                        compatible_rectangles.append(rectangle)
                    if (
                        not state.remaining
                        or any(
                            patch.tag is None
                            or patch.tag.allows(ProtectionTag.from_item(remaining.item))
                            for remaining in fitting
                        )
                    ):
                        protected_rectangles.append(rectangle)
                compatible += _union_area(compatible_rectangles)
                protected += _union_area(protected_rectangles)
        reference = max(total_floor, _EPS)
        largest_norm = min(1.0, largest / reference)
        sliver = 0.0 if free_area <= _EPS else max(0.0, 1.0 - largest / free_area)

        weighted = mass = 0.0
        highest = 0.0
        for container in state.containers:
            floor = container.thickness + container.buffer
            usable = max(_EPS, container.inner_ceiling - floor)
            for value in container.boxes:
                if value.item is None:
                    continue
                item_mass = max(0.0, value.item.mass)
                normalized = min(1.0, max(0.0, (float(value.box.center[2]) - floor) / usable))
                weighted += item_mass * normalized
                mass += item_mass
                highest = max(highest, min(1.0, max(0.0, (float(value.box.maximum[2]) - floor) / usable)))
        cog = 1.0 if mass <= _EPS else 1.0 - weighted / mass

        lanes = open_lanes = 0
        for container in state.containers:
            inner = container.inner_floor
            door = inner.min_y
            for index in range(16):
                x = inner.min_x + (index + 0.5) * (inner.max_x - inner.min_x) / 16.0
                blocked = any(
                    value.box.minimum[0] - self.horizontal_clearance <= x <= value.box.maximum[0] + self.horizontal_clearance
                    and value.box.minimum[1] <= door + 0.30
                    for value in container.boxes
                )
                lanes += 1
                open_lanes += int(not blocked)
        ingress = open_lanes / max(1, lanes)

        def bounded(value: float) -> float:
            return min(1.0, max(0.0, float(value))) if math.isfinite(float(value)) else 0.0

        return ProxyMetrics(
            ingress_access=bounded(ingress),
            largest_free_region=bounded(largest_norm),
            sliver_area=bounded(sliver),
            low_mass_cog_goodness=bounded(cog),
            low_stack=bounded(1.0 - highest),
            compatible_support_capacity=bounded(compatible / reference),
            protection_compatible_capacity=bounded(protected / reference),
        )


__all__ = [
    "LayeredProxy",
    "LayeredProxyState",
    "OccurrenceKey",
    "ProtectionTag",
    "ProxyCandidate",
    "ProxyCandidateBatch",
    "ProxyExposureOrder",
    "ProxyContainer",
    "ProxyMetrics",
    "ProxyOccurrence",
    "ProxyWork",
    "ProxyWorkQuota",
    "SupportPatch",
    "maximal_empty_rectangles",
]
