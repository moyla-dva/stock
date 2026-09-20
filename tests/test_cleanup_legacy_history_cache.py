"""Regression tests for the legacy history-cache cleanup script."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cleanup_legacy_history_cache import classify_legacy_files


class CleanupLegacyHistoryCacheTest(unittest.TestCase):
    def _write_legacy(self, cache_dir, name, dates):
        path = cache_dir / name
        rows = "\n".join(["date,close"] + [f"{date},10.0" for date in dates])
        path.write_text(rows + "\n", encoding="utf-8")
        return path

    def test_dry_run_with_migrate_missing_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            self._write_legacy(cache_dir, "600063_20250429_20260115_qfq.csv", ["2026-01-14", "2026-01-15"])

            deletable, keep_reasons, migrated = classify_legacy_files(cache_dir, migrate_missing=True, apply=False)

            self.assertEqual(len(migrated), 1)
            self.assertEqual(len(deletable), 0)
            self.assertFalse((cache_dir / "600063_20250429_qfq.csv").exists())
            self.assertFalse((cache_dir / "600063_20250429_qfq.csv.meta.json").exists())
            self.assertTrue((cache_dir / "600063_20250429_20260115_qfq.csv").exists())

    def test_apply_migrates_newest_legacy_and_marks_rest_deletable(self):
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            self._write_legacy(cache_dir, "600063_20250429_20260110_qfq.csv", ["2026-01-09", "2026-01-10"])
            self._write_legacy(cache_dir, "600063_20250429_20260115_qfq.csv", ["2026-01-14", "2026-01-15"])

            deletable, keep_reasons, migrated = classify_legacy_files(cache_dir, migrate_missing=True, apply=True)

            canonical = cache_dir / "600063_20250429_qfq.csv"
            self.assertTrue(canonical.exists())
            meta = json.loads((cache_dir / "600063_20250429_qfq.csv.meta.json").read_text())
            self.assertEqual(meta["latest_date"], "20260115")
            self.assertEqual([item[0].name for item in deletable], ["600063_20250429_20260110_qfq.csv"])
            self.assertEqual([item[0].name for item in migrated], ["600063_20250429_20260115_qfq.csv"])
            self.assertTrue((cache_dir / "600063_20250429_20260115_qfq.csv").exists())

    def test_legacy_newer_than_canonical_is_kept(self):
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            canonical = self._write_legacy(cache_dir, "600063_20250429_qfq.csv", ["2026-01-10"])
            canonical.rename(cache_dir / "600063_20250429_qfq.csv")
            self._write_legacy(cache_dir, "600063_20250429_20260115_qfq.csv", ["2026-01-14", "2026-01-15"])
            (cache_dir / "600063_20250429_qfq.csv.meta.json").write_text(
                json.dumps({"stored_at": "2026-01-10T15:00:00", "latest_date": "20260110"}), encoding="utf-8"
            )

            deletable, keep_reasons, migrated = classify_legacy_files(cache_dir, migrate_missing=True, apply=True)

            self.assertEqual(deletable, [])
            self.assertEqual(migrated, [])
            self.assertEqual(len(keep_reasons), 1)
            self.assertIn("legacy 更新", keep_reasons[0][1])


if __name__ == "__main__":
    unittest.main()
