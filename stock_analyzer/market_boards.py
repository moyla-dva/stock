"""Market-level industry and concept board data."""

import hashlib
import json
import math
import os
import threading
import time
from datetime import datetime, time as day_time
from pathlib import Path

import pandas as pd

from stock_analyzer.data_fetcher import beijing_now, parse_start_date
from stock_analyzer.providers.board_market import DEFAULT_BOARD_MARKET_PROVIDER
from stock_analyzer.versioning import DATA_START_DATE

BOARD_MARKET_CACHE_DIR = Path(os.environ.get(
    "STOCK_ANALYZER_BOARD_MARKET_CACHE_DIR",
    Path(__file__).resolve().parents[1] / ".cache" / "board_market",
))
BOARD_MARKET_CACHE_MAX_AGE_DAYS = 14
_BOARD_MARKET_CACHE_LOCK = threading.Lock()


def _clean_number(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _cache_identity(board_type, name=None, index_code=None):
    if name:
        return f"{board_type}:name:{name}"
    return f"{board_type}:code:{index_code or ''}"


def board_market_cache_path(board_type, name=None, index_code=None):
    digest = hashlib.sha1(_cache_identity(board_type, name, index_code).encode("utf-8")).hexdigest()[:20]
    return BOARD_MARKET_CACHE_DIR / f"{board_type}_{digest}.json"


def _coerce_now_datetime(value=None):
    value = beijing_now() if value is None else value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S", "%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return beijing_now()


def _parse_payload_date(value):
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _latest_payload_date(payload):
    latest = _parse_payload_date(payload.get("latest_date"))
    if latest is not None:
        return latest

    history = payload.get("history")
    if isinstance(history, list):
        dates = [
            _parse_payload_date(row.get("date"))
            for row in history
            if isinstance(row, dict)
        ]
        dates = [value for value in dates if value is not None]
        if dates:
            return max(dates)
    return None


def _current_day_payload_is_stale(payload, now=None):
    if not isinstance(payload, dict):
        return False

    current_now = _coerce_now_datetime(now)
    today_text = current_now.strftime("%Y-%m-%d")
    if current_now.weekday() >= 5 or current_now.time() < day_time(15, 10):
        return False

    latest = _latest_payload_date(payload)
    return latest is not None and latest.strftime("%Y-%m-%d") < today_text


def read_cached_board_market(
    board_type,
    name=None,
    index_code=None,
    max_age_days=BOARD_MARKET_CACHE_MAX_AGE_DAYS,
    allow_stale_current_day=False,
):
    path = board_market_cache_path(board_type, name=name, index_code=index_code)
    try:
        if max_age_days is not None:
            age_days = (time.time() - path.stat().st_mtime) / 86400
            if age_days > max_age_days:
                return None
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return None
        if not allow_stale_current_day and _current_day_payload_is_stale(payload):
            return None
        return payload
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[板块行情] 读取缓存失败: {e}")
        return None


def write_cached_board_market(payload):
    if not isinstance(payload, dict):
        return None
    board_type = payload.get("type")
    name = payload.get("name")
    index_code = payload.get("index_code")
    if board_type not in {"industry", "concept"} or not (name or index_code):
        return None

    BOARD_MARKET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = board_market_cache_path(board_type, name=name, index_code=index_code)
    with _BOARD_MARKET_CACHE_LOCK:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    return path


def _normalize_board_history(frame):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])

    frame = frame.copy()
    frame = frame.rename(columns={
        "日期": "date",
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
        "成交额": "amount",
        "trade_date": "date",
    })

    for column in ("date", "open", "high", "low", "close"):
        if column not in frame.columns:
            raise ValueError(f"板块行情缺少必要字段: {column}")
    for optional in ("volume", "amount"):
        if optional not in frame.columns:
            frame[optional] = None

    frame = frame[["date", "open", "high", "low", "close", "volume", "amount"]]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(subset=["date", "close"], inplace=True)
    frame.sort_values("date", inplace=True)
    frame.drop_duplicates(subset=["date"], keep="last", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def _pct_change(close, days):
    if close is None or len(close) <= days:
        return None
    latest = _clean_number(close.iloc[-1])
    base = _clean_number(close.iloc[-days - 1])
    if latest is None or base in (None, 0):
        return None
    return round((latest / base - 1) * 100, 2)


def _board_strength_score(frame):
    if frame.empty:
        return 0.0
    close = frame["close"]
    latest = _clean_number(close.iloc[-1], 0.0)
    ret5 = _pct_change(close, 5) or 0.0
    ret20 = _pct_change(close, 20) or 0.0
    ma20 = _clean_number(close.tail(20).mean()) if len(close) >= 20 else None
    ma20_prev = _clean_number(close.iloc[-25:-5].mean()) if len(close) >= 25 else None
    above_ma20 = bool(ma20 and latest > ma20)
    ma20_slope = ((ma20 / ma20_prev - 1) * 100) if ma20 and ma20_prev else 0.0
    raw = 50 + ret5 * 2.2 + ret20 * 0.9 + ma20_slope * 1.4 + (8 if above_ma20 else -8)
    return round(max(0.0, min(100.0, raw)), 1)


def _trend_label(score):
    if score >= 75:
        return "强势"
    if score >= 55:
        return "偏强"
    if score >= 40:
        return "震荡"
    return "偏弱"


def _serialize_history(frame, limit=120):
    rows = []
    for _, row in frame.tail(limit).iterrows():
        rows.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "open": _clean_number(row["open"]),
            "high": _clean_number(row["high"]),
            "low": _clean_number(row["low"]),
            "close": _clean_number(row["close"]),
            "volume": _clean_number(row["volume"]),
            "amount": _clean_number(row["amount"]),
        })
    return rows


