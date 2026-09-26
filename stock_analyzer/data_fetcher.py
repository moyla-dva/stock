"""Daily market data access and local history cache."""

import json
import math
import os
import time as time_module
import uuid
from datetime import datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.market_data_identity import (
    attach_market_data_identity,
    frame_market_data_identity,
    market_data_revision,
)
from stock_analyzer.market_metadata_store import MarketMetadataStore
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.providers.stock_history import (
    DEFAULT_STOCK_HISTORY_PROVIDER,
    tencent_volume_to_shares,
)
from stock_analyzer.providers.stock_quote import fetch_realtime_quote_bar, merge_quote_bar

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
    """Return a timezone-aware Beijing clock value."""
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def date_range_for_recent_days(days=120, now=None):
    end = now if now is not None else beijing_now()
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


def date_range_for_fetch(days=120, start_date=None, now=None):
    end = now if now is not None else beijing_now()
    explicit_start = parse_start_date(start_date)
    if explicit_start is not None:
        return explicit_start, end
    return date_range_for_recent_days(days, now=end)


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


def _read_history_meta(path):
    try:
        with _history_meta_path(Path(path)).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


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


def _canonical_history_frame(frame):
    """Validate provider volume and return a complete canonical OHLCV frame."""
    if frame is None or frame.empty:
        raise ValueError("行情数据为空")
    volume_column = "volume" if "volume" in frame.columns else "成交量" if "成交量" in frame.columns else None
    if volume_column is None:
        raise ValueError("行情数据缺少成交量字段")
    raw_volume = pd.to_numeric(frame[volume_column], errors="coerce")
    if raw_volume.isna().any() or not raw_volume.map(math.isfinite).all() or (raw_volume < 0).any():
        raise ValueError("行情数据成交量包含无效值")

    canonical = normalize_price_frame(frame)
    if canonical is None or canonical.empty or len(canonical) != len(frame):
        raise ValueError("行情数据 OHLCV 行不完整")
    for column in ("open", "high", "low", "close", "volume"):
        values = canonical[column]
        if values.isna().any() or not values.map(math.isfinite).all():
            raise ValueError(f"行情数据 {column} 包含无效值")
    if (canonical["volume"] < 0).any():
        raise ValueError("行情数据成交量不能为负数")
    return canonical


def _migrate_legacy_cached_volume(frame, code, meta):
    """Upgrade pre-contract Tencent caches whose volume was stored as amount/hands."""
    migrated = frame.copy()
    if meta.get("volume_unit") == "shares":
        return migrated

    volume_column = "volume" if "volume" in migrated.columns else "成交量" if "成交量" in migrated.columns else None
    amount_column = "amount" if "amount" in migrated.columns else None
    source = str(meta.get("data_source") or "")

    if volume_column is None:
        if amount_column is not None:
            migrated["volume"] = migrated[amount_column].map(
                lambda value: tencent_volume_to_shares(code, value)
            )
        return migrated

    volume = pd.to_numeric(migrated[volume_column], errors="coerce")
    has_missing_volume = volume.isna().any()
    if amount_column and has_missing_volume:
        legacy_volume = pd.to_numeric(migrated[amount_column], errors="coerce")
        migrated[volume_column] = volume.where(volume.notna(), legacy_volume).map(
            lambda value: tencent_volume_to_shares(code, value) if pd.notna(value) else value
        )
    elif "tencent_direct" in source:
        migrated[volume_column] = migrated[volume_column].map(
            lambda value: tencent_volume_to_shares(code, value) if pd.notna(value) else value
        )
    elif "tencent_realtime" in source:
        date_column = next((name for name in ("date", "日期", "day") if name in migrated.columns), None)
        if date_column:
            dates = pd.to_datetime(migrated[date_column], errors="coerce")
            latest = dates.max()
            if pd.notna(latest):
                latest_rows = dates.eq(latest)
                migrated.loc[latest_rows, volume_column] = migrated.loc[latest_rows, volume_column].map(
                    lambda value: tencent_volume_to_shares(code, value) if pd.notna(value) else value
                )
    return migrated


def read_history_cache_file(path, code):
    """Read and canonicalize one cache file, including known legacy Tencent formats."""
    path = Path(path)
    frame = pd.read_csv(path)
    meta = _read_history_meta(path)
    frame = _migrate_legacy_cached_volume(frame, code, meta)
    frame = _canonical_history_frame(frame)
    expected_revision = str(meta.get("cache_payload_revision") or "")
    if expected_revision and expected_revision != market_data_revision(frame):
        raise ValueError("行情缓存与元数据 revision 不一致")
    return frame, meta


