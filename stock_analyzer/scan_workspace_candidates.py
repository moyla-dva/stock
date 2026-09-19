"""Filtered candidate shaping for scan workspace drill-downs."""

from stock_analyzer.scan_common import result_concepts
from stock_analyzer.scanner import normalize_scan_type


def _normalize_text(value):
    return str(value or "").strip().lower()


def _v2_state_model(result):
    model = result.get("v2_state_model") or result.get("c_signal_v2_state") or {}
    return model if isinstance(model, dict) else {}


def _plan_gate(result):
    model = _v2_state_model(result)
    permission_model = model.get("v2_permission_model") or {}
    if not isinstance(permission_model, dict):
        permission_model = {}
    gate = permission_model.get("plan_gate") or {}
    return gate if isinstance(gate, dict) else {}


def _exit_gate(result):
    facts = _v2_state_model(result).get("facts") or {}
    if not isinstance(facts, dict):
        return {}
    gate = facts.get("exit_gate") or {}
    return gate if isinstance(gate, dict) else {}


def _reason_texts(result):
    model = _v2_state_model(result)
    permission_model = model.get("v2_permission_model") or {}
    if not isinstance(permission_model, dict):
        permission_model = {}
    gate = _plan_gate(result)
    texts = [
        result.get("reason"),
        result.get("v2_macro_veto_reason"),
        model.get("reason"),
        model.get("next_action"),
        permission_model.get("reason"),
        permission_model.get("next_action"),
        gate.get("target_label"),
        gate.get("target_source"),
    ]
    for container in (result, model, permission_model, gate):
        if not isinstance(container, dict):
            continue
        for key in ("block_reasons", "required_confirmations", "warnings", "v2_environment_block_reasons", "v2_environment_warnings"):
            values = container.get(key) or []
            if isinstance(values, str):
                values = [values]
            texts.extend(values)
    return [str(text) for text in texts if text]


def _reason_blob(result):
    return " ".join(_reason_texts(result))


def _contains_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def _candidate_matches_reason(result, reason=""):
    reason = str(reason or "").strip()
    if not reason:
        return True
    model = _v2_state_model(result)
    gate = _plan_gate(result)
    exit_gate = _exit_gate(result)
    signal = str(result.get("v2_signal") or model.get("signal") or result.get("signal_label") or result.get("signal") or "")
    signal_key = str(result.get("signal_key") or "")
    plan_status = str(gate.get("status") or model.get("plan_status") or result.get("v2_plan_status") or "")
    state = str(model.get("state") or "")
    permission = str(model.get("permission") or result.get("v2_permission") or "")
    marker_role = str(exit_gate.get("marker_role") or exit_gate.get("markerRole") or "")
    text = _reason_blob(result)

    if reason == "plan_ready":
        return plan_status == "ready" or result.get("v2_priority_group") == "trade_ready"
    if reason == "plan_blocked":
        return plan_status == "blocked" or state == "trigger_plan_blocked"
    if reason == "macro_veto":
        return state == "macro_veto_blocked" or "宏观否决" in text or ("大周期" in text and permission == "forbidden")
    if reason == "ma60":
        return _contains_any(text, ["MA60未", "MA60 未", "MA60下行", "MA60 下行", "未满足MA60", "未满足 MA60", "未上行"])
    if reason == "ma250":
        return _contains_any(text, ["MA250下方", "MA250 下方", "低于MA250", "低于 MA250", "未站上MA250", "未站上 MA250", "年线下方", "跌破MA250", "跌破 MA250"])
    if reason == "rr":
        return _contains_any(text, ["收益风险比低于", "收益风险比不足", "低于 2:1", "低于2:1", "2R不足", "不足2R", "未达2R", "未达到2R"])
    if reason == "chase":
        return "追高" in text or "距 MA20" in text or "攻击日涨幅" in text
    if reason == "heat":
        return "过热" in text
    if reason == "wide_stop":
        return "止损距离超过" in text or "止损过宽" in text
    if reason == "c_pullback":
        return signal == "C回" or signal_key == "v2_pullback"
    if reason == "c_breakout":
        return signal == "C突" or signal_key in {"v2_breakout", "v2_bear_trap_recovery"}
    if reason == "c_attack":
        return signal == "C爆" or signal_key in {"v2_attack_day", "v2_ignition"}
    if reason == "exit_sell":
        return marker_role == "sell"
    if reason == "exit_scale_out":
        return marker_role == "scale_out"
    return True


def _candidate_event_date(result):
    return str(result.get("event_date") or result.get("date") or "")


def _candidate_matches(result, sector="", concept="", query="", reason="", code="", event_date=""):
    if code and str(result.get("code") or "") != str(code):
        return False
    if event_date and _candidate_event_date(result) != str(event_date):
        return False
    if sector and str(result.get("sector") or "") != sector:
        return False
    if concept and concept not in result_concepts(result):
        return False
    if not _candidate_matches_reason(result, reason=reason):
        return False
    query = _normalize_text(query)
    if not query:
        return True
    haystack = [
        result.get("code"),
        result.get("name"),
        result.get("sector"),
        " ".join(result_concepts(result)),
        result.get("signal"),
        result.get("signal_label"),
        result.get("signal_name"),
        result.get("reason"),
        _reason_blob(result),
    ]
    return any(query in _normalize_text(value) for value in haystack)


def filter_workspace_candidates(
    workspace,
    scan_type="opportunity",
    sector="",
    concept="",
    query="",
    reason="",
    code="",
    event_date="",
    limit=120,
    offset=0,
    compact_result_func=None,
):
    """Return a stable filtered candidate page from a full local workspace payload."""
    scan_type = normalize_scan_type(scan_type)
    pools = workspace.get("pools") or {}
    pool = pools.get(scan_type) or {}
    results = [
        result
        for result in pool.get("results", [])
        if _candidate_matches(
            result,
            sector=sector,
            concept=concept,
            query=query,
            reason=reason,
            code=code,
            event_date=event_date,
        )
    ]
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 120))
    page = results[offset:offset + limit]
    if compact_result_func is not None:
        page = [compact_result_func(result) for result in page]
    loaded_count = min(len(results), offset + len(page))
    return {
        "scan_type": scan_type,
        "filters": {
            "sector": sector or "",
            "concept": concept or "",
            "query": query or "",
            "reason": reason or "",
            "code": code or "",
            "event_date": event_date or "",
        },
        "offset": offset,
        "limit": limit,
        "count": len(results),
        "loaded_count": loaded_count,
        "has_more": loaded_count < len(results),
        "pool_count": pool.get("count") or len(pool.get("results", [])),
        "results": page,
        "latest_snapshot_day": workspace.get("latest_snapshot_day"),
        "latest_data_date": workspace.get("latest_data_date"),
        "history_mode": workspace.get("history_mode"),
        "history_snapshot_day": workspace.get("history_snapshot_day"),
    }