def build_board_market_payload(board_type, name, index_code, frame, source):
    frame = _normalize_board_history(frame)
    close = frame["close"] if not frame.empty else pd.Series(dtype=float)
    latest_close = _clean_number(close.iloc[-1]) if not frame.empty else None
    latest_date = frame.iloc[-1]["date"].strftime("%Y-%m-%d") if not frame.empty else "-"
    ma20 = _clean_number(close.tail(20).mean()) if len(close) >= 20 else None
    strength_score = _board_strength_score(frame)
    return {
        "type": board_type,
        "name": name,
        "index_code": index_code or name,
        "source": source,
        "latest_date": latest_date,
        "latest_close": latest_close,
        "change_pct": _pct_change(close, 1),
        "ret_5": _pct_change(close, 5),
        "ret_20": _pct_change(close, 20),
        "ma20": round(ma20, 3) if ma20 is not None else None,
        "above_ma20": bool(ma20 and latest_close and latest_close > ma20),
        "strength_score": strength_score,
        "trend_label": _trend_label(strength_score),
        "history": _serialize_history(frame),
    }


def get_industry_board_market(name, start_date=DATA_START_DATE, end_date=None, provider=None):
    provider = provider or DEFAULT_BOARD_MARKET_PROVIDER
    data = provider.fetch_industry_history(name, start_date=start_date, end_date=end_date)
    return build_board_market_payload(
        "industry",
        data["name"],
        data["index_code"],
        data["frame"],
        data["source"],
    )


def get_concept_board_market(name=None, index_code=None, start_date=DATA_START_DATE, provider=None):
    provider = provider or DEFAULT_BOARD_MARKET_PROVIDER
    data = provider.fetch_concept_history(name=name, index_code=index_code)
    frame = _normalize_board_history(data["frame"])
    start = pd.to_datetime(parse_start_date(start_date))
    frame = frame[frame["date"] >= start]
    return build_board_market_payload(
        "concept",
        data["name"],
        data["index_code"],
        frame,
        data["source"],
    )


def get_board_market(board_type, name=None, index_code=None, start_date=DATA_START_DATE, provider=None):
    try:
        if board_type == "concept":
            payload = get_concept_board_market(
                name=name,
                index_code=index_code,
                start_date=start_date,
                provider=provider,
            )
        else:
            payload = get_industry_board_market(name=name, start_date=start_date, provider=provider)
        write_cached_board_market(payload)
        return payload
    except Exception:
        cached = read_cached_board_market(
            board_type,
            name=name,
            index_code=index_code,
            max_age_days=None,
            allow_stale_current_day=True,
        )
        if cached:
            cached = dict(cached)
            cached["cache_fallback"] = True
            cached["cache_stale"] = _current_day_payload_is_stale(cached)
            return cached
        raise


def unavailable_board_market_payload(board_type, name=None, index_code=None, error=None, source="unavailable"):
    return {
        "type": board_type,
        "name": name or index_code or "-",
        "index_code": index_code or name or "",
        "source": source,
        "available": False,
        "status": "unavailable",
        "error": str(error or "板块行情暂不可用"),
        "latest_date": "-",
        "latest_close": None,
        "change_pct": None,
        "ret_5": None,
        "ret_20": None,
        "ma20": None,
        "above_ma20": False,
        "strength_score": None,
        "trend_label": "暂不可用",
        "history": [],
    }
