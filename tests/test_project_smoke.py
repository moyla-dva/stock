import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pandas as pd

import app
from tests.fixtures import (
    add_legacy_scores,
    add_legacy_signal_columns,
    apply_legacy_entry,
    build_minimal_signal_frame,
    mark_legacy_signals,
)
from stock_analyzer import events as events_module
from stock_analyzer import scan_snapshot as scan_snapshot_module
from stock_analyzer import stock_service
from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.backtest import evaluate_signal_events
from stock_analyzer.c_signal_v2 import (
    build_c_signal_v2_permission,
    build_c_signal_v2_priority,
    build_c_signal_v2_state,
    build_c_signal_v2_state_from_result,
    c_signal_v2_fields,
)
from stock_analyzer.c_signal_v2_contracts import V2_SIGNAL_CONTRACTS, v2_signal_fields
from stock_analyzer.c_signal_v2_facts import (
    build_bear_trap_recovery_facts,
    build_c_signal_v2_event_facts,
    build_c_signal_v2_facts,
    build_exit_gate_facts,
    build_legacy_experience_facts,
    build_macro_tide_facts,
    build_momentum_facts,
    build_normalized_bar_facts,
    build_rectangle_candidate_facts,
    build_rectangle_facts,
    build_target_structure_facts,
    build_trigger_facts,
    build_williams_fractal_facts,
    build_v2_setup_facts,
    _unfilled_gap_targets,
)
from stock_analyzer.catalog import (
    FALLBACK_STOCK_CODES,
    get_cached_stock_profile,
    get_stock_codes,
    refresh_stock_concept_cache,
    get_stock_name,
    get_stock_profile,
)
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.concept_graph import (
    build_concept_graph,
    build_profile_graph_edges,
    concept_graph_status,
    delete_concept_graph_edge,
    read_concept_graph_edges,
    upsert_concept_graph_edge,
)
from stock_analyzer.concept_jobs import ConceptRefreshJobManager
from stock_analyzer.data_fetcher import fetch_stock_history
from stock_analyzer.events import SIGNAL_DEFINITIONS, SignalEvent, build_v2_signal_events
from stock_analyzer.indicators import calculate_bull_bear_power, calculate_macd, calculate_williams_r
from stock_analyzer.intraday_fetcher import fetch_stock_minute_history
from stock_analyzer.legacy_c_signal_adapter import LEGACY_C_SIGNAL_CONTRACTS, legacy_c_signal_fields
from stock_analyzer.market_permission import build_v2_environment_permission
from stock_analyzer.multi_timeframe import build_multi_timeframe_payload, summarize_timeframe
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.providers.concepts import _stock_rows_from_ths_concept_html
from stock_analyzer.providers import tdx_client
from stock_analyzer.providers.stock_history_minute import StockMinuteHistoryProvider, market_symbol_for_sina
from stock_analyzer.providers.stock_history import market_symbol_for_tx
from stock_analyzer.profile_relations import (
    attach_profile_relations,
    build_stock_profile_relations,
    delete_profile_relation_evidence,
    profile_relation_evidence_status,
    read_profile_relation_evidence,
    summarize_profile_relation_groups,
    upsert_profile_relation_evidence,
)
from stock_analyzer.tag_profile import build_stock_tag_profile
from stock_analyzer.scanner import EVENT_WEIGHTS, SCAN_CONFIG, build_v2_latest_scan_event, scan_stock_frame
from stock_analyzer.scan_explainer import build_scan_explanation
from stock_analyzer.scan_overview import build_sector_overview
from stock_analyzer.scan_snapshot import (
    build_scan_snapshot,
    is_recent_snapshot,
    read_latest_scan_snapshot,
    read_scan_snapshot,
    scan_result_from_snapshot,
    write_scan_snapshot,
)
from stock_analyzer.scan_workspace_candidates import filter_workspace_candidates
from stock_analyzer.scan_workspace_index import workspace_pool_index, workspace_pool_page
from stock_analyzer.serializers import analysis_frame_to_chart_payload
from stock_analyzer.signals import add_signal_columns
from stock_analyzer.signal_registry import (
    build_event_weights,
    build_scan_config,
    signal_keys_for_reason,
    signal_labels_for_reason,
)
from stock_analyzer.v2_facts_timeline import (
    V2FactsTimelineCache,
    build_v2_facts_timeline,
    v2_timeline_start_index,
)
from stock_analyzer.v2_analysis_context import build_v2_analysis_context
from scripts import analyze_legacy_experience_ablation


def _valid_history_frame(dates, closes=None, volumes=None):
    dates = list(dates)
    count = len(dates)
    closes = list(closes or [10.0] * count)
    volumes = list(volumes or [1000.0] * count)
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [value + 0.2 for value in closes],
        "low": [value - 0.2 for value in closes],
        "close": closes,
        "volume": volumes,
    })


