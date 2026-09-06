import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pandas as pd

import app
from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.backtest import evaluate_signal_events
from stock_analyzer.board_market_refresh import refresh_board_market_cache
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
from stock_analyzer.data_fetcher import fetch_stock_history, market_symbol_for_tx
from stock_analyzer.events import build_composite_signal_events
from stock_analyzer.indicators import calculate_macd
from stock_analyzer.intraday_fetcher import fetch_stock_minute_history
from stock_analyzer.market_boards import (
    build_board_market_payload,
    get_industry_board_market,
    read_cached_board_market,
    write_cached_board_market,
)
from stock_analyzer.multi_timeframe import build_multi_timeframe_payload
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.providers.concepts import _stock_rows_from_ths_concept_html
from stock_analyzer.providers.stock_history_minute import StockMinuteHistoryProvider, market_symbol_for_sina
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
from stock_analyzer.scanner import scan_events_for_type, scan_stock_frame
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
from stock_analyzer.serializers import analysis_frame_to_chart_payload
from stock_analyzer.signals import add_signal_columns
from stock_analyzer.strategy import add_composite_strategy_columns
from scripts import scan_batch
from scripts import scan_uptrend_divergence


class ProjectSmokeTest(unittest.TestCase):
    def _minimal_signal_frame(self, rows=10):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=rows, freq="D"),
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
        return frame

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
        for column in [
            "is_b_point",
            "is_pullback_b",
            "new_is_b_point",
            "new_is_pullback_b",
            "opt_is_b_point",
            "opt_is_pullback_b",
            "is_bottom_divergence",
            "is_top_divergence",
            "opt_is_s_warn",
            "opt_is_s_confirm",
        ]:
            frame[column] = False
        return frame

    def test_normalize_code_accepts_common_stock_formats(self):
        self.assertEqual(normalize_code("600063"), "600063")
        self.assertEqual(normalize_code("sh600063"), "600063")
        self.assertEqual(normalize_code("600063.SH"), "600063")
        self.assertIsNone(normalize_code("abc"))
        self.assertIs(app.normalize_code, normalize_code)

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
    @patch("stock_analyzer.providers.stock_history.fetch_tdx_daily_bars")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_falls_back_to_secondary_provider(self, mock_tx, mock_tdx, mock_dates):
        mock_dates.return_value = (
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-01-31"),
        )
        mock_tx.return_value = pd.DataFrame()
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
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_accepts_fixed_start_date(self, mock_tx, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-10")
        expected = pd.DataFrame({"日期": ["2025-04-29"]})
        mock_tx.return_value = expected

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
        expected = pd.DataFrame({
            "date": ["2026-05-08"],
            "open": [10.0],
            "close": [10.5],
            "high": [10.8],
            "low": [9.9],
            "amount": [1000.0],
        })
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
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_uses_local_cache_when_enabled(self, mock_tx, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-10")
        expected = pd.DataFrame({"日期": ["2025-04-29"], "收盘": [10.0]})
        mock_tx.return_value = expected

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                first = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)
                second = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)

        self.assertEqual(mock_tx.call_count, 1)
        pd.testing.assert_frame_equal(first, expected)
        pd.testing.assert_frame_equal(second, expected)

    @patch("stock_analyzer.data_fetcher.beijing_now")
    @patch("stock_analyzer.providers.stock_history.ak.stock_zh_a_hist_tx")
    def test_fetch_stock_history_refreshes_stale_current_day_cache(self, mock_tx, mock_now):
        mock_now.return_value = pd.Timestamp("2026-05-11 16:00:00")
        stale = pd.DataFrame({"date": ["2026-05-08"], "close": [6.71]})
        fresh = pd.DataFrame({"date": ["2026-05-11"], "close": [6.76]})
        mock_tx.side_effect = [stale, fresh]

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.data_fetcher.CACHE_DIR", Path(tmp_dir)):
                first = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)
                second = fetch_stock_history("600063", start_date="2025-04-29", use_cache=True)

        self.assertEqual(mock_tx.call_count, 2)
        pd.testing.assert_frame_equal(first, stale)
        pd.testing.assert_frame_equal(second, fresh)

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

    def test_board_market_payload_calculates_trend_metrics(self):
        frame = pd.DataFrame({
            "日期": pd.date_range("2026-04-01", periods=25, freq="D"),
            "开盘价": [100 + i for i in range(25)],
            "最高价": [101 + i for i in range(25)],
            "最低价": [99 + i for i in range(25)],
            "收盘价": [100 + i for i in range(25)],
            "成交量": [1000] * 25,
            "成交额": [100000] * 25,
        })

        payload = build_board_market_payload("industry", "半导体", "半导体", frame, "test")

        self.assertEqual(payload["type"], "industry")
        self.assertEqual(payload["name"], "半导体")
        self.assertEqual(payload["latest_date"], "2026-04-25")
        self.assertTrue(payload["above_ma20"])
        self.assertGreater(payload["strength_score"], 50)
        self.assertEqual(len(payload["history"]), 25)

    @patch("stock_analyzer.providers.board_market.disable_proxies")
    @patch("stock_analyzer.providers.board_market.beijing_now")
    @patch("stock_analyzer.providers.board_market.ak.stock_board_industry_index_ths")
    def test_get_industry_board_market_uses_ths_index_source(self, mock_index, mock_now, mock_disable):
        mock_now.return_value = pd.Timestamp("2026-05-11")
        mock_index.return_value = pd.DataFrame({
            "日期": pd.date_range("2026-05-01", periods=3, freq="D"),
            "开盘价": [10, 11, 12],
            "最高价": [11, 12, 13],
            "最低价": [9, 10, 11],
            "收盘价": [10, 11, 12],
            "成交量": [100, 100, 100],
            "成交额": [1000, 1100, 1200],
        })

        payload = get_industry_board_market("半导体", start_date="2025-04-29")

        self.assertEqual(payload["source"], "ths_industry_index")
        self.assertEqual(payload["latest_close"], 12)
        mock_index.assert_called_once_with(
            symbol="半导体",
            start_date="20250429",
            end_date="20260511",
        )
        mock_disable.assert_called_once()

    def test_board_market_cache_uses_name_as_stable_lookup_key(self):
        payload = {
            "type": "concept",
            "name": "存储芯片",
            "index_code": "886042",
            "strength_score": 80,
        }

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.market_boards.BOARD_MARKET_CACHE_DIR", Path(tmp_dir)):
                write_cached_board_market(payload)
                cached = read_cached_board_market("concept", name="存储芯片")

        self.assertEqual(cached["index_code"], "886042")
        self.assertEqual(cached["strength_score"], 80)

    def test_board_market_cache_rejects_stale_current_day_payload_after_close(self):
        payload = {
            "type": "concept",
            "name": "存储芯片",
            "index_code": "886042",
            "latest_date": "2026-05-08",
            "history": [{"date": "2026-05-08", "close": 100}],
        }

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.market_boards.BOARD_MARKET_CACHE_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.market_boards.beijing_now", return_value=pd.Timestamp("2026-05-11 16:00:00")):
                    write_cached_board_market(payload)
                    cached = read_cached_board_market("concept", name="存储芯片")
                    fallback = read_cached_board_market(
                        "concept",
                        name="存储芯片",
                        allow_stale_current_day=True,
                    )

        self.assertIsNone(cached)
        self.assertEqual(fallback["latest_date"], "2026-05-08")

    @patch("app.get_board_market", return_value={
        "type": "concept",
        "name": "存储芯片",
        "index_code": "886042",
        "source": "test",
        "history": [],
    })
    def test_board_market_api_returns_board_payload(self, mock_market):
        response = app.app.test_client().get("/api/board_market?type=concept&name=存储芯片")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["name"], "存储芯片")
        mock_market.assert_called_once()

    @patch("app.get_board_market", side_effect=RuntimeError("provider failed"))
    def test_board_market_api_returns_unavailable_payload_on_provider_failure(self, mock_market):
        response = app.app.test_client().get("/api/board_market?type=industry&name=半导体")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["name"], "半导体")
        self.assertEqual(payload["trend_label"], "暂不可用")

    def test_refresh_board_market_cache_selects_high_priority_rows(self):
        workspace = {
            "sector_overview": [
                {"sector": "低优先", "structure_score": 10, "candidate_signal_count": 1},
                {"sector": "半导体", "structure_score": 80, "candidate_signal_count": 3},
            ]
        }
        calls = []

        def fake_get(board_type, name=None, start_date=None):
            calls.append((board_type, name, start_date))
            return {
                "type": board_type,
                "name": name,
                "latest_date": "2026-05-11",
                "strength_score": 82,
                "trend_label": "强势",
            }

        result = refresh_board_market_cache(
            workspace,
            board_type="industry",
            limit=1,
            start_date="2025-04-29",
            get_board_market_func=fake_get,
            read_cached_func=lambda board_type, name=None: None,
        )

        self.assertEqual(calls, [("industry", "半导体", "2025-04-29")])
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["items"][0]["name"], "半导体")

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

    @patch("app.collect_scan_workspace")
    def test_scan_workspace_candidates_api_filters_locally(self, mock_workspace):
        mock_workspace.return_value = {
            "pools": {
                "opportunity": {
                    "count": 2,
                    "results": [
                        {"code": "600001", "name": "样本A", "sector": "半导体", "concepts": ["存储芯片"]},
                        {"code": "600002", "name": "样本B", "sector": "医药", "concepts": ["创新药"]},
                    ],
                }
            },
            "latest_snapshot_day": "2026-05-11",
            "latest_data_date": "2026-05-11",
        }

        response = app.app.test_client().get(
            "/api/scan_workspace/candidates?scan_type=opportunity&sector=半导体&limit=20&refresh=1"
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["code"], "600001")
        _, kwargs = mock_workspace.call_args
        self.assertFalse(kwargs["include_replay"])
        self.assertFalse(kwargs["include_market_universe"])
        self.assertFalse(kwargs["include_market_breadth"])
        self.assertEqual(kwargs["replay_entry_model"], "event_close")
        self.assertTrue(kwargs["latest_only"])

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
        self.assertTrue(kwargs["include_replay"])
        self.assertEqual(kwargs["replay_entry_model"], "next_open")
        self.assertTrue(kwargs["include_market_universe"])
        self.assertTrue(kwargs["include_market_breadth"])
        self.assertFalse(kwargs["latest_only"])

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

    @patch("app.clear_scan_workspace_cache")
    @patch("app.refresh_board_market_cache", return_value={"updated_count": 1, "items": []})
    @patch("app.collect_scan_workspace", return_value={"sector_overview": []})
    def test_board_market_refresh_api_runs_controlled_refresh(self, mock_workspace, mock_refresh, mock_clear):
        response = app.app.test_client().post("/api/board_market/refresh", json={
            "type": "industry",
            "limit": 3,
        })

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["updated_count"], 1)
        mock_workspace.assert_called_once()
        mock_refresh.assert_called_once()
        self.assertEqual(mock_refresh.call_args.kwargs["board_type"], "industry")
        self.assertEqual(mock_refresh.call_args.kwargs["limit"], 3)
        mock_clear.assert_called_once()

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
            "is_b_point",
            "new_is_b_point",
            "opt_is_b_point",
            "composite_entry",
            "composite_setup_score",
            "composite_confirm_score",
            "composite_risk_score",
        ]:
            self.assertIn(column, result.columns)

        self.assertFalse(result.empty)
        self.assertEqual(len(result), rows)
        self.assertFalse(result["ma20"].isna().any())

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
            "custom_data",
            "dif_data",
            "dea_data",
            "macd_data",
            "mark_points",
            "mark_points_old",
            "mark_points_new",
            "mark_points_opt",
            "mark_points_composite",
            "stats_old",
            "stats_new",
            "stats_opt",
            "stats_composite",
            "event_stats",
            "score_summary",
            "signal_definitions",
        ]:
            self.assertIn(key, payload)

        self.assertEqual(len(payload["dates"]), rows)
        self.assertEqual(len(payload["k_data"]), rows)
        self.assertEqual(payload["mark_points"], payload["mark_points_old"])
        self.assertEqual(payload["stats_old"]["b"]["horizon"], 5)
        self.assertIn("setup", payload["score_summary"])
        self.assertIn("confirm", payload["score_summary"])
        self.assertIn("risk", payload["score_summary"])
        self.assertEqual(payload["signal_definitions"]["composite_pullback"]["label"], "C回")

    def test_serializer_does_not_hide_old_pullback_when_base_b_lacks_divergence(self):
        frame = self._minimal_signal_frame()
        frame.loc[6, "is_b_point"] = True
        frame.loc[6, "is_pullback_b"] = True

        payload = analysis_frame_to_chart_payload(frame)
        names = [point["name"] for point in payload["mark_points_old"]]

        self.assertIn("回踩买点", names)
        self.assertNotIn("黄金B点", names)

    def test_serializer_hides_deprecated_old_and_new_s_marks(self):
        frame = self._minimal_signal_frame()
        frame.loc[5, "is_top_divergence"] = True
        frame.loc[6, "is_s_point"] = True
        frame.loc[6, "break_ma5"] = True
        frame.loc[7, "new_is_s_point"] = True

        payload = analysis_frame_to_chart_payload(frame)

        self.assertNotIn("死亡S点", [point["name"] for point in payload["mark_points_old"]])
        self.assertNotIn("新S点", [point["name"] for point in payload["mark_points_new"]])
        self.assertEqual(payload["stats_new"]["b"]["count"], 0)
        self.assertIsNone(payload["stats_old"]["s"])
        self.assertIsNone(payload["stats_new"]["s"])

    def test_serializer_outputs_composite_entry_and_risk_marks(self):
        frame = self._minimal_signal_frame()
        frame.loc[5, "composite_entry"] = True
        frame.loc[5, "composite_entry_type"] = "pullback"
        frame.loc[5, "composite_entry_reason"] = "缩量回踩 / MACD多头"
        frame.loc[7, "composite_exit"] = True
        frame.loc[7, "composite_risk"] = True
        frame.loc[7, "composite_risk_reason"] = "跌破MA20 / MACD转弱"

        payload = analysis_frame_to_chart_payload(frame)

        names = [point["name"] for point in payload["mark_points_composite"]]
        self.assertIn("综合回踩", names)
        self.assertIn("综合离场", names)
        entry = next(point for point in payload["mark_points_composite"] if point["name"] == "综合回踩")
        exit_point = next(point for point in payload["mark_points_composite"] if point["name"] == "综合离场")
        self.assertEqual(entry["signalKey"], "composite_pullback")
        self.assertEqual(entry["signalCategory"], "entry")
        self.assertEqual(exit_point["signalCategory"], "exit")
        self.assertIn("date", entry)
        self.assertIn("price", entry)
        self.assertEqual(payload["stats_composite"]["b"]["count"], 1)
        self.assertEqual(payload["stats_composite"]["s"]["count"], 1)

    def test_serializer_outputs_composite_divergence_observation_marks(self):
        frame = self._minimal_signal_frame()
        frame.loc[4, "is_bottom_divergence"] = True
        frame.loc[6, "is_top_divergence"] = True

        events = build_composite_signal_events(frame)
        payload = analysis_frame_to_chart_payload(frame)

        self.assertIn("composite_bottom_divergence", [event.key for event in events])
        self.assertIn("composite_top_divergence", [event.key for event in events])
        bottom = next(point for point in payload["mark_points_composite"] if point["name"] == "综合底背离")
        top = next(point for point in payload["mark_points_composite"] if point["name"] == "综合顶背离")
        self.assertEqual(bottom["signalKey"], "composite_bottom_divergence")
        self.assertEqual(bottom["signalCategory"], "bottom")
        self.assertEqual(bottom["signalLabel"], "C底")
        self.assertEqual(bottom["signalOrder"], 80)
        self.assertEqual(top["signalKey"], "composite_top_divergence")
        self.assertEqual(top["signalCategory"], "top")

    def test_serializer_eventizes_legacy_opt_marks(self):
        frame = self._minimal_signal_frame()
        frame.loc[4, "opt_is_b_point"] = True
        frame.loc[6, "opt_is_pullback_b"] = True

        payload = analysis_frame_to_chart_payload(frame)

        names = [point["name"] for point in payload["mark_points_opt"]]
        self.assertIn("优化B点", names)
        self.assertIn("优化回踩", names)
        first = payload["mark_points_opt"][0]
        self.assertEqual(first["signalKey"], "opt_gold")
        self.assertEqual(first["signalGroup"], "opt")
        self.assertEqual(first["signalLabel"], "O★B")
        self.assertEqual(payload["signal_definitions"]["opt_pullback"]["label"], "O回")

    def test_event_backtest_outputs_signal_and_reason_stats(self):
        frame = self._minimal_signal_frame(rows=12)
        frame.loc[4, "composite_entry"] = True
        frame.loc[4, "composite_entry_type"] = "pullback"
        frame.loc[4, "composite_entry_reason"] = "底背离 / MACD多头"

        events = build_composite_signal_events(frame)
        stats = evaluate_signal_events(frame, events, horizon=5)
        payload = analysis_frame_to_chart_payload(frame)

        self.assertEqual(stats["entry_model"], "event_close")
        self.assertEqual(stats["by_signal"]["composite_pullback"]["evaluated_count"], 1)
        self.assertEqual(stats["by_signal"]["composite_pullback"]["entry_model"], "event_close")
        self.assertEqual(stats["by_signal"]["composite_pullback"]["win_rate"], 100.0)
        self.assertGreater(stats["by_signal"]["composite_pullback"]["avg_ret"], 0)
        self.assertIn("MACD多头", stats["by_reason"])
        self.assertEqual(payload["event_stats"]["composite"]["by_reason"]["底背离"]["evaluated_count"], 1)

    def test_event_backtest_supports_next_open_entry_model(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["open"] = [10.0] * 12
        frame.loc[4, "composite_entry"] = True
        frame.loc[4, "composite_entry_type"] = "pullback"
        frame.loc[4, "composite_entry_reason"] = "底背离 / MACD多头"

        events = build_composite_signal_events(frame)
        stats = evaluate_signal_events(frame, events, horizon=5, entry_model="next_open")

        pullback = stats["by_signal"]["composite_pullback"]
        self.assertEqual(stats["entry_model"], "next_open")
        self.assertEqual(pullback["entry_model"], "next_open")
        self.assertEqual(pullback["evaluated_count"], 1)
        self.assertAlmostEqual(pullback["avg_ret"], 10.0)
        self.assertEqual(pullback["win_rate"], 100.0)

    def test_event_backtest_next_open_skips_when_horizon_is_missing(self):
        frame = self._minimal_signal_frame(rows=10)
        frame.loc[4, "composite_entry"] = True
        frame.loc[4, "composite_entry_type"] = "pullback"

        events = build_composite_signal_events(frame)
        event_close = evaluate_signal_events(frame, events, horizon=5)
        next_open = evaluate_signal_events(frame, events, horizon=5, entry_model="next_open")

        self.assertEqual(event_close["by_signal"]["composite_pullback"]["evaluated_count"], 1)
        self.assertEqual(next_open["by_signal"]["composite_pullback"]["evaluated_count"], 0)
        self.assertIsNone(next_open["by_signal"]["composite_pullback"]["avg_ret"])

    def test_composite_strategy_uses_pullback_gate_and_position_stop_loss(self):
        frame = self._strategy_frame()
        frame.loc[1, "open"] = 9.9
        frame.loc[1, "close"] = 9.95
        frame.loc[1, "high"] = 10.1
        frame.loc[1, "low"] = 9.85
        frame.loc[1, "volume"] = 800
        frame.loc[2, "close"] = 9.3
        frame.loc[2, "high"] = 9.4
        frame.loc[2, "low"] = 9.2

        result = add_composite_strategy_columns(frame)

        self.assertTrue(result.loc[1, "composite_entry"])
        self.assertEqual(result.loc[1, "composite_entry_type"], "pullback")
        self.assertTrue(result["composite_exit"].any())
        exit_rows = result[result["composite_exit"]]
        self.assertEqual(exit_rows.iloc[0]["composite_exit_type"], "stop_loss")

    def test_composite_strategy_does_not_emit_risk_before_entry(self):
        frame = self._strategy_frame()

        result = add_composite_strategy_columns(frame)

        self.assertFalse(result["composite_entry"].any())
        self.assertFalse(result["composite_risk"].any())

    def test_composite_strategy_warns_on_top_divergence_after_entry(self):
        frame = self._strategy_frame()
        closes = [10.0, 10.2, 10.5, 10.4, 10.6, 10.7, 10.8, 10.9]
        frame["close"] = closes
        frame["open"] = [value - 0.05 for value in closes]
        frame["high"] = [value + 0.15 for value in closes]
        frame["low"] = [value - 0.15 for value in closes]
        frame["ma5"] = [9.8, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6]
        frame["ma20"] = [9.7, 9.9, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5]
        frame["dif"] = [0.10, 0.18, 0.22, 0.20, 0.21, 0.22, 0.23, 0.24]
        frame["dea"] = [0.05, 0.10, 0.13, 0.15, 0.16, 0.17, 0.18, 0.19]
        frame["break_ma5"] = False
        frame.loc[1, "open"] = 9.9
        frame.loc[1, "close"] = 9.95
        frame.loc[1, "high"] = 10.1
        frame.loc[1, "low"] = 9.85
        frame.loc[1, "volume"] = 800
        frame.loc[3, "is_top_divergence"] = True

        result = add_composite_strategy_columns(frame)

        self.assertTrue(result.loc[1, "composite_entry"])
        self.assertTrue(result.loc[3, "composite_risk_warn"])
        self.assertFalse(result.loc[3, "composite_exit"])
        self.assertEqual(result.loc[3, "composite_risk_type"], "top_divergence")
        self.assertIn("顶背离", result.loc[3, "composite_risk_reason"])

    def test_composite_breakout_requires_prior_high_break(self):
        rows = 25
        frame = pd.DataFrame({
            "open": [10.4] * rows,
            "high": [11.0] * rows,
            "low": [10.2] * rows,
            "close": [10.5] * rows,
            "volume": [1000] * rows,
            "custom": [0.1] * rows,
            "momentum_efficiency": [0.1] * rows,
            "dif": [0.20] * rows,
            "dea": [0.10] * rows,
            "ma5": [10.2] * rows,
            "ma20": [10.1] * rows,
            "vwap": [10.2] * rows,
            "j": [50.0] * rows,
            "trend_ok": [True] * rows,
            "ma20_up": [True] * rows,
            "vol_ma20": [900] * rows,
            "break_ma5": [False] * rows,
            "touch_upper": [False] * rows,
        })
        for column in [
            "is_b_point",
            "is_pullback_b",
            "new_is_b_point",
            "new_is_pullback_b",
            "opt_is_b_point",
            "opt_is_pullback_b",
            "is_bottom_divergence",
            "is_top_divergence",
        ]:
            frame[column] = False
        frame.loc[24, "open"] = 10.6
        frame.loc[24, "close"] = 10.9
        frame.loc[24, "high"] = 11.1
        frame.loc[24, "momentum_efficiency"] = 2.0

        result = add_composite_strategy_columns(frame.copy())
        self.assertFalse(result.loc[24, "composite_entry"])
        self.assertFalse(result.loc[24, "composite_prior_breakout"])

        frame.loc[24, "close"] = 11.2
        frame.loc[24, "high"] = 11.3
        result = add_composite_strategy_columns(frame)

        self.assertTrue(result.loc[24, "composite_prior_breakout"])
        self.assertTrue(result.loc[24, "composite_breakout_setup"])
        self.assertTrue(result.loc[24, "composite_entry"])
        self.assertEqual(result.loc[24, "composite_entry_type"], "breakout")
        self.assertIn("前高突破", result.loc[24, "composite_entry_reason"])

    def test_signal_module_adds_all_current_strategy_columns(self):
        rows = 25
        df = pd.DataFrame({
            "open": [10.0 + i * 0.1 for i in range(rows)],
            "high": [10.4 + i * 0.1 for i in range(rows)],
            "low": [9.8 + i * 0.1 for i in range(rows)],
            "close": [10.1 + i * 0.1 for i in range(rows)],
            "volume": [1000 + i * 20 for i in range(rows)],
            "custom": [(-1) ** i * (i + 1) for i in range(rows)],
            "dif": [0.1 + i * 0.01 for i in range(rows)],
            "dea": [0.05 + i * 0.005 for i in range(rows)],
            "ma5": [10.0 + i * 0.09 for i in range(rows)],
            "ma20": [9.9 + i * 0.08 for i in range(rows)],
            "upper_band": [10.8 + i * 0.1 for i in range(rows)],
            "adx": [20.0] * rows,
            "j": [50.0] * rows,
            "vwap": [10.0 + i * 0.08 for i in range(rows)],
        })

        result = add_signal_columns(df)

        for column in [
            "is_b_point",
            "is_pullback_b",
            "is_s_point",
            "touch_upper",
            "break_ma5",
            "ma20_up",
            "custom_acceleration",
            "new_is_b_point",
            "new_is_pullback_b",
            "new_is_s_point",
            "trend_ok",
            "opt_is_b_point",
            "opt_is_pullback_b",
            "opt_is_s_warn",
            "opt_is_s_confirm",
            "opt_is_s_point",
        ]:
            self.assertIn(column, result.columns)

        self.assertTrue(result["custom_acceleration"].equals(result["custom"].diff()))

    @patch("app.read_latest_scan_snapshot", return_value=None)
    @patch("app.read_scan_snapshot", return_value=None)
    @patch("app.write_scan_snapshot")
    @patch("app.get_stock_profile")
    @patch("app.get_stock_dataframe")
    def test_check_stock_signal_opt_matches_chart_buy_without_divergence(
        self,
        mock_dataframe,
        mock_profile,
        mock_write_snapshot,
        mock_read_snapshot,
        mock_read_latest_snapshot,
    ):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=9, freq="D"),
            "high": [10.2] * 9,
            "low": [9.8] * 9,
            "close": [10.0] * 9,
            "opt_is_b_point": [False] * 9,
            "opt_is_pullback_b": [False] * 9,
            "is_bottom_divergence": [False] * 9,
        })
        frame.loc[8, "opt_is_pullback_b"] = True
        mock_dataframe.return_value = frame
        mock_profile.return_value = {"name": "示例股票", "sector": "半导体"}

        result = app.check_stock_signal("600063", "opt")

        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "600063")
        self.assertEqual(result["name"], "示例股票")
        self.assertEqual(result["sector"], "半导体")
        self.assertEqual(result["signal"], "O回")

    @patch("app.read_latest_scan_snapshot", return_value=None)
    @patch("app.read_scan_snapshot", return_value=None)
    @patch("app.write_scan_snapshot")
    @patch("app.get_stock_profile")
    @patch("app.get_stock_dataframe")
    def test_check_stock_signal_composite_uses_composite_entry(
        self,
        mock_dataframe,
        mock_profile,
        mock_write_snapshot,
        mock_read_snapshot,
        mock_read_latest_snapshot,
    ):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=9, freq="D"),
            "high": [10.2] * 9,
            "low": [9.8] * 9,
            "close": [10.0] * 9,
            "composite_entry": [False] * 9,
            "composite_entry_type": ["pullback"] * 9,
            "composite_entry_reason": [""] * 9,
            "composite_exit": [False] * 9,
            "composite_risk_warn": [False] * 9,
            "is_bottom_divergence": [False] * 9,
            "is_top_divergence": [False] * 9,
        })
        frame.loc[8, "composite_entry"] = True
        mock_dataframe.return_value = frame
        mock_profile.return_value = {"name": "示例股票", "sector": "半导体"}

        result = app.check_stock_signal("600063", "composite")

        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "600063")
        self.assertEqual(result["signal"], "C回")
        self.assertEqual(result["signal_key"], "composite_pullback")
        self.assertIn("rank_score", result)

    def test_scan_events_for_mode_uses_recent_bottom_divergence_event(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=9, freq="D"),
            "high": [10.2] * 9,
            "low": [9.8] * 9,
            "close": [10.0] * 9,
            "is_b_point": [False] * 9,
            "is_pullback_b": [False] * 9,
            "is_bottom_divergence": [False] * 9,
        })
        frame.loc[7, "is_bottom_divergence"] = True

        events = scan_events_for_type(frame, "bottom_div")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].key, "composite_bottom_divergence")

    def test_scan_stock_frame_outputs_scored_opportunity_result(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [2] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_risk_break_score"] = [0] * 12
        frame["composite_risk_heat_score"] = [1] * 12
        frame["composite_prior_high_10"] = [10.51] * 12
        frame["composite_prior_breakout"] = [False] * 12
        frame["momentum_efficiency"] = [0.35] * 12
        frame["custom_z"] = [1.25] * 12
        frame["volume_ratio"] = [1.8] * 12
        frame["return_pct"] = [2.34] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "breakout"
        frame.loc[11, "composite_entry_reason"] = "突破MA20 / MACD多头"
        frame.loc[11, "composite_prior_breakout"] = True

        result = scan_stock_frame("600063", "示例股票", frame, "opportunity")

        self.assertIsNotNone(result)
        self.assertEqual(result["scan_type"], "opportunity")
        self.assertEqual(result["signal_key"], "composite_breakout")
        self.assertEqual(result["setup_score"], 1)
        self.assertEqual(result["confirm_score"], 2)
        self.assertEqual(result["risk_score"], 0)
        self.assertGreater(result["rank_score"], 0)
        self.assertEqual(result["risk_break_score"], 0)
        self.assertEqual(result["risk_heat_score"], 1)
        self.assertEqual(result["prior_high_10"], 10.51)
        self.assertTrue(result["prior_breakout"])
        self.assertEqual(result["momentum_efficiency"], 0.35)
        self.assertEqual(result["custom_z"], 1.25)
        self.assertEqual(result["volume_ratio"], 1.8)
        self.assertEqual(result["return_pct"], 2.34)
        driver_labels = [driver["label"] for driver in result["explanation"]["drivers"]]
        self.assertIn("突破诊断", driver_labels)
        self.assertIn("风险拆分", driver_labels)

    def test_risk_pool_marks_confirmed_risk_stage(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [1] * 12
        frame["composite_risk_score"] = [4] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_exit"] = True
        frame.loc[11, "composite_risk_reason"] = "趋势破坏 / 跌破MA20 / MACD转弱"
        frame.loc[11, "composite_risk_type"] = "trend_break"
        frame.loc[11, "composite_exit_type"] = "trend_break"

        result = scan_stock_frame("600063", "示例股票", frame, "risk")

        self.assertIsNotNone(result)
        self.assertEqual(result["pool_stage"], "confirmed_risk")
        self.assertEqual(result["pool_stage_label"], "强风险")
        self.assertEqual(result["pool_stage_tone"], "danger")

    def test_bottom_divergence_pool_marks_confirmation_stage(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["composite_setup_score"] = [3] * 12
        frame["composite_confirm_score"] = [4] * 12
        frame["composite_risk_score"] = [1] * 12
        frame["composite_watch"] = [True] * 12
        frame.loc[11, "is_bottom_divergence"] = True

        result = scan_stock_frame("600063", "示例股票", frame, "bottom_div")

        self.assertIsNotNone(result)
        self.assertEqual(result["pool_stage"], "trend_confirmed")
        self.assertEqual(result["pool_stage_label"], "趋势确认")
        self.assertEqual(result["pool_stage_tone"], "positive")

    def test_scan_snapshot_persists_all_scan_pool_results(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [4] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
        frame.loc[11, "composite_risk_warn"] = True
        frame.loc[11, "composite_risk_reason"] = "顶背离 / MACD转弱"

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
        risk = scan_result_from_snapshot(cached, "risk")

        self.assertIn("opportunity", cached["computed_scan_types"])
        self.assertIn("risk", cached["computed_scan_types"])
        self.assertEqual(cached["sector"], "半导体")
        self.assertEqual(opportunity["sector"], "半导体")
        self.assertEqual(opportunity["signal_key"], "composite_pullback")
        self.assertEqual(risk["signal_key"], "composite_warning")
        self.assertEqual(cached["trade_plan"]["status"], "risk_control")
        self.assertEqual(opportunity["trade_plan"]["status"], "risk_control")
        self.assertEqual(risk["trade_plan"]["permission"]["mode"], "risk_control")

    def test_check_stock_signal_reuses_snapshot_for_other_scan_types(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [4] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
        frame.loc[11, "composite_risk_warn"] = True
        frame.loc[11, "composite_risk_reason"] = "顶背离 / MACD转弱"

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-10")):
                    with patch("app.get_stock_dataframe", return_value=frame) as mock_dataframe:
                        with patch("app.get_stock_profile", return_value={"name": "示例股票", "sector": "半导体"}):
                            first = app.check_stock_signal("600063", "opportunity")
                            second = app.check_stock_signal("600063", "risk")

        self.assertEqual(mock_dataframe.call_count, 1)
        self.assertEqual(first["signal_key"], "composite_pullback")
        self.assertEqual(second["signal_key"], "composite_warning")
        self.assertEqual(second["name"], "示例股票")

    def test_latest_scan_snapshot_reuses_previous_calendar_day(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    old_snapshot = build_scan_snapshot("600063", "600063", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(old_snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    latest = read_latest_scan_snapshot("600063", start_date="2025-04-29")

        self.assertEqual(latest["snapshot_day"], "20260510")
        self.assertEqual(scan_result_from_snapshot(latest, "opportunity")["signal_key"], "composite_pullback")

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

        self.assertTrue(is_recent_snapshot(snapshot, now_day="2026-05-11 14:50:00"))
        self.assertFalse(is_recent_snapshot(snapshot, now_day="2026-05-11 16:00:00"))
        self.assertTrue(is_recent_snapshot(previous_day_snapshot, now_day="2026-05-11 14:50:00"))
        self.assertFalse(is_recent_snapshot(previous_day_snapshot, now_day="2026-05-11 16:00:00"))
        self.assertTrue(is_recent_snapshot({"snapshot_day": "20260511", "data_date": "2026-05-11"}, now_day="2026-05-11 16:00:00"))

    def test_check_stock_signal_uses_latest_snapshot_without_reloading_data(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        self.assertEqual(result["signal_key"], "composite_pullback")
        self.assertEqual(result["name"], "示例股票")
        self.assertEqual(result["scan_source"], "cache")

    def test_check_stock_signal_auto_recomputes_legacy_strategy_snapshot(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        self.assertEqual(result["signal_key"], "composite_pullback")
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
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
        mock_dataframe.return_value = frame

        result = app.check_stock_signal("600063", "opportunity", refresh_policy="force")

        mock_read_snapshot.assert_not_called()
        mock_read_latest_snapshot.assert_not_called()
        mock_dataframe.assert_called_once_with("600063")
        self.assertEqual(result["signal_key"], "composite_pullback")
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
        self.assertIn("板块共振强", explanation["summary"])
        self.assertEqual(explanation["drivers"][0]["label"], "事件触发")
        self.assertEqual(explanation["score_badges"][3]["label"], "共振")
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
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
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
        self.assertEqual(result["signal_key"], "composite_pullback")

    def test_scan_batch_calculate_signals_creates_missing_legacy_columns(self):
        df = pd.DataFrame({
            "open": [10.0, 10.2],
            "high": [10.5, 10.4],
            "low": [9.8, 10.0],
            "close": [10.1, 10.3],
            "volume": [1000, 900],
            "ma20": [10.0, 10.1],
            "ma20_prev": [9.9, 10.0],
            "j": [20.0, 25.0],
            "bias": [-16.0, -14.0],
            "bb_position": [0.1, 0.3],
            "volume_ma5_prev": [1500, 1200],
            "volume_ma10_prev": [1500, 1200],
            "is_bottom_divergence": [1, 0],
            "is_top_divergence": [0, 0],
            "dif": [0.1, 0.2],
            "dea": [0.0, 0.1],
        })

        result = scan_batch.calculate_signals(df)

        self.assertIn("is_s_point", result.columns)
        self.assertIn("is_pullback_b", result.columns)
        self.assertIn("new_is_b_point", result.columns)
        self.assertIn("new_is_pullback_b", result.columns)
        self.assertIn("new_is_s_point", result.columns)

    @patch("scripts.scan_uptrend_divergence.requests.get")
    def test_analyze_via_api_reads_close_from_kline_payload(self, mock_get):
        payload = {
            "dates": [f"2026-01-{day:02d}" for day in range(1, 12)],
            "k_data": [[10.0, 10.25, 9.8, 10.4]] * 11,
            "ma20_data": list(range(11)),
            "mark_points_new": [],
            "mark_points_old": [],
            "stock_name": "示例股票 (600063)",
        }
        response = Mock(status_code=200)
        response.json.return_value = payload
        mock_get.return_value = response

        result = scan_uptrend_divergence.analyze_via_api("600063")

        self.assertIsNotNone(result)
        self.assertEqual(result["close"], 10.25)
        self.assertTrue(result["is_uptrend"])


if __name__ == "__main__":
    unittest.main()
