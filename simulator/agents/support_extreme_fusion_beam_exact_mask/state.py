from __future__ import annotations

import hashlib
import struct
from typing import Any, Sequence

import numpy as np

from .geometry import aabb_from_pose
from .model import AABB, ContainerState, ItemSpec, PackingState, PlacedItem, _require_exact_nonnegative_int


def _static_obstacles(container: ContainerState) -> list[AABB]:
    shelf_z = container.height / 2.0 + container.thickness / 2.0 + container.buffer
    small_shelf = AABB.from_center_half(
        (
            -container.length / 2.0 + container.cut_x / 2.0 + container.thickness,
            0.0,
            shelf_z,
        ),
        (
            container.cut_x / 2.0,
            container.width / 2.0 - container.thickness,
            container.thickness / 2.0,
        ),
    )
    obstacles = [small_shelf]
    if container.shelf:
        obstacles.append(
            AABB.from_center_half(
                (0.0, container.width / 4.0, shelf_z),
                (
                    container.length / 2.0 - container.thickness / 2.0,
                    container.width / 4.0 - container.thickness,
                    container.thickness / 2.0,
                ),
            )
        )
    return obstacles


def build_packing_state(
    container_list: Sequence[dict],
    depth_maps: np.ndarray | None = None,
) -> PackingState:
    containers: list[ContainerState] = []
    for ordinal, raw in enumerate(container_list):
        metadata_index = raw.get("index", ordinal)
        _require_exact_nonnegative_int(metadata_index, "container metadata index")
        center = tuple(
            float(x)
            for x in raw.get("center", (0.0, 0.0, float(raw["height"]) / 2.0))
        )
        points = np.asarray(raw["points"], dtype=np.float64).copy()
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("container points must have shape (n, 3)")
        points[:, 0] -= center[0]
        normals = np.asarray(raw["n_vecs"], dtype=np.float64).copy()
        if normals.shape != points.shape:
            raise ValueError("container normals must match points shape")
        floor_planes = points[normals[:, 2] < -0.9, 2]
        inferred_buffer = max(
            0.0,
            (float(np.max(floor_planes)) if len(floor_planes) else float(raw["thickness"]))
            - float(raw["thickness"]),
        )
        depth_map = None
        if depth_maps is not None:
            depth_map = np.asarray(depth_maps[ordinal], dtype=np.float64).copy()
        container = ContainerState(
            index=metadata_index,
            length=float(raw["length"]),
            width=float(raw["width"]),
            height=float(raw["height"]),
            thickness=float(raw["thickness"]),
            cut_x=float(raw.get("cut_x", 0.0)),
            cut_y=float(raw.get("cut_y", 0.0)),
            center=center,
            points=points,
            normals=normals,
            volume=float(raw.get("volume", 0.0)),
            ordinal=ordinal,
            shelf=bool(raw.get("shelf", raw.get("require_shelf", False))),
            is_prioritized=bool(raw.get("is_prioritized", False)),
            buffer=float(raw.get("buffer", inferred_buffer)),
            depth_map=depth_map,
        )
        for packed_raw in raw.get("packed_items", []):
            item = ItemSpec.from_dict(packed_raw)
            if item.pos is None or item.orn is None:
                continue
            container.placed.append(
                PlacedItem(
                    item=item,
                    box=aabb_from_pose(item.pos, item.dimensions, item.orn, center[0]),
                )
            )
        container.static_obstacles = _static_obstacles(container)
        containers.append(container)
    return PackingState(containers)


def _pool_item_signature(value: Any) -> tuple[Any, ...]:
    if isinstance(value, ItemSpec):
        item = value
    elif isinstance(value, dict):
        item = ItemSpec.from_dict(value)
    else:
        raise TypeError("pool entries must be ItemSpec instances or dictionaries")
    return (
        int(item.index),
        float(item.length),
        float(item.width),
        float(item.height),
        float(item.mass),
        int(item.is_prioritized),
        int(item.is_soft),
        item.belongs_to,
    )


def state_fingerprint(
    state: PackingState,
    pool: Sequence[ItemSpec | dict] | None = None,
    selected_pool_index: int | None = None,
    profile_digest: str | None = None,
) -> str:
    """Return a canonical digest of exact geometry and action context.

    When a visible pool is supplied, its ordered signatures and selected pool
    position are included.  This prevents an exact root from being reused
    after stream reordering or item mutation.  All numeric arrays are encoded
    as little-endian float64 bytes, independent of host byte order.
    """

    digest = hashlib.sha256()

    def add_text(value: object) -> None:
        encoded = str(value).encode("utf-8")
        digest.update(struct.pack("!I", len(encoded)))
        digest.update(encoded)

    def add_float(value: float) -> None:
        digest.update(struct.pack("!d", float(value)))

    def add_array(array: np.ndarray | None) -> None:
        if array is None:
            digest.update(b"<none>")
            return
        contiguous = np.ascontiguousarray(np.asarray(array, dtype="<f8"))
        digest.update(struct.pack("!I", contiguous.ndim))
        for size in contiguous.shape:
            digest.update(struct.pack("!I", int(size)))
        digest.update(contiguous.tobytes(order="C"))

    add_text(len(state.containers))
    for container in state.containers:
        add_text(getattr(container, "ordinal", container.index))
        add_text(container.index)
        for value in (
            container.length,
            container.width,
            container.height,
            container.thickness,
            container.cut_x,
            container.cut_y,
            container.volume,
            container.buffer,
        ):
            add_float(value)
        add_text(int(container.shelf))
        add_text(int(container.is_prioritized))
        add_array(np.asarray(container.center, dtype=np.float64))
        add_array(container.points)
        add_array(container.normals)
        add_array(container.depth_map)
        add_text(len(container.static_obstacles))
        for obstacle in container.static_obstacles:
            add_array(obstacle.minimum)
            add_array(obstacle.maximum)
        add_text(len(container.placed))
        for placed in container.placed:
            item = placed.item
            add_text(item.index)
            for value in (*item.dimensions, item.mass):
                add_float(value)
            add_text(int(item.is_prioritized))
            add_text(int(item.is_soft))
            add_text(item.belongs_to)
            add_array(placed.box.minimum)
            add_array(placed.box.maximum)
            add_text(int(placed.box.axis_aligned))
    if pool is None:
        add_text("<pool-omitted>")
    else:
        add_text("<pool>")
        add_text(len(pool))
        for entry in pool:
            signature = _pool_item_signature(entry)
            for value in signature:
                add_text(value)
    add_text("<selected-pool-index>")
    add_text("<none>" if selected_pool_index is None else int(selected_pool_index))
    add_text("<profile-digest>")
    add_text("<none>" if profile_digest is None else str(profile_digest))
    return digest.hexdigest()
