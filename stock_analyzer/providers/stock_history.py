"""Provider adapters for daily A-share price history."""

import json
import logging
from datetime import datetime

import akshare as ak
import pandas as pd
import requests

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.market_data_identity import attach_market_data_identity
from stock_analyzer.provider_network import configure_default_socket_timeout
from stock_analyzer.providers.tdx_client import fetch_tdx_daily_bars

LOGGER = logging.getLogger(__name__)


def _log(logger, level, message):
    target = logger or LOGGER
    getattr(target, level)(message)


def market_symbol_for_tx(code):
    """Return Tencent's market-prefixed symbol for沪深京 A-share codes."""
    code = normalize_code(code)
    if not code:
        return None
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def tencent_volume_to_shares(code, volume):
    """Convert Tencent's code-specific volume field to shares.

    This mirrors the unit normalization used by the installed AkShare Tencent
    history adapter: most stock symbols are reported in lots, while STAR Market
    symbols and indices are already reported in shares.
    """
    symbol = market_symbol_for_tx(code)
    try:
        value = float(volume)
    except (TypeError, ValueError):
        return None
    if not pd.notna(value):
        return None
    if symbol and symbol.startswith(("sh688", "sz399", "sh000", "sz000")):
        return value
    return value * 100


def _merge_history_frames(earlier, later):
    """Keep the full earlier range while letting the direct fetch win overlaps."""
    if earlier is None or earlier.empty:
        return later
    from stock_analyzer.normalizer import normalize_price_frame

    frames = [
        normalize_price_frame(frame)
        for frame in (earlier, later)
        if frame is not None and not frame.empty
    ]
    if not frames:
        return None
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"], keep="last")
    merged = merged.sort_values("date").reset_index(drop=True)
    if len(frames) > 1:
        attach_market_data_identity(
            merged,
            data_source="tencent_via_akshare+tencent_direct",
        )
    else:
        attach_market_data_identity(merged, data_source="tencent_direct")
    return merged


