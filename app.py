# -*- coding: utf-8 -*-
"""
A股短线结构工作台 Web版 (Flask)
功能：提供候选池、单股确认和数据后台
启动方式：./venv/bin/python app.py
访问地址：http://127.0.0.1:5009
"""
import logging  # 【新增】日志支持
import math
from numbers import Integral, Real

from flask import Flask, render_template, request, jsonify as flask_jsonify

from stock_analyzer import catalog, scan_service, stock_service
from stock_analyzer.board_market_refresh import refresh_board_market_cache
from stock_analyzer.catalog import get_stock_codes, get_stock_name, get_stock_profile
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.concept_graph import (
    build_concept_graph,
    delete_concept_graph_edge,
    upsert_concept_graph_edge,
)
from stock_analyzer.concept_jobs import ConceptRefreshJobManager
from stock_analyzer.data_sources import collect_data_source_status
from stock_analyzer.market_boards import get_board_market, unavailable_board_market_payload
from stock_analyzer.profile_relations import (
    delete_profile_relation_evidence,
    profile_relation_evidence_status,
    read_profile_relation_evidence,
    upsert_profile_relation_evidence,
)
from stock_analyzer.scan_cache import prune_scan_cache, scan_cache_status
from stock_analyzer.scan_history import list_scan_history
from stock_analyzer.scan_jobs import ScanJobManager
from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache
from stock_analyzer.scanner import scan_events_for_type
from stock_analyzer.scan_snapshot import (
    build_scan_snapshot,
    is_current_strategy_snapshot,
    is_recent_snapshot,
    read_latest_scan_snapshot,
    read_scan_snapshot,
    scan_result_from_snapshot,
    snapshot_has_scan_type,
    write_scan_snapshot,
)
from stock_analyzer.scan_workspace import collect_scan_workspace
from stock_analyzer.versioning import DATA_START_DATE
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

def fetch_and_process_data(code):
    return stock_service.fetch_and_process_data(code, logger=app.logger, verbose=True)


scan_job_manager = ScanJobManager(max_jobs=2, max_workers=5, batch_size=50, batch_delay=1.0, request_delay=0.05)
concept_refresh_job_manager = ConceptRefreshJobManager(max_workers=1)


scan_events_for_mode = scan_events_for_type


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

def check_stock_signal(code, scan_type='opportunity', force_refresh=False, refresh_policy=None):
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
        get_stock_profile_func=get_stock_profile,
        build_scan_snapshot_func=build_scan_snapshot,
        write_scan_snapshot_func=write_scan_snapshot,
        enrich_result_func=enrich_scan_result_with_profile,
    )

@app.route('/api/stock_list')
def get_stock_list():
    """获取全市场股票列表 (增强版：多接口备用)"""
    return stock_api.stock_list_response(jsonify, get_stock_codes)

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


@app.route('/api/scan_history')
def api_scan_history():
    """List local scan snapshot days for history browsing."""
    return scan_api.scan_history_response(jsonify, list_scan_history, DATA_START_DATE, app.logger)


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
    """Return market-level industry/concept board trend metrics."""
    return data_api.board_market_response(
        jsonify,
        get_board_market,
        unavailable_board_market_payload,
        DATA_START_DATE,
    )


@app.route('/api/board_market/refresh', methods=['POST'])
def api_refresh_board_market_cache():
    """Refresh top-priority industry/concept board market caches."""
    return data_api.board_market_refresh_response(
        jsonify,
        collect_scan_workspace,
        refresh_board_market_cache,
        clear_scan_workspace_cache,
        DATA_START_DATE,
        app.logger,
    )


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
    )


def get_scan_universe_codes():
    """Use the local profile universe for scans before falling back to network lists."""
    profiles = catalog.get_cached_stock_profiles()
    codes = sorted(
        {
            normalize_code(code)
            for code in profiles.keys()
            if normalize_code(code)
        }
    )
    if len(codes) >= 1000:
        return codes
    return get_stock_codes()


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
    print(f"收到根路径请求: {request.method} {request.path} from {request.remote_addr}")
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


@app.errorhandler(404)
def not_found(e):
    """
    处理404错误
    【P2-1修复】原代码返回200状态码是错误的，改为返回404
    但为了用户体验，仍然返回首页HTML（这可能需要根据实际需求调整）
    """
    print(f"404错误: {request.method} {request.path} from {request.remote_addr}")
    # 注意：按HTTP规范，404应返回404状态码
    # 但若希望用户在访问不存在路径时仍看到首页，可保持返回200
    # 这里遵守HTTP规范，返回404状态码
    return render_template('index.html'), 404

@app.before_request
def log_request_info():
    """记录所有请求信息"""
    print(f"[请求] {request.method} {request.path} from {request.remote_addr}")
    print(f"  - Host: {request.host}")
    print(f"  - User-Agent: {request.headers.get('User-Agent', 'N/A')[:50]}")
    print(f"  - Referer: {request.headers.get('Referer', 'N/A')[:50]}")

if __name__ == '__main__':
    print("启动服务... 请访问 http://0.0.0.0:5009")
    print("注意: devtunnels 会自动处理 HTTPS 转换，服务器使用 HTTP 即可")
    # 使用 HTTP 模式，devtunnels 会自动转换为 HTTPS
    app.run(host='0.0.0.0', port=5009, debug=False, threaded=True)
