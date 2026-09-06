"""Response shaping for the scan workspace API."""

from stock_analyzer.scan_snapshot import display_snapshot_day
from stock_analyzer.scan_snapshot_meta import build_snapshot_meta
from stock_analyzer.scan_strategy_health import build_strategy_health
from stock_analyzer.scan_workspace_history_compare import rank_value
from stock_analyzer.versioning import build_strategy_meta


def sort_scan_results(results):
    return sorted(
        results,
        key=lambda item: (
            1 if item.get("strategy_status") == "current" else 0,
            rank_value(item),
            str(item.get("event_date") or item.get("date") or ""),
            str(item.get("code") or ""),
        ),
        reverse=True,
    )


def trim_workspace_pools(pools, max_items):
    """Sort pools, preserve full counts, and cap the displayed result payload."""
    for pool in pools.values():
        results = sort_scan_results(pool["results"])
        pool["count"] = len(results)
        pool["max_items"] = max_items
        pool["results"] = results[:max_items]
        pool["loaded_count"] = len(pool["results"])
        pool["has_more"] = pool["loaded_count"] < pool["count"]


def trim_workspace_overview(overview, limit=None):
    if not limit:
        return overview
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return overview
    if limit <= 0:
        return overview
    return (overview or [])[:limit]


def _pool_stat_priority(stat, name_key):
    score_key = f"{name_key}_score"
    return (
        float(stat.get(score_key) or stat.get("candidate_score") or stat.get("structure_score") or 0.0),
        int(stat.get("signal_count") or stat.get("candidate_signal_count") or 0),
        int(stat.get("count") or stat.get("candidate_count") or 0),
        float(stat.get("avg_rank") or 0.0),
        str(stat.get("latest_event") or ""),
    )


def trim_workspace_pool_stats(pools, limit=None):
    if not limit:
        return
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return
    if limit <= 0:
        return
    for pool in (pools or {}).values():
        if isinstance(pool.get("sector_stats"), list):
            pool["sector_stats"] = sorted(
                pool["sector_stats"],
                key=lambda stat: _pool_stat_priority(stat, "sector"),
                reverse=True,
            )[:limit]
        if isinstance(pool.get("concept_stats"), list):
            pool["concept_stats"] = sorted(
                pool["concept_stats"],
                key=lambda stat: _pool_stat_priority(stat, "concept"),
                reverse=True,
            )[:limit]


def build_workspace_response(
    loaded,
    structure,
    start_date=None,
    max_items=120,
    overview_limit=None,
    pool_stats_limit=None,
):
    target_snapshot_day = loaded["target_snapshot_day"]
    latest_snapshots = loaded["latest_snapshots"]
    latest_snapshot_day = loaded["latest_snapshot_day"]
    latest_data_date = loaded["latest_data_date"]
    pools = loaded["pools"]
    trim_workspace_pool_stats(pools, pool_stats_limit)

    active_stale_snapshot_count = loaded["stale_snapshot_count"] if not latest_snapshots else 0
    snapshot_meta = build_snapshot_meta(
        start_date=start_date,
        snapshot_count=loaded["snapshot_count"],
        valid_snapshot_count=loaded["valid_snapshot_count"],
        stale_snapshot_count=active_stale_snapshot_count,
        stored_stale_snapshot_count=loaded["stale_snapshot_count"],
        current_strategy_snapshot_count=loaded["active_current_strategy_snapshot_count"],
        legacy_snapshot_count=loaded["active_legacy_snapshot_count"],
        stored_current_strategy_snapshot_count=loaded["current_strategy_snapshot_count"],
        stored_legacy_snapshot_count=loaded["legacy_snapshot_count"],
        scanned_count=len(latest_snapshots),
        latest_snapshot_day=latest_snapshot_day,
        latest_data_date=latest_data_date,
        history_snapshot_day=target_snapshot_day,
        strategy_version_counts=loaded.get("strategy_version_counts"),
        active_strategy_version_counts=loaded.get("active_strategy_version_counts"),
        strategy_version_labels=loaded.get("strategy_version_labels"),
    )
    strategy_health = build_strategy_health(pools, snapshot_meta)

    return {
        "start_date": start_date or "-",
        "snapshot_count": loaded["snapshot_count"],
        "valid_snapshot_count": loaded["valid_snapshot_count"],
        "stale_snapshot_count": active_stale_snapshot_count,
        "stored_stale_snapshot_count": loaded["stale_snapshot_count"],
        "current_strategy_snapshot_count": loaded["active_current_strategy_snapshot_count"],
        "legacy_snapshot_count": loaded["active_legacy_snapshot_count"],
        "stored_current_strategy_snapshot_count": loaded["current_strategy_snapshot_count"],
        "stored_legacy_snapshot_count": loaded["legacy_snapshot_count"],
        "scanned_count": len(latest_snapshots),
        "latest_snapshot_day": display_snapshot_day(latest_snapshot_day),
        "latest_data_date": latest_data_date,
        "history_mode": bool(target_snapshot_day),
        "history_snapshot_day": target_snapshot_day,
        "history_display_day": display_snapshot_day(target_snapshot_day),
        "snapshot_meta": snapshot_meta,
        "strategy_meta": build_strategy_meta(start_date=start_date),
        "strategy_health": strategy_health,
        "max_items": max_items,
        "concept_graph_status": structure.get("concept_graph_status") or {},
        "sector_overview": trim_workspace_overview(structure["sector_overview"], overview_limit),
        "concept_overview": trim_workspace_overview(structure["concept_overview"], overview_limit),
        "market_structure_meta": structure.get("market_structure_meta") or {},
        "resonance_calibration": structure["resonance_calibration"],
        "replay_calibration": structure["replay_calibration"],
        "pools": pools,
    }