@lru_cache(maxsize=1024)
def _cached_market_calendar_context(date_text, ttl_bucket):
    del ttl_bucket
    try:
        store = MarketMetadataStore()
        context = store.session_context(date_text, calendar_id="XSHG")
        if not context.get("calendar_revision"):
            return {
                "is_session": None,
                "calendar_id": "XSHG",
                "calendar_revision": "",
                "calendar_evidence_level": "",
            }
        return {
            "is_session": context.get("is_session"),
            "calendar_id": context.get("calendar_id") or "XSHG",
            "calendar_revision": context.get("calendar_revision") or "",
            "calendar_evidence_level": (
                context.get("calendar_evidence_level") or ""
            ),
        }
    except Exception:
        return {
            "is_session": None,
            "calendar_id": "XSHG",
            "calendar_revision": "",
            "calendar_evidence_level": "",
        }


def market_calendar_context(date_text):
    """Return versioned session metadata, or an unknown session status on failure."""
    return _cached_market_calendar_context(
        str(date_text or ""),
        int(time_module.time() // 300),
    )


def _daily_bar_state(frame, now=None):
    latest_text = _latest_history_date_text(frame)
    if not latest_text:
        return "unknown"
    now = now if now is not None else beijing_now()
    if hasattr(now, "to_pydatetime"):
        now = now.to_pydatetime()
    current_text = now.strftime("%Y%m%d")
    if latest_text < current_text:
        return "closed"
    if latest_text > current_text:
        return "unknown"
    session_status = market_calendar_context(latest_text).get("is_session")
    if session_status is False:
        return "unknown"
    if session_status is None and now.weekday() >= 5:
        return "closed"
    if now.time() >= time(15, 10):
        return "closed"
    return "preview"


def _current_day_cache_is_stale(frame, end_text, cache_path=None, now=None):
    try:
        requested_end = datetime.strptime(str(end_text), "%Y%m%d")
    except ValueError:
        return False

    now = now if now is not None else beijing_now()
    if hasattr(now, "to_pydatetime"):
        now = now.to_pydatetime()
    if now.strftime("%Y%m%d") != str(end_text):
        return False
    session_status = market_calendar_context(str(end_text)).get("is_session")
    if session_status is False:
        return False
    if session_status is None and requested_end.weekday() >= 5:
        return False
    if now.time() < time(15, 10):
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


def _should_write_history_cache(frame, end_text, now=None):
    """Avoid persisting an unfinished current-day daily bar before the close buffer."""
    try:
        _canonical_history_frame(frame)
    except (TypeError, ValueError):
        return False
    now = now if now is not None else beijing_now()
    if hasattr(now, "to_pydatetime"):
        now = now.to_pydatetime()
    if now.strftime("%Y%m%d") != str(end_text):
        return True
    latest_text = _latest_history_date_text(frame)
    session_status = market_calendar_context(str(end_text)).get("is_session")
    if session_status is False:
        return latest_text != str(end_text)
    if session_status is None and now.weekday() >= 5:
        return True
    if now.time() >= time(15, 10):
        return True
    return latest_text != str(end_text)


def read_cached_history(code, start_text, end_text, adjust="", logger=None, now=None, diagnostics=None):
    candidates = _cached_history_candidates(code, start_text, end_text, adjust=adjust)
    if not candidates:
        if isinstance(diagnostics, dict):
            diagnostics.update({"cache_status": "miss"})
        return None
    canonical_path = cache_path_for_history(code, start_text, end_text, adjust=adjust)
    saw_stale = False
    saw_read_error = False
    for path in candidates:
        try:
            cached, meta = read_history_cache_file(path, code)
            generated_at = (
                now.isoformat()
                if now is not None and hasattr(now, "isoformat")
                else meta.get("generated_at") or meta.get("stored_at") or "unknown"
            )
            calendar_context = market_calendar_context(
                _latest_history_date_text(cached) or str(end_text)
            )
            attach_market_data_identity(
                cached,
                data_source=meta.get("data_source") or "unknown",
                bar_state=meta.get("bar_state") or _daily_bar_state(cached, now=now),
                generated_at=generated_at,
                cache_status="hit",
                cache_written_at=meta.get("stored_at") or "unknown",
                data_revision=meta.get("data_revision") or market_data_revision(cached),
                calendar_id=meta.get("calendar_id") or calendar_context.get("calendar_id"),
                calendar_revision=(
                    meta.get("calendar_revision")
                    or calendar_context.get("calendar_revision")
                ),
                calendar_evidence_level=(
                    meta.get("calendar_evidence_level")
                    or calendar_context.get("calendar_evidence_level")
                ),
            )
            if _current_day_cache_is_stale(cached, end_text, cache_path=path, now=now):
                saw_stale = True
                if logger:
                    latest = _latest_history_date_text(cached) or "-"
                    logger.info(f"日线缓存今日数据需刷新，重新拉取: {path.name}, latest={latest}, end={end_text}")
                continue
            if path != canonical_path:
                write_cached_history(
                    code,
                    start_text,
                    end_text,
                    cached,
                    adjust=adjust,
                    logger=logger,
                    stored_at=now,
                )
            if logger:
                logger.info(f"命中日线缓存: {path.name}, shape={cached.shape}")
            if isinstance(diagnostics, dict):
                diagnostics.update({"cache_status": "hit"})
            return cached
        except Exception as e:
            saw_read_error = True
            if logger:
                logger.warning(f"读取日线缓存失败: {path.name}, error={e}")
            continue
    if isinstance(diagnostics, dict):
        diagnostics.update({
            "cache_status": "stale" if saw_stale else "read_error" if saw_read_error else "miss",
        })
    return None


def write_cached_history(
    code,
    start_text,
    end_text,
    df,
    adjust="",
    logger=None,
    stored_at=None,
):
    if df is None or df.empty:
        return False
    try:
        df = _canonical_history_frame(df)
    except (TypeError, ValueError) as exc:
        if logger:
            logger.warning(f"拒绝写入不完整日线缓存: {code}, error={exc}")
        return False
    path = cache_path_for_history(code, start_text, end_text, adjust=adjust)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f".{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
        df.to_csv(tmp_path, index=False)
        tmp_path.replace(path)
        stored_at = stored_at if stored_at is not None else beijing_now()
        identity = frame_market_data_identity(df)
        calendar_context = market_calendar_context(
            _latest_history_date_text(df) or str(end_text)
        )
        meta = {
            "history_schema_version": 2,
            "volume_unit": "shares",
            "stored_at": stored_at.isoformat(),
            "latest_date": _latest_history_date_text(df),
            "data_source": identity.get("data_source") or "unknown",
            "bar_state": identity.get("bar_state") or _daily_bar_state(df, now=stored_at),
            "data_revision": identity.get("data_revision") or market_data_revision(df),
            "cache_payload_revision": market_data_revision(df),
            "generated_at": identity.get("generated_at") or stored_at.isoformat(),
            "calendar_id": identity.get("calendar_id") or calendar_context.get("calendar_id") or "",
            "calendar_revision": (
                identity.get("calendar_revision")
                or calendar_context.get("calendar_revision")
                or ""
            ),
            "calendar_evidence_level": (
                identity.get("calendar_evidence_level")
                or calendar_context.get("calendar_evidence_level")
                or ""
            ),
        }
        meta_path = _history_meta_path(path)
        tmp_meta_path = meta_path.with_suffix(f".{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
        with tmp_meta_path.open("w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_meta_path.replace(meta_path)
        if logger:
            logger.info(f"写入日线缓存: {path.name}, shape={df.shape}")
        return True
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
        return False


def fetch_stock_history(
    code,
    days=120,
    start_date=None,
    adjust="",
    use_cache=False,
    force_refresh=False,
    use_disable_proxies=False,
    logger=None,
    verbose=False,
    provider=None,
    diagnostics=None,
):
    """Fetch daily A-share history with the existing two-provider fallback."""
    code = normalize_code(code)
    if not code:
        if isinstance(diagnostics, dict):
            diagnostics.clear()
            diagnostics.update({"fetch_status": "invalid_code", "cache_status": "bypass", "attempts": []})
        return None

    fetch_info = {"fetch_status": "unknown", "cache_status": "bypass", "attempts": []}

    request_now = beijing_now()
    start, end = date_range_for_fetch(days=days, start_date=start_date, now=request_now)
    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")

    if use_cache and not force_refresh:
        cache_info = {}
        cached = read_cached_history(
            code,
            start_text,
            end_text,
            adjust=adjust,
            logger=logger,
            now=request_now,
            diagnostics=cache_info,
        )
        if cached is not None and not cached.empty:
            fetch_info.update({"fetch_status": "cache_hit", **cache_info})
            if isinstance(diagnostics, dict):
                diagnostics.clear()
                diagnostics.update(fetch_info)
            return cached
        fetch_info.update(cache_info)
    elif use_cache:
        fetch_info["cache_status"] = "bypass_force_refresh"

    if use_disable_proxies:
        disable_proxies()

    provider = provider or DEFAULT_STOCK_HISTORY_PROVIDER
    detailed_fetch = getattr(type(provider), "fetch_history_with_diagnostics", None)
    try:
        if callable(detailed_fetch):
            df, attempts = provider.fetch_history_with_diagnostics(
                code,
                start_text,
                end_text,
                adjust=adjust,
                logger=logger,
                verbose=verbose,
            )
            fetch_info["attempts"] = list(attempts or [])
        else:
            df = provider.fetch_history(
                code,
                start_text,
                end_text,
                adjust=adjust,
                logger=logger,
                verbose=verbose,
            )
            fetch_info["attempts"] = [{
                "provider": type(provider).__name__,
                "status": "data" if df is not None and not df.empty else "empty",
            }]
    except Exception as exc:
        if diagnostics is None:
            raise
        df = None
        fetch_info["attempts"] = [{
            "provider": type(provider).__name__,
            "status": "error",
            "error_type": type(exc).__name__,
        }]
    provider_identity = frame_market_data_identity(df)

    if force_refresh:
        if use_cache and (df is None or df.empty):
            cache_info = {}
            cached = read_cached_history(
                code,
                start_text,
                end_text,
                adjust=adjust,
                logger=logger,
                now=request_now,
                diagnostics=cache_info,
            )
            if cached is not None and not cached.empty:
                df = cached
                provider_identity = frame_market_data_identity(df)
                fetch_info["cache_status"] = "stale_fallback" if cache_info.get("cache_status") == "stale" else "fallback_hit"
            elif cache_info.get("cache_status") == "stale":
                fetch_info["cache_status"] = "stale"
        quote_bar = fetch_realtime_quote_bar(code, target_date_text=end_text, logger=logger)
        if quote_bar:
            try:
                df = _canonical_history_frame(df) if df is not None and not df.empty else None
            except (TypeError, ValueError) as exc:
                if logger:
                    logger.warning(
                        f"历史行情不满足 OHLCV 契约，实时行情仅用于本次展示: {code}, error={exc}"
                    )
                df = None
            df = merge_quote_bar(df, quote_bar)
            prior_source = provider_identity.get("data_source") or "unknown"
            attach_market_data_identity(
                df,
                data_source=(
                    "tencent_realtime"
                    if prior_source == "unknown"
                    else f"{prior_source}+tencent_realtime"
                ),
                cache_status="realtime_merge",
            )

    if df is not None and not df.empty:
        identity = frame_market_data_identity(df)
        calendar_context = market_calendar_context(
            _latest_history_date_text(df) or end_text
        )
        attach_market_data_identity(
            df,
            data_source=identity.get("data_source") or "unknown",
            bar_state=_daily_bar_state(df, now=request_now),
            generated_at=request_now.isoformat(),
            cache_status=identity.get("cache_status") or ("bypass" if not use_cache else "miss"),
            data_revision=market_data_revision(df),
            calendar_id=calendar_context.get("calendar_id"),
            calendar_revision=calendar_context.get("calendar_revision"),
            calendar_evidence_level=calendar_context.get("calendar_evidence_level"),
        )

    if use_cache and df is not None and not df.empty:
        if _should_write_history_cache(df, end_text, now=request_now):
            write_cached_history(
                code,
                start_text,
                end_text,
                df,
                adjust=adjust,
                logger=logger,
                stored_at=request_now,
            )
        elif logger:
            latest = _latest_history_date_text(df) or "-"
            logger.info(f"盘中日线数据仅用于本次展示，暂不写入缓存: {code}, latest={latest}, end={end_text}")

    if df is not None and not df.empty:
        fetch_info["fetch_status"] = "available"
    else:
        attempt_states = {str(item.get("status") or "") for item in fetch_info.get("attempts", [])}
        if "error" in attempt_states and "empty" in attempt_states:
            fetch_info["fetch_status"] = "provider_partial_failure"
        elif "error" in attempt_states:
            fetch_info["fetch_status"] = "provider_error"
        elif "empty" in attempt_states:
            fetch_info["fetch_status"] = "provider_empty"
        else:
            fetch_info["fetch_status"] = "no_provider_result"
    if isinstance(diagnostics, dict):
        diagnostics.clear()
        diagnostics.update(fetch_info)

    return df
