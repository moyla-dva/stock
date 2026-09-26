"""Provider adapters for recent minute-level A-share price history."""

import logging

import akshare as ak
import pandas as pd

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.provider_network import configure_default_socket_timeout
from stock_analyzer.providers.tdx_client import fetch_tdx_minute_bars

LOGGER = logging.getLogger(__name__)


def _log(logger, level, message):
    target = logger or LOGGER
    getattr(target, level)(message)


def market_symbol_for_sina(code):
    """Return Sina's market-prefixed symbol for A-share minute data."""
    code = normalize_code(code)
    if not code:
        return None
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def _filter_by_range(df, start_text, end_text):
    if df is None or df.empty:
        return df
    date_column = next((column for column in ("day", "时间", "date", "日期") if column in df.columns), None)
    if not date_column:
        return df
    frame = df.copy()
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    start_at = pd.to_datetime(start_text, errors="coerce")
    end_at = pd.to_datetime(end_text, errors="coerce")
    mask = dates.notna()
    if not pd.isna(start_at):
        mask &= dates >= start_at
    if not pd.isna(end_at):
        mask &= dates <= end_at
    return frame[mask].copy()


class StockMinuteHistoryProvider:
    """Fetch recent minute history with Sina as primary and TDX as fallback."""

    def fetch_history(self, code, start_text, end_text, period="60", adjust="qfq", logger=None, verbose=False):
        code = normalize_code(code)
        if not code:
            return None

        sina_symbol = market_symbol_for_sina(code)
        configure_default_socket_timeout()
        try:
            if verbose or logger:
                _log(logger, "info", f"正在从新浪获取分时数据: symbol={sina_symbol}, period={period}")
            df = ak.stock_zh_a_minute(symbol=sina_symbol, period=str(period), adjust=adjust or "")
            df = _filter_by_range(df, start_text, end_text)
            if verbose or logger:
                _log(logger, "info", f"新浪分时数据获取完成，shape={df.shape if df is not None else 'None/Empty'}")
            if df is not None and not df.empty:
                return df
        except Exception as exc:
            if verbose or logger:
                _log(logger, "error", f"stock_zh_a_minute 失败: {exc}")

        if adjust in ("", "none", None):
            try:
                if verbose or logger:
                    _log(logger, "info", f"备选方案: 从 TDX 获取分时数据: code={code}, period={period}")
                return fetch_tdx_minute_bars(
                    code,
                    start_text,
                    end_text,
                    period=str(period),
                    logger=logger,
                    verbose=verbose,
                )
            except Exception as exc:
                if verbose or logger:
                    _log(logger, "error", f"TDX 分时数据获取失败: {exc}")
        return None


DEFAULT_STOCK_MINUTE_HISTORY_PROVIDER = StockMinuteHistoryProvider()
