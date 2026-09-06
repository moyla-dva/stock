"""Local scan snapshot cache governance."""

from stock_analyzer.scan_snapshot import (
    display_snapshot_day,
    is_current_strategy_snapshot,
    is_recent_snapshot,
    normalize_snapshot_day,
    read_scan_snapshot_file,
    scan_snapshot_files,
)


def _file_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _snapshot_code(snapshot, path):
    text = str(snapshot.get("code") or path.name[:6] or "").strip()
    return text[:6] if len(text) >= 6 and text[:6].isdigit() else ""


def _current_strategy_days_by_code(start_date=None, logger=None):
    days_by_code = {}
    for path in scan_snapshot_files(start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if snapshot is None or not is_recent_snapshot(snapshot):
            continue
        if not is_current_strategy_snapshot(snapshot):
            continue
        code = _snapshot_code(snapshot, path)
        snapshot_day = normalize_snapshot_day(snapshot.get("snapshot_day"))
        if code and snapshot_day > days_by_code.get(code, ""):
            days_by_code[code] = snapshot_day
    return days_by_code


def is_obsolete_strategy_snapshot(snapshot, path, current_strategy_days):
    if snapshot is None or is_current_strategy_snapshot(snapshot):
        return False
    code = _snapshot_code(snapshot, path)
    snapshot_day = normalize_snapshot_day(snapshot.get("snapshot_day"))
    current_day = current_strategy_days.get(code)
    return bool(code and snapshot_day and current_day and current_day >= snapshot_day)


def scan_cache_status(start_date=None, logger=None):
    files = scan_snapshot_files(start_date=start_date)
    current_strategy_days = _current_strategy_days_by_code(start_date=start_date, logger=logger)
    status = {
        "start_date": start_date or "-",
        "file_count": 0,
        "total_bytes": 0,
        "size_mb": 0.0,
        "valid_count": 0,
        "stale_count": 0,
        "invalid_count": 0,
        "current_strategy_count": 0,
        "legacy_strategy_count": 0,
        "obsolete_strategy_count": 0,
        "latest_snapshot_day": "-",
        "latest_display_day": "-",
    }

    for path in files:
        status["file_count"] += 1
        status["total_bytes"] += _file_size(path)
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if snapshot is None:
            status["invalid_count"] += 1
            continue
        if not is_recent_snapshot(snapshot):
            status["stale_count"] += 1
        else:
            status["valid_count"] += 1
        if is_current_strategy_snapshot(snapshot):
            status["current_strategy_count"] += 1
        else:
            status["legacy_strategy_count"] += 1
            if is_obsolete_strategy_snapshot(snapshot, path, current_strategy_days):
                status["obsolete_strategy_count"] += 1
        snapshot_day = normalize_snapshot_day(snapshot.get("snapshot_day"))
        if snapshot_day > normalize_snapshot_day(status["latest_snapshot_day"]):
            status["latest_snapshot_day"] = snapshot_day
            status["latest_display_day"] = display_snapshot_day(snapshot_day)

    status["size_mb"] = round(status["total_bytes"] / 1024 / 1024, 2)
    return status


def prune_scan_cache(start_date=None, logger=None, delete_obsolete_strategy=False):
    deleted = []
    kept = 0
    deleted_obsolete_strategy_count = 0
    current_strategy_days = _current_strategy_days_by_code(start_date=start_date, logger=logger)
    for path in scan_snapshot_files(start_date=start_date):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        is_obsolete = (
            delete_obsolete_strategy
            and snapshot is not None
            and is_recent_snapshot(snapshot)
            and is_obsolete_strategy_snapshot(snapshot, path, current_strategy_days)
        )
        should_delete = snapshot is None or not is_recent_snapshot(snapshot) or is_obsolete
        if not should_delete:
            kept += 1
            continue
        try:
            deleted.append({"file": path.name, "bytes": _file_size(path)})
            if is_obsolete:
                deleted_obsolete_strategy_count += 1
            path.unlink()
        except OSError as e:
            if logger:
                logger.warning(f"删除扫描快照失败: {path.name}, error={e}")

    return {
        "start_date": start_date or "-",
        "deleted_count": len(deleted),
        "deleted_bytes": sum(item["bytes"] for item in deleted),
        "deleted_size_mb": round(sum(item["bytes"] for item in deleted) / 1024 / 1024, 2),
        "deleted_obsolete_strategy_count": deleted_obsolete_strategy_count,
        "delete_obsolete_strategy": bool(delete_obsolete_strategy),
        "kept_count": kept,
        "deleted": deleted[:50],
    }
