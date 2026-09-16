"""CLI for collecting and aggregating the non-production Phase-0 evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
import re
from pathlib import Path
import tempfile
import time
from dataclasses import replace
import sys
from typing import Any, Iterable, Sequence

if __package__ in {None, ""}:
    _SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
    if str(_SIMULATOR_ROOT) not in sys.path:
        sys.path.insert(0, str(_SIMULATOR_ROOT))

try:  # package execution: python -m tests.run_quota_fair_phase0
    from .quota_fair_case_manifest import (
        EXPECTED_MANIFEST_SHA256,
        build_fixed_manifest,
        manifest_hash,
        materialized_case_hash,
        materialize_case,
        materialize_case_with_metadata,
    )
    from .quota_fair_starvation_diagnostics import (
        classify_probe,
        measure_pool_position,
        trace_production_catalog,
    )
except ImportError:  # direct execution from simulator/tests
    from quota_fair_case_manifest import (  # type: ignore
        EXPECTED_MANIFEST_SHA256,
        build_fixed_manifest,
        manifest_hash,
        materialized_case_hash,
        materialize_case,
        materialize_case_with_metadata,
    )
    from quota_fair_starvation_diagnostics import (  # type: ignore
        classify_probe,
        measure_pool_position,
        trace_production_catalog,
    )


AGGREGATE_KEYS = {
    "schema_version",
    "manifest_sha256",
    "measured_state_count",
    "lookahead_20_40_state_count",
    "recoverable_state_count",
    "recoverable_frequency",
    "qualifying_state_ids",
    "stop_reason_counts",
    "time_to_first_exact_root_seconds",
    "proceed",
    "source_files",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase-0 starvation diagnostic")
    parser.add_argument("--task", default=None)
    parser.add_argument("--items", type=int, default=None)
    parser.add_argument("--include-saved-snapshots", action="store_true")
    parser.add_argument("--include-fixed-manifest", action="store_true")
    parser.add_argument("--lookaheads", default=None)
    parser.add_argument("--seeds", default=None)
    parser.add_argument("--aggregate", nargs="+")
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON through a same-directory temporary file and Path.replace."""
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
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parse_csv(value: str | None, cast: Any) -> list[Any] | None:
    if value is None or not value.strip():
        return None
    return [cast(part.strip()) for part in value.split(",") if part.strip()]


def _manifest_payload() -> dict[str, Any]:
    cases = build_fixed_manifest()
    return {
        "schema_version": 1,
        "manifest_sha256": manifest_hash(cases),
        "cases": list(cases),
    }


_MANIFEST_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _lookahead_value(value: dict[str, Any]) -> int:
    """Read the observation schema's lookahead_k, with legacy fallbacks."""
    for key in ("lookahead_k", "look_ahead", "lookahead"):
        candidate = value.get(key)
        if candidate is not None:
            return int(candidate)
    return -1


def _derived_observation_evidence(row: dict[str, Any]) -> tuple[bool, Counter[str], list[float]]:
    trace_by_index = {
        int(value["pool_index"]): value
        for value in row.get("trace_rows", [])
        if isinstance(value, dict) and "pool_index" in value
    }
    stop_counts = Counter(str(value.get("stop_reason")) for value in trace_by_index.values() if value.get("stop_reason") is not None)
    times: list[float] = []
    eligible = False
    for probe in row.get("probes", []):
        if not isinstance(probe, dict):
            continue
        index = int(probe.get("pool_index", -1))
        baseline = trace_by_index.get(index, {})
        baseline_reason = str(probe.get("baseline_stop_reason", baseline.get("stop_reason", "unknown")))
        accepted = int(probe.get("baseline_accepted_root_count", baseline.get("accepted_root_count", 0)))
        measurement = probe.get("measurement", {})
        if not isinstance(measurement, dict):
            continue
        exact = bool(measurement.get("exact_root_found", False))
        first = measurement.get("time_to_first_exact_root")
        share = float(probe.get("fair_share_seconds", 0.0))
        if isinstance(first, (int, float)):
            times.append(float(first))
        eligible = eligible or bool(
            accepted == 0
            and baseline_reason in {"global_cap", "catalog_deadline"}
            and exact
            and isinstance(first, (int, float))
            and float(first) <= max(0.0, share)
        )
    return eligible, stop_counts, times