def _fetch_tx_history_direct(
    tx_code,
    start_text,
    end_text,
    adjust="",
    logger=None,
    verbose=False,
):
    """Fetch Tencent daily history directly when AkShare's wrapper cannot parse it."""
    if not tx_code:
        return None

    try:
        range_start = int(start_text[:4])
        range_end = int(end_text[:4]) + 1
    except (TypeError, ValueError):
        return None

    rows = []
    attempts = []
    timeout = configure_default_socket_timeout()
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    current_year = datetime.now().year
    for year in range(range_start, range_end):
        end_date_str = "" if year >= current_year else f"{year + 1}-12-31"
        params = {
            "_var": f"kline_day{adjust}{year}",
            "param": f"{tx_code},day,{year}-01-01,{end_date_str},640,{adjust}",
            "r": "0.8205512681390605",
        }
        try:
            response = requests.get(url, params=params, timeout=timeout)
            data_text = response.text
            payload_start = data_text.find("={")
            if payload_start < 0:
                attempts.append({
                    "provider": "tencent_direct",
                    "period": str(year),
                    "status": "error",
                    "error_type": "InvalidPayload",
                })
                continue
            data_json = json.loads(data_text[payload_start + 1 :])
            symbol_data = (data_json.get("data") or {}).get(tx_code) or {}
            day_rows = (
                symbol_data.get("day")
                or symbol_data.get("qfqday")
                or symbol_data.get("hfqday")
                or []
            )
            rows.extend(day_rows)
            attempts.append({
                "provider": "tencent_direct",
                "period": str(year),
                "status": "data" if day_rows else "empty",
            })
        except Exception as e:
            attempts.append({
                "provider": "tencent_direct",
                "period": str(year),
                "status": "error",
                "error_type": type(e).__name__,
            })
            if verbose or logger:
                _log(logger, "error", f"腾讯源直接获取失败: {tx_code}, year={year}, error={e}")

    if not rows:
        frame = pd.DataFrame()
        frame.attrs["provider_attempts"] = attempts
        return frame

    frame = pd.DataFrame(rows).iloc[:, :6]
    frame.columns = ["date", "open", "close", "high", "low", "volume"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "close", "high", "low", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(subset=["date", "open", "close", "high", "low"], inplace=True)
    frame["volume"] = frame["volume"].map(lambda value: tencent_volume_to_shares(tx_code, value))
    frame.drop_duplicates(subset=["date"], inplace=True, ignore_index=True)
    frame.sort_values("date", inplace=True)

    start_date = pd.to_datetime(start_text, format="%Y%m%d", errors="coerce")
    end_date = pd.to_datetime(end_text, format="%Y%m%d", errors="coerce")
    if not pd.isna(start_date):
        frame = frame[frame["date"] >= start_date]
    if not pd.isna(end_date):
        frame = frame[frame["date"] <= end_date]
    frame.reset_index(drop=True, inplace=True)
    frame["date"] = frame["date"].dt.date
    attach_market_data_identity(frame, data_source="tencent_direct")
    frame.attrs["provider_attempts"] = attempts
    return frame


class StockHistoryProvider:
    """Fetch raw daily stock history from external providers."""

    def fetch_history(self, code, start_text, end_text, adjust="", logger=None, verbose=False):
        frame, _ = self.fetch_history_with_diagnostics(
            code,
            start_text,
            end_text,
            adjust=adjust,
            logger=logger,
            verbose=verbose,
        )
        return frame

    def fetch_history_with_diagnostics(self, code, start_text, end_text, adjust="", logger=None, verbose=False):
        code = normalize_code(code)
        if not code:
            return None, []

        df = None
        attempts = []
        tx_code = market_symbol_for_tx(code)
        timeout = configure_default_socket_timeout()

        try:
            if verbose or logger:
                _log(logger, "info", f"正在从 akshare 获取数据: {tx_code}, start={start_text}, end={end_text}")
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_code,
                start_date=start_text,
                end_date=end_text,
                adjust=adjust,
                timeout=timeout,
            )
            attempts.append({
                "provider": "tencent_via_akshare",
                "status": "data" if df is not None and not df.empty else "empty",
            })
            if df is not None and not df.empty:
                attach_market_data_identity(df, data_source="tencent_via_akshare")
            if verbose or logger:
                _log(logger, "info", f"第一轮获取完成，shape={df.shape if df is not None else 'None/Empty'}")
        except Exception as e:
            attempts.append({
                "provider": "tencent_via_akshare",
                "status": "error",
                "error_type": type(e).__name__,
            })
            if verbose or logger:
                _log(logger, "error", f"ak.stock_zh_a_hist_tx 失败: {e}")
            df = None

        latest_date_str = ""
        if df is not None and not df.empty:
            for col in ("date", "日期"):
                if col in df.columns:
                    s = pd.to_datetime(df[col], errors="coerce").dropna()
                    if not s.empty:
                        latest_date_str = s.max().strftime("%Y%m%d")
                    break

        # 当 akshare 获取为空、或返回数据落后于目标收盘日（例如盘后静态缓存未更新）时，调用腾讯直连
        if (df is None or df.empty) or (end_text and latest_date_str and latest_date_str < str(end_text)):
            if verbose or logger:
                _log(logger, "info", f"触发腾讯直连获取最新数据: {tx_code}")
            direct_df = _fetch_tx_history_direct(
                tx_code,
                start_text,
                end_text,
                adjust=adjust,
                logger=logger,
                verbose=verbose,
            )
            direct_attempts = getattr(direct_df, "attrs", {}).get("provider_attempts") or []
            attempts.extend(direct_attempts)
            if not direct_attempts:
                attempts.append({
                    "provider": "tencent_direct",
                    "status": "data" if direct_df is not None and not direct_df.empty else "empty",
                })
            if direct_df is not None and not direct_df.empty:
                attach_market_data_identity(direct_df, data_source="tencent_direct")
                df = _merge_history_frames(df, direct_df)

        if (df is None or df.empty) and adjust in ("", "none", None):
            try:
                if verbose or logger:
                    _log(logger, "info", f"备选方案: 使用 TDX 获取日线: code={code}")
                df = fetch_tdx_daily_bars(code, start_text, end_text, logger=logger, verbose=verbose)
                attempts.append({
                    "provider": "tdx",
                    "status": "data" if df is not None and not df.empty else "empty",
                })
                if df is not None and not df.empty:
                    attach_market_data_identity(df, data_source="tdx")
            except Exception as e:
                attempts.append({
                    "provider": "tdx",
                    "status": "error",
                    "error_type": type(e).__name__,
                })
                if verbose or logger:
                    _log(logger, "error", f"TDX 日线获取失败: {e}")
                df = None

        return df, attempts


DEFAULT_STOCK_HISTORY_PROVIDER = StockHistoryProvider()
