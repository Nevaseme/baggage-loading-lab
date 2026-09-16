import pathlib
import sys
import tempfile
import unittest

import numpy as np


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulator.tests.replay_support import (  # noqa: E402
    load_observation_snapshot,
    save_observation_snapshot,
)
from simulator.tests.replay_candidate_snapshot import analyze_snapshot  # noqa: E402
from simulator.tests.test_highscore_candidates import container_dict, item_dict  # noqa: E402


class ObservationSnapshotTests(unittest.TestCase):
    def test_round_trip_preserves_observation_and_excludes_shared_memory_handles(self):
        depth_map = np.arange(16, dtype=np.float32).reshape(4, 4) / 10.0
        observation = {
            "container_list": [
                {
                    "index": np.int64(3),
                    "center": np.array([1.25, -0.5, 0.8], dtype=np.float32),
                    "packed_items": [],
                }
            ],
            "pool_list": [
                {
                    "index": np.int32(17),
                    "length": np.float64(0.42),
                    "is_soft": np.bool_(True),
                }
            ],
            "depth_map": depth_map,
            "shm_depth_map_name": "must-not-be-replayed",
            "shm_depth_map": object(),
        }
        metadata = {
            "failed_step": np.int64(9),
            "action": {"place_pos": np.array([0.1, 0.2, 0.3], dtype=np.float32)},
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_path = pathlib.Path(temporary_directory) / "failure.npz"
            save_observation_snapshot(snapshot_path, observation, metadata)
            restored, restored_metadata = load_observation_snapshot(snapshot_path)

        self.assertEqual(
            restored["container_list"],
            [{"index": 3, "center": [1.25, -0.5, 0.800000011920929], "packed_items": []}],
        )
        self.assertEqual(
            restored["pool_list"],
            [{"index": 17, "length": 0.42, "is_soft": True}],
        )
        self.assertNotIn("shm_depth_map_name", restored)
        self.assertNotIn("shm_depth_map", restored)
        np.testing.assert_array_equal(restored["depth_map"], depth_map)
        self.assertEqual(restored["depth_map"].dtype, np.float32)
        self.assertEqual(
            restored_metadata,
            {"failed_step": 9, "action": {"place_pos": [0.10000000149011612, 0.20000000298023224, 0.30000001192092896]}},
        )

    def test_saved_snapshot_can_be_replayed_through_real_candidate_generation(self):
        observation = {
            "container_list": [container_dict()],
            "pool_list": [item_dict(index=21)],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_path = pathlib.Path(temporary_directory) / "candidate-state.npz"
            save_observation_snapshot(snapshot_path, observation, {"failed_step": 4})

            result = analyze_snapshot(snapshot_path, seconds=1.0)

        self.assertEqual(result["metadata"], {"failed_step": 4})
        self.assertEqual(result["pool_size"], 1)
        self.assertEqual(result["candidate_counts"][0]["item_index"], 21)
        self.assertGreater(result["candidate_counts"][0]["safe_candidates"], 0)
        self.assertEqual(
            set(result["candidate_counts"][0]["best_action"]),
            {"item_idx", "container_idx", "place_pos", "orientation"},
        )
        self.assertEqual(result["candidate_counts"][0]["best_action"]["item_idx"], 0)
        self.assertFalse(result["timed_out"])

    def test_replay_budget_is_shared_across_every_pool_item_in_failure_snapshot(self):
        snapshot_path = pathlib.Path(__file__).parent / "artifacts" / "task001_step23_failure.npz"
        observation, metadata = load_observation_snapshot(snapshot_path)

        result = analyze_snapshot(snapshot_path, seconds=0.25)

        self.assertEqual(metadata["task"], "001")
        self.assertEqual(metadata["failed_step"], 23)
        self.assertFalse(metadata["status"]["is_valid"])
        self.assertEqual(len(observation["container_list"][0]["packed_items"]), 23)
        self.assertEqual(observation["depth_map"].shape, (1, 64, 64))
        self.assertEqual(observation["depth_map"].dtype, np.float32)
        self.assertEqual(result["pool_size"], 7)
        self.assertEqual(len(result["candidate_counts"]), 7)
        self.assertEqual(
            [entry["item_index"] for entry in result["candidate_counts"]],
            [14, 17, 19, 21, 25, 26, 28],
        )
        self.assertTrue(result["timed_out"])
        self.assertTrue(
            all(entry["best_action"] is None for entry in result["candidate_counts"])
        )


if __name__ == "__main__":
    unittest.main()
