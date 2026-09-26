"""Create or verify one checksum-protected scan-snapshot day archive.

The command copies immutable JSON snapshots into an atomic ZIP archive and
verifies every member. It never deletes source snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.scan_snapshot import SNAPSHOT_DIR, normalize_snapshot_day
from stock_analyzer.scan_snapshot_archive import (
    ARCHIVE_MANIFEST_NAME,
    ARCHIVE_SCHEMA_VERSION,
    DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR,
    SnapshotArchiveError,
    archive_path_for_day,
    read_archive_manifest,
)
from stock_analyzer.scan_snapshot_paths import SCAN_SNAPSHOT_FILENAME_RE


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _snapshot_paths(snapshot_dir: Path, snapshot_day: str) -> list[Path]:
    return sorted(
        path
        for path in snapshot_dir.glob(f"*_{snapshot_day}.json")
        if path.is_file() and SCAN_SNAPSHOT_FILENAME_RE.fullmatch(path.name)
    )


def _entry(path: Path, raw: bytes, snapshot_day: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid snapshot JSON: {path.name}") from exc
    payload_day = normalize_snapshot_day(payload.get("snapshot_day"))
    if payload_day != snapshot_day:
        raise ValueError(f"snapshot day mismatch: {path.name}")
    parts = path.stem.split("_")
    return {
        "name": path.name,
        "member": f"snapshots/{path.name}",
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "code": str(payload.get("code") or parts[0]),
        "start_key": parts[1],
        "snapshot_version": int(payload.get("version") or 0),
        "strategy_version": str(payload.get("strategy_version") or "unknown"),
        "data_adjust": str(payload.get("data_adjust") or "unknown"),
        "data_date": str(payload.get("data_date") or ""),
        "computed_scan_types": sorted(str(item) for item in payload.get("computed_scan_types") or ()),
    }


def verify_snapshot_day_archive(archive_path: str | Path) -> dict[str, Any]:
    path = Path(archive_path)
    manifest = read_archive_manifest(path)
    entries = manifest.get("entries") or []
    expected_revision = str(manifest.get("archive_revision") or "")
    actual_revision = "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest()
    if expected_revision != actual_revision:
        raise SnapshotArchiveError(f"snapshot archive manifest revision mismatch: {path.name}")
    names = set()
    total_size = 0
    try:
        with zipfile.ZipFile(path, "r") as archive:
            for entry in entries:
                name = str(entry.get("name") or "")
                if name in names:
                    raise SnapshotArchiveError(f"duplicate snapshot archive entry: {name}")
                names.add(name)
                member = str(entry.get("member") or "")
                if member != f"snapshots/{name}":
                    raise SnapshotArchiveError(f"unsafe snapshot archive member: {name}")
                raw = archive.read(member)
                if len(raw) != int(entry.get("size_bytes") or 0):
                    raise SnapshotArchiveError(f"archived snapshot size mismatch: {name}")
                if hashlib.sha256(raw).hexdigest() != str(entry.get("sha256") or ""):
                    raise SnapshotArchiveError(f"archived snapshot checksum mismatch: {name}")
                total_size += len(raw)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SnapshotArchiveError(f"cannot verify snapshot archive: {path.name}") from exc
    if int(manifest.get("file_count") or 0) != len(entries):
        raise SnapshotArchiveError(f"snapshot archive file count mismatch: {path.name}")
    if int(manifest.get("source_size_bytes") or 0) != total_size:
        raise SnapshotArchiveError(f"snapshot archive source size mismatch: {path.name}")
    with zipfile.ZipFile(path, "r") as archive:
        archived_members = {name for name in archive.namelist() if name.startswith("snapshots/")}
    expected_members = {str(entry.get("member") or "") for entry in entries}
    if archived_members != expected_members:
        raise SnapshotArchiveError(f"snapshot archive membership mismatch: {path.name}")
    return {
        "archive_path": str(path.resolve()),
        "snapshot_day": str(manifest.get("snapshot_day") or ""),
        "file_count": len(entries),
        "source_size_bytes": total_size,
        "archive_size_bytes": path.stat().st_size,
        "archive_revision": actual_revision,
        "verified": True,
        "source_deleted": False,
    }


def build_snapshot_day_archive(
    snapshot_dir: str | Path,
    archive_dir: str | Path,
    snapshot_day: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    snapshot_dir = Path(snapshot_dir).expanduser().resolve()
    archive_dir = Path(archive_dir).expanduser().resolve()
    day = normalize_snapshot_day(snapshot_day)
    if not day:
        raise ValueError("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
    paths = _snapshot_paths(snapshot_dir, day)
    if not paths:
        raise ValueError(f"no source snapshots found for {day}")
    output_path = archive_path_for_day(day, archive_dir=archive_dir)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"archive already exists: {output_path}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    entries = []
    try:
        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for path in paths:
                raw = path.read_bytes()
                entry = _entry(path, raw, day)
                entries.append(entry)
                archive.writestr(entry["member"], raw)
            manifest = {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "snapshot_day": day,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_directory": str(snapshot_dir),
                "file_count": len(entries),
                "source_size_bytes": sum(int(entry["size_bytes"]) for entry in entries),
                "archive_revision": "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest(),
                "entries": entries,
            }
            archive.writestr(ARCHIVE_MANIFEST_NAME, _canonical_json(manifest))
        verify_snapshot_day_archive(temp_path)
        os.replace(temp_path, output_path)
        return verify_snapshot_day_archive(output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-day", required=True)
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    day = normalize_snapshot_day(args.snapshot_day)
    archive_path = archive_path_for_day(day, archive_dir=args.archive_dir)
    result = (
        verify_snapshot_day_archive(archive_path)
        if args.verify_only
        else build_snapshot_day_archive(
            args.snapshot_dir,
            args.archive_dir,
            day,
            overwrite=args.overwrite,
        )
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"archive: {result['archive_path']}")
        print(f"snapshot day: {result['snapshot_day']}")
        print(f"files: {result['file_count']}")
        print(f"source: {result['source_size_bytes'] / 1024 / 1024:.1f} MiB")
        print(f"archive: {result['archive_size_bytes'] / 1024 / 1024:.1f} MiB")
        print("verified: yes; source files retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
