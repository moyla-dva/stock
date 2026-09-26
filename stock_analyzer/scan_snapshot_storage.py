"""Discover immutable scan snapshots across active and cold storage tiers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from stock_analyzer.scan_snapshot_archive import (
    DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR,
    SnapshotArchiveError,
    read_archive_manifest,
    read_archived_snapshot_bytes,
)
from stock_analyzer.scan_snapshot_paths import (
    SCAN_SNAPSHOT_FILENAME_RE,
    discover_scan_snapshot_files,
)


STORAGE_TIER_ACTIVE = "active"
STORAGE_TIER_ARCHIVE = "archive"
STORAGE_TIERS = frozenset({STORAGE_TIER_ACTIVE, STORAGE_TIER_ARCHIVE})


@dataclass(frozen=True)
class SnapshotStorageRecord:
    logical_path: Path
    storage_tier: str
    size_bytes: int
    mtime_ns: int
    content_revision: str = ""
    archive_path: Path | None = None
    archive_member: str = ""
    archive_snapshot_revision: str = ""
    archive_revision: str = ""

    def read_bytes(self) -> bytes:
        if self.storage_tier == STORAGE_TIER_ACTIVE:
            return self.logical_path.read_bytes()
        if not self.archive_path:
            raise SnapshotArchiveError(f"archive location is missing: {self.logical_path.name}")
        return read_archived_snapshot_bytes(
            self.logical_path,
            archive_path=self.archive_path,
        )


def active_snapshot_record(path: str | Path) -> SnapshotStorageRecord:
    logical_path = Path(path).expanduser().resolve()
    stat = logical_path.stat()
    return SnapshotStorageRecord(
        logical_path=logical_path,
        storage_tier=STORAGE_TIER_ACTIVE,
        size_bytes=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
    )


def _archive_records(
    source_directory: Path,
    archive_directory: Path,
) -> dict[str, SnapshotStorageRecord]:
    records: dict[str, SnapshotStorageRecord] = {}
    if not archive_directory.is_dir():
        return records
    for archive_path in sorted(archive_directory.glob("scan_snapshots_*.zip")):
        manifest = read_archive_manifest(archive_path)
        manifest_source = str(manifest.get("source_directory") or "")
        if not manifest_source:
            continue
        if Path(manifest_source).expanduser().resolve() != source_directory:
            continue
        archive_stat = archive_path.stat()
        archive_revision = str(manifest.get("archive_revision") or "")
        snapshot_day = str(manifest.get("snapshot_day") or "")
        for entry in manifest.get("entries") or ():
            name = str(entry.get("name") or "")
            member = str(entry.get("member") or "")
            if (
                not SCAN_SNAPSHOT_FILENAME_RE.fullmatch(name)
                or not name.endswith(f"_{snapshot_day}.json")
                or member != f"snapshots/{name}"
            ):
                raise SnapshotArchiveError(
                    f"invalid snapshot archive member: {archive_path.name}:{name}"
                )
            logical_path = (source_directory / name).resolve()
            key = str(logical_path)
            snapshot_revision = f"sha256:{str(entry.get('sha256') or '')}"
            record = SnapshotStorageRecord(
                logical_path=logical_path,
                storage_tier=STORAGE_TIER_ARCHIVE,
                size_bytes=int(entry.get("size_bytes") or 0),
                mtime_ns=int(archive_stat.st_mtime_ns),
                content_revision=snapshot_revision,
                archive_path=archive_path.resolve(),
                archive_member=member,
                archive_snapshot_revision=snapshot_revision,
                archive_revision=archive_revision,
            )
            previous = records.get(key)
            if previous is not None and previous.archive_snapshot_revision != snapshot_revision:
                raise SnapshotArchiveError(f"conflicting archives for snapshot: {name}")
            records[key] = record
    return records


def discover_snapshot_storage(
    source_directory: str | Path,
    archive_directory: str | Path | None = None,
) -> list[SnapshotStorageRecord]:
    """Return one physical location record per logical snapshot path.

    Active files win when both tiers contain the same immutable snapshot. Archive
    metadata remains attached so reconciliation can prove that a later tier move
    will preserve the indexed content revision.
    """

    source_root = Path(source_directory).expanduser().resolve()
    archive_root = Path(
        archive_directory or DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR
    ).expanduser().resolve()
    archived = _archive_records(source_root, archive_root)
    records = dict(archived)
    for path in discover_scan_snapshot_files(source_root):
        active = active_snapshot_record(path)
        archived_copy = archived.get(str(active.logical_path))
        if archived_copy is not None:
            active = replace(
                active,
                archive_path=archived_copy.archive_path,
                archive_member=archived_copy.archive_member,
                archive_snapshot_revision=archived_copy.archive_snapshot_revision,
                archive_revision=archived_copy.archive_revision,
            )
        records[str(active.logical_path)] = active
    return sorted(records.values(), key=lambda item: str(item.logical_path))


def snapshot_storage_revision(records: Iterable[SnapshotStorageRecord]) -> str:
    payload = [
        {
            "logical_path": str(record.logical_path),
            "storage_tier": record.storage_tier,
            "size_bytes": record.size_bytes,
            "content_revision": record.content_revision,
            "archive_path": str(record.archive_path or ""),
            "archive_member": record.archive_member,
            "archive_snapshot_revision": record.archive_snapshot_revision,
            "archive_revision": record.archive_revision,
        }
        for record in sorted(records, key=lambda item: str(item.logical_path))
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
