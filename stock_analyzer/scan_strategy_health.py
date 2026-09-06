"""Strategy migration and calibration readiness for scan workspaces."""

from stock_analyzer.scan_common import as_float, avg_or_none


def build_strategy_health(pools, snapshot_meta):
    pool_stats = {}
    total_results = 0
    current_results = 0
    legacy_results = 0
    current_rank_total = 0.0
    current_rank_count = 0
    current_win_total = 0.0
    current_win_count = 0

    for scan_type, pool in pools.items():
        pool_current = int(pool.get("current_strategy_count") or 0)
        pool_legacy = int(pool.get("legacy_strategy_count") or 0)
        pool_total = pool_current + pool_legacy
        pool_stats[scan_type] = {
            "scan_type": scan_type,
            "title": pool.get("title") or scan_type,
            "count": pool_total,
            "current_strategy_count": pool_current,
            "legacy_strategy_count": pool_legacy,
            "current_ratio": round(pool_current * 100 / pool_total, 1) if pool_total else 0.0,
        }
        total_results += pool_total
        current_results += pool_current
        legacy_results += pool_legacy

        for result in pool.get("results", []):
            if result.get("strategy_status") != "current":
                continue
            current_rank_total += as_float(result.get("rank_score"), 0.0)
            current_rank_count += 1
            if result.get("win_rate") is not None:
                current_win_total += as_float(result.get("win_rate"), 0.0)
                current_win_count += 1

    current_ratio = round(current_results * 100 / total_results, 1) if total_results else 0.0
    legacy_ratio = round(legacy_results * 100 / total_results, 1) if total_results else 0.0
    snapshot_current = int(snapshot_meta.get("current_strategy_snapshot_count") or 0)
    snapshot_legacy = int(snapshot_meta.get("legacy_snapshot_count") or 0)
    snapshot_total = snapshot_current + snapshot_legacy
    migration_ratio = round(snapshot_current * 100 / snapshot_total, 1) if snapshot_total else 0.0

    if legacy_results:
        health = "migration"
        health_label = "迁移中"
        note = "扫描结果包含旧策略样本，校准仅供迁移参考"
    elif current_results >= 30:
        health = "ready"
        health_label = "可校准"
        note = "当前策略样本已可用于共振校准"
    elif current_results:
        health = "warming"
        health_label = "样本积累"
        note = "当前策略样本偏少，先观察分布"
    else:
        health = "empty"
        health_label = "等待样本"
        note = "尚无当前策略扫描结果"

    return {
        "health": health,
        "health_label": health_label,
        "note": note,
        "result_count": total_results,
        "current_strategy_result_count": current_results,
        "legacy_strategy_result_count": legacy_results,
        "current_result_ratio": current_ratio,
        "legacy_result_ratio": legacy_ratio,
        "migration_ratio": migration_ratio,
        "snapshot_current_count": snapshot_current,
        "snapshot_legacy_count": snapshot_legacy,
        "avg_current_rank": avg_or_none(current_rank_total, current_rank_count, 1),
        "avg_current_win_rate": avg_or_none(current_win_total, current_win_count, 1),
        "pool_stats": pool_stats,
    }
