"""Non-production three-mode runner for classifying the step-14 failure.

The runner deliberately sits outside the submitted agent and simulator.  It
saves the exact pre-action observation before stepping an entirely unwrapped
physical Agent.  After the episode and environment close, a fresh shadow Agent
replays each snapshot to reconstruct route/root evidence and run optional
catalog/probe diagnostics.  It can therefore be tested with injected fakes
without importing or launching PyBullet.
"""

from __future__ import annotations

import argparse
import copy
from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import inspect
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np


if __package__ in {None, ""}:
    _SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
    if str(_SIMULATOR_ROOT) not in sys.path:
        sys.path.insert(0, str(_SIMULATOR_ROOT))


SCHEMA_VERSION = 1
FORENSIC_MODES = ("control", "trace", "trace_probe")
ROUTE_NAMES = (
    "mpc",
    "online",
    "emergency_depth",
    "geometry_rescue",
    "deterministic_last_resort",
)
_STATUS_ORDER = ("is_included", "is_valid", "is_placed_safe")
_ACTION_KEYS = {"item_idx", "container_idx", "place_pos", "orientation"}


def _json_safe(value: Any) -> Any:
    """Convert NumPy/dataclass-like values into deterministic JSON values."""

    if isinstance(value, np.ndarray):
        return [_json_safe(child) for child in value.tolist()]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(child)
            for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": _json_safe(vars(value)),
        }
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_action(action: Any) -> dict[str, Any] | None:
    """Return the four public action fields in a stable representation."""

    if action is None or not isinstance(action, Mapping):
        return None
    try:
        position = np.asarray(action["place_pos"], dtype=np.float64)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            return None
        return {
            "item_idx": int(action["item_idx"]),
            "container_idx": int(action["container_idx"]),
            "place_pos": [float(value) for value in position],
            "orientation": int(action["orientation"]),
        }
    except (TypeError, ValueError, OverflowError):
        return None


def action_format_is_valid(action: Any) -> bool:
    """Check the public action shape without applying physical semantics."""

    if not isinstance(action, Mapping):
        return False
    try:
        position = np.asarray(action["place_pos"], dtype=np.float64)
        integer_values = (action["item_idx"], action["container_idx"], action["orientation"])
        return (
            set(action) == _ACTION_KEYS
            and isinstance(action["place_pos"], np.ndarray)
            and action["place_pos"].dtype == np.float32
            and position.shape == (3,)
            and bool(np.all(np.isfinite(position)))
            and all(isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)) for value in integer_values)
            and int(action["item_idx"]) >= 0
            and int(action["container_idx"]) >= 0
            and 0 <= int(action["orientation"]) < 6
        )
    except (TypeError, ValueError, KeyError, OverflowError):
        return False


def action_hash(action: Mapping[str, Any] | None) -> str:
    return sha256_json(canonical_action(action))


def action_sequence_hash(actions: Iterable[Mapping[str, Any] | None]) -> str:
    """Hash a whole action sequence, preserving step boundaries."""

    return sha256_json([canonical_action(action) for action in actions])


def _actions_from_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any] | None]:
    return [record.get("action") for record in records]


def compare_action_sequences(
    left: Sequence[Mapping[str, Any] | None] | Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any] | None] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Find the first differing action and provide sequence-level hashes.

    The function accepts either public action dictionaries or runner records.
    Runner records are detected by the presence of an ``action`` field.
    """

    left_values = _actions_from_records(left) if any("action" in row for row in left if isinstance(row, Mapping)) else list(left)  # type: ignore[arg-type]
    right_values = _actions_from_records(right) if any("action" in row for row in right if isinstance(row, Mapping)) else list(right)  # type: ignore[arg-type]
    first: int | None = None
    for index, (left_action, right_action) in enumerate(zip(left_values, right_values)):
        if canonical_action(left_action) != canonical_action(right_action):
            first = index
            break
    if first is None and len(left_values) != len(right_values):
        first = min(len(left_values), len(right_values))
    return {
        "first_divergent_step": first,
        "left_length": len(left_values),
        "right_length": len(right_values),
        "left_hash": action_sequence_hash(left_values),
        "right_hash": action_sequence_hash(right_values),
        "left_action": canonical_action(left_values[first]) if first is not None and first < len(left_values) else None,
        "right_action": canonical_action(right_values[first]) if first is not None and first < len(right_values) else None,
    }


def first_action_divergence(
    left: Sequence[Mapping[str, Any] | None] | Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any] | None] | Sequence[Mapping[str, Any]],
) -> int | None:
    """Small convenience wrapper returning only the first divergent step."""

    return compare_action_sequences(left, right)["first_divergent_step"]


def atomic_write_json(path: Path, value: Any) -> None:
    """Atomically replace a JSON result, including partial failure results."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(_json_safe(value), stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_save_snapshot(path: Path, observation: Mapping[str, Any], metadata: Mapping[str, Any] | None = None) -> None:
    """Atomically save a portable observation snapshot through ``replay_support``."""

    try:
        from .replay_support import save_observation_snapshot
    except ImportError:  # direct script execution
        from replay_support import save_observation_snapshot  # type: ignore

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        # save_observation_snapshot opens the temporary path and writes only
        # JSON/NumPy data; the caller never observes the temporary filename.
        save_observation_snapshot(temporary, copy.deepcopy(dict(observation)), dict(metadata or {}))
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def canonical_status(status: Any) -> dict[str, Any]:
    """Normalize simulator predicates into the official, stable key order."""

    if not isinstance(status, Mapping):
        return {"status_type_error": type(status).__name__}
    normalized = {str(key): value for key, value in status.items()}
    keys = list(_STATUS_ORDER)
    keys.extend(sorted(str(key) for key in normalized if str(key) not in keys))
    return {key: bool(normalized[key]) if key in normalized else None for key in keys}


