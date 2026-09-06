"""Replay calibration for sector resonance scores using local history caches."""

from pathlib import Path

import pandas as pd

from stock_analyzer import data_fetcher
from stock_analyzer.backtest import ENTRY_MODEL_EVENT_CLOSE, ENTRY_MODEL_NEXT_OPEN, ENTRY_MODELS
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.scan_buckets import RESONANCE_CALIBRATION_BUCKETS
from stock_analyzer.versioning import DATA_ADJUST


UNKNOWN_SECTOR = "未识别板块"
REPLAY_BUCKETS = RESONANCE_CALIBRATION_BUCKETS
DEFAULT_REPLAY_HORIZONS = (3, 5, 10)


def _as_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _avg_or_none(total, count, digits=2):
    if not count:
        return None
    return round(total / count, digits)


def _bucket_key(score):
    score = _as_float(score, 0.0)
    for bucket in REPLAY_BUCKETS:
        if bucket["min"] <= score < bucket["max"]:
            return bucket["key"]
    return REPLAY_BUCKETS[-1]["key"]


def _history_files(code, cache_dir=None, start_date=None):
    code = normalize_code(code)
    if not code:
        return []
    cache_dir = Path(cache_dir or data_fetcher.CACHE_DIR)
    start_key = str(start_date or "").replace("-", "")
    if start_key:
        pattern = f"{code}_{start_key}_*_{DATA_ADJUST}.csv"
    else:
        pattern = f"{code}_*_{DATA_ADJUST}.csv"
    return sorted(cache_dir.glob(pattern), reverse=True)


def _read_history(code, cache_dir=None, start_date=None):
    for path in _history_files(code, cache_dir=cache_dir, start_date=start_date):
        try:
            frame = pd.read_csv(path)
            normalized = normalize_price_frame(frame)
            if normalized is not None and not normalized.empty:
                return normalized
        except Exception:
            continue
    return None


def _event_index(frame, event_date):
    if frame is None or frame.empty or not event_date:
        return None
    event_text = str(event_date)[:10]
    dates = frame["date"].dt.strftime("%Y-%m-%d")
    matches = frame.index[dates == event_text].tolist()
    if not matches:
        return None
    return matches[0]


def _validated_entry_model(entry_model):
    if entry_model not in ENTRY_MODELS:
        choices = ", ".join(sorted(ENTRY_MODELS))
        raise ValueError(f"entry_model must be one of: {choices}")
    return entry_model


def _forward_return(frame, event_date, horizon, entry_model=ENTRY_MODEL_EVENT_CLOSE):
    entry_model = _validated_entry_model(entry_model)
    idx = _event_index(frame, event_date)
    if idx is None:
        return None
    if entry_model == ENTRY_MODEL_NEXT_OPEN:
        if "open" not in frame.columns:
            return None
        entry_idx = idx + 1
        target_idx = entry_idx + int(horizon)
        if target_idx >= len(frame):
            return None
        base_price = _as_float(frame.iloc[entry_idx].get("open"), None)
        window = frame.iloc[entry_idx:target_idx + 1]
    else:
        target_idx = idx + int(horizon)
        if target_idx >= len(frame):
            return None
        base_price = _as_float(frame.iloc[idx].get("close"), None)
        window = frame.iloc[idx + 1:target_idx + 1]
    if target_idx >= len(frame):
        return None

    target_close = _as_float(frame.iloc[target_idx].get("close"), None)
    if not base_price or target_close is None:
        return None

    if window.empty:
        return None
    close_ret = (target_close / base_price - 1) * 100
    worst_close = float(window["close"].min())
    worst_ret = (worst_close / base_price - 1) * 100
    return {
        "ret": round(close_ret, 2),
        "worst_ret": round(worst_ret, 2),
        "target_date": frame.iloc[target_idx]["date"].strftime("%Y-%m-%d"),
    }


