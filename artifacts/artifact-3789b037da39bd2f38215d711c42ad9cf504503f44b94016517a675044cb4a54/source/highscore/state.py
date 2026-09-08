from __future__ import annotations

from typing import Sequence

import numpy as np

from .geometry import aabb_from_pose
from .model import AABB, ContainerState, ItemSpec, PackingState, PlacedItem


def _static_obstacles(container: ContainerState) -> list[AABB]:
    shelf_z = container.height / 2.0 + container.thickness / 2.0 + container.buffer
    small_shelf = AABB.from_center_half(
        (-container.length / 2.0 + container.cut_x / 2.0 + container.thickness, 0.0, shelf_z),
        (container.cut_x / 2.0, container.width / 2.0 - container.thickness, container.thickness / 2.0),
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
        center = tuple(float(x) for x in raw.get("center", (0.0, 0.0, float(raw["height"]) / 2.0)))
        points = np.asarray(raw["points"], dtype=np.float64).copy()
        points[:, 0] -= center[0]
        normals = np.asarray(raw["n_vecs"], dtype=np.float64)
        floor_planes = points[normals[:, 2] < -0.9, 2]
        inferred_buffer = max(
            0.0,
            (float(np.max(floor_planes)) if len(floor_planes) else float(raw["thickness"]))
            - float(raw["thickness"]),
        )
        container = ContainerState(
            index=int(raw.get("index", ordinal)),
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
            shelf=bool(raw.get("shelf", raw.get("require_shelf", False))),
            is_prioritized=bool(raw.get("is_prioritized", False)),
            buffer=float(raw.get("buffer", inferred_buffer)),
            depth_map=(np.asarray(depth_maps[ordinal]) if depth_maps is not None else None),
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
