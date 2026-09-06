"""Load scan snapshots into base workspace pools."""

from stock_analyzer import catalog
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.profile_relations import (
    attach_profile_relations,
    build_profile_relation_cache,
    read_profile_relation_evidence,
)
from stock_analyzer.scan_common import result_concepts
from stock_analyzer.scanner import SCAN_CONFIG, normalize_scan_type
from stock_analyzer.scan_snapshot import (
    display_snapshot_day,
    is_current_strategy_snapshot,
    is_recent_snapshot,
    normalize_snapshot_day,
    read_scan_snapshot_file,
    scan_snapshot_day_files,
    scan_result_from_snapshot,
    scan_snapshot_files,
)


def snapshot_code(snapshot):
    return normalize_code(snapshot.get("code")) or snapshot.get("code")


def _profile_name(code, *values):
    for value in values:
        text = str(value or "").strip()
        if text and text != code:
            return text
    return code


def build_empty_pools(scan_types):
    return {
        normalize_scan_type(scan_type): {
            "title": SCAN_CONFIG[normalize_scan_type(scan_type)]["title"],
            "count": 0,
            "current_strategy_count": 0,
            "legacy_strategy_count": 0,
            "results": [],
        }
        for scan_type in scan_types
    }


def _snapshot_day_from_path(path):
    return normalize_snapshot_day(str(path.stem).rsplit("_", 1)[-1])


def _latest_snapshot_day(paths):
    latest = ""
    for path in paths:
        snapshot_day = _snapshot_day_from_path(path)
        if snapshot_day > latest:
            latest = snapshot_day
    return latest


def _workspace_snapshot_paths(start_date=None, target_snapshot_day="", latest_only=False):
    if target_snapshot_day:
        return scan_snapshot_day_files(start_date=start_date, snapshot_day=target_snapshot_day)

    paths = scan_snapshot_files(start_date=start_date)
    if not latest_only:
        return paths

    latest_day = _latest_snapshot_day(paths)
    if not latest_day:
        return []
    return [
        path
        for path in paths
        if _snapshot_day_from_path(path) == latest_day
    ]


def load_workspace_snapshot_pools(start_date=None, scan_types=(), logger=None, snapshot_day=None, latest_only=False):
    target_snapshot_day = normalize_snapshot_day(snapshot_day)
    pools = build_empty_pools(scan_types)
    snapshot_count = 0
    valid_snapshot_count = 0
    stale_snapshot_count = 0
    current_strategy_snapshot_count = 0
    legacy_snapshot_count = 0
    active_current_strategy_snapshot_count = 0
    active_legacy_snapshot_count = 0
    latest_snapshots = {}
    latest_snapshot_day = "-"
    latest_data_date = "-"
    profile_cache = catalog.get_cached_stock_profiles()
    relation_evidence_cache = read_profile_relation_evidence(cache_dir=catalog.CATALOG_CACHE_DIR)
    profile_cache = build_profile_relation_cache(profile_cache, relation_evidence_cache)

    for path in _workspace_snapshot_paths(
        start_date=start_date,
        target_snapshot_day=target_snapshot_day,
        latest_only=latest_only,
    ):
        snapshot = read_scan_snapshot_file(path, logger=logger)
        if target_snapshot_day:
            if snapshot is None or normalize_snapshot_day(snapshot.get("snapshot_day")) != target_snapshot_day:
                continue
            snapshot_count += 1
        else:
            snapshot_count += 1
        if snapshot is None:
            stale_snapshot_count += 1
            continue
        if not target_snapshot_day and not is_recent_snapshot(snapshot):
            stale_snapshot_count += 1
            continue

        valid_snapshot_count += 1
        if is_current_strategy_snapshot(snapshot):
            current_strategy_snapshot_count += 1
        else:
            legacy_snapshot_count += 1
        code = snapshot_code(snapshot)
        if not code:
            stale_snapshot_count += 1
            continue
        current = latest_snapshots.get(code)
        if current is None or snapshot.get("snapshot_day", "") > current.get("snapshot_day", ""):
            latest_snapshots[code] = snapshot

    for snapshot in latest_snapshots.values():
        code = snapshot_code(snapshot)
        snapshot_day = snapshot.get("snapshot_day") or "-"
        data_date = snapshot.get("data_date") or "-"
        cached_profile = profile_cache.get(code, {}) if isinstance(profile_cache, dict) else {}
        sector = snapshot.get("sector") or cached_profile.get("sector") or ""
        concepts = result_concepts(snapshot) or result_concepts(cached_profile)
        is_current_strategy = is_current_strategy_snapshot(snapshot)
        strategy_status = "current" if is_current_strategy else "legacy"
        strategy_meta = snapshot.get("strategy_meta") if isinstance(snapshot.get("strategy_meta"), dict) else {}
        if is_current_strategy:
            active_current_strategy_snapshot_count += 1
        else:
            active_legacy_snapshot_count += 1
        if snapshot_day > latest_snapshot_day:
            latest_snapshot_day = snapshot_day
        if data_date > latest_data_date:
            latest_data_date = data_date

        for scan_type in pools:
            result = scan_result_from_snapshot(snapshot, scan_type)
            if not result:
                continue
            result["name"] = _profile_name(
                code,
                cached_profile.get("name"),
                snapshot.get("name"),
                result.get("name"),
            )
            result["sector"] = result.get("sector") or sector
            result["concepts"] = result_concepts(result) or concepts
            attach_profile_relations(
                result,
                cached_profile,
                verified_date=data_date,
                relation_evidence=relation_evidence_cache.get(code, []),
            )
            result["snapshot_day"] = display_snapshot_day(snapshot_day)
            result["data_date"] = data_date
            result["strategy_status"] = strategy_status
            result["strategy_source_label"] = "当前策略" if is_current_strategy else "旧策略"
            result["snapshot_strategy_version"] = snapshot.get("strategy_version") or "legacy"
            result["snapshot_strategy_label"] = strategy_meta.get("strategy_label") or ("当前策略" if is_current_strategy else "旧策略快照")
            if is_current_strategy:
                pools[scan_type]["current_strategy_count"] += 1
            else:
                pools[scan_type]["legacy_strategy_count"] += 1
            pools[scan_type]["results"].append(result)

    return {
        "target_snapshot_day": target_snapshot_day,
        "pools": pools,
        "snapshot_count": snapshot_count,
        "valid_snapshot_count": valid_snapshot_count,
        "stale_snapshot_count": stale_snapshot_count,
        "current_strategy_snapshot_count": current_strategy_snapshot_count,
        "legacy_snapshot_count": legacy_snapshot_count,
        "active_current_strategy_snapshot_count": active_current_strategy_snapshot_count,
        "active_legacy_snapshot_count": active_legacy_snapshot_count,
        "latest_snapshots": latest_snapshots,
        "latest_snapshot_day": latest_snapshot_day,
        "latest_data_date": latest_data_date,
        "profile_cache": profile_cache,
    }
