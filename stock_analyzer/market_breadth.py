"""Real market breadth metrics from cached constituent stock histories."""

from pathlib import Path

import pandas as pd

from stock_analyzer import data_fetcher
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.scan_common import result_concepts, result_sector
from stock_analyzer.versioning import DATA_ADJUST


def _history_file_key(path):
    parts = path.stem.split("_")
    end_text = parts[2] if len(parts) >= 3 and parts[2].isdigit() else ""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    return end_text, mtime


def build_history_cache_index(cache_dir=None):
    cache_dir = Path(cache_dir or data_fetcher.CACHE_DIR)
    index = {}
    if not cache_dir.exists():
        return index
    for path in cache_dir.glob(f"*_{DATA_ADJUST}.csv"):
        if not path.is_file():
            continue
        code = normalize_code(path.name[:6])
        if not code:
            continue
        current = index.get(code)
        if current is None or _history_file_key(path) > _history_file_key(current):
            index[code] = path
    return index


def latest_cached_history_path(code, cache_dir=None, history_index=None):
    code = normalize_code(code)
    if not code:
        return None
    if history_index is not None:
        return history_index.get(code)
    cache_dir = Path(cache_dir or data_fetcher.CACHE_DIR)
    paths = [path for path in cache_dir.glob(f"{code}_*_{DATA_ADJUST}.csv") if path.is_file()]
    if not paths:
        return None
    return max(paths, key=_history_file_key)


def _read_history_tail(code, cache_dir=None, history_index=None):
    path = latest_cached_history_path(code, cache_dir=cache_dir, history_index=history_index)
    if path is None:
        return None
    try:
        frame = pd.read_csv(path)
        normalized = normalize_price_frame(frame)
    except Exception:
        return None
    if normalized is None or len(normalized) < 2:
        return None
    return normalized.tail(30).copy()


def _code_breadth(code, cache_dir=None, history_index=None, sample_cache=None):
    code = normalize_code(code)
    if sample_cache is not None and code in sample_cache:
        return sample_cache[code]
    frame = _read_history_tail(code, cache_dir=cache_dir, history_index=history_index)
    if frame is None or len(frame) < 2:
        if sample_cache is not None:
            sample_cache[code] = None
        return None
    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    close = float(latest["close"])
    previous_close = float(previous["close"])
    ma20 = float(frame["close"].tail(20).mean())
    sample = {
        "code": normalize_code(code),
        "date": latest["date"].strftime("%Y-%m-%d") if hasattr(latest["date"], "strftime") else str(latest["date"]),
        "up": close > previous_close,
        "down": close < previous_close,
        "above_ma20": close >= ma20,
    }
    if sample_cache is not None:
        sample_cache[code] = sample
    return sample


def _members_for_board(profile_cache, board_type, name):
    members = []
    for code, profile in (profile_cache or {}).items():
        normalized = normalize_code(code)
        if not normalized or not isinstance(profile, dict):
            continue
        if board_type == "sector":
            if result_sector(profile) == name:
                members.append(normalized)
            continue
        if name in result_concepts(profile):
            members.append(normalized)
    return sorted(set(members))


def _breadth_label(up_rate, ma20_rate, sample_count):
    if sample_count <= 0:
        return "无本地样本"
    if up_rate >= 60 and ma20_rate >= 55:
        return "真实扩散"
    if up_rate >= 50 or ma20_rate >= 55:
        return "偏强"
    if up_rate >= 40 or ma20_rate >= 45:
        return "分化"
    return "偏弱"


def build_board_breadth(
    name,
    board_type,
    profile_cache,
    cache_dir=None,
    sample_limit=240,
    history_index=None,
    sample_cache=None,
):
    members = _members_for_board(profile_cache, board_type, name)
    samples = []
    for code in members[:sample_limit]:
        sample = _code_breadth(
            code,
            cache_dir=cache_dir,
            history_index=history_index,
            sample_cache=sample_cache,
        )
        if sample:
            samples.append(sample)
    sample_count = len(samples)
    up_count = sum(1 for item in samples if item["up"])
    down_count = sum(1 for item in samples if item["down"])
    above_ma20_count = sum(1 for item in samples if item["above_ma20"])
    latest_date = max((item["date"] for item in samples), default="")
    up_rate = round(up_count * 100 / sample_count, 1) if sample_count else None
    ma20_rate = round(above_ma20_count * 100 / sample_count, 1) if sample_count else None
    score = None
    if sample_count:
        score = round((up_rate or 0) * 0.5 + (ma20_rate or 0) * 0.5, 1)
    return {
        "breadth_source": "history_cache",
        "breadth_member_count": len(members),
        "breadth_sample_count": sample_count,
        "breadth_up_count": up_count,
        "breadth_down_count": down_count,
        "breadth_above_ma20_count": above_ma20_count,
        "breadth_up_rate": up_rate,
        "breadth_ma20_rate": ma20_rate,
        "breadth_score": score,
        "breadth_label": _breadth_label(up_rate or 0, ma20_rate or 0, sample_count),
        "breadth_latest_date": latest_date,
    }


def _overview_priority(stat, key_name):
    score_key = f"{key_name}_score"
    return (
        float(stat.get(score_key) or 0),
        int(stat.get("signal_count") or 0),
        float(stat.get("avg_rank") or 0),
    )


def _apply_to_overview(
    overview,
    key_name,
    board_type,
    profile_cache,
    max_boards,
    cache_dir=None,
    history_index=None,
    sample_cache=None,
):
    selected = sorted(overview, key=lambda item: _overview_priority(item, key_name), reverse=True)[:max_boards]
    selected_names = {item.get(key_name) for item in selected}
    for stat in overview:
        if stat.get(key_name) not in selected_names:
            continue
        breadth = build_board_breadth(
            stat.get(key_name),
            board_type,
            profile_cache,
            cache_dir=cache_dir,
            history_index=history_index,
            sample_cache=sample_cache,
        )
        stat["candidate_width_label"] = stat.get("width_label")
        stat["candidate_width_score"] = stat.get("width_score")
        stat.update(breadth)
        if breadth.get("breadth_sample_count"):
            stat["width_label"] = breadth["breadth_label"]
            stat["width_score"] = breadth["breadth_score"]
            stat["market_universe_source"] = "profile_cache+history_cache"


def apply_market_breadth_to_overview(sector_overview, concept_overview, profile_cache, max_boards=16, cache_dir=None):
    """Attach real breadth metrics to the most relevant sector/concept overview rows."""
    history_index = build_history_cache_index(cache_dir=cache_dir)
    sample_cache = {}
    _apply_to_overview(
        sector_overview or [],
        "sector",
        "sector",
        profile_cache,
        max_boards,
        cache_dir=cache_dir,
        history_index=history_index,
        sample_cache=sample_cache,
    )
    _apply_to_overview(
        concept_overview or [],
        "concept",
        "concept",
        profile_cache,
        max_boards,
        cache_dir=cache_dir,
        history_index=history_index,
        sample_cache=sample_cache,
    )
