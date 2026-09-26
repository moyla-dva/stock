import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_scan_snapshot_storage import build_snapshot_storage_report


class ScanSnapshotStorageAuditTest(unittest.TestCase):
    def _snapshot(self, directory, code, day, content="{}"):
        path = directory / f"{code}_20250429_{day}.json"
        path.write_text(content, encoding="utf-8")
        return path

    def _index(self, database, snapshot_dir, paths):
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE snapshot_manifest (
                path TEXT,
                snapshot_day TEXT,
                file_size INTEGER,
                parse_status TEXT,
                data_date TEXT,
                strategy_version TEXT
            );
            """
        )
        revision = "revision-1"
        metadata = {
            "build_scope": "full",
            "source_sync_snapshot_count": str(len(paths)),
            "source_sync_directory": str(snapshot_dir.resolve()),
            "source_sync_revision": revision,
            "snapshot_index_revision": revision,
        }
        connection.executemany("INSERT INTO index_metadata VALUES (?, ?)", metadata.items())
        connection.executemany(
            "INSERT INTO snapshot_manifest VALUES (?, ?, ?, 'ok', ?, '2026.09.20.1')",
            [
                (str(path.resolve()), path.stem.rsplit("_", 1)[-1], path.stat().st_size, day)
                for path, day in paths
            ],
        )
        connection.commit()
        connection.close()

    def test_report_marks_only_old_parity_days_for_archive_review(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_dir = root / "snapshots"
            snapshot_dir.mkdir()
            paths = [
                (self._snapshot(snapshot_dir, "600001", "20260922"), "2026-09-22"),
                (self._snapshot(snapshot_dir, "600002", "20260923", "{\"x\":1}"), "2026-09-23"),
                (self._snapshot(snapshot_dir, "600003", "20260924", "{\"x\":2}"), "2026-09-24"),
            ]
            database = root / "scan.sqlite3"
            self._index(database, snapshot_dir, paths)

            report = build_snapshot_storage_report(snapshot_dir, database, keep_latest_days=1)

        self.assertTrue(report["index"]["global_parity"])
        self.assertEqual(report["retention_plan"]["keep_days"], ["20260924"])
        self.assertEqual(report["retention_plan"]["archive_review_days"], ["20260922", "20260923"])
        self.assertEqual(report["retention_plan"]["archive_review_file_count"], 2)
        self.assertFalse(report["retention_plan"]["apply_enabled"])

    def test_source_manifest_mismatch_blocks_archive_review(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_dir = root / "snapshots"
            snapshot_dir.mkdir()
            indexed = self._snapshot(snapshot_dir, "600001", "20260922")
            database = root / "scan.sqlite3"
            self._index(database, snapshot_dir, [(indexed, "2026-09-22")])
            self._snapshot(snapshot_dir, "600002", "20260923")

            report = build_snapshot_storage_report(snapshot_dir, database, keep_latest_days=1)

        self.assertFalse(report["index"]["global_parity"])
        self.assertEqual(report["retention_plan"]["archive_review_days"], [])
        self.assertTrue(report["retention_plan"]["blockers"])
        self.assertEqual(report["days"][0]["disposition"], "blocked")

    def test_non_snapshot_json_is_reported_as_an_excluded_notice(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_dir = root / "snapshots"
            snapshot_dir.mkdir()
            indexed = self._snapshot(snapshot_dir, "600001", "20260924")
            (snapshot_dir / "notes.json").write_text("{}", encoding="utf-8")
            database = root / "scan.sqlite3"
            self._index(database, snapshot_dir, [(indexed, "2026-09-24")])

            report = build_snapshot_storage_report(snapshot_dir, database, keep_latest_days=1)

        self.assertEqual(report["source"]["ignored_json_count"], 1)
        self.assertEqual(report["retention_plan"]["blockers"], [])
        self.assertTrue(any("non-snapshot" in item for item in report["retention_plan"]["notices"]))


if __name__ == "__main__":
    unittest.main()
