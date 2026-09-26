"""Checksum-verified cold storage for immutable scan snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from stock_analyzer.scan_snapshot_paths import SCAN_SNAPSHOT_FILENAME_RE


ARCHIVE_SCHEMA_VERSION = 1
ARCHIVE_MANIFEST_NAME = "_manifest.json"
DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR = Path(os.environ.get(
    "STOCK_ANALYZER_SCAN_SNAPSHOT_ARCHIVE_DIR",
    Path(__file__).resolve().parents[1] / ".cache" / "scan_snapshot_archives",
))


class SnapshotArchiveError(RuntimeError):
    """Raised when a cold archive cannot prove snapshot integrity."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_day_from_filename(path: str | Path) -> str:
    name = Path(path).name
    if not SCAN_SNAPSHOT_FILENAME_RE.fullmatch(name):
        return ""
    return name.rsplit("_", 1)[-1][:-5]


def archive_path_for_day(
    snapshot_day: str,
    archive_dir: str | Path | None = None,
) -> Path:
    day = str(snapshot_day or "").replace("-", "")[:8]
    root = Path(archive_dir or DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR)
    return root / f"scan_snapshots_{day}.zip"


@lru_cache(maxsize=32)
def _cached_manifest(path_text: str, mtime_ns: int, size: int) -> dict[str, Any]:
    del mtime_ns, size
    path = Path(path_text)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            raw = archive.read(ARCHIVE_MANIFEST_NAME)
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise SnapshotArchiveError(f"invalid snapshot archive manifest: {path.name}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
        raise SnapshotArchiveError(f"unsupported snapshot archive schema: {path.name}")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise SnapshotArchiveError(f"snapshot archive entries are missing: {path.name}")
    expected_revision = str(manifest.get("archive_revision") or "")
    actual_revision = "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest()
    if expected_revision != actual_revision:
        raise SnapshotArchiveError(f"snapshot archive manifest revision mismatch: {path.name}")
    if int(manifest.get("file_count") or 0) != len(entries):
        raise SnapshotArchiveError(f"snapshot archive file count mismatch: {path.name}")
    names = [str(item.get("name") or "") for item in entries if isinstance(item, dict)]
    if len(names) != len(entries) or len(set(names)) != len(names):
        raise SnapshotArchiveError(f"snapshot archive contains duplicate entries: {path.name}")
    return manifest


def read_archive_manifest(
    archive_path: str | Path,
) -> dict[str, Any]:
    path = Path(archive_path)
    try:
        stat = path.stat()
    except OSError as exc:
        raise SnapshotArchiveError(f"snapshot archive is missing: {path}") from exc
    return _cached_manifest(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def _entry_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output = {}
    for item in manifest.get("entries") or ():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if SCAN_SNAPSHOT_FILENAME_RE.fullmatch(name):
            output[name] = item
    return output


def archived_snapshot_paths(
    snapshot_dir: str | Path,
    *,
    snapshot_day: str,
    start_key: str | None = None,
    archive_dir: str | Path | None = None,
) -> list[Path]:
    """Return virtual source paths for one archived day without extracting it."""

    day = str(snapshot_day or "").replace("-", "")[:8]
    archive_path = archive_path_for_day(day, archive_dir=archive_dir)
    if not archive_path.is_file():
        return []
    manifest = read_archive_manifest(archive_path)
    if str(manifest.get("snapshot_day") or "") != day:
        raise SnapshotArchiveError(f"snapshot archive day mismatch: {archive_path.name}")
    names = []
    for entry in _entry_map(manifest).values():
        if start_key and str(entry.get("start_key") or "") != str(start_key):
            continue
        names.append(Path(snapshot_dir) / str(entry["name"]))
    return sorted(names, reverse=True)


def read_archived_snapshot_bytes(
    source_path: str | Path,
    *,
    archive_dir: str | Path | None = None,
    archive_path: str | Path | None = None,
) -> bytes:
    """Read one archived snapshot and verify its size and SHA-256 checksum."""

    source_path = Path(source_path)
    day = snapshot_day_from_filename(source_path)
    if not day:
        raise SnapshotArchiveError(f"invalid scan snapshot filename: {source_path.name}")
    archive_path = (
        Path(archive_path)
        if archive_path is not None
        else archive_path_for_day(day, archive_dir=archive_dir)
    )
    manifest = read_archive_manifest(archive_path)
    if str(manifest.get("snapshot_day") or "") != day:
        raise SnapshotArchiveError(f"snapshot archive day mismatch: {archive_path.name}")
    entry = _entry_map(manifest).get(source_path.name)
    if not entry:
        raise SnapshotArchiveError(f"snapshot is absent from archive: {source_path.name}")
    member = str(entry.get("member") or "")
    if member != f"snapshots/{source_path.name}":
        raise SnapshotArchiveError(f"unsafe snapshot archive member: {source_path.name}")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            raw = archive.read(member)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SnapshotArchiveError(f"cannot read archived snapshot: {source_path.name}") from exc
    expected_size = int(entry.get("size_bytes") or 0)
    expected_digest = str(entry.get("sha256") or "")
    actual_digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != expected_size or actual_digest != expected_digest:
        raise SnapshotArchiveError(f"archived snapshot checksum mismatch: {source_path.name}")
    return raw


def read_scan_snapshot_bytes(
    source_path: str | Path,
    *,
    archive_dir: str | Path | None = None,
    archive_path: str | Path | None = None,
) -> bytes:
    """Read an active snapshot first, then fall back to checksum-verified cold storage."""

    path = Path(source_path)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return read_archived_snapshot_bytes(
            path,
            archive_dir=archive_dir,
            archive_path=archive_path,
        )
