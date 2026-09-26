"""Recent intraday market data access and local minute-history cache."""

import os
from datetime import datetime, time
from pathlib import Path
from uuid import uuid4

import pandas as pd

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.data_fetcher import beijing_now, disable_proxies
from stock_analyzer.providers.stock_history_minute import DEFAULT_STOCK_MINUTE_HISTORY_PROVIDER

MINUTE_CACHE_DIR = Path(
    os.environ.get(
        "STOCK_ANALYZER_MINUTE_CACHE_DIR",
        Path(__file__).resolve().parents[1] / ".cache" / "history_minute",
    )
)


def minute_date_range_for_fetch(days=90):
    end = beijing_now()
    start = end - pd.Timedelta(days=days)
    return start, end


def cache_path_for_minute_history(code, period, start_text, end_text, adjust="qfq"):
    adjust_key = adjust or "none"
    return MINUTE_CACHE_DIR / f"{code}_{period}_{start_text}_{end_text}_{adjust_key}.csv"


def _minute_date_series(frame):
    if frame is None or frame.empty:
        return None
    for column in ("day", "时间", "date", "日期"):
        if column in frame.columns:
            return pd.to_datetime(frame[column], errors="coerce")
    return None


def _minute_price_columns(frame):
    if frame is None or frame.empty:
        return []
    english = ["open", "high", "low", "close"]
    chinese = ["开盘", "最高", "最低", "收盘"]
    if all(column in frame.columns for column in english):
        return english
    if all(column in frame.columns for column in chinese):
        return chinese
    return []


def _latest_usable_minute_timestamp(frame):
    dates = _minute_date_series(frame)
    price_columns = _minute_price_columns(frame)
    if dates is None or not price_columns:
        return None

    mask = dates.notna()
    for column in price_columns:
        mask &= pd.to_numeric(frame[column], errors="coerce").notna()
    if not mask.any():
        return None
    return dates[mask].max()


def _latest_usable_minute_date_text(frame):
    latest = _latest_usable_minute_timestamp(frame)
    return latest.strftime("%Y%m%d") if latest is not None else None


def _current_day_minute_cache_is_stale(frame, end_text):
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

    latest = _latest_usable_minute_timestamp(frame)
    if latest is None or latest.strftime("%Y%m%d") < str(end_text):
        return True
    return latest.strftime("%Y%m%d") == str(end_text) and latest.time() < time(15, 0)


def read_cached_minute_history(code, period, start_text, end_text, adjust="qfq", logger=None):
    path = cache_path_for_minute_history(code, period, start_text, end_text, adjust=adjust)
    if not path.exists():
        return None
    try:
        cached = pd.read_csv(path)
        if _current_day_minute_cache_is_stale(cached, end_text):
            if logger:
                latest = _latest_usable_minute_date_text(cached) or "-"
                logger.info(f"分时缓存缺少今日有效K线，重新拉取: {path.name}, latest={latest}, end={end_text}")
            return None
        if logger:
            logger.info(f"命中分时缓存: {path.name}, shape={cached.shape}")
        return cached
    except Exception as exc:
        if logger:
            logger.warning(f"读取分时缓存失败: {path.name}, error={exc}")
        return None


def write_cached_minute_history(code, period, start_text, end_text, df, adjust="qfq", logger=None):
    if df is None or df.empty:
        return
    if _current_day_minute_cache_is_stale(df, end_text):
        if logger:
            latest = _latest_usable_minute_date_text(df) or "-"
            logger.info(f"分时数据缺少今日有效K线，暂不写入缓存: {code}_{period}, latest={latest}, end={end_text}")
        return
    path = cache_path_for_minute_history(code, period, start_text, end_text, adjust=adjust)
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        df.to_csv(temp_path, index=False)
        os.replace(temp_path, path)
        if logger:
            logger.info(f"写入分时缓存: {path.name}, shape={df.shape}")
    except Exception as exc:
        if logger:
            logger.warning(f"写入分时缓存失败: {path.name}, error={exc}")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def fetch_stock_minute_history(
    code,
    *,
    period="60",
    days=90,
    adjust="qfq",
    use_cache=False,
    cache_only=False,
    use_disable_proxies=False,
    logger=None,
    verbose=False,
    provider=None,
):
    """Fetch recent minute-level A-share history."""
    code = normalize_code(code)
    if not code:
        return None

    start, end = minute_date_range_for_fetch(days=days)
    start_text = start.strftime("%Y-%m-%d %H:%M:%S")
    end_text = end.strftime("%Y-%m-%d %H:%M:%S")
    cache_start_text = start.strftime("%Y%m%d")
    cache_end_text = end.strftime("%Y%m%d")

    if use_cache:
        cached = read_cached_minute_history(code, period, cache_start_text, cache_end_text, adjust=adjust, logger=logger)
        if cached is not None and not cached.empty:
            return cached
    if cache_only:
        if logger:
            logger.info(f"分时缓存未命中，跳过实时拉取: {code}_{period}")
        return None

    if use_disable_proxies:
        disable_proxies()

    provider = provider or DEFAULT_STOCK_MINUTE_HISTORY_PROVIDER
    df = provider.fetch_history(
        code,
        start_text,
        end_text,
        period=period,
        adjust=adjust,
        logger=logger,
        verbose=verbose,
    )

    if use_cache and df is not None and not df.empty:
        write_cached_minute_history(code, period, cache_start_text, cache_end_text, df, adjust=adjust, logger=logger)

    return df
