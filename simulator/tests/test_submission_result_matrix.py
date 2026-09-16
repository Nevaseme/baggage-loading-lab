from __future__ import annotations

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = PROJECT_ROOT / "analysis" / "submission_result_matrix.json"
SCHEMA_PATH = PROJECT_ROOT / "analysis" / "episode_evidence_schema.json"


EXPECTED_RECORDS = (
    {
        "algorithm": "Conservative Extreme-Point Packing",
        "artifact_path": "submit/Conservative Extreme-Point Packing_score29.7",
        "result_log_path": "submit/Conservative Extreme-Point Packing_score29.7/result-log.txt",
        "public_score": 29.74350010538,
        "public_score_note": "exact Public score from verified ledger",
    },
    {
        "algorithm": "Guarded Extreme-Point Beam",
        "artifact_path": "submit/highscore_guarded_20260813_score12.6",
        "result_log_path": "submit/highscore_guarded_20260813_score12.6/result-log.txt",
        "public_score": 12.622949582873819,
        "public_score_note": "exact Public score from verified ledger",
    },
    {
        "algorithm": "Ingress-Preserving Column Scaffold",
        "artifact_path": "submit/ingress_preserving_column_scaffold",
        "result_log_path": "submit/ingress_preserving_column_scaffold/result-log.txt",
        "public_score": None,
        "public_score_note": "pending; no Public score supplied",
    },
    {
        "algorithm": "Surface Frontier Extreme Backfill",
        "artifact_path": "submit/surface_frontier_extreme_backfill_score11",
        "result_log_path": "submit/surface_frontier_extreme_backfill_score11/result-log.txt",
        "public_score": None,
        "public_score_note": "rounded observation 11; exact value pending",
    },
)

COPIED_NUMERIC_FIELDS = (
    "fill_score",
    "cog_score",
    "stability_score",
    "placement_score",
    "soft_item_score",
    "num_placed_items",
    "optimization_max_seconds",
    "policy_max_seconds",
)

REQUIRED_MATRIX_FIELDS = {
    "algorithm",
    "artifact_path",
    "result_log_path",
    "public_score",
    "public_score_note",
    "status",
    *COPIED_NUMERIC_FIELDS,
    "metrics_provenance",
    "status_interpretation",
}

STATUS_INTERPRETATION = (
    "The externally returned status reports is_valid=false before placement; "
    "therefore is_placed_safe=false does not prove settling ran."
)


def load_submission_result_matrix(root: Path) -> list[dict]:
    """Load normalized external records for later evidence checks."""

    payload = json.loads((root / "analysis" / "submission_result_matrix.json").read_text())
    return payload["records"]


def _source_payload(root: Path, result_log_path: str) -> dict:
    return json.loads((root / result_log_path).read_text())


