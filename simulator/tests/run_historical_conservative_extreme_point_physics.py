"""Run the untouched 29.7 historical conservative extreme-point control.

This is a nonproduction diagnostic harness.  It loads the historical source
from its submitted artifact path without adding that module to ``sys.modules``
and delegates the official lifecycle, action guard, telemetry, snapshots, and
atomic result handling to the current physics runner.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import time
import traceback
from types import ModuleType
from typing import Any, Callable, Sequence

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SIMULATOR_ROOT.parent
ARTIFACT_PACKAGE_PATH = (
    PROJECT_ROOT / "submit" / "Conservative Extreme-Point Packing_score29.7" / "high_score"
).resolve()
ARTIFACT_AGENT_PATH = (ARTIFACT_PACKAGE_PATH / "agent.py").resolve()
ARTIFACT_SOURCE_SHA256 = (
    "EBE909962AB3A0722ABB5ED3E67A42DCEB64B116DD1F374C9EF739FDD3967F82"
)
ALGORITHM_NAME = "conservative_extreme_point_packing_historical_control"

from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    _save_failure_snapshot_atomic,
    atomic_write_json,
    materialize_config,
    run_episode,
)
from tests.replay_support import save_observation_snapshot  # noqa: E402


class HistoricalArtifactError(RuntimeError):
    """Raised when the historical source cannot be used unchanged."""


class HistoricalArtifactMutationError(HistoricalArtifactError):
    """Raised before an action/order escapes after artifact mutation."""


class HistoricalSnapshotCaptureError(HistoricalArtifactError):
    """Raised when post-episode capture evidence is not promotable."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


class HistoricalWorkerError(RuntimeError):
    """Raised when the isolated historical worker reports an exception."""


class HistoricalStageTimeout(TimeoutError):
    stage = "unknown"


class HistoricalInitTimeout(HistoricalStageTimeout):
    stage = "init"


class HistoricalOptimizationTimeout(HistoricalStageTimeout):
    stage = "optimization"


class HistoricalPolicyTimeout(HistoricalStageTimeout):
    stage = "policy"


class HistoricalPolicyCapture:
    """Parent-side references retained until the official episode has ended."""

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []


class HistoricalDiagnosticAgentProxy:
    """Forward the historical agent without probing live physics.

    The proxy intentionally stores only references while ``policy`` is being
    measured.  Snapshot copies and all filesystem work happen after
    ``run_episode`` returns in ``_materialize_policy_snapshots``.
    """

    def __init__(self, delegate: Any, capture: HistoricalPolicyCapture) -> None:
        self._delegate = delegate
        self._capture = capture

    def get_init_states(self, init_states: dict[str, Any]) -> Any:
        return self._delegate.get_init_states(init_states)

    def optimize(self, item_list: list[dict[str, Any]]) -> Any:
        return self._delegate.optimize(item_list)

    def policy(self, observation: dict[str, Any]) -> Any:
        evidence: list[Any] = [observation, None]
        self._capture.calls.append(evidence)
        action = self._delegate.policy(observation)
        evidence[1] = action
        return action

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


@dataclass(frozen=True)
class ArtifactSnapshot:
    source_path: Path
    source_bytes: bytes
    source_sha256: str
    manifest: tuple[tuple[Any, ...], ...]
    manifest_sha256: str


