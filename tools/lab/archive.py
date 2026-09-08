"""Safe archive and source-tree handling for the local registry.

The registry never imports or executes candidate source.  This module only
validates names, reads bytes, and writes a staged copy of those bytes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Iterable


class ArchiveError(ValueError):
    """Raised when an archive or source tree cannot be safely imported."""


MAX_MEMBERS = 10_000
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_member_name(name: str) -> tuple[str, bool]:
    if not isinstance(name, str) or not name:
        raise ArchiveError("archive member has an empty or invalid name")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ArchiveError("archive member contains a control character")
    if "\\" in name:
        raise ArchiveError(f"archive member uses an unsafe backslash path: {name!r}")
    if name.startswith("/") or name.startswith("//") or _DRIVE_RE.match(name):
        raise ArchiveError(f"archive member is absolute or drive-qualified: {name!r}")
    is_dir = name.endswith("/")
    body = name[:-1] if is_dir else name
    parts = body.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ArchiveError(f"archive member has traversal or empty components: {name!r}")
    normalised = "/".join(parts)
    if not normalised:
        raise ArchiveError("archive member resolves to the archive root")
    return normalised, is_dir


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def inspect_zip(path: Path) -> list[tuple[zipfile.ZipInfo, str, bool]]:
    """Validate a ZIP before any extraction and return safe members.

    The returned paths use POSIX separators and are unique.  Directory
    entries are retained so a caller can recreate the safe member layout.
    """

    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"cannot read ZIP archive {path}: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ArchiveError(f"archive has too many members ({len(infos)})")
        seen: set[str] = set()
        seen_casefolded: set[str] = set()
        file_total = 0
        result: list[tuple[zipfile.ZipInfo, str, bool]] = []
        file_paths: set[str] = set()
        dir_paths: set[str] = set()
        for info in infos:
            normalised, is_dir = _normalise_member_name(info.filename)
            if normalised in seen:
                raise ArchiveError(f"archive has duplicate normalized member: {normalised!r}")
            if normalised.casefold() in seen_casefolded:
                raise ArchiveError(f"archive has a case-insensitive path collision: {normalised!r}")
            seen.add(normalised)
            seen_casefolded.add(normalised.casefold())
            if _is_symlink(info):
                raise ArchiveError(f"archive member is a symlink: {info.filename!r}")
            if not is_dir:
                if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
                    raise ArchiveError(
                        f"archive member is too large ({normalised}: {info.file_size} bytes)"
                    )
                file_total += info.file_size
                if file_total > MAX_TOTAL_BYTES:
                    raise ArchiveError("archive expands beyond the configured size limit")
                file_paths.add(normalised)
            else:
                dir_paths.add(normalised)
            result.append((info, normalised, is_dir))
        for file_path in file_paths:
            components = file_path.split("/")
            ancestors = ["/".join(components[:index]) for index in range(1, len(components))]
            if any(ancestor in file_paths for ancestor in ancestors):
                raise ArchiveError(f"archive member has a file ancestor: {file_path!r}")
        for directory in dir_paths:
            if directory in file_paths:
                raise ArchiveError(f"archive member is both file and directory: {directory!r}")
        return sorted(result, key=lambda item: (item[1], item[2]))


def _write_bytes_atomic(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".part-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def cache_archive(archive_path: Path, cache_dir: Path, digest: str) -> Path:
    """Copy exact archive bytes to the verified local cache."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"{digest}.zip"
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or sha256_file(destination) != digest:
            raise ArchiveError(f"cached archive conflicts with digest {digest}")
        return destination
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ArchiveError("archive file is too large")
    payload = archive_path.read_bytes()
    if sha256_bytes(payload) != digest:
        raise ArchiveError("archive changed while it was being read")
    _write_bytes_atomic(destination, payload)
    return destination


