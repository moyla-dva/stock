"""Stock-analysis API handlers."""

import inspect

from flask import request

from stock_analyzer.multi_timeframe import normalize_timeframe_period
from stock_analyzer.tag_profile import attach_stock_tag_profile


def stock_list_response(jsonify, get_stock_codes_func):
    try:
        stock_list = get_stock_codes_func()
        return jsonify({"count": len(stock_list), "codes": stock_list})
    except Exception as exc:
        print(f"get_stock_list 异常: {exc}")
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
        print(f"[股票画像] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def analyze_response(jsonify, normalize_code_func, fetch_data_func, get_stock_profile_func, get_stock_name_func):
    raw_code = request.args.get("code", "600063")
    include_legacy_chart = request.args.get("legacy") == "1" or request.args.get("include_legacy") == "1"
    code = normalize_code_func(raw_code)
    if not code:
        return jsonify({"error": "无效的股票代码，请输入6位数字代码"}), 400
    print(f"收到分析请求: {code}")

    if "include_legacy_chart" in inspect.signature(fetch_data_func).parameters:
        data = fetch_data_func(code, include_legacy_chart=include_legacy_chart)
    else:
        data = fetch_data_func(code)
    if not data:
        return jsonify({"error": "无法获取数据，请检查代码是否正确"}), 400

    profile = get_stock_profile_func(code)
    stock_name = profile.get("name") or get_stock_name_func(code)
    data["stock_name"] = f"{stock_name} ({code})"
    data["stock_sector"] = profile.get("sector") or ""
    data["stock_concepts"] = profile.get("concepts") or []
    attach_stock_tag_profile(data, profile={**profile, "code": code, "name": stock_name})
    return jsonify(data)


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
    print(f"收到分时确认请求: {code}" + (f" period={raw_period}" if raw_period else ""))

    data = fetch_timeframes_func(code, period=period, force_refresh=force_refresh)
    if not data:
        return jsonify({"error": "无法获取分时确认数据，请检查代码是否正确"}), 400
    return jsonify(data)
