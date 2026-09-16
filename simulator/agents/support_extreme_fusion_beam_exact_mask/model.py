from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable

import numpy as np


def _require_exact_nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:  # bool and NumPy scalars are not API ints
        raise ValueError(f"{name} must be an exact non-negative int")
    return int(value)


def _finite_vector(value: Iterable[float], name: str) -> np.ndarray:
    try:
        array = np.asarray(tuple(value), dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite vector with shape (3,)") from error
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite vector with shape (3,)")
    return np.array(array, dtype=np.float64, copy=True)


def _immutable_vector(value: Iterable[float], name: str) -> np.ndarray:
    """Create a read-only view backed by immutable bytes.

    A normal ``arr.setflags(write=False)`` is reversible by callers that own
    the array.  A bytes-backed view rejects that transition at NumPy level.
    """

    finite = _finite_vector(value, name)
    raw = finite.astype("<f8", copy=False).tobytes(order="C")
    result = np.frombuffer(raw, dtype="<f8", count=3).reshape((3,))
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class Rect:
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    @property
    def area(self) -> float:
        return max(0.0, self.max_x - self.min_x) * max(0.0, self.max_y - self.min_y)

    def intersection(self, other: "Rect") -> "Rect | None":
        result = Rect(
            max(self.min_x, other.min_x),
            min(self.max_x, other.max_x),
            max(self.min_y, other.min_y),
            min(self.max_y, other.max_y),
        )
        return result if result.area > 0.0 else None


@dataclass(frozen=True)
class AABB:
    minimum: np.ndarray
    maximum: np.ndarray
    axis_aligned: bool = True

    def __post_init__(self) -> None:
        minimum = _immutable_vector(self.minimum, "minimum")
        maximum = _immutable_vector(self.maximum, "maximum")
        if np.any(minimum > maximum):
            raise ValueError("AABB minimum must not exceed maximum")
        minimum.setflags(write=False)
        maximum.setflags(write=False)
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)
        object.__setattr__(self, "axis_aligned", bool(self.axis_aligned))

    @classmethod
    def from_center_half(
        cls,
        center: Iterable[float],
        half: Iterable[float],
        *,
        axis_aligned: bool = True,
    ) -> "AABB":
        c = np.asarray(tuple(center), dtype=np.float64)
        h = np.asarray(tuple(half), dtype=np.float64)
        if c.shape != (3,) or h.shape != (3,):
            raise ValueError("center and half must each contain exactly three values")
        return cls(c - h, c + h, axis_aligned=axis_aligned)

    @property
    def center(self) -> np.ndarray:
        return (self.minimum + self.maximum) * 0.5

    @property
    def half(self) -> np.ndarray:
        return (self.maximum - self.minimum) * 0.5

    @property
    def dimensions(self) -> np.ndarray:
        return self.maximum - self.minimum

    @property
    def volume(self) -> float:
        return float(np.prod(np.maximum(0.0, self.dimensions)))

    @property
    def footprint(self) -> Rect:
        return Rect(
            float(self.minimum[0]),
            float(self.maximum[0]),
            float(self.minimum[1]),
            float(self.maximum[1]),
        )

    def expanded(self, margin: float) -> "AABB":
        delta = np.full(3, float(margin), dtype=np.float64)
        return AABB(self.minimum - delta, self.maximum + delta, self.axis_aligned)

    def intersects(self, other: "AABB", *, tolerance: float = 1e-9) -> bool:
        return bool(
            np.all(self.maximum > other.minimum + tolerance)
            and np.all(other.maximum > self.minimum + tolerance)
        )


@dataclass(frozen=True)
class ItemSpec:
    index: int
    length: float
    width: float
    height: float
    mass: float = 1.0
    is_prioritized: bool = False
    is_soft: bool = False
    belongs_to: int | None = None
    pos: tuple[float, float, float] | None = None
    orn: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        _require_exact_nonnegative_int(self.index, "item index")
        dimensions = (self.length, self.width, self.height)
        if any(not math.isfinite(float(value)) or float(value) <= 0.0 for value in dimensions):
            raise ValueError("item dimensions must be finite and positive")
        if not math.isfinite(float(self.mass)) or float(self.mass) < 0.0:
            raise ValueError("item mass must be finite and non-negative")
        if self.belongs_to is not None:
            _require_exact_nonnegative_int(self.belongs_to, "belongs_to")

    @classmethod
    def from_dict(cls, value: dict) -> "ItemSpec":
        pos = value.get("pos")
        orn = value.get("orn")
        belongs_to = value.get("belongs_to")
        index = value["index"]
        _require_exact_nonnegative_int(index, "item index")
        if belongs_to is not None:
            _require_exact_nonnegative_int(belongs_to, "belongs_to")
        return cls(
            index=index,
            length=float(value["length"]),
            width=float(value["width"]),
            height=float(value["height"]),
            mass=float(value.get("mass", 1.0)),
            is_prioritized=bool(value.get("is_prioritized", False)),
            is_soft=bool(value.get("is_soft", False)),
            belongs_to=belongs_to,
            pos=tuple(float(x) for x in pos) if pos is not None else None,
            orn=tuple(float(x) for x in orn) if orn is not None else None,
        )

    @property
    def dimensions(self) -> tuple[float, float, float]:
        return self.length, self.width, self.height

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    def to_dict(self) -> dict:
        result = {
            "index": int(self.index),
            "length": float(self.length),
            "width": float(self.width),
            "height": float(self.height),
            "mass": float(self.mass),
            "is_prioritized": bool(self.is_prioritized),
            "is_soft": bool(self.is_soft),
        }
        if self.belongs_to is not None:
            result["belongs_to"] = int(self.belongs_to)
        if self.pos is not None:
            result["pos"] = tuple(float(x) for x in self.pos)
        if self.orn is not None:
            result["orn"] = tuple(float(x) for x in self.orn)
        return result


