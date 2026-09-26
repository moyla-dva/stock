"""History comparison helpers for scan workspace snapshots."""

from stock_analyzer.c_signal_v2 import apply_c_signal_v2_priority
from stock_analyzer.scan_common import as_float
from stock_analyzer.scan_snapshot import (
    display_snapshot_day,
    normalize_snapshot_day,
    read_scan_snapshot_file,
    scan_result_from_snapshot,
    scan_snapshot_files,
)
from stock_analyzer.scan_workspace_loader import snapshot_code


def rank_value(result):
    return as_float(result.get("final_score"), as_float(result.get("rank_score"), 0.0))


def v2_priority_value(result):
    try:
        return float(result.get("v2_priority_score"))
    except (TypeError, ValueError):
        return rank_value(result)


def build_latest_reference(start_date=None, excluded_snapshot_day=None, logger=None):
    """Return the latest snapshot per stock outside a history replay day."""
    excluded_snapshot_day = normalize_snapshot_day(excluded_snapshot_day)
    latest = {}
    snapshots = []
    latest_day = ""

    for path in scan_snapshot_files(start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if snapshot is None:
            continue
        snapshot_day = normalize_snapshot_day(snapshot.get("snapshot_day"))
        if snapshot_day > latest_day:
            latest_day = snapshot_day
        snapshots.append((snapshot_day, snapshot))

    if excluded_snapshot_day and latest_day <= excluded_snapshot_day:
        return {}

    for snapshot_day, snapshot in snapshots:
        if excluded_snapshot_day and snapshot_day == excluded_snapshot_day:
            continue
        code = snapshot_code(snapshot)
        if not code:
            continue
        current = latest.get(code)
        if current is None or snapshot_day > normalize_snapshot_day(current.get("snapshot_day")):
            latest[code] = snapshot
    return latest


def _reference_pool(snapshot_map, scan_type):
    results = []
    for snapshot in snapshot_map.values():
        result = scan_result_from_snapshot(snapshot, scan_type)
        if result:
            result["snapshot_day"] = display_snapshot_day(snapshot.get("snapshot_day"))
            result["data_date"] = snapshot.get("data_date") or "-"
            result["scan_type"] = scan_type
            results.append(result)
    apply_c_signal_v2_priority({scan_type: {"results": results}})
    return sorted(
        results,
        key=lambda item: (
            1 if item.get("strategy_status") == "current" else 0,
            v2_priority_value(item),
            rank_value(item),
            str(item.get("event_date") or item.get("date") or ""),
            str(item.get("code") or ""),
        ),
        reverse=True,
    )


def _empty_history_comparison():
    return {
        "reference_available": False,
        "retained_count": 0,
        "new_count": 0,
        "disappeared_count": 0,
        "rank_up_count": 0,
        "rank_down_count": 0,
    }


def apply_history_comparison(pools, latest_reference):
    """Annotate displayed pool results with their relation to the latest snapshot."""
    if not latest_reference:
        for pool in pools.values():
            pool["history_comparison"] = _empty_history_comparison()
        return

    for scan_type, pool in pools.items():
        reference_results = _reference_pool(latest_reference, scan_type)
        reference_codes = {
            result.get("code"): index + 1
            for index, result in enumerate(reference_results)
            if result.get("code")
        }
        selected_codes = set()
        retained_count = 0
        disappeared_count = 0
        rank_up_count = 0
        rank_down_count = 0

        for index, result in enumerate(pool.get("results", []), start=1):
            code = result.get("code")
            selected_codes.add(code)
            latest_rank = reference_codes.get(code)
            if latest_rank is None:
                disappeared_count += 1
                result["history_delta"] = {
                    "status": "disappeared",
                    "label": "最新已消失",
                    "history_rank": index,
                    "latest_rank": None,
                    "rank_delta": None,
                }
                continue

            retained_count += 1
            rank_delta = index - latest_rank
            if rank_delta > 0:
                rank_up_count += 1
                label = f"最新上升 {rank_delta}"
                status = "rank_up"
            elif rank_delta < 0:
                rank_down_count += 1
                label = f"最新下降 {abs(rank_delta)}"
                status = "rank_down"
            else:
                label = "最新持平"
                status = "unchanged"

            result["history_delta"] = {
                "status": status,
                "label": label,
                "history_rank": index,
                "latest_rank": latest_rank,
                "rank_delta": rank_delta,
            }

        pool["history_comparison"] = {
            "reference_available": True,
            "retained_count": retained_count,
            "new_count": len(set(reference_codes) - selected_codes),
            "disappeared_count": disappeared_count,
            "rank_up_count": rank_up_count,
            "rank_down_count": rank_down_count,
        }
