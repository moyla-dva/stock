"""Scan workspace, cache, and job API handlers."""

import hashlib
import json
import logging
import time
from pathlib import Path

from flask import request

from stock_analyzer.catalog_stock_list import StockUniverseUnavailable

from stock_analyzer import catalog, scan_snapshot
from stock_analyzer.backtest import ENTRY_MODEL_EVENT_CLOSE, ENTRY_MODELS
from stock_analyzer.candidate_detail_read_model import CandidateDetail
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.profile_relations import (
    attach_profile_relations,
    build_profile_relation_cache,
    read_profile_relation_evidence,
)
from stock_analyzer.scan_common import result_concepts
from stock_analyzer.scan_snapshot_archive import read_scan_snapshot_bytes
from stock_analyzer.scan_workspace_candidates import filter_workspace_candidates
from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache, get_cached_scan_workspace
from stock_analyzer.scan_workspace_persistent_cache import (
    get_cached_compact_workspace_response,
    put_cached_compact_workspace_response,
    scan_workspace_dependency_fingerprint,
)
from stock_analyzer.scan_workspace_response import compact_scan_result, compact_workspace_response
from stock_analyzer.scanner import normalize_scan_type
from stock_analyzer.versioning import SCAN_STRATEGY_VERSION

LOGGER = logging.getLogger(__name__)


SCAN_JOB_RESULTS_API_LIMIT = 1000
LITE_WORKSPACE_CACHE_ITEMS = 6000
LITE_WORKSPACE_OVERVIEW_LIMIT = 80
LITE_WORKSPACE_POOL_STATS_LIMIT = 80


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


def _scan_index_health_summary(status):
    return {
        key: status.get(key)
        for key in (
            "build_scope",
            "index_complete",
            "snapshot_count",
            "valid_snapshot_count",
            "invalid_snapshot_count",
            "reason_tags_complete",
            "latest_snapshot_day",
        )
    }


def _scan_index_readiness_error(status, *, require_reason_tags=False):
    health = _scan_index_health_summary(status)
    if not int(health.get("snapshot_count") or 0):
        return {
            "code": "scan_index_not_ready",
            "message": "候选索引尚无可读扫描快照，不能据此判断没有候选。",
            "retryable": True,
            "details": {"index_health": health},
        }
    if not health.get("index_complete") or (
        require_reason_tags and not health.get("reason_tags_complete")
    ):
        return {
            "code": "scan_index_incomplete",
            "message": "候选索引尚未完整构建，暂不返回可能不完整的候选结果。",
            "retryable": True,
            "details": {"index_health": health},
        }
    return None


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


def _scan_workspace_cache_key(
    start_date,
    snapshot_day,
    max_items,
    replay_entry_model,
    lite_load,
    overview_limit=None,
    pool_stats_limit=None,
    include_history_comparison=True,
):
    return (
        start_date,
        snapshot_day or "",
        max_items,
        replay_entry_model,
        overview_limit or "",
        pool_stats_limit or "",
        lite_load,
        bool(snapshot_day and include_history_comparison),
        str(scan_snapshot.SNAPSHOT_DIR),
        str(catalog.CATALOG_CACHE_DIR),
    )


def _limit_workspace_pool_results(workspace, max_items, active_scan_type=None):
    if not isinstance(workspace, dict):
        return workspace
    try:
        max_items = int(max_items)
    except (TypeError, ValueError):
        return workspace
    if max_items <= 0:
        return workspace
    for pool_key, pool in (workspace.get("pools") or {}).items():
        if active_scan_type and pool_key != active_scan_type:
            continue
        results = pool.get("results")
        if not isinstance(results, list):
            continue
        total = int(pool.get("count") or len(results))
        pool["count"] = total
        pool["max_items"] = max_items
        pool["results"] = results[:max_items]
        pool["loaded_count"] = len(pool["results"])
        pool["has_more"] = pool["loaded_count"] < total
    if "max_items" in workspace:
        workspace["max_items"] = max_items
    return workspace