def status_is_safe(status: Any) -> bool:
    if not status_format_is_valid(status):
        return False
    return all(bool(status[key]) for key in _STATUS_ORDER)


def status_format_is_valid(status: Any) -> bool:
    return bool(
        isinstance(status, Mapping)
        and all(key in status for key in _STATUS_ORDER)
        and all(isinstance(status[key], (bool, np.bool_)) for key in _STATUS_ORDER)
    )


def status_failure_reason(status: Any) -> str | None:
    """Report the first official failure predicate in canonical precedence."""

    if not status_format_is_valid(status):
        return "format_failure"
    if not bool(status.get("is_included")):
        return "inclusion_failure"
    if not bool(status.get("is_valid")):
        return "transport_failure"
    if not bool(status.get("is_placed_safe")):
        return "placement_failure"
    return None


def _candidate_payload(candidate: Any) -> dict[str, Any] | None:
    if candidate is None:
        return None
    fields = {}
    for name in (
        "pool_index",
        "container_index",
        "orientation",
        "position",
        "support_ratio",
        "min_clearance",
        "rule_violations",
        "secondary_score",
    ):
        if hasattr(candidate, name):
            fields[name] = getattr(candidate, name)
    return _json_safe(fields)


def _stable_candidate_key(candidate: Any) -> str | None:
    """Content-derived candidate key that is stable across fresh processes."""

    if not _looks_like_candidate(candidate):
        return None
    box = getattr(candidate, "box", None)
    payload = {
        "pool_index": int(candidate.pool_index),
        "item_index": getattr(getattr(candidate, "item", None), "index", None),
        "container_index": int(candidate.container_index),
        "orientation": int(candidate.orientation),
        "position": [round(float(value), 9) for value in candidate.position],
        "box_minimum": (
            [round(float(value), 9) for value in getattr(box, "minimum", ())]
            if box is not None
            else []
        ),
        "box_maximum": (
            [round(float(value), 9) for value in getattr(box, "maximum", ())]
            if box is not None
            else []
        ),
    }
    return sha256_json(payload)


def _looks_like_candidate(value: Any) -> bool:
    return value is not None and all(hasattr(value, name) for name in ("pool_index", "container_index", "orientation", "position"))


def _route_method_pairs(agent: Any) -> list[tuple[Any, str, str]]:
    pairs: list[tuple[Any, str, str]] = []
    planner = getattr(agent, "planner", None)
    if planner is not None:
        for method, route in (("choose_mpc", "mpc"), ("choose_online", "online")):
            if callable(getattr(planner, method, None)):
                pairs.append((planner, method, route))
    for method, route in (
        ("_depth_aware_emergency", "emergency_depth"),
        ("_geometry_rescue", "geometry_rescue"),
        ("_deterministic_last_resort", "deterministic_last_resort"),
    ):
        if callable(getattr(agent, method, None)):
            pairs.append((agent, method, route))
    return pairs


