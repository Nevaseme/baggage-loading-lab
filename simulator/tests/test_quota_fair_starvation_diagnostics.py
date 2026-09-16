from __future__ import annotations

import pathlib
import json
import copy
import sys
import time
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.candidates import CandidateGenerator  # noqa: E402
from agents.highscore.catalog import build_root_catalog  # noqa: E402
from agents.highscore.ems import build_proxy_state, propose_actions  # noqa: E402
from agents.highscore.model import ItemSpec  # noqa: E402
from agents.highscore.settings import SearchSettings  # noqa: E402
from agents.highscore.state import build_packing_state  # noqa: E402
from agents.highscore import catalog as highscore_catalog  # noqa: E402
from .quota_fair_starvation_diagnostics import (  # noqa: E402
    CatalogTrace,
    CatalogTraceRow,
    ProbeClassification,
    ProbeMeasurement,
    classify_probe,
    measure_pool_position,
    trace_production_catalog,
)
from .quota_fair_case_manifest import (  # noqa: E402
    EXPECTED_MANIFEST_SHA256,
    EXPECTED_TEMPLATE_COUNT,
    build_fixed_manifest,
    manifest_hash,
    materialized_case_hash,
    materialize_case,
    materialize_case_with_metadata,
)
from .run_quota_fair_phase0 import (  # noqa: E402
    AGGREGATE_KEYS,
    atomic_write_json,
    build_parser,
    _aggregate,
    diagnose_observation,
    load_and_diagnose_snapshots,
    materialize_manifest_observation,
    run_real_warmup,
    run_real_task_episode,
    run_episode_with_diagnostics,
    main as phase0_main,
)
from . import run_quota_fair_phase0 as phase0_module  # noqa: E402


@dataclass(frozen=True)
class _FakeItem:
    index: int
    volume: float = 1.0
    mass: float = 1.0
    is_prioritized: bool = False
    is_soft: bool = False


@dataclass(frozen=True)
class _FakeAction:
    pool_index: int


@dataclass(frozen=True)
class _FakeSettings:
    ems_proxy_actions_per_item: int = 4
    ems_exact_roots_per_item: int = 1
    ems_root_catalog_limit: int = 8
    ems_root_budget_seconds: float = 10.0


@dataclass(frozen=True)
class _FakeContainer:
    volume: float = 10.0


@dataclass(frozen=True)
class _FakeState:
    containers: tuple[_FakeContainer, ...] = (_FakeContainer(),)


class _FakeGenerator:
    def __init__(self, validation_log=None):
        self.validation_log = validation_log

    def validate_proposal(self, state, action):
        if self.validation_log is not None:
            self.validation_log.append(action)
        return object()


class _FakeClock:
    def __init__(self, step: float = 0.1):
        self.value = 0.0
        self.step = step

    def perf_counter(self) -> float:
        result = self.value
        self.value += self.step
        return result


def _run_fake_catalog_trace(mode: str, *, clock_step: float = 0.1, identity_log=None, **setting_overrides):
    """Exercise the tracer against a tiny collaborator-only catalog fixture."""
    settings = _FakeSettings(**setting_overrides)
    state = _FakeState()
    pool = tuple(_FakeItem(index) for index in range(4))
    fake_clock = _FakeClock(clock_step)

    def fake_propose(proxy_state, item, pool_index, *, limit, deadline):
        if mode == "throw" and pool_index == 0:
            raise RuntimeError("fixture proposal failure")
        if mode in {"empty", "empty_then_root"} and pool_index == 0:
            return []
        if mode == "deadline" and pool_index == 0:
            return []
        if mode == "empty_then_root" and pool_index == 1:
            actions = [_FakeAction(pool_index), _FakeAction(pool_index)]
        else:
            actions = [_FakeAction(pool_index)]
        if identity_log is not None:
            identity_log.setdefault("proposed", []).extend(actions)
        return actions

    def fake_apply(proxy_state, action, clearance):
        if identity_log is not None:
            identity_log.setdefault("applied", []).append(action)
        return object()

    def fake_catalog(state, pool, generator, settings, *, deadline):
        if mode == "external_catalog_throw":
            highscore_catalog.time.perf_counter()
            raise RuntimeError("fixture catalog failure")
        start = highscore_catalog.time.perf_counter()
        catalog_deadline = min(deadline, start + settings.ems_root_budget_seconds)
        roots = []
        for pool_index, item in enumerate(pool):
            if mode == "not_visited" and pool_index == 1:
                break
            now = highscore_catalog.time.perf_counter()
            if now >= catalog_deadline or len(roots) >= settings.ems_root_catalog_limit:
                break
            remaining = len(pool) - pool_index
            item_deadline = now + (catalog_deadline - now) / max(1, remaining)
            try:
                proposals = highscore_catalog.propose_actions(
                    object(), item, pool_index,
                    limit=settings.ems_proxy_actions_per_item,
                    deadline=item_deadline,
                )
            except Exception:
                continue
            accepted = 0
            for proposal in proposals:
                now = highscore_catalog.time.perf_counter()
                if (
                    now >= item_deadline
                    or now >= catalog_deadline
                    or accepted >= settings.ems_exact_roots_per_item
                    or len(roots) >= settings.ems_root_catalog_limit
                ):
                    break
                candidate = generator.validate_proposal(state, proposal)
                if candidate is None:
                    continue
                successor = highscore_catalog.apply_action(object(), proposal, 0.0)
                if successor is None:
                    continue
                accepted += 1
                roots.append(object())
        return roots

    fake_time = SimpleNamespace(perf_counter=fake_clock.perf_counter)
    with patch.object(highscore_catalog, "build_root_catalog", fake_catalog), patch.object(
        highscore_catalog, "propose_actions", fake_propose
    ), patch.object(highscore_catalog, "apply_action", fake_apply), patch.object(
        highscore_catalog, "time", fake_time
    ):
        return trace_production_catalog(
            state,
            pool,
            _FakeGenerator(identity_log.setdefault("validated", []) if identity_log is not None else None),
            settings,
            deadline=100.0,
        )


