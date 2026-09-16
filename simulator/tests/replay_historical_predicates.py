"""Replay historical policy actions against the current strict validation profile.

This module is diagnostic only.  It never returns an action to a live
environment and never changes the production agent or strict thresholds.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SIMULATOR_ROOT.parent
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.geometry import (  # noqa: E402
    box_inside_planes,
    depth_map_path_clear,
    effective_transport_lift,
    oriented_dimensions,
    support_metrics,
    transport_path_clear,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import (  # noqa: E402
    ExactMask,
    RejectReason,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PackingState,
    PlacementProposal,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import (  # noqa: E402
    SearchSettings,
)
from agents.support_extreme_fusion_beam_exact_mask.state import (  # noqa: E402
    build_packing_state,
    state_fingerprint,
)
from tests.replay_support import load_observation_snapshot  # noqa: E402
from tests.run_support_extreme_fusion_physics import atomic_write_json  # noqa: E402


STATUS_KEYS = ("is_included", "is_valid", "is_placed_safe")
HASH_METADATA_KEYS = (
    "historical_source_sha256",
    "config_sha256",
    "runner_sha256",
    "action_sequence_sha256",
)
IDENTITY_KEYS = ("task", "seed", "requested_mode", "resolved_mode")
PREDICATE_KEYS = (
    "item_binding",
    "container_ordinal",
    "container_eligibility",
    "target_collision_clear",
    "plane_inclusion",
    "support_ratio",
    "center_support",
    "protection",
    "transport",
    "depth_map",
)


class ReplayIntegrityError(ValueError):
    """Raised when replay evidence cannot be proven internally consistent."""


def _status_known_safe(status: Any) -> bool:
    return isinstance(status, dict) and all(
        type(status.get(key)) is bool and status[key] for key in STATUS_KEYS
    )


def _unpack_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dictionary")
    if isinstance(snapshot.get("observation"), dict):
        observation = snapshot["observation"]
        metadata = snapshot.get("metadata", {})
    elif isinstance(snapshot.get("snapshot"), dict):
        observation = snapshot["snapshot"]
        metadata = snapshot.get("metadata", {})
    else:
        observation = snapshot
        metadata = snapshot.get("_capture_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return observation, metadata


def _float32_target(action: dict[str, Any]) -> np.ndarray:
    if not isinstance(action, dict):
        raise ValueError("action must be a dictionary")
    target = np.asarray(action["place_pos"], dtype=np.float32)
    if target.shape != (3,) or not np.all(np.isfinite(target)):
        raise ValueError("action place_pos must be a finite float32 vector")
    return target


def _strict_action_int(action: dict[str, Any], key: str) -> int:
    value = action[key]
    if type(value) is not int:
        raise ValueError(f"action {key} must be an integer")
    return value


def _depth_maps(observation: dict[str, Any], container_count: int) -> np.ndarray | None:
    value = observation.get("depth_map")
    if value is None:
        return None
    array = np.asarray(value)
    if array.ndim == 2 and container_count == 1:
        array = array[np.newaxis, ...]
    if array.ndim != 3 or array.shape[0] < container_count:
        return None
    return array


def _predicate_defaults() -> dict[str, bool]:
    return {key: False for key in PREDICATE_KEYS}


def _diagnose_predicates(
    state: PackingState,
    pool: Sequence[ItemSpec | dict],
    proposal: PlacementProposal | None,
    item: ItemSpec | None,
    mask: ExactMask,
) -> tuple[dict[str, bool], dict[str, float | None], str | None]:
    predicates = _predicate_defaults()
    metrics: dict[str, float | None] = {
        "support_ratio_value": None,
        "required_support": None,
        "min_clearance": None,
        "effective_lift": None,
    }
    detail: str | None = None
    if proposal is None or item is None:
        return predicates, metrics, detail

    matching = [
        container
        for container in state.containers
        if container.ordinal == proposal.container_index
    ]
    predicates["item_binding"] = (
        0 <= proposal.pool_index < len(pool)
        and item.index == proposal.item_index
        and (
            isinstance(pool[proposal.pool_index], ItemSpec)
            or isinstance(pool[proposal.pool_index], dict)
        )
    )
    predicates["container_ordinal"] = (
        len(matching) == 1
        and 0 <= proposal.container_index < len(state.containers)
        and state.containers[proposal.container_index] is matching[0]
    )
    if not predicates["container_ordinal"]:
        return predicates, metrics, detail
    container = matching[0]

    try:
        mask._check_container_eligibility(state, container, item)
        predicates["container_eligibility"] = True
    except Exception as error:
        detail = f"container_eligibility: {type(error).__name__}: {error}"

    try:
        dimensions = np.asarray(
            oriented_dimensions(item.dimensions, proposal.orientation),
            dtype=np.float64,
        )
        box = AABB.from_center_half(proposal.position, dimensions * 0.5)
    except Exception as error:
        detail = detail or f"target_geometry: {type(error).__name__}: {error}"
        return predicates, metrics, detail

    obstacles = [placed.box for placed in container.placed] + list(
        container.static_obstacles
    )
    predicates["target_collision_clear"] = not any(
        mask._collides_with_clearance(box, obstacle) for obstacle in obstacles
    )
    try:
        predicates["plane_inclusion"] = box_inside_planes(
            box.center,
            box.half,
            container.points,
            container.normals,
            mask.settings.inclusion_margin,
        )
    except Exception as error:
        detail = detail or f"plane_inclusion: {type(error).__name__}: {error}"

    floor_z = container.thickness + container.buffer
    shelf_top = (
        container.height / 2.0
        + container.thickness
        + container.buffer
    )
    support_layers = mask._support_layers(container, box, floor_z, shelf_top)
    measured_layers = [
        (
            *support_metrics(
                box.footprint,
                rectangles,
                mask.settings.center_support_margin,
            ),
            supporting_items,
        )
        for _height, rectangles, supporting_items in support_layers
    ]
    support_ratio = max((entry[0] for entry in measured_layers), default=0.0)
    required_support = (
        mask.settings.soft_support_ratio
        if item.is_soft
        else mask.settings.rigid_support_ratio
    )
    metrics["support_ratio_value"] = float(support_ratio)
    metrics["required_support"] = float(required_support)
    predicates["support_ratio"] = support_ratio + 1e-9 >= required_support
    predicates["center_support"] = any(entry[1] for entry in measured_layers)
    valid_layers = [
        entry
        for entry in measured_layers
        if entry[0] + 1e-9 >= required_support and entry[1]
    ]
    _accepted_ratio, _center_supported, supporting_items = max(
        valid_layers,
        key=lambda entry: entry[0],
        default=(0.0, False, []),
    )
    column_items = [
        placed.item
        for placed in container.placed
        if placed.box.maximum[2]
        <= box.minimum[2] + mask.settings.support_height_tolerance
        and box.footprint.intersection(placed.box.footprint) is not None
    ]
    predicates["protection"] = (
        mask._protection_violations(item, column_items or supporting_items) == 0
    )

    lift = effective_transport_lift(
        bottom_z=float(box.minimum[2]),
        top_z=float(box.maximum[2]),
        resting_surfaces=(floor_z, shelf_top),
        ceiling_surfaces=(
            container.height / 2.0 + container.buffer,
            container.height + container.buffer - container.thickness,
        ),
        requested_lift=0.08,
        ceiling_margin=mask.settings.path_clearance,
    )
    metrics["effective_lift"] = float(lift)
    half = box.half
    start_x_min = (
        -container.length / 2.0
        + container.thickness
        + container.cut_x
        + half[0]
        + 0.01
    )
    start_x_max = (
        container.length / 2.0 - container.thickness - half[0] - 0.01
    )
    if start_x_min <= start_x_max:
        start_x = min(max(float(box.center[0]), start_x_min), start_x_max)
        predicates["transport"] = transport_path_clear(
            box,
            obstacles,
            door_y=-container.width / 2.0 + half[1],
            start_x=start_x,
            lift=lift,
            clearance=mask.settings.path_clearance,
        )
        if container.depth_map is None:
            predicates["depth_map"] = True
        else:
            predicates["depth_map"] = depth_map_path_clear(
                box,
                [placed.box for placed in container.placed],
                container.depth_map,
                container_length=container.length,
                container_width=container.width,
                container_height=container.height,
                container_center_z=container.center[2],
                start_x=start_x,
                lift=lift,
                clearance=mask.settings.path_clearance,
                depth_tolerance=mask.settings.depth_tolerance,
                minimum_blocking_pixels=mask.settings.depth_min_blocking_pixels,
            )
    else:
        detail = detail or "transport: item cannot enter door aperture"
    if metrics["min_clearance"] is None:
        metrics["min_clearance"] = mask._minimum_horizontal_clearance(
            box, obstacles
        )
    return predicates, metrics, detail


def replay_action(
    snapshot: dict,
    action: dict,
    profile: SearchSettings | None = None,
) -> dict[str, object]:
    """Replay one saved action against the current strict validation profile."""

    observation, metadata = _unpack_snapshot(snapshot)
    status = copy.deepcopy(
        metadata.get("official_status", metadata.get("status"))
    )
    pool = observation.get("pool_list", [])
    container_list = observation.get("container_list", [])
    target: np.ndarray | None = None
    item_occurrence: int | None = None
    container_ordinal: int | None = None
    orientation: int | None = None
    item_index: int | None = None
    item: ItemSpec | None = None
    state: PackingState | None = None
    proposal: PlacementProposal | None = None
    trace = None
    predicates = _predicate_defaults()
    metrics: dict[str, float | None] = {
        "support_ratio_value": None,
        "required_support": None,
        "min_clearance": None,
        "effective_lift": None,
    }
    diagnostic_detail: str | None = None
    explicit_reason: str | None = None
    diagnostic_errors: list[dict[str, str]] = []
    settings = profile if profile is not None else SearchSettings()
    if not isinstance(settings, SearchSettings):
        raise TypeError("profile must be SearchSettings")
    mask = ExactMask(settings)
    depth_maps = _depth_maps(observation, len(container_list))

    try:
        target = _float32_target(action)
        item_occurrence = _strict_action_int(action, "item_idx")
        container_ordinal = _strict_action_int(action, "container_idx")
        orientation = _strict_action_int(action, "orientation")
        if item_occurrence < 0:
            explicit_reason = "item_binding"
            diagnostic_detail = "item occurrence must be non-negative"
        elif container_ordinal < 0:
            explicit_reason = "container_ordinal"
            diagnostic_detail = "container ordinal must be non-negative"
        elif not 0 <= orientation <= 5:
            explicit_reason = "action_format"
            diagnostic_detail = "action orientation must be in the range 0..5"
    except Exception as error:
        explicit_reason = "action_format"
        diagnostic_detail = f"{type(error).__name__}: {error}"

    if explicit_reason is None:
        try:
            state = build_packing_state(container_list, depth_maps)
            if item_occurrence is None or not 0 <= item_occurrence < len(pool):
                explicit_reason = "item_binding"
                diagnostic_detail = "item occurrence is outside the visible pool"
            else:
                raw_item = pool[item_occurrence]
                item = (
                    raw_item
                    if isinstance(raw_item, ItemSpec)
                    else ItemSpec.from_dict(raw_item)
                )
                item_index = int(item.index)
                proposal = PlacementProposal(
                    item_index=item_index,
                    pool_index=item_occurrence,
                    container_index=container_ordinal,
                    orientation=orientation,
                    position=tuple(float(value) for value in target),
                    source="historical-replay",
                )
                # ExactMask is authoritative.  The independent predicate
                # projection below is diagnostic-only and cannot replace its
                # decision if it fails.
                try:
                    trace = mask.diagnose(state, pool, proposal)
                except Exception as error:
                    diagnostic_errors.append(
                        {
                            "stage": "authoritative_exact_mask",
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                    explicit_reason = "authoritative_diagnostic_error"
                try:
                    predicates, metrics, diagnostic_detail = _diagnose_predicates(
                        state, pool, proposal, item, mask
                    )
                except Exception as error:
                    diagnostic_errors.append(
                        {
                            "stage": "independent_predicates",
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                    diagnostic_detail = diagnostic_detail or (
                        f"independent_predicates: {type(error).__name__}: {error}"
                    )
        except Exception as error:
            explicit_reason = explicit_reason or "item_binding"
            diagnostic_detail = diagnostic_detail or (
                f"{type(error).__name__}: {error}"
            )

    fingerprint: str | None = None
    if state is not None:
        try:
            fingerprint = state_fingerprint(
                state,
                pool,
                (
                    item_occurrence
                    if item_occurrence is not None
                    and 0 <= item_occurrence < len(pool)
                    else None
                ),
                mask.profile_digest,
            )
        except Exception as error:
            diagnostic_errors.append(
                {
                    "stage": "state_fingerprint",
                    "type": type(error).__name__,
                    "message": str(error),
                }
            )
            diagnostic_detail = diagnostic_detail or (
                f"state_fingerprint: {type(error).__name__}: {error}"
            )

    first_reason: str | None = explicit_reason
    exact_accepted = False
    exact_detail = ""
    if trace is not None:
        exact_accepted = bool(trace.accepted)
        first_reason = (
            trace.first_reason.value
            if isinstance(trace.first_reason, RejectReason)
            else (None if exact_accepted else "mask_reject")
        )
        exact_detail = str(trace.detail)
    elif first_reason is None:
        first_reason = "diagnostic_error"

    row: dict[str, object] = {
        "step": metadata.get("step"),
        "item_occurrence": item_occurrence,
        "item_index": item_index,
        "item_idx": item_occurrence,
        "container_ordinal": container_ordinal,
        "container_idx": container_ordinal,
        "orientation": orientation,
        "target_float32": (
            [float(value) for value in target] if target is not None else None
        ),
        "float32_target": (
            [float(value) for value in target] if target is not None else None
        ),
        "state_fingerprint": fingerprint,
        "profile_digest": mask.profile_digest,
        **{
            key: value
            for key, value in predicates.items()
            if key != "container_ordinal"
        },
        "container_ordinal_predicate": predicates["container_ordinal"],
        "container_ordinal_ok": predicates["container_ordinal"],
        **metrics,
        "exact_mask_accepted": exact_accepted,
        "exact_mask_first_reason": first_reason,
        "exact_mask_detail": exact_detail,
        "detail": diagnostic_detail or exact_detail,
        "official_status": status,
        "known_safe": _status_known_safe(status),
        "diagnostic_errors": diagnostic_errors,
    }
    row["predicate_results"] = {key: bool(value) for key, value in predicates.items()}
    return row


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_snapshot_path(raw_path: str | Path, manifest_path: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.is_file():
        return candidate.resolve()
    candidates = (
        manifest_path.parent / candidate,
        PROJECT_ROOT / candidate,
        Path.cwd() / candidate,
    )
    for value in candidates:
        if value.is_file():
            return value.resolve()
    raise FileNotFoundError(f"snapshot path does not exist: {raw_path}")


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ReplayIntegrityError(
            f"snapshot manifest is not valid JSON: {type(error).__name__}: {error}"
        ) from error
    if isinstance(payload, list):
        return {"snapshots": payload}
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshots"), list):
        raise ReplayIntegrityError(
            "snapshot manifest must contain an ordered snapshots list"
        )
    return payload


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _same_json(left: Any, right: Any) -> bool:
    return _canonical_digest(left) == _canonical_digest(right)


def _require_hash(value: Any, field: str, owner: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ReplayIntegrityError(f"{owner} has invalid {field}")
    normalized = value.lower()
    try:
        int(normalized, 16)
    except ValueError as error:
        raise ReplayIntegrityError(f"{owner} has invalid {field}") from error
    return normalized


def _episode_hashes(episode: dict[str, Any]) -> dict[str, str]:
    artifact = episode.get("historical_artifact")
    source = episode.get("historical_source_sha256")
    if source is None and isinstance(artifact, dict):
        source = artifact.get("source_sha256")
    if source is None:
        raise ReplayIntegrityError("episode has no historical source hash")
    values: dict[str, Any] = {
        "historical_source_sha256": source,
        "config_sha256": episode.get("config_sha256"),
        "runner_sha256": episode.get("runner_sha256"),
        "action_sequence_sha256": episode.get("action_sequence_sha256"),
    }
    result = {
        key: _require_hash(value, key, "episode")
        for key, value in values.items()
    }
    for alias_owner, alias_value in (
        ("episode", episode.get("source_sha256")),
        (
            "episode historical_artifact",
            artifact.get("source_sha256") if isinstance(artifact, dict) else None,
        ),
    ):
        if alias_value is not None and _require_hash(
            alias_value, "source_sha256", alias_owner
        ) != result["historical_source_sha256"]:
            raise ReplayIntegrityError(
                f"{alias_owner} source_sha256 does not match episode metadata"
            )
    return result


def _validate_replay_evidence(
    manifest_file: Path,
    episode_file: Path,
    manifest: dict[str, Any],
    episode: dict[str, Any],
) -> list[tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Validate all evidence before replaying any action.

    The returned tuples are ordered by the manifest's contiguous step index:
    ``(snapshot_path, observation, metadata, official_episode_record)``.
    """

    if not isinstance(episode, dict):
        raise ReplayIntegrityError("episode result must contain an object")
    manifest_digest = _sha256_file(manifest_file).lower()
    episode_manifest_digest = _require_hash(
        episode.get("snapshot_manifest_sha256"),
        "snapshot_manifest_sha256",
        "episode",
    )
    if manifest_digest != episode_manifest_digest:
        raise ReplayIntegrityError(
            "episode snapshot_manifest_sha256 does not match the manifest bytes"
        )
    snapshot_records = manifest.get("snapshots")
    if not isinstance(snapshot_records, list):
        raise ReplayIntegrityError("manifest snapshots must be a list")
    identity: dict[str, Any] = {}
    for key in IDENTITY_KEYS:
        if key not in manifest:
            raise ReplayIntegrityError(f"manifest is missing identity field {key}")
        identity[key] = manifest[key]
    for owner, payload in (("episode", episode),):
        for key, expected in identity.items():
            if key not in payload:
                raise ReplayIntegrityError(f"{owner} is missing identity field {key}")
            actual = payload[key]
            if type(actual) is not type(expected) or actual != expected:
                raise ReplayIntegrityError(
                    f"{owner} identity field {key} does not match manifest"
                )
    manifest_hashes = {
        key: _require_hash(manifest.get(key), key, "manifest")
        for key in HASH_METADATA_KEYS
    }
    episode_hashes = _episode_hashes(episode)
    if manifest_hashes != episode_hashes:
        raise ReplayIntegrityError(
            "manifest metadata hashes do not match episode metadata hashes"
        )

    steps: list[int] = []
    for index, record in enumerate(snapshot_records):
        if not isinstance(record, dict):
            raise ReplayIntegrityError(f"manifest snapshot record {index} is not an object")
        step = record.get("step")
        if isinstance(step, bool) or not isinstance(step, int):
            raise ReplayIntegrityError(f"manifest snapshot record {index} has invalid step")
        steps.append(int(step))
    expected_steps = list(range(len(snapshot_records)))
    if steps != expected_steps or len(set(steps)) != len(steps):
        raise ReplayIntegrityError(
            f"manifest steps must be contiguous and unique 0..N-1, got {steps}"
        )

    episode_records = episode.get("records")
    if not isinstance(episode_records, list) or len(episode_records) != len(snapshot_records):
        raise ReplayIntegrityError(
            "episode records count does not match manifest snapshot count"
        )
    episode_steps: list[int] = []
    for index, record in enumerate(episode_records):
        if not isinstance(record, dict):
            raise ReplayIntegrityError(f"episode record {index} is not an object")
        step = record.get("step")
        if isinstance(step, bool) or not isinstance(step, int):
            raise ReplayIntegrityError(f"episode record {index} has invalid step")
        episode_steps.append(int(step))
    if episode_steps != expected_steps:
        raise ReplayIntegrityError(
            f"episode steps must correspond to manifest steps 0..N-1, got {episode_steps}"
        )

    pre_action_snapshots = episode.get("pre_action_snapshots")
    if pre_action_snapshots is not None and pre_action_snapshots != snapshot_records:
        raise ReplayIntegrityError(
            "episode pre_action_snapshots do not correspond to manifest records"
        )

    tuples: list[tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    replay_actions: list[dict[str, Any]] = []
    for step, (manifest_record, episode_record) in enumerate(
        zip(snapshot_records, episode_records)
    ):
        try:
            snapshot_path = _resolve_snapshot_path(manifest_record.get("path"), manifest_file)
        except Exception as error:
            raise ReplayIntegrityError(
                f"snapshot step {step} is missing: {type(error).__name__}: {error}"
            ) from error
        expected_snapshot_digest = _require_hash(
            manifest_record.get("sha256"), "sha256", f"manifest snapshot {step}"
        )
        actual_snapshot_digest = _sha256_file(snapshot_path).lower()
        if actual_snapshot_digest != expected_snapshot_digest:
            raise ReplayIntegrityError(
                f"snapshot step {step} sha256 does not match manifest record"
            )
        try:
            observation, metadata = load_observation_snapshot(snapshot_path)
        except Exception as error:
            raise ReplayIntegrityError(
                f"snapshot step {step} is corrupt: {type(error).__name__}: {error}"
            ) from error
        if not isinstance(metadata, dict):
            raise ReplayIntegrityError(f"snapshot step {step} metadata is not an object")
        for key, expected in identity.items():
            if key not in metadata:
                raise ReplayIntegrityError(
                    f"snapshot step {step} is missing identity field {key}"
                )
            actual = metadata[key]
            if type(actual) is not type(expected) or actual != expected:
                raise ReplayIntegrityError(
                    f"snapshot step {step} identity field {key} does not match manifest"
                )
        if metadata.get("step") != step:
            raise ReplayIntegrityError(
                f"snapshot metadata step {metadata.get('step')!r} does not match {step}"
            )
        for key in HASH_METADATA_KEYS:
            metadata_value = metadata.get(key)
            if key == "historical_source_sha256" and metadata_value is None:
                metadata_value = metadata.get("source_sha256")
            metadata_hash = _require_hash(metadata_value, key, f"snapshot step {step}")
            if metadata_hash != manifest_hashes[key]:
                raise ReplayIntegrityError(
                    f"snapshot step {step} {key} does not match manifest metadata"
                )
        if "source_sha256" in metadata:
            source_alias = _require_hash(
                metadata["source_sha256"],
                "source_sha256",
                f"snapshot step {step}",
            )
            if source_alias != manifest_hashes["historical_source_sha256"]:
                raise ReplayIntegrityError(
                    f"snapshot step {step} source_sha256 does not match manifest metadata"
                )
        action = metadata.get("action")
        episode_action = episode_record.get("action")
        if not isinstance(action, dict) or not isinstance(episode_action, dict):
            raise ReplayIntegrityError(f"snapshot step {step} has no action correspondence")
        if not _same_json(action, episode_action):
            raise ReplayIntegrityError(
                f"snapshot step {step} action does not match episode record"
            )
        official_status = metadata.get("official_status", metadata.get("status"))
        episode_status = episode_record.get("status")
        if not _same_json(official_status, episode_status):
            raise ReplayIntegrityError(
                f"snapshot step {step} status does not match episode record"
            )
        for key in ("action", "status"):
            if key in manifest_record:
                expected = action if key == "action" else episode_status
                if not _same_json(manifest_record[key], expected):
                    raise ReplayIntegrityError(
                        f"manifest step {step} {key} does not match episode record"
                    )
        replay_actions.append(action)
        tuples.append((snapshot_path, observation, metadata, episode_record))

    expected_action_digest = _canonical_digest(replay_actions)
    if expected_action_digest != manifest_hashes["action_sequence_sha256"]:
        raise ReplayIntegrityError(
            "ordered snapshot actions do not match action_sequence_sha256"
        )
    return tuples


def replay_manifest(
    manifest_path: Path | str,
    episode_result_path: Path | str,
    *,
    profile: SearchSettings | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve(strict=True)
    episode_file = Path(episode_result_path).resolve(strict=True)
    manifest = _load_manifest(manifest_file)
    try:
        episode = json.loads(episode_file.read_text(encoding="utf-8"))
    except Exception as error:
        raise ReplayIntegrityError(
            f"episode result is not valid JSON: {type(error).__name__}: {error}"
        ) from error
    evidence = _validate_replay_evidence(
        manifest_file, episode_file, manifest, episode
    )
    rows: list[dict[str, object]] = []
    for _snapshot_path, observation, metadata, _episode_record in evidence:
        action = metadata["action"]
        rows.append(
            replay_action(
                {"observation": observation, "metadata": metadata}, action, profile
            )
        )

    first_reason_counts: Counter[str] = Counter()
    for row in rows:
        if bool(row["exact_mask_accepted"]):
            first_reason_counts[str(row["exact_mask_first_reason"] or "accepted")] += 1
        else:
            # Rejection aggregation is gated by the authoritative accepted
            # flag.  A diagnostic row with a missing reason can never become
            # an accepted count through ``None or 'accepted'`` coercion.
            first_reason_counts[str(row["exact_mask_first_reason"] or "diagnostic_error")] += 1
    known_safe_rows = [row for row in rows if bool(row["known_safe"])]
    known_safe_exact = [
        row for row in known_safe_rows if bool(row["exact_mask_accepted"])
    ]
    failed_rows = [row for row in rows if not bool(row["known_safe"])]
    failed_exact = [
        row for row in failed_rows if bool(row["exact_mask_accepted"])
    ]
    settings = profile if profile is not None else SearchSettings()
    artifact = episode.get("historical_artifact")
    artifact_source_sha256 = (
        artifact.get("source_sha256")
        if isinstance(artifact, dict)
        else manifest.get("historical_source_sha256")
    )
    output: dict[str, Any] = {
        "snapshot_manifest_path": str(manifest_file),
        "snapshot_manifest_sha256": _sha256_file(manifest_file),
        "episode_result_path": str(episode_file),
        "artifact_source_sha256": artifact_source_sha256,
        "artifact_manifest_sha256": (
            artifact.get("artifact_manifest_sha256")
            if isinstance(artifact, dict)
            else None
        ),
        "config_sha256": manifest.get("config_sha256"),
        "runner_sha256": manifest.get("runner_sha256"),
        "action_sequence_sha256": manifest.get("action_sequence_sha256"),
        "profile_digest": settings.profile_digest(),
        "accepted_action_count": sum(
            1 for row in rows if bool(row["exact_mask_accepted"])
        ),
        "first_reject_reason_counts": dict(sorted(first_reason_counts.items())),
        "known_safe_exact_mask_recall": {
            "numerator": len(known_safe_exact),
            "denominator": len(known_safe_rows),
        },
        "known_safe_exact_mask_recall_numerator": len(known_safe_exact),
        "known_safe_exact_mask_recall_denominator": len(known_safe_rows),
        "failed_action_acceptance": {
            "numerator": len(failed_exact),
            "denominator": len(failed_rows),
        },
        "failed_action_acceptance_numerator": len(failed_exact),
        "failed_action_acceptance_denominator": len(failed_rows),
        "rows": rows,
    }
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay historical snapshots against the current strict predicate mask"
    )
    parser.add_argument("manifest_positional", nargs="?")
    parser.add_argument("episode_positional", nargs="?")
    parser.add_argument(
        "--manifest",
        "--snapshot-manifest",
        dest="manifest",
        type=Path,
    )
    parser.add_argument(
        "--episode-result",
        "--episode",
        dest="episode_result",
        type=Path,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest or args.manifest_positional
    episode_result = args.episode_result or args.episode_positional
    if manifest is None or episode_result is None:
        raise SystemExit("manifest and episode result are required")
    result = replay_manifest(manifest, episode_result)
    atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
