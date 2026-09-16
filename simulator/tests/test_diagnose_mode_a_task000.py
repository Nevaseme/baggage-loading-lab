from __future__ import annotations

import json
import pathlib
import sys
import time
import unittest


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from tests.diagnose_mode_a_task000 import (  # noqa: E402
    analyze_order_beam,
    analyze_step_snapshot,
)
from tests.test_support_extreme_fusion_layered_proxy import (  # noqa: E402
    _container,
    _raw_item,
)


class ModeATask000DiagnosticTests(unittest.TestCase):
    def test_small_order_diagnosis_records_seeds_trace_and_compiler_outcome(self):
        result = analyze_order_beam(
            [_container()], [_raw_item(0)], order_seconds=5.0
        )
        self.assertGreaterEqual(result["candidate_count"], 1)
        self.assertEqual(
            result["complete_candidate_count"], result["candidate_count"]
        )
        self.assertEqual(
            result["compiler_invocations"], result["complete_candidate_count"]
        )
        self.assertTrue(any(row["published"] for row in result["compiler_rows"]))
        self.assertEqual(result["seeds"]["original"], [0])
        self.assertEqual(result["trace"]["deepest"], 1)

    def test_step11_snapshot_diagnosis_is_deterministic_under_bounded_dense_prefix(self):
        path = pathlib.Path(
            "simulator/results/support_extreme_fusion/"
            "task000-a-layered-proxy-order-beam-exact-skeleton-repair-seed42-failure.npz"
        )
        first = analyze_step_snapshot(path, dense_raw_limit=32)
        second = analyze_step_snapshot(path, dense_raw_limit=32)
        self.assertEqual(first["item0_index"], 11)
        self.assertEqual(first["packed_count"], 11)
        self.assertEqual(first["dense_direct"]["raw_records"], 32)
        self.assertEqual(
            first["dense_direct"]["rejection_counts"],
            second["dense_direct"]["rejection_counts"],
        )
        self.assertTrue(
            all(row["fresh_apply"] for row in first["fresh_apply_results"])
        )


if __name__ == "__main__":
    unittest.main()
