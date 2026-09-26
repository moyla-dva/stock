"""Shared pytdx helpers: stock list, daily bars, and minute bars from TDX quote servers.

pytdx speaks TDX's private protocol over raw TCP, so HTTP proxy environment
variables do not apply and Eastmoney-style WAF fingerprinting is not a factor.
"""

import threading
import logging

import pandas as pd
from pytdx.hq import TdxHq_API

TDX_HOSTS = (
    ("119.147.212.81", 7709),
    ("115.238.90.165", 7709),
    ("218.108.98.244", 7709),
)

MINUTE_CATEGORY = {"1": 7, "5": 0, "15": 1, "30": 2, "60": 3}

_api = None
_API_LOCK = threading.RLock()
LOGGER = logging.getLogger(__name__)


def _log(logger, level, message):
    target = logger or LOGGER
    getattr(target, level)(message)


def _connect():
    """Return a connected module-level API instance, rotating across hosts."""
    global _api
    with _API_LOCK:
        if _api is not None:
            return _api
        api = TdxHq_API()
        for ip, port in TDX_HOSTS:
            try:
                if api.connect(ip, port, time_out=6):
                    _api = api
                    return _api
            except Exception:
                continue
        raise ConnectionError("无法连接任何通达信行情主站")


def _reset():
    global _api
    with _API_LOCK:
        try:
            if _api is not None:
                _api.disconnect()
        except Exception:
            pass
        _api = None


def _call(method_name, *args, retries=2, **kwargs):
    """Call a method on the current connection, reconnecting between attempts."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            with _API_LOCK:
                api = _connect()
                result = getattr(api, method_name)(*args, **kwargs)
            if result is not None:
                return result
        except Exception as e:
            last_error = e
        if attempt < retries:
            _reset()
    if last_error:
        raise last_error
    return None


def tdx_market_for(code):
    """Return pytdx market id for SH/SZ A-share codes, None otherwise."""
    code = str(code)
    if code.startswith("6"):
        return 1
    if code.startswith(("0", "3")):
        return 0
    return None


A_SHARE_PREFIXES = {
    1: ("600", "601", "603", "605", "688", "689"),
    0: ("000", "001", "002", "003", "300", "301", "43", "83", "87", "92"),
}


def fetch_tdx_stock_codes(logger=None):
    """Fetch the full A-share code list by paging get_security_list.

    pytdx paging is 1-based with 1000 rows per page, and host behaviour is
    inconsistent, so every host is validated before being trusted.
    """
    last_error = None
    for ip, port in TDX_HOSTS:
        api = TdxHq_API()
        try:
            if not api.connect(ip, port, time_out=6):
                continue
            codes = []
            for market, prefixes in A_SHARE_PREFIXES.items():
                total = api.get_security_count(market)
                if not total or total < 5000:
                    continue
                # 列表 offset 空间存在保留空洞（如沪市前 1000、深市中段），
                # 探测起点后按 1000 步进，遇到空洞跳过，连续多次空页视为到尾。
                first_page = None
                base = None
                for candidate in (1, 1000):
                    probe = api.get_security_list(market, candidate)
                    if probe:
                        first_page = probe
                        base = candidate
                        break
                if first_page is None:
                    continue
                for row in first_page:
                    code = str(row.get("code") or "")
                    if code.startswith(prefixes):
                        codes.append(code)
                start = base + 1000
                misses = 0
                while start <= total + 1000 and misses < 4:
                    rows = api.get_security_list(market, start)
                    if rows:
                        misses = 0
                        for row in rows:
                            code = str(row.get("code") or "")
                            if code.startswith(prefixes):
                                codes.append(code)
                    else:
                        misses += 1
                    start += 1000
            if codes:
                if logger:
                    logger.info(f"TDX 股票清单获取完成: {len(codes)} 只")
                return codes
        except Exception as e:
            last_error = e
        finally:
            try:
                api.disconnect()
            except Exception:
                pass
    if last_error:
        raise last_error
    raise ConnectionError("所有通达信主站的股票清单均不可用")


def fetch_tdx_daily_bars(code, start_text, end_text, logger=None, verbose=False):
    """Fetch daily bars as a frame matching the Tencent provider's column layout."""
    code = str(code)
    market = tdx_market_for(code)
    if market is None:
        return None
    rows = []
    start_ts = pd.to_datetime(str(start_text), errors="coerce")
    offset = 0
    for _ in range(40):
        page = _call("get_security_bars", 9, market, code, offset, 700)
        if not page:
            break
        rows = page + rows
        offset += len(page)
        oldest = pd.to_datetime(str(page[0].get("datetime") or "")[:10], errors="coerce")
        if (not pd.isna(start_ts) and not pd.isna(oldest) and oldest <= start_ts) or len(page) < 700:
            break
    if not rows:
        return None

    frame = pd.DataFrame(
        [
            {
                "date": str(bar.get("datetime") or "")[:10],
                "open": bar.get("open"),
                "close": bar.get("close"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "amount": bar.get("vol"),
            }
            for bar in rows
        ]
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "close", "high", "low", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(subset=["date", "open", "close", "high", "low"], inplace=True)
    frame.drop_duplicates(subset=["date"], inplace=True, ignore_index=True)
    frame.sort_values("date", inplace=True)

    start_date = start_ts
    end_date = pd.to_datetime(str(end_text), errors="coerce")
    if not pd.isna(start_date):
        frame = frame[frame["date"] >= start_date]
    if not pd.isna(end_date):
        frame = frame[frame["date"] <= end_date]
    frame.reset_index(drop=True, inplace=True)
    frame["date"] = frame["date"].dt.date
    if verbose or logger:
        _log(logger, "info", f"TDX 日线 {code}: {len(frame)} 根")
    return frame if not frame.empty else None


def fetch_tdx_minute_bars(code, start_text, end_text, period="60", logger=None, verbose=False):
    """Fetch minute bars as a frame matching the Sina provider's column layout."""
    code = str(code)
    market = tdx_market_for(code)
    category = MINUTE_CATEGORY.get(str(period))
    if market is None or category is None:
        return None
    rows = []
    start_ts = pd.to_datetime(str(start_text), errors="coerce")
    offset = 0
    for _ in range(12):
        page = _call("get_security_bars", category, market, code, offset, 700)
        if not page:
            break
        rows = page + rows
        offset += len(page)
        oldest = pd.to_datetime(str(page[0].get("datetime") or "")[:10], errors="coerce")
        if (not pd.isna(start_ts) and not pd.isna(oldest) and oldest <= start_ts) or len(page) < 700:
            break
    if not rows:
        return None

    frame = pd.DataFrame(
        [
            {
                "day": str(bar.get("datetime") or ""),
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": bar.get("vol"),
            }
            for bar in rows
        ]
    )
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(subset=["day", "close"], inplace=True)

    start_at = pd.to_datetime(str(start_text), errors="coerce")
    end_at = pd.to_datetime(str(end_text), errors="coerce")
    dates = pd.to_datetime(frame["day"], errors="coerce")
    mask = dates.notna()
    if not pd.isna(start_at):
        mask &= dates >= start_at
    if not pd.isna(end_at):
        mask &= dates <= end_at
    frame = frame[mask].reset_index(drop=True)
    if verbose or logger:
        _log(logger, "info", f"TDX 分钟线 {code}: {len(frame)} 根")
    return frame if not frame.empty else None
