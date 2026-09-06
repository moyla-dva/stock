"""Controlled refresh for market-level board caches."""

from stock_analyzer.market_boards import get_board_market, read_cached_board_market
from stock_analyzer.versioning import DATA_START_DATE


BOARD_REFRESH_LIMIT_DEFAULT = 8
BOARD_REFRESH_LIMIT_MAX = 32


def _coerce_limit(value, default=BOARD_REFRESH_LIMIT_DEFAULT):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, BOARD_REFRESH_LIMIT_MAX))


def _rows_for_type(workspace, board_type):
    if board_type == "concept":
        return workspace.get("concept_overview") or [], "concept"
    return workspace.get("sector_overview") or [], "sector"


def _refresh_priority(row):
    return (
        float(row.get("structure_score") or 0.0),
        float(row.get("candidate_score") or 0.0),
        int(row.get("candidate_signal_count") or row.get("signal_count") or 0),
        int(row.get("candidate_count") or row.get("count") or 0),
        int(row.get("market_member_count") or 0),
        str(row.get("latest_event") or ""),
    )


def select_board_market_refresh_rows(workspace, board_type="industry", limit=BOARD_REFRESH_LIMIT_DEFAULT):
    """Select the most useful sector/concept rows to refresh."""
    limit = _coerce_limit(limit)
    rows, key_name = _rows_for_type(workspace or {}, board_type)
    candidates = [
        row for row in rows
        if row.get(key_name)
    ]
    return sorted(candidates, key=_refresh_priority, reverse=True)[:limit], key_name


def _payload_summary(name, status, payload=None, error=None):
    payload = payload or {}
    return {
        "name": name,
        "status": status,
        "latest_date": payload.get("latest_date") or "-",
        "strength_score": payload.get("strength_score"),
        "trend_label": payload.get("trend_label") or "-",
        "cache_stale": bool(payload.get("cache_stale")),
        "cache_fallback": bool(payload.get("cache_fallback")),
        "error": str(error or payload.get("error") or ""),
    }


def refresh_board_market_cache(
    workspace,
    board_type="industry",
    limit=BOARD_REFRESH_LIMIT_DEFAULT,
    start_date=DATA_START_DATE,
    force=False,
    get_board_market_func=None,
    read_cached_func=None,
):
    """Refresh top-priority board market caches from the active workspace."""
    if board_type not in {"industry", "concept"}:
        raise ValueError("board_type 必须为 industry 或 concept")
    get_board_market_func = get_board_market_func or get_board_market
    read_cached_func = read_cached_func or read_cached_board_market
    selected, key_name = select_board_market_refresh_rows(workspace, board_type=board_type, limit=limit)

    items = []
    counts = {"updated": 0, "skipped": 0, "fallback": 0, "failed": 0}
    for row in selected:
        name = row.get(key_name)
        if not name:
            continue
        if not force:
            try:
                cached = read_cached_func(board_type, name=name)
            except Exception:
                cached = None
            if cached:
                counts["skipped"] += 1
                items.append(_payload_summary(name, "skipped", cached))
                continue

        try:
            payload = get_board_market_func(board_type, name=name, start_date=start_date)
        except Exception as exc:
            counts["failed"] += 1
            items.append(_payload_summary(name, "failed", error=exc))
            continue

        if not isinstance(payload, dict) or payload.get("available") is False or payload.get("status") == "unavailable":
            counts["failed"] += 1
            items.append(_payload_summary(name, "failed", payload))
            continue
        if payload.get("cache_fallback"):
            counts["fallback"] += 1
            items.append(_payload_summary(name, "fallback", payload))
            continue
        counts["updated"] += 1
        items.append(_payload_summary(name, "updated", payload))

    return {
        "board_type": board_type,
        "limit": _coerce_limit(limit),
        "force": bool(force),
        "selected_count": len(selected),
        "updated_count": counts["updated"],
        "skipped_count": counts["skipped"],
        "fallback_count": counts["fallback"],
        "failed_count": counts["failed"],
        "items": items,
    }
