"""Stage one scan-snapshot day into cold storage with reversible quarantine.

The default mode is a dry run. ``--apply`` moves verified active JSON files to
quarantine only after the archive and SQLite manifest agree. ``--restore`` moves
quarantined files back. This command has no purge or delete operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.archive_scan_snapshot_day import verify_snapshot_day_archive
from stock_analyzer.scan_index_store import DEFAULT_SCAN_INDEX_PATH, ScanIndexStore
from stock_analyzer.scan_snapshot import SNAPSHOT_DIR, normalize_snapshot_day
from stock_analyzer.scan_snapshot_archive import (
    DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR,
    archive_path_for_day,
    read_archive_manifest,
)
from stock_analyzer.scan_snapshot_paths import SCAN_SNAPSHOT_FILENAME_RE


DEFAULT_QUARANTINE_DIR = ROOT / ".cache" / "scan_snapshot_quarantine"
DEFAULT_REPORT_DIR = ROOT / ".cache" / "reports"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _day_files(directory: Path, snapshot_day: str) -> dict[str, Path]:
    if not directory.is_dir():
        return {}
    return {
        path.name: path
        for path in directory.glob(f"*_{snapshot_day}.json")
        if path.is_file() and SCAN_SNAPSHOT_FILENAME_RE.fullmatch(path.name)
    }


def _archive_entries(archive_path: Path) -> dict[str, dict[str, Any]]:
    verify_snapshot_day_archive(archive_path)
    manifest = read_archive_manifest(archive_path)
    return {
        str(entry["name"]): entry
        for entry in manifest.get("entries") or ()
    }


def _validate_files(
    files: dict[str, Path],
    entries: dict[str, dict[str, Any]],
    *,
    label: str,
) -> None:
    for name, path in files.items():
        entry = entries.get(name)
        if entry is None:
            raise RuntimeError(f"{label} file is absent from archive manifest: {name}")
        if path.stat().st_size != int(entry.get("size_bytes") or 0):
            raise RuntimeError(f"{label} file size differs from archive: {name}")
        if _sha256(path) != str(entry.get("sha256") or ""):
            raise RuntimeError(f"{label} file checksum differs from archive: {name}")


def build_migration_plan(
    snapshot_dir: str | Path,
    archive_dir: str | Path,
    quarantine_dir: str | Path,
    snapshot_day: str,
) -> dict[str, Any]:
    source_root = Path(snapshot_dir).expanduser().resolve()
    archive_root = Path(archive_dir).expanduser().resolve()
    quarantine_root = Path(quarantine_dir).expanduser().resolve() / snapshot_day
    archive_path = archive_path_for_day(snapshot_day, archive_dir=archive_root)
    entries = _archive_entries(archive_path)
    active = _day_files(source_root, snapshot_day)
    quarantined = _day_files(quarantine_root, snapshot_day)
    overlap = sorted(set(active) & set(quarantined))
    if overlap:
        raise RuntimeError(f"files exist in active and quarantine tiers: {overlap[0]}")
    _validate_files(active, entries, label="active")
    _validate_files(quarantined, entries, label="quarantine")
    represented = set(active) | set(quarantined)
    missing = sorted(set(entries) - represented)
    unexpected = sorted(represented - set(entries))
    if missing or unexpected:
        raise RuntimeError(
            "migration membership differs from archive: "
            f"missing={len(missing)}, unexpected={len(unexpected)}"
        )
    return {
        "schema_version": 1,
        "snapshot_day": snapshot_day,
        "snapshot_directory": str(source_root),
        "archive_directory": str(archive_root),
        "archive_path": str(archive_path),
        "quarantine_directory": str(quarantine_root),
        "archive_file_count": len(entries),
        "active_file_count": len(active),
        "quarantined_file_count": len(quarantined),
        "active_paths": [str(active[name]) for name in sorted(active)],
        "quarantined_paths": [str(quarantined[name]) for name in sorted(quarantined)],
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_snapshot_day(
    snapshot_dir: str | Path,
    archive_dir: str | Path,
    quarantine_dir: str | Path,
    database_path: str | Path,
    snapshot_day: str,
    *,
    apply: bool = False,
    restore: bool = False,
    register: bool = False,
) -> dict[str, Any]:
    day = normalize_snapshot_day(snapshot_day)
    if not day:
        raise ValueError("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
    if sum(bool(value) for value in (apply, restore, register)) > 1:
        raise ValueError("apply, restore, and register are mutually exclusive")
    plan = build_migration_plan(snapshot_dir, archive_dir, quarantine_dir, day)
    store = ScanIndexStore(Path(database_path).expanduser().resolve())
    preflight = store.reconcile_source_directory(
        snapshot_dir,
        archive_directory=archive_dir,
        delete_missing=False,
        apply_changes=False,
    )
    if not preflight.get("synchronized") or preflight.get("archive_mismatch_count"):
        raise RuntimeError("SQLite/archive preflight reconciliation failed")
    result = {
        **plan,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": (
            "restore" if restore else "apply" if apply else "register" if register else "dry_run"
        ),
        "preflight": preflight,
        "moved_file_count": 0,
        "restored_file_count": 0,
        "source_deleted": False,
    }
    if apply or restore or register:
        registration = store.reconcile_source_directory(
            snapshot_dir,
            archive_directory=archive_dir,
            delete_missing=False,
        )
        if not registration.get("synchronized") or registration.get("archive_mismatch_count"):
            raise RuntimeError("SQLite/archive registration reconciliation failed")
        result["registration"] = registration
    if register:
        result["status"] = "registered"
        result["reconciliation"] = result["registration"]
        return result
    if not apply and not restore:
        return result

    source_root = Path(plan["snapshot_directory"])
    quarantine_root = Path(plan["quarantine_directory"])
    quarantine_root.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    try:
        if restore:
            files = _day_files(quarantine_root, day)
            for name in sorted(files):
                source = files[name]
                destination = source_root / name
                if destination.exists():
                    raise RuntimeError(f"restore destination already exists: {destination}")
                os.replace(source, destination)
                moved.append((destination, source))
            result["restored_file_count"] = len(moved)
        else:
            files = _day_files(source_root, day)
            for name in sorted(files):
                source = files[name]
                destination = quarantine_root / name
                if destination.exists():
                    raise RuntimeError(f"quarantine destination already exists: {destination}")
                os.replace(source, destination)
                moved.append((destination, source))
            result["moved_file_count"] = len(moved)

        reconciliation = store.reconcile_source_directory(
            source_root,
            archive_directory=archive_dir,
            delete_missing=False,
        )
        day_storage = store.snapshot_storage_counts(day)
        expected_tier = "active" if restore else "archive"
        unexpected_tier = "archive" if restore else "active"
        expected_count = plan["archive_file_count"]
        if (
            not reconciliation.get("synchronized")
            or day_storage[expected_tier] != expected_count
            or day_storage[unexpected_tier] != 0
            or day_storage["total"] != expected_count
        ):
            raise RuntimeError("post-move SQLite storage reconciliation failed")
        result["reconciliation"] = reconciliation
        result["day_storage"] = day_storage
        result["status"] = "restored" if restore else "quarantined"
        return result
    except Exception as original_error:
        for current, original in reversed(moved):
            if current.exists() and not original.exists():
                try:
                    os.replace(current, original)
                except Exception as rollback_error:
                    original_error.add_note(
                        f"snapshot file rollback failed for {current}: {rollback_error}"
                    )
        try:
            store.reconcile_source_directory(
                source_root,
                archive_directory=archive_dir,
                delete_missing=False,
            )
        except Exception as reconciliation_error:
            original_error.add_note(
                f"rollback reconciliation failed: {reconciliation_error}"
            )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-day", required=True)
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_SCAN_SNAPSHOT_ARCHIVE_DIR)
    parser.add_argument("--quarantine-dir", type=Path, default=DEFAULT_QUARANTINE_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--register", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = migrate_snapshot_day(
        args.snapshot_dir,
        args.archive_dir,
        args.quarantine_dir,
        args.db,
        args.snapshot_day,
        apply=args.apply,
        restore=args.restore,
        register=args.register,
    )
    report_path = args.report_dir / f"scan-snapshot-migration-{result['snapshot_day']}.json"
    _write_report(report_path, result)
    result["report_path"] = str(report_path.resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"mode: {result['mode']}")
        print(f"snapshot day: {result['snapshot_day']}")
        print(f"archive files: {result['archive_file_count']}")
        print(f"active files: {result['active_file_count']}")
        print(f"quarantined files: {result['quarantined_file_count']}")
        print(f"moved: {result['moved_file_count']}; restored: {result['restored_file_count']}")
        print("source deleted: no")
        print(f"report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
