# -*- coding: utf-8 -*-
"""
A股短线结构工作台 Web版 (Flask)
功能：提供候选池、单股确认和数据后台
启动方式：./venv/bin/python app.py
访问地址：http://127.0.0.1:5009
"""
import logging  # 【新增】日志支持
import math
import os
import threading
from datetime import datetime, timedelta
from numbers import Integral, Real

from flask import Flask, render_template, request, jsonify as flask_jsonify

from stock_analyzer import catalog, scan_service, stock_service
from stock_analyzer.catalog import get_stock_name, get_stock_profile
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.concept_graph import (
    build_concept_graph,
    delete_concept_graph_edge,
    upsert_concept_graph_edge,
)
from stock_analyzer.concept_jobs import ConceptRefreshJobManager
from stock_analyzer.data_sources import collect_data_source_status
from stock_analyzer.current_universe_audit import audit_current_universe_scan
from stock_analyzer.current_universe import get_current_stock_universe
from stock_analyzer.market_metadata_store import MarketMetadataStore
from stock_analyzer.profile_relations import (
    delete_profile_relation_evidence,
    profile_relation_evidence_status,
    read_profile_relation_evidence,
    upsert_profile_relation_evidence,
)
from stock_analyzer.scan_cache import prune_scan_cache, scan_cache_status
from stock_analyzer.scan_history import list_scan_history
from stock_analyzer.scan_index_store import ScanIndexStore
from stock_analyzer.scan_jobs import ScanJobManager
from stock_analyzer.scan_rank_context_materializer import (
    materialize_workspace_rank_context,
)
from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache
from stock_analyzer.scan_snapshot import (
    build_scan_snapshot,
    is_current_strategy_snapshot,
    is_recent_snapshot,
    read_latest_scan_snapshot,
    read_scan_snapshot,
    scan_snapshot_paths_for_codes,
    scan_result_from_snapshot,
    snapshot_day_text,
    snapshot_has_scan_type,
    write_scan_snapshot,
)
from stock_analyzer.scan_workspace import collect_scan_workspace
from stock_analyzer.versioning import DATA_START_DATE, SCAN_STRATEGY_VERSION
from stock_analyzer.web import concept_api, data_api, scan_api, stock_api

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.jinja_env.auto_reload = True

# 【新增】配置日志输出到控制台
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
app.logger.setLevel(logging.INFO)