def _aggregate(paths: Sequence[str]) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    manifest_digests: list[str] = []
    for raw_path in paths:
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"raw input must be an object: {raw_path}")
        manifest_digest = payload.get("manifest_sha256")
        if not isinstance(manifest_digest, str) or not _MANIFEST_DIGEST_RE.fullmatch(manifest_digest):
            raise ValueError(f"raw input has missing or invalid manifest hash: {raw_path}")
        if manifest_digest != EXPECTED_MANIFEST_SHA256:
            raise ValueError(f"raw input manifest hash differs from expected digest: {raw_path}")
        manifest_digests.append(manifest_digest)
        rows = payload.get("observations", [])
        if not isinstance(rows, list):
            raise ValueError(f"observations must be a list: {raw_path}")
        observations.extend(row for row in rows if isinstance(row, dict))

    by_id: dict[str, dict[str, Any]] = {}
    for row in observations:
        identifier = str(row.get("observation_id", row.get("state_id", len(by_id))))
        if identifier in by_id:
            old = json.dumps(by_id[identifier], sort_keys=True, separators=(",", ":"))
            new = json.dumps(row, sort_keys=True, separators=(",", ":"))
            if old != new:
                raise ValueError(f"conflicting duplicate observation_id: {identifier}")
        else:
            by_id[identifier] = row
    measured = list(by_id.values())
    lookahead_rows = [row for row in measured if _lookahead_value(row) in {20, 40}]
    qualifying: list[str] = []
    stop_counts: Counter[str] = Counter()
    times: list[float] = []
    for row in lookahead_rows:
        recoverable, row_stop_counts, row_times = _derived_observation_evidence(row)
        stop_counts.update(row_stop_counts)
        times.extend(row_times)
        if recoverable:
            qualifying.append(str(row.get("observation_id", row.get("state_id", len(qualifying)))))
    denominator = len(lookahead_rows)
    frequency = len(qualifying) / denominator if denominator else 0.0
    return {
        "schema_version": 1,
        "manifest_sha256": manifest_digests[0] if manifest_digests else EXPECTED_MANIFEST_SHA256,
        "measured_state_count": len(measured),
        "lookahead_20_40_state_count": denominator,
        "recoverable_state_count": len(qualifying),
        "recoverable_frequency": frequency,
        "qualifying_state_ids": qualifying,
        "stop_reason_counts": dict(sorted(stop_counts.items())),
        "time_to_first_exact_root_seconds": times,
        "proceed": len(qualifying) >= 3 and frequency >= 0.05,
        "source_files": list(paths),
    }


def _aggregate_materialized_manifest(paths: Sequence[str]) -> dict[str, Any]:
    cases: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        for row in payload.get("observations", []):
            if not isinstance(row, dict) or "materialized_config" not in row:
                continue
            case = row["materialized_config"]
            digest = row.get("materialized_sha256")
            if not isinstance(digest, str) or digest != materialized_case_hash(case):
                raise ValueError(f"materialized case hash mismatch: {row.get('observation_id')}")
            metadata = row.get("materialized_metadata", {})
            if not isinstance(metadata, dict) or metadata.get("materialized_sha256") != digest:
                raise ValueError(f"materialized metadata hash mismatch: {row.get('observation_id')}")
            identifier = str(row.get("observation_id", len(cases)))
            entry = {
                "observation_id": identifier,
                "template_number": row.get("template_number"),
                "seed": row.get("seed"),
                "config": case,
                "metadata": row.get("materialized_metadata", {}),
                "sha256": digest,
            }
            canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            if identifier in cases and json.dumps(cases[identifier], sort_keys=True, separators=(",", ":")) != canonical:
                raise ValueError(f"conflicting materialized observation_id: {identifier}")
            cases[identifier] = entry
    if not cases:
        raise ValueError("manifest output requires materialized cases in raw inputs")
    return {
        "schema_version": 1,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "materialized_cases": list(cases.values()),
    }


