"""Data-source and board-market API handlers."""

from flask import request

from stock_analyzer.code_utils import normalize_code


def data_sources_response(jsonify, collect_data_source_status_func, start_date, logger):
    try:
        return jsonify(collect_data_source_status_func(start_date=start_date, logger=logger))
    except Exception as exc:
        print(f"[数据源状态] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def board_market_response(jsonify, get_board_market_func, unavailable_payload_func, start_date):
    try:
        board_type = request.args.get("type", "industry")
        name = request.args.get("name") or None
        index_code = request.args.get("index_code") or None
        query_start_date = request.args.get("start_date") or start_date
        if board_type not in {"industry", "concept"}:
            return jsonify({"error": "type必须为industry或concept"}), 400
        payload = get_board_market_func(
            board_type,
            name=name,
            index_code=index_code,
            start_date=query_start_date,
        )
        return jsonify(payload)
    except Exception as exc:
        print(f"[板块行情] 异常: {exc}")
        return jsonify(unavailable_payload_func(
            request.args.get("type", "industry"),
            name=request.args.get("name") or None,
            index_code=request.args.get("index_code") or None,
            error=exc,
        ))


def board_market_refresh_response(
    jsonify,
    collect_scan_workspace_func,
    refresh_board_market_cache_func,
    clear_workspace_cache_func,
    start_date,
    logger,
):
    try:
        data = request.get_json(silent=True) or {}
        board_type = data.get("type") or data.get("board_type") or "industry"
        limit = data.get("limit", 8)
        force = bool(data.get("force", False))
        if board_type not in {"industry", "concept"}:
            return jsonify({"error": "type必须为industry或concept"}), 400
        workspace = collect_scan_workspace_func(
            start_date=start_date,
            max_items=1,
            logger=logger,
            include_replay=False,
        )
        result = refresh_board_market_cache_func(
            workspace,
            board_type=board_type,
            limit=limit,
            start_date=start_date,
            force=force,
        )
        clear_workspace_cache_func()
        return jsonify(result)
    except Exception as exc:
        print(f"[板块行情刷新] 异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def profile_relation_evidence_response(jsonify, read_evidence_func, evidence_status_func, cache_dir):
    try:
        raw_code = request.args.get("code") or ""
        code = normalize_code(raw_code)
        if raw_code and not code:
            return jsonify({"error": "无效的股票代码"}), 400
        evidence = read_evidence_func(cache_dir=cache_dir)
        status = evidence_status_func(cache_dir=cache_dir)
        if code:
            relations = evidence.get(code, [])
            return jsonify({
                "code": code,
                "count": len(relations),
                "relations": relations,
                "status": status,
            })
        return jsonify({
            "stock_count": len(evidence),
            "relation_count": sum(len(rows) for rows in evidence.values()),
            "status": status,
        })
    except Exception as exc:
        print(f"[画像证据] 查询异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def upsert_profile_relation_evidence_response(
    jsonify,
    upsert_evidence_func,
    clear_workspace_cache_func,
    cache_dir,
):
    try:
        data = request.get_json(silent=True) or {}
        code = data.get("code")
        relation = data.get("relation") if isinstance(data.get("relation"), dict) else data
        result = upsert_evidence_func(code, relation, cache_dir=cache_dir)
        clear_workspace_cache_func()
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"[画像证据] 写入异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def delete_profile_relation_evidence_response(
    jsonify,
    delete_evidence_func,
    clear_workspace_cache_func,
    cache_dir,
):
    try:
        data = request.get_json(silent=True) or {}
        code = data.get("code") or request.args.get("code")
        relation_name = data.get("relation_name") or request.args.get("relation_name")
        result = delete_evidence_func(code, relation_name=relation_name, cache_dir=cache_dir)
        clear_workspace_cache_func()
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"[画像证据] 删除异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def concept_graph_response(jsonify, build_graph_func, cache_dir):
    try:
        include_derived = request.args.get("derived", "1") != "0"
        try:
            max_edges = int(request.args.get("limit") or 300)
        except ValueError:
            max_edges = 300
        payload = build_graph_func(
            include_derived=include_derived,
            max_edges=max(1, min(max_edges, 1000)),
            cache_dir=cache_dir,
        )
        return jsonify(payload)
    except Exception as exc:
        print(f"[概念图谱] 查询异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def upsert_concept_graph_edge_response(
    jsonify,
    upsert_edge_func,
    clear_workspace_cache_func,
    cache_dir,
):
    try:
        data = request.get_json(silent=True) or {}
        edge = data.get("edge") if isinstance(data.get("edge"), dict) else data
        result = upsert_edge_func(edge, cache_dir=cache_dir)
        clear_workspace_cache_func()
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"[概念图谱] 写入异常: {exc}")
        return jsonify({"error": str(exc)}), 500


def delete_concept_graph_edge_response(
    jsonify,
    delete_edge_func,
    clear_workspace_cache_func,
    cache_dir,
):
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            data = {
                "source_kind": request.args.get("source_kind"),
                "source_name": request.args.get("source_name"),
                "target_kind": request.args.get("target_kind"),
                "target_name": request.args.get("target_name"),
                "relation_type": request.args.get("relation_type"),
            }
        result = delete_edge_func(data, cache_dir=cache_dir)
        clear_workspace_cache_func()
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        print(f"[概念图谱] 删除异常: {exc}")
        return jsonify({"error": str(exc)}), 500