class RouteCapture:
    """Temporarily wrap the route methods on one Agent instance."""

    def __init__(self, agent: Any):
        self.agent = agent
        self._originals: list[tuple[Any, str, Any, bool, Any]] = []
        self._module_originals: list[tuple[Any, str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._catalog_events: list[dict[str, Any]] = []

    def __enter__(self) -> "RouteCapture":
        # planner.py imports build_root_catalog into a live module alias.  A
        # catalog module patch would miss the actual MPC call, so wrap this
        # alias and restore it with the route methods on exit.
        try:
            import agents.highscore.planner as planner_module

            original_catalog = getattr(planner_module, "build_root_catalog")

            def catalog_wrapped(*args: Any, __original=original_catalog, **kwargs: Any) -> Any:
                started = time.perf_counter()
                try:
                    roots = __original(*args, **kwargs)
                except Exception as error:
                    self._catalog_events.append(
                        {
                            "root_count": 0,
                            "root_candidate_keys": [],
                            "elapsed_seconds": time.perf_counter() - started,
                            "exception": f"{type(error).__name__}: {error}",
                        }
                    )
                    raise
                root_ids = []
                for root in roots or ():
                    candidate = getattr(root, "candidate", root)
                    root_ids.append(
                        {
                            "root_key": _stable_candidate_key(candidate),
                            "pool_index": getattr(candidate, "pool_index", None),
                            "item_index": getattr(getattr(candidate, "item", None), "index", None),
                        }
                    )
                self._catalog_events.append(
                    {
                        "root_count": len(root_ids),
                        "root_candidate_keys": root_ids,
                        "elapsed_seconds": time.perf_counter() - started,
                    }
                )
                return roots

            self._module_originals.append((planner_module, "build_root_catalog", original_catalog))
            setattr(planner_module, "build_root_catalog", catalog_wrapped)
        except Exception:
            # Minimal fake planners need not import production modules.
            self._restore()
        try:
            for owner, method_name, route in _route_method_pairs(self.agent):
                original = getattr(owner, method_name)
                own_attributes = vars(owner)
                self._originals.append(
                    (owner, method_name, original, method_name in own_attributes, own_attributes.get(method_name))
                )

                def wrapped(*args: Any, __original=original, __route=route, **kwargs: Any) -> Any:
                    started = time.perf_counter()
                    try:
                        result = __original(*args, **kwargs)
                    except Exception as error:
                        self.events.append(
                            {
                                "route": __route,
                                "candidate_present": False,
                                "returned_non_null": False,
                                "candidate": None,
                                "candidate_key": None,
                                "elapsed_seconds": time.perf_counter() - started,
                                "exception": f"{type(error).__name__}: {error}",
                                "root_catalog": _json_safe(self._catalog_events),
                            }
                        )
                        self._catalog_events.clear()
                        raise
                    candidate_key = _stable_candidate_key(result)
                    catalog = _json_safe(self._catalog_events)
                    root_keys = {
                        row.get("root_key")
                        for call in self._catalog_events
                        for row in call.get("root_candidate_keys", [])
                        if isinstance(row, Mapping)
                    }
                    self.events.append(
                        {
                            "route": __route,
                            "candidate_present": _looks_like_candidate(result),
                            "returned_non_null": result is not None,
                            "candidate": _candidate_payload(result) if _looks_like_candidate(result) else None,
                            "candidate_key": candidate_key,
                            "selected_root_key": candidate_key if candidate_key in root_keys else None,
                            "elapsed_seconds": time.perf_counter() - started,
                            "root_catalog": catalog,
                        }
                    )
                    self._catalog_events.clear()
                    return result

                setattr(owner, method_name, wrapped)
        except Exception:
            self._restore()
            raise
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self._restore()

    def _restore(self) -> None:
        errors: list[Exception] = []
        for owner, method_name, original, had_own_attribute, own_value in reversed(self._originals):
            try:
                if had_own_attribute:
                    setattr(owner, method_name, own_value)
                elif method_name in vars(owner):
                    delattr(owner, method_name)
            except Exception as error:
                errors.append(error)
        self._originals.clear()
        for owner, method_name, original in reversed(self._module_originals):
            try:
                setattr(owner, method_name, original)
            except Exception as error:
                errors.append(error)
        self._module_originals.clear()
        if errors:
            raise RuntimeError(f"failed to restore {len(errors)} forensic aliases") from errors[0]

    def consume_step(self) -> list[dict[str, Any]]:
        events = self.events
        self.events = []
        return events


def select_route(events: Sequence[Mapping[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("returned_non_null"):
            return str(event.get("route", "unknown"))
    if any(event.get("exception") for event in events):
        return "policy_exception"
    return "unknown"


def authoritative_candidate_present(events: Sequence[Mapping[str, Any]]) -> bool:
    route = select_route(events)
    return any(bool(event.get("candidate_present")) and event.get("route") == route for event in events)


def _default_shadow_exact_validation(
    observation: Mapping[str, Any],
    action: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    agent: Any,
) -> dict[str, Any]:
    """Best-effort offline exact validation, explicitly marked diagnostic."""

    result: dict[str, Any] = {"diagnostic_only": True, "checked": False, "accepted": None, "reason": "unavailable"}
    if action is None:
        result["reason"] = "policy_did_not_return_action"
        return result
    try:
        from agents.highscore.ems import ProxyAction
        from agents.highscore.geometry import oriented_dimensions
        from agents.highscore.model import AABB, ItemSpec
        from agents.highscore.state import build_packing_state

        pool = list(observation.get("pool_list", []))
        pool_index = int(action.get("item_idx", -1))
        if not 0 <= pool_index < len(pool):
            result["reason"] = "item_idx_out_of_range"
            return result
        item = ItemSpec.from_dict(pool[pool_index])
        orientation = int(action.get("orientation", -1))
        dimensions = np.asarray(oriented_dimensions(item.dimensions, orientation), dtype=np.float64)
        center = np.asarray(action.get("place_pos", ()), dtype=np.float64).reshape(3)
        state = build_packing_state(observation.get("container_list", []), observation.get("depth_map"))
        proxy = ProxyAction(
            item=item,
            pool_index=pool_index,
            container_index=int(action.get("container_idx", -1)),
            orientation=orientation,
            box=AABB.from_center_half(center, dimensions * 0.5),
            support_key=(int(action.get("container_idx", -1)), 0),
        )
        generator = getattr(getattr(agent, "planner", None), "generator", None)
        if generator is None:
            result["reason"] = "generator_unavailable"
            return result
        result["checked"] = True
        candidate = generator.validate_proposal(state, proxy)
        result["accepted"] = candidate is not None
        result["reason"] = "accepted" if candidate is not None else "validator_rejected"
        result["candidate"] = _candidate_payload(candidate)
    except Exception as error:
        result["reason"] = f"validation_error:{type(error).__name__}"
    return result


def _invoke_diagnostic(
    diagnose_fn: Callable[..., Any] | None,
    observation: Mapping[str, Any],
    *,
    observation_id: str,
    phase: str,
) -> Any:
    if diagnose_fn is None:
        return {"phase": phase, "skipped": True, "reason": "no_diagnostic_callback"}
    value = copy.deepcopy(dict(observation))
    try:
        signature = inspect.signature(diagnose_fn)
    except (TypeError, ValueError):
        signature = None
    accepts_phase = bool(
        signature is not None
        and (
            "phase" in signature.parameters
            or any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
        )
    )
    if accepts_phase:
        return diagnose_fn(value, observation_id=observation_id, phase=phase)
    return diagnose_fn(value, observation_id=observation_id)


def _initial_result(mode: str, *, seed: int | None, task: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "seed": seed,
        "task": task,
        "completed_steps": 0,
        "attempted_policy_records": 0,
        "first_failure_step": None,
        "terminated": False,
        "truncated": False,
        "records": [],
        "action_sequence_hash": action_sequence_hash([]),
        "failure_classification": "unresolved",
        "env_step_calls": 0,
        "safe_placement_count": 0,
        "final_packed_items": 0,
        "final_packed_item_indices": [],
    }


def _packed_item_indices(observation: Any) -> list[int]:
    if not isinstance(observation, Mapping):
        return []
    indices: list[int] = []
    for container in observation.get("container_list", []):
        if not isinstance(container, Mapping):
            continue
        for item in container.get("packed_items", []):
            if isinstance(item, Mapping) and isinstance(item.get("index"), (int, np.integer)):
                indices.append(int(item["index"]))
    return sorted(indices)


def _extract_collision_telemetry(info: Any) -> dict[str, Any]:
    """Preserve collision/contact evidence already exposed by the environment."""

    if not isinstance(info, Mapping):
        return {}
    selected = {}
    for key, value in info.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("collision", "contact", "body", "link")):
            selected[str(key)] = _json_safe(value)
    return selected


def run_forensic_episode(
    env: Any,
    agent: Any,
    *,
    mode: str = "control",
    seed: int | None = 42,
    task: str | None = None,
    max_steps: int | None = None,
    output_path: Path | None = None,
    snapshot_dir: Path | None = None,
    diagnose_fn: Callable[..., Any] | None = None,
    trace_fn: Callable[..., Any] | None = None,
    probe_fn: Callable[..., Any] | None = None,
    shadow_validator: Callable[[Mapping[str, Any], Mapping[str, Any] | None, Sequence[Mapping[str, Any]], Any], Any] | None = None,
    shadow_agent_factory: Callable[[], Any] | None = None,
    collision_telemetry_fn: Callable[[Any, Any, Mapping[str, Any]], Any] | None = None,
    depth_map_fn: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None,
    close_env: bool = True,
) -> dict[str, Any]:
    """Run one physical episode with diagnostics strictly after stepping.

    ``env`` and ``agent`` are injected so tests can exercise the ordering and
    partial-write guarantees without starting PyBullet.  This function does
    not import the simulator environment.
    """

    if mode not in FORENSIC_MODES:
        raise ValueError(f"mode must be one of {FORENSIC_MODES}, got {mode!r}")
    result = _initial_result(mode, seed=seed, task=task)
    snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else None
    output_path = Path(output_path) if output_path is not None else None
    records: list[dict[str, Any]] = result["records"]
    terminated = truncated = False
    observation: dict[str, Any] | None = None
    initial_states: dict[str, Any] = {}
    pending_diagnostics: list[tuple[dict[str, Any], Path | None, dict[str, Any], dict[str, Any] | None]] = []

    def persist() -> None:
        result["attempted_policy_records"] = len(records)
        result["completed_steps"] = int(result["safe_placement_count"])
        result["action_sequence_hash"] = action_sequence_hash(_actions_from_records(records))
        result["terminated"] = bool(terminated)
        result["truncated"] = bool(truncated)
        if output_path is not None:
            atomic_write_json(output_path, result)

    try:
        env.reset_settings()
        env.reset_item_stream()
        initial_states = copy.deepcopy(env.get_init_states())
        if not agent.get_init_states(initial_states):
            raise RuntimeError("get_init_states returned false")
        observation, _ = env.reset(seed=seed)
        packed_indices = _packed_item_indices(observation)
        result["final_packed_items"] = len(packed_indices)
        result["final_packed_item_indices"] = packed_indices

        # No method or catalog alias is wrapped in the physical loop.  Route
        # provenance is reconstructed from saved snapshots after env.close().
        while not (terminated or truncated):
            if max_steps is not None and len(records) >= max_steps:
                break
            if observation is None:
                raise RuntimeError("environment returned no observation")
            if depth_map_fn is not None:
                observation = depth_map_fn(observation, env)
            pre_observation = copy.deepcopy(observation)
            step_index = len(records)
            policy_started = time.perf_counter()
            action: Any = None
            policy_error: str | None = None
            try:
                action = agent.policy(observation)
            except Exception as error:
                policy_error = f"{type(error).__name__}: {error}"
            policy_elapsed = time.perf_counter() - policy_started
            format_valid = action_format_is_valid(action)
            public_action = canonical_action(action)

            snapshot_path: Path | None = None
            if snapshot_dir is not None:
                snapshot_path = snapshot_dir / f"step-{step_index:04d}.npz"
                atomic_save_snapshot(
                    snapshot_path,
                    pre_observation,
                    {
                        "mode": mode,
                        "task": task,
                        "seed": seed,
                        "step": step_index,
                        "policy_elapsed_seconds": policy_elapsed,
                        "action": public_action,
                        "action_format_valid": format_valid,
                    },
                )

            record: dict[str, Any] = {
                "step": step_index,
                "pre_action_observation_sha256": sha256_json(pre_observation),
                "pre_action_snapshot": str(snapshot_path) if snapshot_path is not None else None,
                "action": public_action,
                "raw_action": _json_safe(action),
                "action_format_valid": format_valid,
                "action_sha256": action_hash(public_action),
                "policy_elapsed_seconds": policy_elapsed,
                "route_events": [],
                "route": "pending_shadow_replay",
                "route_provenance": "diagnostic_shadow_replay",
                "authoritative_candidate_present": False,
                "candidate": None,
                "policy_error": policy_error,
                "item_pool_index": public_action.get("item_idx") if public_action is not None else None,
                "item_index": None,
                "post_policy_exact_validation": {"pending": True, "diagnostic_only": True},
            }
            if public_action is not None:
                pool = pre_observation.get("pool_list", [])
                pool_index = public_action["item_idx"]
                if 0 <= pool_index < len(pool) and isinstance(pool[pool_index], Mapping):
                    record["item_index"] = pool[pool_index].get("index")

            pending_diagnostics.append((record, snapshot_path, pre_observation, public_action))
            if policy_error is not None or not format_valid:
                record["status"] = canonical_status({})
                record["status_format_valid"] = False
                record["step_error"] = policy_error or "policy returned malformed action"
                record["failure_reason"] = (
                    "policy_timeout_or_exception" if policy_error is not None else "format_failure"
                )
                records.append(record)
                result["first_failure_step"] = step_index
                result["failure_classification"] = classify_failure(result)
                persist()
                break

            try:
                result["env_step_calls"] += 1
                step_stdout = io.StringIO()
                with redirect_stdout(step_stdout):
                    next_observation, _, terminated, truncated, info = env.step(action)
                validator_stdout_lines = [
                    line.strip() for line in step_stdout.getvalue().splitlines() if line.strip()
                ]
                collision_lines = [
                    line
                    for line in validator_stdout_lines
                    if "collision" in line.lower() or "contact" in line.lower()
                ]
                raw_status = info.get("status", {}) if isinstance(info, Mapping) else {}
                record["status"] = canonical_status(raw_status)
                record["status_format_valid"] = status_format_is_valid(raw_status)
                record["status_failure_reason"] = status_failure_reason(raw_status)
                record["environment_info"] = _json_safe(info)
                try:
                    collision_telemetry = _json_safe(
                        collision_telemetry_fn(env, action, info)
                        if collision_telemetry_fn is not None
                        else _extract_collision_telemetry(info)
                    )
                except Exception as telemetry_error:
                    collision_telemetry = {
                        "telemetry_error": f"{type(telemetry_error).__name__}: {telemetry_error}"
                    }
                if not isinstance(collision_telemetry, dict):
                    collision_telemetry = {"callback": collision_telemetry}
                collision_telemetry["stdout_collision_lines"] = collision_lines
                collision_telemetry["validator_stdout_lines"] = validator_stdout_lines
                evidence_keys = {
                    key
                    for key in collision_telemetry
                    if key not in {
                        "available",
                        "source",
                        "reason",
                        "telemetry_error",
                        "stdout_collision_lines",
                        "validator_stdout_lines",
                    }
                }
                telemetry_available = bool(collision_lines or evidence_keys)
                collision_telemetry["available"] = telemetry_available
                collision_telemetry["source"] = (
                    "callback+validator_stdout"
                    if collision_telemetry_fn is not None
                    else "environment_info+validator_stdout"
                )
                if not telemetry_available:
                    collision_telemetry["reason"] = (
                        collision_telemetry.get("telemetry_error")
                        or "no_collision_or_contact_evidence"
                    )
                record["collision_telemetry"] = collision_telemetry
                if status_is_safe(raw_status):
                    result["safe_placement_count"] += 1
                else:
                    result["first_failure_step"] = step_index
                packed_indices = _packed_item_indices(next_observation)
                result["final_packed_items"] = len(packed_indices)
                result["final_packed_item_indices"] = packed_indices
            except Exception as error:
                record["status"] = canonical_status({})
                record["status_format_valid"] = False
                record["step_error"] = f"{type(error).__name__}: {error}"
                record["failure_reason"] = "format_failure"
                record["collision_telemetry"] = {
                    "available": False,
                    "source": "env_step_exception",
                    "reason": "env_step_did_not_return_collision_telemetry",
                }
                result["first_failure_step"] = step_index
                next_observation = None

            records.append(record)
            if result["first_failure_step"] is not None:
                result["failure_classification"] = classify_failure(result)
                record["failure_reason"] = result["failure_classification"]
            persist()
            if result["first_failure_step"] is not None:
                break
            observation = next_observation
    except Exception as error:
        result["runner_error"] = f"{type(error).__name__}: {error}"
        if result["first_failure_step"] is None:
            result["first_failure_step"] = len(records)
        result["failure_classification"] = classify_failure(result)
        persist()
    finally:
        if close_env:
            try:
                env.close()
            except Exception as error:
                result["close_error"] = f"{type(error).__name__}: {error}"
        # The physical episode is over before route replay, validation, or
        # catalog/probe work starts.
        # Reload each atomic pre-action snapshot so diagnostics cannot share
        # mutable state or consume time inside the policy/step loop.
        if pending_diagnostics:
            try:
                try:
                    from .replay_support import load_observation_snapshot
                except ImportError:
                    from replay_support import load_observation_snapshot  # type: ignore
                for record, snapshot_path, fallback_observation, public_action in pending_diagnostics:
                    diagnostic_observation = copy.deepcopy(fallback_observation)
                    if snapshot_path is not None and snapshot_path.exists():
                        diagnostic_observation, _ = load_observation_snapshot(snapshot_path)
                    try:
                        if shadow_agent_factory is not None:
                            shadow_agent = shadow_agent_factory()
                        else:
                            shadow_agent = copy.deepcopy(agent)
                        if not shadow_agent.get_init_states(copy.deepcopy(initial_states)):
                            raise RuntimeError("shadow get_init_states returned false")
                        with RouteCapture(shadow_agent) as capture:
                            replay_started = time.perf_counter()
                            shadow_action_raw = shadow_agent.policy(copy.deepcopy(diagnostic_observation))
                            replay_elapsed = time.perf_counter() - replay_started
                            events = capture.consume_step()
                        for event in events:
                            event["diagnostic_only"] = True
                        shadow_action = canonical_action(shadow_action_raw)
                        action_match = shadow_action == public_action
                        record["route_events"] = _json_safe(events)
                        record["route"] = select_route(events) if action_match else "shadow_action_diverged"
                        record["route_provenance"] = "diagnostic_shadow_replay"
                        record["shadow_action"] = shadow_action
                        record["shadow_action_matches_physical"] = action_match
                        record["shadow_policy_elapsed_seconds"] = replay_elapsed
                        record["authoritative_candidate_present"] = bool(
                            action_match and authoritative_candidate_present(events)
                        )
                        record["shadow_authoritative_candidate_present"] = record[
                            "authoritative_candidate_present"
                        ]
                        record["candidate"] = next(
                            (event.get("candidate") for event in reversed(events) if event.get("candidate_present")),
                            None,
                        )
                    except Exception as error:
                        shadow_agent = agent
                        events = []
                        record["route"] = "shadow_replay_error"
                        record["route_provenance"] = "diagnostic_shadow_replay"
                        record["shadow_action_matches_physical"] = False
                        record["shadow_replay_error"] = f"{type(error).__name__}: {error}"
                    try:
                        record["post_policy_exact_validation"] = _json_safe(
                            shadow_validator(
                                copy.deepcopy(diagnostic_observation),
                                public_action,
                                copy.deepcopy(events),
                                shadow_agent,
                            )
                            if shadow_validator is not None
                            else _default_shadow_exact_validation(
                                copy.deepcopy(diagnostic_observation),
                                public_action,
                                copy.deepcopy(events),
                                shadow_agent,
                            )
                        )
                    except Exception as error:
                        record["post_policy_exact_validation"] = {
                            "diagnostic_only": True,
                            "checked": False,
                            "accepted": None,
                            "reason": f"validation_callback_error:{type(error).__name__}",
                        }
                    if mode in {"trace", "trace_probe"}:
                        try:
                            record.setdefault("diagnostics", {})["trace"] = _json_safe(
                                _invoke_diagnostic(
                                    trace_fn or diagnose_fn,
                                    diagnostic_observation,
                                    observation_id=f"step-{record['step']:04d}",
                                    phase="trace",
                                )
                            )
                        except Exception as error:
                            record.setdefault("diagnostics", {})["trace_error"] = f"{type(error).__name__}: {error}"
                    if mode == "trace_probe":
                        try:
                            record.setdefault("diagnostics", {})["probe"] = _json_safe(
                                _invoke_diagnostic(
                                    probe_fn or diagnose_fn,
                                    diagnostic_observation,
                                    observation_id=f"step-{record['step']:04d}",
                                    phase="probe",
                                )
                            )
                        except Exception as error:
                            record.setdefault("diagnostics", {})["probe_error"] = f"{type(error).__name__}: {error}"
                    result["failure_classification"] = classify_failure(result)
                    if result.get("first_failure_step") == record["step"]:
                        record["failure_reason"] = result["failure_classification"]
                    persist()
            except Exception as error:
                result["diagnostic_runner_error"] = f"{type(error).__name__}: {error}"
        result["attempted_policy_records"] = len(records)
        result["completed_steps"] = int(result["safe_placement_count"])
        result["failure_classification"] = classify_failure(result)
        persist()
    return _json_safe(result)


# Explicit name for callers that treat the module as the step-14 runner.
run_step14_forensics = run_forensic_episode


def run_three_mode_task(
    config: Mapping[str, Any],
    *,
    env_factory: Callable[[dict[str, Any]], Any],
    agent_factory: Callable[[], Any],
    configure_agent_fn: Callable[[Any], Any],
    task: str,
    seed: int,
    max_steps: int | None,
    output_path: Path,
    snapshot_root: Path,
    diagnose_fn: Callable[..., Any] | None = None,
    trace_fn: Callable[..., Any] | None = None,
    probe_fn: Callable[..., Any] | None = None,
    depth_map_fn: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run three fresh, physically unwrapped arms and write pairwise evidence."""

    output_path = Path(output_path)
    snapshot_root = Path(snapshot_root)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task": task,
        "seed": seed,
        "config_sha256": sha256_json(config),
        "physical_instrumentation": "unwrapped",
        "modes": {},
        "pairwise": {},
        "materialized_modes": [],
        "failed_modes": [],
        "complete": False,
        "success": False,
    }
    atomic_write_json(output_path, summary)
    pairs = (
        ("control", "trace"),
        ("control", "trace_probe"),
        ("trace", "trace_probe"),
    )

    def update_pairwise() -> None:
        for left, right in pairs:
            if left in summary["modes"] and right in summary["modes"]:
                summary["pairwise"][f"{left}__{right}"] = compare_action_sequences(
                    summary["modes"][left].get("records", []),
                    summary["modes"][right].get("records", []),
                )

    def update_summary_status() -> None:
        materialized = []
        failed = []
        for mode, arm in summary["modes"].items():
            has_error = bool(arm.get("runner_error") or arm.get("diagnostic_runner_error"))
            if has_error:
                failed.append(mode)
            elif isinstance(arm.get("records"), list):
                materialized.append(mode)
            else:
                failed.append(mode)
        summary["materialized_modes"] = [mode for mode in FORENSIC_MODES if mode in materialized]
        summary["failed_modes"] = [mode for mode in FORENSIC_MODES if mode in failed]
        succeeded = (
            set(summary["modes"]) == set(FORENSIC_MODES)
            and set(materialized) == set(FORENSIC_MODES)
            and not failed
        )
        summary["complete"] = succeeded
        summary["success"] = succeeded

    def new_agent() -> Any:
        return configure_agent_fn(agent_factory())

    for mode in FORENSIC_MODES:
        mode_output = output_path.parent / f"{output_path.stem}-{mode}.json"
        try:
            env = env_factory(copy.deepcopy(dict(config)))
            result = run_forensic_episode(
                env,
                new_agent(),
                mode=mode,
                seed=seed,
                task=task,
                max_steps=max_steps,
                output_path=mode_output,
                snapshot_dir=snapshot_root / mode,
                diagnose_fn=diagnose_fn,
                trace_fn=trace_fn,
                probe_fn=probe_fn,
                shadow_agent_factory=new_agent,
                depth_map_fn=depth_map_fn,
            )
        except Exception as error:
            result = {
                "schema_version": SCHEMA_VERSION,
                "mode": mode,
                "task": task,
                "seed": seed,
                "runner_error": f"{type(error).__name__}: {error}",
                "records": [],
                "first_failure_step": 0,
                "failure_classification": "runner_fallback",
            }
            atomic_write_json(mode_output, result)
        summary["modes"][mode] = result
        update_pairwise()
        update_summary_status()
        atomic_write_json(output_path, summary)

    update_summary_status()
    atomic_write_json(output_path, summary)
    return _json_safe(summary)


def _attach_shared_depth_map(observation: dict[str, Any], env: Any) -> dict[str, Any]:
    shared = getattr(env, "shm_depth_map", None)
    if shared is not None:
        observation["depth_map"] = shared.copy()
    return observation


def _configure_real_mpc_agent(agent: Any) -> Any:
    from agents.highscore.planner import Planner

    agent.settings = replace(agent.settings, use_mpc_mcts_ems=True)
    agent.planner = Planner(agent.settings)
    return agent


def _phase0_trace_only(observation: Mapping[str, Any], *, observation_id: str) -> dict[str, Any]:
    from agents.highscore.candidates import CandidateGenerator
    from agents.highscore.model import ItemSpec
    from agents.highscore.settings import SearchSettings
    from agents.highscore.state import build_packing_state
    try:
        from .quota_fair_starvation_diagnostics import trace_production_catalog
    except ImportError:
        from quota_fair_starvation_diagnostics import trace_production_catalog  # type: ignore

    settings = replace(SearchSettings(), use_mpc_mcts_ems=True)
    state = build_packing_state(observation.get("container_list", []), observation.get("depth_map"))
    pool = tuple(ItemSpec.from_dict(item) for item in observation.get("pool_list", []))
    trace = trace_production_catalog(
        state,
        pool,
        CandidateGenerator(settings),
        settings,
        deadline=time.perf_counter() + settings.ems_root_budget_seconds,
    )
    return {
        "observation_id": observation_id,
        "trace_rows": [row.__dict__ for row in trace.rows],
        "observed_catalog_budget_seconds": trace.observed_catalog_budget_seconds,
    }


def _phase0_probe(observation: Mapping[str, Any], *, observation_id: str) -> dict[str, Any]:
    try:
        from .run_quota_fair_phase0 import diagnose_observation
    except ImportError:
        from run_quota_fair_phase0 import diagnose_observation  # type: ignore

    result = diagnose_observation(dict(observation), observation_id=observation_id)
    return {
        "observation_id": result.get("observation_id", observation_id),
        "probes": result.get("probes", []),
        "recoverable": result.get("recoverable", False),
        "stop_reason_counts": result.get("stop_reason_counts", {}),
    }


def run_real_three_mode_task(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    all_config = json.loads((root / "configs" / "sample_config.json").read_text(encoding="utf-8"))
    if args.task not in all_config:
        raise ValueError(f"unknown task: {args.task}")
    config = copy.deepcopy(all_config[args.task])
    requested_items = min(int(args.items), len(config["item_stream"]["item_list"]))
    config["item_stream"]["item_list"] = config["item_stream"]["item_list"][:requested_items]
    config["item_stream"]["look_ahead"] = min(
        int(config["item_stream"].get("look_ahead", requested_items)), requested_items
    )
    config["agent"]["optimize"] = False
    config["visualizer"]["vis"] = False

    from agents.highscore.agent import Agent
    from src.ground_handling.env import GroundHandlingEnv

    return run_three_mode_task(
        config,
        env_factory=lambda value: GroundHandlingEnv(config=value, verbose=False, render_mode=None),
        agent_factory=lambda: Agent("agents/highscore/"),
        configure_agent_fn=_configure_real_mpc_agent,
        task=args.task,
        seed=args.seed,
        max_steps=requested_items,
        output_path=args.output,
        snapshot_root=args.snapshot_dir,
        trace_fn=_phase0_trace_only,
        probe_fn=_phase0_probe,
        depth_map_fn=_attach_shared_depth_map,
    )


def classify_failure(
    result: Mapping[str, Any],
    *,
    comparison: Mapping[str, Any] | None = None,
    control_result: Mapping[str, Any] | None = None,
) -> str:
    """Return the canonical causal label, without inferring score metrics."""

    if comparison is not None and comparison.get("first_divergent_step") is not None:
        if control_result is not None:
            control_failed = control_result.get("first_failure_step") is not None
            traced_failed = result.get("first_failure_step") is not None
            if traced_failed and not control_failed:
                return "diagnostic_interference"
    if result.get("runner_error"):
        return "runner_fallback"
    first = result.get("first_failure_step")
    records = result.get("records", [])
    if first is None or not isinstance(first, int) or not 0 <= first < len(records):
        return "unresolved"
    record = records[first]
    if record.get("policy_error"):
        return "policy_timeout_or_exception"
    elapsed = float(record.get("policy_elapsed_seconds", 0.0) or 0.0)
    if elapsed >= 6.0:
        return "policy_timeout_or_exception"
    action_valid = record.get("action_format_valid")
    if action_valid is False or (action_valid is None and canonical_action(record.get("action")) is None):
        return "format_failure"
    route = str(record.get("route", "unknown"))
    candidate = bool(record.get("authoritative_candidate_present"))
    status = record.get("status", {})
    if record.get("status_format_valid") is False or not status_format_is_valid(status):
        return "format_failure"
    if not bool(status.get("is_included")):
        return "inclusion_failure"
    if not bool(status.get("is_valid")):
        shadow_matches = record.get("shadow_action_matches_physical", True) is True
        if shadow_matches and route == "deterministic_last_resort" and not candidate:
            return "unchecked_last_resort_transport_defect"
        if shadow_matches and route in {"mpc", "online", "emergency_depth", "geometry_rescue"} and candidate:
            return "exact_or_emergency_candidate_safety_defect"
        return "transport_failure"
    if not bool(status.get("is_placed_safe")):
        return "placement_failure"
    return "unresolved"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fresh control/trace/trace_probe step-14 forensics")
    parser.add_argument("--task", default="001")
    parser.add_argument("--items", type=int, default=42)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run three fresh real environments with identical task/seed/MPC settings."""
    args = build_parser().parse_args(argv)
    result = run_real_three_mode_task(args)
    return 0 if bool(result.get("complete") and result.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
