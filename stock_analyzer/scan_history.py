"""History index for local scan snapshots."""

import json
import os
import uuid

from stock_analyzer import scan_snapshot
from stock_analyzer.scanner import SCAN_CONFIG, normalize_scan_type
from stock_analyzer.scan_snapshot import (
    display_snapshot_day,
    is_current_strategy_snapshot,
    normalize_snapshot_day,
    read_scan_snapshot_file,
    scan_result_from_snapshot,
    scan_snapshot_files,
)
from stock_analyzer.versioning import DATA_ADJUST, SCAN_STRATEGY_VERSION


DEFAULT_HISTORY_SCAN_TYPES = ("opportunity", "risk", "bottom_div")
SCAN_HISTORY_INDEX_SCHEMA_VERSION = 1


def _empty_pool_counts(scan_types):
    return {
        normalize_scan_type(scan_type): {
            "scan_type": normalize_scan_type(scan_type),
            "title": SCAN_CONFIG[normalize_scan_type(scan_type)]["title"],
            "count": 0,
        }
        for scan_type in scan_types
    }


def _start_key(start_date=None):
    return str(start_date or "default").replace("-", "")


def _history_index_path(start_date=None):
    return scan_snapshot.SNAPSHOT_DIR / f"_history_index_{_start_key(start_date)}.json"


def _snapshot_fingerprint(paths):
    latest_mtime_ns = 0
    total_size = 0
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        total_size += stat.st_size
    return {
        "file_count": len(paths),
        "latest_mtime_ns": latest_mtime_ns,
        "total_size": total_size,
    }


def _empty_history(start_date, scan_types):
    return {
        "start_date": start_date or "-",
        "count": 0,
        "snapshot_count": 0,
        "invalid_snapshot_count": 0,
        "items": [],
        "cache_meta": {
            "schema_version": SCAN_HISTORY_INDEX_SCHEMA_VERSION,
            "hit": False,
        },
    }


def _read_cached_history(index_path, fingerprint, normalized_scan_types):
    try:
        with index_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    meta = payload.get("cache_meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return None
    if meta.get("schema_version") != SCAN_HISTORY_INDEX_SCHEMA_VERSION:
        return None
    if meta.get("fingerprint") != fingerprint:
        return None
    if tuple(meta.get("scan_types") or ()) != tuple(normalized_scan_types):
        return None
    payload["cache_meta"] = dict(meta, hit=True)
    return payload


def _write_cached_history(index_path, payload, fingerprint, normalized_scan_types):
    cache_payload = dict(payload)
    cache_payload["cache_meta"] = {
        "schema_version": SCAN_HISTORY_INDEX_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "scan_types": list(normalized_scan_types),
        "hit": False,
    }
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = index_path.with_name(f"{index_path.name}.{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(cache_payload, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(index_path)
    except Exception:
        return payload
    return cache_payload


def _slice_history(payload, limit):
    try:
        max_items = max(1, min(int(limit), 120))
    except (TypeError, ValueError):
        max_items = 30
    sliced = dict(payload)
    sliced["items"] = list(payload.get("items") or [])[:max_items]
    return sliced


def _indexed_scan_history(index_store, start_date, normalized_scan_types, limit):
    fingerprint = index_store.cache_fingerprint(scan_snapshot.SNAPSHOT_DIR)
    if not fingerprint.get("available"):
        return None
    rows = index_store.scan_history_rows(
        start_key=_start_key(start_date),
        scan_types=normalized_scan_types,
        current_strategy_version=SCAN_STRATEGY_VERSION,
        current_data_adjust=DATA_ADJUST,
        limit=limit,
    )
    try:
        max_items = max(1, min(int(limit), 120))
    except (TypeError, ValueError):
        max_items = 30
    items = []
    for row in rows[:max_items]:
        raw_counts = row.get("pool_counts") or {}
        pool_counts = _empty_pool_counts(normalized_scan_types)
        for scan_type in normalized_scan_types:
            pool_counts[scan_type]["count"] = int(raw_counts.get(scan_type) or 0)
        items.append({
            "snapshot_day": row["snapshot_day"],
            "display_day": display_snapshot_day(row["snapshot_day"]),
            "snapshot_count": int(row.get("snapshot_count") or 0),
            "current_strategy_count": int(row.get("current_strategy_count") or 0),
            "legacy_strategy_count": int(row.get("legacy_strategy_count") or 0),
            "latest_data_date": str(row.get("latest_data_date") or "-"),
            "pool_counts": pool_counts,
        })
    return {
        "start_date": start_date or "-",
        "count": len(rows),
        "snapshot_count": sum(int(row.get("snapshot_count") or 0) for row in rows),
        "invalid_snapshot_count": 0,
        "items": items,
        "cache_meta": {
            "schema_version": SCAN_HISTORY_INDEX_SCHEMA_VERSION,
            "hit": True,
            "source": "sqlite",
            "index_revision": fingerprint.get("revision") or "",
        },
    }


def _build_scan_history(start_date, normalized_scan_types, paths, logger=None):
    days = {}
    total_snapshots = 0
    invalid_snapshot_count = 0

    for path in paths:
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
    return {
        "start_date": start_date or "-",
        "count": len(items),
        "snapshot_count": total_snapshots,
        "invalid_snapshot_count": invalid_snapshot_count,
        "items": items,
    }


def list_scan_history(
    start_date=None,
    scan_types=DEFAULT_HISTORY_SCAN_TYPES,
    limit=30,
    logger=None,
    force_refresh=False,
    index_store=None,
):
    """Return a compact day index for local scan snapshots."""
    normalized_scan_types = tuple(normalize_scan_type(scan_type) for scan_type in scan_types)
    if index_store is not None:
        try:
            indexed = _indexed_scan_history(
                index_store,
                start_date,
                normalized_scan_types,
                limit,
            )
            if indexed is not None:
                return indexed
        except Exception:
            if logger:
                logger.warning("SQLite 扫描历史不可用，回退 JSON 快照", exc_info=True)
    paths = list(scan_snapshot_files(start_date=start_date))
    fingerprint = _snapshot_fingerprint(paths)
    index_path = _history_index_path(start_date=start_date)
    if not force_refresh:
        cached = _read_cached_history(index_path, fingerprint, normalized_scan_types)
        if cached is not None:
            return _slice_history(cached, limit)
    if not paths:
        history = _empty_history(start_date, normalized_scan_types)
    else:
        history = _build_scan_history(start_date, normalized_scan_types, paths, logger=logger)
    history = _write_cached_history(index_path, history, fingerprint, normalized_scan_types)
    return _slice_history(history, limit)