def _manifest_digest(manifest: tuple[tuple[Any, ...], ...]) -> str:
    encoded = json.dumps(manifest, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest().upper()


def capture_artifact_snapshot(
    path: Path = ARTIFACT_AGENT_PATH,
    expected_source_sha256: str | None = ARTIFACT_SOURCE_SHA256,
) -> ArtifactSnapshot:
    source_path = Path(path).resolve()
    if not source_path.is_file():
        raise HistoricalArtifactError(f"historical agent source is missing: {source_path}")
    root = source_path.parent
    source_bytes: bytes | None = None
    entries: list[tuple[Any, ...]] = []
    paths = (root,) + tuple(
        sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix())
    )
    for entry in paths:
        relative = "." if entry == root else entry.relative_to(root).as_posix()
        stat = entry.stat()
        if entry.is_dir():
            entries.append((relative, "directory", int(stat.st_size), int(stat.st_mtime_ns), None))
            continue
        if not entry.is_file():
            entries.append((relative, "other", int(stat.st_size), int(stat.st_mtime_ns), None))
            continue
        data = entry.read_bytes()
        digest = hashlib.sha256(data).hexdigest().upper()
        entries.append((relative, "file", int(stat.st_size), int(stat.st_mtime_ns), digest))
        if entry == source_path:
            source_bytes = data
    if source_bytes is None:
        raise HistoricalArtifactError("historical source disappeared during snapshot")
    source_digest = hashlib.sha256(source_bytes).hexdigest().upper()
    if (
        expected_source_sha256 is not None
        and source_digest != str(expected_source_sha256).upper()
    ):
        raise HistoricalArtifactError(
            "historical agent source digest changed; refusing a non-control run"
        )
    manifest = tuple(entries)
    return ArtifactSnapshot(
        source_path=source_path,
        source_bytes=source_bytes,
        source_sha256=source_digest,
        manifest=manifest,
        manifest_sha256=_manifest_digest(manifest),
    )


def artifact_metadata(
    path: Path = ARTIFACT_AGENT_PATH,
    expected_source_sha256: str | None = ARTIFACT_SOURCE_SHA256,
    *,
    snapshot: ArtifactSnapshot | None = None,
) -> dict[str, Any]:
    value = snapshot or capture_artifact_snapshot(path, expected_source_sha256)
    return {
        "algorithm_name": ALGORITHM_NAME,
        "package_path": value.source_path.parent.as_posix(),
        "agent_path": value.source_path.as_posix(),
        "source_sha256": value.source_sha256,
        "artifact_manifest_sha256": value.manifest_sha256,
        "artifact_file_set": [entry[0] for entry in value.manifest],
        "historical_source_untouched": True,
    }


def _capture_json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _capture_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=_capture_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _capture_file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _workspace_relative_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _serialize_capture_action(action: Any) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise TypeError("captured action must be a dictionary")
    position = np.asarray(action["place_pos"], dtype=np.float32)
    if position.shape != (3,):
        raise ValueError("captured action place_pos must have shape (3,)")
    if not np.all(np.isfinite(position)):
        raise ValueError("captured action place_pos must be finite")
    return {
        "item_idx": int(action["item_idx"]),
        "container_idx": int(action["container_idx"]),
        "place_pos": [float(value) for value in position],
        "orientation": int(action["orientation"]),
    }


