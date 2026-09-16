"""Portable failure snapshots for physical and candidate replay tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {
            str(key): _json_safe(child)
            for key, child in value.items()
            if not str(key).startswith("shm_") and key != "depth_map"
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported snapshot value: {type(value).__name__}")


def save_observation_snapshot(
    path: Path,
    observation: dict,
    metadata: dict | None = None,
) -> None:
    """Save one observation without process-local shared-memory handles."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    depth_map = observation.get("depth_map")
    has_depth = depth_map is not None
    depth_array = (
        np.asarray(depth_map).copy()
        if has_depth
        else np.empty((0, 0), dtype=np.float32)
    )
    payload_json = json.dumps(_json_safe(observation), separators=(",", ":"))
    metadata_json = json.dumps(_json_safe(metadata or {}), separators=(",", ":"))
    with path.open("wb") as stream:
        np.savez_compressed(
            stream,
            payload_json=np.asarray(payload_json),
            metadata_json=np.asarray(metadata_json),
            has_depth=np.asarray(has_depth, dtype=np.bool_),
            depth_map=depth_array,
        )


def load_observation_snapshot(path: Path) -> tuple[dict, dict]:
    """Load a snapshot using only JSON and non-pickled NumPy arrays."""

    with np.load(Path(path), allow_pickle=False) as archive:
        observation = json.loads(str(archive["payload_json"].item()))
        metadata = json.loads(str(archive["metadata_json"].item()))
        if bool(archive["has_depth"].item()):
            observation["depth_map"] = archive["depth_map"].copy()
    return observation, metadata
