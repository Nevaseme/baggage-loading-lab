from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from tests.replay_support import load_observation_snapshot, save_observation_snapshot  # noqa: E402
from tests.run_historical_conservative_extreme_point_physics import (  # noqa: E402
    ARTIFACT_SOURCE_SHA256,
    build_parser,
    run_historical_episode,
)
from tests.test_run_support_extreme_fusion_physics import (  # noqa: E402
    SAFE,
    _FakeAgent,
    _FakeEnv,
    _action,
    _raw_config,
)


class HistoricalPredicateReplayTests(unittest.TestCase):
    def _rectangular_snapshot(self, status: dict | None = None) -> tuple[dict, dict]:
        container = {
            "index": 0,
            "length": 2.0,
            "width": 1.45,
            "height": 1.61,
            "thickness": 0.04,
            "buffer": 0.0,
            "cut_x": 0.44,
            "cut_y": 0.4,
            "center": [0.0, 0.0, 0.805],
            "shelf": False,
            "is_prioritized": False,
            "packed_items": [],
            "points": [
                [-0.96, 0.0, 0.0],
                [0.96, 0.0, 0.0],
                [0.0, -0.685, 0.0],
                [0.0, 0.685, 0.0],
                [0.0, 0.0, 0.04],
                [0.0, 0.0, 1.57],
            ],
            "n_vecs": [
                [-1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, -1.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, -1.0],
                [0.0, 0.0, 1.0],
            ],
            "volume": 2.0 * 1.45 * 1.61,
        }
        observation = {
            "optimize": True,
            "lookahead_k": 1,
            "container_list": [container],
            "pool_list": [
                {
                    "index": 7,
                    "length": 0.2,
                    "width": 0.2,
                    "height": 0.2,
                    "mass": 1.0,
                    "is_prioritized": False,
                    "is_soft": False,
                }
            ],
        }
        metadata = {
            "task": "000",
            "seed": 42,
            "requested_mode": "A",
            "resolved_mode": "A",
            "step": 4,
            "official_status": copy.deepcopy(status or SAFE),
        }
        return observation, metadata

    def _replay_fixture(
        self,
        directory: Path,
        *,
        action: dict | None = None,
        status: dict | None = None,
        source_sha256: str = "a" * 64,
        config_sha256: str = "b" * 64,
        runner_sha256: str = "c" * 64,
        action_sequence_sha256: str = "d" * 64,
    ) -> tuple[Path, Path, dict, dict]:
        """Build one self-contained replay fixture for integrity tests."""

        from tests.replay_support import save_observation_snapshot

        action_value = action or {
            "item_idx": 0,
            "container_idx": 0,
            "place_pos": [0.0, 0.0, 0.15000000596046448],
            "orientation": 0,
        }
        if action_sequence_sha256 == "d" * 64:
            action_sequence_sha256 = hashlib.sha256(
                json.dumps(
                    [action_value],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
        status_value = copy.deepcopy(status or SAFE)
        observation, _metadata = self._rectangular_snapshot(status_value)
        metadata = {
            "task": "000",
            "seed": 42,
            "requested_mode": "A",
            "resolved_mode": "A",
            "step": 0,
            "action": copy.deepcopy(action_value),
            "official_status": copy.deepcopy(status_value),
            "status": copy.deepcopy(status_value),
            "historical_source_sha256": source_sha256,
            "source_sha256": source_sha256,
            "config_sha256": config_sha256,
            "runner_sha256": runner_sha256,
            "action_sequence_sha256": action_sequence_sha256,
        }
        snapshot_path = directory / "step-000.npz"
        save_observation_snapshot(snapshot_path, observation, metadata)
        snapshot_record = {
            "step": 0,
            "path": snapshot_path.name,
            "sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        }
        manifest_payload = {
            "task": "000",
            "seed": 42,
            "requested_mode": "A",
            "resolved_mode": "A",
            "historical_source_sha256": source_sha256,
            "config_sha256": config_sha256,
            "runner_sha256": runner_sha256,
            "action_sequence_sha256": action_sequence_sha256,
            "snapshots": [snapshot_record],
        }
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        episode_payload = {
            "task": "000",
            "seed": 42,
            "requested_mode": "A",
            "resolved_mode": "A",
            "snapshot_manifest_sha256": manifest_sha256,
            "historical_artifact": {"source_sha256": source_sha256},
            "historical_source_sha256": source_sha256,
            "config_sha256": config_sha256,
            "runner_sha256": runner_sha256,
            "action_sequence_sha256": action_sequence_sha256,
            "records": [
                {
                    "step": 0,
                    "action": copy.deepcopy(action_value),
                    "status": copy.deepcopy(status_value),
                }
            ],
        }
        episode_path = directory / "episode.json"
        episode_path.write_text(
            json.dumps(episode_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest_path, episode_path, manifest_payload, episode_payload

    @staticmethod
    def _rewrite_manifest_and_episode(
        manifest_path: Path,
        episode_path: Path,
        manifest_payload: dict,
        episode_payload: dict,
    ) -> None:
        manifest_path.write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        episode_payload["snapshot_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        episode_path.write_text(
            json.dumps(episode_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_parser_accepts_opt_in_capture_directory_and_defaults_disabled(self):
        # Catches removing the production CLI capture boundary or enabling
        # capture by default, which would alter the historical result boundary.
        default_args = build_parser().parse_args(["--output", "result.json"])
        self.assertIsNone(default_args.capture_all_snapshots)
        args = build_parser().parse_args(
            ["--output", "result.json", "--capture-all-snapshots", "snapshots"]
        )
        self.assertEqual(args.capture_all_snapshots, Path("snapshots"))

    def test_capture_serializes_one_exact_pre_action_snapshot_per_policy_call(self):
        # Catches writing snapshots from a validator/probe or after only the
        # first failure instead of retaining every parent-side policy call.
        env = _FakeEnv([SAFE, SAFE])
        agent = _FakeAgent(actions=[_action(0), _action(0)])
        with tempfile.TemporaryDirectory() as directory:
            result = run_historical_episode(
                _raw_config(),
                requested_items=2,
                seed=42,
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                capture_all_snapshots=Path(directory),
            )
            self.assertEqual(result["outcome"], "success")
            records = result["pre_action_snapshots"]
            self.assertEqual([record["step"] for record in records], [0, 1])
            self.assertEqual(len(records), 2)
            self.assertEqual(len(result["snapshot_manifest_sha256"]), 64)
            self.assertEqual(result["snapshot_manifest_sha256"], result["snapshot_manifest_sha256"].lower())
            manifest_path = Path(result["snapshot_manifest_path"])
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["snapshots"], records)
            for step, record in enumerate(records):
                snapshot_path = Path(record["path"])
                self.assertTrue(snapshot_path.is_file())
                self.assertEqual(record["sha256"], hashlib.sha256(snapshot_path.read_bytes()).hexdigest())
                observation, metadata = load_observation_snapshot(snapshot_path)
                self.assertEqual(metadata["task"], "000")
                self.assertEqual(metadata["seed"], 42)
                self.assertEqual(metadata["step"], step)
                self.assertEqual(metadata["official_status"], SAFE)
                self.assertEqual(metadata["historical_source_sha256"], ARTIFACT_SOURCE_SHA256.lower())
                self.assertEqual(len(metadata["config_sha256"]), 64)
                self.assertEqual(len(metadata["runner_sha256"]), 64)
                self.assertEqual(len(metadata["action_sequence_sha256"]), 64)
                self.assertEqual(metadata["action"]["place_pos"], [0.0, 0.0, 0.20000000298023224])
                self.assertTrue(np.array_equal(observation["depth_map"], np.arange(16, dtype=np.float32).reshape(1, 4, 4)))

    def test_capture_serialization_error_does_not_replace_physical_outcome(self):
        # Catches turning a post-episode artifact-write error into a physics
        # failure or mutating the official outcome after run_episode returns.
        env = _FakeEnv([SAFE])
        agent = _FakeAgent(actions=[_action(0)])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "not-a-directory"
            target.write_text("occupied", encoding="utf-8")
            result = run_historical_episode(
                _raw_config(),
                requested_items=1,
                seed=42,
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                capture_all_snapshots=target,
            )
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["safe_placements"], 1)
        self.assertIn("snapshot_capture_error", result)
        self.assertFalse(result["diagnostic"]["promotable"])

    def test_replay_action_reports_independent_strict_predicates_and_float32_target(self):
        # Catches replaying a Python-float target instead of the serialized
        # float32 action, collapsing all predicate fields to first-reason, or
        # deriving known_safe from the analytical mask rather than status.
        try:
            from tests.replay_historical_predicates import replay_action
        except ModuleNotFoundError as error:  # expected RED before implementation
            self.fail(f"replay API is missing: {error}")
        observation, metadata = self._rectangular_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "step-004.npz"
            save_observation_snapshot(path, observation, metadata)
            loaded_observation, loaded_metadata = load_observation_snapshot(path)
        row = replay_action(
            {"observation": loaded_observation, "metadata": loaded_metadata},
            {
                "item_idx": 0,
                "container_idx": 0,
                "place_pos": np.asarray((0.0, 0.0, 0.15), dtype=np.float32),
                "orientation": 0,
            },
        )
        self.assertEqual(row["step"], 4)
        self.assertEqual(row["item_occurrence"], 0)
        self.assertEqual(row["item_index"], 7)
        self.assertEqual(row["container_ordinal"], 0)
        self.assertEqual(row["orientation"], 0)
        self.assertEqual(row["target_float32"], [0.0, 0.0, 0.15000000596046448])
        self.assertEqual(row["known_safe"], True)
        self.assertEqual(row["official_status"], SAFE)
        self.assertEqual(row["exact_mask_accepted"], True)
        for predicate in (
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
        ):
            if predicate == "container_ordinal":
                self.assertIs(row["predicate_results"][predicate], True, predicate)
            else:
                self.assertIs(row[predicate], True, predicate)
        self.assertEqual(row["required_support"], 0.75)

    def test_replay_known_safe_comes_only_from_observed_status(self):
        # Catches marking a physically failed action known-safe because a
        # replayed predicate happens to pass, or marking it unsafe by inference
        # when the capture metadata says the official step was safe.
        try:
            from tests.replay_historical_predicates import replay_action
        except ModuleNotFoundError as error:  # expected RED before implementation
            self.fail(f"replay API is missing: {error}")
        failed_status = {
            "is_included": True,
            "is_valid": False,
            "is_placed_safe": False,
        }
        observation, metadata = self._rectangular_snapshot(failed_status)
        row = replay_action(
            {"observation": observation, "metadata": metadata},
            {
                "item_idx": 0,
                "container_idx": 0,
                "place_pos": np.asarray((0.0, 0.0, 0.15), dtype=np.float32),
                "orientation": 0,
            },
        )
        self.assertEqual(row["exact_mask_accepted"], True)
        self.assertEqual(row["known_safe"], False)
        self.assertEqual(row["official_status"], failed_status)

    def test_replay_manifest_rejects_tampered_zero_hash_manifest(self):
        # Catches accepting a manifest after a record digest is replaced with
        # a zero hash, even when the episode still points at the old manifest.
        from tests.replay_historical_predicates import replay_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, episode_path, manifest, _episode = self._replay_fixture(root)
            manifest["snapshots"][0]["sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                replay_manifest(manifest_path, episode_path)

    def test_replay_manifest_rejects_every_identity_boundary_mismatch(self):
        # Catches normalizing or checking identity in only one copy.  The
        # manifest=task999 case follows the episode manifest SHA update, so
        # only the strict identity correspondence can reject it.
        from tests.replay_historical_predicates import replay_manifest

        wrong_values = {
            "task": 999,
            "seed": "42",
            "requested_mode": True,
            "resolved_mode": "B",
        }
        for field, wrong_value in wrong_values.items():
            for boundary in ("manifest", "episode", "snapshot"):
                with self.subTest(field=field, boundary=boundary), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    manifest_path, episode_path, manifest, episode = self._replay_fixture(root)
                    if boundary == "manifest":
                        manifest[field] = wrong_value
                        self._rewrite_manifest_and_episode(
                            manifest_path, episode_path, manifest, episode
                        )
                    elif boundary == "episode":
                        episode[field] = wrong_value
                        episode_path.write_text(
                            json.dumps(episode, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                    else:
                        snapshot_path = root / manifest["snapshots"][0]["path"]
                        observation, metadata = load_observation_snapshot(snapshot_path)
                        metadata[field] = wrong_value
                        save_observation_snapshot(snapshot_path, observation, metadata)
                        manifest["snapshots"][0]["sha256"] = hashlib.sha256(
                            snapshot_path.read_bytes()
                        ).hexdigest()
                        self._rewrite_manifest_and_episode(
                            manifest_path, episode_path, manifest, episode
                        )
                    with self.assertRaises(ValueError):
                        replay_manifest(manifest_path, episode_path)

    def test_replay_manifest_rejects_corrupt_or_missing_npz(self):
        # Catches replaying an unreadable or absent NPZ as if it were evidence.
        from tests.replay_historical_predicates import replay_manifest

        for mode in ("corrupt", "missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest_path, episode_path, manifest, episode = self._replay_fixture(root)
                snapshot_path = root / manifest["snapshots"][0]["path"]
                if mode == "corrupt":
                    snapshot_path.write_bytes(b"not-an-npz")
                    manifest["snapshots"][0]["sha256"] = hashlib.sha256(
                        snapshot_path.read_bytes()
                    ).hexdigest()
                    self._rewrite_manifest_and_episode(
                        manifest_path, episode_path, manifest, episode
                    )
                else:
                    snapshot_path.unlink()
                with self.assertRaises(ValueError):
                    replay_manifest(manifest_path, episode_path)

    def test_replay_manifest_rejects_duplicate_or_missing_steps(self):
        # Catches sorting away duplicate steps or silently skipping a gap.
        from tests.replay_historical_predicates import replay_manifest

        for steps in ([0, 0], [0, 2]):
            with self.subTest(steps=steps), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest_path, episode_path, manifest, episode = self._replay_fixture(root)
                original = copy.deepcopy(manifest["snapshots"][0])
                manifest["snapshots"] = [
                    {**original, "step": int(step)} for step in steps
                ]
                episode["records"] = [
                    {"step": int(step), "action": copy.deepcopy(original_action), "status": SAFE}
                    for step, original_action in zip(
                        steps,
                        [
                            {
                                "item_idx": 0,
                                "container_idx": 0,
                                "place_pos": [0.0, 0.0, 0.15000000596046448],
                                "orientation": 0,
                            }
                        ]
                        * len(steps),
                    )
                ]
                self._rewrite_manifest_and_episode(
                    manifest_path, episode_path, manifest, episode
                )
                with self.assertRaises(ValueError):
                    replay_manifest(manifest_path, episode_path)

    def test_replay_manifest_rejects_metadata_hash_and_episode_action_mismatch(self):
        # Catches trusting one metadata copy instead of requiring all source,
        # config, runner, action, and official episode evidence to agree.
        from tests.replay_historical_predicates import replay_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, episode_path, manifest, episode = self._replay_fixture(root)
            observation, _metadata = self._rectangular_snapshot()
            from tests.replay_support import save_observation_snapshot

            metadata = {
                "task": "000",
                "seed": 42,
                "requested_mode": "A",
                "resolved_mode": "A",
                "step": 0,
                "action": episode["records"][0]["action"],
                "official_status": SAFE,
                "status": SAFE,
                "historical_source_sha256": "e" * 64,
                "source_sha256": "e" * 64,
                "config_sha256": manifest["config_sha256"],
                "runner_sha256": manifest["runner_sha256"],
                "action_sequence_sha256": manifest["action_sequence_sha256"],
            }
            snapshot_path = root / manifest["snapshots"][0]["path"]
            save_observation_snapshot(snapshot_path, observation, metadata)
            manifest["snapshots"][0]["sha256"] = hashlib.sha256(
                snapshot_path.read_bytes()
            ).hexdigest()
            self._rewrite_manifest_and_episode(manifest_path, episode_path, manifest, episode)
            with self.assertRaises(ValueError):
                replay_manifest(manifest_path, episode_path)

            # Restore the snapshot evidence and change only the official
            # episode action; correspondence must still fail closed.
            manifest_path, episode_path, manifest, episode = self._replay_fixture(root)
            episode["records"][0]["action"]["place_pos"] = [0.0, 0.0, 0.25]
            episode_path.write_text(
                json.dumps(episode, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                replay_manifest(manifest_path, episode_path)

    def test_invalid_action_has_explicit_reason_and_is_not_accepted(self):
        # Catches false+null rows being counted as accepted and losing the
        # distinction between malformed action and invalid item binding.
        from tests.replay_historical_predicates import replay_action, replay_manifest

        observation, metadata = self._rectangular_snapshot()
        invalid_item = replay_action(
            {"observation": observation, "metadata": metadata},
            {
                "item_idx": 99,
                "container_idx": 0,
                "place_pos": [0.0, 0.0, 0.15],
                "orientation": 0,
            },
        )
        self.assertFalse(invalid_item["exact_mask_accepted"])
        self.assertEqual(invalid_item["exact_mask_first_reason"], "item_binding")

        invalid_format = replay_action(
            {"observation": observation, "metadata": metadata},
            {
                "item_idx": 0,
                "container_idx": 0,
                "place_pos": [float("nan"), 0.0, 0.15],
                "orientation": 0,
            },
        )
        self.assertFalse(invalid_format["exact_mask_accepted"])
        self.assertEqual(invalid_format["exact_mask_first_reason"], "action_format")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, episode_path, manifest, episode = self._replay_fixture(
                root,
                action={
                    "item_idx": 99,
                    "container_idx": 0,
                    "place_pos": [0.0, 0.0, 0.15],
                    "orientation": 0,
                },
            )
            result = replay_manifest(manifest_path, episode_path)
            self.assertEqual(result["first_reject_reason_counts"].get("accepted", 0), 0)
            self.assertEqual(result["first_reject_reason_counts"].get("item_binding"), 1)

    def test_invalid_action_integer_and_range_contract_has_explicit_reason(self):
        # Catches bool/NumPy scalar coercion and negative indices reaching the
        # exact mask without an explicit non-accepted reason.
        from tests.replay_historical_predicates import replay_action

        observation, metadata = self._rectangular_snapshot()
        cases = (
            ("item_idx", -1, "item_binding"),
            ("container_idx", -1, "container_ordinal"),
            ("orientation", -1, "action_format"),
            ("orientation", 6, "action_format"),
            ("item_idx", True, "action_format"),
            ("container_idx", np.int64(0), "action_format"),
        )
        for field, value, expected_reason in cases:
            with self.subTest(field=field, value=value):
                action = {
                    "item_idx": 0,
                    "container_idx": 0,
                    "place_pos": [0.0, 0.0, 0.15],
                    "orientation": 0,
                }
                action[field] = value
                row = replay_action(
                    {"observation": observation, "metadata": metadata}, action
                )
                self.assertIs(row["exact_mask_accepted"], False)
                self.assertEqual(row["exact_mask_first_reason"], expected_reason)

    def test_capture_disabled_result_boundary_is_equal_and_has_no_capture_keys(self):
        # Catches leaking capture-only hashes/keys into the historical result
        # when the opt-in capture flag is disabled.
        def run_once():
            return run_historical_episode(
                _raw_config(),
                requested_items=1,
                seed=42,
                env_factory=lambda _config: _FakeEnv([SAFE]),
                agent_factory=lambda: _FakeAgent(actions=[_action(0)]),
                clock=iter((0.0, 0.1, 1.0, 1.2)).__next__,
            )

        first = run_once()
        second = run_once()
        capture_only_keys = {
            "pre_action_snapshots",
            "snapshot_manifest",
            "snapshot_manifest_path",
            "snapshot_manifest_sha256",
            "snapshot_capture_error",
            "historical_source_sha256",
            "config_sha256",
            "runner_sha256",
            "action_sequence_sha256",
        }
        self.assertTrue(capture_only_keys.isdisjoint(first))
        self.assertEqual(first, second)

    def test_policy_interval_only_retains_references_until_post_episode_materialization(self):
        # Catches deepcopy/save/hash/probe work from entering the measured
        # policy interval instead of running only after run_episode returns.
        import tests.run_historical_conservative_extreme_point_physics as runner

        phase = {"inside_policy": False}
        violations: list[str] = []
        events: list[str] = []
        real_deepcopy = runner.copy.deepcopy
        real_materialize = runner._materialize_policy_snapshots
        real_capture_digest = runner._capture_digest
        real_file_digest = runner._capture_file_digest
        real_save = runner._save_observation_snapshot_atomic

        class _PhaseAgent(_FakeAgent):
            def policy(self, observation):
                events.append("policy_enter")
                phase["inside_policy"] = True
                try:
                    return super().policy(observation)
                finally:
                    phase["inside_policy"] = False
                    events.append("policy_exit")

        def deepcopy_spy(value, *args, **kwargs):
            if phase["inside_policy"]:
                violations.append("deepcopy")
            return real_deepcopy(value, *args, **kwargs)

        def digest_spy(value):
            if phase["inside_policy"]:
                violations.append("capture_digest")
            return real_capture_digest(value)

        def file_digest_spy(path):
            if phase["inside_policy"]:
                violations.append("file_digest")
            return real_file_digest(path)

        def save_spy(*args, **kwargs):
            if phase["inside_policy"]:
                violations.append("save")
            return real_save(*args, **kwargs)

        def materialize_spy(*args, **kwargs):
            self.assertFalse(phase["inside_policy"])
            events.append("materialize")
            return real_materialize(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner.copy, "deepcopy", side_effect=deepcopy_spy), patch.object(
                runner, "_capture_digest", side_effect=digest_spy
            ), patch.object(
                runner, "_capture_file_digest", side_effect=file_digest_spy
            ), patch.object(
                runner, "_save_observation_snapshot_atomic", side_effect=save_spy
            ), patch.object(
                runner, "_materialize_policy_snapshots", side_effect=materialize_spy
            ):
                result = run_historical_episode(
                    _raw_config(),
                    requested_items=1,
                    seed=42,
                    env_factory=lambda _config: _FakeEnv([SAFE]),
                    agent_factory=lambda: _PhaseAgent(actions=[_action(0)]),
                    clock=iter((0.0, 0.1, 1.0, 1.2)).__next__,
                    capture_all_snapshots=Path(directory),
                )
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(violations, [])
        self.assertEqual(events, ["policy_enter", "policy_exit", "materialize"])

    def test_authoritative_exact_mask_survives_independent_diagnostic_error(self):
        # Catches running a copied predicate before ExactMask.diagnose and
        # discarding the authoritative decision when that copy raises.
        import tests.replay_historical_predicates as replay_module

        observation, metadata = self._rectangular_snapshot()
        with patch.object(
            replay_module,
            "_diagnose_predicates",
            side_effect=RuntimeError("independent diagnostic exploded"),
        ):
            row = replay_module.replay_action(
                {"observation": observation, "metadata": metadata},
                {
                    "item_idx": 0,
                    "container_idx": 0,
                    "place_pos": [0.0, 0.0, 0.15],
                    "orientation": 0,
                },
            )
        self.assertTrue(row["exact_mask_accepted"])
        self.assertIsInstance(row["diagnostic_errors"], list)
        self.assertEqual(row["diagnostic_errors"][0]["stage"], "independent_predicates")

    def test_capture_mismatch_is_structured_and_does_not_replace_episode_outcome(self):
        # Catches promoting snapshots when a policy call has no official
        # record, and catches a capture error changing the physical outcome.
        class _FlakyAgent(_FakeAgent):
            def policy(self, observation):
                if len(self.depth_copies) >= 1:
                    raise RuntimeError("policy stopped after first call")
                return super().policy(observation)

        env = _FakeEnv([SAFE, SAFE])
        agent = _FlakyAgent(actions=[_action(0)])
        with tempfile.TemporaryDirectory() as directory:
            result = run_historical_episode(
                _raw_config(),
                requested_items=2,
                seed=42,
                env_factory=lambda _config: env,
                agent_factory=lambda: agent,
                capture_all_snapshots=Path(directory),
            )
        self.assertEqual(result["outcome"], "other_exception")
        self.assertFalse(result["diagnostic"]["promotable"])
        self.assertEqual(result["snapshot_capture_error"]["type"], "HistoricalSnapshotCaptureError")
        self.assertIsInstance(result["snapshot_capture_error"]["details"], dict)


if __name__ == "__main__":
    unittest.main()