class SubmissionResultMatrixTests(unittest.TestCase):
    def test_matrix_has_exactly_one_record_for_each_source_result_log(self):
        payload = json.loads(MATRIX_PATH.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            payload["source_grain"],
            "Externally returned feedback metrics are averages/maxima over an "
            "unspecified evaluation scene set; they are not single-episode evidence.",
        )
        records = payload["records"]
        self.assertEqual(len(records), len(EXPECTED_RECORDS))
        self.assertEqual(
            {record["result_log_path"] for record in records},
            {expected["result_log_path"] for expected in EXPECTED_RECORDS},
        )
        self.assertEqual(
            len({record["result_log_path"] for record in records}),
            len(records),
        )
        self.assertEqual(
            len({record["artifact_path"] for record in records}),
            len(records),
        )

    def test_matrix_copies_every_source_value_without_inference(self):
        payload = json.loads(MATRIX_PATH.read_text())
        by_path = {record["result_log_path"]: record for record in payload["records"]}

        for expected in EXPECTED_RECORDS:
            source = _source_payload(PROJECT_ROOT, expected["result_log_path"])
            record = by_path[expected["result_log_path"]]
            self.assertTrue(REQUIRED_MATRIX_FIELDS.issubset(record))
            self.assertEqual(record["algorithm"], expected["algorithm"])
            self.assertEqual(record["artifact_path"], expected["artifact_path"])
            self.assertEqual(record["public_score"], expected["public_score"])
            self.assertEqual(record["public_score_note"], expected["public_score_note"])
            self.assertEqual(record["status"], source["status"])
            self.assertEqual(record["metrics_provenance"], "external_result_log")
            self.assertEqual(record["status_interpretation"], STATUS_INTERPRETATION)

            for field in COPIED_NUMERIC_FIELDS:
                source_key = field
                if field == "optimization_max_seconds":
                    source_key = "optimization"
                elif field == "policy_max_seconds":
                    source_key = "policy"
                source_value = source["time_results"][source_key] if source_key in source["time_results"] else source[source_key]
                self.assertEqual(record[field], source_value)

    def test_schema_declares_two_grains_and_all_required_field_types(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        self.assertEqual(schema["schema_version"], 1)

        expected_episode_fields = {
            "experiment_id": ("string", False),
            "baseline_id": ("string", True),
            "artifact_hash": ("string", False),
            "config_hash": ("string", False),
            "runner_hash": ("string", False),
            "lifecycle": ("object", False),
            "environment": ("object", False),
            "hardware": ("object", False),
            "timestamp": ("string", False),
            "task": ("string", False),
            "mode": ("string", False),
            "lookahead": ("integer", True),
            "seed": ("integer", False),
            "requested_items": ("integer", False),
            "effective_items": ("integer", False),
            "attempted_steps": ("integer", False),
            "policy_calls": ("integer", False),
            "safe_placements": ("integer", False),
            "completed_numerator": ("integer", False),
            "completed_denominator": ("integer", False),
            "fill_score": ("number", True),
            "evaluator_version": ("string", True),
            "terminal_outcome": ("string", False),
            "terminal_reason": ("string", False),
            "first_failed_predicate": ("string", True),
            "malformed_count": ("integer", False),
            "unchecked_count": ("integer", False),
            "invalid_count": ("integer", False),
            "unsafe_count": ("integer", False),
            "optimize_seconds": ("number", False),
            "optimize_limit_seconds": ("number", False),
            "policy_sample_count": ("integer", False),
            "policy_p50_seconds": ("number", True),
            "policy_p95_seconds": ("number", True),
            "policy_p99_seconds": ("number", True),
            "policy_max_seconds": ("number", True),
            "policy_limit_seconds": ("number", False),
            "action_hash": ("string", False),
            "raw_evidence_path": ("string", False),
        }
        expected_paired_fields = {
            "matched_manifest_hash": ("string", False),
            "pair_count": ("integer", False),
            "seed_count": ("integer", False),
            "median_safe_placement_delta": ("number", False),
            "mean_fill_score_delta": ("number", True),
            "worst_safety_regression": ("number", False),
            "candidate_zero_delta": ("number", True),
            "timing_sample_count": ("integer", False),
            "policy_p99_seconds": ("number", True),
            "policy_max_seconds": ("number", True),
            "gate_result": ("string", False),
        }

        for section_name, expected_fields in (
            ("episode_fact", expected_episode_fields),
            ("paired_experiment_aggregate", expected_paired_fields),
        ):
            section = schema[section_name]
            fields = section["required_fields"]
            self.assertEqual(set(fields), set(expected_fields))
            for field, (expected_type, expected_nullable) in expected_fields.items():
                self.assertEqual(fields[field]["type"], expected_type)
                self.assertEqual(fields[field]["nullable"], expected_nullable)

    def test_schema_declares_null_timing_when_no_samples_without_fabricated_zero(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        episode_semantics = schema["episode_fact"]["conditional_semantics"]
        paired_semantics = schema["paired_experiment_aggregate"]["conditional_semantics"]

        episode_rule = next(
            rule for rule in episode_semantics if rule["when"] == "policy_sample_count == 0"
        )
        self.assertEqual(
            episode_rule["fields"],
            [
                "policy_p50_seconds",
                "policy_p95_seconds",
                "policy_p99_seconds",
                "policy_max_seconds",
            ],
        )
        self.assertIsNone(episode_rule["must_be"])
        self.assertTrue(episode_rule["no_fabricated_zero"])

        paired_rule = next(
            rule
            for rule in paired_semantics
            if rule["when"] == "timing_sample_count == 0"
        )
        self.assertEqual(
            paired_rule["fields"],
            ["policy_p99_seconds", "policy_max_seconds"],
        )
        self.assertIsNone(paired_rule["must_be"])
        self.assertTrue(paired_rule["no_fabricated_zero"])

    def test_progress_keeps_surface_public_score_pending_and_notes_rounded_observation(self):
        progress = (PROJECT_ROOT / "progress.md").read_text()
        lines = progress.splitlines()
        header = next(line for line in lines if line.startswith("| Algorithm |"))
        header_cells = [cell.strip() for cell in header.strip("|").split("|")]
        score_index = header_cells.index("Public score")
        provenance_index = header_cells.index("Public score provenance")
        surface_line = next(
            line
            for line in lines
            if line.startswith("| Surface Frontier Extreme Backfill |")
        )
        surface_cells = [cell.strip() for cell in surface_line.strip("|").split("|")]
        self.assertEqual(surface_cells[score_index], "pending")
        self.assertNotIn("11", surface_cells[score_index])
        self.assertIn("11", surface_cells[provenance_index])

    def test_progress_does_not_claim_mode_a_planner_is_still_missing(self):
        progress = (PROJECT_ROOT / "progress.md").read_text()
        self.assertNotIn("while the missing Mode-A planner is implemented", progress)
        self.assertIn("Mode-A baseline and experiments are recorded below", progress)
        evidence_limit = progress.split("## Public-evaluation evidence limit", 1)[1]
        self.assertIn("Public score", evidence_limit)
        self.assertIn("external result-log", evidence_limit)
        self.assertIn("different grain", evidence_limit)
        self.assertNotIn(
            "component metrics are unavailable for the Public evaluations",
            evidence_limit,
        )


if __name__ == "__main__":
    unittest.main()
