"""Scan workspace, cache, and job API handlers."""

import time

from flask import request

from stock_analyzer import catalog, scan_snapshot
from stock_analyzer.backtest import ENTRY_MODEL_EVENT_CLOSE, ENTRY_MODELS
from stock_analyzer.profile_relations import (
    attach_profile_relations,
    build_profile_relation_cache,
    read_profile_relation_evidence,
)
from stock_analyzer.scan_common import result_concepts
from stock_analyzer.scan_workspace_candidates import filter_workspace_candidates
from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache, get_cached_scan_workspace
from stock_analyzer.scan_workspace_persistent_cache import (
    get_cached_compact_workspace_response,
    put_cached_compact_workspace_response,
    scan_workspace_dependency_fingerprint,
)
from stock_analyzer.scan_workspace_response import compact_scan_result, compact_workspace_response
from stock_analyzer.scanner import normalize_scan_type


SCAN_JOB_RESULTS_API_LIMIT = 1000


def _truthy(value):
    return str(value or "").lower() in {"1", "true", "yes", "y"}


def _falsy(value):
    return str(value or "").lower() in {"0", "false", "no", "n"}


def _workspace_limit(value, default=120, maximum=6000):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, maximum))


def _include_replay(default=True):
    if _truthy(request.args.get("lite")):
        return False
    raw_value = request.args.get("include_replay")
    if raw_value is None:
        return default
    return _truthy(raw_value)


def _lite_load(default=False):
    raw_value = request.args.get("lite")
    if raw_value is None:
        return default
    if _falsy(raw_value):
        return False
    return _truthy(raw_value)


def _entry_model():
    value = request.args.get("entry_model") or ENTRY_MODEL_EVENT_CLOSE
    if value in ENTRY_MODELS:
        return value
    return ENTRY_MODEL_EVENT_CLOSE