def run_real_warmup(config: dict[str, Any], target_steps: int, seed: int, initial_state: str) -> dict[str, Any]:
    """Run the normal control policy until a manifest warm-up target."""
    from agents.highscore.agent import Agent
    from src.ground_handling.env import GroundHandlingEnv

    env = GroundHandlingEnv(config=copy.deepcopy(config), verbose=False, render_mode=None)
    try:
        agent = configure_mpc_agent(Agent("agents/highscore/"))
        env.reset_settings()
        env.reset_item_stream()
        if not agent.get_init_states(env.get_init_states()):
            raise RuntimeError("get_init_states returned false during warm-up")
        observation, _ = env.reset(seed=seed)
        all_safe = True
        for _ in range(max(0, int(target_steps))):
            observation = _attach_depth_map(observation, env)
            action = agent.policy(observation)
            observation, _, terminated, truncated, info = env.step(action)
            status = info.get("status", {}) if isinstance(info, dict) else {}
            if not isinstance(status, dict) or not all(bool(value) for value in status.values()):
                all_safe = False
                break
            if terminated or truncated:
                break
        # The returned observation is also a pre-action observation.  Attach
        # the shared depth map on every exit path, including target zero and
        # a false-status break, before copying any packed-item metadata.
        observation = _attach_depth_map(observation, env)
        packed_items = [
            item
            for container in observation.get("container_list", [])
            for item in container.get("packed_items", [])
        ]
        return {"observation": observation, "packed_items": packed_items, "all_safe": all_safe}
    finally:
        env.close()


def _materialized_rows(
    args: argparse.Namespace,
    *,
    warmup_runner: Any = None,
    diagnose_fn: Any = None,
) -> list[dict[str, Any]]:
    if not args.include_fixed_manifest:
        return []
    config_path = Path(__file__).resolve().parents[1] / "configs" / "sample_config.json"
    sample = json.loads(config_path.read_text(encoding="utf-8"))
    lookaheads = set(_parse_csv(args.lookaheads, int) or [])
    seeds = _parse_csv(args.seeds, int) or [17]
    rows: list[dict[str, Any]] = []
    warmup_runner = warmup_runner or run_real_warmup
    diagnose_fn = diagnose_fn or diagnose_observation
    for template_number, template in enumerate(build_fixed_manifest(), 1):
        if lookaheads and int(template["lookahead"]) not in lookaheads:
            continue
        for seed in seeds:
            observation = materialize_manifest_observation(
                template,
                seed,
                sample,
                warmup_runner=warmup_runner,
            )
            identifier = f"manifest-{template_number:02d}-{seed}"
            diagnostic = diagnose_fn(observation, observation_id=identifier)
            diagnostic.update(
                {
                    "source": "fixed_manifest",
                    "template_number": template_number,
                    "seed": int(seed),
                    "materialized_config": observation["materialized_config"],
                    "materialized_metadata": observation["materialized_metadata"],
                    "materialized_sha256": observation["materialized_sha256"],
                }
            )
            rows.append(diagnostic)
    return rows


