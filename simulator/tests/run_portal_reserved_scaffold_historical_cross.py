"""Matched task000 physical cross for the official-semantics shield.

This is a diagnostic runner.  It uses the same Gymnasium/PyBullet lifecycle as
the existing official runner, but records a rejected historical proposal
without calling ``env.step``.  The production authorizer itself has no corpus
or artifact-file dependency.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import time
from collections.abc import Mapping
from typing import Any, Sequence

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SIMULATOR_ROOT.parent
RESULTS_ROOT = (SIMULATOR_ROOT / "results" / "portal_reserved_scaffold").resolve()
PACKAGE_ROOT = (SIMULATOR_ROOT / "agents" / "portal_reserved_scaffold_dag").resolve()
CAPTURED_CONTROL = RESULTS_ROOT / "historical-task000-captured.json"
SUBMIT_ROOT = (PROJECT_ROOT / "submit").resolve()
HISTORICAL_SOURCE_PATH = (
    SUBMIT_ROOT / "Conservative Extreme-Point Packing_score29.7" / "high_score" / "agent.py"
).resolve()
EXPECTED_HISTORICAL_SOURCE_SHA256 = "ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82"
EXPECTED_SUBMIT_MANIFEST_SHA256 = "95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c"

from agents.portal_reserved_scaffold_dag.agent import Agent  # noqa: E402
from agents.portal_reserved_scaffold_dag.historical_seed import (  # noqa: E402
    historical_source_descriptor,
)
from tests.run_support_extreme_fusion_physics import (  # noqa: E402
    _default_env_factory,
    _mode_init_state,
    _serialize_action,
    action_format_is_valid,
    materialize_config,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file_manifest(root: Path) -> tuple[tuple[str, str], ...]:
    entries = []
    for path in root.rglob("*"):
        if path.is_file():
            entries.append((path.relative_to(root).as_posix(), _file_digest(path)))
    return tuple(sorted(entries))


def _manifest_digest(manifest: tuple[tuple[str, str], ...]) -> str:
    text = "".join(f"{relative}\t{digest}\n" for relative, digest in manifest).encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _package_digest() -> tuple[str, tuple[tuple[str, str], ...]]:
    manifest = _regular_file_manifest(PACKAGE_ROOT)
    # Byte identity is recorded over source files and any package assets, but
    # Python's process-local __pycache__ is intentionally excluded.
    stable = tuple(entry for entry in manifest if "__pycache__/" not in entry[0])
    return _manifest_digest(stable), stable


def _timing_summary(values: Sequence[float]) -> dict[str, float | int]:
    finite = np.asarray([float(value) for value in values if math.isfinite(float(value))])
    if finite.size == 0:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": int(finite.size),
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
        "p99": float(np.percentile(finite, 99)),
        "max": float(np.max(finite)),
    }


def _safe_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe_json(child) for key, child in value.items()}
    if isinstance(value, dict):
        return {str(key): _safe_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(child) for child in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _fill_inputs(env: Any) -> dict[str, float | int]:
    """Expose the physical volume/count inputs used by the evaluator."""

    containers = getattr(getattr(env, "container_manager", None), "containers", ())
    container_volume = sum(float(getattr(container, "volume", 0.0)) for container in containers)
    packed_items = [item for container in containers for item in getattr(container, "packed_items", ())]
    packed_volume = sum(float(getattr(item, "volume", 0.0)) for item in packed_items)
    inside_volume = None
    evaluator = getattr(env, "evaluator", None)
    if evaluator is not None:
        try:
            fill_score, _out_items = evaluator.calculate_fill_rate(containers)
            inside_volume = float(fill_score) * container_volume / 100.0
        except Exception:
            inside_volume = None
    return {
        "packed_volume": packed_volume,
        "container_volume": container_volume,
        "packed_count": len(packed_items),
        "inside_volume": inside_volume,
    }

def _load_expected_prefix() -> list[dict[str, Any]]:
    if not CAPTURED_CONTROL.is_file():
        raise FileNotFoundError(f"Task 2 captured control is missing: {CAPTURED_CONTROL}")
    payload = json.loads(CAPTURED_CONTROL.read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("captured control records are missing")
    prefix = []
    for record in records[:25]:
        prefix.append(_serialize_action(record["action"]))
    if len(prefix) != 25:
        raise ValueError("captured control must contain 25 safe prefix actions")
    return prefix


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the portal shield historical cross")
    parser.add_argument("--task", choices=("000",), default="000")
    parser.add_argument("--items", type=int, default=41)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=RESULTS_ROOT / "task000-official-shield-cross-seed42.json")
    return parser


def run_cross(
    *,
    task: str = "000",
    items: int = 41,
    seed: int = 42,
    output: Path | str | None = None,
) -> dict[str, Any]:
    if task != "000" or type(items) is not int or items != 41 or type(seed) is not int or seed != 42:
        raise ValueError("the matched cross is fixed to task000, 41 items, seed42")
    output_path = Path(output or RESULTS_ROOT / "task000-official-shield-cross-seed42.json").resolve()
    expected_prefix = _load_expected_prefix()
    package_sha256, package_manifest = _package_digest()
    submit_before = _regular_file_manifest(SUBMIT_ROOT)
    submit_before_sha256 = _manifest_digest(submit_before)
    if submit_before_sha256 != EXPECTED_SUBMIT_MANIFEST_SHA256:
        raise RuntimeError(
            "immutable submit manifest differs from the recorded baseline: "
            f"{submit_before_sha256} != {EXPECTED_SUBMIT_MANIFEST_SHA256}"
        )
    historical_source_sha256 = _file_digest(HISTORICAL_SOURCE_PATH)
    if historical_source_sha256 != EXPECTED_HISTORICAL_SOURCE_SHA256:
        raise RuntimeError(
            "historical source differs from the recorded artifact: "
            f"{historical_source_sha256} != {EXPECTED_HISTORICAL_SOURCE_SHA256}"
        )
    config_path = SIMULATOR_ROOT / "configs" / "sample_config.json"
    sample_config = json.loads(config_path.read_text(encoding="utf-8"))
    config = materialize_config(sample_config, task, items, "A")
    config_sha256 = _json_digest(config)
    runner_sha256 = _file_digest(Path(__file__).resolve())
    historical_seed_sha256 = _file_digest(
        SIMULATOR_ROOT / "agents" / "portal_reserved_scaffold_dag" / "historical_seed.py"
    )
    result: dict[str, Any] = {
        "algorithm_name": "portal_reserved_scaffold_dag",
        "task": task,
        "requested_items": items,
        "seed": seed,
        "requested_mode": "A",
        "resolved_mode": None,
        "package_sha256": package_sha256,
        "package_manifest": list(package_manifest),
        "config_sha256": config_sha256,
        "runner_sha256": runner_sha256,
        "historical_seed_sha256": historical_seed_sha256,
        "historical_source_path": HISTORICAL_SOURCE_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "historical_source_sha256": historical_source_sha256,
        "historical_source_expected_sha256": EXPECTED_HISTORICAL_SOURCE_SHA256,
        "historical_source_descriptor": historical_source_descriptor(),
        "historical_artifact_integrity": {
            "before_manifest_sha256": submit_before_sha256,
            "expected_baseline_sha256": EXPECTED_SUBMIT_MANIFEST_SHA256,
            "before_matches_baseline": submit_before_sha256 == EXPECTED_SUBMIT_MANIFEST_SHA256,
            "after_manifest_sha256": None,
            "after_matches_baseline": None,
            "unchanged": False,
        },
        "action_prefix_expected_count": len(expected_prefix),
        "action_prefix_returned_count": 0,
        "action_prefix_sha256": None,
        "action_prefix_expected_sha256": _json_digest(expected_prefix),
        "action_prefix_divergence": [],
        "returned_actions": [],
        "rejected_attempts": [],
        "first_rejection_reason": None,
        "records": [],
        "step_25": {
            "rejected_before_env_step": False,
            "returned_action": None,
            "env_step_count_before": None,
            "env_step_count_after": None,
            "reject_reasons": [],
        },
        "returned_invalid_count": 0,
        "returned_unsafe_count": 0,
        "safe_placements": 0,
        "local_fill": None,
        "evaluation": {},
        "policy_time_seconds": _timing_summary(()),
        "optimize_time_seconds": None,
        "outcome": "other_exception",
        "exception": None,
        "no_unchecked_fallback": True,
    }
    env = None
    policy_times: list[float] = []
    observation = None
    env_step_count = 0
    try:
        env = _default_env_factory(config)
        env.reset_settings()
        env.reset_item_stream()
        init_state = _mode_init_state(env.get_init_states(), "A")
        result["resolved_mode"] = "A" if bool(init_state.get("optimize")) else "C"
        agent = Agent("agents/portal_reserved_scaffold_dag/")
        if not agent.get_init_states(init_state):
            raise RuntimeError("Agent.get_init_states returned false")
        optimization_items = env.get_info_for_optimization()
        optimize_started = time.perf_counter()
        optimized_order = agent.optimize(optimization_items)
        result["optimize_time_seconds"] = max(0.0, time.perf_counter() - optimize_started)
        expected_order = [int(item["index"]) for item in optimization_items]
        if not isinstance(optimized_order, list) or sorted(optimized_order) != sorted(expected_order):
            raise RuntimeError("historical seed returned an invalid complete permutation")
        if not env.set_item_order(optimized_order):
            raise RuntimeError("environment rejected the optimized order")
        env.reset_item_stream()
        observation, _reset_info = env.reset(seed=seed)
        while result["safe_placements"] < items:
            if not isinstance(observation, dict):
                raise RuntimeError("environment observation must be a dictionary")
            observation["depth_map"] = np.asarray(env.shm_depth_map).copy()
            step = len(result["records"])
            policy_started = time.perf_counter()
            try:
                action = agent.policy(observation)
            except Exception as error:
                elapsed = max(0.0, time.perf_counter() - policy_started)
                policy_times.append(elapsed)
                last = getattr(agent, "_last_result", None)
                reject_reasons = list(getattr(last, "reject_reasons", ()))
                rejection = {
                    "step": step,
                    "rejected_before_env_step": True,
                    "exception_type": type(error).__name__,
                    "exception_message": str(error),
                    "reject_reasons": reject_reasons,
                    "policy_seconds": elapsed,
                }
                result["rejected_attempts"].append(rejection)
                result["records"].append(
                    {
                        "step": step,
                        "policy_seconds": elapsed,
                        "action": None,
                        "status": None,
                        "rejected_before_env_step": True,
                        "reject_reasons": reject_reasons,
                    }
                )
                if result["first_rejection_reason"] is None and reject_reasons:
                    result["first_rejection_reason"] = reject_reasons[0]
                if step == 25:
                    result["step_25"].update(
                        {
                            "rejected_before_env_step": True,
                            "env_step_count_before": env_step_count,
                            "env_step_count_after": env_step_count,
                            "reject_reasons": reject_reasons,
                        }
                    )
                result["outcome"] = "shield_rejection"
                break
            elapsed = max(0.0, time.perf_counter() - policy_started)
            policy_times.append(elapsed)
            if not action_format_is_valid(action, observation):
                result["returned_invalid_count"] += 1
                raise RuntimeError("new agent returned malformed action")
            serialized = _serialize_action(action)
            result["returned_actions"].append(serialized)
            result["action_prefix_returned_count"] = min(25, len(result["returned_actions"]))
            if step < len(expected_prefix) and serialized != expected_prefix[step]:
                result["action_prefix_divergence"].append(
                    {"step": step, "expected": expected_prefix[step], "returned": serialized}
                )
            next_observation, _reward, terminated, truncated, info = env.step(action)
            env_step_count += 1
            status = info.get("status") if isinstance(info, dict) else None
            if not isinstance(status, dict):
                raise RuntimeError("official status is missing")
            status = {str(key): bool(value) for key, value in status.items()}
            if not bool(status.get("is_valid", False)) or not bool(status.get("is_placed_safe", False)):
                result["returned_unsafe_count"] += 1
            fill_inputs = _fill_inputs(env)
            result["records"].append(
                {
                    "step": step,
                    "policy_seconds": elapsed,
                    "action": serialized,
                    "status": status,
                    "fill_inputs": fill_inputs,
                    "terminated": bool(terminated),
                    "truncated": bool(truncated),
                }
            )
            if bool(status.get("is_valid", False)) and bool(status.get("is_placed_safe", False)):
                result["safe_placements"] += 1
            else:
                result["outcome"] = "physical_failure"
                break
            observation = next_observation
            if terminated or truncated:
                break
        if result["outcome"] == "other_exception":
            result["outcome"] = "success" if result["safe_placements"] >= items else "physical_failure"
    except Exception as error:
        result["outcome"] = "other_exception"
        result["exception"] = {
            "type": type(error).__name__,
            "message": str(error),
            "step": len(result["records"]),
        }
    finally:
        result["policy_time_seconds"] = _timing_summary(policy_times)
        if env is not None:
            try:
                evaluation = env.evaluate()
                result["evaluation"] = _safe_json(evaluation)
                if isinstance(evaluation, dict):
                    result["local_fill"] = evaluation.get("fill_score")
            except Exception as error:
                result["evaluation_error"] = {"type": type(error).__name__, "message": str(error)}
            try:
                env.close()
            except Exception as error:
                result["close_error"] = {"type": type(error).__name__, "message": str(error)}
        result["action_prefix_sha256"] = _json_digest(result["returned_actions"][:25])
        submit_after = _regular_file_manifest(SUBMIT_ROOT)
        submit_after_sha256 = _manifest_digest(submit_after)
        result["historical_artifact_integrity"] = {
            "before_manifest_sha256": submit_before_sha256,
            "expected_baseline_sha256": EXPECTED_SUBMIT_MANIFEST_SHA256,
            "before_matches_baseline": submit_before_sha256 == EXPECTED_SUBMIT_MANIFEST_SHA256,
            "after_manifest_sha256": submit_after_sha256,
            "after_matches_baseline": submit_after_sha256 == EXPECTED_SUBMIT_MANIFEST_SHA256,
            "unchanged": submit_before == submit_after and submit_after_sha256 == EXPECTED_SUBMIT_MANIFEST_SHA256,
        }
    _atomic_write_json(output_path, result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_cross(task=args.task, items=args.items, seed=args.seed, output=args.output)
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
    return 0 if payload["outcome"] in ("success", "shield_rejection", "physical_failure") else 1


if __name__ == "__main__":
    raise SystemExit(main())
