from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np


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
        return Rect(float(self.minimum[0]), float(self.maximum[0]), float(self.minimum[1]), float(self.maximum[1]))

    def expanded(self, margin: float) -> "AABB":
        delta = np.full(3, margin, dtype=np.float64)
        return AABB(self.minimum - delta, self.maximum + delta, self.axis_aligned)

    def intersects(self, other: "AABB", *, tolerance: float = 1e-9) -> bool:
        return bool(np.all(self.maximum > other.minimum + tolerance) and np.all(other.maximum > self.minimum + tolerance))


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

    @classmethod
    def from_dict(cls, value: dict) -> "ItemSpec":
        pos = value.get("pos")
        orn = value.get("orn")
        return cls(
            index=int(value["index"]),
            length=float(value["length"]),
            width=float(value["width"]),
            height=float(value["height"]),
            mass=float(value.get("mass", 1.0)),
            is_prioritized=bool(value.get("is_prioritized", False)),
            is_soft=bool(value.get("is_soft", False)),
            belongs_to=value.get("belongs_to"),
            pos=tuple(float(x) for x in pos) if pos is not None else None,
            orn=tuple(float(x) for x in orn) if orn is not None else None,
        )

    @property
    def dimensions(self) -> tuple[float, float, float]:
        return self.length, self.width, self.height

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height


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
    shelf: bool = False
    is_prioritized: bool = False
    buffer: float = 0.0
    placed: list[PlacedItem] = field(default_factory=list)
    static_obstacles: list[AABB] = field(default_factory=list)
    depth_map: np.ndarray | None = None

    @property
    def offset_x(self) -> float:
        return float(self.center[0])


@dataclass
class PackingState:
    containers: list[ContainerState]

    def clone(self) -> "PackingState":
        return PackingState(
            [
                ContainerState(
                    **{k: v for k, v in vars(container).items() if k not in {"placed", "static_obstacles"}},
                    placed=list(container.placed),
                    static_obstacles=list(container.static_obstacles),
                )
                for container in self.containers
            ]
        )


@dataclass
class Candidate:
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