def scan_workspace_response(
    jsonify,
    collect_scan_workspace_func,
    start_date,
    logger,
    *,
    index_store=None,
):
    try:
        snapshot_day = request.args.get("snapshot_day") or None
        force_refresh = _truthy(request.args.get("refresh"))
        max_items = _workspace_limit(request.args.get("limit"))
        lite_load = _lite_load(default=False)
        active_scan_type = normalize_scan_type(request.args.get("active_type")) if request.args.get("active_type") else None
        if lite_load and not active_scan_type:
            active_scan_type = "opportunity"
        replay_entry_model = _entry_model()
        overview_limit = _workspace_limit(request.args.get("overview_limit"), default=80, maximum=1000) if lite_load else None
        pool_stats_limit = _workspace_limit(request.args.get("pool_stats_limit"), default=80, maximum=1000) if lite_load else None
        workspace_cache_items = LITE_WORKSPACE_CACHE_ITEMS if lite_load else max_items
        key = _scan_workspace_cache_key(
            start_date,
            snapshot_day,
            workspace_cache_items,
            replay_entry_model,
            lite_load,
            overview_limit=overview_limit,
            pool_stats_limit=pool_stats_limit,
            include_history_comparison=True,
        )
        def build_workspace():
            return get_cached_scan_workspace(
                key,
                lambda: collect_scan_workspace_func(
                    start_date=start_date,
                    max_items=workspace_cache_items,
                    logger=logger,
                    snapshot_day=snapshot_day,
                    replay_entry_model=replay_entry_model,
                    include_history_comparison=True,
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
                    workspace_cache_items,
                    pool_type or "",
                    replay_entry_model,
                    overview_limit or "",
                    pool_stats_limit or "",
                    bool(snapshot_day),
                    str(scan_snapshot.SNAPSHOT_DIR),
                    str(catalog.CATALOG_CACHE_DIR),
                )

            fingerprint = scan_workspace_dependency_fingerprint(
                start_date=start_date,
                index_store=index_store,
            )

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
            _limit_workspace_pool_results(workspace, max_items, active_scan_type=active_scan_type)
        else:
            workspace = build_workspace()
        return jsonify(workspace)
    except Exception as exc:
        LOGGER.debug("扫描工作区异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def _candidate_event_date(result):
    if not isinstance(result, dict):
        return ""
    return str(result.get("event_date") or result.get("date") or "")


def _enrich_candidate_profile(result, snapshot, code):
    if not isinstance(result, dict):
        return result
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
    return result


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
        _enrich_candidate_profile(result, snapshot, code)
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
        replay_entry_model = _entry_model()
        overview_limit = LITE_WORKSPACE_OVERVIEW_LIMIT if lite_load else None
        pool_stats_limit = LITE_WORKSPACE_POOL_STATS_LIMIT if lite_load else None
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
        workspace_cache_items = LITE_WORKSPACE_CACHE_ITEMS
        key = _scan_workspace_cache_key(
            start_date,
            snapshot_day,
            workspace_cache_items,
            replay_entry_model,
            lite_load,
            overview_limit=overview_limit,
            pool_stats_limit=pool_stats_limit,
            include_history_comparison=False,
        )
        started_at = time.perf_counter()
        workspace = get_cached_scan_workspace(
            key,
            lambda: collect_scan_workspace_func(
                start_date=start_date,
                max_items=workspace_cache_items,
                logger=logger,
                snapshot_day=snapshot_day,
                replay_entry_model=replay_entry_model,
                overview_limit=overview_limit,
                pool_stats_limit=pool_stats_limit,
                latest_only=lite_load,
                include_history_comparison=False,
            ),
            force_refresh=force_refresh,
            copy_payload=False,
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
        LOGGER.debug("扫描候选异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def scan_index_candidates_response(jsonify, index_store, start_date, logger):
    """Return a CandidateSummary page backed only by the SQLite index."""

    try:
        raw_snapshot_day = request.args.get("snapshot_day") or ""
        snapshot_day = scan_snapshot.normalize_snapshot_day(raw_snapshot_day) or None
        if raw_snapshot_day and not snapshot_day:
            raise ValueError("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
        scan_type = normalize_scan_type(request.args.get("scan_type") or "opportunity")
        limit = _workspace_limit(request.args.get("limit"), default=120, maximum=1000)
        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        start_key = "".join(character for character in str(start_date) if character.isdigit())
        requested_strategy = request.args.get("strategy_version")
        reason = request.args.get("reason") or ""
        requested_rank_mode = str(request.args.get("rank_mode") or "snapshot_local").strip().lower()
        strategy_filter = requested_strategy or (None if snapshot_day else SCAN_STRATEGY_VERSION)
        index_health = _scan_index_health_summary(index_store.status())
        readiness_error = _scan_index_readiness_error(
            index_health,
            require_reason_tags=bool(reason),
        )
        if readiness_error:
            return jsonify({"error": readiness_error}), 503
        page = index_store.query_candidate_page(
            pool=scan_type,
            snapshot_day=snapshot_day,
            strategy_version=strategy_filter,
            rank_context_strategy_version=requested_strategy or SCAN_STRATEGY_VERSION,
            start_key=start_key,
            sector=request.args.get("sector") or "",
            concept=request.args.get("concept") or "",
            signal_key=request.args.get("signal_key") or "",
            reason=reason,
            query=request.args.get("query") or "",
            limit=limit,
            offset=offset,
            rank_mode=requested_rank_mode,
            recent_only=not bool(snapshot_day),
        )
        resolved_snapshot_day = page.pop("snapshot_day", "")
        history_snapshot_day = page.get("history_snapshot_day") or ""
        page["latest_snapshot_day"] = (
            scan_snapshot.display_snapshot_day(resolved_snapshot_day)
            if resolved_snapshot_day
            else None
        )
        page["history_snapshot_day"] = (
            scan_snapshot.display_snapshot_day(history_snapshot_day)
            if history_snapshot_day
            else None
        )
        page["index_health"] = index_health
        return jsonify(page)
    except ValueError as exc:
        return jsonify({
            "error": {
                "code": "invalid_scan_index_query",
                "message": str(exc),
                "retryable": False,
                "details": {},
            }
        }), 400
    except Exception:
        logger.exception("SQLite 候选索引查询失败")
        return jsonify({
            "error": {
                "code": "scan_index_unavailable",
                "message": "候选索引暂不可用，现有工作区接口未受影响。",
                "retryable": True,
                "details": {},
            }
        }), 503


def scan_index_status_response(jsonify, index_store, logger):
    try:
        return jsonify(index_store.status())
    except Exception:
        logger.exception("SQLite 候选索引状态查询失败")
        return jsonify({
            "error": {
                "code": "scan_index_unavailable",
                "message": "候选索引暂不可用。",
                "retryable": True,
                "details": {},
            }
        }), 503


def scan_index_candidate_detail_response(
    jsonify,
    index_store,
    start_date,
    logger,
    code,
):
    """Read one exact candidate snapshot and project a stable CandidateDetail."""

    normalized_code = normalize_code(code)
    if not normalized_code:
        return jsonify({
            "error": {
                "code": "invalid_stock_code",
                "message": "请提供 6 位股票代码。",
                "retryable": False,
                "details": {},
            }
        }), 400
    try:
        raw_snapshot_day = request.args.get("snapshot_day") or ""
        snapshot_day = scan_snapshot.normalize_snapshot_day(raw_snapshot_day) or None
        if raw_snapshot_day and not snapshot_day:
            raise ValueError("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
        scan_type = normalize_scan_type(request.args.get("scan_type") or "opportunity")
        index_health = _scan_index_health_summary(index_store.status())
        readiness_error = _scan_index_readiness_error(index_health)
        if readiness_error:
            return jsonify({"error": readiness_error}), 503
        start_key = "".join(character for character in str(start_date) if character.isdigit())
        requested_strategy = request.args.get("strategy_version")
        strategy_filter = (
            requested_strategy
            if requested_strategy
            else (None if snapshot_day else SCAN_STRATEGY_VERSION)
        )
        reference = index_store.get_candidate_reference(
            pool=scan_type,
            code=normalized_code,
            snapshot_day=snapshot_day,
            strategy_version=strategy_filter,
            start_key=start_key,
            event_date=request.args.get("event_date") or "",
        )
        if reference is None:
            return jsonify({
                "error": {
                    "code": "candidate_not_found",
                    "message": "指定快照中没有找到该候选。",
                    "retryable": False,
                    "details": {
                        "code": normalized_code,
                        "scan_type": scan_type,
                        "snapshot_day": snapshot_day or "latest",
                    },
                }
            }), 404

        snapshot_path = Path(reference["snapshot_path"])
        raw = read_scan_snapshot_bytes(
            snapshot_path,
            archive_path=reference.get("archive_path") or None,
        )
        actual_revision = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        expected_revision = str(reference["summary"].get("snapshot_revision") or "")
        if expected_revision and actual_revision != expected_revision:
            return jsonify({
                "error": {
                    "code": "snapshot_revision_mismatch",
                    "message": "快照已变更，需先刷新 SQLite 索引。",
                    "retryable": True,
                    "details": {
                        "code": normalized_code,
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                }
            }), 409
        snapshot = json.loads(raw.decode("utf-8"))
        if not snapshot_day and not scan_snapshot.is_recent_snapshot(snapshot):
            return jsonify({
                "error": {
                    "code": "candidate_not_found",
                    "message": "最新工作区中没有找到该候选。",
                    "retryable": False,
                    "details": {
                        "code": normalized_code,
                        "scan_type": scan_type,
                        "snapshot_day": "latest",
                    },
                }
            }), 404
        detail = CandidateDetail.from_snapshot(reference["summary"], snapshot, scan_type)
        if detail is None:
            return jsonify({
                "error": {
                    "code": "candidate_snapshot_inconsistent",
                    "message": "索引候选与原始快照不一致。",
                    "retryable": True,
                    "details": {"code": normalized_code, "scan_type": scan_type},
                }
            }), 409
        payload = detail.to_dict()
        snapshot_result = scan_snapshot.scan_result_from_snapshot(snapshot, scan_type)
        enriched_result = _enrich_candidate_profile(snapshot_result, snapshot, normalized_code)
        if enriched_result:
            payload["profile"].update({
                key: enriched_result[key]
                for key in (
                    "name",
                    "sector",
                    "concepts",
                    "profile_relation_count",
                    "profile_relation_group_summary",
                    "profile_relation_groups",
                )
                if key in enriched_result
            })
        return jsonify(payload)
    except (OSError, json.JSONDecodeError):
        logger.exception("SQLite 候选详情快照读取失败: %s", normalized_code)
        return jsonify({
            "error": {
                "code": "candidate_snapshot_unavailable",
                "message": "候选原始快照暂不可用。",
                "retryable": True,
                "details": {"code": normalized_code},
            }
        }), 503
    except ValueError as exc:
        return jsonify({
            "error": {
                "code": "invalid_scan_index_query",
                "message": str(exc),
                "retryable": False,
                "details": {},
            }
        }), 400
    except Exception:
        logger.exception("SQLite 候选详情查询失败: %s", normalized_code)
        return jsonify({
            "error": {
                "code": "candidate_detail_unavailable",
                "message": "候选详情暂不可用。",
                "retryable": True,
                "details": {"code": normalized_code},
            }
        }), 503


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
        LOGGER.debug("扫描历史异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def scan_cache_status_response(jsonify, scan_cache_status_func, start_date, logger):
    try:
        return jsonify(scan_cache_status_func(start_date=start_date, logger=logger))
    except Exception as exc:
        LOGGER.debug("扫描缓存状态异常: %s", exc, exc_info=True)
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
        LOGGER.debug("扫描缓存清理异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def scan_plan_response(jsonify, build_scan_request_plan_func):
    try:
        data = request.get_json(silent=True) or {}
        _, summary, _ = build_scan_request_plan_func(data)
        return jsonify(summary)
    except StockUniverseUnavailable as exc:
        return jsonify({
            "error": str(exc),
            "code": "stock_universe_unavailable",
            "retryable": True,
        }), 503
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        LOGGER.debug("扫描计划异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def start_scan_job_response(jsonify, build_scan_request_plan_func, scan_job_manager, check_stock_signal_func):
    try:
        data = request.get_json(silent=True) or {}
        plan, summary, force_refresh = build_scan_request_plan_func(data)
        clear_scan_workspace_cache()

        def scan_one_with_quality(code, scan_type, force, refresh_policy):
            return check_stock_signal_func(
                code,
                scan_type,
                force,
                refresh_policy,
                return_outcome=True,
            )

        job = scan_job_manager.start_job(
            plan["codes"],
            summary["scan_type"],
            scan_one_with_quality,
            force_refresh=force_refresh,
            refresh_policy=summary["refresh_policy"],
            plan_summary=summary,
        )
        return jsonify(job), 202
    except StockUniverseUnavailable as exc:
        return jsonify({
            "error": str(exc),
            "code": "stock_universe_unavailable",
            "retryable": True,
        }), 503
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        LOGGER.debug("扫描任务启动异常: %s", exc, exc_info=True)
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