def diagnose_observation(
    observation: dict[str, Any],
    *,
    observation_id: str = "observation",
    state_builder: Any = None,
    pool_builder: Any = None,
    generator_factory: Any = None,
    settings_factory: Any = None,
    urgency_fn: Any = None,
    tracer: Any = None,
    prober: Any = None,
    classifier: Any = None,
) -> dict[str, Any]:
    """Run the real highscore state/catalog path for one supplied observation.

    The function is intentionally injectable at the CLI boundary: saved
    snapshots and the later PyBullet warm-up runner can supply observations
    without making manifest materialization depend on a physics process.
    """
    if state_builder is None:
        from agents.highscore.state import build_packing_state

        state_builder = lambda value: build_packing_state(
            value.get("container_list", []), value.get("depth_map")
        )
    if pool_builder is None:
        from agents.highscore.model import ItemSpec

        pool_builder = lambda value: tuple(ItemSpec.from_dict(item) for item in value.get("pool_list", []))
    if settings_factory is None:
        from agents.highscore.settings import SearchSettings

        settings_factory = lambda: replace(SearchSettings(), use_mpc_mcts_ems=True)
    settings = settings_factory()
    state = state_builder(observation)
    pool = tuple(pool_builder(observation))
    if generator_factory is None:
        from agents.highscore.candidates import CandidateGenerator

        generator_factory = CandidateGenerator
    generator = generator_factory(settings)
    tracer = tracer or trace_production_catalog
    prober = prober or measure_pool_position
    classifier = classifier or classify_probe
    if urgency_fn is None:
        from agents.highscore.scoring import CandidateScorer

        urgency_fn = CandidateScorer.item_urgency
    trace = tracer(
        state,
        pool,
        generator,
        settings,
        deadline=time.perf_counter() + settings.ems_root_budget_seconds,
    )
    rows_by_index = {row.pool_index: row for row in trace.rows}
    ordered_indices = sorted(
        range(len(pool)),
        key=lambda index: (
            -float(urgency_fn(pool[index], state.containers)),
            int(pool[index].index),
            index,
        ),
    )
    probes: list[dict[str, Any]] = []
    remaining_budget = max(0.0, float(trace.observed_catalog_budget_seconds))
    for ordinal, pool_index in enumerate(ordered_indices):
        fair_share = remaining_budget / max(1, len(ordered_indices) - ordinal)
        measurement = prober(
            state,
            pool,
            pool_index,
            generator,
            settings,
            probe_budget_seconds=max(0.0, float(trace.observed_catalog_budget_seconds)),
        )
        classification = classifier(measurement, fair_share_seconds=fair_share)
        baseline = rows_by_index[pool_index]
        baseline_reason = baseline.stop_reason
        eligible = bool(
            baseline.accepted_root_count == 0
            and baseline_reason in {"global_cap", "catalog_deadline"}
            and classification.recoverable
        )
        probes.append({
            "pool_index": pool_index,
            "measurement": {
                "exact_root_found": measurement.exact_root_found,
                "time_to_first_exact_root": measurement.time_to_first_exact_root,
                "measured_elapsed_seconds": measurement.measured_elapsed_seconds,
                "proposals_exhausted": measurement.proposals_exhausted,
            },
            "fair_share_seconds": classification.fair_share_seconds,
            "baseline_stop_reason": baseline_reason,
            "baseline_accepted_root_count": baseline.accepted_root_count,
            "classification_recoverable": classification.recoverable,
            "eligible": eligible,
        })
        remaining_budget = max(
            0.0,
            remaining_budget
            - min(max(0.0, float(measurement.measured_elapsed_seconds)), fair_share),
        )
    stop_counts = Counter(row.stop_reason for row in trace.rows)
    times = [
        probe["measurement"]["time_to_first_exact_root"]
        for probe in probes
        if probe["measurement"]["time_to_first_exact_root"] is not None
    ]
    return {
        "observation_id": observation_id,
        "lookahead": _lookahead_value(observation),
        "stop_reason_counts": dict(sorted(stop_counts.items())),
        "time_to_first_exact_root_seconds": times,
        "recoverable": any(probe["eligible"] for probe in probes),
        "trace_rows": [row.__dict__ for row in trace.rows],
        "probes": probes,
    }


def configure_mpc_agent(agent: Any) -> Any:
    """Enable the normal MPC route without environment flags or CLI mutation."""
    from agents.highscore.planner import Planner

    agent.settings = replace(agent.settings, use_mpc_mcts_ems=True)
    agent.planner = Planner(agent.settings)
    return agent


def _attach_depth_map(observation: dict[str, Any], env: Any) -> dict[str, Any]:
    shared = getattr(env, "shm_depth_map", None)
    if shared is not None:
        observation["depth_map"] = shared.copy()
    return observation


