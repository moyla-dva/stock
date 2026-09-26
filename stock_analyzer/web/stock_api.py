"""Stock-analysis API handlers."""

import inspect
import logging

from flask import request

from stock_analyzer.catalog_stock_list import StockUniverseUnavailable
from stock_analyzer.multi_timeframe import normalize_timeframe_period
from stock_analyzer.single_stock_read_model import SingleStockAnalysis
from stock_analyzer.tag_profile import attach_stock_tag_profile

LOGGER = logging.getLogger(__name__)


def stock_list_response(jsonify, get_stock_codes_func):
    try:
        stock_list = get_stock_codes_func()
        if isinstance(stock_list, dict):
            payload = dict(stock_list)
            payload["count"] = len(payload.get("codes") or [])
            return jsonify(payload)
        if hasattr(stock_list, "as_dict"):
            payload = stock_list.as_dict()
            payload["count"] = len(payload.get("codes") or [])
            return jsonify(payload)
        return jsonify({"count": len(stock_list), "codes": stock_list})
    except StockUniverseUnavailable as exc:
        LOGGER.debug("当前股票名单不可用: %s", exc, exc_info=True)
        return jsonify({
            "error": str(exc),
            "code": "stock_universe_unavailable",
            "retryable": True,
            "count": 0,
            "codes": [],
        }), 503
    except Exception as exc:
        LOGGER.debug("get_stock_list 异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc), "count": 0, "codes": []}), 500


def stock_profiles_response(jsonify, stock_service, get_stock_profile_func):
    try:
        data = request.get_json(silent=True) or {}
        codes = data.get("codes", [])
        if not isinstance(codes, list):
            return jsonify({"error": "codes必须为数组"}), 400

        profiles = stock_service.load_stock_profiles(
            codes,
            get_stock_profile_func=get_stock_profile_func,
        )
        return jsonify({"count": len(profiles), "profiles": profiles})
    except Exception as exc:
        LOGGER.debug("股票画像异常: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def build_stock_analysis_payload(
    code,
    *,
    include_legacy_chart,
    force_refresh,
    fetch_data_func,
    get_stock_profile_func,
    get_stock_name_func,
):
    fetch_kwargs = {}
    fetch_params = inspect.signature(fetch_data_func).parameters
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in fetch_params.values()
    )
    if "include_legacy_chart" in fetch_params or accepts_kwargs:
        fetch_kwargs["include_legacy_chart"] = include_legacy_chart
    if "force_refresh" in fetch_params or accepts_kwargs:
        fetch_kwargs["force_refresh"] = force_refresh
    data = fetch_data_func(code, **fetch_kwargs)
    if not data:
        return None

    profile = get_stock_profile_func(code)
    stock_name = profile.get("name") or get_stock_name_func(code)
    data["stock_name"] = f"{stock_name} ({code})"
    data["stock_sector"] = profile.get("sector") or ""
    data["stock_concepts"] = profile.get("concepts") or []
    attach_stock_tag_profile(data, profile={**profile, "code": code, "name": stock_name})
    return data


def analyze_response(jsonify, normalize_code_func, fetch_data_func, get_stock_profile_func, get_stock_name_func):
    raw_code = request.args.get("code", "600063")
    include_legacy_chart = request.args.get("legacy") == "1" or request.args.get("include_legacy") == "1"
    force_refresh = request.args.get("refresh") == "1"
    code = normalize_code_func(raw_code)
    if not code:
        return jsonify({"error": "无效的股票代码，请输入6位数字代码"}), 400
    LOGGER.debug("收到分析请求: %s", code)

    data = build_stock_analysis_payload(
        code,
        include_legacy_chart=include_legacy_chart,
        force_refresh=force_refresh,
        fetch_data_func=fetch_data_func,
        get_stock_profile_func=get_stock_profile_func,
        get_stock_name_func=get_stock_name_func,
    )
    if not data:
        return jsonify({"error": "无法获取数据，请检查代码是否正确"}), 400
    return jsonify(data)


def single_stock_analysis_response(
    jsonify,
    normalize_code_func,
    fetch_data_func,
    get_stock_profile_func,
    get_stock_name_func,
):
    raw_code = request.args.get("code", "600063")
    code = normalize_code_func(raw_code)
    if not code:
        return jsonify({
            "error": {
                "code": "invalid_stock_code",
                "message": "请提供 6 位股票代码。",
                "retryable": False,
                "details": {},
            }
        }), 400
    include_legacy_chart = request.args.get("legacy") == "1" or request.args.get("include_legacy") == "1"
    force_refresh = request.args.get("refresh") == "1"
    try:
        data = build_stock_analysis_payload(
            code,
            include_legacy_chart=include_legacy_chart,
            force_refresh=force_refresh,
            fetch_data_func=fetch_data_func,
            get_stock_profile_func=get_stock_profile_func,
            get_stock_name_func=get_stock_name_func,
        )
        if not data:
            return jsonify({
                "error": {
                    "code": "stock_analysis_unavailable",
                    "message": "无法获取该股票的分析数据。",
                    "retryable": True,
                    "details": {"code": code},
                }
            }), 503
        return jsonify(
            SingleStockAnalysis.from_payload(
                data,
                refresh_requested=force_refresh,
            ).to_dict()
        )
    except Exception:
        LOGGER.exception("单票稳定读模型构建失败: %s", code)
        return jsonify({
            "error": {
                "code": "stock_analysis_unavailable",
                "message": "单票分析暂不可用。",
                "retryable": True,
                "details": {"code": code},
            }
        }), 503


def analyze_timeframes_response(jsonify, normalize_code_func, fetch_timeframes_func):
    raw_code = request.args.get("code", "600063")
    raw_period = request.args.get("period")
    code = normalize_code_func(raw_code)
    if not code:
        return jsonify({"error": "无效的股票代码，请输入6位数字代码"}), 400
    period = normalize_timeframe_period(raw_period)
    if raw_period and not period:
        return jsonify({"error": "无效的分时周期，请使用 60m 或 4h"}), 400
    force_refresh = request.args.get("refresh") == "1"
    LOGGER.debug("收到分时确认请求: %s%s", code, f" period={raw_period}" if raw_period else "")

    data = fetch_timeframes_func(code, period=period, force_refresh=force_refresh)
    if not data:
        return jsonify({"error": "无法获取分时确认数据，请检查代码是否正确"}), 400
    return jsonify(data)
