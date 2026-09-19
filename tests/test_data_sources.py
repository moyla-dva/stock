import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from stock_analyzer import data_sources
from stock_analyzer.data_sources import collect_data_source_status
from scripts.append_daily_quotes_to_history_cache import append_rejection_reason


class DataSourcesTest(unittest.TestCase):
    def test_collect_data_source_status_reports_local_caches(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            catalog_dir = root / "catalog"
            board_dir = root / "board"
            snapshot_dir = root / "snapshots"
            jobs_path = root / "jobs" / "jobs.json"
            history_dir.mkdir()
            catalog_dir.mkdir()
            board_dir.mkdir()
            snapshot_dir.mkdir()
            jobs_path.parent.mkdir()

            pd.DataFrame({
                "date": ["2026-05-08", "2026-05-11"],
                "open": [10, 11],
                "high": [11, 12],
                "low": [9, 10],
                "close": [10.5, 11.5],
                "volume": [1000, 1200],
            }).to_csv(history_dir / "600063_20250429_20260511_qfq.csv", index=False)

            (catalog_dir / "stock_profiles.json").write_text(json.dumps({
                "600063": {"code": "600063", "name": "示例", "sector": "半导体", "concepts": ["芯片"]},
            }), encoding="utf-8")
            (catalog_dir / "stock_concepts.json").write_text(json.dumps({
                "source": "test",
                "updated_at": "2026-05-11T15:30:00",
                "stocks": {"600063": ["芯片"]},
            }, ensure_ascii=False), encoding="utf-8")
            (board_dir / "industry_demo.json").write_text("{}", encoding="utf-8")
            jobs_path.write_text(json.dumps({"jobs": [{"id": "job1"}]}), encoding="utf-8")

            with patch("stock_analyzer.data_fetcher.CACHE_DIR", history_dir):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", catalog_dir):
                    with patch("stock_analyzer.market_boards.BOARD_MARKET_CACHE_DIR", board_dir):
                        with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", snapshot_dir):
                            with patch("stock_analyzer.scan_jobs.DEFAULT_HISTORY_PATH", jobs_path):
                                status = collect_data_source_status(start_date="2025-04-29")

        sources = {item["key"]: item for item in status["sources"]}
        self.assertEqual(status["overall"]["ready_count"], 6)
        self.assertEqual(status["overall"]["experimental_count"], 1)
        self.assertEqual(sources["concept_graph"]["status"], "experimental")
        self.assertTrue(sources["concept_graph"]["experimental"])
        self.assertIn("6/8 可用", status["overall"]["summary"])
        self.assertEqual(sources["history"]["latest_data_date"], "2026-05-11")
        self.assertEqual(sources["history"]["latest_requested_end"], "2026-05-11")
        self.assertEqual(sources["profiles"]["count"], 1)
        self.assertEqual(sources["concepts"]["concept_count"], 1)
        self.assertEqual(sources["board_market"]["count"], 1)
        self.assertEqual(sources["scan_jobs"]["count"], 1)

    def test_history_status_uses_actual_cached_data_date(self):
        with TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            pd.DataFrame({
                "date": ["2026-05-08", "2026-05-11"],
                "open": [10, 11],
                "high": [11, 12],
                "low": [9, 10],
                "close": [10.5, 11.5],
                "volume": [1000, 1200],
            }).to_csv(history_dir / "600063_20250429_20260512_qfq.csv", index=False)

            with patch("stock_analyzer.data_fetcher.CACHE_DIR", history_dir):
                with patch("stock_analyzer.data_fetcher.beijing_now", return_value=datetime(2026, 5, 12, 15, 30)):
                    status = collect_data_source_status(start_date="2025-04-29")

        history = {item["key"]: item for item in status["sources"]}["history"]
        self.assertEqual(history["latest_data_date"], "2026-05-11")
        self.assertEqual(history["latest_requested_end"], "2026-05-12")
        self.assertEqual(history["status"], "warning")
        self.assertTrue(history["current_day_lag"])

    def test_history_status_accepts_stable_history_cache_key(self):
        with TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            pd.DataFrame({
                "date": ["2026-05-08", "2026-05-11"],
                "open": [10, 11],
                "high": [11, 12],
                "low": [9, 10],
                "close": [10.5, 11.5],
                "volume": [1000, 1200],
            }).to_csv(history_dir / "600063_20250429_qfq.csv", index=False)

            with patch("stock_analyzer.data_fetcher.CACHE_DIR", history_dir):
                status = collect_data_source_status(start_date="2025-04-29")

        history = {item["key"]: item for item in status["sources"]}["history"]
        self.assertEqual(history["latest_data_date"], "2026-05-11")
        self.assertEqual(history["latest_requested_end"], "2026-05-11")
        self.assertEqual(history["status"], "ready")

    def test_collect_data_source_status_can_use_short_cache(self):
        with TemporaryDirectory() as tmp_dir:
            cached_payload = {
                "updated_at": "2026-05-11T15:30:00",
                "overall": {"status": "ready"},
                "sources": [{"key": "history", "status": "ready"}],
            }
            with patch("stock_analyzer.data_sources.DATA_SOURCE_STATUS_CACHE_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.data_sources._build_data_source_status", return_value=cached_payload) as build:
                    first = data_sources.collect_data_source_status(
                        start_date="2025-04-29",
                        use_cache=True,
                    )
                    second = data_sources.collect_data_source_status(
                        start_date="2025-04-29",
                        use_cache=True,
                    )

        self.assertEqual(build.call_count, 1)
        self.assertFalse(first["cache_meta"]["hit"])
        self.assertTrue(second["cache_meta"]["hit"])
        self.assertEqual(second["overall"]["status"], "ready")

    def test_append_daily_quote_rejects_cache_gap_without_override(self):
        previous = pd.DataFrame({
            "date": ["2026-09-14"],
            "close": [10.0],
        })
        bar = {
            "date": "2026-09-16",
            "close": 10.5,
        }

        self.assertEqual(
            append_rejection_reason(previous, bar, "20260916"),
            "cache_gap_detected",
        )
        self.assertEqual(
            append_rejection_reason(previous, bar, "20260916", allow_gap=True),
            "",
        )

    def test_append_daily_quote_rejects_large_close_jump(self):
        previous = pd.DataFrame({
            "date": ["2026-09-14"],
            "close": [10.0],
        })
        bar = {
            "date": "2026-09-15",
            "close": 14.0,
        }

        self.assertEqual(
            append_rejection_reason(previous, bar, "20260915", max_close_jump_pct=30),
            "close_jump_exceeds_limit",
        )


if __name__ == "__main__":
    unittest.main()