def _json_safe(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run_episode_with_diagnostics(
    env: Any,
    agent: Any,
    *,
    diagnose_fn: Any = diagnose_observation,
    depth_map_fn: Any = _attach_depth_map,
    seed: int = 42,
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Run an already-created environment and diagnose every pre-action state."""
    records: list[dict[str, Any]] = []
    terminated = truncated = False
    try:
        env.reset_settings()
        env.reset_item_stream()
        if not agent.get_init_states(env.get_init_states()):
            raise RuntimeError("get_init_states returned false")
        observation, _ = env.reset(seed=seed)
        while not (terminated or truncated):
            if max_steps is not None and len(records) >= max_steps:
                break
            observation = depth_map_fn(observation, env)
            diagnostic = diagnose_fn(observation, observation_id=f"episode-{len(records):04d}")
            action = agent.policy(observation)
            pre_observation = copy.deepcopy(observation)
            next_observation, _, terminated, truncated, info = env.step(action)
            status = info.get("status", {}) if isinstance(info, dict) else {}
            record = {
                "observation_id": diagnostic["observation_id"],
                "observation": _json_safe(pre_observation),
                "trace_rows": diagnostic.get("trace_rows", []),
                "probes": diagnostic.get("probes", []),
                "lookahead": diagnostic.get("lookahead", -1),
                "stop_reason_counts": diagnostic.get("stop_reason_counts", {}),
                "time_to_first_exact_root_seconds": diagnostic.get("time_to_first_exact_root_seconds", []),
                "recoverable": diagnostic.get("recoverable", False),
                "action": _json_safe(action),
                "status": _json_safe(status),
            }
            records.append(record)
            if not isinstance(status, dict) or not all(bool(value) for value in status.values()):
                raise RuntimeError(f"false environment status at step {len(records) - 1}: {status}")
            observation = next_observation
    finally:
        env.close()
    return {
        "observations": records,
        "completed_steps": len(records),
        "terminated": terminated,
        "truncated": truncated,
    }


def run_real_task_episode(
    config: dict[str, Any],
    *,
    task_id: str,
    requested_items: int,
    seed: int = 42,
    diagnose_fn: Any = diagnose_observation,
    env_factory: Any = None,
    agent_factory: Any = None,
) -> dict[str, Any]:
    """Create the real lazy PyBullet environment and run one control episode."""
    if env_factory is None:
        from src.ground_handling.env import GroundHandlingEnv

        env_factory = lambda value: GroundHandlingEnv(config=value, verbose=False, render_mode=None)
    if agent_factory is None:
        from agents.highscore.agent import Agent

        agent_factory = lambda path: Agent(path)
    env = env_factory(config)
    episode_owns_close = False
    try:
        agent = configure_mpc_agent(agent_factory("agents/highscore/"))
        episode_owns_close = True
        result = run_episode_with_diagnostics(
            env,
            agent,
            diagnose_fn=diagnose_fn,
            seed=seed,
            max_steps=requested_items,
        )
        result["task"] = task_id
        result["requested_items"] = requested_items
        result["source"] = "task"
        return result
    finally:
        # The episode helper owns closure after handoff; construction failures
        # still close here because the handoff flag remains false.
        if not episode_owns_close:
            env.close()


def load_and_diagnose_snapshots(
    paths: Sequence[Path],
    *,
    loader: Any = None,
    diagnose_fn: Any = diagnose_observation,
) -> list[dict[str, Any]]:
    if loader is None:
        try:
            from .replay_support import load_observation_snapshot
        except ImportError:
            from replay_support import load_observation_snapshot  # type: ignore

        loader = load_observation_snapshot
    rows: list[dict[str, Any]] = []
    for path in sorted(Path(value) for value in paths):
        observation, metadata = loader(path)
        row = diagnose_fn(observation, observation_id=f"snapshot-{path.stem}")
        row["source"] = "saved_snapshot"
        row["source_file"] = str(path)
        row["snapshot_metadata"] = metadata
        rows.append(row)
    return rows


def materialize_manifest_observation(
    template: dict[str, Any],
    seed: int,
    sample_config: dict[str, Any],
    *,
    warmup_runner: Any,
    fresh_runner: Any | None = None,
) -> dict[str, Any]:
    """Materialize a case through an injected control warm-up lifecycle."""
    case, metadata = materialize_case_with_metadata(template, seed, sample_config)
    target = int(metadata["warmup_target_steps"])
    warmup = warmup_runner(case, target, seed, metadata["initial_state"])
    if not bool(warmup.get("all_safe", True)):
        raise RuntimeError(f"manifest warm-up produced false status: {metadata}")
    if metadata["initial_state"] == "preloaded":
        packed = copy.deepcopy(warmup.get("packed_items", []))
        packed_indices = {int(item["index"]) for item in packed if "index" in item}
        containers = case["containers"]["container_list"]
        for container in containers:
            container["packed_items"] = []
        for item in packed:
            belongs_to = int(item.get("belongs_to", containers[0]["index"]))
            destination = next((container for container in containers if container["index"] == belongs_to), containers[0])
            destination["packed_items"].append(item)
        case["item_stream"]["item_list"] = [
            item for item in case["item_stream"]["item_list"] if int(item["index"]) not in packed_indices
        ]
        case["item_stream"]["visible_pool"] = []
        if fresh_runner is None:
            fresh_runner = warmup_runner
        settled = fresh_runner(case, 0, seed, metadata["initial_state"])
    else:
        settled = warmup
    if not bool(settled.get("all_safe", True)):
        raise RuntimeError(f"manifest fresh initialization produced false status: {metadata}")
    observation = copy.deepcopy(settled.get("observation", {}))
    digest = materialized_case_hash(case)
    metadata = dict(metadata)
    metadata["materialized_sha256"] = digest
    observation["materialized_config"] = case
    observation["materialized_metadata"] = metadata
    observation["materialized_sha256"] = digest
    return observation


def main(
    argv: Sequence[str] | None = None,
    *,
    episode_runner: Any = None,
    snapshot_loader: Any = None,
    warmup_runner: Any = None,
    diagnose_fn: Any = diagnose_observation,
) -> int:
    args = build_parser().parse_args(argv)
    if args.aggregate is not None:
        if args.manifest_output is not None:
            atomic_write_json(args.manifest_output, _aggregate_materialized_manifest(args.aggregate))
        atomic_write_json(args.output, _aggregate(args.aggregate))
        return 0

    rows: list[dict[str, Any]] = []
    source_files: list[str] = []
    root = Path(__file__).resolve().parents[1]
    if args.task is not None:
        sample = json.loads((root / "configs" / "sample_config.json").read_text(encoding="utf-8"))
        if args.task not in sample:
            raise ValueError(f"unknown task: {args.task}")
        config = copy.deepcopy(sample[args.task])
        requested_items = int(args.items or len(config["item_stream"]["item_list"]))
        config["item_stream"]["item_list"] = config["item_stream"]["item_list"][:requested_items]
        config["item_stream"]["look_ahead"] = min(
            int(config["item_stream"].get("look_ahead", requested_items)), requested_items
        )
        config["agent"]["optimize"] = False
        config["visualizer"]["vis"] = False
        if episode_runner is None:
            episode_runner = run_real_task_episode
        result = episode_runner(
            config,
            task_id=args.task,
            requested_items=requested_items,
            diagnose_fn=diagnose_fn,
        )
        rows.extend(result.get("observations", []))
        source_files.append(f"sample_config.json:{args.task}")
    if args.include_saved_snapshots:
        snapshot_paths = sorted((root / "tests" / "artifacts").glob("*.npz"))
        rows.extend(load_and_diagnose_snapshots(snapshot_paths, loader=snapshot_loader, diagnose_fn=diagnose_fn))
        source_files.extend(str(path) for path in snapshot_paths)
    rows.extend(_materialized_rows(args, warmup_runner=warmup_runner, diagnose_fn=diagnose_fn))
    payload = {
        "schema_version": 1,
        "manifest_sha256": manifest_hash(build_fixed_manifest()),
        "observations": rows,
        "source_files": source_files,
    }
    if args.include_fixed_manifest and args.manifest_output is not None:
        atomic_write_json(args.manifest_output, _manifest_payload())
    atomic_write_json(args.output, _json_safe(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
