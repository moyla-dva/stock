"""Single source of truth for scan snapshot refresh policy decisions."""

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.scanner import normalize_scan_type
from stock_analyzer.scan_snapshot import (
    is_current_strategy_snapshot,
    is_recent_snapshot,
    read_latest_scan_snapshot,
    read_scan_snapshot,
    snapshot_has_scan_type,
)


SCAN_REFRESH_POLICIES = {
    "auto": "复用+补齐",
    "cache": "只用本地",
    "force": "强制重扫",
}


def normalize_refresh_policy(refresh_policy=None, force_refresh=False):
    if force_refresh:
        return "force"
    if refresh_policy in SCAN_REFRESH_POLICIES:
        return refresh_policy
    return "auto"


def scan_refresh_policy_label(refresh_policy=None):
    return SCAN_REFRESH_POLICIES[normalize_refresh_policy(refresh_policy)]


def scan_snapshot_status(
    code,
    scan_type,
    *,
    refresh_policy="auto",
    start_date=None,
    logger=None,
    read_scan_snapshot_func=read_scan_snapshot,
    read_latest_scan_snapshot_func=read_latest_scan_snapshot,
    is_recent_snapshot_func=is_recent_snapshot,
    is_current_strategy_snapshot_func=is_current_strategy_snapshot,
    snapshot_has_scan_type_func=snapshot_has_scan_type,
    detect_legacy_strategy=True,
):
    """Resolve local snapshot usability for a scan request.

    Returns both the status and whether the caller may compute a fresh snapshot.
    The status vocabulary is shared by scan planning and actual scan execution.
    """
    code = normalize_code(code)
    scan_type = normalize_scan_type(scan_type)
    refresh_policy = normalize_refresh_policy(refresh_policy)
    allow_compute = refresh_policy in {"auto", "force"}
    use_cache = refresh_policy in {"auto", "cache"}
    require_current_strategy = refresh_policy == "auto"

    if not code:
        return {
            "code": None,
            "status": "invalid",
            "snapshot": None,
            "allow_compute": False,
            "use_cache": False,
            "refresh_policy": refresh_policy,
        }
    if refresh_policy == "force":
        return {
            "code": code,
            "status": "force",
            "snapshot": None,
            "allow_compute": allow_compute,
            "use_cache": False,
            "refresh_policy": refresh_policy,
        }

    exact_status = "missing"
    snapshot = None
    if use_cache:
        snapshot = read_scan_snapshot_func(code, start_date=start_date, logger=logger)
        if snapshot is not None:
            if is_recent_snapshot_func(snapshot):
                if require_current_strategy and not is_current_strategy_snapshot_func(snapshot):
                    exact_status = "legacy_strategy"
                    snapshot = None
                else:
                    exact_status = "ready"
            else:
                exact_status = "stale"
                snapshot = None

        if snapshot is None:
            latest = read_latest_scan_snapshot_func(
                code,
                start_date=start_date,
                logger=logger,
                require_current_strategy=require_current_strategy,
            )
            if latest is not None:
                snapshot = latest
            elif require_current_strategy and detect_legacy_strategy:
                legacy_latest = read_latest_scan_snapshot_func(
                    code,
                    start_date=start_date,
                    logger=logger,
                    require_current_strategy=False,
                )
                if legacy_latest is not None and not is_current_strategy_snapshot_func(legacy_latest):
                    exact_status = "legacy_strategy"

    if snapshot is None:
        return {
            "code": code,
            "status": exact_status,
            "snapshot": None,
            "allow_compute": allow_compute,
            "use_cache": use_cache,
            "refresh_policy": refresh_policy,
        }

    if not snapshot_has_scan_type_func(snapshot, scan_type):
        return {
            "code": code,
            "status": "missing_type",
            "snapshot": snapshot,
            "allow_compute": allow_compute,
            "use_cache": use_cache,
            "refresh_policy": refresh_policy,
        }

    return {
        "code": code,
        "status": "ready",
        "snapshot": snapshot,
        "allow_compute": allow_compute,
        "use_cache": use_cache,
        "refresh_policy": refresh_policy,
    }
