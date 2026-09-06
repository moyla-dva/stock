# -*- coding: utf-8 -*-
"""Scan decision and planning services."""

from stock_analyzer.catalog import get_stock_codes, get_stock_profile
from stock_analyzer.scan_planner import (
    legacy_strategy_snapshot_codes,
    plan_scan_codes,
)
from stock_analyzer.scan_snapshot_policy import normalize_refresh_policy, scan_snapshot_status
from stock_analyzer.scanner import normalize_scan_type
from stock_analyzer.scan_snapshot import (
    SNAPSHOT_SCAN_TYPES,
    build_scan_snapshot,
    is_current_strategy_snapshot,
    is_recent_snapshot,
    read_latest_scan_snapshot,
    read_scan_snapshot,
    scan_result_from_snapshot,
    snapshot_has_scan_type,
    write_scan_snapshot,
)
from stock_analyzer.stock_service import enrich_scan_result_with_profile, get_stock_dataframe
from stock_analyzer.versioning import DATA_START_DATE, build_strategy_meta


def check_stock_signal(
    code,
    scan_type="opportunity",
    force_refresh=False,
    refresh_policy=None,
    *,
    read_scan_snapshot_func=read_scan_snapshot,
    read_latest_scan_snapshot_func=read_latest_scan_snapshot,
    is_recent_snapshot_func=is_recent_snapshot,
    is_current_strategy_snapshot_func=is_current_strategy_snapshot,
    snapshot_has_scan_type_func=snapshot_has_scan_type,
    scan_result_from_snapshot_func=scan_result_from_snapshot,
    get_stock_dataframe_func=get_stock_dataframe,
    get_stock_profile_func=get_stock_profile,
    build_scan_snapshot_func=build_scan_snapshot,
    write_scan_snapshot_func=write_scan_snapshot,
    enrich_result_func=None,
):
    """Check whether a single stock triggers the requested scan signal."""
    try:
        scan_type = normalize_scan_type(scan_type)
        refresh_policy = normalize_refresh_policy(refresh_policy, force_refresh=force_refresh)
        if enrich_result_func is None:
            enrich_result_func = lambda result, scan_code, profile=None: enrich_scan_result_with_profile(
                result,
                scan_code,
                profile=profile,
                get_stock_profile_func=get_stock_profile_func,
            )

        snapshot_decision = scan_snapshot_status(
            code,
            scan_type,
            refresh_policy=refresh_policy,
            start_date=DATA_START_DATE,
            read_scan_snapshot_func=read_scan_snapshot_func,
            read_latest_scan_snapshot_func=read_latest_scan_snapshot_func,
            is_recent_snapshot_func=is_recent_snapshot_func,
            is_current_strategy_snapshot_func=is_current_strategy_snapshot_func,
            snapshot_has_scan_type_func=snapshot_has_scan_type_func,
            detect_legacy_strategy=False,
        )
        snapshot = snapshot_decision.get("snapshot")
        if snapshot_decision.get("status") == "ready" and snapshot:
            result = scan_result_from_snapshot_func(snapshot, scan_type)
            if result:
                enrich_result_func(result, code)
                result["scan_source"] = "cache"
            return result

        if not snapshot_decision.get("allow_compute"):
            return None

        df = get_stock_dataframe_func(code)
        if df is None or df.empty:
            return None

        profile = get_stock_profile_func(code)
        scan_types = SNAPSHOT_SCAN_TYPES
        if scan_type not in set(SNAPSHOT_SCAN_TYPES):
            scan_types = tuple(SNAPSHOT_SCAN_TYPES) + (scan_type,)
        snapshot = build_scan_snapshot_func(
            code,
            profile.get("name") or code,
            df,
            scan_types=scan_types,
            sector=profile.get("sector"),
            concepts=profile.get("concepts"),
        )
        write_scan_snapshot_func(snapshot, start_date=DATA_START_DATE)
        result = scan_result_from_snapshot_func(snapshot, scan_type)
        if result:
            enrich_result_func(result, code, profile=profile)
            result["scan_source"] = "force" if refresh_policy == "force" else "computed"
            return result
    except Exception:
        return None
    return None


def build_scan_request_plan(
    data,
    *,
    scan_job_manager,
    get_stock_codes_func=get_stock_codes,
    logger=None,
):
    if not isinstance(data, dict):
        raise ValueError("无效的JSON数据")
    scan_type = normalize_scan_type(data.get("scan_type") or data.get("mode", "opportunity"))
    force_refresh = bool(data.get("refresh", False))
    refresh_policy = normalize_refresh_policy(data.get("refresh_policy"), force_refresh=force_refresh)
    codes = data.get("codes")
    scope = data.get("scope") or "market"
    code_source = "market"
    if codes is None:
        if scope == "legacy_strategy":
            codes = legacy_strategy_snapshot_codes(
                start_date=DATA_START_DATE,
                scan_type=scan_type,
                logger=logger,
            )
            code_source = "legacy_strategy"
        else:
            codes = get_stock_codes_func()
    else:
        code_source = "custom"
    if not isinstance(codes, list):
        raise ValueError("codes必须为数组")
    if not codes and scope != "legacy_strategy":
        raise ValueError("没有可扫描的股票")

    if code_source == "legacy_strategy" and refresh_policy == "auto":
        plan = {
            "codes": codes,
            "summary": {
                "requested_count": len(codes),
                "eligible_count": len(codes),
                "queued_count": len(codes),
                "skipped_count": 0,
                "cache_hit_count": 0,
                "missing_count": 0,
                "stale_count": 0,
                "legacy_strategy_count": len(codes),
                "missing_type_count": 0,
                "invalid_count": 0,
                "refresh_policy": refresh_policy,
            },
        }
    else:
        plan = plan_scan_codes(
            codes,
            scan_type,
            refresh_policy=refresh_policy,
            start_date=DATA_START_DATE,
            logger=logger,
        )

    summary = dict(plan["summary"])
    summary["queued_count"] = len(plan["codes"])
    summary["total"] = len(plan["codes"])
    summary["scan_type"] = scan_type
    summary["refresh_policy"] = refresh_policy
    summary["scope"] = scope
    summary["code_source"] = code_source
    summary["strategy_meta"] = build_strategy_meta(start_date=DATA_START_DATE)

    batch_size = max(1, int(getattr(scan_job_manager, "batch_size", 1) or 1))
    total = int(summary["total"] or 0)
    summary["batch_size"] = batch_size
    summary["batch_count"] = (total + batch_size - 1) // batch_size if total else 0
    summary["batch_delay_seconds"] = float(getattr(scan_job_manager, "batch_delay", 0) or 0)
    summary["request_delay_seconds"] = float(getattr(scan_job_manager, "request_delay", 0) or 0)
    summary["resume_supported"] = bool(code_source == "legacy_strategy" and refresh_policy == "auto")
    summary["resume_note"] = "停止后再次重算会继续剩余旧策略快照" if summary["resume_supported"] else ""
    return plan, summary, force_refresh