def _save_observation_snapshot_atomic(
    path: Path | str,
    observation: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, str]:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".npz.tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
        save_observation_snapshot(temporary_path, observation, metadata)
        with temporary_path.open("rb+") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
        return {
            "path": _workspace_relative_path(target),
            "sha256": _capture_file_digest(target),
        }
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _validate_capture_consistency(
    result: dict[str, Any], capture: HistoricalPolicyCapture
) -> list[dict[str, Any]]:
    """Require one complete, ordered official record per captured policy call."""

    calls = capture.calls
    records = result.get("records")
    details: dict[str, Any] = {
        "policy_call_count": len(calls),
        "official_record_count": len(records) if isinstance(records, list) else None,
        "status_count": 0,
        "mismatches": [],
    }
    mismatches = details["mismatches"]
    if not isinstance(records, list):
        mismatches.append({"kind": "official_records", "message": "records is not a list"})
    elif len(calls) != len(records):
        mismatches.append(
            {
                "kind": "count",
                "message": "policy calls and official records have different counts",
                "policy_call_count": len(calls),
                "official_record_count": len(records),
            }
        )
    if not isinstance(records, list):
        raise HistoricalSnapshotCaptureError(
            "capture evidence is not promotable", details
        )

    serialized_actions: list[dict[str, Any]] = []
    for step, evidence in enumerate(calls):
        if not isinstance(evidence, list) or len(evidence) != 2:
            mismatches.append(
                {"kind": "call_shape", "step": step, "message": "capture call is incomplete"}
            )
            continue
        try:
            serialized_actions.append(_serialize_capture_action(evidence[1]))
        except Exception as error:
            mismatches.append(
                {
                    "kind": "captured_action",
                    "step": step,
                    "type": type(error).__name__,
                    "message": str(error),
                }
            )
            continue
        if step >= len(records):
            continue
        record = records[step]
        if not isinstance(record, dict):
            mismatches.append(
                {"kind": "official_record", "step": step, "message": "record is not an object"}
            )
            continue
        if record.get("step") != step:
            mismatches.append(
                {
                    "kind": "step",
                    "step": step,
                    "official_step": record.get("step"),
                }
            )
        if "status" not in record:
            mismatches.append(
                {"kind": "status", "step": step, "message": "official status is missing"}
            )
        else:
            details["status_count"] += 1
        official_action = record.get("action")
        if not isinstance(official_action, dict):
            mismatches.append(
                {"kind": "official_action", "step": step, "message": "official action is missing"}
            )
        else:
            try:
                normalized_official = _serialize_capture_action(official_action)
                if _capture_digest(normalized_official) != _capture_digest(
                    serialized_actions[-1]
                ):
                    mismatches.append(
                        {"kind": "action", "step": step, "message": "captured action differs from official action"}
                    )
            except Exception as error:
                mismatches.append(
                    {
                        "kind": "official_action",
                        "step": step,
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                )
    if details["status_count"] != len(records):
        mismatches.append(
            {
                "kind": "status_count",
                "status_count": details["status_count"],
                "official_record_count": len(records),
            }
        )
    if mismatches:
        raise HistoricalSnapshotCaptureError(
            "capture evidence is not promotable", details
        )
    return serialized_actions


def _materialize_policy_snapshots(
    result: dict[str, Any],
    capture: HistoricalPolicyCapture,
    capture_directory: Path | str,
    *,
    config: dict[str, Any],
    task: str,
    seed: int,
    requested_mode: str,
    before_snapshot: ArtifactSnapshot,
) -> None:
    directory = Path(capture_directory).resolve()
    calls = capture.calls
    records = result.get("records", ())
    serialized_actions = _validate_capture_consistency(result, capture)
    action_sequence_sha256 = _capture_digest(serialized_actions)
    config_sha256 = _capture_digest(config)
    runner_sha256 = _capture_file_digest(Path(__file__).resolve())
    source_sha256 = before_snapshot.source_sha256.lower()
    snapshots: list[dict[str, Any]] = []

    for step, evidence in enumerate(calls):
        observation_ref, action_ref = evidence
        action = serialized_actions[step]
        official_record = records[step] if step < len(records) else {}
        official_status = (
            copy.deepcopy(official_record.get("status"))
            if isinstance(official_record, dict)
            else None
        )
        metadata = {
            "task": str(task),
            "seed": int(seed),
            "requested_mode": str(requested_mode),
            "resolved_mode": result.get("resolved_mode"),
            "step": int(step),
            "action": copy.deepcopy(action),
            "official_status": official_status,
            "status": copy.deepcopy(official_status),
            "historical_source_sha256": source_sha256,
            "source_sha256": source_sha256,
            "config_sha256": config_sha256,
            "runner_sha256": runner_sha256,
            "action_sequence_sha256": action_sequence_sha256,
        }
        snapshot_path = directory / f"step-{step:03d}.npz"
        # The first deep copy is deliberately after run_episode has returned.
        snapshot = copy.deepcopy(observation_ref)
        saved = _save_observation_snapshot_atomic(snapshot_path, snapshot, metadata)
        snapshots.append(
            {
                "step": int(step),
                "action": copy.deepcopy(action),
                "status": copy.deepcopy(official_status),
                **saved,
            }
        )

    manifest_path = directory / "manifest.json"
    manifest_payload = {
        "task": str(task),
        "seed": int(seed),
        "requested_mode": str(requested_mode),
        "resolved_mode": result.get("resolved_mode"),
        "historical_source_sha256": source_sha256,
        "config_sha256": config_sha256,
        "runner_sha256": runner_sha256,
        "action_sequence_sha256": action_sequence_sha256,
        "snapshots": snapshots,
    }
    atomic_write_json(manifest_path, manifest_payload)
    manifest_sha256 = _capture_file_digest(manifest_path)
    result["pre_action_snapshots"] = snapshots
    result["snapshot_manifest_path"] = _workspace_relative_path(manifest_path)
    result["snapshot_manifest_sha256"] = manifest_sha256
    result["historical_source_sha256"] = source_sha256
    result["config_sha256"] = config_sha256
    result["runner_sha256"] = runner_sha256
    result["action_sequence_sha256"] = action_sequence_sha256
    result["snapshot_manifest"] = {
        "path": _workspace_relative_path(manifest_path),
        "sha256": manifest_sha256,
    }
    diagnostic = result.setdefault("diagnostic", {})
    diagnostic["capture_enabled"] = True
    diagnostic["promotable"] = True


def _agent_type_from_exact_bytes(source_bytes: bytes, source_path: Path) -> type:
    digest = hashlib.sha256(source_bytes).hexdigest().upper()
    module_name = (
        "_isolated_historical_conservative_extreme_point_"
        + digest[:16].lower()
    )
    module = ModuleType(module_name)
    module.__file__ = str(source_path)
    module.__package__ = ""
    code = compile(source_bytes, str(source_path), "exec")
    exec(code, module.__dict__)
    agent_type = getattr(module, "Agent", None)
    if not isinstance(agent_type, type):
        raise HistoricalArtifactError("historical source has no Agent class")
    for method_name in ("get_init_states", "optimize", "policy"):
        if not callable(getattr(agent_type, method_name, None)):
            raise HistoricalArtifactError(
                f"historical Agent is missing public method {method_name}"
            )
    return agent_type


def load_historical_agent_type(
    path: Path = ARTIFACT_AGENT_PATH,
    expected_source_sha256: str | None = ARTIFACT_SOURCE_SHA256,
) -> type:
    snapshot = capture_artifact_snapshot(path, expected_source_sha256)
    return _agent_type_from_exact_bytes(snapshot.source_bytes, snapshot.source_path)


def _historical_worker(
    connection: Any,
    source_bytes: bytes,
    source_path: str,
    package_path: str,
) -> None:
    try:
        agent_type = _agent_type_from_exact_bytes(source_bytes, Path(source_path))
        agent = agent_type(package_path)
    except BaseException:
        try:
            connection.send(("startup_error", traceback.format_exc()))
        finally:
            connection.close()
        return
    try:
        while True:
            try:
                message = connection.recv()
            except EOFError:
                return
            if not isinstance(message, tuple) or not message:
                continue
            if message[0] == "close":
                return
            if message[0] != "call" or len(message) != 4:
                continue
            _, method_name, args, kwargs = message
            try:
                if method_name not in {"get_init_states", "optimize", "policy"}:
                    raise AttributeError(f"method not allowed: {method_name}")
                result = getattr(agent, method_name)(*args, **kwargs)
                connection.send(("ok", result))
            except BaseException:
                connection.send(("error", traceback.format_exc()))
    finally:
        connection.close()


class HistoricalTimedAgentProxy:
    """Persistent spawn worker with official per-method timeout boundaries."""

    _TIMEOUT_TYPES = {
        "get_init_states": HistoricalInitTimeout,
        "optimize": HistoricalOptimizationTimeout,
        "policy": HistoricalPolicyTimeout,
    }

    def __init__(
        self,
        snapshot: ArtifactSnapshot,
        *,
        init_timeout: float,
        optimization_timeout: float,
        policy_timeout: float,
    ) -> None:
        for name, value in (
            ("init_timeout", init_timeout),
            ("optimization_timeout", optimization_timeout),
            ("policy_timeout", policy_timeout),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        self._snapshot = snapshot
        self._timeouts = {
            "get_init_states": float(init_timeout),
            "optimize": float(optimization_timeout),
            "policy": float(policy_timeout),
        }
        self.timeout_stage: str | None = None
        self.timeout_observation: dict[str, Any] | None = None
        self.closed = False
        self._initial_state: dict[str, Any] | None = None
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=_historical_worker,
            args=(
                child,
                snapshot.source_bytes,
                str(snapshot.source_path),
                str(snapshot.source_path.parent),
            ),
            daemon=True,
        )
        process.start()
        child.close()
        self._connection = parent
        self._process = process

    def _assert_artifact_unchanged(self) -> None:
        try:
            current = capture_artifact_snapshot(
                self._snapshot.source_path, self._snapshot.source_sha256
            )
        except Exception as error:
            raise HistoricalArtifactMutationError(str(error)) from error
        if current.manifest != self._snapshot.manifest:
            raise HistoricalArtifactMutationError(
                "historical artifact file set or metadata changed during worker call"
            )

    def _observation_for_timeout(
        self, method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        if method_name == "policy":
            value = kwargs.get("observation", args[0] if args else {})
            return copy.deepcopy(value) if isinstance(value, dict) else {}
        if method_name == "get_init_states":
            value = kwargs.get("init_states", args[0] if args else {})
            if isinstance(value, dict):
                self._initial_state = copy.deepcopy(value)
                return {
                    "container_list": copy.deepcopy(value.get("container_list", [])),
                    "pool_list": [],
                    "optimize": bool(value.get("optimize", False)),
                    "lookahead_k": int(value.get("lookahead_k", 1)),
                }
            return {}
        items = kwargs.get("item_list", args[0] if args else [])
        initial = self._initial_state or {}
        return {
            "container_list": copy.deepcopy(initial.get("container_list", [])),
            "pool_list": copy.deepcopy(items),
            "optimize": True,
            "lookahead_k": len(items) if isinstance(items, Sequence) else 1,
        }

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        if self.closed:
            raise HistoricalWorkerError("historical worker is closed")
        self._assert_artifact_unchanged()
        try:
            self._connection.send(("call", method_name, args, kwargs))
        except Exception as error:
            raise HistoricalWorkerError(f"historical worker send failed: {error}") from error
        timeout = self._timeouts[method_name]
        if not self._connection.poll(timeout):
            timeout_type = self._TIMEOUT_TYPES[method_name]
            self.timeout_stage = timeout_type.stage
            self.timeout_observation = self._observation_for_timeout(
                method_name, args, kwargs
            )
            self.close()
            raise timeout_type(
                f"historical {self.timeout_stage} timeout after {timeout:.3f}s"
            )
        status, payload = self._connection.recv()
        self._assert_artifact_unchanged()
        if status == "ok":
            if method_name == "get_init_states":
                self._observation_for_timeout(method_name, args, kwargs)
            return payload
        raise HistoricalWorkerError(
            f"historical worker {method_name} failed:\n{payload}"
        )

    def get_init_states(self, init_states: dict[str, Any]) -> Any:
        return self._call("get_init_states", init_states=init_states)

    def optimize(self, item_list: list[dict[str, Any]]) -> Any:
        return self._call("optimize", item_list=item_list)

    def policy(self, observation: dict[str, Any]) -> Any:
        return self._call("policy", observation=observation)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._connection.send(("close",))
        except Exception:
            pass
        try:
            self._connection.close()
        except Exception:
            pass
        if self._process.is_alive():
            self._process.kill()
        self._process.join(timeout=1.0)


def run_historical_episode(
    config: dict[str, Any],
    *,
    requested_items: int = 41,
    seed: int = 42,
    env_factory: Callable[[dict[str, Any]], Any] | None = None,
    agent_factory: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    snapshot_on_failure: Path | str | None = None,
    capture_all_snapshots: Path | str | None = None,
    artifact_agent_path: Path = ARTIFACT_AGENT_PATH,
    expected_source_sha256: str = ARTIFACT_SOURCE_SHA256,
) -> dict[str, Any]:
    before_snapshot = capture_artifact_snapshot(
        artifact_agent_path, expected_source_sha256
    )
    before_metadata = artifact_metadata(
        artifact_agent_path,
        expected_source_sha256,
        snapshot=before_snapshot,
    )
    proxy: HistoricalTimedAgentProxy | None = None
    policy_capture: HistoricalPolicyCapture | None = None
    if agent_factory is None:
        agent_settings = config.get("agent", {})
        proxy = HistoricalTimedAgentProxy(
            before_snapshot,
            init_timeout=float(agent_settings.get("init_timeout", 10.0)),
            optimization_timeout=float(
                agent_settings.get("optimization_timeout", 180.0)
            ),
            policy_timeout=float(agent_settings.get("policy_timeout", 8.0)),
        )
        agent_factory = lambda: proxy
    if capture_all_snapshots is not None:
        policy_capture = HistoricalPolicyCapture()
        base_agent_factory = agent_factory

        def diagnostic_agent_factory() -> HistoricalDiagnosticAgentProxy:
            return HistoricalDiagnosticAgentProxy(
                base_agent_factory(), policy_capture
            )

        agent_factory = diagnostic_agent_factory
    kwargs: dict[str, Any] = {
        "task": "000",
        "requested_items": int(requested_items),
        "seed": int(seed),
        "requested_mode": "A",
        "agent_factory": agent_factory,
        "clock": clock,
        "snapshot_on_failure": snapshot_on_failure,
    }
    if env_factory is not None:
        kwargs["env_factory"] = env_factory
    try:
        result = run_episode(config, **kwargs)
    finally:
        if proxy is not None:
            proxy.close()

    if policy_capture is not None:
        try:
            _materialize_policy_snapshots(
                result,
                policy_capture,
                capture_all_snapshots,
                config=config,
                task="000",
                seed=int(seed),
                requested_mode="A",
                before_snapshot=before_snapshot,
            )
        except Exception as error:
            result["snapshot_capture_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            if isinstance(error, HistoricalSnapshotCaptureError):
                result["snapshot_capture_error"]["details"] = copy.deepcopy(
                    error.details
                )
            result.setdefault("diagnostic", {})["capture_enabled"] = True
            result["diagnostic"]["promotable"] = False

    artifact_changed = False
    try:
        after_snapshot = capture_artifact_snapshot(artifact_agent_path, None)
        artifact_changed = after_snapshot.manifest != before_snapshot.manifest
        after_manifest_sha256: str | None = after_snapshot.manifest_sha256
    except Exception:
        artifact_changed = True
        after_manifest_sha256 = None

    if proxy is not None and proxy.timeout_stage is not None:
        timeout_outcome = f"{proxy.timeout_stage}_timeout"
        result["outcome"] = timeout_outcome
        result["all_safe"] = False
        if isinstance(result.get("exception"), dict):
            result["exception"]["category"] = timeout_outcome
        if snapshot_on_failure is not None:
            timeout_observation = proxy.timeout_observation or {}
            result["failure_snapshot"] = _save_failure_snapshot_atomic(
                snapshot_on_failure,
                timeout_observation,
                {
                    "task": "000",
                    "seed": int(seed),
                    "requested_mode": "A",
                    "resolved_mode": result.get("resolved_mode"),
                    "step": len(result.get("records", ())),
                    "failure_kind": "agent_timeout",
                    "timeout_stage": proxy.timeout_stage,
                    "exception_type": (
                        result.get("exception", {}).get("type")
                        if isinstance(result.get("exception"), dict)
                        else None
                    ),
                },
            )

    exception_type = (
        result.get("exception", {}).get("type")
        if isinstance(result.get("exception"), dict)
        else None
    )
    if artifact_changed or exception_type == "HistoricalArtifactMutationError":
        result["outcome"] = "artifact_mutation"
        result["all_safe"] = False
        if not isinstance(result.get("exception"), dict):
            result["exception"] = {
                "type": "HistoricalArtifactMutationError",
                "message": "historical artifact changed during the run",
                "step": len(result.get("records", ())),
            }
        result["exception"]["category"] = "artifact_mutation"
        result["exception"]["type"] = "HistoricalArtifactMutationError"

    result["algorithm_name"] = ALGORITHM_NAME
    result["agent_module"] = "historical_file_isolated"
    result["historical_artifact"] = before_metadata
    result["historical_artifact"]["historical_source_untouched"] = (
        not artifact_changed
    )
    result["historical_artifact_integrity"] = {
        "before_manifest_sha256": before_snapshot.manifest_sha256,
        "after_manifest_sha256": after_manifest_sha256,
        "unchanged": not artifact_changed,
    }
    result["historical_worker"] = {
        "enabled": proxy is not None,
        "closed": True if proxy is None else proxy.closed,
        "timeout_stage": None if proxy is None else proxy.timeout_stage,
    }
    return result


def write_result_atomic(path: Path | str, result: dict[str, Any]) -> None:
    atomic_write_json(path, result)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the untouched conservative extreme-point historical "
            "control on official task000 Mode A"
        )
    )
    parser.add_argument("--task", choices=("000",), default="000")
    parser.add_argument("--items", type=_positive_int, default=41)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-on-failure", type=Path)
    parser.add_argument(
        "--capture-all-snapshots",
        type=Path,
        help="post-episode directory for every exact pre-action observation",
    )
    return parser


def _minimal_failure(args: argparse.Namespace, error: BaseException) -> dict[str, Any]:
    try:
        historical_artifact: dict[str, Any] | None = artifact_metadata()
    except Exception:
        historical_artifact = None
    return {
        "task": "000",
        "requested_items": int(args.items),
        "effective_items": 0,
        "seed": int(args.seed),
        "requested_mode": "A",
        "resolved_mode": None,
        "algorithm_name": ALGORITHM_NAME,
        "agent_module": "historical_file_isolated",
        "historical_artifact": historical_artifact,
        "outcome": "other_exception",
        "all_safe": False,
        "completed_steps": 0,
        "safe_placements": 0,
        "first_failure_step": None,
        "first_failure_predicate": None,
        "first_failure_status": None,
        "terminated": False,
        "truncated": False,
        "final_packed_count": 0,
        "evaluation": {"fill_score": None, "num_placed_items": None},
        "policy_time_seconds": {
            "count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0
        },
        "optimize_time_seconds": 0.0,
        "optimized_order": None,
        "exception": {
            "category": "other_exception",
            "type": type(error).__name__,
            "message": str(error),
            "step": 0,
        },
        "failure_snapshot": None,
        "records": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with (SIMULATOR_ROOT / "configs" / "sample_config.json").open(
            encoding="utf-8"
        ) as stream:
            sample_config = json.load(stream)
        config = materialize_config(sample_config, "000", args.items, "A")
        result = run_historical_episode(
            config,
            requested_items=args.items,
            seed=args.seed,
            snapshot_on_failure=args.snapshot_on_failure,
            capture_all_snapshots=args.capture_all_snapshots,
        )
    except Exception as error:
        result = _minimal_failure(args, error)
    write_result_atomic(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("outcome") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
