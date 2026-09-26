import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from stock_analyzer.intraday_fetcher import (
    _current_day_minute_cache_is_stale,
    write_cached_minute_history,
)


def _minute_frame(last_time):
    return pd.DataFrame({
        "day": [f"2026-09-24 {last_time}"],
        "open": [10.0],
        "high": [10.2],
        "low": [9.9],
        "close": [10.1],
        "volume": [1000],
    })


class IntradayCacheTest(unittest.TestCase):
    @patch("stock_analyzer.intraday_fetcher.beijing_now", return_value=pd.Timestamp("2026-09-24 16:00:00"))
    def test_current_day_morning_only_cache_is_stale_after_close(self, _mock_now):
        self.assertTrue(_current_day_minute_cache_is_stale(_minute_frame("11:30:00"), "20260924"))
        self.assertFalse(_current_day_minute_cache_is_stale(_minute_frame("15:00:00"), "20260924"))

    @patch("stock_analyzer.intraday_fetcher.beijing_now", return_value=pd.Timestamp("2026-09-24 14:30:00"))
    def test_current_day_partial_cache_remains_usable_while_market_is_open(self, _mock_now):
        self.assertFalse(_current_day_minute_cache_is_stale(_minute_frame("11:30:00"), "20260924"))

    @patch("stock_analyzer.intraday_fetcher.beijing_now", return_value=pd.Timestamp("2026-09-24 16:00:00"))
    def test_minute_cache_write_uses_unique_temp_and_atomic_replace(self, _mock_now):
        real_replace = os.replace
        calls = []

        def replace(source, destination):
            calls.append((Path(source), Path(destination)))
            real_replace(source, destination)

        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            with patch("stock_analyzer.intraday_fetcher.MINUTE_CACHE_DIR", cache_dir), patch(
                "stock_analyzer.intraday_fetcher.os.replace",
                side_effect=replace,
            ):
                write_cached_minute_history(
                    "600063",
                    "60",
                    "20250924",
                    "20260924",
                    _minute_frame("15:00:00"),
                )

            destination = cache_dir / "600063_60_20250924_20260924_qfq.csv"
            self.assertTrue(destination.exists())
            self.assertEqual(len(calls), 1)
            self.assertNotEqual(calls[0][0], destination)
            self.assertEqual(calls[0][1], destination)
            self.assertEqual(list(cache_dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