def _container_dict(*, index: int = 0) -> dict:
    length, width, height, thickness = 2.0, 1.5, 1.6, 0.04
    return {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (0.0, 0.0, height / 2.0),
        "points": [
            [length / 2.0 - thickness, 0.0, 0.0],
            [-length / 2.0 + thickness, 0.0, 0.0],
            [0.0, width / 2.0 - thickness, 0.0],
            [0.0, -width / 2.0 + thickness, 0.0],
            [0.0, 0.0, height - thickness],
            [0.0, 0.0, thickness],
        ],
        "n_vecs": [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        "volume": 4.0,
        "shelf": False,
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int, *, length: float = 0.5, width: float = 0.4, height: float = 0.24) -> ItemSpec:
    return ItemSpec(index=index, length=length, width=width, height=height)


class DiagnosticCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(
            extra_margins=(0.0,),
            front_floor_release_fill=0.0,
            ems_proxy_actions_per_item=12,
            ems_exact_roots_per_item=2,
            ems_root_catalog_limit=8,
            ems_root_budget_seconds=1.0,
        )
        self.state = build_packing_state([_container_dict()])
        self.generator = CandidateGenerator(self.settings)

    def test_trace_calls_real_catalog_once_and_keeps_duplicate_item_ids_separate(self) -> None:
        pool = (_item(7), _item(7))
        with patch.object(highscore_catalog, "build_root_catalog", wraps=build_root_catalog) as wrapped:
            trace = trace_production_catalog(
                self.state,
                pool,
                self.generator,
                self.settings,
                deadline=time.perf_counter() + 1.0,
            )
        self.assertEqual(wrapped.call_count, 1)
        self.assertEqual([row.pool_index for row in trace.rows], [0, 1])
        self.assertEqual([row.item_index for row in trace.rows], [7, 7])

    def test_probe_is_recoverable_only_within_fair_share(self) -> None:
        measurement = ProbeMeasurement(9, True, 0.010, 0.015, True)
        fast = classify_probe(measurement, fair_share_seconds=0.050)
        slow = classify_probe(measurement, fair_share_seconds=0.001)
        self.assertEqual(fast, ProbeClassification(measurement, 0.050, True))
        self.assertEqual(slow, ProbeClassification(measurement, 0.001, False))

    def test_probe_uses_exact_validator_and_apply_path(self) -> None:
        pool = (_item(8),)
        proxy = build_proxy_state(
            self.state,
            self.settings.path_clearance,
            support_inset=max(0.0, -self.settings.inclusion_margin),
            shelf_drop_gap=self.settings.shelf_drop_gap,
        )
        proposals = propose_actions(
            proxy,
            pool[0],
            0,
            limit=self.settings.ems_proxy_actions_per_item,
            deadline=time.perf_counter() + 1.0,
        )
        self.assertTrue(proposals)
        with patch.object(highscore_catalog, "propose_actions", return_value=proposals) as proposed:
            measurement = measure_pool_position(
                self.state, pool, 0, self.generator, self.settings, probe_budget_seconds=1.0
            )
        self.assertTrue(measurement.exact_root_found)
        self.assertEqual(proposed.call_count, 1)

    def test_probe_rejects_pool_index_out_of_range(self) -> None:
        with self.assertRaises(IndexError):
            measure_pool_position(
                self.state, (_item(8),), 1, self.generator, self.settings, probe_budget_seconds=1.0
            )

    def test_classification_clamps_negative_share_without_mutating_measurement(self) -> None:
        measurement = ProbeMeasurement(0, True, 0.0, 0.0, True)
        result = classify_probe(measurement, fair_share_seconds=-1.0)
        self.assertEqual(result.fair_share_seconds, 0.0)
        self.assertIs(result.measurement, measurement)


class PublicShapeTests(unittest.TestCase):
    def test_trace_row_has_exact_taxonomy_field(self) -> None:
        self.assertEqual(
            set(CatalogTraceRow.__dataclass_fields__),
            {
                "pool_index", "item_index", "urgency", "proposal_count",
                "validated_count", "accepted_root_count", "start_time",
                "end_time", "stop_reason",
            },
        )

    def test_phase0_parser_accepts_exact_declared_options(self) -> None:
        parser = build_parser()
        options = set(parser._option_string_actions)
        self.assertEqual(
            options,
            {
                "-h", "--help", "--task", "--items", "--include-saved-snapshots",
                "--include-fixed-manifest", "--lookaheads", "--seeds", "--aggregate",
                "--manifest-output", "--output",
            },
        )

    def test_atomic_write_uses_replace_and_aggregate_schema_is_exact(self) -> None:
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            raw = root / "raw.json"
            raw.write_text(json.dumps({
                "schema_version": 1,
                "manifest_sha256": EXPECTED_MANIFEST_SHA256,
                "observations": [{
                    "observation_id": "x",
                    "lookahead_k": 20,
                    "recoverable": True,
                    "stop_reason_counts": {"global_cap": 1},
                    "time_to_first_exact_root_seconds": [0.01],
                }],
            }), encoding="utf-8")
            output = root / "results.json"
            original_replace = pathlib.Path.replace
            with patch.object(pathlib.Path, "replace", autospec=True, side_effect=original_replace) as replaced:
                phase0_main(["--aggregate", str(raw), "--output", str(output)])
            self.assertTrue(output.exists())
            self.assertGreaterEqual(replaced.call_count, 1)
            self.assertEqual(set(json.loads(output.read_text(encoding="utf-8"))), AGGREGATE_KEYS)

    def test_aggregate_uses_lookahead_k_and_counts_both_requested_denominator_values(self) -> None:
        import tempfile

        rows = [
            {"observation_id": "lookahead-20", "lookahead_k": 20, "trace_rows": [], "probes": []},
            {"observation_id": "lookahead-40", "lookahead_k": 40, "trace_rows": [], "probes": []},
        ]
        with tempfile.TemporaryDirectory() as directory:
            raw = pathlib.Path(directory) / "raw.json"
            raw.write_text(
                json.dumps({"manifest_sha256": EXPECTED_MANIFEST_SHA256, "observations": rows}),
                encoding="utf-8",
            )
            aggregate = _aggregate([str(raw)])
        self.assertEqual(aggregate["lookahead_20_40_state_count"], 2)

    def test_fixed_manifest_is_literal_sixteen_cases_with_stable_hash(self) -> None:
        cases = build_fixed_manifest()
        self.assertIsInstance(cases, tuple)
        self.assertEqual(len(cases), EXPECTED_TEMPLATE_COUNT)
        self.assertEqual(manifest_hash(cases), EXPECTED_MANIFEST_SHA256)
        self.assertEqual(manifest_hash(cases), manifest_hash(json.loads(json.dumps(cases))))

    def test_materialize_case_is_deterministic_and_json_serializable(self) -> None:
        sample_path = pathlib.Path(__file__).resolve().parents[1] / "configs" / "sample_config.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        template = build_fixed_manifest()[3]
        first = materialize_case(template, 42, sample)
        second = materialize_case(template, 42, sample)
        self.assertEqual(first, second)
        self.assertEqual(first["item_stream"]["look_ahead"], template["lookahead"])
        self.assertEqual(len(first["containers"]["container_list"]), template["containers"])
        json.dumps(first, sort_keys=True)

    def test_materialized_camera_priority_alternation_metadata_and_hash(self) -> None:
        sample_path = pathlib.Path(__file__).resolve().parents[1] / "configs" / "sample_config.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        two_container_templates = [template for template in build_fixed_manifest() if template["containers"] == 2]
        designated = []
        for template in two_container_templates:
            case, metadata = materialize_case_with_metadata(template, 17, sample)
            containers = case["containers"]["container_list"]
            designated.append([container["index"] for container in containers if container["is_prioritized"]])
            self.assertEqual(case["camera"]["num_containers"], 2)
            self.assertIn(metadata["warmup_target_steps"], {0, 8, 16})
            self.assertEqual(metadata["initial_state"], template["initial_state"])
            self.assertEqual(materialized_case_hash(case), materialized_case_hash(copy.deepcopy(case)))
        self.assertEqual(designated, [[0], [], [1], [], [0], [], [1], []])

    def test_large_to_small_orders_volume_and_index_descending(self) -> None:
        sample_path = pathlib.Path(__file__).resolve().parents[1] / "configs" / "sample_config.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        template = dict(build_fixed_manifest()[0])
        template["item_order"] = "large-to-small"
        case = materialize_case(template, 17, sample)
        items = case["item_stream"]["item_list"]
        keys = [
            (float(item["length"]) * float(item["width"]) * float(item["height"]), int(item["index"]))
            for item in items
        ]
        self.assertEqual(keys, sorted(keys, reverse=True))

    def test_diagnose_orders_all_positions_and_uses_remaining_budget_recurrence(self) -> None:
        items = tuple(_FakeItem(index) for index in range(4))
        urgencies = {0: 0.1, 1: 0.9, 2: 0.9, 3: 0.2}
        state = _FakeState()
        accepted_counts = {0: 0, 1: 1, 2: 0, 3: 0}
        baseline = tuple(
            CatalogTraceRow(index, index, urgencies[index], 0, 0, accepted_counts[index], 0.0, 0.1, reason)
            for index, reason in enumerate(("global_cap", "global_cap", "proposal_exhausted", "catalog_deadline"))
        )
        trace = CatalogTrace((), baseline, 0.0, 0.6, 0.6)
        probe_calls = []

        def tracer(*args, **kwargs):
            return trace

        def prober(state, pool, pool_index, generator, settings, *, probe_budget_seconds):
            probe_calls.append((pool_index, probe_budget_seconds))
            return ProbeMeasurement(pool_index, True, 0.1, 0.1, True)

        def classifier(measurement, *, fair_share_seconds):
            return ProbeClassification(measurement, fair_share_seconds, True)

        result = diagnose_observation(
            {"lookahead_k": 20},
            state_builder=lambda observation: state,
            pool_builder=lambda observation: items,
            generator_factory=lambda settings: object(),
            settings_factory=lambda: _FakeSettings(),
            urgency_fn=lambda item, containers: urgencies[item.index],
            tracer=tracer,
            prober=prober,
            classifier=classifier,
        )
        self.assertEqual([index for index, _ in probe_calls], [1, 2, 3, 0])
        self.assertEqual(len(result["probes"]), 4)
        self.assertEqual([budget for _, budget in probe_calls], [0.6, 0.6, 0.6, 0.6])
        self.assertTrue(result["recoverable"])
        self.assertEqual(result["lookahead"], 20)
        by_index = {probe["pool_index"]: probe for probe in result["probes"]}
        self.assertTrue(by_index[0]["eligible"])
        self.assertFalse(by_index[1]["eligible"])
        self.assertFalse(by_index[2]["eligible"])
        self.assertTrue(by_index[3]["eligible"])

    def test_diagnose_caps_remaining_budget_consumption_at_fair_share(self) -> None:
        items = tuple(_FakeItem(index) for index in range(4))
        state = _FakeState()
        baseline = tuple(
            CatalogTraceRow(index, index, 0.5, 0, 0, 0, 0.0, 0.1, "proposal_exhausted")
            for index in range(4)
        )
        trace = CatalogTrace((), baseline, 0.0, 0.6, 0.6)
        probe_budgets = []
        classification_shares = []

        def prober(state, pool, pool_index, generator, settings, *, probe_budget_seconds):
            probe_budgets.append(probe_budget_seconds)
            return ProbeMeasurement(pool_index, False, None, 0.3, True)

        def classifier(measurement, *, fair_share_seconds):
            classification_shares.append(fair_share_seconds)
            return ProbeClassification(measurement, fair_share_seconds, False)

        diagnose_observation(
            {},
            state_builder=lambda observation: state,
            pool_builder=lambda observation: items,
            generator_factory=lambda settings: object(),
            settings_factory=lambda: _FakeSettings(),
            urgency_fn=lambda item, containers: 0.5,
            tracer=lambda *args, **kwargs: trace,
            prober=prober,
            classifier=classifier,
        )
        self.assertEqual(probe_budgets, [0.6, 0.6, 0.6, 0.6])
        for share in classification_shares:
            self.assertAlmostEqual(share, 0.15)

    def test_aggregate_rejects_manifest_hash_conflicts_and_duplicate_row_conflicts(self) -> None:
        import tempfile

        row = {
            "observation_id": "same",
            "lookahead": 20,
            "recoverable": True,
            "trace_rows": [{"pool_index": 0, "accepted_root_count": 0, "stop_reason": "proposal_exhausted"}],
            "probes": [{
                "pool_index": 0,
                "baseline_stop_reason": "proposal_exhausted",
                "measurement": {"exact_root_found": True, "time_to_first_exact_root": 0.01},
                "fair_share_seconds": 0.1,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            first = pathlib.Path(directory) / "first.json"
            second = pathlib.Path(directory) / "second.json"
            first.write_text(json.dumps({"manifest_sha256": EXPECTED_MANIFEST_SHA256, "observations": [row]}), encoding="utf-8")
            conflicting = dict(row)
            conflicting["recoverable"] = False
            second.write_text(json.dumps({"manifest_sha256": EXPECTED_MANIFEST_SHA256, "observations": [conflicting]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                _aggregate([str(first), str(second)])
            second.write_text(json.dumps({"manifest_sha256": "0" * 64, "observations": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                _aggregate([str(first), str(second)])

    def test_aggregate_recomputes_recoverability_instead_of_trusting_boolean(self) -> None:
        import tempfile

        row = {
            "observation_id": "derived",
            "lookahead": 20,
            "recoverable": True,
            "trace_rows": [{"pool_index": 0, "accepted_root_count": 0, "stop_reason": "proposal_exhausted"}],
            "probes": [{
                "pool_index": 0,
                "baseline_stop_reason": "proposal_exhausted",
                "measurement": {"exact_root_found": True, "time_to_first_exact_root": 0.01},
                "fair_share_seconds": 0.1,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            raw = pathlib.Path(directory) / "raw.json"
            raw.write_text(json.dumps({"manifest_sha256": EXPECTED_MANIFEST_SHA256, "observations": [row]}), encoding="utf-8")
            aggregate = _aggregate([str(raw)])
        self.assertEqual(aggregate["recoverable_state_count"], 0)
        self.assertEqual(aggregate["qualifying_state_ids"], [])

    def test_aggregate_manifest_output_contains_materialized_cases_not_templates(self) -> None:
        import tempfile

        case = {"containers": {"container_list": []}, "item_stream": {"item_list": []}}
        row = {
            "observation_id": "materialized-1",
            "template_number": 2,
            "seed": 17,
            "materialized_config": case,
            "materialized_metadata": {
                "warmup_target_steps": 8,
                "materialized_sha256": materialized_case_hash(case),
            },
            "materialized_sha256": materialized_case_hash(case),
            "trace_rows": [],
            "probes": [],
            "lookahead": 20,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            raw = root / "raw.json"
            output = root / "results.json"
            manifest = root / "manifest.json"
            raw.write_text(json.dumps({"manifest_sha256": EXPECTED_MANIFEST_SHA256, "observations": [row]}), encoding="utf-8")
            phase0_main(["--aggregate", str(raw), "--manifest-output", str(manifest), "--output", str(output)])
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest_payload["materialized_cases"]), 1)
        self.assertEqual(manifest_payload["materialized_cases"][0]["sha256"], materialized_case_hash(case))

    def test_fake_episode_diagnoses_each_pre_action_and_closes_on_false_status(self) -> None:
        class FakeEnv:
            def __init__(self, safe=True):
                self.safe = safe
                self.closed = False
                self.step_count = 0
                self.shm_depth_map = None

            def reset_settings(self): pass
            def reset_item_stream(self): pass
            def get_init_states(self): return {"lookahead_k": 1, "container_list": []}
            def reset(self, seed=None): return ({"pool_list": [], "container_list": []}, {})
            def step(self, action):
                self.step_count += 1
                status = {"is_placed_safe": self.safe}
                return ({"pool_list": [], "container_list": []}, 0, self.step_count >= 2, False, {"status": status})
            def close(self): self.closed = True

        class FakeAgent:
            def get_init_states(self, value): return True
            def policy(self, observation): return {"item_idx": 0}

        diagnosed = []
        def fake_diagnose(observation, *, observation_id):
            diagnosed.append(observation_id)
            return {
                "observation_id": observation_id, "lookahead": 1,
                "trace_rows": [], "probes": [], "stop_reason_counts": {},
                "time_to_first_exact_root_seconds": [], "recoverable": False,
            }

        env = FakeEnv()
        result = run_episode_with_diagnostics(env, FakeAgent(), diagnose_fn=fake_diagnose)
        self.assertEqual(result["completed_steps"], 2)
        self.assertEqual(diagnosed, ["episode-0000", "episode-0001"])
        self.assertTrue(env.closed)

        unsafe = FakeEnv(safe=False)
        with self.assertRaises(RuntimeError):
            run_episode_with_diagnostics(unsafe, FakeAgent(), diagnose_fn=fake_diagnose)
        self.assertTrue(unsafe.closed)

    def test_snapshot_loader_diagnoses_all_paths_and_preserves_sources(self) -> None:
        paths = [pathlib.Path("b.npz"), pathlib.Path("a.npz")]
        calls = []
        def loader(path):
            return ({"pool_list": [], "container_list": []}, {"source": path.stem})
        def diagnose(observation, *, observation_id):
            calls.append(observation_id)
            return {"observation_id": observation_id}
        rows = load_and_diagnose_snapshots(paths, loader=loader, diagnose_fn=diagnose)
        self.assertEqual(calls, ["snapshot-a", "snapshot-b"])
        self.assertEqual([row["source_file"] for row in rows], ["a.npz", "b.npz"])

    def test_manifest_preloaded_serializes_poses_removes_stream_items_and_fresh_reinitializes(self) -> None:
        sample_path = pathlib.Path(__file__).resolve().parents[1] / "configs" / "sample_config.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        template = next(template for template in build_fixed_manifest() if template["initial_state"] == "preloaded")
        calls = []
        def warmup(case, target, seed, initial_state):
            calls.append((target, initial_state, len(case["item_stream"]["item_list"])))
            return {
                "all_safe": True,
                "observation": {"container_list": [{"packed_items": [{"index": 0, "pos": [0, 0, 0]}]}]},
                "packed_items": [{"index": 0, "pos": [0, 0, 0]}],
            }
        result = materialize_manifest_observation(template, 17, sample, warmup_runner=warmup)
        self.assertEqual([call[0] for call in calls], [16, 0])
        self.assertEqual(result["materialized_config"]["containers"]["container_list"][0]["packed_items"][0]["index"], 0)
        self.assertNotIn(0, [item["index"] for item in result["materialized_config"]["item_stream"]["item_list"]])
        self.assertEqual(result["materialized_config"]["item_stream"]["visible_pool"], [])
        self.assertEqual(
            result["materialized_metadata"]["materialized_sha256"],
            result["materialized_sha256"],
        )

    def test_real_warmup_return_observation_always_has_depth_map(self) -> None:
        class FakeEnv:
            def __init__(self, **kwargs):
                self.shm_depth_map = [[1.0, 2.0]]
                self.closed = False

            def reset_settings(self): pass
            def reset_item_stream(self): pass
            def get_init_states(self): return {"lookahead_k": 20, "container_list": []}
            def reset(self, seed=None): return ({"container_list": [], "pool_list": []}, {})
            def step(self, action):
                return ({"container_list": [], "pool_list": []}, 0.0, True, False, {"status": {"safe": True}})
            def close(self): self.closed = True

        class FakeAgent:
            def __init__(self, path): pass
            def get_init_states(self, value): return True
            def policy(self, observation): return {"item_idx": 0}

        fake_agent_module = SimpleNamespace(Agent=FakeAgent)
        fake_env_module = SimpleNamespace(GroundHandlingEnv=FakeEnv)
        with patch.dict(
            sys.modules,
            {
                "agents.highscore.agent": fake_agent_module,
                "src.ground_handling.env": fake_env_module,
            },
        ), patch.object(phase0_module, "configure_mpc_agent", lambda agent: agent):
            for target_steps in (0, 1):
                result = run_real_warmup(
                    {"containers": {"container_list": []}}, target_steps, 17, "empty"
                )
                self.assertEqual(result["observation"]["depth_map"], [[1.0, 2.0]])

    def test_real_warmup_closes_env_when_agent_construction_raises(self) -> None:
        created = []

        class FakeEnv:
            def __init__(self, **kwargs):
                self.closed = False
                created.append(self)
            def close(self): self.closed = True

        class RaisingAgent:
            def __init__(self, path): raise RuntimeError("agent construction failed")

        with patch.dict(
            sys.modules,
            {
                "agents.highscore.agent": SimpleNamespace(Agent=RaisingAgent),
                "src.ground_handling.env": SimpleNamespace(GroundHandlingEnv=FakeEnv),
            },
        ):
            with self.assertRaises(RuntimeError):
                run_real_warmup({"containers": {"container_list": []}}, 0, 17, "empty")
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].closed)

    def test_real_task_closes_env_when_agent_construction_raises(self) -> None:
        class FakeEnv:
            def __init__(self): self.closed = False
            def close(self): self.closed = True

        env = FakeEnv()
        with self.assertRaises(RuntimeError):
            run_real_task_episode(
                {}, task_id="001", requested_items=1,
                env_factory=lambda config: env,
                agent_factory=lambda path: (_ for _ in ()).throw(RuntimeError("agent construction failed")),
            )
        self.assertTrue(env.closed)

    def test_cli_task_items_uses_injected_episode_runner_and_writes_raw_observations(self) -> None:
        import tempfile
        calls = []
        def episode_runner(config, *, task_id, requested_items, diagnose_fn):
            calls.append((task_id, requested_items, len(config["item_stream"]["item_list"])))
            return {"observations": [{"observation_id": "episode-0000", "lookahead": 1, "trace_rows": [], "probes": []}]}
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "raw.json"
            phase0_main(["--task", "001", "--items", "3", "--output", str(output)], episode_runner=episode_runner)
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(calls, [("001", 3, 3)])
        self.assertEqual(payload["observations"][0]["observation_id"], "episode-0000")

    def test_tracer_preserves_proposal_identity_and_restores_collaborators(self) -> None:
        identity = {}
        original_propose = highscore_catalog.propose_actions
        original_apply = highscore_catalog.apply_action
        original_time = highscore_catalog.time
        original_global_perf_counter = time.perf_counter
        _run_fake_catalog_trace("root", identity_log=identity)
        self.assertEqual(len(identity["proposed"]), len(identity["validated"]))
        self.assertEqual(len(identity["validated"]), len(identity["applied"]))
        for proposed, validated, applied in zip(
            identity["proposed"], identity["validated"], identity["applied"]
        ):
            self.assertIs(proposed, validated)
            self.assertIs(validated, applied)
        self.assertIs(highscore_catalog.propose_actions, original_propose)
        self.assertIs(highscore_catalog.apply_action, original_apply)
        self.assertIs(highscore_catalog.time, original_time)
        self.assertIs(time.perf_counter, original_global_perf_counter)

    def test_tracer_restores_all_refs_after_external_catalog_exception(self) -> None:
        original_propose = highscore_catalog.propose_actions
        original_apply = highscore_catalog.apply_action
        original_time = highscore_catalog.time
        original_global_perf_counter = time.perf_counter
        with self.assertRaises(RuntimeError):
            _run_fake_catalog_trace("external_catalog_throw")
        self.assertIs(highscore_catalog.propose_actions, original_propose)
        self.assertIs(highscore_catalog.apply_action, original_apply)
        self.assertIs(highscore_catalog.time, original_time)
        self.assertIs(time.perf_counter, original_global_perf_counter)

    def test_tracer_restores_directly_mutated_refs_before_test_cleanup(self) -> None:
        original_catalog = highscore_catalog.build_root_catalog
        original_propose = highscore_catalog.propose_actions
        original_apply = highscore_catalog.apply_action
        original_time = highscore_catalog.time
        original_global_perf_counter = time.perf_counter
        settings = _FakeSettings()
        state = _FakeState()
        pool = (_FakeItem(0),)
        generator = _FakeGenerator()

        temporary_propose = object()
        temporary_apply = object()
        temporary_time = SimpleNamespace(perf_counter=lambda: 0.0)

        def normal_catalog(state, pool, generator, settings, *, deadline):
            highscore_catalog.time.perf_counter()
            return []

        highscore_catalog.build_root_catalog = normal_catalog
        highscore_catalog.propose_actions = temporary_propose
        highscore_catalog.apply_action = temporary_apply
        highscore_catalog.time = temporary_time
        try:
            trace_production_catalog(state, pool, generator, settings, deadline=100.0)
            self.assertIs(highscore_catalog.propose_actions, temporary_propose)
            self.assertIs(highscore_catalog.apply_action, temporary_apply)
            self.assertIs(highscore_catalog.time, temporary_time)
        finally:
            highscore_catalog.build_root_catalog = original_catalog
            highscore_catalog.propose_actions = original_propose
            highscore_catalog.apply_action = original_apply
            highscore_catalog.time = original_time

        def raising_catalog(state, pool, generator, settings, *, deadline):
            raise RuntimeError("external catalog failure")

        highscore_catalog.build_root_catalog = raising_catalog
        highscore_catalog.propose_actions = temporary_propose
        highscore_catalog.apply_action = temporary_apply
        highscore_catalog.time = temporary_time
        try:
            with self.assertRaises(RuntimeError):
                trace_production_catalog(state, pool, generator, settings, deadline=100.0)
            self.assertIs(highscore_catalog.propose_actions, temporary_propose)
            self.assertIs(highscore_catalog.apply_action, temporary_apply)
            self.assertIs(highscore_catalog.time, temporary_time)
            self.assertIs(time.perf_counter, original_global_perf_counter)
        finally:
            highscore_catalog.build_root_catalog = original_catalog
            highscore_catalog.propose_actions = original_propose
            highscore_catalog.apply_action = original_apply
            highscore_catalog.time = original_time


class CausalClassificationTests(unittest.TestCase):
    def test_exact_stop_taxonomy_is_emitted_by_literal_collaborator_fixtures(self) -> None:
        traces = {
            "proposal_exhausted": _run_fake_catalog_trace("empty"),
            "unknown": _run_fake_catalog_trace("throw"),
            "per_item_quota": _run_fake_catalog_trace("root"),
            "global_cap": _run_fake_catalog_trace(
                "empty_then_root", ems_exact_roots_per_item=8, ems_root_catalog_limit=1
            ),
            "catalog_deadline": _run_fake_catalog_trace(
                "deadline", clock_step=0.1, ems_root_budget_seconds=0.5
            ),
            "not_visited": _run_fake_catalog_trace("not_visited"),
        }
        observed = {row.stop_reason for trace in traces.values() for row in trace.rows}
        self.assertEqual(
            observed,
            {
                "global_cap",
                "catalog_deadline",
                "not_visited",
                "proposal_exhausted",
                "per_item_quota",
                "unknown",
            },
        )

    def test_throwing_propose_actions_is_unknown(self) -> None:
        trace = _run_fake_catalog_trace("throw")
        self.assertEqual(trace.rows[0].stop_reason, "unknown")

    def test_early_zero_root_exhaustion_is_not_relabelled_by_later_cap(self) -> None:
        trace = _run_fake_catalog_trace(
            "empty_then_root", ems_exact_roots_per_item=8, ems_root_catalog_limit=1
        )
        self.assertEqual(trace.rows[0].accepted_root_count, 0)
        self.assertEqual(trace.rows[0].stop_reason, "proposal_exhausted")
        self.assertEqual(trace.rows[1].stop_reason, "global_cap")

    def test_early_zero_root_exhaustion_is_not_relabelled_by_later_deadline(self) -> None:
        trace = _run_fake_catalog_trace(
            "deadline", clock_step=0.1, ems_root_budget_seconds=1.0
        )
        self.assertEqual(trace.rows[0].accepted_root_count, 0)
        self.assertEqual(trace.rows[0].stop_reason, "proposal_exhausted")
        self.assertEqual(trace.rows[1].stop_reason, "unknown")

    def test_only_zero_root_cap_or_deadline_rows_are_recoverability_eligible(self) -> None:
        cap_trace = _run_fake_catalog_trace(
            "empty_then_root", ems_exact_roots_per_item=8, ems_root_catalog_limit=1
        )
        deadline_trace = _run_fake_catalog_trace(
            "deadline", clock_step=0.1, ems_root_budget_seconds=1.0
        )
        cap_eligible = {
            row.pool_index
            for row in cap_trace.rows
            if row.stop_reason in {"global_cap", "catalog_deadline"}
            and row.accepted_root_count == 0
        }
        deadline_eligible = {
            row.pool_index
            for row in deadline_trace.rows
            if row.stop_reason in {"global_cap", "catalog_deadline"}
            and row.accepted_root_count == 0
        }
        self.assertEqual(cap_eligible, {2, 3})
        self.assertEqual(deadline_eligible, {3})


if __name__ == "__main__":
    unittest.main()
