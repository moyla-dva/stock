import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import app
from stock_analyzer.scan_cache import prune_scan_cache, scan_cache_status
from stock_analyzer.scan_history import list_scan_history
from stock_analyzer.scan_snapshot import build_scan_snapshot, write_scan_snapshot
from stock_analyzer.scan_workspace import collect_scan_workspace


class ScanHistoryTest(unittest.TestCase):
    def _minimal_signal_frame(self, start="2026-04-20", rows=12):
        frame = pd.DataFrame({
            "date": pd.date_range(start, periods=rows, freq="D"),
            "open": [10.0] * rows,
            "high": [10.5] * rows,
            "low": [9.8] * rows,
            "close": [10.0 + i * 0.1 for i in range(rows)],
            "custom": [0.0] * rows,
            "dif": [0.0] * rows,
            "dea": [0.0] * rows,
            "macd_hist": [0.0] * rows,
            "ma20": [10.0] * rows,
            "vwap": [10.0] * rows,
        })
        for column in [
            "is_b_point",
            "is_pullback_b",
            "is_s_point",
            "touch_upper",
            "break_ma5",
            "is_bottom_divergence",
            "is_top_divergence",
            "new_is_b_point",
            "new_is_pullback_b",
            "new_is_s_point",
            "opt_is_b_point",
            "opt_is_pullback_b",
            "opt_is_s_warn",
            "opt_is_s_confirm",
            "opt_is_s_point",
            "composite_entry",
            "composite_risk_warn",
            "composite_exit",
            "composite_risk",
        ]:
            frame[column] = False
        frame["composite_entry_type"] = ""
        frame["composite_risk_type"] = ""
        frame["composite_exit_type"] = ""
        frame["composite_entry_reason"] = ""
        frame["composite_risk_reason"] = ""
        frame["composite_setup_score"] = [2] * rows
        frame["composite_confirm_score"] = [3] * rows
        frame["composite_risk_score"] = [0] * rows
        frame["composite_watch"] = [False] * rows
        frame.loc[rows - 1, "composite_entry"] = True
        frame.loc[rows - 1, "composite_entry_type"] = "pullback"
        frame.loc[rows - 1, "composite_entry_reason"] = "回踩确认"
        return frame

    def test_list_scan_history_groups_snapshot_days(self):
        frame = self._minimal_signal_frame()

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                first = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-01")
                second = build_scan_snapshot("000001", "示例B", frame, snapshot_day="2026-05-02")
                write_scan_snapshot(first, start_date="2025-04-29", snapshot_day="2026-05-01")
                write_scan_snapshot(second, start_date="2025-04-29", snapshot_day="2026-05-02")

                history = list_scan_history(start_date="2025-04-29")
                with patch(
                    "stock_analyzer.scan_history.read_scan_snapshot_file",
                    side_effect=AssertionError("cache miss"),
                ):
                    cached = list_scan_history(start_date="2025-04-29")

        self.assertEqual(history["count"], 2)
        self.assertFalse(history["cache_meta"]["hit"])
        self.assertTrue(cached["cache_meta"]["hit"])
        self.assertEqual(cached["count"], 2)
        self.assertEqual(history["items"][0]["snapshot_day"], "20260502")
        self.assertEqual(history["items"][0]["display_day"], "2026-05-02")
        self.assertEqual(history["items"][0]["pool_counts"]["opportunity"]["count"], 1)
        self.assertEqual(history["items"][1]["snapshot_count"], 1)

    def test_collect_scan_workspace_can_replay_expired_history_day(self):
        frame = self._minimal_signal_frame(start="2026-04-20", rows=12)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-20")):
                        snapshot = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-01")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-01")
                        latest = collect_scan_workspace(start_date="2025-04-29")
                        history = collect_scan_workspace(start_date="2025-04-29", snapshot_day="2026-05-01")

        self.assertEqual(latest["scanned_count"], 0)
        self.assertEqual(latest["snapshot_meta"]["health"], "expired")
        self.assertEqual(history["scanned_count"], 1)
        self.assertTrue(history["history_mode"])
        self.assertEqual(history["history_snapshot_day"], "20260501")
        self.assertEqual(history["snapshot_meta"]["health"], "history")
        self.assertEqual(history["pools"]["opportunity"]["count"], 1)

    def test_history_workspace_compares_selected_day_with_latest(self):
        frame = self._minimal_signal_frame()

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    old_a = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-01")
                    old_b = build_scan_snapshot("000001", "示例B", frame, snapshot_day="2026-05-01")
                    latest_a = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-02")
                    write_scan_snapshot(old_a, start_date="2025-04-29", snapshot_day="2026-05-01")
                    write_scan_snapshot(old_b, start_date="2025-04-29", snapshot_day="2026-05-01")
                    write_scan_snapshot(latest_a, start_date="2025-04-29", snapshot_day="2026-05-02")

                    workspace = collect_scan_workspace(start_date="2025-04-29", snapshot_day="2026-05-01")

        comparison = workspace["pools"]["opportunity"]["history_comparison"]
        self.assertTrue(comparison["reference_available"])
        self.assertEqual(comparison["retained_count"], 1)
        self.assertEqual(comparison["disappeared_count"], 1)
        labels = {item["code"]: item["history_delta"]["label"] for item in workspace["pools"]["opportunity"]["results"]}
        self.assertEqual(labels["000001"], "最新已消失")

    def test_scan_history_api_returns_local_snapshot_days(self):
        frame = self._minimal_signal_frame()

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                snapshot = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-01")
                write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-01")
                response = app.app.test_client().get("/api/scan_history?limit=5")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["items"][0]["snapshot_day"], "20260501")

    def test_scan_cache_status_and_prune_remove_expired_snapshots(self):
        frame = self._minimal_signal_frame(start="2026-04-20", rows=12)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-20")):
                    snapshot = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-01")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-01")
                    before = scan_cache_status(start_date="2025-04-29")
                    pruned = prune_scan_cache(start_date="2025-04-29")
                    after = scan_cache_status(start_date="2025-04-29")

        self.assertEqual(before["stale_count"], 1)
        self.assertEqual(pruned["deleted_count"], 1)
        self.assertEqual(after["file_count"], 0)

    def test_scan_cache_can_prune_obsolete_strategy_snapshots(self):
        frame = self._minimal_signal_frame(start="2026-04-20", rows=12)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    legacy = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-10")
                    legacy.pop("strategy_version", None)
                    legacy.pop("strategy_meta", None)
                    current = build_scan_snapshot("600063", "示例A", frame, snapshot_day="2026-05-11")
                    write_scan_snapshot(legacy, start_date="2025-04-29", snapshot_day="2026-05-10")
                    write_scan_snapshot(current, start_date="2025-04-29", snapshot_day="2026-05-11")

                    before = scan_cache_status(start_date="2025-04-29")
                    default_prune = prune_scan_cache(start_date="2025-04-29")
                    kept = scan_cache_status(start_date="2025-04-29")
                    pruned = prune_scan_cache(
                        start_date="2025-04-29",
                        delete_obsolete_strategy=True,
                    )
                    after = scan_cache_status(start_date="2025-04-29")

        self.assertEqual(before["file_count"], 2)
        self.assertEqual(before["obsolete_strategy_count"], 1)
        self.assertEqual(default_prune["deleted_count"], 0)
        self.assertEqual(kept["file_count"], 2)
        self.assertEqual(pruned["deleted_count"], 1)
        self.assertEqual(pruned["deleted_obsolete_strategy_count"], 1)
        self.assertEqual(after["file_count"], 1)
        self.assertEqual(after["legacy_strategy_count"], 0)


if __name__ == "__main__":
    unittest.main()
