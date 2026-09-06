"""Provider adapters for daily A-share price history."""

import json

import akshare as ak
import pandas as pd
import requests

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.provider_network import configure_default_socket_timeout
from stock_analyzer.providers.tdx_client import fetch_tdx_daily_bars


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


def _fetch_tx_history_direct(tx_code, start_text, end_text, adjust="", logger=None, verbose=False):
    """Fetch Tencent daily history directly when AkShare's wrapper cannot parse it."""
    if not tx_code:
        return None

    try:
        range_start = int(start_text[:4])
        range_end = int(end_text[:4]) + 1
    except (TypeError, ValueError):
        return None

    rows = []
    timeout = configure_default_socket_timeout()
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    for year in range(range_start, range_end):
        params = {
            "_var": f"kline_day{adjust}{year}",
            "param": f"{tx_code},day,{year}-01-01,{year + 1}-12-31,640,{adjust}",
            "r": "0.8205512681390605",
        }
        try:
            response = requests.get(url, params=params, timeout=timeout)
            data_text = response.text
            payload_start = data_text.find("={")
            if payload_start < 0:
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
        except Exception as e:
            if verbose:
                print(f"[ERROR] 腾讯源直接获取失败: {tx_code}, year={year}, error={e}", flush=True)
            if logger:
                logger.error(f"腾讯源直接获取失败: {tx_code}, year={year}, error={e}")

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows).iloc[:, :6]
    frame.columns = ["date", "open", "close", "high", "low", "amount"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "close", "high", "low", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(subset=["date", "open", "close", "high", "low"], inplace=True)
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
    return frame


class StockHistoryProvider:
    """Fetch raw daily stock history from external providers."""

    def fetch_history(self, code, start_text, end_text, adjust="", logger=None, verbose=False):
        code = normalize_code(code)
        if not code:
            return None

        df = None
        tx_code = market_symbol_for_tx(code)
        timeout = configure_default_socket_timeout()

        try:
            if verbose:
                print(f"[DEBUG] 正在从 akshare 获取数据: {tx_code}, start={start_text}, end={end_text}", flush=True)
            if logger:
                logger.info(f"正在从 akshare 获取数据: {tx_code}, start={start_text}, end={end_text}")
            df = ak.stock_zh_a_hist_tx(
                symbol=tx_code,
                start_date=start_text,
                end_date=end_text,
                adjust=adjust,
                timeout=timeout,
            )
            if verbose:
                print(f"[DEBUG] 第一轮获取完成，shape={df.shape if df is not None else 'None/Empty'}", flush=True)
            if logger:
                logger.info(f"第一轮获取完成，shape={df.shape if df is not None else 'None/Empty'}")
        except Exception as e:
            if verbose:
                print(f"[ERROR] ak.stock_zh_a_hist_tx 失败: {e}", flush=True)
            if logger:
                logger.error(f"ak.stock_zh_a_hist_tx 失败: {e}")
            df = None

        if (df is None or df.empty) and tx_code and tx_code.startswith("bj"):
            if verbose:
                print(f"[DEBUG] 北交所兜底: 直接从腾讯源获取数据: {tx_code}", flush=True)
            if logger:
                logger.info(f"北交所兜底: 直接从腾讯源获取数据: {tx_code}")
            df = _fetch_tx_history_direct(
                tx_code,
                start_text,
                end_text,
                adjust=adjust,
                logger=logger,
                verbose=verbose,
            )

        if (df is None or df.empty) and adjust in ("", "none", None):
            try:
                if verbose:
                    print(f"[DEBUG] 备选方案: 使用 TDX 获取日线: code={code}", flush=True)
                if logger:
                    logger.info(f"备选方案: 使用 TDX 获取日线: code={code}")
                df = fetch_tdx_daily_bars(code, start_text, end_text, logger=logger, verbose=verbose)
            except Exception as e:
                if verbose:
                    print(f"[ERROR] TDX 日线获取失败: {e}", flush=True)
                if logger:
                    logger.error(f"TDX 日线获取失败: {e}")
                df = None

        return df


DEFAULT_STOCK_HISTORY_PROVIDER = StockHistoryProvider()