def scan_workspace_response(jsonify, collect_scan_workspace_func, start_date, logger):
    try:
        snapshot_day = request.args.get("snapshot_day") or None
        force_refresh = _truthy(request.args.get("refresh"))
        max_items = _workspace_limit(request.args.get("limit"))
        lite_load = _lite_load(default=False)
        active_scan_type = normalize_scan_type(request.args.get("active_type")) if request.args.get("active_type") else None
        if lite_load and not active_scan_type:
            active_scan_type = "opportunity"
        include_replay = _include_replay(default=True)
        replay_entry_model = _entry_model()
        overview_limit = _workspace_limit(request.args.get("overview_limit"), default=80, maximum=1000) if lite_load else None
        pool_stats_limit = _workspace_limit(request.args.get("pool_stats_limit"), default=80, maximum=1000) if lite_load else None
        key = (
            start_date,
            snapshot_day or "",
            max_items,
            include_replay,
            replay_entry_model,
            not lite_load,
            overview_limit or "",
            pool_stats_limit or "",
            lite_load,
            str(scan_snapshot.SNAPSHOT_DIR),
            str(catalog.CATALOG_CACHE_DIR),
        )
        def build_workspace():
            return get_cached_scan_workspace(
                key,
                lambda: collect_scan_workspace_func(
                    start_date=start_date,
                    max_items=max_items,
                    logger=logger,
                    snapshot_day=snapshot_day,
                    include_replay=include_replay,
                    replay_entry_model=replay_entry_model,
                    include_market_universe=not lite_load,
                    include_market_breadth=not lite_load,
                    overview_limit=overview_limit,
                    pool_stats_limit=pool_stats_limit,
                    latest_only=lite_load,
                ),
                force_refresh=force_refresh,
            )

        if lite_load:
            def persistent_key_for(pool_type):
                return (
                    "scan_workspace_lite",
                    start_date,
                    snapshot_day or "",
                    max_items,
                    pool_type or "",
                    replay_entry_model,
                    overview_limit or "",
                    pool_stats_limit or "",
                    str(scan_snapshot.SNAPSHOT_DIR),
                    str(catalog.CATALOG_CACHE_DIR),
                )

            fingerprint = scan_workspace_dependency_fingerprint(start_date=start_date)

            def build_compact_workspace():
                raw_workspace = build_workspace()
                active_compact = compact_workspace_response(raw_workspace, active_scan_type=active_scan_type)
                for pool_type in (raw_workspace.get("pools") or {}):
                    if pool_type == active_scan_type:
                        continue
                    put_cached_compact_workspace_response(
                        persistent_key_for(pool_type),
                        fingerprint,
                        compact_workspace_response(raw_workspace, active_scan_type=pool_type),
                    )
                return active_compact

            workspace = get_cached_compact_workspace_response(
                persistent_key_for(active_scan_type),
                fingerprint,
                build_compact_workspace,
                force_refresh=force_refresh,
            )
        else:
            workspace = build_workspace()
        return jsonify(workspace)
    except Exception as exc:
        print(f"[扫描工作区] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def _candidate_event_date(result):
    if not isinstance(result, dict):
        return ""
    return str(result.get("event_date") or result.get("date") or "")


def _direct_candidate_detail_payload(code, scan_type, start_date, snapshot_day=None, event_date="", logger=None):
    snapshot = None
    if snapshot_day:
        snapshot = scan_snapshot.read_scan_snapshot(
            code,
            start_date=start_date,
            snapshot_day=snapshot_day,
            logger=logger,
        )
    else:
        snapshot = scan_snapshot.read_latest_scan_snapshot(
            code,
            start_date=start_date,
            logger=logger,
            require_current_strategy=False,
        )
    result = scan_snapshot.scan_result_from_snapshot(snapshot, scan_type) if snapshot else None
    if event_date and _candidate_event_date(result) != str(event_date):
        result = None
    if result:
        relation_evidence = read_profile_relation_evidence(cache_dir=catalog.CATALOG_CACHE_DIR)
        profile_cache = build_profile_relation_cache(catalog.get_cached_stock_profiles(), relation_evidence)
        profile = profile_cache.get(code, {}) if isinstance(profile_cache, dict) else {}
        result["name"] = result.get("name") or profile.get("name") or snapshot.get("name") or code
        result["sector"] = result.get("sector") or snapshot.get("sector") or profile.get("sector") or ""
        result["concepts"] = result_concepts(result) or result_concepts(snapshot) or result_concepts(profile)
        attach_profile_relations(
            result,
            profile,
            verified_date=snapshot.get("data_date"),
            relation_evidence=relation_evidence.get(code, []),
        )
    results = [result] if result else []
    latest_snapshot_day = scan_snapshot.display_snapshot_day(snapshot.get("snapshot_day")) if snapshot else None
    latest_data_date = snapshot.get("data_date") if snapshot else None
    return {
        "scan_type": scan_type,
        "filters": {
            "sector": "",
            "concept": "",
            "query": "",
            "reason": "",
            "code": code or "",
            "event_date": event_date or "",
        },
        "offset": 0,
        "limit": 1,
        "count": len(results),
        "loaded_count": len(results),
        "has_more": False,
        "pool_count": len(results),
        "results": results,
        "latest_snapshot_day": latest_snapshot_day,
        "latest_data_date": latest_data_date,
        "history_mode": bool(snapshot_day),
        "history_snapshot_day": scan_snapshot.normalize_snapshot_day(snapshot_day),
    }


def scan_workspace_candidates_response(jsonify, collect_scan_workspace_func, start_date, logger):
    try:
        snapshot_day = request.args.get("snapshot_day") or None
        force_refresh = _truthy(request.args.get("refresh"))
        scan_type = normalize_scan_type(request.args.get("scan_type") or "opportunity")
        sector = request.args.get("sector") or ""
        concept = request.args.get("concept") or ""
        query = request.args.get("query") or ""
        code = request.args.get("code") or ""
        event_date = request.args.get("event_date") or ""
        reason = request.args.get("reason") or ""
        lite_load = _lite_load(default=True)
        detail_load = _truthy(request.args.get("detail"))
        compact_load = lite_load and not detail_load and not _falsy(request.args.get("compact"))
        include_replay = _include_replay(default=True)
        replay_entry_model = _entry_model()
        if lite_load and request.args.get("include_replay") is None:
            include_replay = False
        pool_stats_limit = 1 if lite_load else None
        limit = _workspace_limit(request.args.get("limit"))
        try:
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0
        if detail_load and code and not any((sector, concept, query, reason)) and limit == 1 and offset == 0:
            started_at = time.perf_counter()
            payload = _direct_candidate_detail_payload(
                code,
                scan_type,
                start_date,
                snapshot_day=snapshot_day,
                event_date=event_date,
                logger=logger,
            )
            if _truthy(request.args.get("profile")):
                payload["performance"] = {
                    "mode": "detail_snapshot",
                    "entry_model": replay_entry_model,
                    "workspace_seconds": 0.0,
                    "filter_seconds": 0.0,
                    "total_seconds": round(time.perf_counter() - started_at, 4),
                }
            return jsonify(payload)
        key = (
            start_date,
            snapshot_day or "",
            6000,
            include_replay,
            replay_entry_model,
            not lite_load,
            pool_stats_limit or "",
            lite_load,
            str(scan_snapshot.SNAPSHOT_DIR),
            str(catalog.CATALOG_CACHE_DIR),
        )
        started_at = time.perf_counter()
        workspace = get_cached_scan_workspace(
            key,
            lambda: collect_scan_workspace_func(
                start_date=start_date,
                max_items=6000,
                logger=logger,
                snapshot_day=snapshot_day,
                include_replay=include_replay,
                replay_entry_model=replay_entry_model,
                include_market_universe=not lite_load,
                include_market_breadth=not lite_load,
                pool_stats_limit=pool_stats_limit,
                latest_only=lite_load,
            ),
            force_refresh=force_refresh,
        )
        workspace_elapsed = time.perf_counter() - started_at
        filter_started_at = time.perf_counter()
        payload = filter_workspace_candidates(
            workspace,
            scan_type=scan_type,
            sector=sector,
            concept=concept,
            query=query,
            reason=reason,
            code=code,
            event_date=event_date,
            limit=limit,
            offset=offset,
            compact_result_func=compact_scan_result if compact_load else None,
        )
        filter_elapsed = time.perf_counter() - filter_started_at
        if _truthy(request.args.get("profile")):
            payload["performance"] = {
                "mode": "lite" if lite_load else "full",
                "entry_model": replay_entry_model,
                "workspace_seconds": round(workspace_elapsed, 4),
                "filter_seconds": round(filter_elapsed, 4),
                "total_seconds": round(time.perf_counter() - started_at, 4),
            }
        return jsonify(payload)
    except Exception as exc:
        print(f"[扫描候选] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def scan_history_response(jsonify, list_scan_history_func, start_date, logger):
    try:
        limit = int(request.args.get("limit", 30))
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 120))
    try:
        return jsonify(list_scan_history_func(
            start_date=start_date,
            limit=limit,
            logger=logger,
            force_refresh=_truthy(request.args.get("refresh")),
        ))
    except Exception as exc:
        print(f"[扫描历史] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def scan_cache_status_response(jsonify, scan_cache_status_func, start_date, logger):
    try:
        return jsonify(scan_cache_status_func(start_date=start_date, logger=logger))
    except Exception as exc:
        print(f"[扫描缓存] 状态异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def prune_scan_cache_response(jsonify, prune_scan_cache_func, scan_cache_status_func, start_date, logger):
    try:
        data = request.get_json(silent=True) or {}
        delete_obsolete_strategy = bool(
            data.get("delete_obsolete_strategy")
            or request.args.get("delete_obsolete_strategy") in {"1", "true", "yes"}
        )
        result = prune_scan_cache_func(
            start_date=start_date,
            logger=logger,
            delete_obsolete_strategy=delete_obsolete_strategy,
        )
        clear_scan_workspace_cache()
        result["status"] = scan_cache_status_func(start_date=start_date, logger=logger)
        return jsonify(result)
    except Exception as exc:
        print(f"[扫描缓存] 清理异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def scan_plan_response(jsonify, build_scan_request_plan_func):
    try:
        data = request.get_json(silent=True) or {}
        _, summary, _ = build_scan_request_plan_func(data)
        return jsonify(summary)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"[扫描计划] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def start_scan_job_response(jsonify, build_scan_request_plan_func, scan_job_manager, check_stock_signal_func):
    try:
        data = request.get_json(silent=True) or {}
        plan, summary, force_refresh = build_scan_request_plan_func(data)
        clear_scan_workspace_cache()
        job = scan_job_manager.start_job(
            plan["codes"],
            summary["scan_type"],
            check_stock_signal_func,
            force_refresh=force_refresh,
            refresh_policy=summary["refresh_policy"],
            plan_summary=summary,
        )
        return jsonify(job), 202
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"[扫描任务] 启动异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def list_scan_jobs_response(jsonify, scan_job_manager):
    try:
        limit = int(request.args.get("limit", 12))
    except (TypeError, ValueError):
        limit = 12
    limit = max(1, min(limit, 50))
    return jsonify({"jobs": scan_job_manager.list_jobs(limit=limit)})


def scan_job_response(jsonify, scan_job_manager, job_id):
    include_results = _truthy(request.args.get("include_results"))
    job = scan_job_manager.get_job(job_id, include_results=include_results)
    if job is None:
        return jsonify({"error": "扫描任务不存在"}), 404
    results = job.get("results") or []
    if not include_results:
        # Progress polling only needs counters; returning full results made the
        # response grow linearly with every matched stock during market scans.
        job["results"] = []
        job["results_omitted"] = True
    elif len(results) > SCAN_JOB_RESULTS_API_LIMIT:
        job["results"] = results[-SCAN_JOB_RESULTS_API_LIMIT:]
        job["results_truncated"] = True
    return jsonify(job)


def cancel_scan_job_response(jsonify, scan_job_manager, job_id):
    job = scan_job_manager.cancel_job(job_id)
    if job is None:
        return jsonify({"error": "扫描任务不存在"}), 404
    return jsonify(job)
