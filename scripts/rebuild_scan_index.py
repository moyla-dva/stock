"""Build or incrementally refresh the SQLite scan metadata index."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.scan_index_store import (
    DEFAULT_SCAN_INDEX_PATH,
    ScanIndexStore,
)
from stock_analyzer.scan_snapshot import SNAPSHOT_DIR
from stock_analyzer.scan_snapshot_archive import DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR
from stock_analyzer.scan_snapshot_storage import discover_snapshot_storage


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a rebuildable SQLite index over scan snapshot JSON files."
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SNAPSHOT_DIR,
        help="Directory containing scan snapshot JSON files.",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR,
        help="Directory containing checksum-verified per-day snapshot archives.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_SCAN_INDEX_PATH,
        help="SQLite index path.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear only the SQLite index before rebuilding; source snapshots are untouched.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-read files even when path, size, and mtime are unchanged.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Index at most this many files for validation; 0 means all files.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress after this many files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the final machine-readable summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    snapshot_dir = args.snapshot_dir.expanduser().resolve()
    archive_dir = args.archive_dir.expanduser().resolve()
    database_path = args.db.expanduser().resolve()
    if not snapshot_dir.exists():
        raise SystemExit(f"snapshot directory does not exist: {snapshot_dir}")

    all_records = discover_snapshot_storage(snapshot_dir, archive_dir)
    records = all_records
    if args.limit > 0:
        records = records[: args.limit]
    progress_every = max(1, int(args.progress_every))
    started = time.perf_counter()

    def report(position, total, stats):
        if args.json or (position % progress_every != 0 and position != total):
            return
        print(
            f"indexed {position}/{total} files "
            f"(written={stats.indexed}, skipped={stats.skipped}, "
            f"failed={stats.failed}, candidates={stats.candidates})",
            flush=True,
        )

    store = ScanIndexStore(database_path)
    build_stats = store.index_snapshot_records(
        records,
        reset=args.reset,
        force=args.force,
        progress_callback=report,
    )
    if args.reset:
        build_scope = (
            "full"
            if args.limit <= 0 and build_stats.failed == 0
            else "partial"
        )
        store.record_build_scope(
            build_scope,
            source_snapshot_count=len(all_records) if build_scope == "full" else None,
            source_directory=snapshot_dir if build_scope == "full" else None,
        )
    if args.limit <= 0:
        store.reconcile_source_directory(
            snapshot_dir,
            archive_directory=archive_dir,
        )
    elapsed = time.perf_counter() - started
    summary = {
        "snapshot_directory": str(snapshot_dir),
        "archive_directory": str(archive_dir),
        "database_path": str(database_path),
        "elapsed_seconds": round(elapsed, 3),
        "source_snapshot_count": len(all_records),
        "build": build_stats.to_dict(),
        "index": store.status(),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if build_stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
