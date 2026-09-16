from __future__ import annotations

import hashlib
import json
import math
import sys
import unittest
from pathlib import Path


SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.portal_reserved_scaffold_dag.agent import Agent  # noqa: E402
from agents.portal_reserved_scaffold_dag.historical_seed import (  # noqa: E402
    HistoricalSeedError,
    historical_source_descriptor,
)
from tests.run_support_extreme_fusion_physics import materialize_config  # noqa: E402


RESULTS_ROOT = SIMULATOR_ROOT / "results" / "portal_reserved_scaffold"
PACKAGE_ROOT = SIMULATOR_ROOT / "agents" / "portal_reserved_scaffold_dag"
SUBMIT_ROOT = SIMULATOR_ROOT.parent / "submit"
HISTORICAL_SOURCE = SUBMIT_ROOT / "Conservative Extreme-Point Packing_score29.7" / "high_score" / "agent.py"
EXPECTED_HISTORICAL_SOURCE_SHA256 = "ebe909962ab3a0722abb5ed3e67a42dceb64b116dd1f374c9ef739fdd3967f82"
EXPECTED_SUBMIT_MANIFEST_SHA256 = "95e6acacfb773b80b26df4d18a9ecaa514cd8cfeea4623f46aebd830b01b870c"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(root: Path) -> tuple[tuple[str, str], ...]:
    entries = []
    for path in root.rglob("*"):
        if path.is_file():
            entries.append((path.relative_to(root).as_posix(), _sha256_file(path)))
    return tuple(sorted(entries))


def _manifest_sha256(manifest: tuple[tuple[str, str], ...]) -> str:
    encoded = "".join(f"{relative}\t{digest}\n" for relative, digest in manifest).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_package_manifest() -> tuple[tuple[str, str], ...]:
    return tuple(entry for entry in _manifest(PACKAGE_ROOT) if "__pycache__/" not in entry[0])


def _json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PortalReservedScaffoldHistoricalCrossTests(unittest.TestCase):
    def test_historical_seed_is_standalone_and_does_not_reference_submit(self):
        # Catches runtime import/file reads of the immutable historical
        # artifact; the adaptation must be a self-contained source module.
        descriptor = historical_source_descriptor()
        self.assertEqual(descriptor["runtime_artifact_dependency"], False)
        self.assertEqual(descriptor["runtime_result_dependency"], False)
        source = (
            SIMULATOR_ROOT
            / "agents"
            / "portal_reserved_scaffold_dag"
            / "historical_seed.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/submit/", source.replace("\\", "/"))
        self.assertNotIn("submit\\", source)

    def test_agent_fail_closes_when_seed_candidate_or_authorization_fails(self):
        # Catches dummy/previous-action fallbacks that could send an unchecked
        # action to env.step after the shield rejects a historical candidate.
        agent = Agent("portal_reserved_scaffold_dag")
        agent.get_init_states({"container_list": [], "lookahead_k": 1, "optimize": True})
        with self.assertRaises(HistoricalSeedError):
            agent.policy({"pool_list": [], "container_list": []})

    def test_matched_cross_artifact_records_prefix_and_rejection_boundary(self):
        # Catches a runner that reports a score without proving the returned
        # prefix, pre-step rejection, timing, and immutable source hashes.
        result_path = RESULTS_ROOT / "task000-official-shield-cross-seed42.json"
        if not result_path.is_file():
            self.skipTest("matched physical cross has not been run")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        records = payload["records"]
        safe_records = [
            record
            for record in records
            if isinstance(record.get("status"), dict)
            and record["status"].get("is_valid") is True
            and record["status"].get("is_placed_safe") is True
        ]
        self.assertGreaterEqual(len(safe_records), 24)
        self.assertEqual(payload["safe_placements"], len(safe_records))
        last_fill = safe_records[-1]["fill_inputs"]
        derived_fill = min(
            100.0 * float(last_fill["inside_volume"]) / float(last_fill["container_volume"]),
            100.0,
        )
        self.assertAlmostEqual(payload["local_fill"], derived_fill, places=9)
        self.assertGreaterEqual(derived_fill, 32.0)
        self.assertEqual(last_fill["packed_count"], len(safe_records))
        self.assertEqual(payload["step_25"]["rejected_before_env_step"], True)
        # Catches recording len(records) after appending the rejected attempt
        # as env.step count; the pre-step rejection must leave the real count
        # unchanged at 25.
        self.assertEqual(payload["step_25"]["env_step_count_before"], len(safe_records))
        self.assertEqual(payload["step_25"]["env_step_count_after"], len(safe_records))
        self.assertEqual(
            payload["step_25"]["env_step_count_before"],
            payload["step_25"]["env_step_count_after"],
        )
        self.assertEqual(payload["first_rejection_reason"], "target_penetration")
        self.assertEqual(payload["returned_invalid_count"], 0)
        self.assertEqual(payload["returned_unsafe_count"], 0)
        derived_max_time = max(float(record["policy_seconds"]) for record in records)
        self.assertAlmostEqual(payload["policy_time_seconds"]["max"], derived_max_time, places=9)
        self.assertLess(derived_max_time, 6.0)

        captured = json.loads((RESULTS_ROOT / "historical-task000-captured.json").read_text(encoding="utf-8"))
        expected_prefix = [record["action"] for record in captured["records"][:25]]
        returned_prefix = [record["action"] for record in safe_records[:25]]
        self.assertEqual(returned_prefix, expected_prefix)
        self.assertEqual(payload["action_prefix_returned_count"], len(returned_prefix))
        self.assertEqual(payload["action_prefix_sha256"], _json_sha256(returned_prefix))
        self.assertEqual(payload["action_prefix_expected_sha256"], _json_sha256(expected_prefix))
        self.assertEqual(payload["action_prefix_divergence"], [])

        stable_manifest = _stable_package_manifest()
        self.assertEqual(payload["package_manifest"], [list(entry) for entry in stable_manifest])
        self.assertEqual(payload["package_sha256"], _manifest_sha256(stable_manifest))
        self.assertEqual(payload["runner_sha256"], _sha256_file(Path(__file__).with_name("run_portal_reserved_scaffold_historical_cross.py")))
        self.assertEqual(payload["historical_seed_sha256"], _sha256_file(PACKAGE_ROOT / "historical_seed.py"))
        self.assertEqual(_sha256_file(HISTORICAL_SOURCE), EXPECTED_HISTORICAL_SOURCE_SHA256)
        self.assertEqual(payload["historical_source_sha256"], _sha256_file(HISTORICAL_SOURCE))

        submit_manifest_sha256 = _manifest_sha256(_manifest(SUBMIT_ROOT))
        self.assertEqual(submit_manifest_sha256, EXPECTED_SUBMIT_MANIFEST_SHA256)
        integrity = payload["historical_artifact_integrity"]
        self.assertEqual(integrity["before_manifest_sha256"], EXPECTED_SUBMIT_MANIFEST_SHA256)
        self.assertEqual(integrity["after_manifest_sha256"], EXPECTED_SUBMIT_MANIFEST_SHA256)
        self.assertTrue(integrity["before_matches_baseline"])
        self.assertTrue(integrity["after_matches_baseline"])
        self.assertTrue(integrity["unchanged"])

        config_payload = json.loads((SIMULATOR_ROOT / "configs" / "sample_config.json").read_text(encoding="utf-8"))
        config = materialize_config(config_payload, "000", 41, "A")
        self.assertEqual(payload["config_sha256"], _json_sha256(config))


if __name__ == "__main__":
    unittest.main()
