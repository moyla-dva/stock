import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.archive_scan_snapshot_day import build_snapshot_day_archive
from scripts.migrate_scan_snapshot_day_to_archive import migrate_snapshot_day
from stock_analyzer.scan_index_store import ScanIndexStore
from stock_analyzer.versioning import SCAN_STRATEGY_VERSION


def _snapshot():
    return {
        "version": 1,
        "strategy_version": SCAN_STRATEGY_VERSION,
        "data_adjust": "qfq",
        "code": "600001",
        "name": "sample",
        "snapshot_day": "20260922",
        "data_date": "2026-09-22",
        "rows": 10,
        "computed_scan_types": ["opportunity"],
        "results": {
            "opportunity": {
                "code": "600001",
                "name": "sample",
                "event_date": "2026-09-22",
                "signal_key": "v2_breakout",
                "v2_signal": "C突",
                "v2_state": "trigger_plan_ready",
                "v2_permission": "breakout_allowed",
                "v2_plan_status": "ready",
                "v2_priority_score": 180,
            }
        },
    }


class ScanSnapshotStorageMigrationTest(unittest.TestCase):
    def test_apply_quarantines_and_restore_recovers_without_deleting(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "snapshots"
            archives = root / "archives"
            quarantine = root / "quarantine"
            database = root / "scan.sqlite3"
            source.mkdir()
            path = source / "600001_20250429_20260922.json"
            path.write_text(json.dumps(_snapshot()), encoding="utf-8")
            build_snapshot_day_archive(source, archives, "20260922")
            store = ScanIndexStore(database)
            store.index_snapshot_files([path], reset=True)
            store.record_build_scope(
                "full",
                source_snapshot_count=1,
                source_directory=source,
            )

            dry_run = migrate_snapshot_day(
                source, archives, quarantine, database, "20260922"
            )
            with store._connect() as connection:
                dry_run_manifest = connection.execute(
                    "SELECT storage_tier, archive_path FROM snapshot_manifest"
                ).fetchone()
            self.assertEqual(dry_run["mode"], "dry_run")
            self.assertFalse(dry_run["preflight"]["changes_applied"])
            self.assertTrue(path.exists())
            self.assertEqual(dry_run_manifest["storage_tier"], "active")
            self.assertEqual(dry_run_manifest["archive_path"], "")

            registered = migrate_snapshot_day(
                source,
                archives,
                quarantine,
                database,
                "20260922",
                register=True,
            )
            with store._connect() as connection:
                registered_manifest = connection.execute(
                    "SELECT storage_tier, archive_path FROM snapshot_manifest"
                ).fetchone()
            self.assertEqual(registered["status"], "registered")
            self.assertFalse(registered["preflight"]["changes_applied"])
            self.assertTrue(registered["registration"]["changes_applied"])
            self.assertEqual(registered_manifest["storage_tier"], "active")
            self.assertTrue(registered_manifest["archive_path"])
            self.assertTrue(path.exists())

            applied = migrate_snapshot_day(
                source, archives, quarantine, database, "20260922", apply=True
            )
            archived_status = store.status()
            restored = migrate_snapshot_day(
                source, archives, quarantine, database, "20260922", restore=True
            )
            active_status = store.status()

            self.assertEqual(applied["status"], "quarantined")
            self.assertEqual(applied["moved_file_count"], 1)
            self.assertEqual(applied["day_storage"], {"active": 0, "archive": 1, "total": 1})
            self.assertEqual(archived_status["archive_snapshot_count"], 1)
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(restored["restored_file_count"], 1)
            self.assertEqual(restored["day_storage"], {"active": 1, "archive": 0, "total": 1})
            self.assertTrue(path.exists())
            self.assertEqual(active_status["active_snapshot_count"], 1)
            self.assertFalse(applied["source_deleted"])

    def test_preflight_rejects_stale_archive_before_moving_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "snapshots"
            archives = root / "archives"
            quarantine = root / "quarantine"
            database = root / "scan.sqlite3"
            source.mkdir()
            path = source / "600001_20250429_20260922.json"
            path.write_text(json.dumps(_snapshot()), encoding="utf-8")
            build_snapshot_day_archive(source, archives, "20260922")
            changed = _snapshot()
            changed["results"]["opportunity"]["v2_priority_score"] = 999
            path.write_text(json.dumps(changed), encoding="utf-8")
            store = ScanIndexStore(database)
            store.index_snapshot_files([path], reset=True)
            store.record_build_scope(
                "full",
                source_snapshot_count=1,
                source_directory=source,
            )

            with self.assertRaises(RuntimeError):
                migrate_snapshot_day(
                    source,
                    archives,
                    quarantine,
                    database,
                    "20260922",
                    apply=True,
                )

            with store._connect() as connection:
                manifest = connection.execute(
                    "SELECT storage_tier, archive_path FROM snapshot_manifest"
                ).fetchone()

            self.assertTrue(path.exists())
            self.assertFalse((quarantine / "20260922" / path.name).exists())
            self.assertEqual(manifest["storage_tier"], "active")
            self.assertEqual(manifest["archive_path"], "")

    def test_rollback_cleanup_failure_preserves_original_migration_error(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "snapshots"
            archives = root / "archives"
            quarantine = root / "quarantine"
            database = root / "scan.sqlite3"
            source.mkdir()
            path = source / "600001_20250429_20260922.json"
            path.write_text(json.dumps(_snapshot()), encoding="utf-8")
            build_snapshot_day_archive(source, archives, "20260922")
            store = ScanIndexStore(database)
            store.index_snapshot_files([path], reset=True)
            store.record_build_scope(
                "full",
                source_snapshot_count=1,
                source_directory=source,
            )

            original_reconcile = ScanIndexStore.reconcile_source_directory
            calls = 0

            def reconcile_with_post_move_failure(instance, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls <= 2:
                    return original_reconcile(instance, *args, **kwargs)
                if calls == 3:
                    return {"synchronized": False}
                raise RuntimeError("cleanup reconciliation failed")

            with (
                patch.object(
                    ScanIndexStore,
                    "reconcile_source_directory",
                    autospec=True,
                    side_effect=reconcile_with_post_move_failure,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "post-move SQLite storage reconciliation failed",
                ) as raised,
            ):
                migrate_snapshot_day(
                    source,
                    archives,
                    quarantine,
                    database,
                    "20260922",
                    apply=True,
                )

            self.assertTrue(path.exists())
            self.assertFalse((quarantine / "20260922" / path.name).exists())
            self.assertTrue(any(
                "rollback reconciliation failed: cleanup reconciliation failed" in note
                for note in getattr(raised.exception, "__notes__", ())
            ))


if __name__ == "__main__":
    unittest.main()