def _empty_bucket(bucket):
    return {
        "key": bucket["key"],
        "label": bucket["label"],
        "candidate_count": 0,
        "sector_count": 0,
        "sectors": set(),
        "horizons": {},
    }


def _empty_horizon():
    return {
        "sample_count": 0,
        "win_count": 0,
        "ret_total": 0.0,
        "worst_ret": None,
        "worst_path_total": 0.0,
    }


def _finalize_horizon(stat):
    count = stat["sample_count"]
    return {
        "sample_count": count,
        "win_rate": _avg_or_none(stat["win_count"] * 100, count, 1),
        "avg_ret": _avg_or_none(stat["ret_total"], count, 2),
        "worst_ret": None if stat["worst_ret"] is None else round(stat["worst_ret"], 2),
        "avg_worst_ret": _avg_or_none(stat["worst_path_total"], count, 2),
    }


def _candidate_results(pools):
    for scan_type in ("opportunity", "bottom_div"):
        for result in pools.get(scan_type, {}).get("results", []):
            if str(result.get("sector") or "").strip() == UNKNOWN_SECTOR:
                continue
            if result.get("sector_score") is None:
                continue
            yield result


def build_replay_calibration(
    pools,
    start_date=None,
    horizons=DEFAULT_REPLAY_HORIZONS,
    cache_dir=None,
    max_candidates=800,
    entry_model=ENTRY_MODEL_EVENT_CLOSE,
):
    """Build forward-return calibration buckets from local history cache only."""
    entry_model = _validated_entry_model(entry_model)
    buckets = {bucket["key"]: _empty_bucket(bucket) for bucket in REPLAY_BUCKETS}
    histories = {}
    candidates_seen = 0
    complete_candidates = 0

    for result in _candidate_results(pools):
        if candidates_seen >= max_candidates:
            break
        candidates_seen += 1

        code = normalize_code(result.get("code"))
        if not code:
            continue
        if code not in histories:
            histories[code] = _read_history(code, cache_dir=cache_dir, start_date=start_date)
        history = histories[code]
        if history is None or history.empty:
            continue

        bucket = buckets[_bucket_key(result.get("sector_score"))]
        bucket_touched = False
        for horizon in horizons:
            replay = _forward_return(
                history,
                result.get("event_date") or result.get("date"),
                horizon,
                entry_model=entry_model,
            )
            if replay is None:
                continue
            horizon_key = str(horizon)
            stat = bucket["horizons"].setdefault(horizon_key, _empty_horizon())
            stat["sample_count"] += 1
            stat["win_count"] += 1 if replay["ret"] > 0 else 0
            stat["ret_total"] += replay["ret"]
            stat["worst_path_total"] += replay["worst_ret"]
            stat["worst_ret"] = replay["worst_ret"] if stat["worst_ret"] is None else min(stat["worst_ret"], replay["worst_ret"])
            bucket_touched = True

        if bucket_touched:
            complete_candidates += 1
            bucket["candidate_count"] += 1
            bucket["sectors"].add(result.get("sector") or UNKNOWN_SECTOR)

    output_buckets = []
    for bucket_def in REPLAY_BUCKETS:
        bucket = buckets[bucket_def["key"]]
        output_buckets.append({
            "key": bucket["key"],
            "label": bucket["label"],
            "candidate_count": bucket["candidate_count"],
            "sector_count": len(bucket["sectors"]),
            "horizons": {
                str(horizon): _finalize_horizon(bucket["horizons"].get(str(horizon), _empty_horizon()))
                for horizon in horizons
            },
            "sample_quality": "可参考" if bucket["candidate_count"] >= 10 else ("样本少" if bucket["candidate_count"] else "无样本"),
        })

    return {
        "method": "historical_snapshot_replay",
        "note": "使用本地日线缓存追踪事件日后的真实交易日收益",
        "entry_model": entry_model,
        "horizons": list(horizons),
        "candidate_count": complete_candidates,
        "requested_count": candidates_seen,
        "buckets": output_buckets,
    }
