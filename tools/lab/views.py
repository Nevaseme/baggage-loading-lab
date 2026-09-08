"""Deterministic generated views for the local registry."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .archive import sha256_bytes
from .registry import SCHEMA_VERSION, _canonical_json, _read_json, _write_bytes_atomic


def _artifact_records(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    artifacts = root / "artifacts"
    if not artifacts.is_dir():
        return result
    for directory in sorted(artifacts.iterdir(), key=lambda path: path.name):
        if not directory.is_dir() or not (directory / "manifest.json").is_file():
            continue
        try:
            manifest = _read_json(directory / "manifest.json")
        except Exception:
            continue
        if isinstance(manifest, dict):
            result.append(manifest)
    return result


def _evaluation_records(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    evaluations = root / "evaluations"
    if not evaluations.is_dir():
        return result
    for directory in sorted(evaluations.iterdir(), key=lambda path: path.name):
        if not directory.is_dir() or not (directory / "record.json").is_file():
            continue
        try:
            record = _read_json(directory / "record.json")
        except Exception:
            continue
        if isinstance(record, dict):
            result.append(record)
    return result


def registry_revision(root: Path) -> str:
    """Hash only structured registry records, in stable path order."""

    entries: list[tuple[str, bytes]] = []
    for base in (root / "artifacts", root / "evaluations"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.name in {"manifest.json", "record.json"}:
                entries.append((path.relative_to(root).as_posix(), path.read_bytes()))
    digest = hashlib.sha256()
    for relative, payload in entries:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _display(value: Any, fallback: str = "pending") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _progress(root: Path, revision: str) -> bytes:
    artifacts = _artifact_records(root)
    evaluations = _evaluation_records(root)
    lines = [
        "# Baggage-Loading Lab Registry",
        "",
        "This file is generated from `artifacts/` and `evaluations/`; do not edit it by hand.",
        "",
        f"Registry revision: `{revision}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Algorithm | Archive | Source files |",
        "|---|---|---|---:|",
    ]
    if artifacts:
        for manifest in sorted(artifacts, key=lambda item: str(item.get("artifact_id", ""))):
            artifact_id = str(manifest.get("artifact_id", "unknown"))
            algorithm = str(manifest.get("algorithm_name", "unknown")).replace("|", "\\|")
            archive = _display(manifest.get("archive_availability"))
            files = manifest.get("source_file_hashes")
            count = len(files) if isinstance(files, dict) else 0
            lines.append(
                f"| [{artifact_id}](artifacts/{artifact_id}/manifest.json) | {algorithm} | {archive} | {count} |"
            )
    else:
        lines.append("| *(none)* | | | 0 |")
    lines.extend(
        [
            "",
            "## Evaluations",
            "",
            "| Evaluation | Artifact | Kind | Public score | Rounded | Status |",
            "|---|---|---|---:|---|---|",
        ]
    )
    if evaluations:
        for record in sorted(evaluations, key=lambda item: str(item.get("evaluation_id", ""))):
            evaluation_id = str(record.get("evaluation_id", "unknown"))
            artifact_id = str(record.get("artifact_id", "unknown"))
            public = _display(record.get("public_score"))
            rounded = _display(record.get("rounded_public"), "")
            status = _display(record.get("status_normalized"), "unknown")
            kind = _display(record.get("evaluation_kind"), "unknown")
            lines.append(
                f"| [{evaluation_id}](evaluations/{evaluation_id}/record.json) | "
                f"[{artifact_id}](artifacts/{artifact_id}/manifest.json) | {kind} | {public} | {rounded} | {status} |"
            )
    else:
        lines.append("| *(none)* | | | pending | | unknown |")
    lines.extend(
        [
            "",
            "## Evidence notes",
            "",
            "Exact Public scores remain decimal text. Missing and rounded values are not inferred.",
            "Raw result bytes are retained beneath each evaluation's `raw/` directory.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _current(root: Path, revision: str) -> bytes:
    artifacts = _artifact_records(root)
    evaluations = _evaluation_records(root)
    lines = [
        "# Current Registry Context",
        "",
        "This generated index is the compact entry point for the local artifact/evaluation registry.",
        "",
        f"Registry revision: `{revision}`",
        "",
        "## Read next",
        "",
        "1. `progress.md` for the deterministic comparison table.",
        "2. Each linked artifact `manifest.json` and its `source/` bytes.",
        "3. Each linked evaluation `record.json` and its preserved `raw/` evidence.",
        "",
        "## Facts",
        "",
        f"- Registered artifacts: {len(artifacts)}",
        f"- Registered evaluations: {len(evaluations)}",
        "- Candidate source is stored as data and is never executed by registry operations.",
        "- Unknown status, missing scores, and rounded scores remain explicit.",
        "",
    ]
    if artifacts:
        lines.extend(["## Artifacts", ""])
        for manifest in sorted(artifacts, key=lambda item: str(item.get("artifact_id", ""))):
            artifact_id = str(manifest.get("artifact_id", "unknown"))
            lines.append(f"- [{artifact_id}](../artifacts/{artifact_id}/manifest.json)")
        lines.append("")
    if evaluations:
        lines.extend(["## Evaluations", ""])
        for record in sorted(evaluations, key=lambda item: str(item.get("evaluation_id", ""))):
            evaluation_id = str(record.get("evaluation_id", "unknown"))
            lines.append(f"- [{evaluation_id}](../evaluations/{evaluation_id}/record.json)")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def expected_views(root: Path) -> tuple[bytes, bytes]:
    revision = registry_revision(root)
    return _progress(root, revision), _current(root, revision)


def render_views(root: Path, *, preserve_history: bool = True) -> dict[str, Any]:
    progress, current = expected_views(root)
    progress_path = root / "progress.md"
    knowledge_path = root / "knowledge" / "CURRENT.md"
    if preserve_history and progress_path.is_file():
        history_path = root / "knowledge" / "history" / "progress-original.md"
        if not history_path.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(progress_path, history_path)
    _write_bytes_atomic(progress_path, progress)
    _write_bytes_atomic(knowledge_path, current)
    revision = registry_revision(root)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "registry_revision": revision,
        "progress_sha256": sha256_bytes(progress),
        "current_sha256": sha256_bytes(current),
    }
    _write_bytes_atomic(root / ".lab" / "views.json", _canonical_json(metadata) + b"\n")
    return {
        "registry_revision": revision,
        "progress": str(progress_path),
        "current": str(knowledge_path),
    }


__all__ = ["expected_views", "registry_revision", "render_views"]