def _json_safe(value):
    """Convert Python numeric sentinels into strict JSON-compatible values."""
    if isinstance(value, dict):
        return {
            key if isinstance(key, str) else str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def jsonify(*args, **kwargs):
    """Flask jsonify wrapper that never emits NaN/Infinity."""
    safe_args = tuple(_json_safe(arg) for arg in args)
    safe_kwargs = {key: _json_safe(value) for key, value in kwargs.items()}
    return flask_jsonify(*safe_args, **safe_kwargs)

def fetch_and_process_data(code, include_legacy_chart=False, force_refresh=False):
    return stock_service.fetch_and_process_data(
        code,
        logger=app.logger,
        verbose=False,
        include_legacy_chart=include_legacy_chart,
        force_refresh=force_refresh,
    )


def fetch_multi_timeframe_data(code, period=None, force_refresh=False):
    return stock_service.fetch_multi_timeframe_data(
        code,
        logger=app.logger,
        verbose=False,
        period=period,
        force_refresh=force_refresh,
    )


scan_index_store = ScanIndexStore()
market_metadata_store = MarketMetadataStore()
_scan_index_sync_lock = threading.Lock()


def audit_scan_job_universe(job):
    """Record whether a full-market job used the current pinned universe."""
    if not isinstance(job, dict):
        return {"status": "not_applicable"}
    if job.get("scope") != "market" or job.get("code_source") != "market":
        return {"status": "not_applicable"}
    as_of = str(job.get("universe_as_of") or "")
    if not as_of:
        return {"status": "missing_job_provenance"}
    try:
        report = audit_current_universe_scan(as_of, market_metadata_store, [job])
    except Exception as exc:
        app.logger.warning("当前股票池一致性审计失败: as_of=%s, error=%s", as_of, exc)
        return {"status": "audit_error", "error": str(exc)}
    if report.get("status") != "consistent":
        app.logger.warning(
            "当前股票池一致性审计未通过: as_of=%s, status=%s",
            as_of,
            report.get("status"),
        )
    return report


def sync_scan_job_index(job, codes):
    """Index touched snapshots, then publish an optional contextual rank overlay."""

    universe_consistency = audit_scan_job_universe(job)
    current_day = datetime.strptime(snapshot_day_text(), "%Y%m%d").date()
    try:
        first_day = datetime.fromisoformat(str((job or {}).get("started_at"))).date()
    except (TypeError, ValueError):
        first_day = current_day
    first_day = min(first_day, current_day)
    first_day = max(first_day, current_day - timedelta(days=7))
    snapshot_days = []
    day = first_day
    while day <= current_day:
        snapshot_days.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    paths = scan_snapshot_paths_for_codes(
        codes,
        start_date=DATA_START_DATE,
        snapshot_days=snapshot_days,
    )
    if not paths:
        return {
            "status": "no_snapshots",
            "snapshot_count": 0,
            "universe_consistency": universe_consistency,
            "index": {"status": "skipped", "reason": "no_snapshots"},
            "rank_context": {"status": "skipped", "reason": "no_snapshots"},
        }
    with _scan_index_sync_lock:
        stats = scan_index_store.index_snapshot_files(paths)
        try:
            reconciliation = scan_index_store.reconcile_source_directory(paths[0].parent)
        except Exception as exc:
            app.logger.warning(
                "SQLite 快照存储层对账失败；继续尝试生成候选排序上下文: %s",
                exc,
            )
            reconciliation = {
                "synchronized": False,
                "status": "failed",
                "error": str(exc),
            }
        index_result = {
            "status": "indexed",
            "snapshot_count": len(paths),
            **stats.to_dict(),
            "reconciliation": reconciliation,
        }
        try:
            strategy_version = (job or {}).get("strategy_version") or SCAN_STRATEGY_VERSION
            rank_context_scopes = {}
            for context_scope in ("snapshot", "latest_fresh"):
                try:
                    rank_context_scopes[context_scope] = materialize_workspace_rank_context(
                        scan_index_store,
                        start_date=DATA_START_DATE,
                        strategy_version=strategy_version,
                        context_scope=context_scope,
                        logger=app.logger,
                    )
                except Exception as exc:
                    app.logger.warning(
                        "候选上下文排名物化失败: scope=%s, error=%s",
                        context_scope,
                        exc,
                    )
                    rank_context_scopes[context_scope] = {
                        "status": "failed",
                        "error": str(exc),
                        "fallback": "snapshot_local",
                    }
            rank_context_result = dict(
                rank_context_scopes.get("latest_fresh") or {}
            )
            rank_context_result["contexts"] = {
                scope: result.get("rank_context")
                for scope, result in rank_context_scopes.items()
            }
            current_context = rank_context_scopes.get("latest_fresh") or {}
            if (current_context.get("rank_context") or {}).get("available"):
                overall_status = "indexed"
            else:
                rank_context_result["status"] = "failed"
                rank_context_result["fallback"] = "snapshot_local"
                overall_status = "indexed_context_failed"
        except Exception as exc:
            app.logger.warning("候选上下文排名物化失败，保留快照本地排序: %s", exc)
            rank_context_result = {
                "status": "failed",
                "error": str(exc),
                "fallback": "snapshot_local",
            }
            overall_status = "indexed_context_failed"
    return {
        "status": overall_status,
        "snapshot_count": len(paths),
        "universe_consistency": universe_consistency,
        **stats.to_dict(),
        "index": index_result,
        "rank_context": rank_context_result,
    }


scan_job_manager = ScanJobManager(
    max_jobs=2,
    max_workers=5,
    batch_size=50,
    batch_delay=1.0,
    request_delay=0.05,
    completion_hook=sync_scan_job_index,
)
concept_refresh_job_manager = ConceptRefreshJobManager(max_workers=1)


def enrich_scan_result_with_profile(result, code, profile=None):
    return stock_service.enrich_scan_result_with_profile(
        result,
        code,
        profile=profile,
        get_stock_profile_func=get_stock_profile,
    )


def build_concept_graph_payload(**kwargs):
    return build_concept_graph(profile_cache=catalog.get_cached_stock_profiles(), **kwargs)


def get_stock_dataframe(code):
    """
    获取股票的原始 DataFrame（用于扫描功能）
    返回 DataFrame 或 None
    """
    return stock_service.get_stock_dataframe(code)

def get_stock_dataframe_with_diagnostics(code):
    return stock_service.get_stock_dataframe_with_diagnostics(code)

def check_stock_signal(code, scan_type='opportunity', force_refresh=False, refresh_policy=None, return_outcome=False):
    """
    检查单只股票是否触发信号
    返回: (code, name, price, has_signal)
    逻辑与图表显示逻辑保持一致：检查最新一天是否为信号
    """
    return scan_service.check_stock_signal(
        code,
        scan_type=scan_type,
        force_refresh=force_refresh,
        refresh_policy=refresh_policy,
        read_scan_snapshot_func=read_scan_snapshot,
        read_latest_scan_snapshot_func=read_latest_scan_snapshot,
        is_recent_snapshot_func=is_recent_snapshot,
        is_current_strategy_snapshot_func=is_current_strategy_snapshot,
        snapshot_has_scan_type_func=snapshot_has_scan_type,
        scan_result_from_snapshot_func=scan_result_from_snapshot,
        get_stock_dataframe_func=get_stock_dataframe,
        get_stock_dataframe_outcome_func=get_stock_dataframe_with_diagnostics,
        get_stock_profile_func=get_stock_profile,
        build_scan_snapshot_func=build_scan_snapshot,
        write_scan_snapshot_func=write_scan_snapshot,
        enrich_result_func=enrich_scan_result_with_profile,
        return_outcome=return_outcome,
    )

@app.route('/api/stock_list')
def get_stock_list():
    """返回带来源与 revision 的当前股票池名单。"""
    return stock_api.stock_list_response(jsonify, get_current_stock_universe)

@app.route('/api/scan_batch', methods=['POST'])
def scan_batch():
    """Retired synchronous batch scan endpoint. Use background scan jobs."""
    return jsonify({
        "error": "同步批扫接口已下线，请使用后台扫描任务",
        "replacement": "/api/scan_jobs",
        "status": "retired",
    }), 410

@app.route('/api/scan_workspace')
def api_scan_workspace():
    """读取本地扫描快照，恢复扫描工作区。"""
    return scan_api.scan_workspace_response(
        jsonify,
        collect_scan_workspace,
        DATA_START_DATE,
        app.logger,
        index_store=scan_index_store,
    )


@app.route('/api/scan_workspace/candidates')
def api_scan_workspace_candidates():
    """读取本地扫描快照中的目标候选，支持板块/概念/搜索过滤。"""
    return scan_api.scan_workspace_candidates_response(
        jsonify,
        collect_scan_workspace,
        DATA_START_DATE,
        app.logger,
    )


@app.route('/api/scan_index/candidates')
def api_scan_index_candidates():
    """Read the default CandidateSummary projection from SQLite."""
    return scan_api.scan_index_candidates_response(
        jsonify,
        scan_index_store,
        DATA_START_DATE,
        app.logger,
    )


@app.route('/api/scan_index/status')
def api_scan_index_status():
    """Return SQLite scan-index health without reading snapshot JSON."""
    return scan_api.scan_index_status_response(jsonify, scan_index_store, app.logger)


@app.route('/api/scan_index/candidates/<code>')
def api_scan_index_candidate_detail(code):
    """Read one stable CandidateDetail through its indexed snapshot identity."""
    return scan_api.scan_index_candidate_detail_response(
        jsonify,
        scan_index_store,
        DATA_START_DATE,
        app.logger,
        code,
    )


@app.route('/api/scan_history')
def api_scan_history():
    """List local scan snapshot days for history browsing."""
    return scan_api.scan_history_response(
        jsonify,
        lambda **kwargs: list_scan_history(index_store=scan_index_store, **kwargs),
        DATA_START_DATE,
        app.logger,
    )


@app.route('/api/scan_cache')
def api_scan_cache_status():
    """Return local scan snapshot cache size and freshness."""
    return scan_api.scan_cache_status_response(jsonify, scan_cache_status, DATA_START_DATE, app.logger)


@app.route('/api/scan_cache/prune', methods=['POST'])
def api_prune_scan_cache():
    """Delete invalid or expired local scan snapshots."""
    return scan_api.prune_scan_cache_response(
        jsonify,
        prune_scan_cache,
        scan_cache_status,
        DATA_START_DATE,
        app.logger,
    )


@app.route('/api/data_sources')
def api_data_sources():
    """Return unified local data-source/cache status."""
    return data_api.data_sources_response(
        jsonify,
        collect_data_source_status,
        DATA_START_DATE,
        app.logger,
    )

@app.route('/api/stock_profiles', methods=['POST'])
def api_stock_profiles():
    """按需补齐扫描结果中的股票名称和板块。"""
    return stock_api.stock_profiles_response(jsonify, stock_service, get_stock_profile)


@app.route('/api/stock_concepts/refresh', methods=['POST'])
def api_refresh_stock_concepts():
    """Start a background refresh for local stock concept/topic tags."""
    return concept_api.refresh_stock_concepts_response(
        jsonify,
        concept_refresh_job_manager,
        stock_service,
        app.logger,
    )


@app.route('/api/stock_concepts/status')
def api_stock_concepts_status():
    """Return local concept-cache status and the latest refresh job."""
    return concept_api.stock_concepts_status_response(
        jsonify,
        concept_refresh_job_manager,
        stock_service,
    )


@app.route('/api/stock_concepts/jobs/<job_id>')
def api_get_stock_concept_job(job_id):
    return concept_api.stock_concept_job_response(jsonify, concept_refresh_job_manager, job_id)


@app.route('/api/board_market')
def api_board_market():
    """Return an explicit retirement response for the old board-market API."""
    return jsonify({
        "error": "板块/概念行情功能已退役；行业和概念候选分布仍可在候选池查看。",
        "status": "retired",
    }), 410


@app.route('/api/board_market/refresh', methods=['POST'])
def api_refresh_board_market_cache():
    """Return an explicit retirement response for the old refresh API."""
    return jsonify({
        "error": "板块/概念行情刷新入口已退役。",
        "status": "retired",
    }), 410


@app.route('/api/profile_relations/evidence')
def api_profile_relation_evidence():
    """Return local verified stock-profile relation evidence."""
    return data_api.profile_relation_evidence_response(
        jsonify,
        read_profile_relation_evidence,
        profile_relation_evidence_status,
        catalog.CATALOG_CACHE_DIR,
    )


@app.route('/api/profile_relations/evidence', methods=['POST'])
def api_upsert_profile_relation_evidence():
    """Add or replace one local verified stock-profile relation evidence row."""
    return data_api.upsert_profile_relation_evidence_response(
        jsonify,
        upsert_profile_relation_evidence,
        clear_scan_workspace_cache,
        catalog.CATALOG_CACHE_DIR,
    )


@app.route('/api/profile_relations/evidence', methods=['DELETE'])
def api_delete_profile_relation_evidence():
    """Delete local verified stock-profile relation evidence."""
    return data_api.delete_profile_relation_evidence_response(
        jsonify,
        delete_profile_relation_evidence,
        clear_scan_workspace_cache,
        catalog.CATALOG_CACHE_DIR,
    )


@app.route('/api/concept_graph')
def api_concept_graph():
    """Return local sector/concept relation graph edges."""
    return data_api.concept_graph_response(
        jsonify,
        build_concept_graph_payload,
        catalog.CATALOG_CACHE_DIR,
    )


@app.route('/api/concept_graph/edges', methods=['POST'])
def api_upsert_concept_graph_edge():
    """Add or replace one local sector/concept graph edge."""
    return data_api.upsert_concept_graph_edge_response(
        jsonify,
        upsert_concept_graph_edge,
        clear_scan_workspace_cache,
        catalog.CATALOG_CACHE_DIR,
    )


@app.route('/api/concept_graph/edges', methods=['DELETE'])
def api_delete_concept_graph_edge():
    """Delete one or more local sector/concept graph edges."""
    return data_api.delete_concept_graph_edge_response(
        jsonify,
        delete_concept_graph_edge,
        clear_scan_workspace_cache,
        catalog.CATALOG_CACHE_DIR,
    )


def build_scan_request_plan(data):
    return scan_service.build_scan_request_plan(
        data,
        scan_job_manager=scan_job_manager,
        get_stock_codes_func=get_scan_universe_codes,
        logger=app.logger,
        scan_index_store=scan_index_store,
    )


def get_scan_universe_codes():
    """Return a revision-pinned SQLite universe for market scans."""
    return get_current_stock_universe()


def get_current_stock_codes():
    """Return codes from the revision-pinned SQLite universe."""
    return list(get_current_stock_universe().codes)


@app.route('/api/scan_plan', methods=['POST'])
def api_scan_plan():
    """预估扫描任务规模，不启动后台任务。"""
    return scan_api.scan_plan_response(jsonify, build_scan_request_plan)


@app.route('/api/scan_jobs', methods=['POST'])
def api_start_scan_job():
    """启动后台扫描任务，前端通过轮询获取进度。"""
    return scan_api.start_scan_job_response(
        jsonify,
        build_scan_request_plan,
        scan_job_manager,
        check_stock_signal,
    )

@app.route('/api/scan_jobs')
def api_list_scan_jobs():
    return scan_api.list_scan_jobs_response(jsonify, scan_job_manager)

@app.route('/api/scan_jobs/<job_id>')
def api_get_scan_job(job_id):
    return scan_api.scan_job_response(jsonify, scan_job_manager, job_id)

@app.route('/api/scan_jobs/<job_id>/cancel', methods=['POST'])
def api_cancel_scan_job(job_id):
    return scan_api.cancel_scan_job_response(jsonify, scan_job_manager, job_id)

@app.route('/')
def index():
    app.logger.debug("收到根路径请求: %s %s from %s", request.method, request.path, request.remote_addr)
    return render_template('index.html')

@app.route('/api/analyze')
def api_analyze():
    return stock_api.analyze_response(
        jsonify,
        normalize_code,
        fetch_and_process_data,
        get_stock_profile,
        get_stock_name,
    )


@app.route('/api/single_stock_analysis')
def api_single_stock_analysis():
    """Return the default stable SingleStockAnalysis projection."""
    return stock_api.single_stock_analysis_response(
        jsonify,
        normalize_code,
        fetch_and_process_data,
        get_stock_profile,
        get_stock_name,
    )


@app.route('/api/analyze/timeframes')
def api_analyze_timeframes():
    return stock_api.analyze_timeframes_response(
        jsonify,
        normalize_code,
        fetch_multi_timeframe_data,
    )


@app.errorhandler(404)
def not_found(e):
    """
    处理404错误
    页面路由返回 SPA 首页，API 路由返回 JSON 错误契约。
    """
    app.logger.debug("404错误: %s %s from %s", request.method, request.path, request.remote_addr)
    if request.path.startswith("/api/"):
        return jsonify({"error": "not_found", "path": request.path}), 404
    return render_template('index.html'), 404

@app.before_request
def log_request_info():
    """记录所有请求信息"""
    app.logger.debug("[请求] %s %s from %s", request.method, request.path, request.remote_addr)
    app.logger.debug("  - Host: %s", request.host)
    app.logger.debug("  - User-Agent: %s", request.headers.get('User-Agent', 'N/A')[:50])
    app.logger.debug("  - Referer: %s", request.headers.get('Referer', 'N/A')[:50])

if __name__ == '__main__':
    # 默认只监听本机；如需局域网/devtunnel 访问，显式设置 STOCK_ANALYZER_BIND_HOST=0.0.0.0
    host = os.environ.get("STOCK_ANALYZER_BIND_HOST", "127.0.0.1")
    print(f"启动服务... 请访问 http://{host}:5009")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print("警告: 服务绑定在非回环地址，且全部接口无鉴权，同一网络内的设备均可访问。")
    app.run(host=host, port=5009, debug=False, threaded=True)
