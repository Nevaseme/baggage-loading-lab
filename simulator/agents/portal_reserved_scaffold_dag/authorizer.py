"""Current-state official-semantics authorization for the portal scaffold.

The module deliberately owns one receipt-producing authorizer.  Historical
planning code proposes actions, but it never gets to format an action without
passing this module's current observation checks.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import numbers
import struct
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np


ORIENTATION_PERMS: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2),
    (0, 2, 1),
    (2, 1, 0),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
)

_POSITION_STRUCT = struct.Struct("<3f")
_F32_MAX = float(np.finfo(np.float32).max)
_PENETRATION_EPSILON = 1.0e-9


class AuthorizationError(ValueError):
    """Raised when an authorization receipt cannot format an action."""


class ProposalError(ValueError):
    """Raised when an action cannot be represented as a proposal."""


@dataclass(frozen=True, slots=True)
class AuthorizerProfile:
    """Official process constants; risk terms are intentionally absent."""

    inclusion_margin: float = -0.005
    transport_contact_margin: float = 0.015
    transport_step: float = 0.01
    start_z: float = 0.08
    ceiling_margin: float = 0.018
    displacement_limit: float = 0.3
    penetration_epsilon: float = _PENETRATION_EPSILON


@dataclass(frozen=True, slots=True)
class ActionProposal:
    route: str
    pool_ordinal: Any
    item_index: Any
    item_signature: Any
    container_ordinal: Any
    container_metadata_index: Any
    orientation: Any
    position_f32_le: bytes
    source_key: Any
    proposal_digest: str

    @property
    def position(self) -> tuple[float, float, float]:
        if len(self.position_f32_le) != 12:
            return (math.nan, math.nan, math.nan)
        return tuple(float(value) for value in _POSITION_STRUCT.unpack(self.position_f32_le))


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    accepted: bool
    proposal: ActionProposal | None
    state_fingerprint: str
    profile_digest: str
    hard_evidence: Mapping[str, Any]
    settling_evidence: Mapping[str, Any]
    score_evidence: Mapping[str, Any]
    reject_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        # Copy evidence into immutable mappings so a receipt cannot be altered
        # through a retained caller-owned dict after authorization.
        for name in ("hard_evidence", "settling_evidence", "score_evidence"):
            value = getattr(self, name)
            if not isinstance(value, MappingProxyType):
                object.__setattr__(self, name, MappingProxyType(dict(value)))
        if not isinstance(self.reject_reasons, tuple):
            object.__setattr__(self, "reject_reasons", tuple(self.reject_reasons))


@dataclass(frozen=True, slots=True)
class _OBB:
    center: np.ndarray
    axes: np.ndarray
    half: np.ndarray
    mass: float | None = None
    is_soft: bool = False
    is_prioritized: bool = False
    item_index: int | None = None


_RECEIPTS: dict[int, AuthorizationResult] = {}


def _canonical(value: Any) -> Any:
    """Build a type-sensitive, deterministic representation for fingerprints."""

    if isinstance(value, Mapping):
        pairs = [
            (_canonical(key), _canonical(child))
            for key, child in value.items()
        ]
        pairs.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, separators=(",", ":")))
        return {"__dict__": pairs}
    if isinstance(value, np.ndarray):
        return {
            "__ndarray__": {
                "dtype": str(value.dtype),
                "shape": [int(dim) for dim in value.shape],
                "value": _canonical(value.tolist()),
            }
        }
    if isinstance(value, (list, tuple)):
        marker = "__tuple__" if isinstance(value, tuple) else "__list__"
        return {marker: [_canonical(child) for child in value]}
    if isinstance(value, (np.bool_, bool)):
        return {"__bool__": bool(value)}
    if isinstance(value, (np.integer,)):
        return {"__numpy_int__": str(int(value)), "dtype": str(value.dtype)}
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return {"__int__": str(value)}
    if isinstance(value, (np.floating, float)):
        value_float = float(value)
        return {"__float__": value_float.hex()}
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if dataclasses.is_dataclass(value):
        return {"__dataclass__": type(value).__qualname__, "value": _canonical(dataclasses.asdict(value))}
    if hasattr(value, "__dict__"):
        return {"__object__": type(value).__qualname__, "value": _canonical(vars(value))}
    return {"__repr__": repr(value), "__type__": type(value).__qualname__}


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _profile_value(profile: Any) -> Any:
    if profile is None:
        return AuthorizerProfile()
    if isinstance(profile, AuthorizerProfile):
        return profile
    return profile


def profile_semantics(profile: Any = None) -> dict[str, Any]:
    value = _profile_value(profile)
    if isinstance(value, Mapping):
        result = dict(value)
    elif dataclasses.is_dataclass(value):
        result = dataclasses.asdict(value)
    elif hasattr(value, "__dict__"):
        result = dict(vars(value))
    else:
        result = {"value": repr(value)}
    defaults = dataclasses.asdict(AuthorizerProfile())
    for key, default in defaults.items():
        result.setdefault(key, default)
    return result


def profile_digest(profile: Any = None) -> str:
    return _digest({"profile_type": type(_profile_value(profile)).qualname__, "semantics": profile_semantics(profile)})


def _profile_number(profile: Any, key: str) -> float:
    value = profile_semantics(profile).get(key)
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"profile field {key} is not numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"profile field {key} is not finite")
    return result


def _item_signature(item: Any) -> Any:
    return _canonical(item)


def _observation_signature(observation: Any, profile: Any) -> Any:
    if not isinstance(observation, Mapping):
        return {"observation": _canonical(observation), "profile": profile_semantics(profile)}
    pool = observation.get("pool_list")
    containers = observation.get("container_list")
    pool_signature = []
    if isinstance(pool, (list, tuple)):
        # Ordered occurrences are deliberate: duplicate item indices are not
        # interchangeable visible-pool bindings.
        for ordinal, item in enumerate(pool):
            pool_signature.append({"ordinal": ordinal, "item": _item_signature(item)})
    else:
        pool_signature = {"invalid": _canonical(pool)}
    container_signature = []
    if isinstance(containers, (list, tuple)):
        for ordinal, container in enumerate(containers):
            if isinstance(container, Mapping):
                # Every observable container key is part of the receipt.  The
                # packed sequence is kept as an ordered occurrence list so a
                # reordered duplicate cannot reuse a stale authorization.
                metadata = {
                    key: value
                    for key, value in container.items()
                    if key != "packed_items"
                }
                packed = [
                    {"ordinal": packed_ordinal, "item": _item_signature(item)}
                    for packed_ordinal, item in enumerate(container.get("packed_items", []) or [])
                ]
                container_signature.append({"ordinal": ordinal, "metadata": _canonical(metadata), "packed": packed})
            else:
                container_signature.append({"ordinal": ordinal, "container": _canonical(container)})
    else:
        container_signature = {"invalid": _canonical(containers)}
    observable_fields = {
        key: value
        for key, value in observation.items()
        if key not in {"pool_list", "container_list"}
    }
    return {
        "pool": pool_signature,
        "containers": container_signature,
        "observation": _canonical(observable_fields),
        "profile": profile_semantics(profile),
    }


def state_fingerprint(observation: Mapping[str, Any], profile: Any = None) -> str:
    return _digest(_observation_signature(observation, _profile_value(profile)))


def _is_builtin_int(value: Any) -> bool:
    return type(value) is int


def _canonical_position(position: Any) -> bytes:
    if isinstance(position, np.ndarray):
        values = position.reshape(-1).tolist()
    elif isinstance(position, (list, tuple)):
        values = list(position)
    else:
        raise ProposalError("place_pos must be a three-value sequence")
    if len(values) != 3:
        raise ProposalError("place_pos must have length three")
    converted: list[float] = []
    for value in values:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real):
            raise ProposalError("place_pos values must be numeric")
        converted_value = float(value)
        if not math.isfinite(converted_value) or abs(converted_value) > _F32_MAX:
            raise ProposalError("place_pos values must be finite float32 values")
        converted.append(converted_value)
    try:
        return _POSITION_STRUCT.pack(*converted)
    except (OverflowError, struct.error) as error:
        raise ProposalError("place_pos cannot be represented as float32") from error


def _proposal_payload(proposal: ActionProposal) -> dict[str, Any]:
    return {
        "route": proposal.route,
        "pool_ordinal": proposal.pool_ordinal,
        "item_index": proposal.item_index,
        "item_signature": proposal.item_signature,
        "container_ordinal": proposal.container_ordinal,
        "container_metadata_index": proposal.container_metadata_index,
        "orientation": proposal.orientation,
        "position_f32_le": proposal.position_f32_le,
        "source_key": proposal.source_key,
    }


def _proposal_digest(proposal: ActionProposal) -> str:
    return _digest(_proposal_payload(proposal))


def _invalid_proposal_from_action(action: Any, observation: Mapping[str, Any], route: str, source_key: Any) -> ActionProposal:
    item_idx = action.get("item_idx", -1) if isinstance(action, Mapping) else -1
    container_idx = action.get("container_idx", -1) if isinstance(action, Mapping) else -1
    orientation = action.get("orientation", -1) if isinstance(action, Mapping) else -1
    item_index: Any = -1
    item_signature: Any = ()
    container_metadata_index: Any = -1
    try:
        pool = observation.get("pool_list", [])
        if _is_builtin_int(item_idx) and 0 <= item_idx < len(pool):
            item_index = pool[item_idx].get("index", -1)
            item_signature = _item_signature(pool[item_idx])
    except Exception:
        pass
    try:
        containers = observation.get("container_list", [])
        if _is_builtin_int(container_idx) and 0 <= container_idx < len(containers):
            container_metadata_index = containers[container_idx].get("index", -1)
    except Exception:
        pass
    try:
        position_bytes = _canonical_position(action.get("place_pos"))
    except Exception:
        position_bytes = b""
    proposal = ActionProposal(
        route=route,
        pool_ordinal=item_idx,
        item_index=item_index,
        item_signature=item_signature,
        container_ordinal=container_idx,
        container_metadata_index=container_metadata_index,
        orientation=orientation,
        position_f32_le=position_bytes,
        source_key=source_key,
        proposal_digest="",
    )
    return dataclasses.replace(proposal, proposal_digest=_proposal_digest(proposal))


def proposal_from_action(
    action: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    route: str = "historical",
    source_key: Any = "historical_seed",
    allow_invalid: bool = False,
) -> ActionProposal:
    """Bind an official action dictionary to the visible occurrence/state."""

    expected_keys = {"item_idx", "container_idx", "place_pos", "orientation"}
    if not isinstance(action, Mapping) or set(action) != expected_keys:
        if allow_invalid:
            return _invalid_proposal_from_action(action, observation, route, source_key)
        raise ProposalError("action keys must exactly match the official interface")
    item_idx = action["item_idx"]
    container_idx = action["container_idx"]
    orientation = action["orientation"]
    try:
        position_bytes = _canonical_position(action["place_pos"])
    except ProposalError:
        if not allow_invalid:
            raise
        return _invalid_proposal_from_action(action, observation, route, source_key)
    try:
        pool = observation["pool_list"]
        containers = observation["container_list"]
        if not _is_builtin_int(item_idx) or not (0 <= item_idx < len(pool)):
            raise ProposalError("item_idx is not a visible pool ordinal")
        if not _is_builtin_int(container_idx) or not (0 <= container_idx < len(containers)):
            raise ProposalError("container_idx is not a container ordinal")
        item = pool[item_idx]
        container = containers[container_idx]
        item_index = item.get("index")
        metadata_index = container.get("index")
    except Exception as error:
        if not allow_invalid:
            if isinstance(error, ProposalError):
                raise
            raise ProposalError("action binding failed") from error
        return _invalid_proposal_from_action(action, observation, route, source_key)
    proposal = ActionProposal(
        route=route,
        pool_ordinal=item_idx,
        item_index=item_index,
        item_signature=_item_signature(item),
        container_ordinal=container_idx,
        container_metadata_index=metadata_index,
        orientation=orientation,
        position_f32_le=position_bytes,
        source_key=source_key,
        proposal_digest="",
    )
    return dataclasses.replace(proposal, proposal_digest=_proposal_digest(proposal))


def _orientation_quaternion(orientation: int) -> tuple[float, float, float, float]:
    half_pi = math.pi * 0.5
    eulers = (
        (0.0, 0.0, 0.0),
        (half_pi, 0.0, 0.0),
        (0.0, half_pi, 0.0),
        (0.0, 0.0, half_pi),
        (0.0, half_pi, half_pi),
        (half_pi, 0.0, half_pi),
    )
    roll, pitch, yaw = eulers[orientation]
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def _quaternion_matrix(quaternion: Sequence[float]) -> np.ndarray | None:
    try:
        x, y, z, w = (float(value) for value in quaternion)
    except (TypeError, ValueError):
        return None
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(norm) or norm <= 1.0e-12:
        return None
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _dimensions(item: Mapping[str, Any], orientation: int) -> np.ndarray:
    dims = np.asarray(
        [float(item["length"]), float(item["width"]), float(item["height"])],
        dtype=np.float64,
    )
    return dims[list(ORIENTATION_PERMS[orientation])]


def _target_obb(item: Mapping[str, Any], orientation: int, center: Sequence[float]) -> _OBB:
    rotation = _quaternion_matrix(_orientation_quaternion(orientation))
    if rotation is None:
        raise ValueError("target orientation quaternion is invalid")
    original_dims = np.asarray(
        [float(item["length"]), float(item["width"]), float(item["height"])],
        dtype=np.float64,
    )
    return _OBB(
        center=np.asarray(center, dtype=np.float64),
        axes=rotation,
        half=original_dims * 0.5,
    )


def _packed_obb(item: Mapping[str, Any], center_x_offset: float = 0.0) -> _OBB | None:
    if "pos" not in item or "orn" not in item:
        return None
    rotation = _quaternion_matrix(item["orn"])
    if rotation is None:
        return None
    try:
        center = np.asarray(item["pos"], dtype=np.float64).reshape(3)
        center = center.copy()
        # Observed packed positions are world coordinates.  Lightweight
        # fixtures may provide local positions explicitly with a marker.
        if bool(item.get("position_is_local", False)):
            center[0] += center_x_offset
        half = np.asarray(
            [float(item["length"]), float(item["width"]), float(item["height"])],
            dtype=np.float64,
        ) * 0.5
    except (KeyError, TypeError, ValueError):
        return None
    try:
        mass = float(item.get("mass", 0.0))
    except (TypeError, ValueError):
        mass = None
    return _OBB(
        center=center,
        axes=rotation,
        half=half,
        mass=mass if mass is not None and math.isfinite(mass) else None,
        is_soft=bool(item.get("is_soft", False)),
        is_prioritized=bool(item.get("is_prioritized", False)),
        item_index=item.get("index") if type(item.get("index")) is int else None,
    )


def _aabb_obb(center: Sequence[float], half: Sequence[float]) -> _OBB:
    return _OBB(
        center=np.asarray(center, dtype=np.float64),
        axes=np.eye(3, dtype=np.float64),
        half=np.asarray(half, dtype=np.float64),
    )


def _sat_separation(first: _OBB, second: _OBB) -> float:
    """Return the maximum signed SAT separation for two OBBs."""

    axes: list[np.ndarray] = []
    for axis in first.axes.T:
        axes.append(np.asarray(axis, dtype=np.float64))
    for axis in second.axes.T:
        axes.append(np.asarray(axis, dtype=np.float64))
    for first_axis in first.axes.T:
        for second_axis in second.axes.T:
            cross = np.cross(first_axis, second_axis)
            norm = float(np.linalg.norm(cross))
            if norm > 1.0e-10:
                axes.append(cross / norm)
    delta = second.center - first.center
    separations = []
    for axis in axes:
        axis = axis / max(float(np.linalg.norm(axis)), 1.0e-12)
        radius_first = float(np.sum(np.abs(first.axes.T @ axis) * first.half))
        radius_second = float(np.sum(np.abs(second.axes.T @ axis) * second.half))
        separations.append(abs(float(np.dot(delta, axis))) - radius_first - radius_second)
    return float(max(separations)) if separations else -math.inf


def _obb_vertices(box: _OBB) -> np.ndarray:
    signs = np.asarray(
        [
            [-1, -1, -1],
            [-1, -1, 1],
            [-1, 1, -1],
            [-1, 1, 1],
            [1, -1, -1],
            [1, -1, 1],
            [1, 1, -1],
            [1, 1, 1],
        ],
        dtype=np.float64,
    )
    return box.center[None, :] + signs @ (box.axes * box.half[None, :]).T


_OBB_EDGE_INDEXES: tuple[tuple[int, int], ...] = (
    (0, 1), (0, 2), (1, 3), (2, 3),
    (4, 5), (4, 6), (5, 7), (6, 7),
    (0, 4), (1, 5), (2, 6), (3, 7),
)
_OBB_FACE_INDEXES: tuple[tuple[int, int, int, int], ...] = (
    (0, 1, 3, 2),
    (4, 6, 7, 5),
    (0, 4, 5, 1),
    (2, 3, 7, 6),
    (0, 2, 6, 4),
    (1, 5, 7, 3),
)


def _point_triangle_distance(point: np.ndarray, first: np.ndarray, second: np.ndarray, third: np.ndarray) -> float:
    """Return the closest Euclidean point-to-triangle distance."""

    edge_first = second - first
    edge_second = third - first
    to_point = point - first
    dot_first = float(np.dot(edge_first, to_point))
    dot_second = float(np.dot(edge_second, to_point))
    dot_edges = float(np.dot(edge_first, edge_first))
    dot_cross = float(np.dot(edge_first, edge_second))
    dot_other = float(np.dot(edge_second, edge_second))
    denominator = dot_edges * dot_other - dot_cross * dot_cross
    if denominator > 1.0e-24:
        bary_first = (dot_other * dot_first - dot_cross * dot_second) / denominator
        bary_second = (dot_edges * dot_second - dot_cross * dot_first) / denominator
        if bary_first >= 0.0 and bary_second >= 0.0 and bary_first + bary_second <= 1.0:
            closest = first + bary_first * edge_first + bary_second * edge_second
            return float(np.linalg.norm(point - closest))
    # The degenerate/edge cases below are explicit segment distances, so no
    # projection can escape the triangle boundary.
    return min(
        _point_segment_distance(point, first, second),
        _point_segment_distance(point, first, third),
        _point_segment_distance(point, second, third),
    )


def _point_segment_distance(point: np.ndarray, first: np.ndarray, second: np.ndarray) -> float:
    segment = second - first
    denominator = float(np.dot(segment, segment))
    if denominator <= 1.0e-24:
        return float(np.linalg.norm(point - first))
    fraction = min(1.0, max(0.0, float(np.dot(point - first, segment)) / denominator))
    return float(np.linalg.norm(point - (first + fraction * segment)))


def _segment_segment_distance(first: np.ndarray, second: np.ndarray, third: np.ndarray, fourth: np.ndarray) -> float:
    """Return the closest distance between two finite line segments."""

    first_direction = second - first
    second_direction = fourth - third
    between = first - third
    a = float(np.dot(first_direction, first_direction))
    b = float(np.dot(first_direction, second_direction))
    c = float(np.dot(second_direction, second_direction))
    d = float(np.dot(first_direction, between))
    e = float(np.dot(second_direction, between))
    denominator = a * c - b * b
    if a <= 1.0e-24 and c <= 1.0e-24:
        return float(np.linalg.norm(first - third))
    if a <= 1.0e-24:
        return _point_segment_distance(first, third, fourth)
    if c <= 1.0e-24:
        return _point_segment_distance(third, first, second)
    if denominator > 1.0e-24:
        first_fraction = (b * e - c * d) / denominator
        second_fraction = (a * e - b * d) / denominator
    else:
        first_fraction = 0.0
        second_fraction = e / c
    if first_fraction < 0.0:
        first_fraction = 0.0
        second_fraction = min(1.0, max(0.0, e / c))
    elif first_fraction > 1.0:
        first_fraction = 1.0
        second_fraction = min(1.0, max(0.0, (e + b) / c))
    elif second_fraction < 0.0:
        second_fraction = 0.0
        first_fraction = min(1.0, max(0.0, -d / a))
    elif second_fraction > 1.0:
        second_fraction = 1.0
        first_fraction = min(1.0, max(0.0, (b - d) / a))
    closest_first = first + first_fraction * first_direction
    closest_second = third + second_fraction * second_direction
    return float(np.linalg.norm(closest_first - closest_second))


def _obb_feature_distance(first: _OBB, second: _OBB) -> float:
    first_vertices = _obb_vertices(first)
    second_vertices = _obb_vertices(second)
    minimum = math.inf
    for vertex in first_vertices:
        for i0, i1, i2, i3 in _OBB_FACE_INDEXES:
            minimum = min(
                minimum,
                _point_triangle_distance(vertex, second_vertices[i0], second_vertices[i1], second_vertices[i2]),
                _point_triangle_distance(vertex, second_vertices[i0], second_vertices[i2], second_vertices[i3]),
            )
    for vertex in second_vertices:
        for i0, i1, i2, i3 in _OBB_FACE_INDEXES:
            minimum = min(
                minimum,
                _point_triangle_distance(vertex, first_vertices[i0], first_vertices[i1], first_vertices[i2]),
                _point_triangle_distance(vertex, first_vertices[i0], first_vertices[i2], first_vertices[i3]),
            )
    for first_start, first_end in _OBB_EDGE_INDEXES:
        for second_start, second_end in _OBB_EDGE_INDEXES:
            minimum = min(
                minimum,
                _segment_segment_distance(
                    first_vertices[first_start],
                    first_vertices[first_end],
                    second_vertices[second_start],
                    second_vertices[second_end],
                ),
            )
    return 0.0 if not math.isfinite(minimum) else float(max(0.0, minimum))


def _axis_aligned_extents(box: _OBB) -> np.ndarray | None:
    """Return exact world extents for a signed-permutation OBB."""

    absolute_axes = np.abs(box.axes)
    if not (
        np.allclose(np.sum(absolute_axes, axis=0), 1.0, atol=1.0e-10)
        and np.allclose(np.sum(absolute_axes, axis=1), 1.0, atol=1.0e-10)
        and np.all((absolute_axes <= 1.0e-10) | (np.abs(absolute_axes - 1.0) <= 1.0e-10))
    ):
        return None
    return np.sum(absolute_axes * box.half[None, :], axis=1)


def _obb_separation(first: _OBB, second: _OBB) -> float:
    """Return closest Euclidean OBB distance, with intersections at zero."""

    first_extents = _axis_aligned_extents(first)
    second_extents = _axis_aligned_extents(second)
    if first_extents is not None and second_extents is not None:
        gaps = np.maximum(
            0.0,
            np.abs(second.center - first.center) - first_extents - second_extents,
        )
        return float(np.linalg.norm(gaps))
    signed_sat = _sat_separation(first, second)
    if signed_sat <= 0.0:
        return 0.0
    return _obb_feature_distance(first, second)


def _obb_separation_for_threshold(first: _OBB, second: _OBB, threshold: float) -> float:
    """Use a conservative AABB lower bound before exact near-contact work."""

    first_extents = np.sum(np.abs(first.axes) * first.half[None, :], axis=1)
    second_extents = np.sum(np.abs(second.axes) * second.half[None, :], axis=1)
    lower_bound = float(
        np.linalg.norm(
            np.maximum(0.0, np.abs(second.center - first.center) - first_extents - second_extents)
        )
    )
    if lower_bound > float(threshold):
        # This value is used only for a strict threshold comparison by the
        # transport path; callers needing the receipt's exact clearance use
        # _obb_separation directly.
        return lower_bound
    return _obb_separation(first, second)


def _obb_positive_overlap(first: _OBB, second: _OBB, epsilon: float) -> bool:
    """Return true only for positive-volume OBB intersection."""

    return bool(_sat_separation(first, second) < -float(epsilon))


def _points_world(container: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    normals = np.asarray(container.get("n_vecs", []), dtype=np.float64)
    points = np.asarray(container.get("points", []), dtype=np.float64)
    if normals.ndim != 2 or points.ndim != 2 or normals.shape != points.shape or normals.shape[1] != 3:
        length = float(container.get("length", 0.0))
        width = float(container.get("width", 0.0))
        height = float(container.get("height", 0.0))
        thickness = float(container.get("thickness", 0.04))
        center = np.asarray(container.get("center", [0.0, 0.0, 0.0]), dtype=np.float64)
        normals = np.asarray(
            [[-1, 0, 0], [1, 0, 0], [0, -1, 0], [0, 1, 0], [0, 0, -1], [0, 0, 1]],
            dtype=np.float64,
        )
        points = np.asarray(
            [
                [-length / 2 + thickness, 0, 0],
                [length / 2 - thickness, 0, 0],
                [0, -width / 2 + thickness, 0],
                [0, width / 2 - thickness, 0],
                [0, 0, thickness],
                [0, 0, height - thickness],
            ],
            dtype=np.float64,
        )
        points[:, 0] += center[0]
        return normals, points
    center = np.asarray(container.get("center", [0.0, 0.0, 0.0]), dtype=np.float64)
    points = points.copy()
    if abs(float(center[0])) > 1.0e-9:
        world_distance = float(np.mean(np.abs(points[:, 0] - center[0])))
        local_distance = float(np.mean(np.abs(points[:, 0])))
        if local_distance + 1.0e-7 < world_distance:
            points[:, 0] += center[0]
    return normals, points


def _plane_evidence(container: Mapping[str, Any], target: _OBB, margin: float) -> tuple[bool, dict[str, Any]]:
    normals, points = _points_world(container)
    world_half = np.sum(np.abs(target.axes) * target.half[None, :], axis=1)
    dots = []
    for normal, point in zip(normals, points):
        norm = float(np.linalg.norm(normal))
        if norm <= 1.0e-12 or not math.isfinite(norm):
            dots.append(math.inf)
            continue
        normal = normal / norm
        dots.append(float(np.dot(normal, target.center - point) + np.dot(np.abs(normal), world_half)))
    maximum = max(dots) if dots else math.inf
    return bool(dots) and maximum <= margin, {
        "plane_inclusion": bool(dots) and maximum <= margin,
        "plane_max_dot": maximum,
        "plane_margin": margin,
        "plane_dots": tuple(dots),
    }


def _container_offset_x(container: Mapping[str, Any]) -> float:
    center = container.get("center", [0.0, 0.0, 0.0])
    try:
        return float(center[0])
    except (TypeError, IndexError, ValueError):
        return 0.0


def _buffer(container: Mapping[str, Any]) -> float:
    if container.get("buffer") is not None:
        return float(container.get("buffer"))
    center = container.get("center", [0.0, 0.0, 0.0])
    try:
        return float(center[2]) - float(container.get("height", 0.0)) * 0.5
    except (TypeError, IndexError, ValueError):
        return 0.0


def _shelf_obbs(container: Mapping[str, Any]) -> list[tuple[_OBB, str]]:
    length = float(container.get("length", 0.0))
    width = float(container.get("width", 0.0))
    height = float(container.get("height", 0.0))
    thickness = float(container.get("thickness", 0.04))
    cut_x = float(container.get("cut_x", 0.0))
    offset_x = _container_offset_x(container)
    buffer = _buffer(container)
    shelves: list[tuple[_OBB, str]] = []
    small_center = np.asarray(
        [offset_x - length / 2.0 + cut_x / 2.0 + thickness, 0.0, height / 2.0 + thickness / 2.0 + buffer],
        dtype=np.float64,
    )
    small_half = np.asarray([cut_x / 2.0, width / 2.0 - thickness, thickness / 2.0], dtype=np.float64)
    shelves.append((_aabb_obb(small_center, small_half), "small_shelf"))
    if bool(container.get("shelf", container.get("require_shelf", False))):
        main_center = np.asarray([offset_x, width / 4.0, height / 2.0 + thickness / 2.0 + buffer], dtype=np.float64)
        main_half = np.asarray([length / 2.0 - thickness / 2.0, width / 4.0 - thickness, thickness / 2.0], dtype=np.float64)
        shelves.append((_aabb_obb(main_center, main_half), "main_shelf"))
    return shelves


def _transport_path(
    container: Mapping[str, Any],
    item: Mapping[str, Any],
    target: _OBB,
    orientation: int,
    packed: Sequence[_OBB],
    shelves: Sequence[tuple[_OBB, str]],
    profile: Any,
) -> tuple[bool, dict[str, Any]]:
    length = float(container.get("length", 0.0))
    width = float(container.get("width", 0.0))
    height = float(container.get("height", 0.0))
    thickness = float(container.get("thickness", 0.04))
    buffer = _buffer(container)
    cut_x = float(container.get("cut_x", 0.0))
    offset_x = _container_offset_x(container)
    dimensions = _dimensions(item, orientation)
    half = dimensions * 0.5
    target_local = target.center.copy()
    target_local[0] -= offset_x
    resting_surfaces = (thickness, height / 2.0 + thickness + buffer)
    effective_lift = _profile_number(profile, "start_z")
    bottom_z = float(target.center[2] - half[2])
    for resting_z in resting_surfaces:
        if 0.0 <= bottom_z - resting_z <= 0.05:
            effective_lift = 0.0
            break
    top_z = float(target.center[2] + half[2])
    if effective_lift > 0.0:
        for ceiling_z in (height / 2.0 + buffer, height + buffer - thickness):
            clearance = ceiling_z - top_z
            ceiling_margin = _profile_number(profile, "ceiling_margin")
            if 0.0 <= clearance < effective_lift + ceiling_margin:
                effective_lift = max(0.0, clearance - ceiling_margin - 0.0005)
                break
    start_margin = 0.01
    path_z = min(
        height + buffer - thickness - half[2] - start_margin,
        float(target.center[2] + effective_lift),
    )
    x_min = -length / 2.0 + thickness + cut_x + half[0] + start_margin
    x_max = length / 2.0 - thickness - half[0] - start_margin
    # Preserve the official clamp expression even for an inverted interval;
    # the simulator applies min(max(x, x_min), x_max) without a special case.
    start_x_local = min(max(float(target_local[0]), x_min), x_max)
    start_world = np.asarray([start_x_local + offset_x, -width / 2.0, path_z], dtype=np.float64)
    safety = _profile_number(profile, "transport_contact_margin")
    step_len = _profile_number(profile, "transport_step")
    obstacles = list(packed) + [shelf for shelf, _name in shelves]

    def check_sample(center: np.ndarray) -> tuple[bool, float]:
        moving = _OBB(center=center, axes=target.axes, half=target.half)
        clearances = [
            _obb_separation_for_threshold(moving, obstacle, safety + 1.0e-9)
            for obstacle in obstacles
        ]
        if not clearances:
            return True, math.inf
        minimum = min(clearances)
        # Equality is conservative, while the epsilon only absorbs binary
        # representation noise around an exact 15 mm contact.
        return bool(minimum > safety + 1.0e-9), float(minimum)

    y_target = float(target.center[1])
    y_delta = y_target - float(start_world[1])
    y_steps = max(int(math.ceil(abs(y_delta) / step_len)), 1)
    minimum_clearance = math.inf
    current = start_world.copy()
    for sample in range(y_steps + 1):
        fraction = sample / y_steps
        current = np.asarray(
            [start_world[0], start_world[1] + y_delta * fraction, start_world[2]],
            dtype=np.float64,
        )
        clear, clearance = check_sample(current)
        minimum_clearance = min(minimum_clearance, clearance)
        if not clear:
            return False, {
                "transport": False,
                "transport_min_clearance": minimum_clearance,
                "transport_contact_margin": safety,
                "effective_lift": effective_lift,
                "start_x": start_x_local,
                "path_z": path_z,
                "failed_segment": "y",
                "sample_index": sample,
            }
    x_target = float(target_local[0] + offset_x)
    x_delta = x_target - float(current[0])
    x_steps = max(int(math.ceil(abs(x_delta) / step_len)), 1)
    for sample in range(x_steps + 1):
        fraction = sample / x_steps
        current = np.asarray(
            [start_world[0] + x_delta * fraction, target.center[1], start_world[2]],
            dtype=np.float64,
        )
        clear, clearance = check_sample(current)
        minimum_clearance = min(minimum_clearance, clearance)
        if not clear:
            return False, {
                "transport": False,
                "transport_min_clearance": minimum_clearance,
                "transport_contact_margin": safety,
                "effective_lift": effective_lift,
                "start_x": start_x_local,
                "path_z": path_z,
                "failed_segment": "x",
                "sample_index": sample,
            }
    return True, {
        "transport": True,
        "transport_min_clearance": minimum_clearance,
        "transport_contact_margin": safety,
        "effective_lift": effective_lift,
        "start_x": start_x_local,
        "path_z": path_z,
        "failed_segment": None,
        "sample_index": None,
    }


def _rect_overlap_area(first_min: np.ndarray, first_max: np.ndarray, second_min: np.ndarray, second_max: np.ndarray) -> float:
    return max(0.0, min(float(first_max[0]), float(second_max[0])) - max(float(first_min[0]), float(second_min[0]))) * max(
        0.0, min(float(first_max[1]), float(second_max[1])) - max(float(first_min[1]), float(second_min[1]))
    )


def _support_surfaces(container: Mapping[str, Any], packed: Sequence[_OBB], shelves: Sequence[tuple[_OBB, str]]) -> list[tuple[np.ndarray, np.ndarray, float, str, _OBB | None]]:
    surfaces: list[tuple[np.ndarray, np.ndarray, float, str, _OBB | None]] = []
    normals, points = _points_world(container)
    floor_z = None
    for normal, point in zip(normals, points):
        norm = float(np.linalg.norm(normal))
        if norm > 1.0e-12 and float(normal[2]) / norm < -0.9:
            floor_z = float(point[2])
            break
    if floor_z is not None:
        center_x = _container_offset_x(container)
        length = float(container.get("length", 0.0))
        width = float(container.get("width", 0.0))
        thickness = float(container.get("thickness", 0.04))
        surfaces.append(
            (
                np.asarray([center_x - length / 2.0 + thickness, -width / 2.0 + thickness]),
                np.asarray([center_x + length / 2.0 - thickness, width / 2.0 - thickness]),
                floor_z,
                "floor",
                None,
            )
        )
    for obstacle in packed:
        corners = obstacle.center[None, :] + np.asarray(
            [
                [-1, -1, -1],
                [-1, -1, 1],
                [-1, 1, -1],
                [-1, 1, 1],
                [1, -1, -1],
                [1, -1, 1],
                [1, 1, -1],
                [1, 1, 1],
            ],
            dtype=np.float64,
        ) @ (obstacle.axes * obstacle.half[None, :]).T
        lower = np.min(corners, axis=0)
        upper = np.max(corners, axis=0)
        surfaces.append((lower[:2], upper[:2], float(upper[2]), "packed", obstacle))
    for obstacle, name in shelves:
        lower = obstacle.center - obstacle.half
        upper = obstacle.center + obstacle.half
        surfaces.append((lower[:2], upper[:2], float(upper[2]), name, obstacle))
    return surfaces


def _settling_evidence(
    container: Mapping[str, Any],
    item: Mapping[str, Any],
    target: _OBB,
    orientation: int,
    packed: Sequence[_OBB],
    shelves: Sequence[tuple[_OBB, str]],
    profile: Any,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    dimensions = _dimensions(item, orientation)
    half = dimensions * 0.5
    world_half = np.sum(np.abs(target.axes) * target.half[None, :], axis=1)
    footprint_min = target.center[:2] - world_half[:2]
    footprint_max = target.center[:2] + world_half[:2]
    bottom = float(target.center[2] - world_half[2])
    surfaces = _support_surfaces(container, packed, shelves)
    candidate_surfaces = []
    for lower, upper, top_z, kind, supporter in surfaces:
        overlap = _rect_overlap_area(footprint_min, footprint_max, lower, upper)
        # Only surfaces below the target bottom are landings.  The old
        # arbitrary 30 mm band could select an upper surface and mask the
        # actual highest lower landing.
        if overlap > 0.0 and top_z <= bottom:
            candidate_surfaces.append((top_z, overlap, lower, upper, kind, supporter))
    reasons: list[str] = []
    if not candidate_surfaces:
        landing_surface = None
        lower_surface = None
        support_ratio = 0.0
        center_support = False
        predicted_drop = math.inf
        landing_support = 0.0
        supporter_kind = None
        supporter_pose = None
    else:
        top_z = max(candidate[0] for candidate in candidate_surfaces)
        selected = [candidate for candidate in candidate_surfaces if abs(candidate[0] - top_z) <= 1.0e-8]
        footprint_area = max(float(np.prod(world_half[:2] * 2.0)), 1.0e-12)
        support_area = sum(candidate[1] for candidate in selected)
        support_ratio = min(1.0, support_area / footprint_area)
        center_support = any(
            float(lower[0]) <= float(target.center[0]) <= float(upper[0])
            and float(lower[1]) <= float(target.center[1]) <= float(upper[1])
            for _z, _area, lower, upper, _kind, _supporter in selected
        )
        predicted_drop = max(0.0, bottom - top_z)
        landing_surface = top_z
        lower_surface = top_z
        landing_support = support_ratio
        supporter_kind = selected[0][4]
        supporter_pose = selected[0][5].center.tolist() if selected[0][5] is not None else None
        if predicted_drop > _profile_number(profile, "displacement_limit"):
            reasons.append("predicted_drop")
    if not candidate_surfaces:
        reasons.append("no_landing_surface")
    selected_supporters = [candidate[5] for candidate in candidate_surfaces if candidate[0] == landing_surface]
    selected_supporters = [supporter for supporter in selected_supporters if supporter is not None]
    supporter_masses = [supporter.mass for supporter in selected_supporters if supporter.mass is not None]
    supporter_load = float(sum(supporter_masses)) if supporter_masses else None
    hard_on_soft_violation = bool(
        not bool(item.get("is_soft", False))
        and any(bool(supporter.is_soft) for supporter in selected_supporters)
    )
    hard_on_priority_violation = bool(
        not bool(item.get("is_prioritized", False))
        and any(bool(supporter.is_prioritized) for supporter in selected_supporters)
    )
    protection_violation = hard_on_soft_violation or hard_on_priority_violation
    mass = float(item.get("mass", 0.0))
    evidence = {
        "support_ratio": float(support_ratio),
        "center_support": bool(center_support),
        "predicted_drop": float(predicted_drop),
        "lower_landing_surface": lower_surface,
        "landing_surface": landing_surface,
        "landing_support": float(landing_support),
        "supporter_kind": supporter_kind,
        "supporter_pose": supporter_pose,
        "supporter_load": supporter_load,
        "hard_on_soft_violation": hard_on_soft_violation,
        "hard_on_priority_violation": hard_on_priority_violation,
        "protection_violation": protection_violation,
        "protection": not protection_violation,
        "stack_height": float(target.center[2] + world_half[2]),
        "mass": mass,
        "soft": bool(item.get("is_soft", False)),
        "prioritized": bool(item.get("is_prioritized", False)),
        "settling_gap": float(predicted_drop) if math.isfinite(predicted_drop) else math.inf,
    }
    return evidence, tuple(reasons)


def _score_evidence(
    container: Mapping[str, Any],
    item: Mapping[str, Any],
    settling: Mapping[str, Any],
    *,
    depth_map: Any = None,
    target: _OBB | None = None,
) -> dict[str, Any]:
    priority_violation = bool(settling.get("hard_on_priority_violation", False))
    soft_violation = bool(settling.get("hard_on_soft_violation", False))
    depth_consistent: bool | None = None
    depth_mean: float | None = None
    depth_std: float | None = None
    if depth_map is not None:
        try:
            depth_values = np.asarray(depth_map, dtype=np.float64)
            finite_values = depth_values[np.isfinite(depth_values)]
            if finite_values.size:
                depth_mean = float(np.mean(finite_values))
                depth_std = float(np.std(finite_values))
                target_height = float(target.center[2]) if target is not None else float(settling.get("stack_height", math.nan))
                if math.isfinite(target_height):
                    depth_consistent = bool(abs(target_height - depth_mean) <= max(0.05, depth_std))
        except (TypeError, ValueError):
            depth_consistent = None
    return {
        "priority_container": bool(container.get("is_prioritized", False)),
        "priority_violation": priority_violation,
        "soft_violation": soft_violation,
        "hard_on_soft_violation": soft_violation,
        "hard_on_priority_violation": priority_violation,
        "protection_violation": bool(settling.get("protection_violation", False)),
        "protection": bool(settling.get("protection", True)),
        "supporter_load": settling.get("supporter_load"),
        "cog_support": settling.get("center_support"),
        "support_ratio": settling.get("support_ratio"),
        "stack_height": settling.get("stack_height"),
        "depth_map_available": depth_consistent is not None,
        "depth_map_mean": depth_mean,
        "depth_map_std": depth_std,
        "depth_map_consistent": depth_consistent,
    }


def _binding_reasons(proposal: Any, observation: Any) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    evidence: dict[str, Any] = {
        "action_format": True,
        "action_position_range": False,
        "item_binding": False,
        "container_ordinal": False,
        "container_metadata": False,
        "orientation": False,
    }
    if not isinstance(proposal, ActionProposal):
        return ["action_format"], evidence
    if not _is_builtin_int(proposal.pool_ordinal) or not _is_builtin_int(proposal.container_ordinal) or not _is_builtin_int(proposal.orientation):
        reasons.append("action_format")
        evidence["action_format"] = False
    if not isinstance(proposal.item_index, int) or isinstance(proposal.item_index, bool):
        reasons.append("action_format")
    if not isinstance(proposal.container_metadata_index, int) or isinstance(proposal.container_metadata_index, bool):
        reasons.append("action_format")
    if len(proposal.position_f32_le) != 12:
        reasons.append("action_format")
    else:
        try:
            position = proposal.position
            if not all(math.isfinite(value) for value in position):
                reasons.append("action_format")
            elif not all(-100.0 <= value <= 100.0 for value in position):
                evidence["action_position_range"] = False
                reasons.append("action_position_range")
            else:
                evidence["action_position_range"] = True
        except Exception:
            reasons.append("action_format")
    if proposal.proposal_digest != _proposal_digest(proposal):
        reasons.append("proposal_digest")
    if not isinstance(observation, Mapping):
        reasons.append("state")
        return list(dict.fromkeys(reasons)), evidence
    pool = observation.get("pool_list")
    containers = observation.get("container_list")
    if not isinstance(pool, (list, tuple)) or not isinstance(containers, (list, tuple)):
        reasons.append("state")
        return list(dict.fromkeys(reasons)), evidence
    if _is_builtin_int(proposal.pool_ordinal) and 0 <= proposal.pool_ordinal < len(pool):
        item = pool[proposal.pool_ordinal]
        if type(item.get("index")) is int and item.get("index") == proposal.item_index and _item_signature(item) == proposal.item_signature:
            evidence["item_binding"] = True
        else:
            reasons.append("item_binding")
    else:
        reasons.append("item_binding")
    if _is_builtin_int(proposal.container_ordinal) and 0 <= proposal.container_ordinal < len(containers):
        container = containers[proposal.container_ordinal]
        evidence["container_ordinal"] = True
        if type(container.get("index")) is int and container.get("index") == proposal.container_metadata_index:
            evidence["container_metadata"] = True
        else:
            reasons.append("container_metadata")
    else:
        reasons.append("container_ordinal")
    if _is_builtin_int(proposal.orientation) and 0 <= proposal.orientation < len(ORIENTATION_PERMS):
        evidence["orientation"] = True
    else:
        reasons.append("action_format")
    return list(dict.fromkeys(reasons)), evidence


def _register(result: AuthorizationResult) -> AuthorizationResult:
    _RECEIPTS[id(result)] = result
    return result


def authorize_current(
    proposal: ActionProposal,
    observation: Mapping[str, Any],
    profile: Any = None,
    deadline: float | None = None,
) -> AuthorizationResult:
    """Authorize one proposal against the supplied current observation."""

    selected_profile = _profile_value(profile)
    try:
        pdigest = profile_digest(selected_profile)
    except Exception:
        pdigest = _digest({"invalid_profile": repr(selected_profile)})
    try:
        fingerprint = state_fingerprint(observation, selected_profile)
    except Exception:
        fingerprint = _digest({"invalid_observation": repr(observation), "profile": profile_semantics(selected_profile)})
    reasons: list[str] = []
    hard: dict[str, Any] = {
        "item_binding": False,
        "container_ordinal": False,
        "container_metadata": False,
        "container_eligibility": False,
        "action_position_range": False,
        "target_clear": False,
        "target_penetration": False,
        "plane_inclusion": False,
        "transport": False,
        "target_clearance": None,
        "transport_detail": {},
    }
    settling: dict[str, Any] = {}
    score: dict[str, Any] = {}
    if deadline is not None:
        try:
            if isinstance(deadline, (bool, np.bool_)) or not isinstance(deadline, numbers.Real) or not math.isfinite(float(deadline)) or time.perf_counter() >= float(deadline):
                reasons.append("deadline")
        except Exception:
            reasons.append("deadline")
    binding, binding_evidence = _binding_reasons(proposal, observation)
    reasons.extend(binding)
    hard.update(binding_evidence)
    if reasons:
        result = AuthorizationResult(False, proposal if isinstance(proposal, ActionProposal) else None, fingerprint, pdigest, hard, settling, score, tuple(dict.fromkeys(reasons)))
        return _register(result)
    item = observation["pool_list"][proposal.pool_ordinal]
    container = observation["container_list"][proposal.container_ordinal]
    try:
        position = proposal.position
        target = _target_obb(item, proposal.orientation, position)
        dimensions = _dimensions(item, proposal.orientation)
        container_eligible = all(float(value) > 0.0 for value in (container.get("length", 0), container.get("width", 0), container.get("height", 0)))
        hard["container_eligibility"] = container_eligible
        if not container_eligible:
            reasons.append("container_eligibility")
        plane_ok, plane_details = _plane_evidence(container, target, _profile_number(selected_profile, "inclusion_margin"))
        hard.update(plane_details)
        if not plane_ok:
            reasons.append("plane_inclusion")
        packed: list[_OBB] = []
        for packed_item in container.get("packed_items", []) or []:
            packed_obb = _packed_obb(packed_item, _container_offset_x(container))
            if packed_obb is not None:
                packed.append(packed_obb)
        shelves = _shelf_obbs(container)
        target_obstacles = list(packed) + [obstacle for obstacle, _name in shelves]
        target_separations = [_obb_separation(target, obstacle) for obstacle in target_obstacles]
        target_clearance = min(target_separations) if target_separations else math.inf
        hard["target_clearance"] = float(target_clearance)
        penetration_epsilon = _profile_number(selected_profile, "penetration_epsilon")
        hard["target_penetration"] = any(
            _obb_positive_overlap(target, obstacle, penetration_epsilon)
            for obstacle in target_obstacles
        )
        hard["target_clear"] = not hard["target_penetration"]
        if hard["target_penetration"]:
            reasons.append("target_penetration")
        transport_ok, transport_detail = _transport_path(container, item, target, proposal.orientation, packed, shelves, selected_profile)
        hard.update(transport_detail)
        hard["transport_detail"] = dict(transport_detail)
        if not transport_ok:
            reasons.append("transport")
        settling, settling_reasons = _settling_evidence(container, item, target, proposal.orientation, packed, shelves, selected_profile)
        settling["effective_lift"] = transport_detail.get("effective_lift")
        settling["transport_min_clearance"] = transport_detail.get("transport_min_clearance")
        reasons.extend(settling_reasons)
        score = _score_evidence(
            container,
            item,
            settling,
            depth_map=observation.get("depth_map"),
            target=target,
        )
    except Exception as error:
        hard["diagnostic_error"] = f"{type(error).__name__}: {error}"
        reasons.append("authorizer_error")
    unique_reasons = tuple(dict.fromkeys(reasons))
    result = AuthorizationResult(
        accepted=not unique_reasons,
        proposal=proposal,
        state_fingerprint=fingerprint,
        profile_digest=pdigest,
        hard_evidence=hard,
        settling_evidence=settling,
        score_evidence=score,
        reject_reasons=unique_reasons,
    )
    return _register(result)


def format_authorized_action(
    result: AuthorizationResult,
    observation: Mapping[str, Any],
    profile: Any = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Freshly reauthorize and format one official action dictionary."""

    if type(result) is not AuthorizationResult or _RECEIPTS.get(id(result)) is not result:
        raise AuthorizationError("authorization receipt is not owned by this authorizer")
    if type(result.accepted) is not bool or not result.accepted or result.proposal is None:
        raise AuthorizationError("only an accepted authorization receipt can format")
    fresh = authorize_current(result.proposal, observation, profile=profile, deadline=deadline)
    if not fresh.accepted:
        raise AuthorizationError(f"fresh authorization rejected: {fresh.reject_reasons}")
    if fresh.proposal != result.proposal:
        raise AuthorizationError("fresh proposal differs from receipt")
    if fresh.state_fingerprint != result.state_fingerprint:
        raise AuthorizationError("authorization state is stale")
    if fresh.profile_digest != result.profile_digest:
        raise AuthorizationError("authorization profile is stale")
    if dict(fresh.hard_evidence) != dict(result.hard_evidence):
        raise AuthorizationError("hard evidence differs from receipt")
    position = np.frombuffer(result.proposal.position_f32_le, dtype="<f4").copy()
    return {
        "item_idx": int(result.proposal.pool_ordinal),
        "container_idx": int(result.proposal.container_ordinal),
        "place_pos": position,
        "orientation": int(result.proposal.orientation),
    }


__all__ = [
    "ActionProposal",
    "AuthorizationError",
    "AuthorizationResult",
    "AuthorizerProfile",
    "ORIENTATION_PERMS",
    "ProposalError",
    "authorize_current",
    "format_authorized_action",
    "profile_digest",
    "profile_semantics",
    "proposal_from_action",
    "state_fingerprint",
]