def extract_archive(archive_path: Path, destination: Path) -> dict[str, str]:
    """Extract validated regular files and return relative path hashes."""

    members = inspect_zip(archive_path)
    destination.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info, relative, is_dir in members:
                output = destination.joinpath(*relative.split("/"))
                if is_dir:
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix=".part-", dir=str(output.parent))
                digest = hashlib.sha256()
                actual_size = 0
                try:
                    with archive.open(info, "r") as source, os.fdopen(fd, "wb") as target:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            actual_size += len(chunk)
                            if actual_size > MAX_MEMBER_BYTES:
                                raise ArchiveError(f"archive member expands beyond the size limit: {relative}")
                            digest.update(chunk)
                            target.write(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    if actual_size != info.file_size:
                        raise ArchiveError(f"archive member size changed while reading: {relative}")
                    os.replace(temporary, output)
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                    raise
                hashes[relative] = digest.hexdigest()
    except ArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, EOFError, KeyError, zlib.error) as exc:
        raise ArchiveError(f"cannot safely extract ZIP archive {archive_path}: {exc}") from exc
    return dict(sorted(hashes.items()))


def _iter_source_files(source: Path) -> Iterable[tuple[Path, str]]:
    if source.is_symlink():
        raise ArchiveError("source root may not be a symlink")
    if source.is_file():
        yield source, source.name
        return
    if not source.is_dir():
        raise ArchiveError(f"source path is not a file or directory: {source}")
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for directory in sorted(directories):
            candidate = current_path / directory
            if candidate.is_symlink():
                raise ArchiveError(f"source tree contains a symlink: {candidate}")
            if directory == "__pycache__":
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories
        for filename in sorted(files):
            candidate = current_path / filename
            if candidate.is_symlink():
                raise ArchiveError(f"source tree contains a symlink: {candidate}")
            if filename.endswith(".pyc"):
                continue
            relative = candidate.relative_to(source).as_posix()
            # The walk gives us relative filesystem names, but retain a strict
            # check so platform-specific path behavior cannot bypass it.
            normalised, is_dir = _normalise_member_name(relative)
            if is_dir:
                raise ArchiveError(f"source file has an invalid path: {relative!r}")
            yield candidate, normalised


def source_file_hashes(source: Path) -> tuple[dict[str, str], str, int]:
    """Return hashes, a path/hash identity, and the total source bytes.

    Sizes enforce extraction limits but are deliberately not part of the
    identity: SHA-256 already identifies each file's exact bytes, and the
    original source-only registry recipe hashes sorted ``path + NUL + digest``
    entries without a trailing separator.
    """

    entries: list[tuple[str, bytes, bytes]] = []
    total = 0
    for file_path, relative in _iter_source_files(source):
        size = file_path.stat().st_size
        if size > MAX_MEMBER_BYTES:
            raise ArchiveError(f"source file is too large ({relative}: {size} bytes)")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ArchiveError("source tree exceeds the configured size limit")
        digest = sha256_file(file_path)
        entries.append((relative, digest.encode("ascii"), str(size).encode("ascii")))
    entries.sort(key=lambda item: item[0])
    manifest_digest = hashlib.sha256()
    hashes: dict[str, str] = {}
    for relative, digest_bytes, size_bytes in entries:
        manifest_digest.update(relative.encode("utf-8"))
        manifest_digest.update(b"\0")
        manifest_digest.update(digest_bytes)
        hashes[relative] = digest_bytes.decode("ascii")
    return dict(sorted(hashes.items())), manifest_digest.hexdigest(), total


def copy_source_tree(source: Path, destination: Path) -> dict[str, str]:
    """Copy source files byte-for-byte while omitting cache bytecode."""

    hashes, _identity, _total = source_file_hashes(source)
    destination.mkdir(parents=True, exist_ok=True)
    for file_path, relative in _iter_source_files(source):
        output = destination.joinpath(*relative.split("/"))
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".part-", dir=str(output.parent))
        try:
            with file_path.open("rb") as source_handle, os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(source_handle, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, output)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    return hashes


def validate_relative_path(relative: str) -> str:
    """Validate a stored registry relative path and return its normalized form."""

    normalized, is_dir = _normalise_member_name(relative)
    if is_dir:
        raise ArchiveError(f"stored path must identify a file: {relative!r}")
    return normalized
