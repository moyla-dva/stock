"""Persistent cache for deferred intraday chart payloads."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from stock_analyzer.versioning import DATA_ADJUST, SCAN_STRATEGY_VERSION


TIMEFRAME_CHART_CACHE_SCHEMA_VERSION = 1
TIMEFRAME_CHART_CACHE_DIR = (
    Path(__file__).resolve().parents[1] / ".cache" / "timeframe_charts"
)


def _now_text():
    return datetime.now().isoformat(timespec="seconds")


def _safe_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return round(number, 6)


def _date_text(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _numeric_sum(frame, column):
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    return _safe_float(values.sum())


def chart_frame_fingerprint(frame):
    """Return a compact invalidation fingerprint for an analyzed chart frame."""
    if frame is None or frame.empty:
        return {"rows": 0}

    first = frame.iloc[0]
    latest = frame.iloc[-1]
    columns = [column for column in ("open", "high", "low", "close", "volume") if column in frame.columns]
    first_values = {column: _safe_float(first.get(column)) for column in columns}
    latest_values = {column: _safe_float(latest.get(column)) for column in columns}
    return {
        "rows": int(len(frame)),
        "first_date": _date_text(first.get("date")),
        "latest_date": _date_text(latest.get("date")),
        "columns": columns,
        "first": first_values,
        "latest": latest_values,
        "close_sum": _numeric_sum(frame, "close"),
        "volume_sum": _numeric_sum(frame, "volume"),
    }


def _cache_digest(key):
    return hashlib.sha1(
        json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _cache_path(key):
    return TIMEFRAME_CHART_CACHE_DIR / f"{_cache_digest(key)}.json"


def _read_cached_payload(path, key):
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None

    meta = payload.get("timeframe_chart_cache_meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return None
    if meta.get("schema_version") != TIMEFRAME_CHART_CACHE_SCHEMA_VERSION:
        return None
    if meta.get("key") != key:
        return None

    payload["timeframe_chart_cache_meta"] = dict(meta, hit=True)
    return payload


def _write_cached_payload(path, payload, key):
    cached = dict(payload or {})
    cached["timeframe_chart_cache_meta"] = {
        "schema_version": TIMEFRAME_CHART_CACHE_SCHEMA_VERSION,
        "key": key,
        "stored_at": _now_text(),
        "hit": False,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(cached, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(path)
    except Exception:
        return payload
    return cached


def get_cached_timeframe_chart_payload(
    code,
    period_key,
    frame,
    event_lookback,
    factory,
    *,
    force_refresh=False,
    include_legacy=False,
):
    """Read or build a deferred timeframe chart payload."""
    key = {
        "schema_version": TIMEFRAME_CHART_CACHE_SCHEMA_VERSION,
        "code": str(code or ""),
        "period_key": str(period_key or ""),
        "event_lookback": int(event_lookback or 0),
        "include_legacy": bool(include_legacy),
        "strategy_version": SCAN_STRATEGY_VERSION,
        "data_adjust": DATA_ADJUST,
        "frame": chart_frame_fingerprint(frame),
    }
    cache_path = _cache_path(key)
    if not force_refresh:
        cached = _read_cached_payload(cache_path, key)
        if cached is not None:
            return cached

    payload = factory()
    return _write_cached_payload(cache_path, payload, key)
