# -*- coding: utf-8 -*-
"""Scan decision and planning services."""

from dataclasses import dataclass

from stock_analyzer.catalog import get_stock_codes, get_stock_profile
from stock_analyzer.market_data_identity import frame_market_data_identity
from stock_analyzer.scan_planner import (
    legacy_strategy_snapshot_codes,
    plan_scan_codes,
)
from stock_analyzer.scan_snapshot_policy import normalize_refresh_policy, scan_snapshot_status
from stock_analyzer.scanner import format_scan_date, normalize_scan_type
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
from stock_analyzer.stock_service import (
    enrich_scan_result_with_profile,
    get_stock_dataframe,
    get_stock_dataframe_with_diagnostics,
)
from stock_analyzer.versioning import DATA_START_DATE, build_strategy_meta


@dataclass(frozen=True)
class ScanCheckOutcome:
    result: dict | None
    data_quality: dict


def _quality_from_snapshot(snapshot, status="available"):
    return {
        "status": status,
        "data_date": str(snapshot.get("data_date") or "") if isinstance(snapshot, dict) else "",
        "bar_state": str(snapshot.get("bar_state") or "unknown") if isinstance(snapshot, dict) else "unknown",
        "data_source": str(snapshot.get("data_source") or "unknown") if isinstance(snapshot, dict) else "unknown",
        "fetch_status": "scan_snapshot" if status == "available" else status,
        "cache_status": str(snapshot.get("cache_status") or "unknown") if isinstance(snapshot, dict) else "unknown",
    }


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
    return_outcome=False,
    get_stock_dataframe_outcome_func=None,
):
    """Check whether a single stock triggers the requested scan signal."""
    quality = {"status": "unknown", "data_date": "", "bar_state": "unknown", "data_source": "unknown"}
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
        quality = _quality_from_snapshot(
            snapshot,
            status=("available" if snapshot_decision.get("status") == "ready" else str(snapshot_decision.get("status") or "unknown")),
        )
        if snapshot_decision.get("status") == "ready" and snapshot:
            result = scan_result_from_snapshot_func(snapshot, scan_type)
            if result:
                enrich_result_func(result, code)
                result["scan_source"] = "cache"
            if return_outcome:
                return ScanCheckOutcome(result, quality)
            return result

        if not snapshot_decision.get("allow_compute"):
            if return_outcome:
                return ScanCheckOutcome(None, quality)
            return None

        fetch_diagnostics = {}
        if return_outcome and get_stock_dataframe_outcome_func is not None:
            df, fetch_diagnostics = get_stock_dataframe_outcome_func(code)
        else:
            df = get_stock_dataframe_func(code)
        if df is None or df.empty:
            fetch_status = str(fetch_diagnostics.get("fetch_status") or "no_data")
            quality = {
                **quality,
                "status": fetch_status if fetch_status in {
                    "provider_empty", "provider_error", "provider_partial_failure", "no_provider_result",
                } else "no_data",
                "fetch_status": fetch_status,
                "cache_status": str(fetch_diagnostics.get("cache_status") or "unknown"),
                "fetch_attempts": list(fetch_diagnostics.get("attempts") or []),
            }
            if return_outcome:
                return ScanCheckOutcome(None, quality)
            return None

        identity = frame_market_data_identity(df)
        quality = {
            "status": "available",
            "data_date": format_scan_date(df.iloc[-1].get("date")) if "date" in df.columns else "",
            "bar_state": str(identity.get("bar_state") or "unknown"),
            "data_source": str(identity.get("data_source") or "unknown"),
            "fetch_status": str(fetch_diagnostics.get("fetch_status") or "available"),
            "cache_status": str(identity.get("cache_status") or fetch_diagnostics.get("cache_status") or "unknown"),
            "fetch_attempts": list(fetch_diagnostics.get("attempts") or []),
        }

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
        quality = _quality_from_snapshot(snapshot)
        quality.update({
            "fetch_status": str(fetch_diagnostics.get("fetch_status") or "available"),
            "cache_status": str(
                frame_market_data_identity(df).get("cache_status")
                or fetch_diagnostics.get("cache_status")
                or "unknown"
            ),
            "fetch_attempts": list(fetch_diagnostics.get("attempts") or []),
        })
        if result:
            enrich_result_func(result, code, profile=profile)
            result["scan_source"] = "force" if refresh_policy == "force" else "computed"
            if return_outcome:
                return ScanCheckOutcome(result, quality)
            return result
        if return_outcome:
            return ScanCheckOutcome(None, quality)
    except Exception as exc:
        if return_outcome:
            return ScanCheckOutcome(None, {
                **quality,
                "status": "analysis_error",
                "error_type": type(exc).__name__,
            })
        return None
    return None


def build_scan_request_plan(
    data,
    *,
    scan_job_manager,
    get_stock_codes_func=get_stock_codes,
    logger=None,
    scan_index_store=None,
):
    if not isinstance(data, dict):
        raise ValueError("无效的JSON数据")
    scan_type = normalize_scan_type(data.get("scan_type") or data.get("mode", "opportunity"))
    force_refresh = bool(data.get("refresh", False))
    refresh_policy = normalize_refresh_policy(data.get("refresh_policy"), force_refresh=force_refresh)
    codes = data.get("codes")
    scope = data.get("scope") or "market"
    code_source = "market"
    universe_meta = {}
    if codes is None:
        if scope == "legacy_strategy":
            codes = legacy_strategy_snapshot_codes(
                start_date=DATA_START_DATE,
                scan_type=scan_type,
                logger=logger,
                index_store=scan_index_store,
            )
            code_source = "legacy_strategy"
        else:
            universe = get_stock_codes_func()
            if isinstance(universe, dict):
                universe_meta = universe
                codes = universe.get("codes")
            elif hasattr(universe, "codes"):
                codes = list(universe.codes)
                universe_meta = {
                    "as_of": getattr(universe, "as_of", ""),
                    "revision": getattr(universe, "revision", ""),
                    "source": getattr(universe, "source", ""),
                    "coverage_status": getattr(universe, "coverage_status", ""),
                    "calendar_revision": getattr(universe, "calendar_revision", ""),
                    "member_count": len(codes),
                }
            else:
                codes = universe
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
            index_store=scan_index_store,
        )

    summary = dict(plan["summary"])
    summary["queued_count"] = len(plan["codes"])
    summary["total"] = len(plan["codes"])
    summary["scan_type"] = scan_type
    summary["refresh_policy"] = refresh_policy
    summary["scope"] = scope
    summary["code_source"] = code_source
    if code_source == "market":
        summary.update({
            "universe_as_of": str(universe_meta.get("as_of") or ""),
            "universe_revision": str(universe_meta.get("revision") or ""),
            "universe_source": str(universe_meta.get("source") or ""),
            "universe_coverage_status": str(universe_meta.get("coverage_status") or ""),
            "universe_calendar_revision": str(universe_meta.get("calendar_revision") or ""),
            "universe_member_count": int(universe_meta.get("member_count") or len(codes)),
        })
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
