"""Scan workspace, cache, and job API handlers."""

from flask import request

from stock_analyzer import catalog, scan_snapshot
from stock_analyzer.scan_workspace_candidates import filter_workspace_candidates
from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache, get_cached_scan_workspace


def _truthy(value):
    return str(value or "").lower() in {"1", "true", "yes", "y"}


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


def scan_workspace_response(jsonify, collect_scan_workspace_func, start_date, logger):
    try:
        snapshot_day = request.args.get("snapshot_day") or None
        force_refresh = _truthy(request.args.get("refresh"))
        max_items = _workspace_limit(request.args.get("limit"))
        lite_load = _truthy(request.args.get("lite"))
        include_replay = _include_replay(default=True)
        overview_limit = _workspace_limit(request.args.get("overview_limit"), default=80, maximum=1000) if lite_load else None
        pool_stats_limit = _workspace_limit(request.args.get("pool_stats_limit"), default=80, maximum=1000) if lite_load else None
        key = (
            start_date,
            snapshot_day or "",
            max_items,
            include_replay,
            not lite_load,
            not lite_load,
            overview_limit or "",
            pool_stats_limit or "",
            lite_load,
            str(scan_snapshot.SNAPSHOT_DIR),
            str(catalog.CATALOG_CACHE_DIR),
        )
        workspace = get_cached_scan_workspace(
            key,
            lambda: collect_scan_workspace_func(
                start_date=start_date,
                max_items=max_items,
                logger=logger,
                snapshot_day=snapshot_day,
                include_replay=include_replay,
                include_market_universe=not lite_load,
                include_market_breadth=not lite_load,
                overview_limit=overview_limit,
                pool_stats_limit=pool_stats_limit,
                latest_only=lite_load,
            ),
            force_refresh=force_refresh,
        )
        return jsonify(workspace)
    except Exception as exc:
        print(f"[扫描工作区] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def scan_workspace_candidates_response(jsonify, collect_scan_workspace_func, start_date, logger):
    try:
        snapshot_day = request.args.get("snapshot_day") or None
        force_refresh = _truthy(request.args.get("refresh"))
        scan_type = request.args.get("scan_type") or "opportunity"
        sector = request.args.get("sector") or ""
        concept = request.args.get("concept") or ""
        query = request.args.get("query") or ""
        lite_load = _truthy(request.args.get("lite"))
        include_replay = _include_replay(default=True)
        pool_stats_limit = 1 if lite_load else None
        limit = _workspace_limit(request.args.get("limit"))
        try:
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0
        key = (
            start_date,
            snapshot_day or "",
            6000,
            include_replay,
            not lite_load,
            not lite_load,
            pool_stats_limit or "",
            lite_load,
            str(scan_snapshot.SNAPSHOT_DIR),
            str(catalog.CATALOG_CACHE_DIR),
        )
        workspace = get_cached_scan_workspace(
            key,
            lambda: collect_scan_workspace_func(
                start_date=start_date,
                max_items=6000,
                logger=logger,
                snapshot_day=snapshot_day,
                include_replay=include_replay,
                include_market_universe=not lite_load,
                include_market_breadth=not lite_load,
                pool_stats_limit=pool_stats_limit,
                latest_only=lite_load,
            ),
            force_refresh=force_refresh,
        )
        return jsonify(filter_workspace_candidates(
            workspace,
            scan_type=scan_type,
            sector=sector,
            concept=concept,
            query=query,
            limit=limit,
            offset=offset,
        ))
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
        return jsonify(list_scan_history_func(start_date=start_date, limit=limit, logger=logger))
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
    job = scan_job_manager.get_job(job_id)
    if job is None:
        return jsonify({"error": "扫描任务不存在"}), 404
    return jsonify(job)


def cancel_scan_job_response(jsonify, scan_job_manager, job_id):
    job = scan_job_manager.cancel_job(job_id)
    if job is None:
        return jsonify({"error": "扫描任务不存在"}), 404
    return jsonify(job)
