"""Scan planning from local snapshot state."""

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.scanner import normalize_scan_type
from stock_analyzer.scan_snapshot_policy import (
    SCAN_REFRESH_POLICIES,
    normalize_refresh_policy,
    scan_refresh_policy_label,
    scan_snapshot_status,
)
from stock_analyzer.scan_snapshot import (
    is_current_strategy_snapshot,
    is_recent_snapshot,
    normalize_snapshot_day,
    read_latest_scan_snapshot,
    read_scan_snapshot,
    read_scan_snapshot_file,
    scan_snapshot_files,
    snapshot_has_scan_type,
)


def legacy_strategy_snapshot_codes(start_date=None, scan_type=None, logger=None):
    scan_type = normalize_scan_type(scan_type) if scan_type else None
    legacy_codes = []
    legacy_seen = set()
    current_seen = set()
    for path in scan_snapshot_files(start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if snapshot is None or not is_recent_snapshot(snapshot):
            continue
        if scan_type and not snapshot_has_scan_type(snapshot, scan_type):
            continue
        code = normalize_code(snapshot.get("code")) or normalize_code(path.name)
        if not code:
            continue
        if is_current_strategy_snapshot(snapshot):
            current_seen.add(code)
            continue
        if code in legacy_seen:
            continue
        legacy_seen.add(code)
        legacy_codes.append(code)
    return [code for code in legacy_codes if code not in current_seen]


def build_scan_snapshot_status_index(scan_type, start_date=None, logger=None):
    """Build per-code snapshot status in one pass for scan planning."""
    scan_type = normalize_scan_type(scan_type)
    statuses = {}
    seen_ready_or_missing_type = set()

    for path in scan_snapshot_files(start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        code = normalize_code((snapshot or {}).get("code")) or normalize_code(path.name)
        if not code or code in seen_ready_or_missing_type:
            continue

        current = statuses.setdefault(code, {"status": "missing", "snapshot_day": ""})
        snapshot_day = normalize_snapshot_day((snapshot or {}).get("snapshot_day"))
        if snapshot_day and snapshot_day < current.get("snapshot_day", ""):
            continue

        if snapshot is None:
            current.update({"status": "stale", "snapshot_day": snapshot_day})
            continue

        if is_recent_snapshot(snapshot):
            if is_current_strategy_snapshot(snapshot):
                status = "ready" if snapshot_has_scan_type(snapshot, scan_type) else "missing_type"
                current.update({"status": status, "snapshot_day": snapshot_day})
                seen_ready_or_missing_type.add(code)
            elif current.get("status") == "missing":
                current.update({"status": "legacy_strategy", "snapshot_day": snapshot_day})
        elif current.get("status") in {"missing", "legacy_strategy"}:
            current.update({"status": "stale", "snapshot_day": snapshot_day})

    return {code: item["status"] for code, item in statuses.items()}


def plan_scan_codes(codes, scan_type, refresh_policy="auto", start_date=None, logger=None):
    refresh_policy = normalize_refresh_policy(refresh_policy)
    scan_type = normalize_scan_type(scan_type)
    requested = list(codes or [])
    planned_codes = []
    seen = set()
    summary = {
        "requested_count": len(requested),
        "eligible_count": 0,
        "queued_count": 0,
        "skipped_count": 0,
        "cache_hit_count": 0,
        "missing_count": 0,
        "stale_count": 0,
        "legacy_strategy_count": 0,
        "missing_type_count": 0,
        "invalid_count": 0,
        "refresh_policy": refresh_policy,
    }
    status_index = (
        build_scan_snapshot_status_index(scan_type, start_date=start_date, logger=logger)
        if refresh_policy == "auto"
        else None
    )

    for raw_code in requested:
        code = normalize_code(raw_code)
        if not code:
            summary["invalid_count"] += 1
            continue
        if code in seen:
            continue
        seen.add(code)
        summary["eligible_count"] += 1

        if refresh_policy == "force":
            planned_codes.append(code)
            continue

        if status_index is not None:
            status = status_index.get(code, "missing")
        else:
            status = scan_snapshot_status(
                code,
                scan_type,
                refresh_policy=refresh_policy,
                start_date=start_date,
                logger=logger,
            )["status"]
        if status == "ready":
            summary["cache_hit_count"] += 1
            summary["skipped_count"] += 1
            continue
        if status == "stale":
            summary["stale_count"] += 1
        elif status == "legacy_strategy":
            summary["legacy_strategy_count"] += 1
        elif status == "missing_type":
            summary["missing_type_count"] += 1
        else:
            summary["missing_count"] += 1

        if refresh_policy == "auto":
            planned_codes.append(code)
        else:
            summary["skipped_count"] += 1

    summary["queued_count"] = len(planned_codes)
    if refresh_policy == "force":
        summary["skipped_count"] = 0
    return {"codes": planned_codes, "summary": summary}
