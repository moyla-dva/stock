"""History index for local scan snapshots."""

from stock_analyzer.scanner import SCAN_CONFIG, normalize_scan_type
from stock_analyzer.scan_snapshot import (
    display_snapshot_day,
    is_current_strategy_snapshot,
    normalize_snapshot_day,
    read_scan_snapshot_file,
    scan_result_from_snapshot,
    scan_snapshot_files,
)


DEFAULT_HISTORY_SCAN_TYPES = ("opportunity", "risk", "bottom_div")


def _empty_pool_counts(scan_types):
    return {
        normalize_scan_type(scan_type): {
            "scan_type": normalize_scan_type(scan_type),
            "title": SCAN_CONFIG[normalize_scan_type(scan_type)]["title"],
            "count": 0,
        }
        for scan_type in scan_types
    }


def list_scan_history(start_date=None, scan_types=DEFAULT_HISTORY_SCAN_TYPES, limit=30, logger=None):
    """Return a compact day index for local scan snapshots."""
    normalized_scan_types = tuple(normalize_scan_type(scan_type) for scan_type in scan_types)
    days = {}
    total_snapshots = 0
    invalid_snapshot_count = 0

    for path in scan_snapshot_files(start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if snapshot is None:
            invalid_snapshot_count += 1
            continue

        snapshot_day = normalize_snapshot_day(snapshot.get("snapshot_day"))
        if not snapshot_day:
            invalid_snapshot_count += 1
            continue

        total_snapshots += 1
        day = days.setdefault(snapshot_day, {
            "snapshot_day": snapshot_day,
            "display_day": display_snapshot_day(snapshot_day),
            "snapshot_count": 0,
            "current_strategy_count": 0,
            "legacy_strategy_count": 0,
            "latest_data_date": "-",
            "pool_counts": _empty_pool_counts(normalized_scan_types),
        })
        day["snapshot_count"] += 1
        if is_current_strategy_snapshot(snapshot):
            day["current_strategy_count"] += 1
        else:
            day["legacy_strategy_count"] += 1

        data_date = str(snapshot.get("data_date") or "")
        if data_date and data_date > day["latest_data_date"]:
            day["latest_data_date"] = data_date

        for scan_type in normalized_scan_types:
            if scan_result_from_snapshot(snapshot, scan_type):
                day["pool_counts"][scan_type]["count"] += 1

    items = sorted(days.values(), key=lambda item: item["snapshot_day"], reverse=True)
    try:
        max_items = max(1, min(int(limit), 120))
    except (TypeError, ValueError):
        max_items = 30

    return {
        "start_date": start_date or "-",
        "count": len(items),
        "snapshot_count": total_snapshots,
        "invalid_snapshot_count": invalid_snapshot_count,
        "items": items[:max_items],
    }
