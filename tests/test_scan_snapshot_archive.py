import json
import zipfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.archive_scan_snapshot_day import (
    build_snapshot_day_archive,
    verify_snapshot_day_archive,
)
from stock_analyzer import scan_snapshot
from stock_analyzer.scan_snapshot_archive import (
    ARCHIVE_MANIFEST_NAME,
    SnapshotArchiveError,
    read_archived_snapshot_bytes,
)
from stock_analyzer.versioning import SCAN_SNAPSHOT_SCHEMA_VERSION, SCAN_STRATEGY_VERSION


def _snapshot(code, day):
    return {
        "version": SCAN_SNAPSHOT_SCHEMA_VERSION,
        "strategy_version": SCAN_STRATEGY_VERSION,
        "data_adjust": "qfq",
        "code": code,
        "snapshot_day": day,
        "data_date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "computed_scan_types": ["opportunity", "risk"],
        "results": {},
    }


class ScanSnapshotArchiveTest(unittest.TestCase):
    def _write_snapshot(self, directory, code, day):
        path = directory / f"{code}_20250429_{day}.json"
        path.write_text(json.dumps(_snapshot(code, day)), encoding="utf-8")
        return path

    def test_archive_round_trip_keeps_sources_and_reads_after_source_removal(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "snapshots"
            archive_dir = root / "archives"
            source.mkdir()
            paths = [
                self._write_snapshot(source, "600001", "20260922"),
                self._write_snapshot(source, "000001", "20260922"),
            ]

            result = build_snapshot_day_archive(source, archive_dir, "2026-09-22")

            self.assertTrue(result["verified"])
            self.assertEqual(result["file_count"], 2)
            self.assertTrue(all(path.is_file() for path in paths))
            for path in paths:
                path.unlink()

            with patch.object(scan_snapshot, "SNAPSHOT_DIR", source):
                virtual_paths = scan_snapshot.scan_snapshot_day_files(
                    start_date="2025-04-29",
                    snapshot_day="20260922",
                    archive_dir=archive_dir,
                )
                payloads = [
                    scan_snapshot.read_scan_snapshot_file(path, archive_dir=archive_dir)
                    for path in virtual_paths
                ]

        self.assertEqual({item["code"] for item in payloads}, {"600001", "000001"})

    def test_corrupt_member_is_rejected_by_checksum(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "snapshots"
            archive_dir = root / "archives"
            source.mkdir()
            path = self._write_snapshot(source, "600001", "20260922")
            result = build_snapshot_day_archive(source, archive_dir, "20260922")
            archive_path = Path(result["archive_path"])
            with zipfile.ZipFile(archive_path, "r") as archive:
                manifest = archive.read(ARCHIVE_MANIFEST_NAME)
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(ARCHIVE_MANIFEST_NAME, manifest)
                archive.writestr(f"snapshots/{path.name}", b"corrupt")

            with self.assertRaises(SnapshotArchiveError):
                read_archived_snapshot_bytes(path, archive_dir=archive_dir)
            with self.assertRaises(SnapshotArchiveError):
                verify_snapshot_day_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
