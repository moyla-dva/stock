"""Audit scan-snapshot storage and produce a review-only retention plan.

The JSON snapshots remain the detail and reproducibility source. This command
never moves or deletes files and intentionally has no ``--apply`` option. Days
outside the active retention window are only marked for archive review.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.scan_index_store import DEFAULT_SCAN_INDEX_PATH
from stock_analyzer.scan_snapshot import SNAPSHOT_DIR
from stock_analyzer.scan_snapshot_archive import DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR
from stock_analyzer.scan_snapshot_paths import SCAN_SNAPSHOT_FILENAME_RE
from stock_analyzer.scan_snapshot_storage import (
    STORAGE_TIER_ACTIVE,
    discover_snapshot_storage,
    snapshot_storage_revision,
)


def _source_inventory(
    snapshot_dir: Path,
    archive_dir: Path,
) -> tuple[dict[str, dict[str, int]], int, int, str]:
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {
        "file_count": 0,
        "size_bytes": 0,
        "active_file_count": 0,
        "archive_file_count": 0,
    })
    ignored_json_count = 0
    if snapshot_dir.is_dir():
        with os.scandir(snapshot_dir) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
                    continue
                if not SCAN_SNAPSHOT_FILENAME_RE.fullmatch(entry.name):
                    ignored_json_count += 1
    records = discover_snapshot_storage(snapshot_dir, archive_dir)
    archive_paths = set()
    for record in records:
        snapshot_day = record.logical_path.name.rsplit("_", 1)[-1][:-5]
        by_day[snapshot_day]["file_count"] += 1
        by_day[snapshot_day]["size_bytes"] += record.size_bytes
        if record.storage_tier == STORAGE_TIER_ACTIVE:
            by_day[snapshot_day]["active_file_count"] += 1
        else:
            by_day[snapshot_day]["archive_file_count"] += 1
        if record.archive_path:
            archive_paths.add(record.archive_path)
    archive_physical_size = sum(
        path.stat().st_size for path in archive_paths if path.is_file()
    )
    return (
        dict(by_day),
        ignored_json_count,
        archive_physical_size,
        snapshot_storage_revision(records),
    )


def _read_index_inventory(database_path: Path) -> dict[str, Any]:
    if not database_path.is_file():
        return {"available": False, "error": "index database is missing", "days": {}, "metadata": {}}
    uri = f"file:{database_path.resolve()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "snapshot_manifest" not in tables:
            return {"available": False, "error": "snapshot_manifest table is missing", "days": {}, "metadata": {}}
        metadata = {}
        if "index_metadata" in tables:
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM index_metadata")
            }
        rows = connection.execute(
            """
            SELECT snapshot_day,
                   COUNT(*) AS file_count,
                   COALESCE(SUM(file_size), 0) AS size_bytes,
                   SUM(CASE WHEN parse_status != 'ok' THEN 1 ELSE 0 END) AS invalid_count,
                   MIN(data_date) AS first_data_date,
                   MAX(data_date) AS latest_data_date,
                   GROUP_CONCAT(DISTINCT strategy_version) AS strategy_versions
            FROM snapshot_manifest
            GROUP BY snapshot_day
            ORDER BY snapshot_day
            """
        ).fetchall()
        days = {
            str(row["snapshot_day"]): {
                "file_count": int(row["file_count"] or 0),
                "size_bytes": int(row["size_bytes"] or 0),
                "invalid_count": int(row["invalid_count"] or 0),
                "first_data_date": str(row["first_data_date"] or ""),
                "latest_data_date": str(row["latest_data_date"] or ""),
                "strategy_versions": sorted(filter(None, str(row["strategy_versions"] or "").split(","))),
            }
            for row in rows
        }
        return {"available": True, "error": "", "days": days, "metadata": metadata}
    except sqlite3.Error as exc:
        return {"available": False, "error": str(exc), "days": {}, "metadata": {}}
    finally:
        if "connection" in locals():
            connection.close()


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_snapshot_storage_report(
    snapshot_dir: str | Path,
    database_path: str | Path,
    *,
    archive_dir: str | Path | None = None,
    keep_latest_days: int = 5,
) -> dict[str, Any]:
    snapshot_dir = Path(snapshot_dir).expanduser().resolve()
    database_path = Path(database_path).expanduser().resolve()
    archive_dir = Path(
        archive_dir or DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR
    ).expanduser().resolve()
    keep_latest_days = max(1, int(keep_latest_days))
    (
        source_days,
        ignored_json_count,
        archive_physical_size,
        source_storage_revision,
    ) = _source_inventory(
        snapshot_dir,
        archive_dir,
    )
    index = _read_index_inventory(database_path)
    index_days = index["days"]
    all_days = sorted(set(source_days) | set(index_days))
    keep_days = set(all_days[-keep_latest_days:])

    metadata = index.get("metadata") or {}
    source_file_count = sum(item["file_count"] for item in source_days.values())
    source_size_bytes = sum(item["size_bytes"] for item in source_days.values())
    active_file_count = sum(item["active_file_count"] for item in source_days.values())
    archive_file_count = sum(item["archive_file_count"] for item in source_days.values())
    manifest_file_count = sum(item["file_count"] for item in index_days.values())
    manifest_size_bytes = sum(item["size_bytes"] for item in index_days.values())
    source_directory_matches = bool(
        metadata.get("source_sync_directory")
        and Path(metadata["source_sync_directory"]).expanduser().resolve() == snapshot_dir
    )
    archive_directory_matches = bool(
        metadata.get("source_sync_archive_directory")
        and Path(metadata["source_sync_archive_directory"]).expanduser().resolve() == archive_dir
    )
    storage_revision_matches = bool(
        metadata.get("source_sync_storage_revision")
        and metadata.get("source_sync_storage_revision") == source_storage_revision
    )
    revision_matches = bool(
        metadata.get("source_sync_revision")
        and metadata.get("source_sync_revision") == metadata.get("snapshot_index_revision")
    )
    build_scope_full = metadata.get("build_scope") == "full"
    sync_count = _integer(metadata.get("source_sync_snapshot_count"))
    global_parity = bool(
        index.get("available")
        and build_scope_full
        and source_directory_matches
        and archive_directory_matches
        and revision_matches
        and storage_revision_matches
        and sync_count == source_file_count == manifest_file_count
    )

    blockers = []
    if not index.get("available"):
        blockers.append(f"SQLite index unavailable: {index.get('error') or 'unknown error'}")
    if index.get("available") and not build_scope_full:
        blockers.append("SQLite index build_scope is not full")
    if index.get("available") and not source_directory_matches:
        blockers.append("SQLite source_sync_directory does not match the snapshot directory")
    if index.get("available") and not archive_directory_matches:
        blockers.append("SQLite source_sync_archive_directory does not match the archive directory")
    if index.get("available") and not revision_matches:
        blockers.append("SQLite source and index revisions do not match")
    if index.get("available") and not storage_revision_matches:
        blockers.append("SQLite storage revision does not match active/archive inventory")
    if index.get("available") and sync_count != source_file_count:
        blockers.append("SQLite source_sync_snapshot_count does not match the filesystem")
    if index.get("available") and manifest_file_count != source_file_count:
        blockers.append("SQLite manifest membership count does not match the filesystem")
    notices = []
    if ignored_json_count:
        notices.append(
            f"snapshot directory contains {ignored_json_count} non-snapshot JSON files; they are excluded"
        )

    day_reports = []
    archive_review_file_count = 0
    archive_review_size_bytes = 0
    for day in all_days:
        source = source_days.get(day, {
            "file_count": 0,
            "size_bytes": 0,
            "active_file_count": 0,
            "archive_file_count": 0,
        })
        manifest = index_days.get(day, {})
        count_matches = source["file_count"] == int(manifest.get("file_count") or 0)
        size_matches = source["size_bytes"] == int(manifest.get("size_bytes") or 0)
        invalid_count = int(manifest.get("invalid_count") or 0)
        day_ready = global_parity and count_matches and size_matches and invalid_count == 0
        if source["file_count"] and source["archive_file_count"] == source["file_count"]:
            disposition = "archived"
        elif day in keep_days:
            disposition = "keep_active"
        elif day_ready:
            disposition = "archive_review"
            archive_review_file_count += source["file_count"]
            archive_review_size_bytes += source["size_bytes"]
        else:
            disposition = "blocked"
        day_reports.append({
            "snapshot_day": day,
            "disposition": disposition,
            "source_file_count": source["file_count"],
            "source_size_bytes": source["size_bytes"],
            "active_file_count": source["active_file_count"],
            "archive_file_count": source["archive_file_count"],
            "manifest_file_count": int(manifest.get("file_count") or 0),
            "manifest_size_bytes": int(manifest.get("size_bytes") or 0),
            "invalid_count": invalid_count,
            "first_data_date": str(manifest.get("first_data_date") or ""),
            "latest_data_date": str(manifest.get("latest_data_date") or ""),
            "strategy_versions": list(manifest.get("strategy_versions") or []),
            "index_parity": count_matches and size_matches,
        })

    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "review_only",
        "source": {
            "snapshot_directory": str(snapshot_dir),
            "archive_directory": str(archive_dir),
            "file_count": source_file_count,
            "active_file_count": active_file_count,
            "archive_file_count": archive_file_count,
            "size_bytes": source_size_bytes,
            "archive_physical_size_bytes": archive_physical_size,
            "storage_revision": source_storage_revision,
            "day_count": len(source_days),
            "ignored_json_count": ignored_json_count,
        },
        "index": {
            "database_path": str(database_path),
            "available": bool(index.get("available")),
            "error": index.get("error") or "",
            "manifest_file_count": manifest_file_count,
            "manifest_size_bytes": manifest_size_bytes,
            "build_scope": metadata.get("build_scope") or "unknown",
            "source_sync_snapshot_count": sync_count,
            "source_directory_matches": source_directory_matches,
            "archive_directory_matches": archive_directory_matches,
            "revision_matches": revision_matches,
            "storage_revision_matches": storage_revision_matches,
            "source_sync_storage_revision": metadata.get("source_sync_storage_revision") or "",
            "global_parity": global_parity,
        },
        "retention_plan": {
            "keep_latest_snapshot_days": keep_latest_days,
            "keep_days": sorted(keep_days),
            "archive_review_days": [
                item["snapshot_day"] for item in day_reports if item["disposition"] == "archive_review"
            ],
            "archive_review_file_count": archive_review_file_count,
            "archive_review_size_bytes": archive_review_size_bytes,
            "apply_enabled": False,
            "blockers": blockers,
            "notices": notices,
            "completed_safeguards": [
                "per-day ZIP archive format with a per-file SHA-256 manifest",
                "active-first CandidateDetail and explicit historical-day archive readers",
                "SQLite-backed history-day listing",
                "source-to-archive round-trip verification without source deletion",
                "SQLite schema v9 active/archive storage-tier reconciliation",
                "dry-run, register, quarantine, and restore migration phases",
            ],
            "required_before_source_removal": [
                "archive and verify every selected day before changing source membership",
                "register archive metadata while active files remain authoritative",
                "upgrade or stop every runtime that predates archive-aware reads",
                "quarantine one day at a time and observe read paths before any purge policy",
                "define quarantine retention and a separate explicit purge policy; no purge exists today",
            ],
        },
        "days": day_reports,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    parser.add_argument("--keep-latest-days", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_snapshot_storage_report(
        args.snapshot_dir,
        args.db,
        archive_dir=args.archive_dir,
        keep_latest_days=args.keep_latest_days,
    )
    if args.output:
        _write_report(args.output, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        source = report["source"]
        plan = report["retention_plan"]
        print(f"snapshot directory: {source['snapshot_directory']}")
        print(f"snapshots: {source['file_count']} files / {source['size_bytes'] / 1024 / 1024:.1f} MiB")
        print(
            f"storage tiers: active={source['active_file_count']}, "
            f"archive={source['archive_file_count']}"
        )
        print(f"snapshot days: {source['day_count']}; keep latest: {plan['keep_latest_snapshot_days']}")
        print(
            "archive review: "
            f"{len(plan['archive_review_days'])} days / {plan['archive_review_file_count']} files / "
            f"{plan['archive_review_size_bytes'] / 1024 / 1024:.1f} MiB"
        )
        print("audit apply: disabled; use the reversible migration command after reviewing this report")
        for blocker in plan["blockers"]:
            print(f"blocker: {blocker}")
        for notice in plan["notices"]:
            print(f"notice: {notice}")
        if args.output:
            print(f"report: {args.output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
