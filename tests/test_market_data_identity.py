import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.data_fetcher import (
    _daily_bar_state,
    _should_write_history_cache,
    beijing_now,
    fetch_stock_history,
    read_cached_history,
    write_cached_history,
)
from stock_analyzer.market_data_identity import (
    attach_market_data_identity,
    frame_market_data_identity,
)
from stock_analyzer.scan_snapshot import build_scan_snapshot
from stock_analyzer.serializers import analysis_frame_to_chart_payload


def _raw_frame(end="2026-09-22", rows=30):
    dates = pd.date_range(end=end, periods=rows, freq="D")
    return pd.DataFrame({
        "date": dates,
        "open": [10 + index * 0.01 for index in range(rows)],
        "high": [10.3 + index * 0.01 for index in range(rows)],
        "low": [9.8 + index * 0.01 for index in range(rows)],
        "close": [10.1 + index * 0.01 for index in range(rows)],
        "volume": [1000 + index for index in range(rows)],
    })


class MarketDataIdentityTest(unittest.TestCase):
    def test_beijing_clock_has_real_eight_hour_offset(self):
        self.assertEqual(beijing_now().utcoffset(), timedelta(hours=8))

    def test_daily_bar_state_rejects_bar_on_confirmed_non_session(self):
        frame = _raw_frame(end="2026-09-25", rows=2)
        with patch(
            "stock_analyzer.data_fetcher.market_calendar_context",
            return_value={"is_session": False},
        ):
            state = _daily_bar_state(
                frame,
                now=pd.Timestamp("2026-09-25 16:00:00"),
            )
            should_write = _should_write_history_cache(
                frame,
                "20260925",
                now=pd.Timestamp("2026-09-25 16:00:00"),
            )

        self.assertEqual(state, "unknown")
        self.assertFalse(should_write)

    def test_daily_bar_state_keeps_preview_for_confirmed_session(self):
        frame = _raw_frame(end="2026-09-22", rows=2)
        with patch(
            "stock_analyzer.data_fetcher.market_calendar_context",
            return_value={"is_session": True},
        ):
            state = _daily_bar_state(
                frame,
                now=pd.Timestamp("2026-09-22 10:30:00"),
            )

        self.assertEqual(state, "preview")

    @patch("stock_analyzer.data_fetcher.fetch_realtime_quote_bar")
    def test_realtime_merge_marks_preview_and_source(self, mock_quote):
        history = _raw_frame(end="2026-09-21", rows=2)
        attach_market_data_identity(history, data_source="tencent_direct")
        provider = Mock()
        provider.fetch_history.return_value = history
        mock_quote.return_value = {
            "date": "2026-09-22",
            "open": 10.2,
            "close": 10.5,
            "high": 10.6,
            "low": 10.1,
            "volume": 1200,
        }

        with patch(
            "stock_analyzer.data_fetcher.beijing_now",
            return_value=pd.Timestamp("2026-09-22 10:30:00"),
        ), patch(
            "stock_analyzer.data_fetcher.market_calendar_context",
            return_value={
                "is_session": True,
                "calendar_id": "XSHG",
                "calendar_revision": "sha256:calendar",
                "calendar_evidence_level": "provider",
            },
        ):
            result = fetch_stock_history(
                "600001",
                start_date="2025-04-29",
                force_refresh=True,
                provider=provider,
            )

        identity = frame_market_data_identity(result)
        self.assertEqual(identity["bar_state"], "preview")
        self.assertEqual(identity["data_source"], "tencent_direct+tencent_realtime")
        self.assertEqual(identity["cache_status"], "realtime_merge")
        self.assertTrue(identity["data_revision"].startswith("sha256:"))
        self.assertEqual(identity["calendar_revision"], "sha256:calendar")
        self.assertEqual(identity["calendar_evidence_level"], "provider")

    def test_cache_metadata_round_trips_market_identity(self):
        frame = _raw_frame(rows=2)
        attach_market_data_identity(
            frame,
            data_source="tencent_via_akshare",
            bar_state="closed",
            generated_at="2026-09-22T16:00:00+08:00",
            cache_status="miss",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                write_cached_history(
                    "600001",
                    "20250429",
                    "20260922",
                    frame,
                    adjust="qfq",
                    stored_at=pd.Timestamp("2026-09-22 16:00:00"),
                )
                cached = read_cached_history(
                    "600001",
                    "20250429",
                    "20260922",
                    adjust="qfq",
                    now=pd.Timestamp("2026-09-22 16:05:00"),
                )
                meta_path = Path(tmp_dir) / "600001_20250429_qfq.csv.meta.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

        identity = frame_market_data_identity(cached)
        self.assertEqual(meta["data_source"], "tencent_via_akshare")
        self.assertEqual(meta["bar_state"], "closed")
        self.assertEqual(identity["data_source"], "tencent_via_akshare")
        self.assertEqual(identity["bar_state"], "closed")
        self.assertEqual(identity["cache_status"], "hit")

    def test_analysis_payload_and_snapshot_preserve_identity(self):
        raw = _raw_frame()
        attach_market_data_identity(
            raw,
            data_source="tencent_direct",
            bar_state="closed",
            generated_at="2026-09-22T16:00:00+08:00",
            cache_status="hit",
            calendar_id="XSHG",
            calendar_revision="sha256:calendar",
            calendar_evidence_level="provider",
        )

        frame = prepare_analysis_frame(raw, fill_initial_ma20=True)
        payload = analysis_frame_to_chart_payload(frame, v2_events=[], facts={})
        snapshot = build_scan_snapshot("600001", "样本A", frame, snapshot_day="2026-09-22")

        identity = payload["data_identity"]
        self.assertEqual(identity["data_source"], "tencent_direct")
        self.assertEqual(identity["bar_state"], "closed")
        self.assertTrue(identity["data_revision"].startswith("sha256:"))
        self.assertEqual(snapshot["data_source"], "tencent_direct")
        self.assertEqual(snapshot["bar_state"], "closed")
        self.assertEqual(snapshot["data_revision"], identity["data_revision"])
        self.assertEqual(snapshot["calendar_id"], "XSHG")
        self.assertEqual(snapshot["calendar_revision"], "sha256:calendar")

    def test_fetch_diagnostics_distinguish_empty_provider_from_provider_error(self):
        class EmptyProvider:
            def fetch_history(self, *args, **kwargs):
                return pd.DataFrame()

        class ErrorProvider:
            def fetch_history(self, *args, **kwargs):
                raise TimeoutError("not retained in diagnostics")

        empty_diagnostics = {}
        error_diagnostics = {}
        fetch_stock_history(
            "600001",
            provider=EmptyProvider(),
            diagnostics=empty_diagnostics,
        )
        fetch_stock_history(
            "600001",
            provider=ErrorProvider(),
            diagnostics=error_diagnostics,
        )

        self.assertEqual(empty_diagnostics["fetch_status"], "provider_empty")
        self.assertEqual(error_diagnostics["fetch_status"], "provider_error")
        self.assertEqual(error_diagnostics["attempts"][0]["error_type"], "TimeoutError")
        self.assertNotIn("not retained in diagnostics", str(error_diagnostics))


if __name__ == "__main__":
    unittest.main()
