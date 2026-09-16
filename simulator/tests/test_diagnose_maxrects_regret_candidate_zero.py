from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tests.diagnose_maxrects_regret_candidate_zero import (
    StageProfiler,
    atomic_write_json,
    build_parser,
    classify_exhaustion,
    sha256_file,
    summarize_run,
)


class Task18dDiagnosticTests(unittest.TestCase):
    def test_run_summary_preserves_terminal_and_planner_evidence(self):
        payload = {
            "outcome": "candidate_zero",
            "safe_placements": 15,
            "final_packed_count": 15,
            "exception": {"message": "strict root catalog is empty", "step": 15},
            "records": [
                {"policy_seconds": 1.0},
                {"policy_seconds": 2.0},
                {"policy_seconds": 3.0},
            ],
            "policy_time_seconds": {
                "count": 4,
                "p50": 2.25,
                "p95": 3.5,
                "p99": 3.9,
                "max": 4.0,
            },
            "diagnostic": {"b_search_traces": [
                {"step": 0, "deadline_reached": True, "nodes": 2},
                {"step": 1, "node_quota_exhausted": True, "fit_tests": 4},
            ]},
            "evaluation": {"fill_score": 15.0},
        }
        result = summarize_run(payload)
        self.assertEqual(result["status"], "candidate_zero")
        self.assertEqual(result["failure_step"], 15)
        self.assertEqual(result["safe_placements"], 15)
        self.assertEqual(result["selector_deadline_steps"], 1)
        self.assertEqual(result["selector_node_quota_steps"], 1)
        self.assertEqual(result["selector_trace_by_step"][1]["fit_tests"], 4)
        self.assertEqual(result["policy_count"], 4)
        self.assertEqual(result["policy_p50"], 2.25)
        self.assertEqual(result["policy_max"], 4.0)

    def test_exhaustion_requires_zero_nonexpired_default_and_later_exact_root(self):
        default = [
            {"root_count": 0, "deadline_reached": False},
            {"root_count": 0, "deadline_reached": False},
        ]
        dense = [{"accepted": 0}, {"accepted": 6}]
        self.assertEqual(classify_exhaustion(default, dense), "candidate_exposure_cap")
        self.assertEqual(
            classify_exhaustion([{**default[0], "deadline_reached": True}], dense),
            "default_scan_deadline",
        )
        self.assertEqual(
            classify_exhaustion([{**default[0], "root_count": 1}], dense),
            "not_reproduced",
        )

    def test_profile_aggregation_is_bounded_and_json_serializable(self):
        profiler = StageProfiler()
        profiler.depth = 2
        profiler.lineage = 3
        profiler.add("enumerate_item", 0.125, 4)
        profiler.by_depth_lineage[profiler.context_key]["fit_tests"] += 8
        payload = profiler.as_dict()
        self.assertEqual(payload["totals"]["enumerate_item"]["calls"], 1)
        self.assertEqual(payload["totals"]["enumerate_item"]["outputs"], 4)
        self.assertEqual(
            payload["by_depth_lineage"]["depth2:lineage3"]["fit_tests"], 8
        )
        json.dumps(payload, allow_nan=False)

    def test_atomic_json_is_materialized_and_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "diagnosis.json"
            atomic_write_json(path, {"classification": "candidate_exposure_cap"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["classification"],
                "candidate_exposure_cap",
            )
            self.assertEqual(len(sha256_file(path)), 64)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_parser_requires_output_and_exposes_replay_controls(self):
        args = build_parser().parse_args(
            [
                "--output",
                "result.json",
                "--scan-repetitions",
                "4",
                "--replay-repetitions",
                "3",
                "--replay-seconds",
                "1.5",
                "--dense-limits",
                "128",
                "4096",
            ]
        )
        self.assertEqual(args.scan_repetitions, 4)
        self.assertEqual(args.replay_repetitions, 3)
        self.assertEqual(args.replay_seconds, 1.5)
        self.assertEqual(args.dense_limits, [128, 4096])


if __name__ == "__main__":
    unittest.main()
