"""Market-level board context for scan resonance scoring."""

from stock_analyzer.scan_common import UNKNOWN_CONCEPT, UNKNOWN_SECTOR, as_float


BOARD_MARKET_TOP_LIMIT = 16


def board_market_boost(payload):
    if not isinstance(payload, dict):
        return 0.0
    strength = as_float(payload.get("strength_score"), 50.0)
    ret5 = as_float(payload.get("ret_5"), 0.0)
    ret20 = as_float(payload.get("ret_20"), 0.0)
    raw_boost = (strength - 50.0) * 0.10 + ret5 * 0.28 + ret20 * 0.06
    return round(max(-8.0, min(10.0, raw_boost)), 1)


def board_market_context(payload):
    if not isinstance(payload, dict):
        return None
    strength = as_float(payload.get("strength_score"), None)
    if strength is None:
        return None
    return {
        "market_source": payload.get("source") or "",
        "market_index_code": payload.get("index_code") or "",
        "market_strength_score": round(strength, 1),
        "market_trend_label": payload.get("trend_label") or "-",
        "market_ret_5": payload.get("ret_5"),
        "market_ret_20": payload.get("ret_20"),
        "market_latest_date": payload.get("latest_date") or "-",
        "market_cache_stale": bool(payload.get("cache_stale")),
        "market_cache_fallback": bool(payload.get("cache_fallback")),
        "market_boost": board_market_boost(payload),
    }


def resolve_board_market_reader(board_market_reader):
    if board_market_reader is not None:
        return board_market_reader
    try:
        from stock_analyzer.market_boards import _current_day_payload_is_stale, read_cached_board_market

        def reader(board_type, name=None, index_code=None, max_age_days=None):
            payload = read_cached_board_market(
                board_type,
                name=name,
                index_code=index_code,
                max_age_days=max_age_days,
                allow_stale_current_day=True,
            )
            if not isinstance(payload, dict):
                return payload
            payload = dict(payload)
            payload["cache_stale"] = _current_day_payload_is_stale(payload)
            payload["cache_fallback"] = bool(payload.get("cache_stale"))
            return payload

        return reader
    except Exception:
        return None


def _board_market_priority(stat, key_name):
    score_key = f"{key_name}_score"
    return (
        float(stat.get(score_key) or stat.get("candidate_score") or 0.0),
        int(stat.get("candidate_signal_count") or stat.get("signal_count") or 0),
        int(stat.get("count") or stat.get("candidate_count") or 0),
        float(stat.get("avg_rank") or 0.0),
        int(stat.get("market_member_count") or 0),
        str(stat.get("latest_event") or ""),
    )


def _select_board_market_rows(overview, key_name, limit):
    return sorted(
        overview or [],
        key=lambda item: _board_market_priority(item, key_name),
        reverse=True,
    )[:limit]


def apply_board_market_to_overview(overview, key_name, board_type, board_market_reader=None):
    reader = resolve_board_market_reader(board_market_reader)
    if reader is None:
        return

    for stat in _select_board_market_rows(overview, key_name, BOARD_MARKET_TOP_LIMIT):
        value = stat.get(key_name)
        if not value or value in {UNKNOWN_SECTOR, UNKNOWN_CONCEPT}:
            continue
        try:
            payload = reader(board_type, name=value)
        except Exception:
            payload = None
        context = board_market_context(payload)
        if context:
            stat.update(context)


def market_delta_for_pool(scan_type, boost, weight):
    value = as_float(boost, 0.0) * weight
    if scan_type == "risk":
        value *= -1
    return round(value, 1)


def apply_result_market_context(result, stat, scan_type, prefix, weight):
    boost = stat.get("market_boost")
    if boost is None:
        return
    result[f"{prefix}_market_score"] = stat.get("market_strength_score")
    result[f"{prefix}_market_trend"] = stat.get("market_trend_label")
    result[f"{prefix}_market_ret_5"] = stat.get("market_ret_5")
    result[f"{prefix}_market_ret_20"] = stat.get("market_ret_20")
    result[f"{prefix}_market_latest_date"] = stat.get("market_latest_date")
    result[f"{prefix}_market_cache_stale"] = bool(stat.get("market_cache_stale"))
    result[f"{prefix}_market_source"] = stat.get("market_source")

    delta = market_delta_for_pool(scan_type, boost, weight)
    result[f"{prefix}_market_boost"] = delta
    result["market_boost"] = round(as_float(result.get("market_boost"), 0.0) + delta, 1)
    result["final_score"] = round(
        as_float(result.get("final_score"), as_float(result.get("rank_score"), 0.0)) + delta,
        1,
    )