class ProjectSmokeTest(unittest.TestCase):
    def _minimal_signal_frame(self, rows=10):
        return build_minimal_signal_frame(rows=rows)

    def _strategy_frame(self):
        rows = 8
        frame = pd.DataFrame({
            "open": [10.0] * rows,
            "high": [10.2, 10.4, 10.3, 10.0, 9.8, 9.6, 9.7, 9.8],
            "low": [9.8, 10.0, 9.9, 9.6, 9.3, 9.2, 9.3, 9.4],
            "close": [10.0, 10.2, 10.1, 9.8, 9.5, 9.4, 9.5, 9.6],
            "volume": [1000, 1400, 1000, 1000, 1000, 1000, 1000, 1000],
            "custom": [0.1, 0.3, 0.0, -0.2, -0.4, -0.2, 0.1, 0.1],
            "dif": [0.10, 0.20, 0.18, 0.04, -0.02, -0.05, -0.02, 0.01],
            "dea": [0.05, 0.10, 0.12, 0.05, 0.00, -0.01, -0.01, 0.00],
            "ma5": [9.8, 9.9, 10.0, 10.0, 9.9, 9.8, 9.7, 9.7],
            "ma20": [9.8, 9.9, 10.0, 10.0, 9.95, 9.9, 9.85, 9.8],
            "vwap": [9.9, 10.0, 10.0, 10.0, 9.9, 9.8, 9.75, 9.7],
            "j": [50.0] * rows,
            "trend_ok": [True] * rows,
            "ma20_up": [True] * rows,
            "vol_ma20": [900] * rows,
            "break_ma5": [False, False, False, True, True, True, False, False],
            "touch_upper": [False] * rows,
        })
        return add_legacy_signal_columns(frame)

    def _v2_trigger_frame(self):
        rows = 14
        frame = self._minimal_signal_frame(rows=rows)
        frame["open"] = [10.0, 10.1, 10.2, 10.15, 9.8, 9.2, 9.4, 9.7, 10.0, 9.55, 9.9, 10.1, 10.5, 9.9]
        frame["high"] = [10.1, 10.25, 10.4, 10.5, 10.3, 10.2, 10.3, 10.5, 10.6, 10.55, 10.55, 10.6, 10.7, 10.95]
        frame["low"] = [9.8, 9.7, 9.6, 9.5, 9.3, 9.0, 9.2, 9.4, 9.5, 9.25, 9.45, 10.0, 9.55, 9.85]
        frame["close"] = [10.0, 10.15, 10.25, 10.05, 10.02, 10.0, 10.05, 10.1, 10.35, 10.05, 10.2, 10.35, 10.0, 10.85]
        frame["volume"] = [1000] * 13 + [1800]
        frame["vol_ma20"] = [1000] * rows
        frame["ma20"] = [10.2] * rows
        frame["ma20_up"] = [True] * rows
        frame["trend_ok"] = [True] * rows
        frame["williams_r"] = [70.0] * 13 + [35.0]
        frame["williams_r_cross_bull"] = [False] * 13 + [True]
        add_legacy_scores(frame, setup=0, confirm=0, risk=0, break_score=0, heat_score=0)
        return frame

    def _v2_long_macro_frame(self, *, macro="down"):
        trigger = self._v2_trigger_frame()
        history_rows = 246
        if macro == "down":
            closes = [18.0 - i * 0.025 for i in range(history_rows)]
        else:
            closes = [7.5 + i * 0.014 for i in range(history_rows)]
        history = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=history_rows, freq="D"),
            "open": [value - 0.05 for value in closes],
            "high": [value + 0.25 for value in closes],
            "low": [value - 0.25 for value in closes],
            "close": closes,
            "custom": [0.0] * history_rows,
            "dif": [0.0] * history_rows,
            "dea": [0.0] * history_rows,
            "macd_hist": [0.0] * history_rows,
            "ma20": closes,
            "vwap": closes,
        })
        add_legacy_signal_columns(history)
        trigger = trigger.copy()
        trigger["date"] = pd.date_range(history["date"].iloc[-1] + pd.Timedelta(days=1), periods=len(trigger), freq="D")
        return pd.concat([history, trigger], ignore_index=True)

    def _v2_trigger_frame_with_upper_target(self):
        history_rows = 130
        history = self._minimal_signal_frame(rows=history_rows)
        history["date"] = pd.date_range("2025-01-01", periods=history_rows, freq="D")
        history["open"] = [10.0] * history_rows
        history["high"] = [10.4] * history_rows
        history["low"] = [9.7] * history_rows
        history["close"] = [10.0] * history_rows
        history.loc[40, "high"] = 14.0
        history.loc[40, "close"] = 10.2
        trigger = self._v2_trigger_frame()
        trigger["date"] = pd.date_range(history["date"].iloc[-1] + pd.Timedelta(days=1), periods=len(trigger), freq="D")
        return pd.concat([history, trigger], ignore_index=True)

    def _v2_legacy_entry_frame(self, entry_type="breakout", *, return_pct=2.0, ma20=10.0):
        rows = 25
        frame = self._minimal_signal_frame(rows=rows)
        frame["open"] = [9.95] * rows
        frame["high"] = [10.15] * rows
        frame["low"] = [9.85] * rows
        frame["close"] = [10.0] * rows
        frame["ma20"] = [ma20] * rows
        frame["return_pct"] = [0.0] * rows
        frame["volume_ratio"] = [1.5] * rows
        if entry_type == "pullback":
            frame.loc[rows - 8, "high"] = 10.6
            frame.loc[rows - 1, ["open", "high", "low", "close"]] = [10.0, 10.4, 9.9, 10.35]
        else:
            frame.loc[rows - 1, ["open", "high", "low", "close"]] = [10.05, 10.7, 10.0, 10.6]
        frame.loc[rows - 1, "return_pct"] = return_pct
        return frame

    def _v2_divergence_frame(self, rows=24, *, repair=False):
        frame = self._minimal_signal_frame(rows=rows)
        lows = [10.0] * (rows - 5) + [10.0, 9.9, 9.7, 9.75, 9.6]
        frame["low"] = lows
        frame["close"] = [value + 0.1 for value in lows]
        frame["high"] = [value + 0.3 for value in lows]
        frame["open"] = [value + 0.15 for value in lows]
        if repair:
            frame["macd_hist"] = [0.0] * (rows - 5) + [0.0, -0.2, -0.4, -0.15, -0.1]
        else:
            frame["macd_hist"] = [0.0] * (rows - 5) + [0.0, -0.2, -0.4, -0.1, -0.2]
        return frame

    def _v2_entry_frames(self, rows=25):
        frame = self._minimal_signal_frame(rows=rows)
        frame["open"] = [9.95] * rows
        frame["high"] = [10.15] * rows
        frame["low"] = [9.85] * rows
        frame["close"] = [10.0] * rows
        frame["ma20"] = [10.0] * rows
        return frame

    def _v2_entry_then_crash_frame(self, rows=25):
        frame = self._v2_entry_frames(rows=rows)
        frame.loc[rows - 3, ["open", "high", "low", "close"]] = [10.05, 10.7, 10.0, 10.6]
        frame.loc[rows - 2, ["open", "high", "low", "close"]] = [10.4, 10.4, 9.7, 9.8]
        frame.loc[rows - 1, ["open", "high", "low", "close"]] = [9.7, 9.8, 8.8, 9.0]
        return frame

    def _v2_entry_then_rally_frame(self, rows=24):
        frame = self._v2_entry_frames(rows=rows)
        frame.loc[rows - 4, ["open", "high", "low", "close"]] = [10.0, 10.7, 9.95, 10.6]
        frame.loc[rows - 3, ["open", "high", "low", "close"]] = [10.6, 12.5, 10.5, 11.0]
        frame.loc[rows - 2, ["open", "high", "low", "close"]] = [11.0, 12.5, 10.9, 11.5]
        frame.loc[rows - 1, ["open", "high", "low", "close"]] = [11.6, 12.4, 11.5, 11.8]
        return frame

    def test_normalize_code_accepts_common_stock_formats(self):
        self.assertEqual(normalize_code("600063"), "600063")
        self.assertEqual(normalize_code("sh600063"), "600063")
        self.assertEqual(normalize_code("600063.SH"), "600063")
        self.assertIsNone(normalize_code("abc"))
        self.assertIs(app.normalize_code, normalize_code)

    def test_index_uses_local_echarts_bundle(self):
        client = app.app.test_client()

        index_response = client.get("/")
        html = index_response.get_data(as_text=True)
        vendor_response = client.get("/static/vendor/echarts.min.js")
        vendor_head = vendor_response.data[:500]
        vendor_response.close()

        self.assertEqual(index_response.status_code, 200)
        self.assertIn("/static/vendor/echarts.min.js", html)
        self.assertNotIn("cdn.jsdelivr", html)
        self.assertEqual(vendor_response.status_code, 200)
        self.assertIn(b"Apache Software Foundation", vendor_head)

    def test_indicator_module_calculates_macd_shape(self):
        df = pd.DataFrame({"close": [10.0, 10.5, 10.2, 10.8, 11.0]})

        dif, dea, macd_hist = calculate_macd(df)

        self.assertEqual(len(dif), len(df))
        self.assertEqual(len(dea), len(df))
        self.assertEqual(len(macd_hist), len(df))

    def test_normalizer_canonicalizes_chinese_ohlcv_columns(self):
        df = pd.DataFrame({
            "日期": ["2026-01-03", "2026-01-02"],
            "开盘": [10.0, 9.8],
            "最高": [10.5, 10.1],
            "最低": [9.9, 9.7],
            "收盘": [10.2, 10.0],
            "成交量": [1000, 900],
            "其他": ["ignored", "ignored"],
        })

        result = normalize_price_frame(df)

        self.assertEqual(list(result.columns), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(result["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-01-02", "2026-01-03"])

    def test_normalizer_does_not_guess_amount_is_volume(self):
        frame = pd.DataFrame({
            "date": ["2026-09-24"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.8],
            "close": [10.1],
            "amount": [100000.0],
        })

        with self.assertRaisesRegex(ValueError, "volume"):
            normalize_price_frame(frame)

    def test_normalizer_drops_rows_with_unknown_volume_instead_of_fabricating_zero(self):
        frame = _valid_history_frame(
            ["2026-09-23", "2026-09-24"],
            closes=[10.0, 10.1],
            volumes=[None, 1200],
        )

        result = normalize_price_frame(frame)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["volume"], 1200)

    def test_tencent_volume_contract_uses_security_specific_share_units(self):
        from stock_analyzer.providers.stock_history import tencent_volume_to_shares

        self.assertEqual(tencent_volume_to_shares("600000", 12), 1200)
        self.assertEqual(tencent_volume_to_shares("300200", 12), 1200)
        self.assertEqual(tencent_volume_to_shares("920046", 12), 1200)
        self.assertEqual(tencent_volume_to_shares("688001", 12), 12)
        self.assertEqual(tencent_volume_to_shares("000001", 12), 12)

    @patch("stock_analyzer.providers.stock_history.requests.get")
    def test_tencent_direct_history_returns_volume_in_shares(self, mock_get):
        from stock_analyzer.providers.stock_history import _fetch_tx_history_direct

        response = Mock()
        response.text = (
            'kline_day2026={"data":{"sh600000":{"day":'
            '[["2026-09-24","10","10.5","10.8","9.9","12"]]}}}'
        )
        mock_get.return_value = response

        result = _fetch_tx_history_direct("sh600000", "20260924", "20260924")

        self.assertEqual(list(result.columns), ["date", "open", "close", "high", "low", "volume"])
        self.assertEqual(float(result.iloc[0]["volume"]), 1200.0)

    @patch("stock_analyzer.providers.stock_history._fetch_tx_history_direct")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_partial_direct_history_merges_instead_of_replacing_akshare_range(
        self,
        mock_akshare,
        mock_direct,
    ):
        from stock_analyzer.providers.stock_history import StockHistoryProvider

        mock_akshare.return_value = pd.DataFrame({
            "日期": ["2026-09-22", "2026-09-23"],
            "开盘": [10.0, 10.2],
            "最高": [10.4, 10.5],
            "最低": [9.9, 10.1],
            "收盘": [10.2, 10.3],
            "成交量": [1000, 1100],
        })
        mock_direct.return_value = pd.DataFrame({
            "date": [pd.Timestamp("2026-09-23").date(), pd.Timestamp("2026-09-24").date()],
            "open": [10.3, 10.4],
            "high": [10.6, 10.8],
            "low": [10.2, 10.3],
            "close": [10.5, 10.7],
            "volume": [1200, 1300],
        })

        frame, _ = StockHistoryProvider().fetch_history_with_diagnostics(
            "600001", "20260922", "20260924"
        )

        self.assertEqual(frame["date"].dt.strftime("%Y-%m-%d").tolist(), [
            "2026-09-22", "2026-09-23", "2026-09-24",
        ])
        self.assertEqual(frame["close"].tolist(), [10.2, 10.5, 10.7])
        self.assertEqual(
            frame.attrs["market_data_identity"]["data_source"],
            "tencent_via_akshare+tencent_direct",
        )

    def test_stale_history_cache_checks_older_candidates_and_reports_result(self):
        from stock_analyzer.data_fetcher import read_cached_history

        canonical = Path("/tmp/canonical-history.csv")
        legacy = Path("/tmp/legacy-history.csv")
        frame = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1000])
        with (
            patch("stock_analyzer.data_fetcher._cached_history_candidates", return_value=[canonical, legacy]),
            patch("stock_analyzer.data_fetcher.cache_path_for_history", return_value=canonical),
            patch("stock_analyzer.data_fetcher.read_history_cache_file", return_value=(frame, {})) as read_cache,
            patch("stock_analyzer.data_fetcher._current_day_cache_is_stale", side_effect=[True, False]),
            patch("stock_analyzer.data_fetcher.market_calendar_context", return_value={"is_session": True}),
            patch("stock_analyzer.data_fetcher.write_cached_history", return_value=True),
        ):
            diagnostics = {}
            result = read_cached_history(
                "600001", "20250429", "20260511", now=pd.Timestamp("2026-05-11 16:00:00"),
                diagnostics=diagnostics,
            )

        self.assertIsNotNone(result)
        self.assertEqual(read_cache.call_count, 2)
        self.assertEqual(diagnostics["cache_status"], "hit")

        stale_diagnostics = {}
        with (
            patch("stock_analyzer.data_fetcher._cached_history_candidates", return_value=[canonical]),
            patch("stock_analyzer.data_fetcher.cache_path_for_history", return_value=canonical),
            patch("stock_analyzer.data_fetcher.read_history_cache_file", return_value=(frame, {})),
            patch("stock_analyzer.data_fetcher._current_day_cache_is_stale", return_value=True),
            patch("stock_analyzer.data_fetcher.market_calendar_context", return_value={"is_session": True}),
        ):
            stale_result = read_cached_history(
                "600001", "20250429", "20260511", now=pd.Timestamp("2026-05-11 16:00:00"),
                diagnostics=stale_diagnostics,
            )

        self.assertIsNone(stale_result)
        self.assertEqual(stale_diagnostics["cache_status"], "stale")

    def test_tencent_realtime_quote_returns_volume_in_shares(self):
        from stock_analyzer.providers.stock_quote import bar_from_quote_fields

        fields = [""] * 39
        fields[2] = "600000"
        fields[3] = "10.5"
        fields[5] = "10.0"
        fields[6] = "12"
        fields[30] = "20260924"
        fields[33] = "10.8"
        fields[34] = "9.9"
        fields[37] = "120"
        fields[38] = "0.5"

        bar = bar_from_quote_fields(fields, target_date_text="20260924")

        self.assertEqual(bar["volume"], 1200)

    def test_realtime_merge_preserves_history_and_share_volume(self):
        from stock_analyzer.data_fetcher import _canonical_history_frame
        from stock_analyzer.providers.stock_quote import merge_quote_bar

        history = pd.DataFrame({
            "date": ["2026-09-23"],
            "open": [10.0],
            "close": [10.2],
            "high": [10.4],
            "low": [9.9],
            "volume": [12300],
        })
        quote = {
            "date": "2026-09-24",
            "open": 10.2,
            "close": 10.5,
            "high": 10.8,
            "low": 10.1,
            "volume": 45600,
        }

        result = normalize_price_frame(merge_quote_bar(_canonical_history_frame(history), quote))

        self.assertEqual(result["volume"].tolist(), [12300, 45600])

    def test_legacy_tencent_cache_volume_is_migrated_to_shares(self):
        from stock_analyzer.data_fetcher import cache_path_for_history, read_cached_history

        legacy = pd.DataFrame({
            "date": ["2026-09-23", "2026-09-24"],
            "open": [10.0, 10.2],
            "high": [10.4, 10.8],
            "low": [9.9, 10.1],
            "close": [10.2, 10.5],
            "amount": [123, 0],
            "volume": [None, 12],
        })
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)), patch(
                "stock_analyzer.data_fetcher.market_calendar_context",
                return_value={"is_session": True, "calendar_id": "XSHG"},
            ):
                path = cache_path_for_history("600000", "20260923", "20260924")
                legacy.to_csv(path, index=False)
                path.with_suffix(path.suffix + ".meta.json").write_text(
                    json.dumps({"data_source": "tencent_direct+tencent_realtime"}),
                    encoding="utf-8",
                )
                result = read_cached_history("600000", "20260923", "20260924")

        self.assertEqual(result["volume"].tolist(), [12300, 1200])

    def test_normalizer_accepts_intraday_time_columns(self):
        df = pd.DataFrame({
            "时间": ["2026-05-10 10:30:00", "2026-05-10 09:30:00"],
            "开盘": [10.1, 10.0],
            "最高": [10.3, 10.2],
            "最低": [9.9, 9.8],
            "收盘": [10.2, 10.1],
            "成交量": [1200, 1100],
        })

        result = normalize_price_frame(df)

        self.assertEqual(list(result.columns), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(
            result["date"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
            ["2026-05-10 09:30:00", "2026-05-10 10:30:00"],
        )

    def test_normalizer_accepts_sina_intraday_day_columns(self):
        df = pd.DataFrame({
            "day": ["2026-05-10 10:30:00", "2026-05-10 09:30:00"],
            "open": [10.1, 10.0],
            "high": [10.3, 10.2],
            "low": [9.9, 9.8],
            "close": [10.2, 10.1],
            "volume": [1200, 1100],
        })

        result = normalize_price_frame(df)

        self.assertEqual(list(result.columns), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(
            result["date"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist(),
            ["2026-05-10 09:30:00", "2026-05-10 10:30:00"],
        )

    @patch("stock_analyzer.data_fetcher.date_range_for_recent_days")
    @patch("stock_analyzer.providers.stock_history._fetch_tx_history_direct")
    @patch("stock_analyzer.providers.stock_history.fetch_tdx_daily_bars")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_falls_back_to_secondary_provider(self, mock_tx, mock_tdx, mock_direct_tx, mock_dates):
        mock_dates.return_value = (
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-01-31"),
        )
        mock_tx.return_value = pd.DataFrame()
        mock_direct_tx.return_value = pd.DataFrame()
        expected = pd.DataFrame({"date": ["2026-01-02"]})
        mock_tdx.return_value = expected

        result = fetch_stock_history("600063")

        self.assertIs(result, expected)
        mock_tx.assert_called_once()
        mock_tdx.assert_called_once_with(
            "600063",
            "20260101",
            "20260131",
            logger=None,
            verbose=False,
        )

    @patch("stock_analyzer.data_fetcher.beijing_now")
    @patch("stock_analyzer.providers.stock_history._fetch_tx_history_direct")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_accepts_fixed_start_date(self, mock_tx, mock_direct_tx, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-10")
        expected = pd.DataFrame({"日期": ["2025-04-29"]})
        mock_tx.return_value = expected
        mock_direct_tx.return_value = pd.DataFrame()

        result = fetch_stock_history("600063", start_date="2025-04-29")

        self.assertIs(result, expected)
        mock_tx.assert_called_once_with(
            symbol="sh600063",
            start_date="20250429",
            end_date="20260510",
            adjust="",
            timeout=15.0,
        )

    @patch("stock_analyzer.data_fetcher.beijing_now")
    @patch("stock_analyzer.providers.stock_history._fetch_tx_history_direct")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_uses_beijing_tencent_symbol(
        self,
        mock_tx,
        mock_direct_tx,
        mock_now,
    ):
        mock_now.return_value = pd.Timestamp("2026-05-10")
        mock_tx.side_effect = KeyError("day")
        expected = _valid_history_frame(["2026-05-08"], closes=[10.5], volumes=[1000.0])
        mock_direct_tx.return_value = expected

        result = fetch_stock_history("920046", start_date="2025-04-29")

        self.assertIs(result, expected)
        self.assertEqual(market_symbol_for_tx("920046"), "bj920046")
        mock_tx.assert_called_once_with(
            symbol="bj920046",
            start_date="20250429",
            end_date="20260510",
            adjust="",
            timeout=15.0,
        )
        mock_direct_tx.assert_called_once_with(
            "bj920046",
            "20250429",
            "20260510",
            adjust="",
            logger=None,
            verbose=False,
        )

    @patch("stock_analyzer.data_fetcher.beijing_now")
    @patch("stock_analyzer.providers.stock_history._fetch_tx_history_direct")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_uses_local_cache_when_enabled(self, mock_tx, mock_direct_tx, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-10")
        expected = pd.DataFrame({
            "日期": ["2025-04-29"],
            "开盘": [9.8],
            "最高": [10.2],
            "最低": [9.7],
            "收盘": [10.0],
            "成交量": [1000],
        })
        mock_tx.return_value = expected
        mock_direct_tx.return_value = pd.DataFrame()

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                first = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)
                second = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)

        self.assertEqual(mock_tx.call_count, 1)
        pd.testing.assert_frame_equal(first, expected)
        self.assertEqual(second["volume"].tolist(), [1000])

    @patch("stock_analyzer.data_fetcher.fetch_realtime_quote_bar")
    def test_fetch_stock_history_force_refresh_merges_quote_without_persisting_intraday_bar(self, mock_quote):
        from stock_analyzer.data_fetcher import cache_path_for_history

        cached = _valid_history_frame(["2026-05-08"], closes=[6.71], volumes=[12300])
        history = _valid_history_frame(["2026-05-08"], closes=[6.71], volumes=[12300])
        quote_bar = {
            "date": "2026-05-11",
            "open": 6.80,
            "close": 6.88,
            "high": 6.90,
            "low": 6.76,
            "volume": 1200,
        }
        provider = Mock()
        provider.fetch_history.return_value = history
        mock_quote.return_value = quote_bar

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                path = cache_path_for_history("600063", "20250429", "20260511", adjust="qfq")
                path.parent.mkdir(parents=True, exist_ok=True)
                cached.to_csv(path, index=False)
                with patch(
                    "stock_analyzer.data_fetcher.date_range_for_fetch",
                    return_value=(pd.Timestamp("2025-04-29"), pd.Timestamp("2026-05-11")),
                ):
                    with patch("stock_analyzer.data_fetcher.beijing_now", return_value=pd.Timestamp("2026-05-11 10:30:00")):
                        result = fetch_stock_history(
                            "600063",
                            start_date="2025-04-29",
                            adjust="qfq",
                            use_cache=True,
                            force_refresh=True,
                            provider=provider,
                        )
                stored = pd.read_csv(path)

        provider.fetch_history.assert_called_once()
        mock_quote.assert_called_once_with("600063", target_date_text="20260511", logger=None)
        self.assertEqual(
            pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d").tolist(),
            ["2026-05-08", "2026-05-11"],
        )
        self.assertEqual(float(result.iloc[-1]["close"]), 6.88)
        pd.testing.assert_frame_equal(stored, cached)

    def test_fetch_stock_history_migrates_legacy_daily_cache_to_stable_key(self):
        from stock_analyzer.data_fetcher import cache_path_for_history, legacy_cache_path_for_history

        expected = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1000])
        provider = Mock()

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                legacy_path = legacy_cache_path_for_history("600063", "20250429", "20260511", adjust="qfq")
                legacy_path.parent.mkdir(parents=True, exist_ok=True)
                expected.to_csv(legacy_path, index=False)
                with patch(
                    "stock_analyzer.data_fetcher.date_range_for_fetch",
                    return_value=(pd.Timestamp("2025-04-29"), pd.Timestamp("2026-05-11")),
                ):
                    with patch("stock_analyzer.data_fetcher.beijing_now", return_value=pd.Timestamp("2026-05-11 16:00:00")):
                        result = fetch_stock_history(
                            "600063",
                            start_date="2025-04-29",
                            adjust="qfq",
                            use_cache=True,
                            provider=provider,
                        )
                stable_path = cache_path_for_history("600063", "20250429", "20260511", adjust="qfq")
                stable_exists = stable_path.exists()
                stable_name = stable_path.name

        provider.fetch_history.assert_not_called()
        self.assertTrue(stable_exists)
        self.assertEqual(stable_name, "600063_20250429_qfq.csv")
        self.assertEqual(result["volume"].tolist(), [1000])
        self.assertEqual(pd.to_datetime(result.iloc[0]["date"]).strftime("%Y-%m-%d"), "2026-05-11")

    def test_fetch_stock_history_reuses_stable_cache_across_requested_end_dates(self):
        first_frame = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1000])
        provider = Mock()
        provider.fetch_history.return_value = first_frame

        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", cache_dir):
                with patch("stock_analyzer.data_fetcher.date_range_for_fetch") as mock_range:
                    mock_range.side_effect = [
                        (pd.Timestamp("2025-04-29"), pd.Timestamp("2026-05-11")),
                        (pd.Timestamp("2025-04-29"), pd.Timestamp("2026-05-12")),
                    ]
                    with patch("stock_analyzer.data_fetcher.beijing_now") as mock_now:
                        mock_now.side_effect = [
                            pd.Timestamp("2026-05-11 16:00:00"),
                            pd.Timestamp("2026-05-12 10:00:00"),
                        ]
                        first = fetch_stock_history("600063", start_date="2025-04-29", adjust="qfq", use_cache=True, provider=provider)
                        second = fetch_stock_history("600063", start_date="2025-04-29", adjust="qfq", use_cache=True, provider=provider)
                csv_files = sorted(path.name for path in cache_dir.glob("*.csv"))

        self.assertEqual(provider.fetch_history.call_count, 1)
        self.assertEqual(csv_files, ["600063_20250429_qfq.csv"])
        self.assertEqual(first["volume"].tolist(), [1000])
        self.assertEqual(second["volume"].tolist(), [1000])
        self.assertEqual(pd.to_datetime(first["date"]).tolist(), pd.to_datetime(second["date"]).tolist())

    @patch("stock_analyzer.data_fetcher.beijing_now")
    @patch("stock_analyzer.providers.stock_history._fetch_tx_history_direct")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_refreshes_stale_current_day_cache(self, mock_tx, mock_direct_tx, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-11 16:00:00")
        stale = _valid_history_frame(["2026-05-08"], closes=[6.71], volumes=[1000])
        fresh = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1200])
        mock_tx.return_value = stale
        mock_direct_tx.return_value = fresh

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                first = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)
                second = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)

        self.assertEqual(mock_tx.call_count, 1)
        self.assertEqual(mock_direct_tx.call_count, 1)
        self.assertEqual(first["volume"].tolist(), [1000, 1200])
        self.assertEqual(second["volume"].tolist(), [1000, 1200])

    def test_fetch_stock_history_refreshes_intraday_current_day_cache_after_close(self):
        morning_snapshot = _valid_history_frame(["2026-05-11"], closes=[6.70], volumes=[1000])
        closing_snapshot = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1200])
        provider = Mock()
        provider.fetch_history.side_effect = [morning_snapshot, closing_snapshot]

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                with patch(
                    "stock_analyzer.data_fetcher.date_range_for_fetch",
                    return_value=(pd.Timestamp("2025-04-29"), pd.Timestamp("2026-05-11")),
                ):
                    with patch("stock_analyzer.data_fetcher.beijing_now") as mock_now:
                        mock_now.side_effect = [
                            pd.Timestamp("2026-05-11 10:00:00"),
                            pd.Timestamp("2026-05-11 16:00:00"),
                            pd.Timestamp("2026-05-11 16:00:00"),
                        ]
                        first = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True, provider=provider)
                        second = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True, provider=provider)

        self.assertEqual(provider.fetch_history.call_count, 2)
        self.assertEqual(first["close"].tolist(), [6.70])
        self.assertEqual(second["close"].tolist(), [6.76])

    @patch("stock_analyzer.data_fetcher.beijing_now", return_value=pd.Timestamp("2026-05-11 16:00:00"))
    def test_write_cached_history_is_atomic_and_writes_metadata(self, _mock_now):
        from stock_analyzer.data_fetcher import cache_path_for_history, write_cached_history

        frame = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1000])
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                write_cached_history("600063", "20250429", "20260511", frame, adjust="qfq")
                path = cache_path_for_history("600063", "20250429", "20260511", adjust="qfq")
                tmp_files = list(Path(tmp_dir).glob("*.tmp"))
                meta_path = path.with_suffix(path.suffix + ".meta.json")

                cached = pd.read_csv(path)
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

        self.assertEqual(tmp_files, [])
        self.assertEqual(meta["latest_date"], "20260511")
        self.assertEqual(meta["stored_at"], "2026-05-11T16:00:00")
        self.assertEqual(meta["volume_unit"], "shares")
        self.assertTrue(meta["cache_payload_revision"].startswith("sha256:"))
        self.assertEqual(list(cached.columns), ["date", "open", "high", "low", "close", "volume"])
        pd.testing.assert_frame_equal(cached, frame)

    def test_history_cache_rejects_csv_and_metadata_revision_mismatch(self):
        from stock_analyzer.data_fetcher import cache_path_for_history, read_cached_history, write_cached_history

        frame = _valid_history_frame(["2026-05-11"], closes=[6.76], volumes=[1000])
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                write_cached_history("600063", "20250429", "20260511", frame, adjust="qfq")
                path = cache_path_for_history("600063", "20250429", "20260511", adjust="qfq")
                changed = frame.copy()
                changed.loc[0, "close"] = 6.81
                changed.to_csv(path, index=False)
                diagnostics = {}
                cached = read_cached_history(
                    "600063",
                    "20250429",
                    "20260511",
                    adjust="qfq",
                    diagnostics=diagnostics,
                )

        self.assertIsNone(cached)
        self.assertEqual(diagnostics["cache_status"], "read_error")

    def test_incomplete_history_is_not_written_to_cache(self):
        from stock_analyzer.data_fetcher import (
            _should_write_history_cache,
            cache_path_for_history,
            write_cached_history,
        )

        incomplete = pd.DataFrame({
            "date": ["2026-09-24"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.8],
            "close": [10.1],
            "volume": [None],
        })
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                written = write_cached_history(
                    "600000", "20260901", "20260924", incomplete
                )
                path = cache_path_for_history("600000", "20260901", "20260924")

        self.assertFalse(written)
        self.assertFalse(path.exists())
        self.assertFalse(_should_write_history_cache(incomplete, "20260924"))

    def test_tdx_daily_and_minute_bars_advance_paging_offset(self):
        def bars(start, count, prefix):
            return [
                {
                    "datetime": f"2026-05-{(idx % 28) + 1:02d} 10:00:00" if prefix == "minute" else f"2026-05-{(idx % 28) + 1:02d}",
                    "open": 10.0,
                    "close": 10.1,
                    "high": 10.2,
                    "low": 9.9,
                    "vol": 1000 + start + idx,
                }
                for idx in range(count)
            ]

        class FakeTdxApi:
            def __init__(self):
                self.calls = []

            def get_security_bars(self, category, market, code, offset, count):
                self.calls.append((category, market, code, offset, count))
                if offset == 0:
                    return bars(offset, 700, "daily")
                if offset == 700:
                    return bars(offset, 2, "daily")
                return []

        daily_api = FakeTdxApi()
        with patch("stock_analyzer.providers.tdx_client._connect", return_value=daily_api):
            daily = tdx_client.fetch_tdx_daily_bars("600063", "20200101", "20261231")

        minute_api = FakeTdxApi()
        with patch("stock_analyzer.providers.tdx_client._connect", return_value=minute_api):
            minute = tdx_client.fetch_tdx_minute_bars("600063", "2020-01-01 00:00:00", "2026-12-31 23:59:59", period="60")

        self.assertIsNotNone(daily)
        self.assertIsNotNone(minute)
        self.assertEqual([call[3] for call in daily_api.calls[:2]], [0, 700])
        self.assertEqual([call[3] for call in minute_api.calls[:2]], [0, 700])

    @patch("stock_analyzer.intraday_fetcher.beijing_now")
    def test_fetch_stock_minute_history_refreshes_stale_current_day_cache(self, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-26 16:00:00")
        stale = pd.DataFrame({
            "day": ["2026-05-25 15:00:00"],
            "open": [6.63],
            "high": [6.72],
            "low": [6.61],
            "close": [6.67],
            "volume": [21073300],
        })
        fresh = pd.DataFrame({
            "day": ["2026-05-26 15:00:00"],
            "open": [6.50],
            "high": [6.57],
            "low": [6.48],
            "close": [6.55],
            "volume": [5892579],
        })
        provider = Mock()
        provider.fetch_history.return_value = fresh

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.intraday_fetcher.MINUTE_CACHE_DIR", Path(tmp_dir)):
                stale.to_csv(Path(tmp_dir) / "600063_60_20250526_20260526_qfq.csv", index=False)
                result = fetch_stock_minute_history(
                    "600063",
                    period="60",
                    days=365,
                    adjust="qfq",
                    use_cache=True,
                    provider=provider,
                )

        provider.fetch_history.assert_called_once()
        pd.testing.assert_frame_equal(result, fresh)

    @patch("stock_analyzer.intraday_fetcher.beijing_now")
    def test_fetch_stock_minute_history_cache_only_skips_provider_when_stale(self, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-26 16:00:00")
        stale = pd.DataFrame({
            "day": ["2026-05-25 15:00:00"],
            "open": [6.63],
            "high": [6.72],
            "low": [6.61],
            "close": [6.67],
            "volume": [21073300],
        })
        provider = Mock()

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.intraday_fetcher.MINUTE_CACHE_DIR", Path(tmp_dir)):
                stale.to_csv(Path(tmp_dir) / "600063_60_20250526_20260526_qfq.csv", index=False)
                result = fetch_stock_minute_history(
                    "600063",
                    period="60",
                    days=365,
                    adjust="qfq",
                    use_cache=True,
                    cache_only=True,
                    provider=provider,
                )

        provider.fetch_history.assert_not_called()
        self.assertIsNone(result)

    @patch("stock_analyzer.intraday_fetcher.beijing_now")
    def test_fetch_stock_minute_history_does_not_cache_current_day_without_ohlc(self, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-26 16:00:00")
        invalid_current_day = pd.DataFrame({
            "day": ["2026-05-26 15:00:00"],
            "open": [None],
            "high": [None],
            "low": [None],
            "close": [None],
            "volume": [5892579],
        })
        fresh = pd.DataFrame({
            "day": ["2026-05-26 15:00:00"],
            "open": [6.50],
            "high": [6.57],
            "low": [6.48],
            "close": [6.55],
            "volume": [5892579],
        })
        provider = Mock()
        provider.fetch_history.side_effect = [invalid_current_day, fresh]

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.intraday_fetcher.MINUTE_CACHE_DIR", Path(tmp_dir)):
                first = fetch_stock_minute_history(
                    "600063",
                    period="60",
                    days=365,
                    adjust="qfq",
                    use_cache=True,
                    provider=provider,
                )
                second = fetch_stock_minute_history(
                    "600063",
                    period="60",
                    days=365,
                    adjust="qfq",
                    use_cache=True,
                    provider=provider,
                )

        self.assertEqual(provider.fetch_history.call_count, 2)
        pd.testing.assert_frame_equal(first, invalid_current_day)
        pd.testing.assert_frame_equal(second, fresh)

    @patch("stock_analyzer.providers.stock_history_minute.fetch_tdx_minute_bars")
    @patch("stock_analyzer.providers.stock_history_minute.ak.stock_zh_a_minute")
    def test_stock_minute_provider_uses_sina_primary(self, mock_sina, mock_tdx):
        mock_sina.return_value = pd.DataFrame({
            "day": ["2026-05-09 15:00:00", "2026-05-10 10:30:00", "2026-05-10 15:00:00"],
            "open": [9.9, 10.0, 10.2],
            "high": [10.0, 10.3, 10.4],
            "low": [9.8, 9.9, 10.1],
            "close": [9.95, 10.2, 10.3],
            "volume": [900, 1000, 1100],
        })

        result = StockMinuteHistoryProvider().fetch_history(
            "600063",
            "2026-05-10 09:30:00",
            "2026-05-10 15:00:00",
            period="60",
            adjust="qfq",
        )

        self.assertEqual(market_symbol_for_sina("600063"), "sh600063")
        mock_sina.assert_called_once_with(symbol="sh600063", period="60", adjust="qfq")
        mock_tdx.assert_not_called()
        self.assertEqual(result["day"].tolist(), ["2026-05-10 10:30:00", "2026-05-10 15:00:00"])

    @patch("stock_analyzer.providers.stock_history_minute.fetch_tdx_minute_bars")
    @patch("stock_analyzer.providers.stock_history_minute.ak.stock_zh_a_minute")
    def test_stock_minute_provider_falls_back_to_tdx(self, mock_sina, mock_tdx):
        mock_sina.return_value = pd.DataFrame()
        expected = pd.DataFrame({
            "day": ["2026-05-10 10:30:00"],
            "open": [10.0],
            "high": [10.3],
            "low": [9.9],
            "close": [10.2],
            "volume": [1000],
        })
        mock_tdx.return_value = expected

        result = StockMinuteHistoryProvider().fetch_history(
            "600063",
            "2026-05-10 09:30:00",
            "2026-05-10 15:00:00",
            period="60",
            adjust="",
        )

        self.assertIs(result, expected)
        mock_tdx.assert_called_once_with(
            "600063",
            "2026-05-10 09:30:00",
            "2026-05-10 15:00:00",
            period="60",
            logger=None,
            verbose=False,
        )

    @patch("stock_analyzer.providers.stock_history_minute.fetch_tdx_minute_bars")
    @patch("stock_analyzer.providers.stock_history_minute.ak.stock_zh_a_minute")
    def test_stock_minute_provider_skips_tdx_for_adjusted_requests(self, mock_sina, mock_tdx):
        mock_sina.return_value = pd.DataFrame()

        result = StockMinuteHistoryProvider().fetch_history(
            "600063",
            "2026-05-10 09:30:00",
            "2026-05-10 15:00:00",
            period="60",
            adjust="qfq",
        )

        self.assertIsNone(result)
        mock_tdx.assert_not_called()

    @patch("stock_analyzer.providers.catalog.ak.stock_profile_cninfo")
    def test_catalog_get_stock_name_reads_display_name(self, mock_cninfo):
        mock_cninfo.return_value = pd.DataFrame({
            "A股代码": ["600063"],
            "A股简称": ["示例股票"],
            "所属行业": ["化学原料"],
        })

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                self.assertEqual(get_stock_name("sh600063"), "示例股票")
        mock_cninfo.assert_called_once_with(symbol="600063")

    @patch("stock_analyzer.providers.catalog.ak.stock_profile_cninfo")
    def test_catalog_get_stock_profile_reads_sector_and_caches(self, mock_cninfo):
        mock_cninfo.return_value = pd.DataFrame({
            "A股代码": ["600063"],
            "A股简称": ["示例股票"],
            "所属行业": ["半导体"],
            "所属概念": ["AI芯片, 算力"],
        })

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                first = get_stock_profile("600063")
                second = get_stock_profile("600063")
                cached = get_cached_stock_profile("600063")

        self.assertEqual(first["name"], "示例股票")
        self.assertEqual(first["sector"], "半导体")
        self.assertEqual(first["concepts"], ["AI芯片", "算力"])
        self.assertEqual(second["sector"], "半导体")
        self.assertEqual(second["concepts"], ["AI芯片", "算力"])
        self.assertEqual(cached["sector"], "半导体")
        self.assertEqual(cached["concepts"], ["AI芯片", "算力"])
        mock_cninfo.assert_called_once_with(symbol="600063")

    @patch("stock_analyzer.providers.catalog.ak.stock_profile_cninfo")
    def test_catalog_get_stock_profile_survives_provider_failure(self, mock_cninfo):
        mock_cninfo.side_effect = RuntimeError("cninfo failed")

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                profile = get_stock_profile("600063")

        self.assertFalse(profile.get("sector"))
        self.assertEqual(profile.get("code"), "600063")

    @patch("stock_analyzer.catalog.disable_proxies")
    def test_refresh_stock_concept_cache_builds_stock_to_concepts(self, mock_disable):
        class FakeConceptProvider:
            def list_boards(self, logger=None):
                return [
                    {"name": "黄金概念", "index_code": "886001", "concept_code": "301001", "code": "301001"},
                    {"name": "机器人概念", "index_code": "886002", "concept_code": "301002", "code": "301002"},
                ], "adata_ths_concepts"

            def fetch_adata_constituents(self, board):
                if board["name"] == "黄金概念":
                    return [{"code": "600063", "name": "皖维高新"}, {"code": "601069", "name": "西部黄金"}]
                return [{"code": "600063", "name": "皖维高新"}, {"code": "000001", "name": "平安银行"}]

            def fetch_ths_constituents(self, board):
                return []

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                summary = refresh_stock_concept_cache(provider=FakeConceptProvider())
                profile = get_cached_stock_profile("600063")

        self.assertEqual(summary["concept_count"], 2)
        self.assertEqual(summary["stock_count"], 3)
        self.assertEqual(summary["source"], "adata_ths_concepts")
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(profile["name"], "皖维高新")
        self.assertEqual(profile["concepts"], ["黄金概念", "机器人概念"])
        mock_disable.assert_called_once()

    @patch("stock_analyzer.catalog.disable_proxies")
    def test_refresh_stock_concept_cache_reports_progress_when_a_concept_fails(self, mock_disable):
        class FakeConceptProvider:
            def __init__(self):
                self.calls = 0

            def list_boards(self, logger=None):
                return [
                    {"name": "黄金概念", "index_code": "", "concept_code": "301001", "code": "301001"},
                    {"name": "失败概念", "index_code": "", "concept_code": "301002", "code": "301002"},
                ], "ths_concept_pages"

            def fetch_adata_constituents(self, board):
                return []

            def fetch_ths_constituents(self, board):
                self.calls += 1
                if self.calls == 1:
                    return [{"code": "600063", "name": "皖维高新"}]
                raise RuntimeError("provider failed")

        progress = []

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                summary = refresh_stock_concept_cache(
                    progress_callback=lambda **item: progress.append(item),
                    provider=FakeConceptProvider(),
                )

        self.assertEqual(summary["concept_count"], 2)
        self.assertEqual(summary["completed_count"], 2)
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["stock_count"], 1)
        self.assertEqual(progress[-1]["completed"], 2)
        self.assertEqual(progress[-1]["stock_count"], 1)
        mock_disable.assert_called_once()

    @patch("stock_analyzer.catalog.disable_proxies")
    def test_refresh_stock_concept_cache_preserves_previous_cache_when_coverage_collapses(self, mock_disable):
        class PartialConceptProvider:
            def list_boards(self, logger=None):
                return [
                    {"name": "局部概念", "index_code": "", "concept_code": "301001", "code": "301001"},
                ], "ths_concept_pages"

            def fetch_adata_constituents(self, board):
                return []

            def fetch_ths_constituents(self, board):
                return [
                    {"code": "600001", "name": "样本1"},
                    {"code": "600002", "name": "样本2"},
                ]

        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            previous = {
                f"600{i:03d}": [f"旧概念{i}"]
                for i in range(1, 11)
            }
            (cache_dir / "stock_concepts.json").write_text(json.dumps({
                "source": "previous",
                "updated_at": "2026-09-19T15:30:00",
                "stocks": previous,
            }, ensure_ascii=False), encoding="utf-8")
            logger = Mock()
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", cache_dir):
                summary = refresh_stock_concept_cache(provider=PartialConceptProvider(), logger=logger)
                preserved = json.loads((cache_dir / "stock_concepts.json").read_text(encoding="utf-8"))
                profile = get_cached_stock_profile("600001")

        self.assertEqual(summary["stock_count"], 2)
        self.assertEqual(preserved["source"], "previous")
        self.assertEqual(preserved["stocks"], previous)
        self.assertEqual(profile["concepts"], ["局部概念", "旧概念1"])
        logger.warning.assert_called_once()
        mock_disable.assert_called_once()

    @patch("stock_analyzer.catalog.disable_proxies")
    def test_refresh_stock_concept_cache_falls_back_to_ths_page_when_adata_constituent_fails(
        self,
        mock_disable,
    ):
        class FakeConceptProvider:
            def __init__(self):
                self.ths_calls = 0

            def list_boards(self, logger=None):
                return [
                    {"name": "存储芯片", "index_code": "886042", "concept_code": "307940", "code": "307940"},
                ], "adata_ths_concepts"

            def fetch_adata_constituents(self, board):
                raise RuntimeError("adata failed")

            def fetch_ths_constituents(self, board):
                self.ths_calls += 1
                return [{"code": "300302", "name": "同有科技"}]

        provider = FakeConceptProvider()
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                summary = refresh_stock_concept_cache(provider=provider)
                profile = get_cached_stock_profile("300302")

        self.assertEqual(summary["source"], "adata_ths_concepts")
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(profile["concepts"], ["存储芯片"])
        self.assertEqual(provider.ths_calls, 1)

    def test_ths_concept_html_parser_reads_stock_rows_only(self):
        html = """
        <table class="m-table m-pager-table">
            <tbody>
                <tr><td>1</td><td><a>688328</a></td><td><a>深科达</a></td><td>70.31</td></tr>
                <tr><td>2</td><td><a>300302</a></td><td><a>同有科技</a></td><td>42.60</td></tr>
                <tr><td colspan="14">暂无成份股数据</td></tr>
            </tbody>
        </table>
        """

        rows = _stock_rows_from_ths_concept_html(html)

        self.assertEqual(rows, [
            {"code": "688328", "name": "深科达"},
            {"code": "300302", "name": "同有科技"},
        ])

    def test_concept_refresh_job_manager_tracks_background_progress(self):
        with TemporaryDirectory() as tmp_dir:
            manager = ConceptRefreshJobManager(max_workers=1, history_path=Path(tmp_dir) / "concept_jobs.json")

            try:
                def refresh(max_concepts=None, progress_callback=None):
                    progress_callback(total=2, completed=1, current_concept="黄金概念", stock_count=1)
                    progress_callback(total=2, completed=2, current_concept="机器人概念", stock_count=3)
                    return {"concept_count": 2, "completed_count": 2, "stock_count": 3}

                job = manager.start_job(refresh, max_concepts=2)
                self.assertEqual(job["id"], manager.current_job()["id"])
                finished = None
                for future in list(manager._job_futures.values()):
                    future.result(timeout=3)
                finished = manager.get_job(job["id"])

                self.assertEqual(finished["status"], "completed")
                self.assertEqual(finished["progress"], 100)
                self.assertEqual(finished["stock_count"], 3)
            finally:
                manager.shutdown(wait=True)

    def test_concept_refresh_job_manager_reuses_concurrent_start_requests(self):
        entered = threading.Event()
        release = threading.Event()
        start = threading.Barrier(4)
        uuid_lock = threading.Lock()
        uuid_counter = [0]
        results = []
        errors = []

        class FakeUuid:
            def __init__(self, value):
                self.hex = value

        def fake_uuid4():
            start.wait(timeout=2)
            with uuid_lock:
                uuid_counter[0] += 1
                return FakeUuid(f"{uuid_counter[0]:032x}")

        def refresh(max_concepts=None, progress_callback=None):
            entered.set()
            release.wait(timeout=2)
            return {"concept_count": 1, "completed_count": 1, "stock_count": 2}

        manager = ConceptRefreshJobManager(max_workers=1, history_path=None)
        try:
            def worker():
                try:
                    results.append(manager.start_job(refresh, max_concepts=1))
                except Exception as exc:
                    errors.append(exc)

            with patch("stock_analyzer.concept_jobs.uuid.uuid4", side_effect=fake_uuid4):
                threads = [threading.Thread(target=worker) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertTrue(entered.wait(timeout=1))
            release.set()
            for future in list(manager._job_futures.values()):
                future.result(timeout=3)
            finished = manager.current_job()
        finally:
            release.set()
            manager.shutdown(wait=True)

        self.assertFalse(errors)
        self.assertEqual(len(results), 4)
        self.assertEqual(len({item["id"] for item in results}), 1)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["stock_count"], 2)

    def test_concept_refresh_job_manager_persists_history_for_restart(self):
        with TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "concept_jobs.json"
            manager = ConceptRefreshJobManager(max_workers=1, history_path=history_path)
            try:
                def refresh(max_concepts=None, progress_callback=None):
                    progress_callback(total=1, completed=1, current_concept="黄金概念", stock_count=2)
                    return {"concept_count": 1, "completed_count": 1, "stock_count": 2}

                job = manager.start_job(refresh, max_concepts=1)
                for future in list(manager._job_futures.values()):
                    future.result(timeout=3)
            finally:
                manager.shutdown(wait=True)

            reloaded = ConceptRefreshJobManager(max_workers=1, history_path=history_path)
            try:
                restored = reloaded.get_job(job["id"])
                current = reloaded.current_job()
            finally:
                reloaded.shutdown(wait=True)

        self.assertEqual(restored["status"], "completed")
        self.assertEqual(restored["stock_count"], 2)
        self.assertEqual(current["id"], job["id"])

    def test_concept_refresh_job_manager_marks_running_history_interrupted(self):
        with TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "concept_jobs.json"
            history_path.write_text(json.dumps({
                "version": 1,
                "jobs": [{
                    "id": "concept123",
                    "status": "running",
                    "total": 390,
                    "completed": 313,
                    "progress": 80,
                    "current_concept": "网络游戏",
                    "stock_count": 1200,
                    "concept_count": 390,
                    "created_at": "2026-05-11T09:30:00",
                    "started_at": "2026-05-11T09:30:01",
                    "updated_at": "2026-05-11T09:31:00",
                }],
            }), encoding="utf-8")

            manager = ConceptRefreshJobManager(max_workers=1, history_path=history_path)
            try:
                restored = manager.get_job("concept123")
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["completed"], 313)
        self.assertEqual(restored["current_concept"], "")
        self.assertEqual(restored["error"], "服务重启，概念刷新中断")

    @patch("stock_analyzer.catalog.disable_proxies")
    @patch("stock_analyzer.providers.catalog.ak.stock_info_a_code_name")
    def test_catalog_get_stock_codes_uses_primary_provider(self, mock_info, mock_disable):
        mock_info.return_value = pd.DataFrame({"code": ["600063", "000001", "920992"], "name": ["A", "B", "C"]})

        self.assertEqual(get_stock_codes(), ["600063", "000001", "920992"])
        mock_disable.assert_called_once()

    @patch("stock_analyzer.catalog.disable_proxies")
    @patch("stock_analyzer.providers.catalog.fetch_tdx_stock_codes")
    @patch("stock_analyzer.providers.catalog.ak.stock_info_a_code_name")
    def test_catalog_get_stock_codes_uses_fallback_list_when_providers_fail(self, mock_info, mock_tdx, mock_disable):
        mock_info.side_effect = RuntimeError("primary failed")
        mock_tdx.side_effect = RuntimeError("secondary failed")

        self.assertEqual(get_stock_codes(), FALLBACK_STOCK_CODES)
        mock_disable.assert_called_once()

    @patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体", "concepts": ["AI芯片"]})
    @patch("app.fetch_and_process_data", return_value={"stock_code": "600063", "dates": ["2026-05-08"]})
    def test_analyze_api_returns_stock_sector(self, mock_fetch, mock_profile):
        response = app.app.test_client().get("/api/analyze?code=600063")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["stock_name"], "示例股票 (600063)")
        self.assertEqual(payload["stock_sector"], "半导体")
        self.assertEqual(payload["stock_concepts"], ["AI芯片"])
        self.assertEqual(payload["tag_profile"]["official_industry"], "半导体")
        self.assertIn("AI芯片", payload["tag_profile"]["raw_concepts"])

    @patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体", "concepts": []})
    @patch("stock_analyzer.stock_service.fetch_and_process_data", return_value={"stock_code": "600063", "dates": ["2026-05-08"]})
    def test_analyze_route_forwards_force_refresh_to_stock_service(self, mock_fetch, mock_profile):
        response = app.app.test_client().get("/api/analyze?code=600063&refresh=1")

        self.assertEqual(response.status_code, 200)
        _, kwargs = mock_fetch.call_args
        self.assertTrue(kwargs["force_refresh"])
        self.assertFalse(kwargs["include_legacy_chart"])

    def test_analyze_api_passes_legacy_chart_flag_when_requested(self):
        captured = {}

        def fetch_data(code, include_legacy_chart=False):
            captured["code"] = code
            captured["include_legacy_chart"] = include_legacy_chart
            return {"stock_code": code, "dates": ["2026-05-08"]}

        with app.app.test_request_context("/api/analyze?code=600063&legacy=1"):
            response = app.stock_api.analyze_response(
                app.flask_jsonify,
                app.normalize_code,
                fetch_data,
                lambda code: {"name": "示例股票", "sector": "半导体", "concepts": ["AI芯片"]},
                lambda code: "示例股票",
            )

        payload = response.get_json()
        self.assertEqual(payload["stock_code"], "600063")
        self.assertEqual(captured["code"], "600063")
        self.assertTrue(captured["include_legacy_chart"])

    def test_analyze_api_passes_force_refresh_when_requested(self):
        captured = {}

        def fetch_data(code, include_legacy_chart=False, force_refresh=False):
            captured["code"] = code
            captured["include_legacy_chart"] = include_legacy_chart
            captured["force_refresh"] = force_refresh
            return {"stock_code": code, "dates": ["2026-05-08"]}

        with app.app.test_request_context("/api/analyze?code=600063&refresh=1"):
            response = app.stock_api.analyze_response(
                app.flask_jsonify,
                app.normalize_code,
                fetch_data,
                lambda code: {"name": "示例股票", "sector": "半导体", "concepts": ["AI芯片"]},
                lambda code: "示例股票",
            )

        payload = response.get_json()
        self.assertEqual(payload["stock_code"], "600063")
        self.assertEqual(captured["code"], "600063")
        self.assertTrue(captured["force_refresh"])
        self.assertFalse(captured["include_legacy_chart"])

    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_exposes_daily_and_hourly_layers(self, mock_minute):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        mock_minute.return_value = pd.DataFrame({
            "时间": pd.date_range("2026-05-10 09:30:00", periods=48, freq="60min"),
            "开盘": [10.0 + i * 0.02 for i in range(48)],
            "最高": [10.1 + i * 0.02 for i in range(48)],
            "最低": [9.9 + i * 0.02 for i in range(48)],
            "收盘": [10.0 + i * 0.02 for i in range(48)],
            "成交量": [1000 + i * 5 for i in range(48)],
        })

        payload = build_multi_timeframe_payload("600063", daily, logger=None, verbose=False)

        self.assertIn("daily", payload)
        self.assertIn("hour_1", payload)
        self.assertIn("hour_4", payload)
        self.assertTrue(payload["daily"]["available"])
        self.assertTrue(payload["hour_1"]["available"])
        self.assertEqual(payload["hour_1"]["label"], "60m")
        self.assertIn("chart", payload["hour_1"])
        self.assertEqual(payload["hour_1"]["chart"]["dates"][0], "2026-05-10 09:30")
        self.assertTrue(payload["hour_4"]["available"])
        self.assertEqual(payload["hour_4"]["label"], "4h")
        self.assertIn("chart", payload["hour_4"])
        self.assertTrue(payload["hour_4"]["derived"])
        self.assertIn("由 60m 合成", payload["hour_4"]["detail"])

    @patch("stock_analyzer.multi_timeframe.analysis_frame_to_chart_payload", return_value={"dates": ["cached"]})
    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_can_cache_requested_timeframe_chart(self, mock_minute, mock_chart):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        mock_minute.return_value = pd.DataFrame({
            "时间": pd.date_range("2026-05-10 09:30:00", periods=48, freq="60min"),
            "开盘": [10.0 + i * 0.02 for i in range(48)],
            "最高": [10.1 + i * 0.02 for i in range(48)],
            "最低": [9.9 + i * 0.02 for i in range(48)],
            "收盘": [10.0 + i * 0.02 for i in range(48)],
            "成交量": [1000 + i * 5 for i in range(48)],
        })

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.timeframe_chart_cache.TIMEFRAME_CHART_CACHE_DIR", Path(tmp_dir)):
                first = build_multi_timeframe_payload(
                    "600063",
                    daily,
                    target_periods="60m",
                    use_chart_cache=True,
                )
                second = build_multi_timeframe_payload(
                    "600063",
                    daily,
                    target_periods="60m",
                    use_chart_cache=True,
                )

        self.assertEqual(mock_chart.call_count, 1)
        self.assertFalse(first["hour_1"]["chart"]["timeframe_chart_cache_meta"]["hit"])
        self.assertTrue(second["hour_1"]["chart"]["timeframe_chart_cache_meta"]["hit"])

    @patch("stock_analyzer.multi_timeframe.analysis_frame_to_chart_payload", return_value={"dates": ["mock"]})
    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_can_load_only_requested_60m_layer(self, mock_minute, mock_chart):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        mock_minute.return_value = pd.DataFrame({
            "时间": pd.date_range("2026-05-10 09:30:00", periods=48, freq="60min"),
            "开盘": [10.0 + i * 0.02 for i in range(48)],
            "最高": [10.1 + i * 0.02 for i in range(48)],
            "最低": [9.9 + i * 0.02 for i in range(48)],
            "收盘": [10.0 + i * 0.02 for i in range(48)],
            "成交量": [1000 + i * 5 for i in range(48)],
        })

        payload = build_multi_timeframe_payload("600063", daily, target_periods="60m")

        self.assertIn("chart", payload["hour_1"])
        self.assertNotIn("chart", payload["hour_4"])
        self.assertFalse(payload["hour_4"]["available"])
        self.assertEqual(mock_chart.call_count, 1)

    @patch("stock_analyzer.multi_timeframe.analysis_frame_to_chart_payload", return_value={"dates": ["mock"]})
    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_can_load_only_requested_4h_layer(self, mock_minute, mock_chart):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        mock_minute.return_value = pd.DataFrame({
            "时间": pd.date_range("2026-05-10 09:30:00", periods=48, freq="60min"),
            "开盘": [10.0 + i * 0.02 for i in range(48)],
            "最高": [10.1 + i * 0.02 for i in range(48)],
            "最低": [9.9 + i * 0.02 for i in range(48)],
            "收盘": [10.0 + i * 0.02 for i in range(48)],
            "成交量": [1000 + i * 5 for i in range(48)],
        })

        payload = build_multi_timeframe_payload("600063", daily, target_periods="4h")

        self.assertNotIn("chart", payload["hour_1"])
        self.assertIn("chart", payload["hour_4"])
        self.assertFalse(payload["hour_1"]["available"])
        self.assertTrue(payload["hour_4"]["derived"])
        self.assertEqual(mock_chart.call_count, 1)

    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_can_skip_realtime_fetch_for_initial_analysis(self, mock_minute):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        mock_minute.return_value = None

        payload = build_multi_timeframe_payload("600063", daily, allow_fetch=False)

        self.assertFalse(payload["hour_1"]["available"])
        self.assertTrue(payload["hour_1"]["chart_deferred"])
        self.assertIn("延后加载", payload["hour_1"]["detail"])
        mock_minute.assert_not_called()

    @patch("stock_analyzer.multi_timeframe.analysis_frame_to_chart_payload")
    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_defers_hourly_charts_for_initial_analysis(self, mock_minute, mock_chart):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        mock_minute.return_value = pd.DataFrame({
            "时间": pd.date_range("2026-05-10 09:30:00", periods=48, freq="60min"),
            "开盘": [10.0 + i * 0.02 for i in range(48)],
            "最高": [10.1 + i * 0.02 for i in range(48)],
            "最低": [9.9 + i * 0.02 for i in range(48)],
            "收盘": [10.0 + i * 0.02 for i in range(48)],
            "成交量": [1000 + i * 5 for i in range(48)],
        })

        payload = build_multi_timeframe_payload("600063", daily, allow_fetch=False)

        self.assertFalse(payload["hour_1"]["available"])
        self.assertTrue(payload["hour_1"]["chart_deferred"])
        self.assertNotIn("chart", payload["hour_1"])
        self.assertNotIn("chart", payload["hour_4"])
        mock_minute.assert_not_called()
        mock_chart.assert_not_called()

    @patch("stock_analyzer.multi_timeframe.build_v2_signal_events")
    @patch("stock_analyzer.multi_timeframe.fetch_stock_minute_history")
    def test_multi_timeframe_payload_reuses_daily_events_for_initial_summary(self, mock_minute, mock_events):
        daily = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        reused_event = SignalEvent(
            key="v2_repair_watch",
            group="v2",
            date="2026-01-30",
            coord_price=11.1,
            price=11.2,
            reason="复用日线图面事件",
            value="修复观察",
        )
        mock_minute.return_value = None

        payload = build_multi_timeframe_payload(
            "600063",
            daily,
            allow_fetch=False,
            daily_recent_events=[reused_event],
        )

        self.assertEqual(payload["daily"]["event"]["signal_key"], "v2_repair_watch")
        self.assertEqual(payload["daily"]["event"]["reason"], "复用日线图面事件")
        mock_events.assert_not_called()

    def test_timeframe_event_payload_exposes_v2_semantics(self):
        frame = self._v2_divergence_frame()

        item = summarize_timeframe(
            frame,
            period_key="daily",
            period_label="日线",
            role_label="主趋势",
        )

        self.assertEqual(item["event"]["signal_key"], "v2_bottom_research")
        self.assertEqual(item["event"]["signal_label"], "C研")
        self.assertEqual(item["event"]["v2_signal"], "C研")
        self.assertEqual(item["event"]["v2_role_label"], "观察")
        self.assertFalse(item["event"]["requires_stop_loss"])

    @patch("app.fetch_multi_timeframe_data", return_value={
        "stock_code": "600063",
        "multi_timeframes": {
            "daily": {"period": "1d", "available": True},
            "hour_1": {"period": "60m", "available": True, "chart": {"dates": ["2026-05-10 09:30"]}},
            "hour_4": {"period": "4h", "available": True, "chart": {"dates": ["2026-05-10"]}},
        },
    })
    def test_analyze_timeframes_api_returns_deferred_payload(self, mock_fetch):
        response = app.app.test_client().get("/api/analyze/timeframes?code=600063")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["stock_code"], "600063")
        self.assertIn("chart", payload["multi_timeframes"]["hour_1"])
        self.assertIn("chart", payload["multi_timeframes"]["hour_4"])
        mock_fetch.assert_called_once_with("600063", period=None, force_refresh=False)

    @patch("app.fetch_multi_timeframe_data", return_value={
        "stock_code": "600063",
        "requested_period": "hour_1",
        "multi_timeframes": {
            "daily": {"period": "1d", "available": True},
            "hour_1": {"period": "60m", "available": True, "chart": {"dates": ["2026-05-10 09:30"]}},
            "hour_4": {"period": "4h", "available": False},
        },
    })
    def test_analyze_timeframes_api_accepts_requested_period(self, mock_fetch):
        response = app.app.test_client().get("/api/analyze/timeframes?code=600063&period=60m")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("chart", payload["multi_timeframes"]["hour_1"])
        self.assertNotIn("chart", payload["multi_timeframes"]["hour_4"])
        mock_fetch.assert_called_once_with("600063", period="hour_1", force_refresh=False)

    @patch("app.fetch_multi_timeframe_data", return_value={
        "stock_code": "600063",
        "requested_period": "hour_4",
        "multi_timeframes": {
            "daily": {"period": "1d", "available": True},
            "hour_4": {"period": "4h", "available": True, "chart": {"dates": ["2026-05-10"]}},
        },
    })
    def test_analyze_timeframes_api_supports_cache_refresh(self, mock_fetch):
        response = app.app.test_client().get("/api/analyze/timeframes?code=600063&period=4h&refresh=1")

        self.assertEqual(response.status_code, 200)
        mock_fetch.assert_called_once_with("600063", period="hour_4", force_refresh=True)

    def test_analyze_timeframes_api_rejects_unknown_period(self):
        response = app.app.test_client().get("/api/analyze/timeframes?code=600063&period=15m")

        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertIn("无效的分时周期", payload["error"])

    @patch("stock_analyzer.stock_service.get_stock_profile", return_value={})
    @patch("stock_analyzer.stock_service.build_multi_timeframe_payload", return_value={"daily": {"available": True}})
    @patch("stock_analyzer.stock_service.analysis_frame_to_chart_payload", return_value={"score_summary": {"setup": 1, "confirm": 0, "risk": 0}})
    @patch("stock_analyzer.stock_service.build_v2_analysis_context")
    @patch("stock_analyzer.stock_service.build_analysis_frame")
    def test_fetch_and_process_data_reuses_v2_request_context(
        self,
        mock_frame,
        mock_context,
        mock_chart,
        mock_timeframes,
        mock_profile,
    ):
        frame = prepare_analysis_frame(pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=30, freq="D"),
            "开盘": [10.0 + i * 0.05 for i in range(30)],
            "最高": [10.3 + i * 0.05 for i in range(30)],
            "最低": [9.8 + i * 0.05 for i in range(30)],
            "收盘": [10.1 + i * 0.05 for i in range(30)],
            "成交量": [1000 + i * 10 for i in range(30)],
        }), fill_initial_ma20=True)
        facts = {"scores": {"setup": 1, "confirm": 0, "risk": 0}}
        structures = {"rectangle": {"available": False}}
        events = [
            SignalEvent(
                key="v2_structure_candidate",
                group="v2",
                date="2026-01-30",
                coord_price=11.1,
                price=11.2,
                reason="复用事件",
                value="结构候选",
            )
        ]
        mock_frame.return_value = frame
        state = {"state": "structure_candidate"}
        trade_plan = {"status": "blocked"}
        mock_context.return_value = {
            "facts": facts,
            "structures": structures,
            "events": events,
            "state": state,
            "trade_plan": trade_plan,
            "score_summary": {"setup": 1, "confirm": 0, "risk": 0},
        }

        payload = stock_service.fetch_and_process_data("600063", verbose=False)

        self.assertEqual(payload["stock_code"], "600063")
        mock_context.assert_called_once_with(frame, include_trade_plan=True, events_cache_scope="single:600063")
        self.assertIs(mock_chart.call_args.kwargs["v2_events"], events)
        self.assertIs(mock_chart.call_args.kwargs["facts"], facts)
        self.assertFalse(mock_chart.call_args.kwargs["include_legacy"])
        self.assertIs(payload["c_signal_v2_state"], state)
        self.assertIs(payload["trade_plan"], trade_plan)
        self.assertIs(mock_timeframes.call_args.kwargs["daily_recent_events"], events)
        self.assertEqual(mock_timeframes.call_args.kwargs["daily_score_summary"], {"setup": 1, "confirm": 0, "risk": 0})

    @patch("stock_analyzer.stock_service.get_stock_profile", return_value={"name": "示例股票"})
    @patch("stock_analyzer.stock_service.build_multi_timeframe_payload", return_value={"daily": {"available": True}})
    @patch("stock_analyzer.stock_service.analysis_frame_to_chart_payload", return_value={"score_summary": {"setup": 1, "confirm": 0, "risk": 0}})
    @patch("stock_analyzer.stock_service.build_v2_analysis_context")
    @patch("stock_analyzer.stock_service.build_analysis_frame")
    def test_fetch_and_process_data_can_include_legacy_chart_payload(
        self,
        mock_frame,
        mock_context,
        mock_chart,
        mock_timeframes,
        mock_profile,
    ):
        frame = self._minimal_signal_frame(rows=30)
        mock_frame.return_value = frame
        mock_context.return_value = {
            "facts": {},
            "structures": {},
            "events": [],
            "state": {"state": "structure_candidate"},
            "trade_plan": {"status": "blocked"},
            "score_summary": {"setup": 1, "confirm": 0, "risk": 0},
        }

        stock_service.fetch_and_process_data("600063", verbose=False, include_legacy_chart=True)

        self.assertTrue(mock_chart.call_args.kwargs["include_legacy"])

    def test_v2_analysis_context_builds_shared_payload_parts(self):
        frame = self._v2_legacy_entry_frame("breakout")

        context = build_v2_analysis_context(frame, include_events=True, include_trade_plan=True)

        self.assertEqual(context["source"], "v2_analysis_context_p23a")
        self.assertIs(context["facts"], context["components"]["facts"])
        self.assertIs(context["structures"], context["components"]["structures"])
        self.assertIs(context["trade_context"]["c_signal_v2_facts"], context["facts"])
        self.assertIs(context["trade_context"]["technical_structures"], context["structures"])
        self.assertIsInstance(context["events"], list)
        self.assertIsInstance(context["state"], dict)
        self.assertIsInstance(context["trade_plan"], dict)
        self.assertNotEqual(context["score_summary"]["date"], "-")

    def test_v2_analysis_context_handles_empty_frame(self):
        context = build_v2_analysis_context(None, include_events=True, include_trade_plan=True)

        self.assertEqual(context["facts"], {})
        self.assertEqual(context["events"], [])
        self.assertEqual(context["score_summary"], {"date": "-", "setup": 0, "confirm": 0, "risk": 0, "watch": False})
        self.assertEqual(context["state"]["state"], "no_data")
        self.assertEqual(context["trade_plan"]["status"], "blocked")

    def test_c_signal_v2_state_model_ignores_legacy_composite_entry(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["close"] = [10.0] * 12
        frame["open"] = [10.0] * 12
        apply_legacy_entry(frame, entry_type="breakout", setup=1, confirm=4)

        state = build_c_signal_v2_state(frame, event_key="composite_breakout")

        self.assertNotEqual(state["state"], "legacy_entry_unconfirmed")
        self.assertNotIn(state["permission"], {"attack_allowed", "breakout_allowed", "pullback_allowed"})
        self.assertFalse(state["requires_trade_plan"])
        self.assertEqual(state["event_mapping"]["v2_signal"], "C突")

    def test_c_signal_v2_facts_surfaces_legacy_experience_without_permission(self):
        frame = self._minimal_signal_frame(rows=14)
        mark_legacy_signals(frame, {
            10: ["new_is_b_point"],
            11: ["is_bottom_divergence"],
            12: ["new_is_pullback_b"],
            13: ["opt_is_s_warn"],
        })

        legacy = build_legacy_experience_facts(frame)
        facts = build_c_signal_v2_facts(frame)
        state = build_c_signal_v2_state(frame)

        self.assertTrue(legacy["available"])
        self.assertEqual(legacy["source"], "legacy_experience_p21")
        self.assertEqual(legacy["priority"], [
            "legacy_low_risk_pullback",
            "legacy_bottom_repair_hint",
            "legacy_risk_hint",
        ])
        self.assertTrue(facts["legacy_experience"]["available"])
        self.assertTrue(all(item["grants_permission"] is False for item in legacy["items"]))
        self.assertFalse(legacy["grants_permission"])
        self.assertNotIn(state["permission"], {"attack_allowed", "breakout_allowed", "pullback_allowed"})

    def test_legacy_experience_ablation_report_keeps_permission_boundary(self):
        rows = [
            {
                "status": "evaluated",
                "code": "600063",
                "return_pct": 2.0,
                "legacy_keys": ["legacy_low_risk_pullback"],
                "legacy_grants_permission": False,
                "v2_signal": "C候",
                "v2_permission": "structure_only",
                "candidate_substate": "pullback_setup",
                "signal_close": 10.0,
                "outcome_close": 10.2,
            },
            {
                "status": "evaluated",
                "code": "000001",
                "return_pct": -1.0,
                "legacy_keys": [],
                "legacy_grants_permission": False,
                "v2_signal": "C研",
                "v2_permission": "watch_only",
                "candidate_substate": "",
                "signal_close": 10.0,
                "outcome_close": 9.9,
            },
        ]

        report = analyze_legacy_experience_ablation.build_report(
            rows,
            signal_date="2026-09-11",
            outcome_date="2026-09-14",
            elapsed_seconds=1.2,
            counts={"evaluated": 2},
        )

        self.assertEqual(report["source"], "legacy_experience_ablation_p21b")
        self.assertEqual(report["baseline"]["count"], 2)
        self.assertEqual(report["legacy_any"]["avg_return_pct"], 2.0)
        self.assertEqual(report["legacy_none"]["avg_return_pct"], -1.0)
        self.assertEqual(report["buckets"]["legacy_low_risk_pullback"]["count"], 1)
        self.assertEqual(report["permission_leak_count"], 0)

    def test_legacy_experience_rollup_report_combines_pair_summaries(self):
        first = {
            "signal_date": "2026-09-09",
            "outcome_date": "2026-09-10",
            "elapsed_seconds": 1.0,
            "permission_leak_count": 0,
            "baseline": {"count": 2, "avg_return_pct": 1.0, "up": 1, "flat": 0, "down": 1},
            "legacy_any": {"count": 1, "avg_return_pct": 2.0, "up": 1, "flat": 0, "down": 0},
            "legacy_none": {"count": 1, "avg_return_pct": 0.0, "up": 0, "flat": 0, "down": 1},
            "v2_candidate_substate": {
                "weak_repair_candidate": {"count": 1, "avg_return_pct": 2.0, "up": 1, "flat": 0, "down": 0}
            },
            "buckets": {
                "legacy_low_risk_pullback": {"count": 1, "avg_return_pct": 2.0, "up": 1, "flat": 0, "down": 0},
                "legacy_bottom_repair_hint": {"count": 0},
                "legacy_risk_hint": {"count": 1, "avg_return_pct": 2.0, "up": 1, "flat": 0, "down": 0},
            },
        }
        second = {
            "signal_date": "2026-09-10",
            "outcome_date": "2026-09-11",
            "elapsed_seconds": 2.0,
            "permission_leak_count": 0,
            "baseline": {"count": 2, "avg_return_pct": -1.0, "up": 0, "flat": 0, "down": 2},
            "legacy_any": {"count": 2, "avg_return_pct": -1.0, "up": 0, "flat": 0, "down": 2},
            "legacy_none": {"count": 0},
            "v2_candidate_substate": {
                "weak_repair_candidate": {"count": 1, "avg_return_pct": -2.0, "up": 0, "flat": 0, "down": 1},
                "pullback_setup": {"count": 1, "avg_return_pct": 0.0, "up": 0, "flat": 0, "down": 1},
            },
            "buckets": {
                "legacy_low_risk_pullback": {"count": 1, "avg_return_pct": -2.0, "up": 0, "flat": 0, "down": 1},
                "legacy_bottom_repair_hint": {"count": 1, "avg_return_pct": 0.0, "up": 0, "flat": 0, "down": 1},
                "legacy_risk_hint": {"count": 2, "avg_return_pct": -1.0, "up": 0, "flat": 0, "down": 2},
            },
        }

        report = analyze_legacy_experience_ablation.build_rollup_report([first, second])

        self.assertEqual(report["source"], "legacy_experience_ablation_rollup_p21c")
        self.assertEqual(report["pair_count"], 2)
        self.assertEqual(report["baseline"]["count"], 4)
        self.assertEqual(report["baseline"]["avg_return_pct"], 0.0)
        self.assertEqual(report["baseline"]["win_rate_pct"], 25.0)
        self.assertEqual(report["legacy_any"]["count"], 3)
        self.assertEqual(report["buckets"]["legacy_low_risk_pullback"]["avg_return_pct"], 0.0)
        self.assertEqual(report["v2_candidate_substate"]["weak_repair_candidate"]["count"], 2)
        self.assertEqual(report["permission_leak_count"], 0)

    def test_c_signal_v2_state_model_prioritizes_risk_without_entry_stop(self):
        frame = self._v2_entry_then_crash_frame()

        state = build_c_signal_v2_state(frame)

        self.assertEqual(state["state"], "exit_gate_sell")
        self.assertEqual(state["permission"], "risk_only")
        self.assertEqual(state["signal"], "C风")
        self.assertFalse(state["requires_trade_plan"])
        self.assertFalse(state["requires_stop_loss"])

    def test_c_signal_v2_facts_detect_structure_and_trigger_without_trade_permission(self):
        frame = self._v2_trigger_frame()

        facts = build_c_signal_v2_facts(frame)

        self.assertEqual(facts["source"], "c_signal_v2_p19_repair_watch_facts")
        self.assertIn("normalized_bars", facts["structure"])
        self.assertIn("active_rectangle", facts["structure"])
        self.assertIn("macro_rectangle", facts["structure"])
        self.assertTrue(facts["structure"]["fractals"]["double_bottom_higher_low"])
        self.assertTrue(facts["structure"]["rectangle"]["available"])
        self.assertEqual(facts["structure"]["rectangle"]["c_point"], 10.0)
        self.assertEqual(facts["structure"]["rectangle"]["c_point_source"], "lowest_close")
        self.assertTrue(facts["trigger"]["attack_day"])
        self.assertTrue(facts["trigger"]["strict_attack"]["triggered"])
        self.assertTrue(facts["trigger"]["ignition"]["triggered"])
        self.assertTrue(facts["momentum"]["power_flip"])
        self.assertTrue(facts["momentum"]["williams_r_power_cross"])
        self.assertEqual(facts["macro_tide"]["permission"], "unknown")
        self.assertFalse(facts["target_structure"]["selected_breakout_target"])
        self.assertGreaterEqual(facts["v2_scores"]["structure_score"], 65)
        self.assertGreaterEqual(facts["v2_scores"]["trigger_quality"], 75)

    def test_c_signal_v2_target_structure_separates_pullback_and_breakout_targets(self):
        frame = self._v2_trigger_frame_with_upper_target()

        target_structure = build_target_structure_facts(frame)

        self.assertEqual(target_structure["pullback_target"]["source"], "rectangle_upper")
        self.assertEqual(target_structure["pullback_target"]["price"], 10.95)
        self.assertIn(target_structure["selected_breakout_target"]["source"], {"prior_high_120", "prior_high_250"})
        self.assertEqual(target_structure["selected_breakout_target"]["price"], 14.0)
        self.assertTrue(target_structure["resistance_zones"])
        self.assertGreaterEqual(target_structure["selected_breakout_target"]["strength_score"], 60)
        self.assertIn("强度", target_structure["target_selection_reason"])

    def test_c_signal_v2_target_structure_skips_weak_near_resistance_for_core_target(self):
        rows = 130
        frame = self._minimal_signal_frame(rows=rows)
        frame["high"] = [10.5] * rows
        frame["low"] = [9.7] * rows
        frame["close"] = [10.0] * rows
        for idx in range(20, 25):
            frame.loc[idx, "high"] = 13.0
        frame.loc[80, "high"] = 11.0
        frame.loc[rows - 1, "close"] = 10.2

        target_structure = build_target_structure_facts(frame)
        weak_zone = next(zone for zone in target_structure["resistance_zones"] if zone["price"] == 11.0)

        self.assertEqual(weak_zone["role"], "warning")
        self.assertEqual(target_structure["selected_breakout_target"]["price"], 13.0)
        self.assertEqual(target_structure["selected_breakout_target"]["role"], "target")

    def test_c_signal_v2_exit_gate_scales_out_at_strong_resistance_without_selling(self):
        frame = self._v2_entry_then_rally_frame()

        exit_gate = build_exit_gate_facts(
            frame,
            target_structure={
                "resistance_zones": [{
                    "role": "target",
                    "price": 12.0,
                    "source": "prior_high_120",
                    "label": "120日前高",
                    "strength_score": 72,
                    "distance_pct": 0.84,
                }],
            },
        )

        self.assertEqual(exit_gate["action"], "scale_out")
        self.assertEqual(exit_gate["marker_role"], "scale_out")
        self.assertEqual(exit_gate["position_lifecycle"]["position_state"], "scale_out")
        self.assertIn("不直接替代 S 点", exit_gate["scale_out"]["reason"])

    def test_c_signal_v2_exit_gate_sells_only_after_trailing_stop_break(self):
        frame = self._v2_entry_then_crash_frame()

        exit_gate = build_exit_gate_facts(frame)

        self.assertEqual(exit_gate["action"], "sell")
        self.assertEqual(exit_gate["marker_role"], "sell")
        self.assertIn(exit_gate["marker_reason"], {"trailing_stop_break", "v2_structure_break"})
        self.assertEqual(exit_gate["position_lifecycle"]["position_state"], "exited")

    def test_c_signal_v2_top_fractal_is_observation_not_cwind(self):
        fields = c_signal_v2_fields("v2_top_fractal_risk")

        self.assertEqual(fields["v2_signal"], "C研")
        self.assertEqual(fields["v2_role_label"], "观察")
        self.assertEqual(fields["trade_intent"], "watch_only")

    def test_v2_signal_events_emit_top_fractal_observation_marker(self):
        frame = self._minimal_signal_frame(rows=8)
        frame["high"] = [10.0, 10.4, 11.2, 10.7, 10.2, 10.1, 10.3, 11.7]
        frame["low"] = [9.7, 9.9, 10.1, 9.9, 9.8, 9.7, 9.8, 11.4]
        frame["close"] = [9.9, 10.2, 10.8, 10.3, 10.0, 9.9, 10.0, 11.6]
        frame["ma20"] = [10.0] * len(frame)

        events = build_v2_signal_events(frame)
        top_event = next(event for event in events if event.key == "v2_top_fractal_observe")

        self.assertEqual(top_event.label, "C研")
        self.assertEqual(top_event.category, "top")
        self.assertEqual(top_event.definition["marker_role"], "observe")

    def test_v2_signal_events_emit_fractal_markers_on_intraday_frame(self):
        frame = self._minimal_signal_frame(rows=8)
        frame["date"] = pd.date_range("2026-01-01 09:30", periods=8, freq="60min")
        frame["high"] = [10.0, 10.4, 11.2, 10.7, 10.2, 10.1, 10.3, 11.7]
        frame["low"] = [9.7, 9.9, 10.1, 9.9, 9.8, 9.7, 9.8, 11.4]
        frame["close"] = [9.9, 10.2, 10.8, 10.3, 10.0, 9.9, 10.0, 11.6]
        frame["ma20"] = [10.0] * len(frame)

        events = build_v2_signal_events(frame)

        top_event = next(event for event in events if event.key == "v2_top_fractal_observe")
        self.assertEqual(top_event.date, "2026-01-01")
        self.assertEqual(top_event.category, "top")

    def test_v2_signal_events_cache_invalidates_when_same_day_prices_change(self):
        frame = self._minimal_signal_frame(rows=8)
        updated = frame.copy()
        updated.loc[updated.index[-1], "close"] = 99.0
        calls = []

        def fake_events(df_display, lookback=None, **_kwargs):
            latest_close = float(df_display["close"].iloc[-1])
            calls.append(latest_close)
            return [SignalEvent(
                key="v2_structure_candidate",
                group="v2",
                date=str(df_display["date"].iloc[-1])[:10],
                coord_price=latest_close,
                price=latest_close,
            )]

        events_module._V2_EVENTS_CACHE.clear()
        try:
            with patch("stock_analyzer.events.build_v2_signal_events", side_effect=fake_events):
                first = events_module.build_v2_signal_events_cached(frame, lookback=60, cache_scope="single:demo")
                second = events_module.build_v2_signal_events_cached(updated, lookback=60, cache_scope="single:demo")
        finally:
            events_module._V2_EVENTS_CACHE.clear()

        self.assertEqual([event.price for event in first], [10.7])
        self.assertEqual([event.price for event in second], [99.0])
        self.assertEqual(calls, [10.7, 99.0])

    def test_v2_event_fingerprint_detects_middle_row_reordering(self):
        first = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "close": [10.0, 11.0, 12.0, 13.0],
        })
        second = first.copy()
        second.loc[[1, 2], "close"] = second.loc[[2, 1], "close"].to_numpy()

        self.assertNotEqual(
            events_module._v2_events_frame_fingerprint(first),
            events_module._v2_events_frame_fingerprint(second),
        )

    def test_v2_facts_timeline_preserves_prefix_windows_for_lookback(self):
        frame = self._minimal_signal_frame(rows=8)
        calls = []

        def fake_facts_builder(prefix):
            calls.append(len(prefix))
            return {
                "latest_date": str(prefix["date"].iloc[-1])[:10],
                "structure": {
                    "rectangle": {"available": len(prefix) >= 5},
                },
            }

        timeline = build_v2_facts_timeline(frame, lookback=3, facts_builder=fake_facts_builder)

        self.assertEqual(v2_timeline_start_index(frame, lookback=3), 5)
        self.assertEqual(timeline.start_idx, 5)
        self.assertEqual(calls, [5, 6, 7, 8])
        self.assertEqual(timeline.built_count, 4)
        self.assertEqual(timeline.reused_count, 0)
        self.assertTrue(timeline.previous_facts["structure"]["rectangle"]["available"])
        self.assertEqual([point.idx for point in timeline.points], [5, 6, 7])
        self.assertEqual([point.facts["latest_date"] for point in timeline.points], [
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
        ])

    def test_v2_facts_timeline_reuses_known_latest_facts(self):
        frame = self._minimal_signal_frame(rows=8)
        calls = []
        known_latest = {
            "latest_date": "known",
            "structure": {"rectangle": {"available": True}},
        }

        def fake_facts_builder(prefix):
            calls.append(len(prefix))
            return {
                "latest_date": str(prefix["date"].iloc[-1])[:10],
                "structure": {
                    "rectangle": {"available": len(prefix) >= 5},
                },
            }

        timeline = build_v2_facts_timeline(
            frame,
            lookback=3,
            facts_builder=fake_facts_builder,
            known_facts_by_idx={len(frame) - 1: known_latest},
        )

        self.assertEqual(calls, [5, 6, 7])
        self.assertEqual(timeline.built_count, 3)
        self.assertEqual(timeline.reused_count, 1)
        self.assertIs(timeline.points[-1].facts, known_latest)

    def test_v2_facts_timeline_cache_reuses_only_unchanged_prefixes(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-09-01", periods=8, freq="D"),
            "close": range(8),
        })
        calls = []

        def fake_facts_builder(prefix):
            calls.append(len(prefix))
            return {"rows": len(prefix)}

        cache = V2FactsTimelineCache(max_entries=2)
        first = build_v2_facts_timeline(
            frame,
            lookback=3,
            facts_builder=fake_facts_builder,
        )
        cache.store("daily:600001", frame, first)
        appended = pd.concat([
            frame,
            pd.DataFrame({"date": [pd.Timestamp("2026-09-09")], "close": [8]}),
        ], ignore_index=True)
        second = build_v2_facts_timeline(
            appended,
            lookback=3,
            facts_builder=fake_facts_builder,
            known_facts_by_idx=cache.known_facts("daily:600001", appended),
        )

        self.assertEqual(second.built_count, 1)
        self.assertEqual(second.reused_count, 3)
        cache.store("daily:600001", appended, second)

        revised = appended.copy()
        revised.loc[7, "close"] = 70
        third = build_v2_facts_timeline(
            revised,
            lookback=3,
            facts_builder=fake_facts_builder,
            known_facts_by_idx=cache.known_facts("daily:600001", revised),
        )
        self.assertEqual(third.built_count, 2)
        self.assertEqual(third.reused_count, 2)

        renamed = appended.rename(columns={"close": "price"})
        self.assertEqual(cache.known_facts("daily:600001", renamed), {})

    def test_cached_v2_events_build_only_appended_fact_point(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-09-01", periods=8, freq="D"),
            "open": range(8),
            "high": range(1, 9),
            "low": range(8),
            "close": range(8),
        })
        calls = []

        def fake_event_facts(prefix):
            calls.append(len(prefix))
            return {
                "setup": {},
                "repair": {},
                "risk": {},
                "structure": {"fractals": {}, "rectangle": {}},
                "exit_gate": {},
                "trigger": {},
            }

        scope = "test-incremental:600001:daily"
        with patch(
            "stock_analyzer.v2_facts_timeline.build_c_signal_v2_event_facts",
            side_effect=fake_event_facts,
        ):
            events_module.build_v2_signal_events_cached(
                frame,
                lookback=3,
                cache_scope=scope,
            )
            first_call_count = len(calls)
            appended = pd.concat([
                frame,
                pd.DataFrame({
                    "date": [pd.Timestamp("2026-09-09")],
                    "open": [8],
                    "high": [9],
                    "low": [8],
                    "close": [8],
                }),
            ], ignore_index=True)
            events_module.build_v2_signal_events_cached(
                appended,
                lookback=3,
                cache_scope=scope,
            )

        self.assertEqual(first_call_count, 4)
        self.assertEqual(len(calls) - first_call_count, 1)

    def test_v2_signal_events_can_consume_injected_facts_without_building(self):
        frame = self._minimal_signal_frame(rows=1)
        known_facts = {
            "setup": {"bottom_divergence": True},
            "structure": {},
            "trigger": {},
            "exit_gate": {},
            "repair": {},
            "risk": {},
        }

        def forbidden_facts_builder(_prefix):
            raise AssertionError("facts builder should not be called when facts are injected")

        events = build_v2_signal_events(
            frame,
            known_facts_by_idx={0: known_facts},
            facts_builder=forbidden_facts_builder,
        )

        self.assertEqual([event.key for event in events], ["v2_bottom_research"])

    def test_v2_event_facts_profile_matches_full_facts_for_events(self):
        frame = self._v2_trigger_frame()

        full_events = build_v2_signal_events(frame, facts_builder=build_c_signal_v2_facts)
        event_profile_events = build_v2_signal_events(frame, facts_builder=build_c_signal_v2_event_facts)

        def stable(events):
            return [
                (event.key, event.group, event.date, event.coord_price, event.price, event.reason, event.value)
                for event in events
            ]

        self.assertEqual(stable(event_profile_events), stable(full_events))

        event_facts = build_c_signal_v2_event_facts(frame)
        self.assertEqual(event_facts["source"], "c_signal_v2_event_facts")
        self.assertIn("setup", event_facts)
        self.assertIn("structure", event_facts)
        self.assertIn("trigger", event_facts)
        self.assertIn("exit_gate", event_facts)
        self.assertIn("repair", event_facts)
        self.assertNotIn("macro_tide", event_facts)
        self.assertNotIn("legacy_experience", event_facts)

    def test_v2_event_facts_benchmark_reports_zero_diff(self):
        from scripts.benchmark_v2_event_facts import benchmark_event_facts, stable_event_signature

        frame = self._v2_trigger_frame()
        result = benchmark_event_facts(frame, lookback=6, repeat=1)

        self.assertTrue(result["zero_diff"])
        self.assertEqual(result["repeat"], 1)
        self.assertEqual(result["full_signature"], result["event_signature"])
        self.assertEqual(stable_event_signature(build_v2_signal_events(frame)), result["event_signature"])
        self.assertGreaterEqual(result["full_facts"]["avg_seconds"], 0)
        self.assertGreaterEqual(result["event_facts"]["avg_seconds"], 0)
        self.assertIn("speedup", result)

    def test_signal_event_stats_match_intraday_event_dates(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01 09:30", periods=8, freq="60min"),
            "close": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4],
        })
        event = SignalEvent(
            key="v2_attack_day",
            group="v2",
            date="2026-01-01 11:30",
            coord_price=10.4,
            price=10.4,
        )

        stats = evaluate_signal_events(frame, [event], horizon=2)

        self.assertEqual(stats["by_signal"]["v2_attack_day"]["count"], 1)
        self.assertEqual(stats["by_signal"]["v2_attack_day"]["evaluated_count"], 1)

    def test_signal_event_stats_ignore_nan_returns(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=4, freq="D"),
            "open": [10.0, float("nan"), 10.4, 10.6],
            "close": [10.0, 10.2, float("nan"), 10.6],
        })
        event_close = SignalEvent(
            key="v2_attack_day",
            group="v2",
            date="2026-01-01",
            coord_price=10.0,
            price=10.0,
        )
        next_open = SignalEvent(
            key="v2_breakout",
            group="v2",
            date="2026-01-01",
            coord_price=10.0,
            price=10.0,
        )

        close_stats = evaluate_signal_events(frame, [event_close], horizon=2)
        open_stats = evaluate_signal_events(frame, [next_open], horizon=1, entry_model="next_open")

        self.assertEqual(close_stats["by_signal"]["v2_attack_day"]["count"], 1)
        self.assertEqual(close_stats["by_signal"]["v2_attack_day"]["evaluated_count"], 0)
        self.assertIsNone(close_stats["by_signal"]["v2_attack_day"]["avg_ret"])
        self.assertEqual(open_stats["by_signal"]["v2_breakout"]["count"], 1)
        self.assertEqual(open_stats["by_signal"]["v2_breakout"]["evaluated_count"], 0)

    def test_c_signal_v2_macro_tide_flags_explicit_downtrend(self):
        frame = self._v2_long_macro_frame(macro="down")

        macro_tide = build_macro_tide_facts(frame)

        self.assertEqual(macro_tide["permission"], "forbidden")
        self.assertIn("ma60", macro_tide)
        self.assertEqual(macro_tide["ma250"]["permission"], "forbidden")
        self.assertFalse(macro_tide["ma250"]["above"])
        self.assertLess(macro_tide["ma250"]["slope_pct"], 0)
        self.assertTrue(macro_tide["block_reasons"])

    def test_c_signal_v2_momentum_facts_detect_power_flip(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "open": [10.0, 10.0, 10.0],
            "high": [11.0, 11.0, 11.0],
            "low": [9.0, 9.0, 9.0],
            "close": [10.0, 9.4, 10.8],
            "williams_r": [70.0, 65.0, 35.0],
        })

        facts = build_momentum_facts(frame)

        self.assertEqual(facts["balance"], 0.8)
        self.assertEqual(facts["previous_balance"], -0.6)
        self.assertEqual(facts["balance_ma3"], 0.067)
        self.assertTrue(facts["power_flip"])
        self.assertTrue(facts["williams_r_power_cross"])

    def test_c_signal_v2_normalized_bars_merge_inclusions_with_original_mapping(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "open": [9.2, 10.0, 10.4, 8.0, 8.6, 9.2],
            "high": [10.0, 11.0, 10.8, 10.5, 11.0, 12.0],
            "low": [8.0, 9.0, 9.4, 7.0, 8.5, 9.0],
            "close": [9.6, 10.6, 10.5, 8.2, 10.4, 11.4],
        })

        normalized = build_normalized_bar_facts(frame)
        fractals = build_williams_fractal_facts(frame)

        self.assertEqual(normalized["original_count"], 6)
        self.assertEqual(normalized["normalized_count"], 5)
        self.assertEqual(normalized["containment_count"], 1)
        self.assertEqual(normalized["merge_count"], 1)
        merged_bar = normalized["bars"][1]
        self.assertEqual(merged_bar["source_dates"], ["2026-01-02", "2026-01-03"])
        self.assertEqual(merged_bar["merge_direction"], "up")
        self.assertEqual(merged_bar["low"], 9.4)
        self.assertTrue(fractals["normalization_used"])
        self.assertEqual(fractals["latest_bottom"]["date"], "2026-01-04")
        self.assertEqual(fractals["latest_bottom"]["analysis_date"], "2026-01-04")
        self.assertEqual(fractals["latest_bottom"]["price_source_index"], 3)

    def test_c_signal_v2_rectangle_candidates_keep_macro_as_context(self):
        rows = 260
        frame = self._minimal_signal_frame(rows=rows)
        frame["high"] = [12.0] * 200 + [10.8] * 60
        frame["low"] = [8.0] * 200 + [9.8] * 60
        frame["close"] = [9.0 if i % 2 else 11.0 for i in range(200)] + [10.2 if i % 2 else 10.5 for i in range(60)]

        candidates = build_rectangle_candidate_facts(frame)

        self.assertTrue(candidates["available"])
        self.assertIsNotNone(candidates["short_rectangle"])
        self.assertIsNotNone(candidates["swing_rectangle"])
        self.assertIsNotNone(candidates["macro_rectangle"])
        self.assertIn(candidates["active_rectangle"]["family"], {"short", "swing"})
        self.assertNotEqual(candidates["active_rectangle"]["family"], "macro")
        self.assertEqual(candidates["macro_rectangle"]["family"], "macro")
        self.assertIn("previous_upper", candidates["macro_rectangle"])
        self.assertIn("breaks_previous_upper", candidates["macro_rectangle"])
        self.assertIn("优先使用", candidates["active_reason"])

    def test_c_signal_v2_bear_trap_recovery_detects_quick_breakout(self):
        frame = self._minimal_signal_frame(rows=16)
        frame["open"] = [10.8] * 13 + [10.6, 10.75, 11.0]
        frame["high"] = [11.0] * 13 + [10.7, 10.9, 11.4]
        frame["low"] = [10.6] * 13 + [10.4, 10.65, 10.9]
        frame["close"] = [10.8] * 13 + [10.65, 10.85, 11.2]

        facts = build_c_signal_v2_facts(frame)
        recovery = facts["structure"]["bear_trap_recovery"]

        self.assertEqual(facts["source"], "c_signal_v2_p19_repair_watch_facts")
        self.assertTrue(recovery["available"])
        self.assertTrue(recovery["recovered"])
        self.assertTrue(recovery["breakout_after_recovery"])
        self.assertEqual(recovery["break_date"], "2026-01-14")
        self.assertEqual(recovery["box_lower"], 10.6)
        self.assertEqual(recovery["box_upper"], 11.0)
        self.assertEqual(recovery["stop_price"], 10.4)
        self.assertTrue(facts["structure"]["trigger_observed"])

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_c_signal_v2_state_model_treats_bear_trap_breakout_as_new_breakout_plan(self):
        frame = self._minimal_signal_frame(rows=16)
        frame["open"] = [10.8] * 13 + [10.6, 10.75, 11.0]
        frame["high"] = [11.0] * 13 + [10.7, 10.9, 11.4]
        frame["low"] = [10.6] * 13 + [10.4, 10.65, 10.9]
        frame["close"] = [10.8] * 13 + [10.65, 10.85, 11.2]
        frame["ma20"] = [10.8] * 16
        frame["volume"] = [1000] * 16
        frame["vol_ma20"] = [1000] * 16
        add_legacy_scores(frame, setup=1, confirm=1, risk=0, break_score=0, heat_score=0)

        state = build_c_signal_v2_state(frame, context={"target_price": 13.0})

        self.assertEqual(state["state"], "bear_trap_breakout")
        self.assertEqual(state["signal"], "C突")
        self.assertEqual(state["permission"], "breakout_allowed")
        self.assertEqual(state["v2_permission_model"]["plan_status"], "ready")
        self.assertEqual(state["v2_permission_model"]["signal_key"], "v2_bear_trap_recovery")
        self.assertEqual(state["v2_permission_model"]["plan_gate"]["stop_price"], 10.4)

    def test_opportunity_event_weights_cover_bear_trap_recovery(self):
        self.assertIn("v2_bear_trap_recovery", SCAN_CONFIG["opportunity"]["keys"])
        self.assertGreater(EVENT_WEIGHTS["v2_bear_trap_recovery"], EVENT_WEIGHTS["v2_structure_candidate"])
        self.assertGreaterEqual(EVENT_WEIGHTS["v2_bear_trap_recovery"], EVENT_WEIGHTS["v2_breakout"])

    def test_c_signal_v2_bear_trap_recovery_without_breakout_stays_observation(self):
        frame = self._minimal_signal_frame(rows=16)
        frame["open"] = [10.8] * 13 + [10.6, 10.75, 10.85]
        frame["high"] = [11.0] * 13 + [10.7, 10.9, 10.95]
        frame["low"] = [10.6] * 13 + [10.4, 10.65, 10.75]
        frame["close"] = [10.8] * 13 + [10.65, 10.85, 10.9]
        frame["ma20"] = [10.8] * 16
        frame["volume"] = [1000] * 16
        frame["vol_ma20"] = [1000] * 16
        add_legacy_scores(frame, setup=1, confirm=1, risk=0, break_score=0, heat_score=0)

        facts = build_c_signal_v2_facts(frame)
        state = build_c_signal_v2_state(frame, context={"target_price": 13.0})

        self.assertTrue(facts["structure"]["bear_trap_recovery"]["recovered"])
        self.assertFalse(facts["structure"]["bear_trap_recovery"]["breakout_after_recovery"])
        self.assertNotEqual(state["v2_permission_model"].get("signal_key"), "v2_bear_trap_recovery")
        self.assertNotEqual(state["state"], "bear_trap_breakout")
        self.assertFalse(state["requires_trade_plan"])
        self.assertEqual(state["candidate_substate"], "strong_repair_watch")
        self.assertEqual(state["candidate_display_label"], "待触")
        self.assertEqual(state["candidate_confirmation_price"], 11.0)
        self.assertIn("突破确认价", state["candidate_missing_confirmations"])
        trigger_plan = state["candidate_trigger_plan"]
        self.assertEqual(trigger_plan["status"], "pending_trigger")
        self.assertFalse(trigger_plan["is_buy_point"])
        self.assertEqual(trigger_plan["confirmation_price"], 11.0)
        self.assertIn("不是买点", trigger_plan["summary"])
        self.assertIn("次日收盘有效突破", trigger_plan["next_session_rule"])

    def test_c_signal_v2_rectangle_c_point_uses_lowest_close_not_intraday_low(self):
        frame = self._minimal_signal_frame(rows=10)
        frame["high"] = [10.5, 10.4, 10.3, 10.2, 10.4, 10.5, 10.3, 10.2, 10.4, 10.5]
        frame["low"] = [9.8, 9.7, 9.6, 8.8, 9.5, 9.6, 9.7, 9.8, 9.7, 9.8]
        frame["close"] = [10.1, 10.0, 9.9, 9.6, 9.8, 9.9, 10.0, 10.1, 10.2, 10.3]

        rectangle = build_rectangle_facts(frame)

        self.assertTrue(rectangle["available"])
        self.assertEqual(rectangle["lower"], 8.8)
        self.assertEqual(rectangle["lowest_close"], 9.6)
        self.assertEqual(rectangle["c_point"], 9.6)
        self.assertEqual(rectangle["invalidation_price"], 9.6)

    def test_c_signal_v2_trigger_facts_separate_loose_and_strict_attack_day(self):
        frame = self._minimal_signal_frame(rows=4)
        frame["open"] = [10.0, 10.1, 10.2, 10.3]
        frame["high"] = [10.2, 10.3, 10.4, 10.9]
        frame["low"] = [9.8, 9.9, 10.0, 10.2]
        frame["close"] = [10.1, 10.2, 10.1, 10.8]
        frame["volume"] = [1000, 1000, 1000, 1600]
        frame["vol_ma20"] = [1000] * 4

        trigger = build_trigger_facts(frame)

        self.assertFalse(trigger["attack_day"])
        self.assertTrue(trigger["loose_attack_day"])
        self.assertFalse(trigger["strict_attack"]["triggered"])

    def test_c_signal_v2_trigger_facts_detect_gap_fill_reversal(self):
        frame = self._minimal_signal_frame(rows=3)
        frame["open"] = [10.0, 10.1, 9.8]
        frame["high"] = [10.3, 10.4, 10.25]
        frame["low"] = [9.8, 10.0, 9.7]
        frame["close"] = [10.1, 10.2, 10.15]

        trigger = build_trigger_facts(frame)

        self.assertTrue(trigger["gap_fill_reversal"])
        self.assertEqual(trigger["gap_fill"]["gap_down_pct"], -3.92)
        self.assertTrue(trigger["gap_fill"]["filled_previous_close"])
        self.assertEqual(trigger["gap_fill"]["stop_price"], 9.7)

    def _weekly_close_frame(self, business_days):
        closes = [10.0 + (0.3 if (index // 5) % 2 else -0.3) for index in range(business_days)]
        return pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=business_days),
            "open": closes,
            "high": [value + 0.1 for value in closes],
            "low": [value - 0.1 for value in closes],
            "close": closes,
        })

    def test_macro_tide_weekly_macd_excludes_forming_week(self):
        # 截到最后一个完整交易周之前的周三，形成中周不得参与判定。
        frame = self._weekly_close_frame(427).iloc[:-4]
        self.assertEqual(frame["date"].iloc[-1].dayofweek, 2)

        macro = build_macro_tide_facts(frame)
        weekly = macro["weekly_macd"]

        self.assertTrue(weekly["available"])
        dated = frame[["date", "close"]].copy()
        completed = dated.set_index("date")["close"].resample("W-FRI").last().dropna().to_frame("close").iloc[:-1]
        including_forming = dated.set_index("date")["close"].resample("W-FRI").last().dropna().to_frame("close")
        dif_completed, dea_completed, hist_completed = calculate_macd(completed)
        dif_all, dea_all, hist_all = calculate_macd(including_forming)
        self.assertAlmostEqual(weekly["hist"], round(float(hist_completed.iloc[-1]), 4), places=6)
        self.assertAlmostEqual(weekly["previous_hist"], round(float(hist_completed.iloc[-2]), 4), places=6)
        self.assertGreater(abs(weekly["hist"] - float(hist_all.iloc[-1])), 0.01)

    def test_macro_tide_weekly_macd_requires_sixty_completed_weeks(self):
        short_frame = self._weekly_close_frame(290)  # 58 个完整周
        macro_short = build_macro_tide_facts(short_frame)
        self.assertFalse(macro_short["weekly_macd"]["available"])
        self.assertEqual(macro_short["weekly_macd"]["permission"], "unknown")

        boundary_frame = self._weekly_close_frame(300)  # 60 个完整周，最后一根为周五
        macro_boundary = build_macro_tide_facts(boundary_frame)
        self.assertTrue(macro_boundary["weekly_macd"]["available"])

    def test_unfilled_gap_targets_skip_nan_rows_without_false_fill(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=5, freq="D"),
            "open": [10.0, 10.0, 9.0, 9.05, 9.2],
            "high": [10.5, 10.2, 9.2, float("nan"), 9.4],
            "low": [9.8, 9.9, 8.8, 8.9, 9.0],
            "close": [10.1, 10.0, 9.0, 9.1, 9.2],
        })

        targets = _unfilled_gap_targets(frame, 9.0, lookback=250)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["price"], 9.2)

        filled_frame = frame.copy()
        filled_frame.loc[3, "high"] = 9.95
        self.assertEqual(_unfilled_gap_targets(filled_frame, 9.0, lookback=250), [])

        all_nan_after = frame.copy()
        all_nan_after.loc[3:, "high"] = float("nan")
        self.assertEqual(len(_unfilled_gap_targets(all_nan_after, 9.0, lookback=250)), 1)

    def test_v2_setup_breakout_trigger_requires_fresh_breakout_bar(self):
        # 15 根以内不触发 prior_high 分支，隔离矩形分支的 fresh 守卫。
        rows = 15
        closes = [10.0 + index * 0.08 for index in range(rows)]
        frame = pd.DataFrame({
            "date": pd.bdate_range("2026-01-01", periods=rows),
            "open": closes,
            "high": [value + 0.1 for value in closes],
            "low": [value - 0.1 for value in closes],
            "close": closes,
        })
        rectangle = {"available": True, "previous_upper": 10.6, "previous_lower": 9.8, "lower": 9.8}
        absorbed_bars = {"available": True, "recent_bars": [{"source_indices": [13, 14]}]}
        fresh_bars = {"available": True, "recent_bars": [{"source_indices": [14]}]}

        fresh = build_v2_setup_facts(frame, rectangle=rectangle, normalized_bars=fresh_bars)
        absorbed = build_v2_setup_facts(frame, rectangle=rectangle, normalized_bars=absorbed_bars)

        self.assertTrue(fresh["breakout_setup"])
        self.assertTrue(fresh["breakout_trigger"])
        # 末根被包含合并吸收时，previous_upper 退化为旧箱体，突破触发必须被抑制。
        self.assertTrue(absorbed["breakout_setup"])
        self.assertFalse(absorbed["breakout_trigger"])

    def test_c_signal_v2_state_model_defers_execution_when_macro_sample_insufficient(self):
        frame = self._v2_trigger_frame()

        state = build_c_signal_v2_state(frame, context={"target_price": 15.0})

        self.assertEqual(state["state"], "trigger_plan_waiting")
        self.assertEqual(state["permission"], "watch_only")
        self.assertEqual(state["v2_permission_model"]["plan_status"], "ready")
        self.assertFalse(state["v2_permission_model"]["can_open"])
        self.assertIn("样本不足", state["v2_permission_model"]["reason"])
        self.assertIn("MA250", state["v2_permission_model"]["reason"])

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_c_signal_v2_state_model_promotes_independent_facts_to_attack_plan(self):
        frame = self._v2_trigger_frame()

        state = build_c_signal_v2_state(frame, context={"target_price": 15.0})

        self.assertEqual(state["source"], "c_signal_v2_p19_repair_watch")
        self.assertEqual(state["v2_state_schema_version"], 2)
        self.assertEqual(state["state"], "ignition_triggered")
        self.assertEqual(state["signal"], "C爆")
        self.assertEqual(state["permission"], "attack_allowed")
        self.assertTrue(state["requires_trade_plan"])
        self.assertTrue(state["facts"]["structure"]["candidate"])
        self.assertTrue(state["facts"]["trigger"]["ignition"]["triggered"])
        self.assertEqual(state["permission_context"]["macro_tide_permission"], "unknown")
        self.assertEqual(state["v2_permission_model"]["mode"], "trigger_plan_required")
        self.assertEqual(state["v2_permission_model"]["plan_status"], "ready")

    def test_c_signal_v2_state_model_blocks_entry_when_macro_tide_is_forbidden(self):
        frame = self._v2_long_macro_frame(macro="down")

        state = build_c_signal_v2_state(frame, context={"target_price": 15.0})

        self.assertEqual(state["state"], "macro_veto_blocked")
        self.assertEqual(state["permission"], "forbidden")
        self.assertEqual(state["signal"], "C候")
        self.assertFalse(state["requires_trade_plan"])
        self.assertIsNone(state["v2_permission_model"]["plan_gate"])
        self.assertEqual(state["permission_context"]["macro_tide_permission"], "forbidden")
        self.assertIn("周线 MACD", " / ".join(state["v2_permission_model"]["required_confirmations"]))

    def test_c_signal_v2_permission_vetoes_pullback_when_ma60_is_not_up(self):
        frame = self._v2_legacy_entry_frame("pullback")
        latest = frame.iloc[-1]
        facts = build_c_signal_v2_facts(frame)
        facts["macro_tide"]["ma60"] = {
            "available": True,
            "value": 10.8,
            "slope_pct": -1.2,
            "above": False,
            "up": False,
            "permission": "watch",
            "label": "MA60观察",
            "summary": "价格或 MA60 斜率仍未完全转强。",
        }

        permission = build_c_signal_v2_permission(facts, latest, event_key="composite_pullback", context={"target_price": 12.0})

        self.assertEqual(permission["state"], "macro_veto_blocked")
        self.assertEqual(permission["permission"], "forbidden")
        self.assertIn("MA60 上行", " / ".join(permission["block_reasons"]))

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_c_signal_v2_state_model_promotes_breakout_through_unified_trade_gate(self):
        frame = self._v2_legacy_entry_frame("breakout")

        state = build_c_signal_v2_state(frame, event_key="composite_breakout", context={"target_price": 12.5})

        self.assertEqual(state["state"], "entry_breakout")
        self.assertEqual(state["signal"], "C突")
        self.assertEqual(state["permission"], "breakout_allowed")
        self.assertTrue(state["requires_trade_plan"])
        self.assertEqual(state["v2_permission_model"]["plan_gate"]["entry_type"], "breakout")
        self.assertEqual(state["v2_permission_model"]["plan_status"], "ready")

    def test_c_signal_v2_state_model_blocks_breakout_chase_through_unified_trade_gate(self):
        frame = self._v2_legacy_entry_frame("breakout", return_pct=6.8, ma20=9.55)

        state = build_c_signal_v2_state(frame, event_key="composite_breakout", context={"target_price": 12.5})

        self.assertEqual(state["state"], "trigger_plan_blocked")
        self.assertEqual(state["permission"], "forbidden")
        self.assertEqual(state["signal"], "C候")
        plan_gate = state["v2_permission_model"]["plan_gate"]
        self.assertEqual(plan_gate["entry_type"], "breakout")
        self.assertIn("extended_return", plan_gate["execution_risk_flags"])
        self.assertIn("ma20_extended", plan_gate["execution_risk_flags"])

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_c_signal_v2_state_model_promotes_pullback_through_unified_trade_gate(self):
        frame = self._v2_legacy_entry_frame("pullback")

        state = build_c_signal_v2_state(frame, event_key="composite_pullback", context={"target_price": 12.5})

        self.assertEqual(state["state"], "entry_pullback")
        self.assertEqual(state["signal"], "C回")
        self.assertEqual(state["permission"], "pullback_allowed")
        self.assertTrue(state["requires_trade_plan"])
        self.assertEqual(state["v2_permission_model"]["plan_gate"]["entry_type"], "pullback")

    def test_c_signal_v2_backfill_keeps_entry_snapshot_as_plan_review(self):
        state = build_c_signal_v2_state_from_result({
            "scan_type": "opportunity",
            "signal_key": "composite_breakout",
            "date": "2026-09-08",
            "setup_score": 2,
            "confirm_score": 4,
            "risk_score": 0,
        })

        self.assertEqual(state["source"], "scan_result_backfill_p6_trade_gate")
        self.assertEqual(state["state"], "entry_breakout")
        self.assertEqual(state["signal"], "C突")
        self.assertEqual(state["permission"], "watch_only")
        self.assertEqual(state["permission_label"], "计划待核")

    def test_c_signal_v2_backfill_maps_v2_breakout_to_breakout_gate(self):
        state = build_c_signal_v2_state_from_result({
            "scan_type": "opportunity",
            "signal_key": "v2_breakout",
            "v2_plan_status": "ready",
            "date": "2026-09-08",
            "setup_score": 2,
            "confirm_score": 4,
            "risk_score": 0,
        })

        self.assertEqual(state["state"], "entry_breakout")
        self.assertEqual(state["signal"], "C突")
        self.assertEqual(state["permission"], "breakout_allowed")

    def test_c_signal_v2_backfill_keeps_top_fractal_risk_as_observation(self):
        state = build_c_signal_v2_state_from_result({
            "scan_type": "risk",
            "signal_key": "v2_top_fractal_risk",
            "date": "2026-09-08",
            "risk_score": 3,
        })

        self.assertEqual(state["state"], "observe_top_fractal")
        self.assertEqual(state["signal"], "C研")
        self.assertEqual(state["role"], "watch")
        self.assertEqual(state["permission"], "watch_only")
        self.assertEqual(state["permission_label"], "只观察")
        self.assertEqual(state["trade_intent"], "watch_only")

    def test_c_signal_v2_backfill_marks_no_box_repair_with_clear_target_as_pending_trigger(self):
        state = build_c_signal_v2_state_from_result({
            "scan_type": "opportunity",
            "signal_key": "v2_structure_candidate",
            "date": "2026-09-11",
            "setup_score": 1,
            "confirm_score": 0,
            "risk_score": 0,
            "v2_state_model": {
                "state": "structure_candidate",
                "permission": "structure_only",
                "facts": {
                    "setup": {"repair_impulse": True},
                    "structure": {
                        "candidate": True,
                        "rectangle": {"available": False},
                        "fractals": {"latest_bottom": {"price": 8.51}},
                    },
                    "macro_tide": {"ma250": {"above": True}},
                    "target_structure": {
                        "selected_breakout_target": {
                            "price": 10.1,
                            "strength_score": 98,
                            "distance_pct": 10.87,
                        },
                    },
                },
            },
        })

        self.assertEqual(state["candidate_substate"], "strong_repair_watch")
        self.assertEqual(state["candidate_display_label"], "待触")
        self.assertEqual(state["candidate_confirmation_price"], 10.1)
        self.assertEqual(state["candidate_invalidation_price"], 8.51)
        self.assertEqual(state["candidate_trigger_plan"]["status"], "pending_trigger")
        self.assertIn("突破确认价", state["candidate_trigger_plan"]["missing_confirmations"])
        self.assertEqual(state["candidate_trigger_plan"]["confirmation_price"], 10.1)
        self.assertFalse(state["requires_trade_plan"])

    def test_c_signal_v2_state_model_blocks_trigger_when_plan_space_is_insufficient(self):
        frame = self._v2_trigger_frame()

        state = build_c_signal_v2_state(frame)

        self.assertEqual(state["state"], "trigger_plan_waiting")
        self.assertEqual(state["permission"], "watch_only")
        self.assertEqual(state["signal"], "C候")
        self.assertFalse(state["requires_trade_plan"])
        self.assertEqual(state["v2_permission_model"]["plan_status"], "waiting")
        self.assertIn("确认至少 2R 的目标空间", state["v2_permission_model"]["required_confirmations"])
        self.assertEqual(state["v2_permission_model"]["plan_gate"]["target_source"], "breakout_target_missing")
        self.assertEqual(state["candidate_substate"], "reversal_confirmed")
        self.assertEqual(state["candidate_display_label"], "触")

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_c_signal_v2_state_model_uses_upper_resistance_for_attack_target(self):
        frame = self._v2_trigger_frame_with_upper_target()

        state = build_c_signal_v2_state(frame)

        self.assertEqual(state["state"], "ignition_triggered")
        self.assertEqual(state["permission"], "attack_allowed")
        plan_gate = state["v2_permission_model"]["plan_gate"]
        self.assertIn(plan_gate["target_source"], {"macro_rectangle_upper", "prior_high_120", "prior_high_250"})
        self.assertEqual(plan_gate["target_price"], 14.0)
        self.assertGreaterEqual(plan_gate["risk_reward_ratio"], 2)

    @patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"})
    @patch("app.fetch_and_process_data", return_value={
        "stock_code": "600063",
        "dates": ["2026-05-08"],
        "stats_composite": {"b": {"count": 1, "win_rate": float("nan"), "avg_ret": float("nan")}},
    })
    def test_analyze_api_returns_strict_json_for_nan_values(self, mock_fetch, mock_profile):
        response = app.app.test_client().get("/api/analyze?code=600063")

        raw_payload = response.get_data(as_text=True)
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("NaN", raw_payload)
        self.assertIsNone(payload["stats_composite"]["b"]["win_rate"])
        self.assertIsNone(payload["stats_composite"]["b"]["avg_ret"])

    @patch("app.get_stock_profile", return_value={"code": "600063", "name": "示例股票", "sector": "半导体", "concepts": ["AI芯片"]})
    def test_stock_profiles_api_returns_name_and_sector(self, mock_profile):
        response = app.app.test_client().post("/api/stock_profiles", json={"codes": ["600063", "sh600063", "bad"]})

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["profiles"]["600063"]["name"], "示例股票")
        self.assertEqual(payload["profiles"]["600063"]["sector"], "半导体")
        self.assertEqual(payload["profiles"]["600063"]["concepts"], ["AI芯片"])

    @patch("app.concept_refresh_job_manager.current_job", return_value=None)
    @patch("app.stock_service.get_stock_concepts_status", return_value={
        "available": True,
        "stock_count": 120,
        "concept_count": 18,
        "updated_at": "2026-05-11T08:00:00",
        "source": "eastmoney_concept_boards",
    })
    def test_stock_concepts_status_api_returns_cache_status(self, mock_status, mock_current):
        response = app.app.test_client().get("/api/stock_concepts/status")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["cache"]["stock_count"], 120)
        self.assertIsNone(payload["job"])

    @patch("app.concept_refresh_job_manager.start_job", return_value={"id": "job1", "status": "queued"})
    def test_stock_concepts_refresh_api_starts_background_job(self, mock_start):
        response = app.app.test_client().post("/api/stock_concepts/refresh", json={"max_concepts": 3})

        payload = response.get_json()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["id"], "job1")
        mock_start.assert_called_once()

    @patch("app.collect_data_source_status", return_value={"overall": {"status": "ready"}, "sources": []})
    def test_data_sources_api_uses_default_cache_ttl(self, mock_status):
        response = app.app.test_client().get("/api/data_sources?refresh=1")

        self.assertEqual(response.status_code, 200)
        kwargs = mock_status.call_args.kwargs
        self.assertTrue(kwargs["use_cache"])
        self.assertTrue(kwargs["force_refresh"])
        self.assertNotIn("cache_ttl_seconds", kwargs)

    def test_unknown_api_route_returns_json_404(self):
        response = app.app.test_client().get("/api/not_found_demo")

        payload = response.get_json()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content_type, "application/json")
        self.assertEqual(payload["error"], "not_found")
        self.assertEqual(payload["path"], "/api/not_found_demo")

    def test_board_market_api_is_explicitly_retired(self):
        response = app.app.test_client().get("/api/board_market?type=concept&name=存储芯片")

        payload = response.get_json()
        self.assertEqual(response.status_code, 410)
        self.assertEqual(payload["status"], "retired")
        self.assertIn("候选分布", payload["error"])

    def test_board_market_refresh_api_is_explicitly_retired(self):
        response = app.app.test_client().post("/api/board_market/refresh", json={"type": "industry"})

        payload = response.get_json()
        self.assertEqual(response.status_code, 410)
        self.assertEqual(payload["status"], "retired")

    def test_filter_workspace_candidates_returns_target_page(self):
        workspace = {
            "pools": {
                "opportunity": {
                    "count": 3,
                    "results": [
                        {"code": "600001", "name": "样本A", "sector": "半导体", "concepts": ["存储芯片"], "rank_score": 80},
                        {"code": "600002", "name": "样本B", "sector": "半导体", "concepts": ["人工智能"], "rank_score": 70},
                        {"code": "600003", "name": "样本C", "sector": "医药", "concepts": ["创新药"], "rank_score": 60},
                    ],
                }
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        payload = filter_workspace_candidates(
            workspace,
            scan_type="opportunity",
            sector="半导体",
            query="样本",
            limit=1,
            offset=0,
        )

        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["results"][0]["code"], "600001")

    def test_workspace_pool_index_centralizes_page_metadata_and_mapping(self):
        workspace = {
            "pools": {
                "risk": {
                    "count": 4,
                    "results": [
                        {"code": "600001", "risk_score": 1},
                        {"code": "600002", "risk_score": 4},
                        {"code": "600003", "risk_score": 5},
                    ],
                },
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-10",
            "history_mode": True,
            "history_snapshot_day": "2026-05-11",
        }

        index = workspace_pool_index(workspace, "risk")
        payload = workspace_pool_page(
            index,
            matcher=lambda item: item.get("risk_score", 0) >= 4,
            limit=1,
            offset=0,
            result_mapper=lambda item: {"code": item["code"], "_compact": True},
        )

        self.assertEqual(index.pool_count, 4)
        self.assertEqual(payload["scan_type"], "risk")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["pool_count"], 4)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["latest_data_date"], "2026-05-10")
        self.assertEqual(payload["results"], [{"code": "600002", "_compact": True}])

    def test_filter_workspace_candidates_filters_v2_reasons(self):
        workspace = {
            "pools": {
                "opportunity": {
                    "count": 3,
                    "results": [
                        {
                            "code": "600001",
                            "name": "计划放行",
                            "v2_signal": "C回",
                            "v2_priority_group": "trade_ready",
                            "v2_state_model": {
                                "signal": "C回",
                                "state": "entry_ready",
                                "permission": "attack_allowed",
                                "next_action": "MA250顺风，计划达到 2R",
                                "v2_permission_model": {
                                    "plan_gate": {
                                        "status": "ready",
                                        "target_label": "目标达到 2R",
                                    },
                                },
                            },
                        },
                        {
                            "code": "600002",
                            "name": "赔率拦截",
                            "v2_signal": "C突",
                            "v2_state_model": {
                                "signal": "C突",
                                "state": "trigger_plan_blocked",
                                "permission": "watch_only",
                                "v2_permission_model": {
                                    "plan_gate": {
                                        "status": "blocked",
                                        "block_reasons": ["收益风险比低于 2:1"],
                                    },
                                },
                            },
                        },
                        {
                            "code": "600003",
                            "name": "大势否决",
                            "v2_signal": "C爆",
                            "v2_state_model": {
                                "signal": "C爆",
                                "state": "macro_veto_blocked",
                                "permission": "forbidden",
                                "v2_permission_model": {
                                    "block_reasons": ["C突/C爆 位于 MA250 下方，突破诱多风险过高"],
                                },
                            },
                        },
                    ],
                }
            }
        }

        ready = filter_workspace_candidates(workspace, scan_type="opportunity", reason="plan_ready")
        rr_blocked = filter_workspace_candidates(workspace, scan_type="opportunity", reason="rr")
        macro_blocked = filter_workspace_candidates(workspace, scan_type="opportunity", reason="ma250")

        self.assertEqual([item["code"] for item in ready["results"]], ["600001"])
        self.assertEqual([item["code"] for item in rr_blocked["results"]], ["600002"])
        self.assertEqual([item["code"] for item in macro_blocked["results"]], ["600003"])
        self.assertNotIn("600001", [item["code"] for item in rr_blocked["results"]])
        self.assertNotIn("600001", [item["code"] for item in macro_blocked["results"]])

    @patch("app.collect_scan_workspace")
    def test_scan_workspace_candidates_api_filters_locally(self, mock_workspace):
        mock_workspace.return_value = {
            "pools": {
                "opportunity": {
                    "count": 2,
                    "results": [
                        {
                            "code": "600001",
                            "name": "样本A",
                            "sector": "半导体",
                            "concepts": ["存储芯片"],
                            "v2_state_model": {
                                "v2_permission_model": {"plan_gate": {"status": "ready"}},
                            },
                        },
                        {
                            "code": "600002",
                            "name": "样本B",
                            "sector": "半导体",
                            "concepts": ["创新药"],
                            "v2_state_model": {
                                "v2_permission_model": {
                                    "plan_gate": {
                                        "status": "blocked",
                                        "block_reasons": ["收益风险比低于 2:1"],
                                    },
                                },
                            },
                        },
                    ],
                }
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&sector=半导体&reason=plan_ready&limit=20&refresh=1"
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["code"], "600001")
        self.assertEqual(payload["filters"]["reason"], "plan_ready")
        _, kwargs = mock_workspace.call_args
        self.assertEqual(kwargs["replay_entry_model"], "event_close")
        self.assertTrue(kwargs["latest_only"])
        self.assertFalse(kwargs["include_history_comparison"])

    @patch("stock_analyzer.web.scan_api.get_cached_compact_workspace_response")
    @patch("app.collect_scan_workspace")
    def test_lite_workspace_and_candidates_share_raw_cache(self, mock_workspace, mock_compact_cache):
        app.clear_scan_workspace_cache()
        mock_compact_cache.side_effect = lambda key, fingerprint, factory, force_refresh=False: factory()
        mock_workspace.return_value = {
            "max_items": 6000,
            "pools": {
                "opportunity": {
                    "count": 2,
                    "loaded_count": 2,
                    "has_more": False,
                    "results": [
                        {"code": "600001", "name": "样本A", "sector": "半导体", "concepts": []},
                        {"code": "600002", "name": "样本B", "sector": "半导体", "concepts": []},
                    ],
                },
                "risk": {"count": 0, "loaded_count": 0, "has_more": False, "results": []},
                "bottom_div": {"count": 0, "loaded_count": 0, "has_more": False, "results": []},
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        client = app.app.test_client()
        candidates_response = client.get(
            "/api/scan_workspace/candidates?scan_type=opportunity&limit=1&include_replay=1"
        )
        workspace_response = client.get("/api/scan_workspace?lite=1&active_type=opportunity&limit=1")

        candidates_payload = candidates_response.get_json()
        workspace_payload = workspace_response.get_json()
        self.assertEqual(candidates_response.status_code, 200)
        self.assertEqual(workspace_response.status_code, 200)
        self.assertEqual(candidates_payload["loaded_count"], 1)
        self.assertEqual(workspace_payload["pools"]["opportunity"]["loaded_count"], 1)
        self.assertEqual(workspace_payload["pools"]["opportunity"]["count"], 2)
        self.assertEqual(mock_workspace.call_count, 1)
        _, kwargs = mock_workspace.call_args
        self.assertEqual(kwargs["max_items"], 6000)
        self.assertEqual(kwargs["overview_limit"], 80)
        self.assertEqual(kwargs["pool_stats_limit"], 80)
        self.assertTrue(kwargs["latest_only"])
        self.assertFalse(kwargs["include_history_comparison"])

    @patch("stock_analyzer.web.scan_api.get_cached_compact_workspace_response")
    @patch("app.collect_scan_workspace")
    def test_historical_lite_workspace_and_candidates_do_not_share_different_factories(
        self,
        mock_workspace,
        mock_compact_cache,
    ):
        app.clear_scan_workspace_cache()
        mock_compact_cache.side_effect = lambda key, fingerprint, factory, force_refresh=False: factory()
        mock_workspace.return_value = {
            "pools": {
                "opportunity": {"count": 0, "results": []},
                "risk": {"count": 0, "results": []},
                "bottom_div": {"count": 0, "results": []},
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        client = app.app.test_client()
        client.get(
            "/api/scan_workspace/candidates?scan_type=opportunity&snapshot_day=2026-05-11"
        )
        client.get(
            "/api/scan_workspace?lite=1&active_type=opportunity&snapshot_day=2026-05-11"
        )

        self.assertEqual(mock_workspace.call_count, 2)
        self.assertEqual(
            {call.kwargs["include_history_comparison"] for call in mock_workspace.call_args_list},
            {True, False},
        )

    @patch("app.collect_scan_workspace")
    def test_scan_workspace_candidates_api_can_request_full_workspace_profile(self, mock_workspace):
        mock_workspace.return_value = {
            "pools": {
                "opportunity": {
                    "count": 1,
                    "results": [
                        {"code": "600001", "name": "样本A", "sector": "半导体", "concepts": ["存储芯片"]},
                    ],
                }
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&limit=20&lite=0&include_replay=1&profile=1&entry_model=next_open"
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["performance"]["mode"], "full")
        self.assertEqual(payload["performance"]["entry_model"], "next_open")
        _, kwargs = mock_workspace.call_args
        self.assertEqual(kwargs["replay_entry_model"], "next_open")
        self.assertFalse(kwargs["latest_only"])

    @patch("app.collect_scan_workspace")
    def test_scan_workspace_lite_compacts_heavy_candidate_fields(self, mock_workspace):
        mock_workspace.return_value = {
            "scanned_count": 1,
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
            "pools": {
                "opportunity": {
                    "count": 1,
                    "loaded_count": 1,
                    "has_more": False,
                    "results": [
                        {
                            "code": "600001",
                            "name": "样本A",
                            "scan_type": "opportunity",
                            "sector": "半导体",
                            "concepts": ["存储芯片"],
                            "v2_state_model": {
                                "version": "2",
                                "state": "entry_breakout",
                                "permission": "breakout_allowed",
                                "signal": "C突",
                                "requires_trade_plan": True,
                                "facts": {
                                    "source": "c_signal_v2_p11_exit_gate_facts",
                                    "structure": {
                                        "rectangle": {"available": True, "width_pct": 9.2},
                                        "resistance_zones": [{"price": 12.3}],
                                    },
                                    "target_structure": {
                                        "selected_breakout_target": {"price": 12.3, "label": "前高"},
                                        "resistance_zones": [{"price": 12.3}],
                                    },
                                    "macro_tide": {"permission": "allowed", "label": "顺风"},
                                    "exit_gate": {"marker_role": "observe", "summary": "观察"},
                                },
                                "v2_permission_model": {
                                    "plan_gate": {"status": "ready", "target_price": 12.3}
                                },
                            },
                            "trade_plan": {
                                "status": "ready",
                                "technical_structures": {
                                    "williams_clock": {"state": "neutral"},
                                    "resistance_zones": [{"price": 12.3}],
                                },
                            },
                            "profile_relations": [{"relation_name": "完整明细"}],
                            "profile_relation_groups": [
                                {"key": "core_business", "label": "主营", "count": 1, "relations": [{"name": "重字段"}]}
                            ],
                        }
                    ],
                }
            },
        }

        response = app.app.test_client().get("/api/scan_workspace?lite=1&limit=1&refresh=1")

        payload = response.get_json()
        result = payload["pools"]["opportunity"]["results"][0]
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["compact"])
        self.assertTrue(result["_compact"])
        self.assertNotIn("profile_relations", result)
        self.assertNotIn("resistance_zones", result["v2_state_model"]["facts"]["target_structure"])
        self.assertEqual(result["v2_state_model"]["facts"]["target_structure"]["selected_breakout_target"]["price"], 12.3)
        self.assertNotIn("trade_plan", result)

    @patch("app.collect_scan_workspace")
    def test_scan_workspace_candidate_detail_keeps_full_candidate_fields(self, mock_workspace):
        mock_workspace.return_value = {
            "pools": {
                "opportunity": {
                    "count": 1,
                    "results": [
                        {
                            "code": "600001",
                            "name": "样本A",
                            "scan_type": "opportunity",
                            "sector": "半导体",
                            "concepts": ["存储芯片"],
                            "v2_state_model": {"facts": {"target_structure": {"resistance_zones": [{"price": 12.3}]}}},
                            "trade_plan": {"technical_structures": {"resistance_zones": [{"price": 12.3}]}},
                            "profile_relations": [{"relation_name": "完整明细"}],
                        }
                    ],
                }
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        compact_response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&code=600001&limit=1&refresh=1"
        )
        detail_response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&code=600001&sector=半导体&limit=1&detail=1&refresh=1"
        )

        compact = compact_response.get_json()["results"][0]
        detail = detail_response.get_json()["results"][0]
        self.assertTrue(compact["_compact"])
        self.assertNotIn("profile_relations", compact)
        self.assertNotIn("_compact", detail)
        self.assertIn("profile_relations", detail)
        self.assertIn("resistance_zones", detail["v2_state_model"]["facts"]["target_structure"])

    @patch("stock_analyzer.web.scan_api.scan_snapshot.read_latest_scan_snapshot")
    def test_scan_workspace_candidate_detail_can_read_exact_snapshot(self, mock_snapshot):
        mock_snapshot.return_value = {
            "code": "600001",
            "name": "样本A",
            "snapshot_day": "20260511",
            "data_date": "2026-05-11",
            "results": {
                "opportunity": {
                    "code": "600001",
                    "name": "样本A",
                    "scan_type": "opportunity",
                    "sector": "半导体",
                    "concepts": ["存储芯片"],
                    "profile_relations": [{"relation_name": "完整明细"}],
                },
            },
        }

        response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&code=600001&limit=1&detail=1&profile=1"
        )

        payload = response.get_json()
        result = payload["results"][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["performance"]["mode"], "detail_snapshot")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(result["code"], "600001")
        self.assertIn("profile_relations", result)
        self.assertNotIn("_compact", result)

    @patch("stock_analyzer.web.scan_api.scan_snapshot.read_latest_scan_snapshot")
    def test_scan_workspace_candidate_detail_rejects_event_date_mismatch(self, mock_snapshot):
        mock_snapshot.return_value = {
            "code": "600001",
            "name": "样本A",
            "snapshot_day": "20260511",
            "data_date": "2026-05-11",
            "results": {
                "opportunity": {
                    "code": "600001",
                    "name": "样本A",
                    "scan_type": "opportunity",
                    "event_date": "2026-05-11",
                    "date": "2026-05-11",
                },
            },
        }

        response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&code=600001&event_date=2026-05-10&limit=1&detail=1"
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["filters"]["event_date"], "2026-05-10")

    def test_sector_overview_tracks_active_days_for_structure_width(self):
        pools = {
            "opportunity": {
                "results": [
                    {"code": "600001", "sector": "半导体", "event_date": "2026-05-10", "rank_score": 70},
                    {"code": "600002", "sector": "半导体", "event_date": "2026-05-11", "rank_score": 80},
                ]
            },
            "risk": {"results": []},
            "bottom_div": {"results": []},
        }

        overview = build_sector_overview(pools)

        self.assertEqual(overview[0]["sector"], "半导体")
        self.assertEqual(overview[0]["active_day_count"], 2)

    def test_stock_profile_relations_normalize_sector_and_concepts(self):
        relations = build_stock_profile_relations(
            {"sector": "半导体", "concepts": ["存储芯片", "AI芯片"]},
            verified_date="2026-05-11",
        )

        self.assertEqual([item["relation_name"] for item in relations], ["半导体", "存储芯片", "AI芯片"])
        self.assertEqual(relations[0]["relation_kind"], "industry")
        self.assertEqual(relations[0]["relation_type"], "core_business")
        self.assertEqual(relations[0]["evidence_group"], "core_business")
        self.assertEqual(relations[1]["relation_kind"], "concept")
        self.assertEqual(relations[1]["relation_type"], "market_tag")
        self.assertEqual(relations[1]["last_verified_date"], "2026-05-11")

    def test_stock_profile_relations_group_event_and_weak_tags(self):
        relations = build_stock_profile_relations({
            "sector": "计算机设备",
            "concepts": ["2025年报预增", "注册制次新股", "人工智能"],
        })
        groups = summarize_profile_relation_groups(relations)

        self.assertEqual([group["key"] for group in groups], [
            "core_business",
            "event_driven",
            "market_tag",
            "weak_association",
        ])
        self.assertEqual(groups[1]["relations"][0]["relation_type"], "event_driven")
        self.assertEqual(groups[3]["relations"][0]["relation_type"], "weak_association")

    def test_stock_tag_profile_separates_facts_clues_and_governance(self):
        result = {
            "code": "600063",
            "name": "示例股票",
            "sector": "计算机设备",
            "concepts": ["人工智能", "融资融券", "2025年报预增"],
            "profile_relations": [
                {
                    "relation_name": "AI应用",
                    "relation_kind": "concept",
                    "relation_type": "manual_confirm",
                    "evidence_group": "manual",
                    "source": "manual",
                    "confidence": 0.95,
                    "evidence": "人工确认主营相关",
                },
                {
                    "relation_name": "人工智能",
                    "relation_kind": "concept",
                    "relation_type": "market_theme",
                    "evidence_group": "market_tag",
                    "source": "manual",
                    "confidence": 0.88,
                    "evidence": "题材标签",
                },
                {
                    "relation_name": "2025年报预增",
                    "relation_kind": "event",
                    "relation_type": "event_signal",
                    "evidence_group": "event_driven",
                    "source": "manual",
                    "confidence": 0.9,
                    "evidence": "事件驱动",
                },
                {
                    "relation_name": "融资融券",
                    "relation_kind": "concept",
                    "relation_type": "weak_association",
                    "evidence_group": "weak_association",
                    "source": "manual",
                    "confidence": 0.6,
                    "evidence": "弱关联标签",
                },
            ],
        }

        profile = build_stock_tag_profile(result)

        self.assertEqual(profile["official_industry"], "计算机设备")
        self.assertEqual(profile["groups"]["official_industry"]["layer"], "fact")
        self.assertEqual(profile["groups"]["manual"]["tags"][0]["name"], "AI应用")
        self.assertEqual(profile["groups"]["market_tag"]["tags"][0]["name"], "人工智能")
        self.assertEqual(profile["groups"]["event_driven"]["tags"][0]["name"], "2025年报预增")
        self.assertEqual(profile["groups"]["weak_association"]["tags"][0]["name"], "融资融券")
        self.assertNotIn("active_market", profile)
        self.assertEqual(profile["governance"]["quality_label"], "静态清晰")
        self.assertEqual(profile["summary"], "行业:计算机设备 / 市场标签:1 / 弱关联:1")

    def test_profile_relation_evidence_overlay_can_be_loaded_and_merged(self):
        with TemporaryDirectory() as tmp_dir:
            evidence_path = Path(tmp_dir) / "stock_relation_evidence.json"
            evidence_path.write_text(json.dumps({
                "stocks": {
                    "sh600063": [
                        {
                            "relation_name": "储能",
                            "relation_kind": "business",
                            "relation_type": "core_business",
                            "source": "manual",
                            "confidence": 0.92,
                            "evidence": "公告确认主营业务覆盖储能设备",
                            "last_verified_date": "2026-05-13",
                        }
                    ]
                }
            }, ensure_ascii=False), encoding="utf-8")

            evidence = read_profile_relation_evidence(path=evidence_path)
            result = {"code": "600063", "sector": "化学原料和化学制品制造业", "concepts": ["储能"]}
            attach_profile_relations(result, result, verified_date="2026-05-11", relation_evidence=evidence["600063"])

        storage = [
            relation
            for relation in result["profile_relations"]
            if relation["relation_name"] == "储能"
        ][0]
        self.assertEqual(storage["relation_type"], "core_business")
        self.assertEqual(storage["source"], "manual")
        self.assertEqual(storage["confidence"], 0.92)
        self.assertIn("主营行业", result["profile_relation_group_summary"])

    def test_profile_relation_evidence_can_be_upserted_and_deleted(self):
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            upserted = upsert_profile_relation_evidence("sh600063", {
                "relation_name": "储能",
                "relation_kind": "business",
                "relation_type": "core_business",
                "source": "manual",
                "confidence": 0.9,
            }, cache_dir=cache_dir)

            evidence = read_profile_relation_evidence(cache_dir=cache_dir)
            status = profile_relation_evidence_status(cache_dir=cache_dir)

            self.assertEqual(upserted["code"], "600063")
            self.assertEqual(evidence["600063"][0]["relation_name"], "储能")
            self.assertEqual(status["relation_count"], 1)

            deleted = delete_profile_relation_evidence("600063", relation_name="储能", cache_dir=cache_dir)
            evidence_after_delete = read_profile_relation_evidence(cache_dir=cache_dir)

            self.assertEqual(deleted["removed_count"], 1)
            self.assertEqual(evidence_after_delete, {})

    def test_concept_graph_derives_edges_from_profile_membership(self):
        profile_cache = {
            "600001": {"sector": "计算机设备", "concepts": ["人工智能", "CPO"]},
            "600002": {"sector": "计算机设备", "concepts": ["人工智能", "CPO"]},
            "600003": {"sector": "通信设备", "concepts": ["人工智能", "CPO"]},
        }

        edges = build_profile_graph_edges(
            profile_cache,
            min_shared_members=2,
            min_overlap_rate=0.5,
            max_edges=20,
        )
        pairs = {
            (
                edge["source_kind"],
                edge["source_name"],
                edge["target_kind"],
                edge["target_name"],
            ): edge
            for edge in edges
        }

        self.assertIn(("concept", "CPO", "concept", "人工智能"), pairs)
        self.assertIn(("sector", "计算机设备", "concept", "人工智能"), pairs)
        self.assertEqual(pairs[("concept", "CPO", "concept", "人工智能")]["shared_count"], 3)
        self.assertEqual(pairs[("sector", "计算机设备", "concept", "人工智能")]["relation_type"], "member_overlap")

        graph = build_concept_graph(
            profile_cache=profile_cache,
            include_derived=True,
            min_shared_members=2,
            min_overlap_rate=0.5,
        )
        self.assertGreaterEqual(graph["status"]["derived_count"], 2)
        self.assertGreaterEqual(graph["status"]["node_count"], 3)

    def test_concept_graph_edges_can_be_upserted_and_deleted(self):
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            upserted = upsert_concept_graph_edge({
                "source_kind": "sector",
                "source_name": "计算机设备",
                "target_kind": "concept",
                "target_name": "人工智能",
                "relation_type": "same_theme",
                "confidence": 0.88,
                "source": "manual",
                "evidence": "人工确认算力链关系",
            }, cache_dir=cache_dir)

            edges = read_concept_graph_edges(cache_dir=cache_dir)
            status = concept_graph_status(cache_dir=cache_dir)

            self.assertEqual(upserted["status"]["edge_count"], 1)
            self.assertEqual(edges[0]["relation_type"], "same_theme")
            self.assertEqual(status["node_count"], 2)

            deleted = delete_concept_graph_edge({
                "source_kind": "concept",
                "source_name": "人工智能",
                "target_kind": "industry",
                "target_name": "计算机设备",
                "relation_type": "same_theme",
            }, cache_dir=cache_dir)
            self.assertEqual(deleted["removed_count"], 1)
            self.assertEqual(read_concept_graph_edges(cache_dir=cache_dir), [])

    @patch("app.clear_scan_workspace_cache")
    def test_concept_graph_api_persists_edges(self, mock_clear):
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                client = app.app.test_client()
                response = client.post("/api/concept_graph/edges", json={
                    "edge": {
                        "source_kind": "sector",
                        "source_name": "半导体",
                        "target_kind": "concept",
                        "target_name": "存储芯片",
                        "relation_type": "same_theme",
                        "confidence": 0.9,
                    }
                })

                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.get_json()["status"]["edge_count"], 1)

                get_response = client.get("/api/concept_graph?derived=0")
                get_payload = get_response.get_json()
                self.assertEqual(get_response.status_code, 200)
                self.assertEqual(get_payload["status"]["persisted_count"], 1)
                self.assertEqual(get_payload["edges"][0]["target_name"], "存储芯片")

                delete_response = client.delete("/api/concept_graph/edges", json={
                    "source_kind": "sector",
                    "source_name": "半导体",
                    "target_kind": "concept",
                    "target_name": "存储芯片",
                    "relation_type": "same_theme",
                })
                self.assertEqual(delete_response.status_code, 200)
                self.assertEqual(delete_response.get_json()["removed_count"], 1)
                self.assertEqual(mock_clear.call_count, 2)

    @patch("app.clear_scan_workspace_cache")
    def test_profile_relation_evidence_api_persists_and_clears_workspace_cache(self, mock_clear):
        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir)):
                client = app.app.test_client()
                response = client.post("/api/profile_relations/evidence", json={
                    "code": "600063",
                    "relation": {
                        "relation_name": "储能",
                        "relation_kind": "business",
                        "relation_type": "core_business",
                        "source": "manual",
                        "confidence": 0.91,
                    },
                })

                self.assertEqual(response.status_code, 201)
                payload = response.get_json()
                self.assertEqual(payload["status"]["relation_count"], 1)
                mock_clear.assert_called_once()

                get_response = client.get("/api/profile_relations/evidence?code=600063")
                get_payload = get_response.get_json()
                self.assertEqual(get_response.status_code, 200)
                self.assertEqual(get_payload["count"], 1)
                self.assertEqual(get_payload["relations"][0]["relation_name"], "储能")

                delete_response = client.delete("/api/profile_relations/evidence", json={
                    "code": "600063",
                    "relation_name": "储能",
                })
                self.assertEqual(delete_response.status_code, 200)
                self.assertEqual(delete_response.get_json()["removed_count"], 1)

    def test_analysis_pipeline_prepares_indicators_and_signals(self):
        rows = 30
        df = pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=rows, freq="D"),
            "开盘": [10.0 + i * 0.1 for i in range(rows)],
            "最高": [10.4 + i * 0.1 for i in range(rows)],
            "最低": [9.8 + i * 0.1 for i in range(rows)],
            "收盘": [10.1 + i * 0.1 for i in range(rows)],
            "成交量": [1000 + i * 20 for i in range(rows)],
        })

        result = prepare_analysis_frame(df, fill_initial_ma20=True)

        for column in [
            "custom",
            "dif",
            "dea",
            "macd_hist",
            "ma5",
            "ma20",
            "vwap",
            "bull_power",
            "bear_power",
            "bull_bear_balance",
            "williams_r",
            "williams_r_cross_bull",
            "williams_r_cross_bear",
            "is_b_point",
            "new_is_b_point",
            "opt_is_b_point",
        ]:
            self.assertIn(column, result.columns)

        self.assertFalse(result.empty)
        self.assertEqual(len(result), rows)
        self.assertFalse(result["ma20"].isna().any())

    def test_williams_direction_indicators_follow_course_formulas(self):
        frame = pd.DataFrame({
            "open": [10.0, 10.0, 10.0],
            "high": [12.0, 14.0, 15.0],
            "low": [8.0, 9.0, 10.0],
            "close": [11.0, 10.0, 14.0],
            "volume": [1000, 1000, 1000],
        })

        result = calculate_williams_r(calculate_bull_bear_power(frame.copy()), period=3)

        self.assertEqual(result.loc[0, "bull_power"], 3.0)
        self.assertEqual(result.loc[0, "bear_power"], 1.0)
        self.assertAlmostEqual(result.loc[0, "bull_bear_balance"], 0.5)
        self.assertAlmostEqual(result.loc[1, "williams_r"], 66.666666, places=5)
        self.assertEqual(result.loc[1, "williams_r_center_side"], "bear")
        self.assertTrue(result.loc[2, "williams_r_cross_bull"])
        self.assertEqual(result.loc[2, "williams_r_center_side"], "bull")

    def test_serializer_outputs_existing_chart_payload_contract(self):
        rows = 30
        df = pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=rows, freq="D"),
            "开盘": [10.0 + i * 0.1 for i in range(rows)],
            "最高": [10.4 + i * 0.1 for i in range(rows)],
            "最低": [9.8 + i * 0.1 for i in range(rows)],
            "收盘": [10.1 + i * 0.1 for i in range(rows)],
            "成交量": [1000 + i * 20 for i in range(rows)],
        })
        frame = prepare_analysis_frame(df, fill_initial_ma20=True)

        payload = analysis_frame_to_chart_payload(frame)

        for key in [
            "dates",
            "k_data",
            "ma20_data",
            "vwap_data",
            "bull_power_data",
            "bear_power_data",
            "williams_r_data",
            "custom_data",
            "dif_data",
            "dea_data",
            "macd_data",
            "mark_points",
            "mark_points_v2",
            "event_stats",
            "score_summary",
            "signal_definitions",
        ]:
            self.assertIn(key, payload)

        self.assertEqual(len(payload["dates"]), rows)
        self.assertEqual(len(payload["k_data"]), rows)
        self.assertEqual(len(payload["bull_power_data"]), rows)
        self.assertEqual(len(payload["williams_r_data"]), rows)
        self.assertEqual(payload["mark_points"], payload["mark_points_v2"])
        self.assertNotIn("mark_points_old", payload)
        self.assertNotIn("mark_points_new", payload)
        self.assertNotIn("mark_points_opt", payload)
        self.assertNotIn("stats_old", payload)
        self.assertNotIn("stats_new", payload)
        self.assertNotIn("stats_opt", payload)
        self.assertEqual(set(payload["event_stats"].keys()), {"v2"})
        self.assertIn("setup", payload["score_summary"])
        self.assertIn("confirm", payload["score_summary"])
        self.assertIn("risk", payload["score_summary"])
        self.assertEqual(payload["signal_definitions"]["v2_pullback"]["label"], "C回")
        self.assertEqual(payload["signal_definitions"]["v2_structure_candidate"]["label"], "C候")

    def test_serializer_can_include_legacy_marks_for_debug(self):
        frame = self._minimal_signal_frame()
        mark_legacy_signals(frame, {6: ["is_b_point", "is_pullback_b"]})

        payload = analysis_frame_to_chart_payload(frame, include_legacy=True)

        self.assertIn("mark_points_old", payload)
        self.assertIn("mark_points_new", payload)
        self.assertIn("mark_points_opt", payload)
        self.assertIn("stats_old", payload)
        self.assertIn("stats_new", payload)
        self.assertIn("stats_opt", payload)
        self.assertEqual(payload["mark_points"], payload["mark_points_old"])
        self.assertEqual(payload["stats_old"]["b"]["horizon"], 5)
        self.assertIn("old", payload["event_stats"])
        self.assertIn("new", payload["event_stats"])
        self.assertIn("opt", payload["event_stats"])

    def test_serializer_does_not_hide_old_pullback_when_base_b_lacks_divergence(self):
        frame = self._minimal_signal_frame()
        mark_legacy_signals(frame, {6: ["is_b_point", "is_pullback_b"]})

        payload = analysis_frame_to_chart_payload(frame, include_legacy=True)
        names = [point["name"] for point in payload["mark_points_old"]]

        self.assertIn("回踩买点", names)
        self.assertNotIn("黄金B点", names)

    def test_serializer_hides_deprecated_old_and_new_s_marks(self):
        frame = self._minimal_signal_frame()
        mark_legacy_signals(frame, {
            5: ["is_top_divergence"],
            6: ["is_s_point", "break_ma5"],
            7: ["new_is_s_point"],
        })

        payload = analysis_frame_to_chart_payload(frame, include_legacy=True)

        self.assertNotIn("死亡S点", [point["name"] for point in payload["mark_points_old"]])
        self.assertNotIn("新S点", [point["name"] for point in payload["mark_points_new"]])
        self.assertEqual(payload["stats_new"]["b"]["count"], 0)
        self.assertIsNone(payload["stats_old"]["s"])
        self.assertIsNone(payload["stats_new"]["s"])

    def test_c_signal_v2_contract_separates_observation_from_entry(self):
        v2_repair_watch = c_signal_v2_fields("v2_repair_watch")
        repair_watch = c_signal_v2_fields("composite_confirm")
        bottom_watch = c_signal_v2_fields("composite_bottom_divergence")
        pullback_entry = c_signal_v2_fields("composite_pullback")
        legacy_entry = c_signal_v2_fields("new_gold")

        self.assertEqual(v2_repair_watch["v2_signal"], "C修")
        self.assertEqual(v2_repair_watch["trade_intent"], "watch_only")
        self.assertFalse(v2_repair_watch["requires_trade_plan"])
        self.assertFalse(v2_repair_watch["requires_stop_loss"])
        self.assertEqual(repair_watch["v2_signal"], "C修")
        self.assertEqual(repair_watch["v2_role_label"], "观察")
        self.assertEqual(repair_watch["trade_intent"], "watch_only")
        self.assertFalse(repair_watch["requires_trade_plan"])
        self.assertFalse(repair_watch["requires_stop_loss"])
        self.assertEqual(bottom_watch["v2_signal"], "C研")
        self.assertFalse(bottom_watch["requires_stop_loss"])
        self.assertEqual(pullback_entry["v2_role_label"], "可交易")
        self.assertTrue(pullback_entry["requires_trade_plan"])
        self.assertTrue(pullback_entry["requires_stop_loss"])
        self.assertEqual(legacy_entry["v2_signal"], "C候")
        self.assertEqual(legacy_entry["v2_role_label"], "候选")

    def test_c_signal_v2_contract_uses_legacy_adapter_only_for_reference_events(self):
        self.assertIn("v2_breakout", V2_SIGNAL_CONTRACTS)
        self.assertNotIn("composite_breakout", V2_SIGNAL_CONTRACTS)
        self.assertIn("composite_breakout", LEGACY_C_SIGNAL_CONTRACTS)
        self.assertEqual(v2_signal_fields("v2_breakout")["v2_signal"], "C突")
        self.assertEqual(legacy_c_signal_fields("composite_breakout")["v2_signal"], "C突")
        self.assertEqual(c_signal_v2_fields("v2_breakout"), v2_signal_fields("v2_breakout"))
        self.assertEqual(c_signal_v2_fields("composite_breakout"), legacy_c_signal_fields("composite_breakout"))

    def test_signal_registry_drives_scan_pool_keys_and_reason_aliases(self):
        scan_config = build_scan_config()
        event_weights = build_event_weights()
        pool_keys = set().union(*(pool["keys"] for pool in scan_config.values()))

        self.assertEqual(list(scan_config.keys()), ["opportunity", "risk", "bottom_div"])
        self.assertEqual(scan_config["bottom_div"]["title"], "修复观察")
        self.assertEqual(scan_config["bottom_div"]["lookback"], 2)
        self.assertIn("v2_bear_trap_recovery", scan_config["opportunity"]["keys"])
        self.assertEqual(event_weights["v2_bear_trap_recovery"], 20)
        self.assertGreaterEqual(event_weights["v2_bear_trap_recovery"], event_weights["v2_breakout"])
        self.assertTrue(pool_keys.issubset(set(V2_SIGNAL_CONTRACTS.keys())))
        self.assertTrue(pool_keys.issubset(set(event_weights.keys())))
        self.assertTrue(pool_keys.issubset(set(SIGNAL_DEFINITIONS.keys())))
        self.assertEqual(signal_labels_for_reason("c_breakout"), {"C突"})
        self.assertEqual(signal_keys_for_reason("c_breakout"), {"v2_breakout", "v2_bear_trap_recovery"})
        self.assertEqual(signal_keys_for_reason("unknown"), set())

    def test_serializer_outputs_independent_v2_marks(self):
        frame = self._v2_trigger_frame()

        payload = analysis_frame_to_chart_payload(frame)

        v2_keys = [point["signalKey"] for point in payload["mark_points_v2"]]
        v2_dates = [point["date"] for point in payload["mark_points_v2"]]
        self.assertIn("v2_structure_candidate", v2_keys)
        self.assertIn("v2_ignition", v2_keys)
        self.assertEqual(v2_dates, sorted(v2_dates))
        ignition = next(point for point in payload["mark_points_v2"] if point["signalKey"] == "v2_ignition")
        structure = next(point for point in payload["mark_points_v2"] if point["signalKey"] == "v2_structure_candidate")
        self.assertEqual(ignition["v2Signal"], "C爆")
        self.assertEqual(ignition["markerRole"], "buy")
        self.assertEqual(ignition["markerLevel"], "strong")
        self.assertTrue(ignition["requiresTradePlan"])
        self.assertEqual(structure["v2Signal"], "C候")
        self.assertEqual(structure["markerRole"], "observe")
        self.assertFalse(structure["requiresTradePlan"])
        self.assertIn("v2", payload["event_stats"])

    def test_serializer_marks_exit_point_with_same_day_bottom_display_context(self):
        frame = self._minimal_signal_frame(rows=3)
        frame["date"] = pd.date_range("2026-08-22", periods=3, freq="D")
        events = [
            SignalEvent(
                key="v2_exit_gate_sell",
                group="v2",
                date="2026-08-24",
                coord_price=7.05,
                price=7.10,
                reason="收盘价跌破动态防守线 7.05",
                value="trailing_stop_break",
            )
        ]
        facts = {
            "structure": {
                "fractals": {
                    "recent_bottoms": [{
                        "date": "2026-08-24",
                        "source_start_date": "2026-08-24",
                        "source_end_date": "2026-08-24",
                    }]
                }
            }
        }

        payload = analysis_frame_to_chart_payload(frame, v2_events=events, facts=facts)

        point = payload["mark_points_v2"][0]
        self.assertEqual(point["signalKey"], "v2_exit_gate_sell")
        self.assertEqual(point["markerRole"], "sell")
        self.assertTrue(point["same_day_bottom_candidate"])
        self.assertEqual(point["display_context_hint"], "break_with_bottom_fractal")

    def test_serializer_eventizes_legacy_opt_marks(self):
        frame = self._minimal_signal_frame()
        mark_legacy_signals(frame, {
            4: ["opt_is_b_point"],
            6: ["opt_is_pullback_b"],
        })

        payload = analysis_frame_to_chart_payload(frame, include_legacy=True)

        names = [point["name"] for point in payload["mark_points_opt"]]
        self.assertIn("优化B点", names)
        self.assertIn("优化回踩", names)
        first = payload["mark_points_opt"][0]
        self.assertEqual(first["signalKey"], "opt_gold")
        self.assertEqual(first["signalGroup"], "opt")
        self.assertEqual(first["signalLabel"], "O★B")
        self.assertEqual(payload["signal_definitions"]["opt_pullback"]["label"], "O回")

    def test_latest_scan_event_uses_recent_bottom_divergence_event(self):
        frame = self._v2_divergence_frame()

        event, _ = build_v2_latest_scan_event(frame, "bottom_div")

        self.assertIsNotNone(event)
        self.assertEqual(event.key, "v2_bottom_research")

    def test_opportunity_pool_admits_plan_ready_breakout_and_pullback(self):
        frame = self._minimal_signal_frame(rows=2)
        ready_cases = [
            ("breakout_allowed", "v2_breakout"),
            ("pullback_allowed", "v2_pullback"),
        ]

        for permission, signal_key in ready_cases:
            with self.subTest(permission=permission):
                event, _ = build_v2_latest_scan_event(
                    frame,
                    "opportunity",
                    state_model={
                        "state": "entry_breakout" if permission == "breakout_allowed" else "entry_pullback",
                        "permission": permission,
                        "state_label": "计划放行",
                        "signal_name": "V2计划",
                        "v2_permission_model": {"signal_key": signal_key},
                    },
                )

                self.assertIsNotNone(event)
                self.assertEqual(event.key, signal_key)

        fallback_event, _ = build_v2_latest_scan_event(
            frame,
            "opportunity",
            state_model={
                "state": "entry_breakout",
                "permission": "breakout_allowed",
                "state_label": "计划放行",
            },
        )
        self.assertEqual(fallback_event.key, "v2_breakout")

    def test_scan_stock_frame_outputs_scored_opportunity_result(self):
        frame = self._v2_legacy_entry_frame("breakout")
        frame["momentum_efficiency"] = [0.35] * len(frame)
        frame["custom_z"] = [1.25] * len(frame)
        frame["volume_ratio"] = [1.8] * len(frame)
        frame["return_pct"] = [2.34] * len(frame)
        frame["bull_power"] = [0.7] * len(frame)
        frame["bear_power"] = [0.2] * len(frame)
        frame["bull_bear_balance"] = [0.556] * len(frame)
        frame["bull_power_dominant"] = [True] * len(frame)
        frame["bear_power_dominant"] = [False] * len(frame)
        frame["williams_r"] = [35.0] * len(frame)
        frame["williams_r_cross_bull"] = [False] * len(frame)
        frame["williams_r_cross_bear"] = [False] * len(frame)
        frame["williams_r_center_side"] = ["bull"] * len(frame)

        result = scan_stock_frame("600063", "示例股票", frame, "opportunity")

        self.assertIsNotNone(result)
        self.assertEqual(result["scan_type"], "opportunity")
        self.assertEqual(result["scan_admission_source"], "v2_state")
        self.assertIn(
            result["signal_key"],
            {"v2_structure_candidate", "v2_breakout", "v2_pullback", "v2_ignition", "v2_attack_day"},
        )
        self.assertEqual(result["momentum_efficiency"], 0.35)
        self.assertEqual(result["custom_z"], 1.25)
        self.assertEqual(result["volume_ratio"], 1.8)
        self.assertEqual(result["return_pct"], 2.34)
        self.assertEqual(result["bull_power"], 0.7)
        self.assertEqual(result["bear_power"], 0.2)
        self.assertEqual(result["bull_bear_balance"], 0.556)
        self.assertTrue(result["bull_power_dominant"])
        self.assertEqual(result["williams_r"], 35.0)
        self.assertEqual(result["williams_r_center_side"], "bull")
        self.assertGreaterEqual(result["risk_break_score"], 0)
        self.assertGreaterEqual(result["risk_heat_score"], 0)
        self.assertIn("view_model", result)
        self.assertIn("explanation", result)

    def test_scan_stock_frame_admits_independent_v2_current_state(self):
        frame = self._v2_trigger_frame()

        result = scan_stock_frame("600063", "示例股票", frame, "opportunity")

        self.assertIsNotNone(result)
        self.assertEqual(result["scan_admission_source"], "v2_state")
        self.assertEqual(result["signal_key"], "v2_structure_candidate")
        self.assertEqual(result["signal"], "C候")
        self.assertEqual(result["v2_state_model"]["state"], "trigger_plan_waiting")
        self.assertEqual(result["v2_state_model"]["permission"], "watch_only")
        self.assertEqual(result["v2_state_model"]["signal"], "C候")
        self.assertEqual(result["v2_queue"], "structure_watch")
        self.assertEqual(result["v2_permission"], "watch_only")
        self.assertEqual(result["v2_plan_status"], "waiting")
        self.assertEqual(result["v2_priority_group"], "structure_watch")
        self.assertEqual(result["view_model"]["decision_label"], "只观察")
        driver_labels = [driver["label"] for driver in result["explanation"]["drivers"]]
        badge_labels = [badge["label"] for badge in result["explanation"]["score_badges"]]
        self.assertIn("交易闸门", driver_labels)
        self.assertIn("结构目标", driver_labels)
        self.assertIn("大周期", driver_labels)
        self.assertIn("闸门", badge_labels)
        self.assertIn("目标", badge_labels)
        self.assertIn("大周期", badge_labels)

    def test_v2_environment_permission_ignores_board_context_without_macro_facts(self):
        result = {
            "scan_type": "opportunity",
            "sector_score": 68,
            "sector_market_score": 62,
            "sector_opportunity_count": 4,
            "sector_risk_count": 1,
            "concept_score": 42,
        }

        permission = build_v2_environment_permission(result)

        self.assertEqual(permission["v2_environment_permission"], "unknown")
        self.assertEqual(permission["v2_sector_permission"], "not_used")
        self.assertEqual(permission["v2_concept_permission"], "not_used")
        self.assertEqual(permission["v2_environment_effect"], "needs_context")
        self.assertEqual(permission["v2_effective_permission"], "unknown")

    def test_v2_environment_permission_ignores_weak_board_when_macro_allows_entry(self):
        result = {
            "scan_type": "opportunity",
            "rank_score": 88,
            "final_score": 500,
            "sector_score": 18,
            "sector_market_score": 35,
            "sector_opportunity_count": 1,
            "sector_risk_count": 3,
            "v2_state_model": {
                "state": "ignition_triggered",
                "permission": "attack_allowed",
                "role": "entry",
                "v2_permission_model": {"plan_status": "ready"},
                "facts": {
                    "macro_tide": {
                        "available": True,
                        "summary": "个股宏观条件通过",
                        "ma250": {"available": True, "above": True},
                        "weekly_macd": {"available": True},
                    },
                },
            },
        }

        priority = build_c_signal_v2_priority(result)

        self.assertEqual(priority["v2_environment_permission"], "allowed")
        self.assertEqual(priority["v2_environment_effect"], "allow")
        self.assertEqual(priority["v2_effective_permission"], "attack_allowed")
        self.assertEqual(priority["v2_queue"], "trade_ready")
        self.assertEqual(priority["v2_environment_block_reasons"], [])

        stock_only = dict(result)
        stock_only["final_score"] = stock_only["rank_score"]
        stock_only.pop("sector_score")
        stock_only.pop("sector_market_score")
        stock_only.pop("sector_opportunity_count")
        stock_only.pop("sector_risk_count")
        self.assertEqual(
            build_c_signal_v2_priority(stock_only)["v2_priority_score"],
            priority["v2_priority_score"],
        )

    def test_workspace_result_drops_legacy_market_scores_but_keeps_labels(self):
        from stock_analyzer.scan_workspace_response import _remove_legacy_market_context

        result = {
            "rank_score": 44.0,
            "final_score": 99.0,
            "sector": "半导体",
            "concepts": ["存储芯片"],
            "sector_score": 100,
            "concept_score": 100,
            "sector_market_boost": 5,
            "market_boost": 5,
        }

        _remove_legacy_market_context(result)

        self.assertEqual(result["final_score"], 44.0)
        self.assertEqual(result["sector"], "半导体")
        self.assertEqual(result["concepts"], ["存储芯片"])
        self.assertNotIn("sector_score", result)
        self.assertNotIn("concept_score", result)
        self.assertNotIn("sector_market_boost", result)
        self.assertNotIn("market_boost", result)

    def test_v2_environment_permission_exposes_macro_veto_for_breakout(self):
        result = {
            "scan_type": "opportunity",
            "rank_score": 88,
            "v2_state_model": {
                "state": "entry_breakout",
                "permission": "breakout_allowed",
                "signal": "C突",
                "role": "entry",
                "v2_permission_model": {
                    "plan_status": "ready",
                    "plan_gate": {"entry_type": "breakout"},
                },
                "facts": {
                    "macro_tide": {
                        "available": True,
                        "ma250": {"available": True, "above": False},
                        "weekly_macd": {"available": False},
                    },
                },
            },
        }

        permission = build_v2_environment_permission(result)

        self.assertEqual(permission["v2_macro_veto_permission"], "forbidden")
        self.assertEqual(permission["v2_environment_permission"], "forbidden")
        self.assertEqual(permission["v2_environment_effect"], "block_entry")
        self.assertEqual(permission["v2_effective_permission"], "environment_blocked")
        self.assertIn("MA250", permission["v2_macro_veto_reason"])

    def test_scan_snapshot_persists_independent_v2_pool_result_without_legacy_entry(self):
        frame = self._v2_trigger_frame()

        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
        result = scan_result_from_snapshot(snapshot, "opportunity")

        self.assertIn("opportunity", snapshot["computed_scan_types"])
        self.assertEqual(result["scan_admission_source"], "v2_state")
        self.assertEqual(result["signal_key"], "v2_structure_candidate")
        self.assertEqual(result["v2_state_model"]["state"], "trigger_plan_waiting")
        self.assertEqual(result["v2_state_model"]["permission"], "watch_only")

    def test_risk_pool_marks_confirmed_risk_stage(self):
        frame = self._v2_entry_then_crash_frame()

        result = scan_stock_frame("600063", "示例股票", frame, "risk")

        self.assertIsNotNone(result)
        self.assertEqual(result["pool_stage"], "confirmed_risk")
        self.assertEqual(result["pool_stage_label"], "强风险")
        self.assertEqual(result["pool_stage_tone"], "danger")

    def test_bottom_divergence_pool_marks_confirmation_stage(self):
        frame = self._v2_divergence_frame()

        result = scan_stock_frame("600063", "示例股票", frame, "bottom_div")

        self.assertIsNotNone(result)
        self.assertEqual(result["pool_stage"], "unconfirmed")
        self.assertEqual(result["pool_stage_label"], "底部研究")
        self.assertEqual(result["pool_stage_tone"], "muted")

    def test_bottom_divergence_pool_promotes_v2_repair_watch_without_entry_permission(self):
        frame = self._v2_divergence_frame(repair=True)

        facts = build_c_signal_v2_facts(frame)
        state = build_c_signal_v2_state(frame)
        result = scan_stock_frame("600063", "示例股票", frame, "bottom_div")

        self.assertEqual(facts["repair"]["stage"], "repair_setup")
        self.assertIn("底背离", " / ".join(facts["repair"]["evidence"]))
        self.assertEqual(state["signal"], "C修")
        self.assertEqual(state["permission"], "watch_only")
        self.assertFalse(state["requires_trade_plan"])
        self.assertFalse(state["requires_stop_loss"])
        self.assertIsNotNone(result)
        self.assertEqual(result["scan_admission_source"], "v2_state")
        self.assertEqual(result["signal_key"], "v2_repair_watch")
        self.assertEqual(result["v2_signal"], "C修")
        self.assertEqual(result["v2_state_model"]["state"], "repair_setup")
        self.assertEqual(result["pool_stage"], "repair_watch")
        self.assertFalse(result["requires_trade_plan"])
        self.assertFalse(result["requires_stop_loss"])

    def test_scan_snapshot_persists_all_scan_pool_results(self):
        frame = self._v2_legacy_entry_frame("breakout")

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                snapshot = build_scan_snapshot(
                    "600063",
                    "600063",
                    frame,
                    snapshot_day="2026-05-10",
                    sector="半导体",
                )
                write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                cached = read_scan_snapshot("600063", start_date="2025-04-29", snapshot_day="2026-05-10")

        opportunity = scan_result_from_snapshot(cached, "opportunity")

        self.assertIn("opportunity", cached["computed_scan_types"])
        self.assertEqual(cached["sector"], "半导体")
        self.assertEqual(opportunity["sector"], "半导体")
        self.assertEqual(opportunity["scan_admission_source"], "v2_state")
        self.assertEqual(opportunity["signal_key"], "v2_structure_candidate")
        self.assertEqual(opportunity["v2_signal"], "C候")
        self.assertIn(opportunity["candidate_substate"], {"structure_candidate", "pullback_setup", "strong_repair_watch", "reversal_confirmed"})
        self.assertTrue(opportunity["candidate_display_label"])
        self.assertEqual(opportunity["v2_state_model"]["candidate_substate"], opportunity["candidate_substate"])
        self.assertFalse(opportunity["requires_trade_plan"])
        self.assertIn("trade_plan", opportunity)

    def test_scan_snapshot_reuses_one_v2_analysis_context_for_all_pools(self):
        frame = self._v2_legacy_entry_frame("breakout")
        shared_context = build_v2_analysis_context(
            frame,
            context={
                "alignment": "scan_candidate",
                "detail": "来自扫描候选，仍需核对市场结构和板块阶段。",
            },
            include_events=False,
            include_trade_plan=True,
        )

        with patch("stock_analyzer.scan_snapshot.build_v2_analysis_context", return_value=shared_context) as mock_context:
            with patch("stock_analyzer.scan_snapshot.scan_stock_frame", wraps=scan_snapshot_module.scan_stock_frame) as mock_scan:
                snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")

        self.assertIn("opportunity", snapshot["computed_scan_types"])
        mock_context.assert_called_once()
        self.assertEqual(mock_scan.call_count, 3)
        for call in mock_scan.call_args_list:
            self.assertIs(call.kwargs["analysis_context"], shared_context)

    def test_scan_result_from_snapshot_backfills_v2_fields_for_legacy_cache(self):
        frame = self._v2_legacy_entry_frame("breakout")
        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
        for result in snapshot["results"].values():
            for key in list(result.keys()):
                if key.startswith("v2_") or key in {"trade_intent", "trade_intent_label", "requires_trade_plan", "requires_stop_loss"}:
                    result.pop(key)

        result = scan_result_from_snapshot(snapshot, "opportunity")

        self.assertEqual(result["signal_key"], "v2_structure_candidate")
        self.assertEqual(result["v2_signal"], "C候")
        self.assertFalse(result["requires_stop_loss"])
        self.assertEqual(result["v2_state_model"]["source"], "scan_result_backfill_p6_trade_gate")
        self.assertEqual(result["v2_state_model"]["state"], "structure_candidate")
        self.assertEqual(result["v2_state_model"]["permission"], "watch_only")

    def test_scan_result_backfill_keeps_bottom_research_out_of_risk_state(self):
        result = scan_result_from_snapshot({
            "results": {
                "bottom_div": {
                    "code": "600063",
                    "name": "示例股票",
                    "signal_key": "composite_bottom_divergence",
                    "signal": "C底",
                    "date": "2026-05-10",
                    "risk_score": 4,
                    "setup_score": 3,
                    "confirm_score": 2,
                },
            },
        }, "bottom_div")

        self.assertEqual(result["v2_state_model"]["source"], "scan_result_backfill_p6_trade_gate")
        self.assertEqual(result["v2_state_model"]["state"], "research_bottom")
        self.assertEqual(result["v2_state_model"]["permission"], "watch_only")
        self.assertEqual(result["v2_state_model"]["signal"], "C研")

    def test_check_stock_signal_reuses_snapshot_for_other_scan_types(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-10")):
                    with patch("app.get_stock_dataframe", return_value=frame) as mock_dataframe:
                        with patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"}):
                            first = app.check_stock_signal("600063", "opportunity")
                            second = app.check_stock_signal("600063", "opportunity")

        self.assertEqual(mock_dataframe.call_count, 1)
        self.assertEqual(first["signal_key"], "v2_structure_candidate")
        self.assertEqual(second["signal_key"], "v2_structure_candidate")
        self.assertEqual(second["name"], "示例股票")

    def test_latest_scan_snapshot_reuses_previous_calendar_day(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=1, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    old_snapshot = build_scan_snapshot("600063", "600063", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(old_snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    latest = read_latest_scan_snapshot("600063", start_date="2025-04-29")

        self.assertEqual(latest["snapshot_day"], "20260510")
        self.assertEqual(scan_result_from_snapshot(latest, "opportunity")["signal_key"], "v2_structure_candidate")

    def test_recent_scan_snapshot_age_window(self):
        snapshot = {"snapshot_day": "20260510"}
        stale_data_snapshot = {"snapshot_day": "20260511", "data_date": "2026-01-09"}

        self.assertTrue(is_recent_snapshot(snapshot, max_age_days=7, now_day="2026-05-11"))
        self.assertFalse(is_recent_snapshot(snapshot, max_age_days=7, now_day="2026-05-20"))
        self.assertFalse(is_recent_snapshot(stale_data_snapshot, max_age_days=7, now_day="2026-05-11"))
        self.assertFalse(is_recent_snapshot(stale_data_snapshot, max_age_days=None))

    def test_recent_scan_snapshot_requires_current_day_data_after_close(self):
        snapshot = {"snapshot_day": "20260511", "data_date": "2026-05-08"}
        previous_day_snapshot = {"snapshot_day": "20260510", "data_date": "2026-05-10"}

        with patch(
            "stock_analyzer.scan_snapshot.market_calendar_context",
            return_value={"is_session": True},
        ):
            self.assertTrue(is_recent_snapshot(snapshot, now_day="2026-05-11 14:50:00"))
            self.assertFalse(is_recent_snapshot(snapshot, now_day="2026-05-11 16:00:00"))
            self.assertTrue(is_recent_snapshot(previous_day_snapshot, now_day="2026-05-11 14:50:00"))
            self.assertFalse(is_recent_snapshot(previous_day_snapshot, now_day="2026-05-11 16:00:00"))
            self.assertTrue(is_recent_snapshot({"snapshot_day": "20260511", "data_date": "2026-05-11"}, now_day="2026-05-11 16:00:00"))

    def test_recent_scan_snapshot_does_not_require_holiday_bar_after_close(self):
        snapshot = {"snapshot_day": "20260925", "data_date": "2026-09-24"}

        with patch(
            "stock_analyzer.scan_snapshot.market_calendar_context",
            return_value={"is_session": False},
        ):
            self.assertTrue(
                is_recent_snapshot(snapshot, now_day="2026-09-25 16:00:00")
            )

    def test_recent_scan_snapshot_uses_weekday_fallback_when_calendar_unknown(self):
        snapshot = {"snapshot_day": "20260511", "data_date": "2026-05-08"}

        with patch(
            "stock_analyzer.scan_snapshot.market_calendar_context",
            return_value={"is_session": None},
        ):
            self.assertFalse(
                is_recent_snapshot(snapshot, now_day="2026-05-11 16:00:00")
            )

    def test_check_stock_signal_uses_latest_snapshot_without_reloading_data(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=1, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    with patch("app.read_scan_snapshot", return_value=None):
                        with patch("app.get_stock_dataframe") as mock_dataframe:
                            with patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"}):
                                snapshot = build_scan_snapshot("600063", "600063", frame, snapshot_day="2026-05-10")
                                write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                                result = app.check_stock_signal("600063", "opportunity")

        mock_dataframe.assert_not_called()
        self.assertEqual(result["signal_key"], "v2_structure_candidate")
        self.assertEqual(result["name"], "示例股票")
        self.assertEqual(result["scan_source"], "cache")

    def test_check_stock_signal_auto_recomputes_legacy_strategy_snapshot(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=1, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    legacy = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    legacy.pop("strategy_version", None)
                    legacy.pop("strategy_meta", None)
                    write_scan_snapshot(legacy, start_date="2025-04-29", snapshot_day="2026-05-10")
                    with patch("app.get_stock_dataframe", return_value=frame) as mock_dataframe:
                        with patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"}):
                            result = app.check_stock_signal("600063", "opportunity", refresh_policy="auto")

        mock_dataframe.assert_called_once_with("600063")
        self.assertEqual(result["signal_key"], "v2_structure_candidate")
        self.assertEqual(result["scan_source"], "computed")

    @patch("app.read_latest_scan_snapshot", return_value=None)
    @patch("app.read_scan_snapshot", return_value=None)
    @patch("app.get_stock_dataframe")
    def test_check_stock_signal_cache_policy_does_not_fetch_on_miss(
        self,
        mock_dataframe,
        mock_read_snapshot,
        mock_read_latest_snapshot,
    ):
        result = app.check_stock_signal("600063", "opportunity", refresh_policy="cache")

        self.assertIsNone(result)
        mock_dataframe.assert_not_called()

    @patch("app.read_scan_snapshot")
    @patch("app.read_latest_scan_snapshot")
    @patch("app.write_scan_snapshot")
    @patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"})
    @patch("app.get_stock_dataframe")
    def test_check_stock_signal_force_policy_skips_snapshot(
        self,
        mock_dataframe,
        mock_profile,
        mock_write_snapshot,
        mock_read_latest_snapshot,
        mock_read_snapshot,
    ):
        frame = self._minimal_signal_frame(rows=12)
        apply_legacy_entry(frame)
        mock_dataframe.return_value = frame

        result = app.check_stock_signal("600063", "opportunity", refresh_policy="force")

        mock_read_snapshot.assert_not_called()
        mock_read_latest_snapshot.assert_not_called()
        mock_dataframe.assert_called_once_with("600063")
        self.assertEqual(result["signal_key"], "v2_structure_candidate")
        self.assertEqual(result["scan_source"], "force")

    def test_scan_explanation_is_backend_serializable(self):
        explanation = build_scan_explanation({
            "signal_name": "综合突破",
            "reason": "MA20向上 / MACD多头",
            "rank_score": 76,
            "setup_score": 3,
            "confirm_score": 4,
            "risk_score": 0,
            "sector": "半导体",
            "sector_score": 82,
            "sector_signal_count": 5,
            "sector_risk_count": 0,
            "win_rate": 66.7,
            "avg_ret": 2.15,
        })

        self.assertEqual(explanation["headline"], "强势候选 · 综合突破")
        self.assertNotIn("共振", explanation["summary"])
        self.assertIn("所属行业/概念", [driver["label"] for driver in explanation["drivers"]])
        self.assertEqual(explanation["drivers"][0]["label"], "事件触发")
        self.assertNotIn("共振", [badge["label"] for badge in explanation["score_badges"]])
        json.dumps(explanation, ensure_ascii=False)

    @patch("app.read_latest_scan_snapshot", return_value=None)
    @patch("app.read_scan_snapshot")
    @patch("app.is_recent_snapshot", return_value=False)
    @patch("app.write_scan_snapshot")
    @patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"})
    @patch("app.get_stock_dataframe")
    def test_check_stock_signal_ignores_stale_same_day_snapshot(
        self,
        mock_dataframe,
        mock_profile,
        mock_write_snapshot,
        mock_recent,
        mock_read_snapshot,
        mock_read_latest_snapshot,
    ):
        frame = self._minimal_signal_frame(rows=12)
        apply_legacy_entry(frame)
        mock_dataframe.return_value = frame
        mock_read_snapshot.return_value = {
            "version": 1,
            "code": "600063",
            "snapshot_day": "20260511",
            "data_date": "2026-01-09",
            "computed_scan_types": ["opportunity"],
            "results": {
                "opportunity": {
                    "code": "600063",
                    "signal_key": "stale",
                },
            },
        }

        result = app.check_stock_signal("600063", "opportunity")

        mock_recent.assert_called_once_with(mock_read_snapshot.return_value)
        mock_read_latest_snapshot.assert_called_once()
        mock_dataframe.assert_called_once_with("600063")
        self.assertEqual(result["signal_key"], "v2_structure_candidate")


if __name__ == "__main__":
    unittest.main()
