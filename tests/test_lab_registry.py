import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import os
import stat
import shutil
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


class LabCliTest(unittest.TestCase):
    def run_cli(self, root, *args):
        completed = subprocess.run(
            [str(PYTHON), "-m", "tools.lab", "--root", str(root), *args],
            cwd=PROJECT,
            text=True,
            capture_output=True,
        )
        return completed

    def test_ingest_roundtrip_registers_exact_source_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            source_zip = Path(temp) / "candidate.zip"
            with zipfile.ZipFile(source_zip, "w") as archive:
                archive.writestr("agent.py", b"print('candidate')\n")
                archive.writestr("nested/config.json", b'{"value": 1}\n')

            completed = self.run_cli(root, "ingest", "--zip", source_zip, "--name", "Candidate")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            artifact_id = response["artifact_id"]
            artifact_dir = root / "artifacts" / artifact_id
            self.assertEqual((artifact_dir / "source" / "agent.py").read_bytes(), b"print('candidate')\n")
            self.assertEqual((artifact_dir / "source" / "nested" / "config.json").read_bytes(), b'{"value": 1}\n')
            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifact_id"], artifact_id)
            self.assertEqual(manifest["archive_availability"], "available")
            self.assertEqual(len(manifest["zip_sha256"]), 64)
            self.assertEqual(
                manifest["source_file_hashes"]["agent.py"],
                hashlib.sha256(b"print('candidate')\n").hexdigest(),
            )

    def make_zip(self, directory, filename="candidate.zip", files=None):
        path = Path(directory) / filename
        files = files or {"agent.py": b"print(1)\n"}
        with zipfile.ZipFile(path, "w") as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)
        return path

    def ingest(self, root, archive, name="Candidate"):
        completed = self.run_cli(root, "ingest", "--zip", archive, "--name", name)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_same_bytes_deduplicate_and_different_bytes_do_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            first = self.make_zip(temp, "first.zip", {"agent.py": b"same\n"})
            second = Path(temp) / "copy.zip"
            second.write_bytes(first.read_bytes())
            third = self.make_zip(temp, "different.zip", {"agent.py": b"different\n"})
            one = self.ingest(root, first, "First")
            two = self.ingest(root, second, "Other name")
            three = self.ingest(root, third, "First")
            self.assertEqual(one["artifact_id"], two["artifact_id"])
            self.assertTrue(two["deduplicated"])
            self.assertNotEqual(one["artifact_id"], three["artifact_id"])
            self.assertFalse(three["deduplicated"])

    def test_ingest_repairs_missing_zip_cache_in_a_clean_clone(self):
        with tempfile.TemporaryDirectory() as temp:
            first_root = Path(temp) / "first"
            clean_root = Path(temp) / "clean-clone"
            archive = self.make_zip(temp)
            first = self.ingest(first_root, archive)
            shutil.copytree(first_root / "artifacts", clean_root / "artifacts")
            repeated = self.run_cli(clean_root, "ingest", "--zip", archive, "--name", "Candidate")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            response = json.loads(repeated.stdout)
            self.assertTrue(response["deduplicated"])
            artifact_id = first["artifact_id"]
            cached = clean_root / ".lab" / "assets" / f"{artifact_id.removeprefix('artifact-')}.zip"
            self.assertEqual(cached.read_bytes(), archive.read_bytes())

    def test_import_source_preserves_bytes_but_omits_python_caches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            source = Path(temp) / "source"
            (source / "pkg" / "__pycache__").mkdir(parents=True)
            (source / "pkg" / "agent.py").write_bytes(b"source\x00bytes")
            (source / "pkg" / "__pycache__" / "agent.cpython-312.pyc").write_bytes(b"cache")
            response = self.run_cli(root, "import-source", "--source", source, "--name", "Source"); self.assertEqual(response.returncode, 0, response.stderr)
            artifact_id = json.loads(response.stdout)["artifact_id"]
            artifact = root / "artifacts" / artifact_id
            self.assertEqual((artifact / "source" / "pkg" / "agent.py").read_bytes(), b"source\x00bytes")
            self.assertFalse((artifact / "source" / "pkg" / "__pycache__").exists())
            manifest = json.loads((artifact / "manifest.json").read_text())
            self.assertIsNone(manifest["zip_sha256"])
            self.assertEqual(manifest["archive_availability"], "missing")
            self.assertEqual(manifest["identity_kind"], "source")

    def test_source_identity_uses_path_and_file_hash_without_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            source = Path(temp) / "source"
            source.mkdir()
            payload = b"source identity\n"
            (source / "agent.py").write_bytes(payload)
            completed = self.run_cli(root, "import-source", "--source", source, "--name", "Source")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            file_digest = hashlib.sha256(payload).hexdigest().encode("ascii")
            expected_identity = hashlib.sha256(b"agent.py\0" + file_digest).hexdigest()
            self.assertEqual(json.loads(completed.stdout)["artifact_id"], f"source-{expected_identity}")

    def test_source_only_artifact_accepts_evaluation_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            source = Path(temp) / "source"
            source.mkdir()
            (source / "agent.py").write_bytes(b"source")
            imported = self.run_cli(root, "import-source", "--source", source, "--name", "Source")
            self.assertEqual(imported.returncode, 0, imported.stderr)
            artifact = json.loads(imported.stdout)["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"1"}', encoding="utf-8")
            recorded = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(recorded.returncode, 0, recorded.stdout)

    def test_record_preserves_decimal_text_status_and_raw_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            archive = self.make_zip(temp)
            artifact = self.ingest(root, archive)["artifact_id"]
            result = Path(temp) / "feedback.json"
            raw = b'{"fill_score":1.2300,"num_placed_items":4,"time_results":{"policy":0.0100},"status":"mystery","extra":{"x":9}}\n'
            result.write_bytes(raw)
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--public-score", "29.74350010538", "--submission-id", "sub-1")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            record_path = root / "evaluations" / response["evaluation_id"] / "record.json"
            record = json.loads(record_path.read_text())
            self.assertEqual(record["public_score"], "29.74350010538")
            self.assertEqual(record["status_raw"], "mystery")
            self.assertEqual(record["status_normalized"], "unknown")
            self.assertEqual(record["metrics"]["fill_score"], "1.2300")
            self.assertEqual(record["timing"]["policy"], "0.0100")
            self.assertEqual(record["raw_feedback"]["extra"]["x"], "9")
            self.assertEqual(record["raw_result_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(record["association_basis"]["artifact_identity"]["zip_sha256"], json.loads((root / "artifacts" / artifact / "manifest.json").read_text())["zip_sha256"])
            self.assertTrue(record["association_basis"]["score_override"]["recorded_with_raw_result"])
            self.assertEqual((record_path.parent / "raw" / "result.json").read_bytes(), raw)
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            valid = self.run_cli(root, "validate")
            self.assertEqual(valid.returncode, 0, valid.stdout)

    def test_json_feedback_in_a_result_log_text_file_is_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result-log.txt"
            result.write_text(
                "{\"fill_score\": 24.805389462909353, \"time_results\": {\"policy\": 5.75}, \"status\": \"Stopped in the middle. Did not satisfy {'is_valid', 'is_placed_safe'}\"}",
                encoding="utf-8",
            )
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evaluation_id = json.loads(completed.stdout)["evaluation_id"]
            record = json.loads((root / "evaluations" / evaluation_id / "record.json").read_text())
            self.assertEqual(record["metrics"]["fill_score"], "24.805389462909353")
            self.assertEqual(record["timing"]["policy"], "5.75")
            self.assertEqual(record["status_normalized"], "stopped")

    def test_plain_score_and_rounded_score_stay_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            note = Path(temp) / "note.txt"
            note.write_text("approximately 11 points", encoding="utf-8")
            rounded = self.run_cli(root, "record", "--artifact", artifact, "--result", note)
            self.assertEqual(rounded.returncode, 0, rounded.stderr)
            record = json.loads((root / "evaluations" / json.loads(rounded.stdout)["evaluation_id"] / "record.json").read_text())
            self.assertIsNone(record["public_score"])
            self.assertEqual(record["rounded_public"], "approximately 11 points")
            exact = Path(temp) / "score.txt"
            exact.write_text("Public score: 11.0000", encoding="utf-8")
            exact_result = self.run_cli(root, "record", "--artifact", artifact, "--result", exact)
            self.assertEqual(exact_result.returncode, 0, exact_result.stderr)
            exact_record = json.loads((root / "evaluations" / json.loads(exact_result.stdout)["evaluation_id"] / "record.json").read_text())
            self.assertEqual(exact_record["public_score"], "11.0000")

    def test_score_note_is_accepted_even_when_result_filename_is_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "score.json"; result.write_text("29.74350010538", encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            evaluation_id = json.loads(completed.stdout)["evaluation_id"]
            record = json.loads((root / "evaluations" / evaluation_id / "record.json").read_text())
            self.assertEqual(record["public_score"], "29.74350010538")

    def test_approximate_json_public_value_stays_rounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"about 11"}', encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            evaluation_id = json.loads(completed.stdout)["evaluation_id"]
            record = json.loads((root / "evaluations" / evaluation_id / "record.json").read_text())
            self.assertIsNone(record["public_score"])
            self.assertEqual(record["rounded_public"], "about 11")

    def test_exact_decimal_score_keeps_leading_zero_and_trailing_precision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"status":"completed"}', encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--public-score", "001.2300")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            evaluation_id = json.loads(completed.stdout)["evaluation_id"]
            record = json.loads((root / "evaluations" / evaluation_id / "record.json").read_text())
            self.assertEqual(record["public_score"], "001.2300")

    def test_explicit_score_override_records_conflicting_invalid_input_as_raw_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"not-a-score"}', encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--public-score", "29.74350010538")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            evaluation_id = json.loads(completed.stdout)["evaluation_id"]
            record = json.loads((root / "evaluations" / evaluation_id / "record.json").read_text())
            self.assertEqual(record["public_score"], "29.74350010538")
            self.assertTrue(record["association_basis"]["score_override_conflicted_with_input"])
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            valid = self.run_cli(root, "validate")
            self.assertEqual(valid.returncode, 0, valid.stdout)

    def test_ambiguous_plain_score_fails_without_mutating_evaluations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            note = Path(temp) / "ambiguous.txt"
            note.write_text("score: 10; public score: 11", encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", note)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(list((root / "evaluations").iterdir()), [])

    def test_same_evidence_deduplicates_but_submission_id_allows_reevaluation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "feedback.json"
            result.write_text('{"status":"completed"}', encoding="utf-8")
            first = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--submission-id", "submission-a")
            retry = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--submission-id", "submission-a")
            other = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--submission-id", "submission-b")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(other.returncode, 0, other.stderr)
            first_id = json.loads(first.stdout)["evaluation_id"]
            self.assertEqual(first_id, json.loads(retry.stdout)["evaluation_id"])
            self.assertTrue(json.loads(retry.stdout)["deduplicated"])
            self.assertNotEqual(first_id, json.loads(other.stdout)["evaluation_id"])

    def test_same_evidence_deduplicates_against_legacy_association_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "feedback.json"
            result.write_text('{"status":"completed"}', encoding="utf-8")
            first = self.run_cli(
                root,
                "record",
                "--artifact",
                artifact,
                "--result",
                result,
                "--public-score",
                "12.300",
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            evaluation_id = json.loads(first.stdout)["evaluation_id"]
            record_path = root / "evaluations" / evaluation_id / "record.json"
            legacy = json.loads(record_path.read_text(encoding="utf-8"))
            for field in (
                "rounded_public_override",
                "submission_id_override",
                "supersedes_override",
            ):
                del legacy["association_basis"][field]
            record_path.write_text(
                json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            preserved = record_path.read_bytes()

            retry = self.run_cli(
                root,
                "record",
                "--artifact",
                artifact,
                "--result",
                result,
                "--public-score",
                "12.300",
            )

            self.assertEqual(retry.returncode, 0, retry.stdout)
            self.assertTrue(json.loads(retry.stdout)["deduplicated"])
            self.assertEqual(record_path.read_bytes(), preserved)

    def test_same_evidence_deduplicates_after_result_file_is_renamed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            original = Path(temp) / "original-result.json"
            renamed = Path(temp) / "renamed-result.json"
            raw = b'{"public_score":"42.123","status":"completed"}'
            original.write_bytes(raw)
            renamed.write_bytes(raw)
            first = self.run_cli(root, "record", "--artifact", artifact, "--result", original)
            self.assertEqual(first.returncode, 0, first.stderr)
            evaluation_id = json.loads(first.stdout)["evaluation_id"]
            record_path = root / "evaluations" / evaluation_id / "record.json"
            preserved = record_path.read_bytes()

            retry = self.run_cli(root, "record", "--artifact", artifact, "--result", renamed)

            self.assertEqual(retry.returncode, 0, retry.stdout)
            self.assertTrue(json.loads(retry.stdout)["deduplicated"])
            self.assertEqual(record_path.read_bytes(), preserved)

    def test_correction_links_old_evaluation_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            old_result = Path(temp) / "old.json"; old_result.write_text('{"public_score":"10"}', encoding="utf-8")
            old = self.run_cli(root, "record", "--artifact", artifact, "--result", old_result)
            self.assertEqual(old.returncode, 0, old.stderr)
            old_id = json.loads(old.stdout)["evaluation_id"]
            new_result = Path(temp) / "new.json"; new_result.write_text('{"public_score":"11","supersedes":"%s"}' % old_id, encoding="utf-8")
            new = self.run_cli(root, "record", "--artifact", artifact, "--result", new_result)
            self.assertEqual(new.returncode, 0, new.stderr)
            new_id = json.loads(new.stdout)["evaluation_id"]
            self.assertTrue((root / "evaluations" / old_id / "record.json").is_file())
            newer = json.loads((root / "evaluations" / new_id / "record.json").read_text())
            self.assertEqual(newer["supersedes_evaluation_id"], old_id)

    def test_validate_recomputes_evaluation_identity_after_record_tampering(self):
        for field, value in (("public_score", "2"), ("submission_id", "tampered")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "registry"
                artifact = self.ingest(root, self.make_zip(temp)) ["artifact_id"]
                result = Path(temp) / "result.json"
                result.write_text('{"public_score":"1","submission_id":"original"}', encoding="utf-8")
                response = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
                self.assertEqual(response.returncode, 0, response.stderr)
                evaluation_id = json.loads(response.stdout)["evaluation_id"]
                record_path = root / "evaluations" / evaluation_id / "record.json"
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record[field] = value
                record_path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(self.run_cli(root, "render").returncode, 0)
                invalid = self.run_cli(root, "validate")
                self.assertNotEqual(invalid.returncode, 0)
                self.assertTrue(
                    "identity" in invalid.stdout
                    or "feedback mismatch" in invalid.stdout
                    or "raw-derived field mismatch" in invalid.stdout
                )

    def test_validate_reparses_raw_feedback_before_accepting_derived_fields(self):
        mutations = {
            "public_score": lambda record: (
                record.update(public_score="2.00"),
                record["raw_feedback"].update(public_score="2.00"),
            ),
            "metrics": lambda record: (
                record["metrics"].update(fill_score="99.0"),
                record["raw_feedback"].update(fill_score="99.0"),
            ),
            "timing": lambda record: (
                record["timing"].update(policy="99.0"),
                record["raw_feedback"]["time_results"].update(policy="99.0"),
            ),
            "status": lambda record: (
                record.update(status_raw="changed", status_normalized="unknown"),
                record["raw_feedback"].update(status="changed"),
            ),
            "competition": lambda record: (
                record.update(competition_id="changed"),
                record["raw_feedback"].update(competition_id="changed"),
            ),
            "evaluated_at": lambda record: (
                record.update(evaluated_at="changed"),
                record["raw_feedback"].update(evaluated_at="changed"),
            ),
            "kind": lambda record: (
                record.update(evaluation_kind="changed"),
                record["raw_feedback"].update(kind="changed"),
            ),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "registry"
                artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
                result = Path(temp) / "feedback.json"
                result.write_text(
                    json.dumps(
                        {
                            "public_score": "1.00",
                            "fill_score": 2.5,
                            "cog_score": 3.5,
                            "time_results": {"optimization": 4.5, "policy": 0.25},
                            "status": "completed",
                            "submission_id": "raw-submission",
                            "competition_id": "raw-competition",
                            "evaluated_at": "2026-09-08T00:00:00Z",
                            "kind": "public",
                        }
                    ),
                    encoding="utf-8",
                )
                recorded = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
                self.assertEqual(recorded.returncode, 0, recorded.stderr)
                evaluation_id = json.loads(recorded.stdout)["evaluation_id"]
                record_path = root / "evaluations" / evaluation_id / "record.json"
                record = json.loads(record_path.read_text(encoding="utf-8"))
                mutate(record)
                record_path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(self.run_cli(root, "render").returncode, 0)
                invalid = self.run_cli(root, "validate")
                self.assertNotEqual(invalid.returncode, 0, field)

    def test_validate_requires_one_known_raw_result_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "feedback.json"
            result.write_text(
                '{"public_score":"1.00","fill_score":2.5,"status":"completed"}',
                encoding="utf-8",
            )
            recorded = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            evaluation_id = json.loads(recorded.stdout)["evaluation_id"]
            record_path = root / "evaluations" / evaluation_id / "record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["public_score"] = "2.00"
            record["metrics"]["fill_score"] = "99.0"
            record["status_raw"] = "changed"
            record["status_normalized"] = "unknown"
            record["raw_feedback"].update(
                public_score="2.00",
                fill_score="99.0",
                status="changed",
            )
            record["evidence_refs"][0]["kind"] = "not_raw_result"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)

            invalid = self.run_cli(root, "validate")

            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("evidence kind", invalid.stdout)
            self.assertIn("raw-result evidence", invalid.stdout)

    def test_validate_binds_parser_selection_to_recorded_source_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "score.json"
            result.write_text('"1.250"', encoding="utf-8")
            recorded = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            evaluation_id = json.loads(recorded.stdout)["evaluation_id"]
            record_path = root / "evaluations" / evaluation_id / "record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["public_score"] = None
            record["evaluation_kind"] = "unknown"
            record["association_basis"]["source_path_name"] = "score.txt"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)

            invalid = self.run_cli(root, "validate")

            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("raw-derived field", invalid.stdout)

    def test_scalar_json_string_score_validates_against_its_raw_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "score.json"
            result.write_text('"42.123"', encoding="utf-8")
            recorded = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            evaluation_id = json.loads(recorded.stdout)["evaluation_id"]
            record = json.loads(
                (root / "evaluations" / evaluation_id / "record.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["public_score"], "42.123")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)

            valid = self.run_cli(root, "validate")

            self.assertEqual(valid.returncode, 0, valid.stdout)

    def test_validate_requires_artifact_id_to_match_zip_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            manifest_path = root / "artifacts" / artifact / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["zip_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("ZIP identity", invalid.stdout)

    def test_record_rejects_result_symlink_and_symlinked_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            real_result = Path(temp) / "real-result.json"
            real_result.write_text('{"public_score":"1"}', encoding="utf-8")
            link = Path(temp) / "result-link.json"
            try:
                os.symlink(real_result, link)
            except (OSError, NotImplementedError):
                self.skipTest("file symlinks are unavailable")
            direct = self.run_cli(root, "record", "--artifact", artifact, "--result", link)
            self.assertNotEqual(direct.returncode, 0)
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "result.json").write_text('{"public_score":"1"}', encoding="utf-8")
            ancestor = Path(temp) / "ancestor-link"
            try:
                os.symlink(outside, ancestor, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            nested = self.run_cli(root, "record", "--artifact", artifact, "--result", ancestor / "result.json")
            self.assertNotEqual(nested.returncode, 0)
            self.assertFalse((root / "evaluations").exists() and any((root / "evaluations").iterdir()))

    def test_export_rejects_protected_or_existing_generic_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            protected = root / "artifacts" / artifact / "source" / "agent.py"
            original_bytes = protected.read_bytes()
            rejected = self.run_cli(root, "export-context", "--output", protected)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(protected.read_bytes(), original_bytes)
            existing = Path(temp) / "already-there.zip"
            existing.write_bytes(b"preserve me")
            rejected = self.run_cli(root, "export-context", "--output", existing)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(existing.read_bytes(), b"preserve me")
            safe = root / ".lab" / "exports" / "context.zip"
            accepted = self.run_cli(root, "export-context", "--output", safe)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            accepted_again = self.run_cli(root, "export-context", "--output", safe)
            self.assertEqual(accepted_again.returncode, 0, accepted_again.stderr)

    def test_export_denylist_covers_common_secret_names_and_env_suffix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            self.ingest(root, self.make_zip(temp))
            fixture_dir = root / "experiments" / "secret-fixtures"
            fixture_dir.mkdir(parents=True)
            for name in ("token.txt", "secrets.env", "id_rsa", ".npmrc", "settings.env"):
                (fixture_dir / name).write_text("secret\n", encoding="utf-8")
            output = Path(temp) / "context.zip"
            completed = self.run_cli(root, "export-context", "--output", output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                for name in ("token.txt", "secrets.env", "id_rsa", ".npmrc", "settings.env"):
                    self.assertNotIn(f"experiments/secret-fixtures/{name}", names)

    def test_supersedes_requires_same_artifact_and_immutable_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            first = self.ingest(root, self.make_zip(temp, "first.zip", {"agent.py": b"one"}))["artifact_id"]
            second = self.ingest(root, self.make_zip(temp, "second.zip", {"agent.py": b"two"}))["artifact_id"]
            old_result = Path(temp) / "old.json"
            old_result.write_text('{"public_score":"1"}', encoding="utf-8")
            old = self.run_cli(root, "record", "--artifact", first, "--result", old_result)
            self.assertEqual(old.returncode, 0, old.stderr)
            old_id = json.loads(old.stdout)["evaluation_id"]
            new_result = Path(temp) / "new.json"
            new_result.write_text('{"public_score":"2"}', encoding="utf-8")
            cross = self.run_cli(
                root,
                "record",
                "--artifact",
                second,
                "--result",
                new_result,
                "--supersedes",
                old_id,
            )
            self.assertNotEqual(cross.returncode, 0)
            old_record_path = root / "evaluations" / old_id / "record.json"
            old_record = json.loads(old_record_path.read_text(encoding="utf-8"))
            old_record["evaluation_id"] = "evaluation-" + ("0" * 64)
            old_record_path.write_text(json.dumps(old_record), encoding="utf-8")
            immutable_target = self.run_cli(
                root,
                "record",
                "--artifact",
                first,
                "--result",
                new_result,
                "--supersedes",
                old_id,
            )
            self.assertNotEqual(immutable_target.returncode, 0)

    def test_validate_detects_supersession_cycles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            first_result = Path(temp) / "first.json"; first_result.write_text('{"public_score":"1"}', encoding="utf-8")
            first = self.run_cli(root, "record", "--artifact", artifact, "--result", first_result)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_id = json.loads(first.stdout)["evaluation_id"]
            second_result = Path(temp) / "second.json"; second_result.write_text('{"public_score":"2"}', encoding="utf-8")
            second = self.run_cli(root, "record", "--artifact", artifact, "--result", second_result, "--supersedes", first_id)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_id = json.loads(second.stdout)["evaluation_id"]
            first_path = root / "evaluations" / first_id / "record.json"
            first_record = json.loads(first_path.read_text(encoding="utf-8"))
            first_record["supersedes_evaluation_id"] = second_id
            first_path.write_text(json.dumps(first_record), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("cycle", invalid.stdout)

    def test_unsafe_archive_members_are_rejected_before_artifact_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            traversal = self.make_zip(temp, "traversal.zip", {"../escape.py": b"x"})
            result = self.run_cli(root, "ingest", "--zip", traversal, "--name", "Bad")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(temp) / "escape.py").exists())
            self.assertFalse((root / "artifacts").exists())

            duplicate = Path(temp) / "duplicate.zip"
            with zipfile.ZipFile(duplicate, "w") as archive:
                archive.writestr("a/../agent.py", b"x")
            result = self.run_cli(root, "ingest", "--zip", duplicate, "--name", "Bad")
            self.assertNotEqual(result.returncode, 0)

            symlink = Path(temp) / "symlink.zip"
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(symlink, "w") as archive:
                archive.writestr(info, b"agent.py")
            result = self.run_cli(root, "ingest", "--zip", symlink, "--name", "Bad")
            self.assertNotEqual(result.returncode, 0)

            case_collision = Path(temp) / "case-collision.zip"
            with zipfile.ZipFile(case_collision, "w") as archive:
                archive.writestr("Agent.py", b"a")
                archive.writestr("agent.py", b"b")
            result = self.run_cli(root, "ingest", "--zip", case_collision, "--name", "Bad")
            self.assertNotEqual(result.returncode, 0)

    def test_corrupt_archive_is_rejected_without_partial_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            valid = self.make_zip(temp, "valid.zip", {"agent.py": b"payload"})
            corrupt = Path(temp) / "corrupt.zip"
            corrupt.write_bytes(valid.read_bytes()[:-7])
            completed = self.run_cli(root, "ingest", "--zip", corrupt, "--name", "Bad")
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((root / "artifacts").exists())

    def test_duplicate_json_keys_are_not_silently_inferred(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "duplicate.json"
            result.write_text('{"public_score":"1","public_score":"2"}', encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertNotEqual(completed.returncode, 0)

    def test_json_null_is_not_treated_as_an_unknown_plain_note(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "null.json"; result.write_text("null", encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertNotEqual(completed.returncode, 0)

    def test_render_validate_and_stale_view_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            root.mkdir(parents=True)
            (root / "progress.md").write_text("historical progress\n", encoding="utf-8")
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"status":"completed","public_score":"1.00"}', encoding="utf-8")
            self.assertEqual(self.run_cli(root, "record", "--artifact", artifact, "--result", result).returncode, 0)
            rendered = self.run_cli(root, "render")
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertTrue((root / "knowledge" / "history" / "progress-original.md").is_file())
            self.assertEqual(self.run_cli(root, "validate").returncode, 0)
            (root / "progress.md").write_text("stale\n", encoding="utf-8")
            stale = self.run_cli(root, "validate")
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("stale", stale.stdout)

    def test_validate_catches_tampered_view_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            metadata_path = root / ".lab" / "views.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["registry_revision"] = "0" * 64
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("view metadata", invalid.stdout)

    def test_validate_succeeds_without_ignored_local_cache_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"1"}', encoding="utf-8")
            self.assertEqual(self.run_cli(root, "record", "--artifact", artifact, "--result", result).returncode, 0)
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            (root / ".lab" / "views.json").unlink()
            for cached in (root / ".lab" / "assets").glob("*"):
                cached.unlink()
            valid = self.run_cli(root, "validate")
            self.assertEqual(valid.returncode, 0, valid.stdout)

    def test_validate_catches_source_and_raw_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"1"}', encoding="utf-8")
            evaluation = json.loads(self.run_cli(root, "record", "--artifact", artifact, "--result", result).stdout)["evaluation_id"]
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            source = next((root / "artifacts" / artifact / "source").rglob("*")); source.write_bytes(b"tampered")
            raw = root / "evaluations" / evaluation / "raw" / "result.json"; raw.write_bytes(b"tampered")
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("mismatch", invalid.stdout)

    def test_validate_catches_raw_hash_metadata_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"1"}', encoding="utf-8")
            evaluation = json.loads(self.run_cli(root, "record", "--artifact", artifact, "--result", result).stdout)["evaluation_id"]
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            record_path = root / "evaluations" / evaluation / "record.json"
            record = json.loads(record_path.read_text())
            record["raw_result_sha256"] = "0" * 64
            record_path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("raw", invalid.stdout)

    def test_context_export_is_deterministic_and_excludes_credentials_and_caches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            (root / "knowledge").mkdir(exist_ok=True)
            (root / "knowledge" / "CURRENT.md").write_text("guidance\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "knowledge" / "__pycache__").mkdir()
            (root / "knowledge" / "__pycache__" / "junk.pyc").write_bytes(b"cache")
            first = Path(temp) / "context-one.zip"
            second = Path(temp) / "context-two.zip"
            one = self.run_cli(root, "export-context", "--output", first)
            two = self.run_cli(root, "export-context", "--output", second)
            self.assertEqual(one.returncode, 0, one.stderr)
            self.assertEqual(two.returncode, 0, two.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                self.assertIn("START_HERE.md", names)
                self.assertIn("FILE_HASHES.json", names)
                self.assertNotIn(".env", names)
                self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))
                hashes = json.loads(archive.read("FILE_HASHES.json"))
                self.assertIn("REGISTRY.json", hashes["files"])

    def test_context_export_includes_required_guidance_and_experiments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            self.ingest(root, self.make_zip(temp))
            required = [
                "README.md",
                "docs/evaluation-contract.md",
                "docs/registry-operations.md",
                "docs/README.md",
                "docs/2026-09-08-instruction-audit.md",
            ]
            for relative in required:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative, encoding="utf-8")
            evidence = root / "experiments" / "public" / "evidence.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("measured evidence\n", encoding="utf-8")
            output = Path(temp) / "context.zip"
            completed = self.run_cli(root, "export-context", "--output", output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("START_HERE.md", names)
                for relative in required:
                    self.assertIn(relative, names)
                self.assertIn("experiments/public/evidence.md", names)

    def test_context_export_does_not_follow_symlinked_experiment_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            self.ingest(root, self.make_zip(temp))
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("must stay out", encoding="utf-8")
            experiments = root / "experiments"
            experiments.mkdir()
            link = experiments / "external"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            output = Path(temp) / "context.zip"
            completed = self.run_cli(root, "export-context", "--output", output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with zipfile.ZipFile(output) as archive:
                self.assertNotIn("experiments/external/secret.txt", archive.namelist())

    def test_invalid_score_fails_before_creating_evaluation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "bad.json"; result.write_text('{"status":"completed"}', encoding="utf-8")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result, "--public-score", "101")
            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse((root / "evaluations").exists() and any((root / "evaluations").iterdir()))

    def test_incomplete_artifact_directory_is_not_overwritten_on_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            archive = self.make_zip(temp)
            payload = archive.read_bytes()
            artifact_id = "artifact-" + hashlib.sha256(payload).hexdigest()
            incomplete = root / "artifacts" / artifact_id
            incomplete.mkdir(parents=True)
            (incomplete / "partial.marker").write_text("do not replace", encoding="utf-8")
            completed = self.run_cli(root, "ingest", "--zip", archive, "--name", "Candidate")
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual((incomplete / "partial.marker").read_text(encoding="utf-8"), "do not replace")

    def test_json_extension_with_corrupt_payload_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "corrupt.json"
            result.write_bytes(b"{not-json}")
            completed = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("JSON", completed.stdout)
            self.assertFalse((root / "evaluations").exists() and any((root / "evaluations").iterdir()))

    def test_validate_reports_missing_required_manifest_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            manifest_path = root / "artifacts" / artifact / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            del manifest["release_asset"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("required", invalid.stdout)

    def test_validate_checks_source_manifest_identity_and_parent_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            manifest_path = root / "artifacts" / artifact / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["source_manifest_sha256"] = "0" * 64
            manifest["parent_artifact_ids"] = ["artifact-missing"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("identity", invalid.stdout)
            self.assertIn("parent", invalid.stdout)

    def test_validate_rejects_unapproved_size_based_zip_manifest_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            manifest_path = root / "artifacts" / artifact / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_dir = root / "artifacts" / artifact / "source"
            digest = hashlib.sha256()
            for relative, file_digest in sorted(manifest["source_file_hashes"].items()):
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                digest.update(str((source_dir / Path(*relative.split("/"))).stat().st_size).encode("ascii"))
                digest.update(b"\0")
                digest.update(file_digest.encode("ascii"))
                digest.update(b"\0")
            manifest["source_manifest_sha256"] = digest.hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("identity", invalid.stdout)

    def test_validate_rejects_source_id_with_arbitrary_manifest_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            source = Path(temp) / "source"
            source.mkdir()
            (source / "agent.py").write_bytes(b"source\n")
            imported = self.run_cli(root, "import-source", "--source", source, "--name", "Source")
            self.assertEqual(imported.returncode, 0, imported.stderr)
            original_id = json.loads(imported.stdout)["artifact_id"]
            arbitrary_id = "source-" + ("0" * 64)
            original = root / "artifacts" / original_id
            forged = root / "artifacts" / arbitrary_id
            import shutil

            shutil.copytree(original, forged)
            manifest_path = forged / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifact_id"] = arbitrary_id
            manifest["source_manifest_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("identity", invalid.stdout)

    def test_staging_directory_uses_normal_mkdir_instead_of_private_tempfile(self):
        from tools.lab.registry import Registry

        with tempfile.TemporaryDirectory() as temp:
            registry = Registry(Path(temp) / "registry")
            registry._prepare()
            with mock.patch("tools.lab.registry.tempfile.mkdtemp", side_effect=AssertionError("private temp ACL")):
                stage = registry._stage_dir()
            self.assertTrue(stage.is_dir())
            self.assertEqual(stage.parent, registry.lab_dir / "staging")
            self.assertRegex(stage.name, r"^op-[0-9a-f]{32}$")
            import shutil

            shutil.rmtree(stage)

    def test_validate_reports_missing_required_record_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
            result = Path(temp) / "result.json"; result.write_text('{"public_score":"1"}', encoding="utf-8")
            evaluation = json.loads(self.run_cli(root, "record", "--artifact", artifact, "--result", result).stdout)["evaluation_id"]
            record_path = root / "evaluations" / evaluation / "record.json"
            record = json.loads(record_path.read_text())
            del record["association_basis"]
            record_path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(self.run_cli(root, "render").returncode, 0)
            invalid = self.run_cli(root, "validate")
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("required", invalid.stdout)

    def test_validate_rejects_tampered_record_schema_fields_and_types(self):
        mutations = {
            "schema_version": "one",
            "rounded_public": 11,
            "raw_result_sha256": "not-a-sha256",
            "supersedes_evaluation_id": 7,
            "raw_feedback": None,
            "status_normalized": [],
            "evaluation_kind": {"kind": "public"},
        }
        for field, value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "registry"
                artifact = self.ingest(root, self.make_zip(temp))["artifact_id"]
                result = Path(temp) / "result.json"; result.write_text('{"public_score":"1"}', encoding="utf-8")
                recorded = self.run_cli(root, "record", "--artifact", artifact, "--result", result)
                self.assertEqual(recorded.returncode, 0, recorded.stderr)
                evaluation_id = json.loads(recorded.stdout)["evaluation_id"]
                record_path = root / "evaluations" / evaluation_id / "record.json"
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record[field] = value
                record_path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(self.run_cli(root, "render").returncode, 0)
                invalid = self.run_cli(root, "validate")
                self.assertNotEqual(invalid.returncode, 0)


if __name__ == "__main__":
    unittest.main()
