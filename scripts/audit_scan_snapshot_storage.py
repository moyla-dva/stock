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
from stock_analyzer.scan_snapshot_paths import SCAN_SNAPSHOT_FILENAME_RE


def _source_inventory(snapshot_dir: Path) -> tuple[dict[str, dict[str, int]], int]:
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"file_count": 0, "size_bytes": 0})
    ignored_json_count = 0
    if not snapshot_dir.is_dir():
        return {}, 0
    with os.scandir(snapshot_dir) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
                continue
            if not SCAN_SNAPSHOT_FILENAME_RE.fullmatch(entry.name):
                ignored_json_count += 1
                continue
            snapshot_day = entry.name.rsplit("_", 1)[-1][:-5]
            stat = entry.stat(follow_symlinks=False)
            by_day[snapshot_day]["file_count"] += 1
            by_day[snapshot_day]["size_bytes"] += int(stat.st_size)
    return dict(by_day), ignored_json_count


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
    keep_latest_days: int = 5,
) -> dict[str, Any]:
    snapshot_dir = Path(snapshot_dir).expanduser().resolve()
    database_path = Path(database_path).expanduser().resolve()
    keep_latest_days = max(1, int(keep_latest_days))
    source_days, ignored_json_count = _source_inventory(snapshot_dir)
    index = _read_index_inventory(database_path)
    index_days = index["days"]
    all_days = sorted(set(source_days) | set(index_days))
    keep_days = set(all_days[-keep_latest_days:])

    metadata = index.get("metadata") or {}
    source_file_count = sum(item["file_count"] for item in source_days.values())
    source_size_bytes = sum(item["size_bytes"] for item in source_days.values())
    manifest_file_count = sum(item["file_count"] for item in index_days.values())
    manifest_size_bytes = sum(item["size_bytes"] for item in index_days.values())
    source_directory_matches = bool(
        metadata.get("source_sync_directory")
        and Path(metadata["source_sync_directory"]).expanduser().resolve() == snapshot_dir
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
        and revision_matches
        and sync_count == source_file_count == manifest_file_count
    )

    blockers = []
    if not index.get("available"):
        blockers.append(f"SQLite index unavailable: {index.get('error') or 'unknown error'}")
    if index.get("available") and not build_scope_full:
        blockers.append("SQLite index build_scope is not full")
    if index.get("available") and not source_directory_matches:
        blockers.append("SQLite source_sync_directory does not match the snapshot directory")
    if index.get("available") and not revision_matches:
        blockers.append("SQLite source and index revisions do not match")
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
        source = source_days.get(day, {"file_count": 0, "size_bytes": 0})
        manifest = index_days.get(day, {})
        count_matches = source["file_count"] == int(manifest.get("file_count") or 0)
        size_matches = source["size_bytes"] == int(manifest.get("size_bytes") or 0)
        invalid_count = int(manifest.get("invalid_count") or 0)
        day_ready = global_parity and count_matches and size_matches and invalid_count == 0
        if day in keep_days:
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
            "file_count": source_file_count,
            "size_bytes": source_size_bytes,
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
            "revision_matches": revision_matches,
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
            "required_before_apply": [
                "define a cold archive format with per-file checksums",
                "implement CandidateDetail and historical readers over that archive",
                "verify a source-to-archive round trip before removing originals",
                "reconcile the SQLite manifest after any source membership change",
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
    parser.add_argument("--db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    parser.add_argument("--keep-latest-days", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_snapshot_storage_report(
        args.snapshot_dir,
        args.db,
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
        print(f"snapshot days: {source['day_count']}; keep latest: {plan['keep_latest_snapshot_days']}")
        print(
            "archive review: "
            f"{len(plan['archive_review_days'])} days / {plan['archive_review_file_count']} files / "
            f"{plan['archive_review_size_bytes'] / 1024 / 1024:.1f} MiB"
        )
        print("apply: disabled (archive reader and round-trip verification are required first)")
        for blocker in plan["blockers"]:
            print(f"blocker: {blocker}")
        for notice in plan["notices"]:
            print(f"notice: {notice}")
        if args.output:
            print(f"report: {args.output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
