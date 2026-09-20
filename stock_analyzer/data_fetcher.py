"""Daily market data access and local history cache."""

import json
import os
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.providers.stock_history import (
    DEFAULT_STOCK_HISTORY_PROVIDER,
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
    return CACHE_DIR / f"{code}_{start_text}_{adjust_key}.csv"


def legacy_cache_path_for_history(code, start_text, end_text, adjust=""):
    adjust_key = adjust or "none"
    return CACHE_DIR / f"{code}_{start_text}_{end_text}_{adjust_key}.csv"


def _history_cache_path_key(path):
    parts = path.stem.split("_")
    end_text = parts[2] if len(parts) >= 4 and parts[2].isdigit() and len(parts[2]) == 8 else ""
    latest_text = end_text or _read_latest_history_date_text(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    is_canonical = 1 if len(parts) == 3 else 0
    return latest_text or "", is_canonical, mtime


def _read_latest_history_date_text(path):
    meta_path = _history_meta_path(path)
    try:
        with meta_path.open("r", encoding="utf-8") as handle:
            meta = json.load(handle)
        latest = str(meta.get("latest_date") or "").replace("-", "")
        if len(latest) == 8 and latest.isdigit():
            return latest
    except Exception:
        pass
    try:
        frame = pd.read_csv(path, usecols=lambda column: column in {"date", "日期"})
    except Exception:
        return ""
    return _latest_history_date_text(frame) or ""


def _cached_history_candidates(code, start_text, end_text, adjust="", cache_dir=None):
    cache_dir = Path(cache_dir or CACHE_DIR)
    canonical = cache_dir / f"{code}_{start_text}_{adjust or 'none'}.csv"
    legacy_exact = cache_dir / f"{code}_{start_text}_{end_text}_{adjust or 'none'}.csv" if end_text else canonical
    adjust_key = adjust or "none"
    candidates = []
    seen = set()
    for path in (canonical, legacy_exact):
        if path.exists() and path not in seen:
            candidates.append(path)
            seen.add(path)
    for path in cache_dir.glob(f"{code}_{start_text}_*_{adjust_key}.csv"):
        if path.is_file() and path not in seen:
            candidates.append(path)
            seen.add(path)
    if canonical.exists() and canonical not in seen:
        candidates.append(canonical)
    return sorted(candidates, key=_history_cache_path_key, reverse=True)


def _history_meta_path(path):
    return path.with_suffix(path.suffix + ".meta.json")


def _coerce_datetime(value):
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _cache_written_at(path):
    meta_path = _history_meta_path(path)
    try:
        with meta_path.open("r", encoding="utf-8") as handle:
            meta = json.load(handle)
        stored_at = _coerce_datetime(meta.get("stored_at"))
        if stored_at is not None:
            return stored_at
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


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


def _current_day_cache_is_stale(frame, end_text, cache_path=None):
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
    if not latest_text:
        return False
    if latest_text < str(end_text):
        return True
    if latest_text != str(end_text) or cache_path is None:
        return False
    written_at = _cache_written_at(Path(cache_path))
    written_at = _coerce_datetime(written_at)
    if written_at is None:
        return False
    return written_at.strftime("%Y%m%d") == str(end_text) and written_at.time() < time(15, 10)


def read_cached_history(code, start_text, end_text, adjust="", logger=None):
    candidates = _cached_history_candidates(code, start_text, end_text, adjust=adjust)
    if not candidates:
        return None
    canonical_path = cache_path_for_history(code, start_text, end_text, adjust=adjust)
    for path in candidates:
        try:
            cached = pd.read_csv(path)
            if _current_day_cache_is_stale(cached, end_text, cache_path=path):
                if logger:
                    latest = _latest_history_date_text(cached) or "-"
                    logger.info(f"日线缓存今日数据需刷新，重新拉取: {path.name}, latest={latest}, end={end_text}")
                return None
            if path != canonical_path:
                write_cached_history(code, start_text, end_text, cached, adjust=adjust, logger=logger)
            if logger:
                logger.info(f"命中日线缓存: {path.name}, shape={cached.shape}")
            return cached
        except Exception as e:
            if logger:
                logger.warning(f"读取日线缓存失败: {path.name}, error={e}")
            continue
    return None


def write_cached_history(code, start_text, end_text, df, adjust="", logger=None):
    if df is None or df.empty:
        return
    path = cache_path_for_history(code, start_text, end_text, adjust=adjust)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f".{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
        df.to_csv(tmp_path, index=False)
        tmp_path.replace(path)
        meta = {
            "stored_at": beijing_now().isoformat(),
            "latest_date": _latest_history_date_text(df),
        }
        meta_path = _history_meta_path(path)
        tmp_meta_path = meta_path.with_suffix(f".{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
        with tmp_meta_path.open("w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_meta_path.replace(meta_path)
        if logger:
            logger.info(f"写入日线缓存: {path.name}, shape={df.shape}")
    except Exception as e:
        for tmp in ("tmp_path", "tmp_meta_path"):
            tmp_value = locals().get(tmp)
            if tmp_value is not None:
                try:
                    Path(tmp_value).unlink(missing_ok=True)
                except OSError:
                    pass
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
