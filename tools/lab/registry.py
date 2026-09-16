"""The local artifact/evaluation registry.

All mutation methods stage their output and replace complete files or
directories atomically.  Candidate source is treated as opaque bytes: this
module never imports it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from .archive import (
    ArchiveError,
    cache_archive,
    copy_source_tree,
    extract_archive,
    inspect_zip,
    MAX_ARCHIVE_BYTES,
    sha256_bytes,
    sha256_file,
    source_file_hashes,
    validate_relative_path,
)


class LabError(ValueError):
    """An expected, user-actionable registry error."""


SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
_SCORE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_MAX_SCORE_DIGITS = 200
_STATUS_MAP = {
    "complete": "completed",
    "completed": "completed",
    "finished": "completed",
    "finish": "completed",
    "success": "completed",
    "succeeded": "completed",
    "正常終了": "completed",
    "stopped": "stopped",
    "stop": "stopped",
    "途中停止": "stopped",
    "partial": "stopped",
    "incomplete": "stopped",
    "timeout": "stopped",
    "timed_out": "stopped",
    "timed-out": "stopped",
    "stopped in the middle": "stopped",
    "unknown": "unknown",
    "不明": "unknown",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LabError(f"invalid JSON at {path}: {exc}") from exc


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _write_json_atomic(path: Path, value: Any) -> None:
    _write_bytes_atomic(path, _canonical_json(value) + b"\n")


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".part-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise LabError("name must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise LabError("name contains a control character")
    if len(name) > 512:
        raise LabError("name is too long")
    return name


def validate_id(identifier: str, *, prefix: str | None = None) -> str:
    if not isinstance(identifier, str) or not _ID_RE.fullmatch(identifier):
        raise LabError(f"unsafe registry ID: {identifier!r}")
    if prefix and not identifier.startswith(prefix):
        raise LabError(f"registry ID must start with {prefix!r}: {identifier!r}")
    return identifier


def _validate_score(value: Any, *, label: str = "public score") -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise LabError(f"{label} must be a decimal string")
    text = str(value).strip()
    if not _SCORE_RE.fullmatch(text):
        raise LabError(f"{label} is not an exact decimal: {text!r}")
    if len(text.replace(".", "")) > _MAX_SCORE_DIGITS:
        raise LabError(f"{label} has excessive precision")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise LabError(f"{label} is not a decimal: {text!r}") from exc
    if number < 0 or number > 100:
        raise LabError(f"{label} must be in the range 0..100")
    return text


def _normalise_status(value: Any) -> tuple[str | None, str]:
    if value is None:
        return None, "unknown"
    if not isinstance(value, str):
        raise LabError("status must be a string or null")
    raw = value
    key = value.strip().casefold()
    normalized = _STATUS_MAP.get(key)
    if normalized is None and key.startswith("stopped in the middle"):
        normalized = "stopped"
    if normalized is None:
        normalized = "unknown"
    return raw, normalized


def _normalise_numeric_payload(value: Any) -> Any:
    """Retain decimal spellings while making JSON records deterministic."""

    if isinstance(value, dict):
        return {str(key): _normalise_numeric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_numeric_payload(item) for item in value]
    # json.loads(parse_int/parse_float=str) already makes all JSON numerics
    # strings.  This branch supports callers passing regular Python values.
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise LabError("metrics contain a non-finite number")
        return repr(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


def _evaluation_identity_payload(
    *,
    artifact_id: str,
    raw_result_sha256: str,
    public_score_override: str | None,
    rounded_public_override: str | None,
    submission_id: str | None,
    supersedes: str | None,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "raw_result_sha256": raw_result_sha256,
        "public_score_override": public_score_override,
        "rounded_public_override": rounded_public_override,
        "submission_id": submission_id,
        "supersedes": supersedes,
    }


def _evaluation_id_from_identity(identity: dict[str, Any]) -> str:
    return f"evaluation-{sha256_bytes(_canonical_json(identity))}"


def _evaluation_id_candidates(record: dict[str, Any]) -> set[str]:
    """Return IDs produced by the immutable evaluation identity recipe.

    Existing records intentionally do not store whether a rounded value came
    from the command line or the result payload, so both historical inputs
    are considered when rebuilding the legacy identity.  Other fields are
    taken directly from the record and are therefore not silently ignored.
    """

    basis = record.get("association_basis")
    raw_digest = record.get("raw_result_sha256")
    if not isinstance(basis, dict) or not isinstance(raw_digest, str):
        return set()
    score_override = basis.get("score_override")
    if score_override is None:
        public_override = None
    elif isinstance(score_override, dict):
        public_override = score_override.get("public_score")
    else:
        return set()
    rounded_values: list[Any] = [record.get("rounded_public"), None]
    candidates: set[str] = set()
    for rounded_override in rounded_values:
        identity = _evaluation_identity_payload(
            artifact_id=record.get("artifact_id"),
            raw_result_sha256=raw_digest,
            public_score_override=public_override,
            rounded_public_override=rounded_override,
            submission_id=record.get("submission_id"),
            supersedes=record.get("supersedes_evaluation_id"),
        )
        try:
            candidates.add(_evaluation_id_from_identity(identity))
        except (TypeError, ValueError):
            continue
    return candidates


def _matches_legacy_association_metadata(
    existing_record: Any,
    replayed_record: dict[str, Any],
) -> bool:
    """Compare replay evidence while preserving descriptive legacy metadata.

    The added keys refine how already-identical evidence was associated; they
    do not change the legacy evaluation identity.  Missing keys may therefore
    be filled only for this comparison.  The original result filename is also
    descriptive rather than evidence identity, so a byte-identical renamed
    input may replay.  The stored record remains untouched.
    """

    if not isinstance(existing_record, dict):
        return False
    existing_basis = existing_record.get("association_basis")
    replayed_basis = replayed_record.get("association_basis")
    if not isinstance(existing_basis, dict) or not isinstance(replayed_basis, dict):
        return False
    normalized = dict(existing_record)
    normalized_basis = dict(existing_basis)
    for key in (
        "rounded_public_override",
        "submission_id_override",
        "supersedes_override",
    ):
        if key not in normalized_basis and key in replayed_basis:
            normalized_basis[key] = replayed_basis[key]
    if "source_path_name" in normalized_basis and "source_path_name" in replayed_basis:
        normalized_basis["source_path_name"] = replayed_basis["source_path_name"]
    normalized["association_basis"] = normalized_basis
    return normalized == replayed_record


def _raw_result_consistency_errors(
    record: dict[str, Any],
    raw_path: Path,
    raw_bytes: bytes,
) -> list[str]:
    """Reparse preserved result bytes and compare every derived record field."""

    basis = record.get("association_basis")
    if not isinstance(basis, dict):
        return []
    try:
        parsed = _parse_result_bytes(raw_bytes)
    except (LabError, UnicodeDecodeError, ValueError) as exc:
        return [f"preserved raw result cannot be reparsed: {exc}"]

    errors: list[str] = []
    parser_name = basis.get("parser")
    if parser_name != parsed["parser"]:
        errors.append("recorded parser does not match preserved raw result")
    if record.get("raw_feedback") != parsed["payload"]:
        errors.append("recorded raw feedback does not match preserved raw result")

    score_override: str | None = None
    score_override_value = basis.get("score_override")
    if isinstance(score_override_value, dict):
        value = score_override_value.get("public_score")
        if isinstance(value, str):
            score_override = value

    extracted_score = parsed["extracted_score"]
    raw_score_error: str | None = None
    try:
        expected_score = _validate_score(extracted_score)
    except LabError as exc:
        raw_score_error = str(exc)
        if isinstance(extracted_score, str) and re.search(
            r"(?i)(?:about|around|approximately|approx\.?|roughly|~|約)\s*[0-9]",
            extracted_score,
        ):
            expected_score = None
        elif score_override is None:
            errors.append(f"preserved raw result score is invalid: {exc}")
            expected_score = None
        else:
            # An explicit CLI score is allowed to supersede an invalid source
            # score, but the invalid source remains part of the raw evidence.
            expected_score = score_override
    if score_override is not None:
        expected_score = score_override
        try:
            original_score = _validate_score(extracted_score)
        except LabError as exc:
            original_score = None
            raw_score_error = str(exc)
        expected_conflict = extracted_score is not None and original_score != score_override
        if basis.get("score_override_conflicted_with_input") != expected_conflict:
            errors.append("score override conflict marker does not match preserved raw result")
        if basis.get("input_score_error") != raw_score_error:
            errors.append("score override input error does not match preserved raw result")
    if record.get("public_score") != expected_score:
        errors.append("recorded public score does not match preserved raw result")

    expected_rounded = parsed["rounded_from_payload"]
    if expected_rounded is None and isinstance(extracted_score, str) and re.search(
        r"(?i)(?:about|around|approximately|approx\.?|roughly|~|約)\s*[0-9]",
        extracted_score,
    ):
        expected_rounded = extracted_score.strip()
    if "rounded_public_override" in basis:
        rounded_override = basis.get("rounded_public_override")
        if rounded_override is not None:
            expected_rounded = rounded_override
    elif expected_rounded is None and record.get("rounded_public") is not None:
        # Legacy records did not retain whether rounded text came from the
        # CLI.  Their evaluation ID still covers the stored rounded value.
        expected_rounded = record.get("rounded_public")
    elif expected_rounded is not None and record.get("rounded_public") != expected_rounded:
        # A legacy CLI rounded override is likewise distinguishable only by
        # the immutable evaluation ID, so preserve that compatibility path.
        expected_rounded = record.get("rounded_public")
    if record.get("rounded_public") != expected_rounded:
        errors.append("recorded rounded score does not match preserved raw result")

    try:
        expected_status_raw, expected_status_normalized = _normalise_status(parsed["status_value"])
    except LabError as exc:
        errors.append(f"preserved raw result status is invalid: {exc}")
        expected_status_raw, expected_status_normalized = None, "unknown"
    expected_metrics = _normalise_numeric_payload(parsed["metrics"])
    expected_timing = _normalise_numeric_payload(parsed["timing"])
    expected_kind = parsed["evaluation_kind"]
    if expected_kind is None:
        expected_kind = "public" if (expected_score is not None or expected_rounded is not None) else (
            "external_feedback" if expected_metrics is not None else "unknown"
        )
    elif isinstance(expected_kind, str):
        expected_kind = expected_kind.strip()
    else:
        errors.append("preserved raw result evaluation kind is invalid")
        expected_kind = None

    for field, expected in (
        ("evaluation_kind", expected_kind),
        ("competition_id", parsed["competition_id"]),
        ("evaluated_at", parsed["evaluated_at"]),
        ("status_raw", expected_status_raw),
        ("status_normalized", expected_status_normalized),
        ("metrics", expected_metrics),
        ("timing", expected_timing),
    ):
        if record.get(field) != expected:
            errors.append(f"recorded {field} does not match preserved raw result")

    if "submission_id_override" in basis:
        submission_override = basis.get("submission_id_override")
        raw_submission = parsed["input_submission_id"]
        expected_submission = submission_override
        if expected_submission is None and raw_submission is not None:
            expected_submission = str(raw_submission)
        if record.get("submission_id") != expected_submission:
            errors.append("recorded submission ID does not match preserved raw result")
    if "supersedes_override" in basis:
        supersedes_override = basis.get("supersedes_override")
        expected_correction = supersedes_override if supersedes_override is not None else parsed["correction"]
        if record.get("supersedes_evaluation_id") != expected_correction:
            errors.append("recorded supersession does not match preserved raw result")
    return errors


def _single_value(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> Any:
    found: list[Any] = []
    for key in keys:
        if key in payload and payload[key] is not None:
            found.append(payload[key])
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    # Compare normalized scalar values only.  Distinct values are ambiguous;
    # equivalent duplicate fields are harmless and preserve the raw payload.
    first = found[0]
    if all(item == first for item in found[1:]):
        return first
    raise LabError(f"ambiguous {label}: multiple conflicting fields")


def _extract_public_score(payload: dict[str, Any]) -> Any:
    return _single_value(
        payload,
        ("public_score", "publicScore", "public", "Public", "score"),
        "public score",
    )


def _parse_plain_note(text: str) -> tuple[str | None, str | None]:
    """Parse a score note without guessing among unrelated numbers."""

    stripped = text.strip()
    if not stripped:
        return None, None
    labeled = re.findall(
        r"(?i)(?:public(?:\s+score)?|score)\s*(?:is|=|:)\s*([0-9]+(?:\.[0-9]+)?)",
        stripped,
    )
    if len(labeled) > 1 and len(set(labeled)) > 1:
        raise LabError("ambiguous plain score note: multiple conflicting scores")
    if labeled:
        return _validate_score(labeled[0]), None
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", stripped):
        return _validate_score(stripped), None
    approximate = re.search(
        r"(?i)(?:about|around|approximately|approx\.?|roughly|~|約)\s*([0-9]+(?:\.[0-9]+)?)",
        stripped,
    )
    if approximate:
        # Rounded/approximate input is deliberately not promoted to an exact
        # score.  Keep the user's text as the rounded evidence.
        return None, stripped
    if re.search(r"(?i)(?:public(?:\s+score)?|score)\s*[:=]", stripped):
        raise LabError("plain score note has an invalid score")
    return None, None


def _parse_result_bytes(raw_bytes: bytes) -> dict[str, Any]:
    """Parse result bytes into the fields derived by :meth:`Registry.record`.

    Keeping this parser shared by record creation and validation is important:
    validation must not treat the mutable ``raw_feedback`` copy as the source
    of truth.  The original bytes and their parser selection are the evidence.
    """

    parsed: Any = None
    stripped = raw_bytes.lstrip()
    json_syntax_hint = stripped.startswith((b"{", b"[", b'"'))
    valid_json_payload = False
    try:
        parsed = json.loads(
            raw_bytes.decode("utf-8"),
            parse_int=str,
            parse_float=str,
            object_pairs_hook=_pairs_without_duplicates,
        )
        valid_json_payload = True
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Parser selection depends on the immutable bytes, never on mutable
        # source-name metadata.  Malformed JSON syntax still fails unless it
        # also carries an unambiguous plain score note.
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LabError("result is neither valid UTF-8 JSON nor a score note") from exc
        note_score, note_rounded = _parse_plain_note(text)
        if json_syntax_hint and note_score is None and note_rounded is None:
            raise LabError("result looks like JSON but is invalid JSON")
        parsed = None

    if isinstance(parsed, dict):
        payload = _normalise_numeric_payload(parsed)
        extracted_score = _extract_public_score(payload)
        rounded_from_payload = _single_value(
            payload,
            ("rounded_public", "roundedPublic", "public_score_rounded", "rounded_score"),
            "rounded public score",
        )
        status_value = _single_value(payload, ("status_raw", "status"), "status")
        metrics = payload.get("metrics")
        if metrics is None:
            metric_keys = (
                "fill_score",
                "cog_score",
                "stability_score",
                "placement_score",
                "soft_item_score",
                "num_placed_items",
            )
            inferred_metrics = {key: payload[key] for key in metric_keys if key in payload}
            metrics = inferred_metrics or None
        timing = payload.get("timing")
        if timing is None and "time_results" in payload:
            timing = payload["time_results"]
        evaluation_kind = payload.get("evaluation_kind") or payload.get("kind")
        competition_id = payload.get("competition_id")
        input_submission_id = payload.get("submission_id")
        evaluated_at = payload.get("evaluated_at")
        correction = _single_value(
            payload,
            ("supersedes", "supersedes_evaluation_id", "correction_of", "corrects"),
            "superseded evaluation",
        )
    elif parsed is not None:
        # A scalar JSON decimal is a valid score-only result note; other
        # scalar JSON payloads cannot supply the registry's feedback fields.
        scalar_score = parsed.strip() if isinstance(parsed, str) else None
        if scalar_score is None or not _SCORE_RE.fullmatch(scalar_score):
            raise LabError("JSON result must be an object or a decimal score note")
        extracted_score = _validate_score(scalar_score)
        rounded_from_payload = None
        payload = {"text": raw_bytes.decode("utf-8", errors="strict")}
        status_value = None
        metrics = None
        timing = None
        evaluation_kind = None
        competition_id = None
        input_submission_id = None
        evaluated_at = None
        correction = None
    else:
        if valid_json_payload:
            raise LabError("JSON result must be an object or a decimal score note")
        text = raw_bytes.decode("utf-8", errors="strict")
        extracted_score, rounded_from_payload = _parse_plain_note(text)
        payload = {"text": text}
        status_value = None
        metrics = None
        timing = None
        evaluation_kind = None
        competition_id = None
        input_submission_id = None
        evaluated_at = None
        correction = None

    return {
        "parsed": parsed,
        "payload": payload,
        "extracted_score": extracted_score,
        "rounded_from_payload": rounded_from_payload,
        "status_value": status_value,
        "metrics": metrics,
        "timing": timing,
        "evaluation_kind": evaluation_kind,
        "competition_id": competition_id,
        "input_submission_id": input_submission_id,
        "evaluated_at": evaluated_at,
        "correction": correction,
        "parser": "json" if isinstance(parsed, dict) else "plain_score_note",
    }


def _git_commit(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        return None
    return commit.lower()


def _lexical_absolute(path: Path) -> Path:
    """Make an absolute path without resolving symlinks."""

    expanded = path.expanduser()
    if expanded.is_absolute():
        return Path(os.path.abspath(str(expanded)))
    return Path(os.path.abspath(str(Path.cwd() / expanded)))


def _reject_symlinked_ancestors(path: Path, *, label: str) -> None:
    """Reject a path or any lexical ancestor that is a symlink."""

    current = path
    while True:
        if current.is_symlink():
            raise LabError(f"{label} path may not be a symlink: {path}")
        parent = current.parent
        if parent == current:
            break
        current = parent


@contextlib.contextmanager
def _mutation_lock(lab_dir: Path, *, timeout: float = 15.0) -> Iterator[None]:
    lab_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lab_dir / "registry.lock"
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LabError("registry is locked by another mutation")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink()
        except OSError:
            pass


class Registry:
    """Manage a registry rooted at a caller-selected filesystem path."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.artifacts_dir = self.root / "artifacts"
        self.evaluations_dir = self.root / "evaluations"
        self.lab_dir = self.root / ".lab"
        self.assets_dir = self.lab_dir / "assets"

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.evaluations_dir.mkdir(parents=True, exist_ok=True)
        self.lab_dir.mkdir(parents=True, exist_ok=True)

    def _stage_dir(self) -> Path:
        staging = self.lab_dir / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        # tempfile.mkdtemp applies a restrictive private ACL on Windows.  A
        # UUID-named directory created directly below the registry staging
        # parent inherits the normal project ACL while remaining collision
        # resistant.  Retry the (theoretical) UUID collision without ever
        # opening an existing directory.
        for _attempt in range(8):
            candidate = staging / f"op-{uuid.uuid4().hex}"
            try:
                candidate.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            return candidate
        raise LabError("could not allocate a unique registry staging directory")

    @staticmethod
    def _artifact_manifest(
        *,
        artifact_id: str,
        name: str,
        archive_availability: str,
        zip_sha256: str | None,
        source_file_hashes_value: dict[str, str],
        source_manifest_sha256: str,
        source_commit: str | None,
        original_filename: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_id": artifact_id,
            "identity_kind": "zip" if zip_sha256 else "source",
            "algorithm_name": name,
            "zip_sha256": zip_sha256,
            "source_manifest_sha256": source_manifest_sha256,
            "original_filename": original_filename,
            "archive_availability": archive_availability,
            "source_file_hashes": dict(sorted(source_file_hashes_value.items())),
            "parent_artifact_ids": [],
            "created_by": "tools.lab",
            "source_commit": source_commit,
            "release_asset": None,
        }

    def _existing_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        path = self.artifacts_dir / artifact_id / "manifest.json"
        if not path.exists():
            return None
        manifest = _read_json(path)
        if not isinstance(manifest, dict):
            raise LabError(f"existing artifact manifest is not an object: {path}")
        if manifest.get("artifact_id") != artifact_id:
            raise LabError(f"existing artifact manifest ID mismatch: {path}")
        return manifest

    def ingest(self, archive_path: str | os.PathLike[str], name: str) -> dict[str, Any]:
        archive_input = Path(archive_path).expanduser()
        if archive_input.is_symlink():
            raise LabError(f"ZIP path may not be a symlink: {archive_input}")
        archive = archive_input.resolve()
        name = _safe_name(name)
        if not archive.is_file() or archive.is_symlink():
            raise LabError(f"ZIP path is not a regular file: {archive}")
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise LabError("ZIP file is too large")
        try:
            inspect_zip(archive)
        except ArchiveError as exc:
            raise LabError(str(exc)) from exc
        payload = archive.read_bytes()
        zip_digest = sha256_bytes(payload)
        artifact_id = f"artifact-{zip_digest}"
        source_manifest_probe = None
        with tempfile.TemporaryDirectory(prefix="lab-inspect-") as scratch:
            try:
                hashes = extract_archive(archive, Path(scratch) / "source")
            except ArchiveError as exc:
                raise LabError(str(exc)) from exc
            source_manifest_probe = _source_manifest_digest(
                hashes,
                trailing_separator=True,
            )
        manifest = self._artifact_manifest(
            artifact_id=artifact_id,
            name=name,
            archive_availability="available",
            zip_sha256=zip_digest,
            source_file_hashes_value=hashes,
            source_manifest_sha256=source_manifest_probe,
            source_commit=_git_commit(self.root),
            original_filename=archive.name,
        )
        with _mutation_lock(self.lab_dir):
            self._prepare()
            existing = self._existing_artifact(artifact_id)
            if existing is not None:
                self._verify_existing_artifact(artifact_id, existing, archive=archive)
                return {
                    "artifact_id": artifact_id,
                    "path": str(self.artifacts_dir / artifact_id),
                    "deduplicated": True,
                }
            stage = self._stage_dir()
            try:
                cached_archive = cache_archive(archive, self.assets_dir, zip_digest)
                source_destination = stage / "artifact" / "source"
                staged_hashes = extract_archive(cached_archive, source_destination)
                if staged_hashes != hashes:
                    raise ArchiveError("archive changed between inspection and staging")
                _write_json_atomic(stage / "artifact" / "manifest.json", manifest)
                final = self.artifacts_dir / artifact_id
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / "artifact", final)
            except (OSError, ArchiveError) as exc:
                raise LabError(f"artifact ingest failed without completing the record: {exc}") from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return {"artifact_id": artifact_id, "path": str(self.artifacts_dir / artifact_id), "deduplicated": False}

    def import_source(self, source_path: str | os.PathLike[str], name: str) -> dict[str, Any]:
        source_input = Path(source_path).expanduser()
        if source_input.is_symlink():
            raise LabError(f"source path may not be a symlink: {source_input}")
        source = source_input.resolve()
        name = _safe_name(name)
        if not source.exists() or source.is_symlink():
            raise LabError(f"source path is not a regular file or directory: {source}")
        if source == self.root:
            raise LabError("source path may not be the registry root")
        if source.is_dir():
            try:
                self.root.relative_to(source)
            except ValueError:
                pass
            else:
                raise LabError("source directory may not contain the registry root")
        try:
            hashes, source_identity, _total = source_file_hashes(source)
        except (OSError, ArchiveError) as exc:
            raise LabError(str(exc)) from exc
        artifact_id = f"source-{source_identity}"
        manifest = self._artifact_manifest(
            artifact_id=artifact_id,
            name=name,
            archive_availability="missing",
            zip_sha256=None,
            source_file_hashes_value=hashes,
            source_manifest_sha256=source_identity,
            source_commit=_git_commit(self.root),
            original_filename=None,
        )
        with _mutation_lock(self.lab_dir):
            self._prepare()
            existing = self._existing_artifact(artifact_id)
            if existing is not None:
                self._verify_existing_artifact(artifact_id, existing)
                return {
                    "artifact_id": artifact_id,
                    "path": str(self.artifacts_dir / artifact_id),
                    "deduplicated": True,
                }
            stage = self._stage_dir()
            try:
                staged_hashes = copy_source_tree(source, stage / "artifact" / "source")
                if staged_hashes != hashes:
                    raise ArchiveError("source changed between inspection and staging")
                _write_json_atomic(stage / "artifact" / "manifest.json", manifest)
                final = self.artifacts_dir / artifact_id
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / "artifact", final)
            except (OSError, ArchiveError) as exc:
                raise LabError(f"source import failed without completing the record: {exc}") from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return {"artifact_id": artifact_id, "path": str(self.artifacts_dir / artifact_id), "deduplicated": False}

    def _verify_existing_artifact(
        self,
        artifact_id: str,
        manifest: dict[str, Any],
        *,
        archive: Path | None = None,
    ) -> None:
        expected = self.artifacts_dir / artifact_id / "source"
        if not expected.is_dir():
            raise LabError(f"existing artifact is incomplete: {artifact_id}")
        hashes = manifest.get("source_file_hashes")
        if not isinstance(hashes, dict):
            raise LabError(f"existing artifact has invalid source hash manifest: {artifact_id}")
        actual: dict[str, str] = {}
        for path in sorted(expected.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(expected).as_posix()
            try:
                validate_relative_path(relative)
            except ArchiveError as exc:
                raise LabError(str(exc)) from exc
            actual[relative] = sha256_file(path)
        if actual != {str(key): str(value) for key, value in hashes.items()}:
            raise LabError(f"existing artifact source conflicts with its immutable manifest: {artifact_id}")
        if manifest.get("zip_sha256"):
            if artifact_id != f"artifact-{manifest['zip_sha256']}":
                raise LabError(f"existing artifact ZIP identity conflicts with its ID: {artifact_id}")
            cache = self.assets_dir / f"{manifest['zip_sha256']}.zip"
            if cache.is_symlink() or (cache.exists() and (not cache.is_file() or sha256_file(cache) != manifest["zip_sha256"])):
                raise LabError(f"existing artifact archive cache is missing or corrupt: {artifact_id}")
            if not cache.exists():
                if archive is None:
                    raise LabError(f"existing artifact archive cache is missing: {artifact_id}")
                cache_archive(archive, self.assets_dir, manifest["zip_sha256"])

    def _artifact(self, artifact_id: str) -> tuple[Path, dict[str, Any]]:
        if artifact_id.startswith("artifact-"):
            validate_id(artifact_id, prefix="artifact-")
        elif artifact_id.startswith("source-"):
            validate_id(artifact_id, prefix="source-")
        else:
            raise LabError(f"unsafe registry ID: {artifact_id!r}")
        artifact_dir = self.artifacts_dir / artifact_id
        manifest_path = artifact_dir / "manifest.json"
        if not manifest_path.is_file():
            raise LabError(f"unknown artifact ID: {artifact_id}")
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("artifact_id") != artifact_id:
            raise LabError(f"artifact manifest is invalid: {artifact_id}")
        return artifact_dir, manifest

    def _immutable_evaluation_record(self, evaluation_id: str) -> dict[str, Any]:
        """Read a correction target and verify its directory identity."""

        validate_id(evaluation_id, prefix="evaluation-")
        record_path = self.evaluations_dir / evaluation_id / "record.json"
        if not record_path.is_file() or record_path.is_symlink():
            raise LabError(f"superseded evaluation does not exist: {evaluation_id}")
        record = _read_json(record_path)
        if not isinstance(record, dict) or record.get("evaluation_id") != evaluation_id:
            raise LabError(f"superseded evaluation record is not immutable: {evaluation_id}")
        return record

    def _validate_supersedes_target(self, evaluation_id: str, artifact_id: str) -> None:
        """Require an existing same-artifact target and an acyclic chain."""

        seen: set[str] = set()
        current = evaluation_id
        while current is not None:
            if current in seen:
                raise LabError(f"superseded evaluation chain contains a cycle: {evaluation_id}")
            seen.add(current)
            target = self._immutable_evaluation_record(current)
            if target.get("artifact_id") != artifact_id:
                raise LabError("superseded evaluation belongs to a different artifact")
            next_id = target.get("supersedes_evaluation_id")
            if next_id is None:
                break
            if not isinstance(next_id, str):
                raise LabError(f"superseded evaluation link is invalid: {current}")
            validate_id(next_id, prefix="evaluation-")
            current = next_id

    def record(
        self,
        artifact_id: str,
        result_path: str | os.PathLike[str],
        *,
        public_score: str | None = None,
        rounded_public: str | None = None,
        submission_id: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        _artifact_dir, artifact_manifest = self._artifact(artifact_id)
        result_input = _lexical_absolute(Path(result_path))
        _reject_symlinked_ancestors(result_input, label="result")
        result = result_input.resolve()
        if not result.is_file() or result.is_symlink():
            raise LabError(f"result path is not a regular file: {result}")
        raw_bytes = result.read_bytes()
        raw_digest = sha256_bytes(raw_bytes)
        parsed_fields = _parse_result_bytes(raw_bytes)
        parsed = parsed_fields["parsed"]
        payload = parsed_fields["payload"]
        extracted_score = parsed_fields["extracted_score"]
        rounded_from_payload = parsed_fields["rounded_from_payload"]
        status_value = parsed_fields["status_value"]
        metrics = parsed_fields["metrics"]
        timing = parsed_fields["timing"]
        evaluation_kind = parsed_fields["evaluation_kind"]
        competition_id = parsed_fields["competition_id"]
        input_submission_id = parsed_fields["input_submission_id"]
        evaluated_at = parsed_fields["evaluated_at"]
        correction = parsed_fields["correction"]
        cli_submission_id = submission_id
        if submission_id is not None and (not isinstance(submission_id, str) or not submission_id.strip()):
            raise LabError("submission ID must be a non-empty string when supplied")
        if input_submission_id is not None and submission_id is None:
            submission_id = str(input_submission_id)
        if submission_id is not None:
            _safe_name(submission_id)
        if supersedes is not None:
            correction = supersedes
        if correction is not None:
            if not isinstance(correction, str):
                raise LabError("superseded evaluation ID must be a string")
            self._validate_supersedes_target(correction, artifact_id)
        rounded_value = rounded_public if rounded_public is not None else rounded_from_payload
        if rounded_value is not None:
            if not isinstance(rounded_value, str) or not rounded_value.strip():
                raise LabError("rounded public score must be non-empty text")
            rounded_value = rounded_value.strip()
        cli_score = _validate_score(public_score, label="--public-score") if public_score is not None else None
        if cli_score is not None:
            exact_score = cli_score
        else:
            try:
                exact_score = _validate_score(extracted_score)
            except LabError:
                if isinstance(extracted_score, str) and re.search(
                    r"(?i)(?:about|around|approximately|approx\.?|roughly|~|約)\s*[0-9]",
                    extracted_score,
                ):
                    exact_score = None
                    if rounded_value is None:
                        rounded_value = extracted_score.strip()
                else:
                    raise
        original_score_error = None
        if cli_score is not None and extracted_score is not None:
            try:
                original_score = _validate_score(extracted_score)
            except LabError as exc:
                original_score = None
                original_score_error = str(exc)
            # The explicit command-line value wins, but evidence of the
            # conflicting original remains in association_basis/raw_feedback.
            score_conflict = original_score != cli_score
        else:
            score_conflict = False
        status_raw, status_normalized = _normalise_status(status_value)
        metrics = _normalise_numeric_payload(metrics)
        timing = _normalise_numeric_payload(timing)
        if evaluation_kind is None:
            evaluation_kind = "public" if (exact_score is not None or rounded_value is not None) else (
                "external_feedback" if metrics is not None else "unknown"
            )
        if not isinstance(evaluation_kind, str) or not evaluation_kind.strip():
            raise LabError("evaluation kind must be non-empty text")
        if competition_id is not None and not isinstance(competition_id, (str, int)):
            raise LabError("competition ID must be text or numeric")
        if evaluated_at is not None and not isinstance(evaluated_at, str):
            raise LabError("evaluated_at must be text or null")
        identity = _evaluation_identity_payload(
            artifact_id=artifact_id,
            raw_result_sha256=raw_digest,
            public_score_override=cli_score,
            rounded_public_override=rounded_public,
            submission_id=submission_id,
            supersedes=correction,
        )
        evaluation_id = _evaluation_id_from_identity(identity)
        suffix = ".json" if isinstance(parsed, dict) else ".txt"
        raw_relative = f"evaluations/{evaluation_id}/raw/result{suffix}"
        evidence = {
            "artifact_identity": {
                "artifact_id": artifact_id,
                "zip_sha256": artifact_manifest.get("zip_sha256"),
                "source_manifest_sha256": artifact_manifest.get("source_manifest_sha256"),
            },
            "raw_result_sha256": raw_digest,
            "source_path_name": result.name,
            "score_override": (
                {"public_score": cli_score, "recorded_with_raw_result": True}
                if cli_score is not None
                else None
            ),
            "score_override_conflicted_with_input": score_conflict,
            "input_score_error": original_score_error,
            "rounded_public_override": rounded_public,
            "submission_id_override": cli_submission_id,
            "supersedes_override": supersedes,
            "parser": "json" if isinstance(parsed, dict) else "plain_score_note",
        }
        record = {
            "schema_version": SCHEMA_VERSION,
            "evaluation_id": evaluation_id,
            "artifact_id": artifact_id,
            "evaluation_kind": evaluation_kind.strip(),
            "competition_id": competition_id,
            "submission_id": submission_id,
            "evaluated_at": evaluated_at,
            "public_score": exact_score,
            "rounded_public": rounded_value,
            "raw_result_sha256": raw_digest,
            "status_raw": status_raw,
            "status_normalized": status_normalized,
            "metrics": metrics,
            "timing": timing,
            "evidence_refs": [{"path": raw_relative, "sha256": raw_digest, "kind": "raw_result"}],
            "association_basis": evidence,
            "supersedes_evaluation_id": correction,
            "raw_feedback": payload,
        }
        with _mutation_lock(self.lab_dir):
            self._prepare()
            final = self.evaluations_dir / evaluation_id
            if final.exists():
                existing_record_path = final / "record.json"
                existing_raw = final / "raw" / f"result{suffix}"
                if not existing_record_path.is_file() or not existing_raw.is_file():
                    raise LabError(f"existing evaluation is incomplete: {evaluation_id}")
                existing_record = _read_json(existing_record_path)
                records_match = existing_record == record or _matches_legacy_association_metadata(
                    existing_record,
                    record,
                )
                if not records_match or existing_raw.read_bytes() != raw_bytes:
                    raise LabError(f"immutable evaluation ID conflicts with existing evidence: {evaluation_id}")
                return {
                    "evaluation_id": evaluation_id,
                    "artifact_id": artifact_id,
                    "path": str(final),
                    "deduplicated": True,
                }
            stage = self._stage_dir()
            try:
                (stage / "evaluation" / "raw").mkdir(parents=True, exist_ok=True)
                _write_bytes_atomic(stage / "evaluation" / "raw" / f"result{suffix}", raw_bytes)
                _write_json_atomic(stage / "evaluation" / "record.json", record)
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage / "evaluation", final)
            except OSError as exc:
                raise LabError(f"evaluation record failed without completing the record: {exc}") from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return {"evaluation_id": evaluation_id, "artifact_id": artifact_id, "path": str(final), "deduplicated": False}

    def render(self) -> dict[str, Any]:
        from .views import render_views

        with _mutation_lock(self.lab_dir):
            self._prepare()
            return render_views(self.root, preserve_history=True)

    def validate(self) -> dict[str, Any]:
        from .views import expected_views, registry_revision

        errors: list[str] = []
        if not self.root.exists():
            errors.append("registry root does not exist")
            return {"valid": False, "errors": errors}
        artifacts: dict[str, dict[str, Any]] = {}
        if self.artifacts_dir.exists():
            for child in sorted(self.artifacts_dir.iterdir()):
                if not child.is_dir():
                    errors.append(f"unexpected artifact entry: {child.name}")
                    continue
                try:
                    if child.name.startswith("artifact-"):
                        validate_id(child.name, prefix="artifact-")
                    elif child.name.startswith("source-"):
                        validate_id(child.name, prefix="source-")
                    else:
                        raise LabError(f"unsafe registry ID: {child.name!r}")
                    manifest_path = child / "manifest.json"
                    if not manifest_path.is_file():
                        errors.append(f"artifact missing manifest: {child.name}")
                        continue
                    manifest = _read_json(manifest_path)
                    if not isinstance(manifest, dict):
                        errors.append(f"artifact manifest is not an object: {child.name}")
                        continue
                    required_manifest_fields = {
                        "schema_version",
                        "artifact_id",
                        "identity_kind",
                        "algorithm_name",
                        "zip_sha256",
                        "source_manifest_sha256",
                        "original_filename",
                        "archive_availability",
                        "source_file_hashes",
                        "parent_artifact_ids",
                        "created_by",
                        "source_commit",
                        "release_asset",
                    }
                    missing_manifest_fields = sorted(required_manifest_fields - set(manifest))
                    if missing_manifest_fields:
                        errors.append(
                            f"artifact manifest required fields missing ({child.name}): "
                            + ", ".join(missing_manifest_fields)
                        )
                    if manifest.get("artifact_id") != child.name:
                        errors.append(f"artifact ID mismatch: {child.name}")
                    hashes = manifest.get("source_file_hashes")
                    if not isinstance(hashes, dict):
                        errors.append(f"artifact source hash manifest invalid: {child.name}")
                        continue
                    if manifest.get("schema_version") != SCHEMA_VERSION:
                        errors.append(f"artifact schema version invalid: {child.name}")
                    availability = manifest.get("archive_availability")
                    if availability not in ("available", "missing", "reconstructed"):
                        errors.append(f"artifact archive availability invalid: {child.name}")
                    identity_kind = manifest.get("identity_kind")
                    if identity_kind not in ("zip", "source"):
                        errors.append(f"artifact identity kind invalid: {child.name}")
                    parent_ids = manifest.get("parent_artifact_ids")
                    if not isinstance(parent_ids, list):
                        errors.append(f"artifact parent list invalid: {child.name}")
                        parent_ids = []
                    for parent_id in parent_ids:
                        try:
                            if isinstance(parent_id, str) and parent_id.startswith("artifact-"):
                                validate_id(parent_id, prefix="artifact-")
                            elif isinstance(parent_id, str) and parent_id.startswith("source-"):
                                validate_id(parent_id, prefix="source-")
                            else:
                                raise LabError("unsafe parent ID")
                            if not (self.artifacts_dir / parent_id / "manifest.json").is_file():
                                raise LabError("parent artifact is missing")
                        except LabError as exc:
                            errors.append(f"artifact parent link invalid ({child.name}): {exc}")
                    source_dir = child / "source"
                    actual: dict[str, str] = {}
                    if not source_dir.is_dir():
                        errors.append(f"artifact missing source tree: {child.name}")
                    else:
                        for path in sorted(source_dir.rglob("*")):
                            if path.is_symlink():
                                errors.append(f"artifact source contains symlink: {child.name}/{path.relative_to(source_dir)}")
                            elif path.is_file():
                                relative = path.relative_to(source_dir).as_posix()
                                try:
                                    validate_relative_path(relative)
                                    actual[relative] = sha256_file(path)
                                except (ArchiveError, OSError) as exc:
                                    errors.append(f"artifact source path invalid ({child.name}/{relative}): {exc}")
                    expected_hashes = {str(k): str(v) for k, v in hashes.items()}
                    for relative, digest in expected_hashes.items():
                        try:
                            validate_relative_path(relative)
                        except ArchiveError as exc:
                            errors.append(f"artifact source path metadata invalid ({child.name}): {exc}")
                        if not re.fullmatch(r"[0-9a-f]{64}", digest):
                            errors.append(f"artifact source hash metadata invalid ({child.name}/{relative})")
                    if actual != expected_hashes:
                        errors.append(f"artifact source hash mismatch: {child.name}")
                    source_identity = manifest.get("source_manifest_sha256")
                    if identity_kind == "source":
                        # Source imports use the same path/digest recipe as
                        # archive.source_file_hashes (no trailing separator).
                        # File sizes are used for extraction limits only.
                        accepted_source_identities = {
                            _source_manifest_digest(
                                expected_hashes,
                                trailing_separator=False,
                            ),
                        }
                        expected_source_id = f"source-{source_identity}" if isinstance(source_identity, str) else None
                        if expected_source_id != child.name:
                            errors.append(f"artifact source ID does not match its manifest identity: {child.name}")
                    elif identity_kind == "zip":
                        # ZIP source manifests use the delimited registry
                        # form, distinct from source-only identities.
                        accepted_source_identities = {
                            _source_manifest_digest(
                                expected_hashes,
                                trailing_separator=True,
                            ),
                        }
                    else:
                        accepted_source_identities = set()
                    if not isinstance(source_identity, str) or source_identity not in accepted_source_identities:
                        errors.append(f"artifact source manifest identity mismatch: {child.name}")
                    digest = manifest.get("zip_sha256")
                    if identity_kind == "zip":
                        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                            errors.append(f"artifact ZIP digest invalid: {child.name}")
                        else:
                            if child.name != f"artifact-{digest}":
                                errors.append(f"artifact ZIP identity does not match its ID: {child.name}")
                            cache = self.assets_dir / f"{digest}.zip"
                            if cache.is_symlink() or (cache.exists() and (not cache.is_file() or sha256_file(cache) != digest)):
                                errors.append(f"artifact ZIP cache mismatch: {child.name}")
                    elif identity_kind == "source":
                        if digest is not None:
                            errors.append(f"source-only artifact has a ZIP digest: {child.name}")
                        if manifest.get("archive_availability") not in ("missing", "reconstructed"):
                            errors.append(f"source-only archive availability invalid: {child.name}")
                    if identity_kind == "zip" and manifest.get("archive_availability") not in ("available", "reconstructed"):
                        errors.append(f"archive-bearing artifact availability invalid: {child.name}")
                    artifacts[child.name] = manifest
                except (LabError, OSError) as exc:
                    errors.append(f"artifact validation failed ({child.name}): {exc}")
        elif self.evaluations_dir.exists():
            errors.append("evaluations exist but artifacts directory is missing")

        evaluations: dict[str, dict[str, Any]] = {}
        if self.evaluations_dir.exists():
            for child in sorted(self.evaluations_dir.iterdir()):
                if not child.is_dir():
                    errors.append(f"unexpected evaluation entry: {child.name}")
                    continue
                try:
                    validate_id(child.name, prefix="evaluation-")
                    record_path = child / "record.json"
                    if not record_path.is_file():
                        errors.append(f"evaluation missing record: {child.name}")
                        continue
                    record = _read_json(record_path)
                    if not isinstance(record, dict):
                        errors.append(f"evaluation record is not an object: {child.name}")
                        continue
                    required_record_fields = {
                        "schema_version",
                        "evaluation_id",
                        "artifact_id",
                        "evaluation_kind",
                        "competition_id",
                        "submission_id",
                        "evaluated_at",
                        "public_score",
                        "rounded_public",
                        "raw_result_sha256",
                        "status_raw",
                        "status_normalized",
                        "metrics",
                        "timing",
                        "evidence_refs",
                        "association_basis",
                        "supersedes_evaluation_id",
                        "raw_feedback",
                    }
                    missing_record_fields = sorted(required_record_fields - set(record))
                    if missing_record_fields:
                        errors.append(
                            f"evaluation record required fields missing ({child.name}): "
                            + ", ".join(missing_record_fields)
                        )
                    if record.get("evaluation_id") != child.name:
                        errors.append(f"evaluation ID mismatch: {child.name}")
                    if isinstance(record.get("schema_version"), bool) or record.get("schema_version") != SCHEMA_VERSION:
                        errors.append(f"evaluation schema version invalid: {child.name}")
                    evaluation_kind = record.get("evaluation_kind")
                    if not isinstance(evaluation_kind, str) or not evaluation_kind.strip():
                        errors.append(f"evaluation kind invalid: {child.name}")
                    target = record.get("artifact_id")
                    if not isinstance(target, str):
                        errors.append(f"evaluation artifact ID type invalid: {child.name}")
                    elif target not in artifacts:
                        errors.append(f"evaluation references missing artifact ({child.name}): {target!r}")
                    competition_id = record.get("competition_id")
                    if competition_id is not None and (
                        isinstance(competition_id, bool) or not isinstance(competition_id, (str, int))
                    ):
                        errors.append(f"evaluation competition ID invalid: {child.name}")
                    submission_value = record.get("submission_id")
                    if submission_value is not None and (
                        not isinstance(submission_value, str) or not submission_value.strip()
                    ):
                        errors.append(f"evaluation submission ID invalid: {child.name}")
                    evaluated_at = record.get("evaluated_at")
                    if evaluated_at is not None and not isinstance(evaluated_at, str):
                        errors.append(f"evaluation timestamp invalid: {child.name}")
                    try:
                        _validate_score(record.get("public_score"))
                    except LabError as exc:
                        errors.append(f"evaluation score invalid ({child.name}): {exc}")
                    rounded_value = record.get("rounded_public")
                    if rounded_value is not None and (not isinstance(rounded_value, str) or not rounded_value.strip()):
                        errors.append(f"evaluation rounded score invalid: {child.name}")
                    raw_metadata_digest = record.get("raw_result_sha256")
                    if not isinstance(raw_metadata_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_metadata_digest):
                        errors.append(f"evaluation raw-result hash metadata invalid: {child.name}")
                    status_raw = record.get("status_raw")
                    if status_raw is not None and not isinstance(status_raw, str):
                        errors.append(f"evaluation raw status invalid: {child.name}")
                    status_normalized = record.get("status_normalized")
                    if not isinstance(status_normalized, str) or status_normalized not in {
                        "completed",
                        "stopped",
                        "unknown",
                    }:
                        errors.append(f"evaluation normalized status invalid: {child.name}")
                    else:
                        try:
                            expected_status = _normalise_status(status_raw)[1]
                            if status_normalized != expected_status:
                                errors.append(f"evaluation status normalization mismatch: {child.name}")
                        except LabError as exc:
                            errors.append(f"evaluation raw status invalid ({child.name}): {exc}")
                    if record.get("metrics") is not None and not isinstance(record.get("metrics"), dict):
                        errors.append(f"evaluation metrics type invalid: {child.name}")
                    if record.get("timing") is not None and not isinstance(record.get("timing"), dict):
                        errors.append(f"evaluation timing type invalid: {child.name}")
                    if not isinstance(record.get("raw_feedback"), dict):
                        errors.append(f"evaluation raw feedback type invalid: {child.name}")
                    basis = record.get("association_basis")
                    if not isinstance(basis, dict):
                        errors.append(f"evaluation association basis type invalid: {child.name}")
                    else:
                        basis_raw_digest = basis.get("raw_result_sha256")
                        if basis_raw_digest != raw_metadata_digest:
                            errors.append(f"evaluation association raw hash mismatch: {child.name}")
                        basis_artifact = basis.get("artifact_identity")
                        if not isinstance(basis_artifact, dict) or basis_artifact.get("artifact_id") != target:
                            errors.append(f"evaluation association artifact mismatch: {child.name}")
                        score_override = basis.get("score_override")
                        if score_override is not None:
                            if not isinstance(score_override, dict):
                                errors.append(f"evaluation score override type invalid: {child.name}")
                            else:
                                override_value = score_override.get("public_score")
                                try:
                                    _validate_score(override_value)
                                except LabError as exc:
                                    errors.append(f"evaluation score override invalid ({child.name}): {exc}")
                                if override_value != record.get("public_score"):
                                    errors.append(f"evaluation score override mismatch: {child.name}")
                        parser_name = basis.get("parser")
                        if not isinstance(parser_name, str) or parser_name not in {"json", "plain_score_note"}:
                            errors.append(f"evaluation parser invalid: {child.name}")
                    refs = record.get("evidence_refs")
                    if not isinstance(refs, list) or not refs:
                        errors.append(f"evaluation evidence references missing: {child.name}")
                    else:
                        raw_evidence_paths: list[Path] = []
                        for reference in refs:
                            if not isinstance(reference, dict):
                                errors.append(f"evaluation evidence reference invalid: {child.name}")
                                continue
                            relative = reference.get("path")
                            try:
                                if not isinstance(relative, str) or not relative.startswith(f"evaluations/{child.name}/"):
                                    raise ArchiveError("evidence path is outside its evaluation")
                                safe_relative = validate_relative_path(relative)
                                raw_path = self.root / Path(*safe_relative.split("/"))
                                if not raw_path.is_file() or raw_path.is_symlink():
                                    raise ArchiveError("evidence file is missing")
                                expected_digest = reference.get("sha256")
                                if not isinstance(expected_digest, str) or sha256_file(raw_path) != expected_digest:
                                    raise ArchiveError("evidence hash mismatch")
                                if raw_metadata_digest is not None and raw_metadata_digest != expected_digest:
                                    raise ArchiveError("raw-result hash metadata mismatch")
                                kind = reference.get("kind")
                                if kind != "raw_result":
                                    errors.append(f"evaluation evidence kind is unknown: {child.name}")
                                else:
                                    raw_evidence_paths.append(raw_path)
                            except (ArchiveError, OSError) as exc:
                                errors.append(f"evaluation evidence invalid ({child.name}): {exc}")
                        if len(raw_evidence_paths) != 1:
                            errors.append(f"evaluation must have exactly one raw-result evidence reference: {child.name}")
                        else:
                            raw_evidence_path = raw_evidence_paths[0]
                            try:
                                raw_bytes = raw_evidence_path.read_bytes()
                                if raw_metadata_digest is None or sha256_bytes(raw_bytes) == raw_metadata_digest:
                                    for consistency_error in _raw_result_consistency_errors(
                                        record,
                                        raw_evidence_path,
                                        raw_bytes,
                                    ):
                                        errors.append(
                                            f"evaluation raw-derived field mismatch ({child.name}): "
                                            + consistency_error
                                        )
                            except OSError as exc:
                                errors.append(f"evaluation raw evidence cannot be read ({child.name}): {exc}")
                    correction = record.get("supersedes_evaluation_id")
                    if correction is not None:
                        try:
                            validate_id(correction, prefix="evaluation-")
                            correction_path = self.evaluations_dir / correction / "record.json"
                            if correction not in evaluations and not correction_path.is_file():
                                raise LabError("target does not exist")
                            if correction == child.name:
                                raise LabError("correction target cannot be itself")
                        except LabError as exc:
                            errors.append(f"evaluation correction link invalid ({child.name}): {exc}")
                    if child.name not in _evaluation_id_candidates(record):
                        errors.append(f"evaluation identity does not match immutable record: {child.name}")
                    evaluations[child.name] = record
                except (LabError, OSError) as exc:
                    errors.append(f"evaluation validation failed ({child.name}): {exc}")
        # Validate the full supersession graph after all records are loaded so
        # forward references and cycles are checked consistently.
        for evaluation_id, record in evaluations.items():
            correction = record.get("supersedes_evaluation_id")
            if correction is None or not isinstance(correction, str):
                continue
            target = evaluations.get(correction)
            if target is None:
                continue
            if target.get("artifact_id") != record.get("artifact_id"):
                errors.append(f"evaluation correction crosses artifacts: {evaluation_id}")
            chain_seen: set[str] = set()
            current: str | None = evaluation_id
            while current is not None:
                if current in chain_seen:
                    errors.append(f"evaluation correction cycle detected: {evaluation_id}")
                    break
                chain_seen.add(current)
                current_record = evaluations.get(current)
                if not isinstance(current_record, dict):
                    break
                next_id = current_record.get("supersedes_evaluation_id")
                current = next_id if isinstance(next_id, str) else None
        try:
            expected_progress, expected_current = expected_views(self.root)
            progress_path = self.root / "progress.md"
            current_path = self.root / "knowledge" / "CURRENT.md"
            if not progress_path.is_file() or progress_path.read_bytes() != expected_progress:
                errors.append("progress.md is missing or stale")
            if not current_path.is_file() or current_path.read_bytes() != expected_current:
                errors.append("knowledge/CURRENT.md is missing or stale")
            views_metadata_path = self.lab_dir / "views.json"
            if views_metadata_path.is_file():
                try:
                    views_metadata = _read_json(views_metadata_path)
                    expected_metadata = {
                        "schema_version": SCHEMA_VERSION,
                        "registry_revision": registry_revision(self.root),
                        "progress_sha256": sha256_bytes(expected_progress),
                        "current_sha256": sha256_bytes(expected_current),
                    }
                    if views_metadata != expected_metadata:
                        errors.append("generated view metadata is stale or invalid")
                except LabError as exc:
                    errors.append(f"generated view metadata is invalid: {exc}")
        except (LabError, OSError) as exc:
            errors.append(f"generated views cannot be checked: {exc}")
        revision = registry_revision(self.root)
        return {"valid": not errors, "errors": errors, "registry_revision": revision}

    def export_context(self, output: str | os.PathLike[str]) -> dict[str, Any]:
        from .views import registry_revision

        requested_output = _lexical_absolute(Path(output))
        _reject_symlinked_ancestors(requested_output, label="context output")
        root_path = self.root.resolve(strict=False)
        safe_output_dir = root_path / ".lab" / "exports"
        try:
            requested_output.relative_to(safe_output_dir)
            inside_safe_output_dir = True
        except ValueError:
            inside_safe_output_dir = False
        try:
            requested_output.relative_to(root_path)
            inside_registry = True
        except ValueError:
            inside_registry = False
        if inside_registry and not inside_safe_output_dir:
            raise LabError("context output must be outside the registry or beneath .lab/exports")
        if requested_output.exists() and requested_output.is_dir():
            raise LabError("context output must be a file path")
        if requested_output.exists() and not inside_safe_output_dir:
            raise LabError("refusing to replace an existing context output")
        if inside_safe_output_dir:
            safe_output_dir.mkdir(parents=True, exist_ok=True)
        output_path = requested_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        revision = registry_revision(self.root)
        files: dict[str, bytes] = {}
        explicit = [
            "START_HERE.md",
            "AGENTS.md",
            "README.md",
            "progress.md",
            "docs/evaluation-contract.md",
            "docs/registry-operations.md",
            "docs/README.md",
            "docs/2026-09-08-instruction-audit.md",
            "docs/development.md",
            "docs/2026-09-16-astra-workspace-audit.md",
        ]

        def add_context_file(path: Path) -> None:
            relative = _safe_context_relative(self.root, path)
            if relative is None or path.resolve() == output_path:
                return
            files[relative] = path.read_bytes()

        for relative in explicit:
            add_context_file(self.root / relative)
        if "START_HERE.md" not in files:
            files["START_HERE.md"] = _fallback_start_here(revision).encode("utf-8")
        for base_name in ("knowledge", "artifacts", "evaluations", "contracts", "experiments"):
            base = self.root / base_name
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                add_context_file(path)
        registry_summary = {
            "schema_version": SCHEMA_VERSION,
            "registry_revision": revision,
            "source_commit": _git_commit(self.root),
            "artifact_ids": sorted(
                path.name
                for path in self.artifacts_dir.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
            if self.artifacts_dir.is_dir()
            else [],
            "evaluation_ids": sorted(
                path.name
                for path in self.evaluations_dir.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
            if self.evaluations_dir.is_dir()
            else [],
        }
        files["REGISTRY.json"] = _canonical_json(registry_summary) + b"\n"
        hashes = {relative: sha256_bytes(payload) for relative, payload in sorted(files.items())}
        files["FILE_HASHES.json"] = _canonical_json({"schema_version": SCHEMA_VERSION, "files": hashes}) + b"\n"
        zip_bytes = _deterministic_zip(files)
        _write_bytes_atomic(output_path, zip_bytes)
        return {
            "output": str(output_path),
            "sha256": sha256_bytes(zip_bytes),
            "registry_revision": revision,
            "file_count": len(files),
        }


def _source_manifest_digest(
    hashes: dict[str, str],
    *,
    trailing_separator: bool = False,
) -> str:
    """Hash a sorted source manifest using an explicit registry recipe.

    ``source_file_hashes`` is the current source identity recipe: path, NUL,
    digest, with no separator after the digest.  ZIP manifests use the same
    form with a final separator.  Callers select the exact form rather than
    accepting an arbitrary value.
    """

    digest = hashlib.sha256()
    for relative, file_digest in sorted(hashes.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        if trailing_separator:
            digest.update(b"\0")
    return digest.hexdigest()


def _excluded_context_path(relative: str) -> bool:
    parts = relative.replace("\\", "/").split("/")
    lower = [part.casefold() for part in parts]
    if any(part in (".git", ".lab", "__pycache__") for part in lower):
        return True
    name = lower[-1]
    if (
        name.endswith(".pyc")
        or name.endswith(".pyo")
        or name.startswith(".env")
        or name.endswith(".env")
    ):
        return True
    if name in {
        "credentials",
        "credentials.json",
        "secrets.json",
        "token.json",
        "token.txt",
        "id_rsa",
        ".npmrc",
    }:
        return True
    if name.endswith((".pem", ".key", ".p12", ".pfx")):
        return True
    return False


def _safe_context_relative(root: Path, path: Path) -> str | None:
    """Return a safe in-root context path, refusing symlinked ancestors."""

    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return None
    if _excluded_context_path(relative):
        return None
    current = root
    for component in Path(relative).parts:
        current = current / component
        if current.is_symlink():
            return None
    if not path.is_file() or path.is_symlink():
        return None
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return None
    return relative


def _fallback_start_here(revision: str) -> str:
    return (
        "# Baggage-Loading Lab Context\n\n"
        "This offline bundle contains the current registry guidance, artifact source bytes, "
        "and evaluation evidence. Read `knowledge/CURRENT.md` and `progress.md` first.\n\n"
        f"Registry revision: `{revision}`\n"
    )


def _deterministic_zip(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, payload in sorted(files.items()):
            info = zipfile.ZipInfo(relative)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


__all__ = ["LabError", "Registry", "validate_id"]
