"""Daily market data access and local history cache."""

import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.providers.stock_history import (
    DEFAULT_STOCK_HISTORY_PROVIDER,
    _fetch_tx_history_direct,
    market_symbol_for_tx,
)

CACHE_DIR = Path(os.environ.get(
    "STOCK_ANALYZER_CACHE_DIR",
    Path(__file__).resolve().parents[1] / ".cache" / "history",
))


def disable_proxies():
    """Disable local proxy environment variables for data providers that need it."""
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(key, None)
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"


def beijing_now():
    """Return current Beijing time using UTC as the source clock."""
    return datetime.now(timezone.utc) + timedelta(hours=8)


def date_range_for_recent_days(days=120):
    end = beijing_now()
    start = end - timedelta(days=days)
    return start, end


def parse_start_date(start_date):
    if start_date is None:
        return None
    if hasattr(start_date, "strftime"):
        return start_date
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(str(start_date), pattern)
        except ValueError:
            continue
    raise ValueError("start_date must use YYYY-MM-DD or YYYYMMDD format")


def date_range_for_fetch(days=120, start_date=None):
    end = beijing_now()
    explicit_start = parse_start_date(start_date)
    if explicit_start is not None:
        return explicit_start, end
    return date_range_for_recent_days(days)


def cache_path_for_history(code, start_text, end_text, adjust=""):
    adjust_key = adjust or "none"
    return CACHE_DIR / f"{code}_{start_text}_{end_text}_{adjust_key}.csv"


def _latest_history_date_text(frame):
    if frame is None or frame.empty:
        return None
    for column in ("date", "日期"):
        if column not in frame.columns:
            continue
        dates = pd.to_datetime(frame[column], errors="coerce").dropna()
        if not dates.empty:
            return dates.max().strftime("%Y%m%d")
    return None


def _current_day_cache_is_stale(frame, end_text):
    try:
        requested_end = datetime.strptime(str(end_text), "%Y%m%d")
    except ValueError:
        return False

    now = beijing_now()
    if hasattr(now, "to_pydatetime"):
        now = now.to_pydatetime()
    if now.strftime("%Y%m%d") != str(end_text):
        return False
    if requested_end.weekday() >= 5 or now.time() < time(15, 10):
        return False

    latest_text = _latest_history_date_text(frame)
    return bool(latest_text and latest_text < str(end_text))


def read_cached_history(code, start_text, end_text, adjust="", logger=None):
    path = cache_path_for_history(code, start_text, end_text, adjust=adjust)
    if not path.exists():
        return None
    try:
        cached = pd.read_csv(path)
        if _current_day_cache_is_stale(cached, end_text):
            if logger:
                latest = _latest_history_date_text(cached) or "-"
                logger.info(f"日线缓存缺少今日数据，重新拉取: {path.name}, latest={latest}, end={end_text}")
            return None
        if logger:
            logger.info(f"命中日线缓存: {path.name}, shape={cached.shape}")
        return cached
    except Exception as e:
        if logger:
            logger.warning(f"读取日线缓存失败: {path.name}, error={e}")
        return None


def write_cached_history(code, start_text, end_text, df, adjust="", logger=None):
    if df is None or df.empty:
        return
    path = cache_path_for_history(code, start_text, end_text, adjust=adjust)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        if logger:
            logger.info(f"写入日线缓存: {path.name}, shape={df.shape}")
    except Exception as e:
        if logger:
            logger.warning(f"写入日线缓存失败: {path.name}, error={e}")


def fetch_stock_history(
    code,
    days=120,
    start_date=None,
    adjust="",
    use_cache=False,
    use_disable_proxies=False,
    logger=None,
    verbose=False,
    provider=None,
):
    """Fetch daily A-share history with the existing two-provider fallback."""
    code = normalize_code(code)
    if not code:
        return None

    start, end = date_range_for_fetch(days=days, start_date=start_date)
    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")

    if use_cache:
        cached = read_cached_history(code, start_text, end_text, adjust=adjust, logger=logger)
        if cached is not None and not cached.empty:
            return cached

    if use_disable_proxies:
        disable_proxies()

    provider = provider or DEFAULT_STOCK_HISTORY_PROVIDER
    df = provider.fetch_history(
        code,
        start_text,
        end_text,
        adjust=adjust,
        logger=logger,
        verbose=verbose,
    )

    if use_cache and df is not None and not df.empty:
        write_cached_history(code, start_text, end_text, df, adjust=adjust, logger=logger)

    return df
