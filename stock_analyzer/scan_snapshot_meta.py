"""User-facing health metadata for local scan snapshots."""

from stock_analyzer.scan_snapshot import (
    MAX_LATEST_SNAPSHOT_AGE_DAYS,
    MAX_SNAPSHOT_DATA_LAG_DAYS,
    SNAPSHOT_VERSION,
    display_snapshot_day,
    normalize_snapshot_day,
)
from stock_analyzer.versioning import build_strategy_meta


def build_snapshot_meta(
    start_date=None,
    snapshot_count=0,
    valid_snapshot_count=0,
    stale_snapshot_count=0,
    current_strategy_snapshot_count=0,
    legacy_snapshot_count=0,
    stored_stale_snapshot_count=None,
    stored_current_strategy_snapshot_count=None,
    stored_legacy_snapshot_count=None,
    scanned_count=0,
    latest_snapshot_day="-",
    latest_data_date="-",
    history_snapshot_day=None,
):
    snapshot_count_value = int(snapshot_count or 0)
    valid_snapshot_count_value = int(valid_snapshot_count or 0)
    stale_snapshot_count_value = int(stale_snapshot_count or 0)
    current_strategy_snapshot_count_value = int(current_strategy_snapshot_count or 0)
    legacy_snapshot_count_value = int(legacy_snapshot_count or 0)
    stored_stale_snapshot_count_value = int(
        stale_snapshot_count_value if stored_stale_snapshot_count is None else stored_stale_snapshot_count
    )
    stored_current_strategy_snapshot_count_value = int(
        current_strategy_snapshot_count_value
        if stored_current_strategy_snapshot_count is None
        else stored_current_strategy_snapshot_count
    )
    stored_legacy_snapshot_count_value = int(
        legacy_snapshot_count_value
        if stored_legacy_snapshot_count is None
        else stored_legacy_snapshot_count
    )
    scanned_count_value = int(scanned_count or 0)
    latest_snapshot_display = display_snapshot_day(latest_snapshot_day)
    latest_data_display = latest_data_date or "-"
    history_day = normalize_snapshot_day(history_snapshot_day)
    history_display = display_snapshot_day(history_day)

    if history_day and valid_snapshot_count_value:
        health = "history"
        health_label = "历史回看"
        action_label = "回到最新"
    elif not snapshot_count_value:
        health = "empty"
        health_label = "无快照"
        action_label = "先扫描"
    elif not valid_snapshot_count_value:
        health = "expired"
        health_label = "已过期"
        action_label = "重建"
    elif legacy_snapshot_count_value:
        health = "legacy"
        health_label = "策略待刷新"
        action_label = "重算"
    elif stale_snapshot_count_value:
        health = "partial"
        health_label = "需补扫"
        action_label = "增量补齐"
    else:
        health = "healthy"
        health_label = "可用"
        action_label = "按需更新"

    strategy_meta = build_strategy_meta(start_date=start_date)
    strategy_version = strategy_meta["strategy_version"]
    if health == "history":
        health_summary = "历史快照回看"
        health_detail = "当前查看 {} · 最新快照 {} · 数据 {}".format(
            history_display,
            latest_snapshot_display,
            latest_data_display,
        )
    elif health == "empty":
        health_summary = "还没有本地快照"
        health_detail = "先运行增量扫描，生成当前池候选。"
    elif health == "expired":
        health_summary = "快照已过期"
        health_detail = "有效 0 · 过期 {} · 建议重建当前池。".format(
            stored_stale_snapshot_count_value
        )
    elif health == "legacy":
        health_summary = "旧策略待重算"
        health_detail = "旧版 {} · 当前 {} · 最新策略 {}。".format(
            legacy_snapshot_count_value,
            current_strategy_snapshot_count_value,
            strategy_version,
        )
    elif health == "partial":
        health_summary = "需要增量补齐"
        health_detail = "有效 {} · 过期 {} · 已扫描 {}。".format(
            valid_snapshot_count_value,
            stale_snapshot_count_value,
            scanned_count_value,
        )
    else:
        health_summary = "快照可用"
        health_detail = "数据 {} · 快照 {} · 策略 {}。".format(
            latest_data_display,
            latest_snapshot_display,
            strategy_version,
        )

    return {
        "schema_version": SNAPSHOT_VERSION,
        "strategy_version": strategy_version,
        "strategy_label": strategy_meta["strategy_label"],
        "explanation_version": strategy_meta["explanation_version"],
        "start_date": start_date or "-",
        "snapshot_count": snapshot_count_value,
        "valid_snapshot_count": valid_snapshot_count_value,
        "stale_snapshot_count": stale_snapshot_count_value,
        "stored_stale_snapshot_count": stored_stale_snapshot_count_value,
        "current_strategy_snapshot_count": current_strategy_snapshot_count_value,
        "legacy_snapshot_count": legacy_snapshot_count_value,
        "stored_current_strategy_snapshot_count": stored_current_strategy_snapshot_count_value,
        "stored_legacy_snapshot_count": stored_legacy_snapshot_count_value,
        "scanned_count": scanned_count_value,
        "latest_snapshot_day": latest_snapshot_display,
        "latest_data_date": latest_data_display,
        "history_mode": bool(history_day),
        "history_snapshot_day": history_day,
        "history_display_day": history_display,
        "max_snapshot_age_days": MAX_LATEST_SNAPSHOT_AGE_DAYS,
        "max_data_lag_days": MAX_SNAPSHOT_DATA_LAG_DAYS,
        "health": health,
        "health_label": health_label,
        "health_summary": health_summary,
        "health_detail": health_detail,
        "action_label": action_label,
    }