@dataclass
class PlacedItem:
    item: ItemSpec
    box: AABB


@dataclass
class ContainerState:
    index: int
    length: float
    width: float
    height: float
    thickness: float
    cut_x: float
    cut_y: float
    center: tuple[float, float, float]
    points: np.ndarray
    normals: np.ndarray
    volume: float
    ordinal: int | None = None
    shelf: bool = False
    is_prioritized: bool = False
    buffer: float = 0.0
    placed: list[PlacedItem] = field(default_factory=list)
    static_obstacles: list[AABB] = field(default_factory=list)
    depth_map: np.ndarray | None = None

    def __post_init__(self) -> None:
        _require_exact_nonnegative_int(self.index, "container metadata index")
        if self.ordinal is None:
            self.ordinal = int(self.index)
        else:
            _require_exact_nonnegative_int(self.ordinal, "container ordinal")
        self.points = np.array(self.points, dtype=np.float64, copy=True)
        self.normals = np.array(self.normals, dtype=np.float64, copy=True)
        if self.points.ndim != 2 or self.points.shape[1] != 3:
            raise ValueError("container points must have shape (n, 3)")
        if self.normals.shape != self.points.shape:
            raise ValueError("container normals must match points shape")
        if self.depth_map is not None:
            self.depth_map = np.array(self.depth_map, dtype=np.float64, copy=True)

    @property
    def offset_x(self) -> float:
        return float(self.center[0])


@dataclass
class PackingState:
    containers: list[ContainerState]

    def clone(self) -> "PackingState":
        def clone_box(box: AABB) -> AABB:
            return AABB(box.minimum.copy(), box.maximum.copy(), box.axis_aligned)

        return PackingState(
            [
                ContainerState(
                    **{
                        key: value.copy() if isinstance(value, np.ndarray) else value
                        for key, value in vars(container).items()
                        if key not in {"placed", "static_obstacles"}
                    },
                    placed=[PlacedItem(placed.item, clone_box(placed.box)) for placed in container.placed],
                    static_obstacles=[clone_box(obstacle) for obstacle in container.static_obstacles],
                )
                for container in self.containers
            ]
        )


@dataclass(frozen=True)
class PlacementProposal:
    """A raw proposal that has not passed the strict exact mask."""

    item_index: int
    pool_index: int
    container_index: int
    orientation: int
    position: tuple[float, float, float]
    source: str = ""

    def __post_init__(self) -> None:
        _require_exact_nonnegative_int(self.item_index, "item_index")
        _require_exact_nonnegative_int(self.pool_index, "pool_index")
        _require_exact_nonnegative_int(self.container_index, "container_index")
        if type(self.orientation) is not int or self.orientation not in range(6):
            raise ValueError("orientation must be an exact int in range(6)")
        try:
            position = tuple(float(value) for value in self.position)
        except (TypeError, ValueError) as error:
            raise ValueError("position must be a finite vector with shape (3,)") from error
        if len(position) != 3 or not np.all(np.isfinite(np.asarray(position, dtype=np.float64))):
            raise ValueError("position must be a finite vector with shape (3,)")
        object.__setattr__(self, "position", position)
        if not isinstance(self.source, str):
            raise ValueError("source must be a string")


_VALIDATION_TOKEN = object()

_ORIENTATION_PERMUTATIONS = (
    (0, 1, 2),
    (0, 2, 1),
    (2, 1, 0),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
)


def _item_signature(item: ItemSpec) -> tuple[Any, ...]:
    return (
        int(item.index),
        float(item.length),
        float(item.width),
        float(item.height),
        float(item.mass),
        bool(item.is_prioritized),
        bool(item.is_soft),
        item.belongs_to,
    )


@dataclass(frozen=True, init=False)
class ValidatedRoot:
    """A proposal proven safe for exactly one packing-state fingerprint."""

    proposal: PlacementProposal
    box: AABB
    state_fingerprint: str
    support_ratio: float = 0.0
    min_clearance: float = 0.0
    rule_violations: int = 0
    source: str = ""
    profile_digest: str
    item_signature: tuple[Any, ...]
    proposal_key: tuple[Any, ...]
    strict: bool
    _proof: object

    def __init__(
        self,
        *,
        proposal: PlacementProposal,
        box: AABB,
        state_fingerprint: str,
        support_ratio: float = 0.0,
        min_clearance: float = 0.0,
        rule_violations: int = 0,
        source: str = "",
        profile_digest: str = "",
        item_signature: tuple[Any, ...] = (),
        proposal_key: tuple[Any, ...] = (),
        strict: bool = True,
        _proof: object | None = None,
    ) -> None:
        if _proof is not _VALIDATION_TOKEN:
            raise TypeError("ValidatedRoot must be issued by the exact validation mask")
        if not isinstance(proposal, PlacementProposal):
            raise TypeError("proposal must be a PlacementProposal")
        if not isinstance(box, AABB):
            raise TypeError("box must be an AABB")
        if not isinstance(state_fingerprint, str) or not state_fingerprint:
            raise ValueError("state_fingerprint must be non-empty")
        if not isinstance(profile_digest, str) or not profile_digest:
            raise ValueError("profile_digest must be non-empty")
        if not strict:
            raise ValueError("only strict exact roots may be issued")
        if type(rule_violations) is not int or rule_violations != 0:
            raise ValueError("validated roots require zero rule violations")
        if (
            not math.isfinite(float(support_ratio))
            or float(support_ratio) < 0.0
            or not math.isfinite(float(min_clearance))
            or float(min_clearance) < 0.0
        ):
            raise ValueError("validated safety metrics must be finite and non-negative")
        if not item_signature or not proposal_key:
            raise ValueError("exact roots must bind an item signature and proposal key")
        object.__setattr__(self, "proposal", proposal)
        object.__setattr__(self, "box", box)
        object.__setattr__(self, "state_fingerprint", state_fingerprint)
        object.__setattr__(self, "support_ratio", float(support_ratio))
        object.__setattr__(self, "min_clearance", float(min_clearance))
        object.__setattr__(self, "rule_violations", 0)
        object.__setattr__(self, "source", str(source))
        object.__setattr__(self, "profile_digest", profile_digest)
        object.__setattr__(self, "item_signature", tuple(item_signature))
        object.__setattr__(self, "proposal_key", tuple(proposal_key))
        object.__setattr__(self, "strict", True)
        object.__setattr__(self, "_proof", _VALIDATION_TOKEN)


def _issue_validated_root(
    *,
    proposal: PlacementProposal,
    box: AABB,
    state_fingerprint: str,
    item: ItemSpec,
    profile_digest: str,
    pool: tuple[ItemSpec | dict, ...] | list[ItemSpec | dict],
    selected_pool_index: int,
    support_ratio: float,
    min_clearance: float,
    source: str = "",
    rule_violations: int = 0,
    strict: bool = True,
) -> ValidatedRoot:
    """Issue an exact root for the package's strict-mask implementation.

    The token is module-private; callers should use this helper only after all
    exact geometry/protection/depth checks have passed.
    """

    if not isinstance(item, ItemSpec):
        raise TypeError("item must be an ItemSpec")
    _require_exact_nonnegative_int(selected_pool_index, "selected_pool_index")
    if selected_pool_index >= len(pool):
        raise ValueError("selected_pool_index is outside the current pool")
    pool_item = pool[selected_pool_index]
    if isinstance(pool_item, dict):
        pool_item = ItemSpec.from_dict(pool_item)
    if not isinstance(pool_item, ItemSpec):
        raise TypeError("pool entries must be ItemSpec instances or dictionaries")
    if proposal.pool_index != selected_pool_index or _item_signature(pool_item) != _item_signature(item):
        raise ValueError("validated root must bind the selected pool position and item")
    if proposal.item_index != item.index:
        raise ValueError("validated root proposal does not match item index")
    if not np.allclose(
        box.center,
        np.asarray(proposal.position, dtype=np.float64),
        rtol=0.0,
        atol=1e-8,
    ):
        raise ValueError("validated root box center does not match proposal position")
    expected_dimensions = np.asarray(
        tuple(item.dimensions[index] for index in _ORIENTATION_PERMUTATIONS[proposal.orientation]),
        dtype=np.float64,
    )
    if not np.allclose(box.dimensions, expected_dimensions, rtol=0.0, atol=1e-8):
        raise ValueError("validated root box does not match item dimensions")
    proposal_key = (
        proposal.item_index,
        proposal.pool_index,
        proposal.container_index,
        proposal.orientation,
        tuple(round(value, 7) for value in proposal.position),
    )
    return ValidatedRoot(
        proposal=proposal,
        box=box,
        state_fingerprint=state_fingerprint,
        support_ratio=support_ratio,
        min_clearance=min_clearance,
        rule_violations=rule_violations,
        source=source,
        profile_digest=profile_digest,
        item_signature=_item_signature(item),
        proposal_key=proposal_key,
        strict=strict,
        _proof=_VALIDATION_TOKEN,
    )


@dataclass(frozen=True)
class Candidate:
    """Compatibility value for proposal-generation and scoring phases."""

    item: ItemSpec
    pool_index: int
    container_index: int
    orientation: int
    position: tuple[float, float, float]
    box: AABB
    support_ratio: float
    min_clearance: float
    rule_violations: int = 0
    secondary_score: float = 0.0
    future_feasible: float = 0.0
