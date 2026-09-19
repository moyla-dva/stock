"""Market scan helpers built on top of the shared signal event layer."""

import math

from stock_analyzer.c_signal_v2 import (
    build_c_signal_v2_priority,
    build_c_signal_v2_state,
    build_c_signal_v2_state_components,
)
from stock_analyzer.events import SignalEvent
from stock_analyzer.legacy_c_signal_adapter import c_signal_v2_fields
from stock_analyzer.scan_explainer import attach_scan_explanation
from stock_analyzer.v2_analysis_context import build_v2_analysis_context


SCAN_CONFIG = {
    "opportunity": {
        "groups": (),
        "keys": {
            "v2_ignition",
            "v2_attack_day",
            "v2_bear_trap_recovery",
            "v2_breakout",
            "v2_pullback",
            "v2_structure_candidate",
        },
        "lookback": 0,
        "title": "参与候选",
    },
    "risk": {
        "groups": (),
        "keys": {
            "v2_exit_gate_sell",
            "v2_strong_resistance_scale_out",
            "v2_risk_break",
            "v2_risk_heat",
            "v2_top_fractal_observe",
            "v2_top_fractal_risk",
        },
        "lookback": 0,
        "title": "风险验证",
    },
    "bottom_div": {
        "groups": (),
        "keys": {"v2_repair_watch", "v2_bottom_research", "v2_bearish_new_low"},
        "lookback": 2,
        "title": "修复观察",
    },
}

EVENT_WEIGHTS = {
    "v2_ignition": 28,
    "v2_attack_day": 24,
    "v2_structure_candidate": 16,
    "v2_bottom_research": 12,
    "v2_repair_watch": 14,
    "v2_bearish_new_low": 10,
    "v2_top_fractal_observe": 8,
    "v2_top_fractal_risk": 8,
    "v2_strong_resistance_scale_out": 18,
    "v2_exit_gate_sell": 24,
    "v2_bear_trap_recovery": 20,
    "v2_breakout": 18,
    "v2_pullback": 16,
    "v2_risk_break": 20,
    "v2_risk_heat": 14,
}



def _event_source_fields(event):
    return {
        "scan_admission_source": "v2_state",
        "scan_admission_label": "V2当前状态",
    }


def _pool_stage_fields(scan_type, event, scores, df_display):
    if scan_type == "risk":
        if event.key in {"v2_exit_gate_sell", "v2_risk_break"}:
            return {
                "pool_stage": "confirmed_risk",
                "pool_stage_label": "强风险",
                "pool_stage_tone": "danger",
                "pool_stage_detail": "V2 破位或离场事实已触发，优先看风险控制。",
            }
        if event.key == "v2_strong_resistance_scale_out":
            return {
                "pool_stage": "profit_protection",
                "pool_stage_label": "收益保护",
                "pool_stage_tone": "warning",
                "pool_stage_detail": "触及核心强阻，偏向保护利润或减仓。",
            }
        if event.key in {"v2_top_fractal_observe", "v2_top_fractal_risk", "v2_risk_heat"}:
            return {
                "pool_stage": "top_observe",
                "pool_stage_label": "顶部/过热观察",
                "pool_stage_tone": "warning",
                "pool_stage_detail": "顶分型或过热事实出现，但尚未形成离场确认。",
            }
        return {
            "pool_stage": "risk_warning",
            "pool_stage_label": "风险预警",
            "pool_stage_tone": "warning",
            "pool_stage_detail": "V2 风险条件出现，但尚未升级为强风险。",
        }

    if scan_type == "bottom_div":
        if event.key == "v2_repair_watch":
            return {
                "pool_stage": "repair_watch",
                "pool_stage_label": "修复观察",
                "pool_stage_tone": "warning",
                "pool_stage_detail": "底背离后已有修复事实，但仍未进入可执行入场许可。",
            }
        if event.key == "v2_bearish_new_low":
            return {
                "pool_stage": "extreme_watch",
                "pool_stage_label": "极端观察",
                "pool_stage_tone": "danger",
                "pool_stage_detail": "阴包阳创新低，只作为极端观察事实，等待结构确认。",
            }
        return {
            "pool_stage": "unconfirmed",
            "pool_stage_label": "底部研究",
            "pool_stage_tone": "muted",
            "pool_stage_detail": "V2 底背离出现，尚未得到修复确认。",
        }

    return {}


def format_scan_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def normalize_scan_type(scan_type):
    if scan_type in SCAN_CONFIG:
        return scan_type
    return "opportunity"


def _scan_config(scan_type):
    return SCAN_CONFIG[normalize_scan_type(scan_type)]


def scan_events_for_type(df_display, scan_type):
    scan_type = normalize_scan_type(scan_type)
    if df_display is None or df_display.empty or "date" not in df_display.columns:
        return []

    config = _scan_config(scan_type)
    event, _ = build_v2_latest_scan_event(df_display, scan_type)
    if event is None or event.key not in config["keys"]:
        return []
    return [event]


def latest_scan_score_summary(df_display, components=None):
    if df_display is None or df_display.empty:
        return {
            "date": "-",
            "setup": 0,
            "confirm": 0,
            "risk": 0,
            "watch": False,
        }

    latest = df_display.iloc[-1]
    if components is None:
        components = build_c_signal_v2_state_components(df_display) or {}
    facts = components.get("facts") if isinstance(components, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    scores = facts.get("scores") if isinstance(facts.get("scores"), dict) else {}
    setup_facts = facts.get("setup") if isinstance(facts.get("setup"), dict) else {}
    return {
        "date": format_scan_date(latest.get("date", "-")),
        "setup": _as_int(scores.get("setup")),
        "confirm": _as_int(scores.get("confirm")),
        "risk": _as_int(scores.get("risk")),
        "watch": bool(setup_facts.get("pullback_setup") or setup_facts.get("breakout_setup")),
    }


def _as_int(value, default=0):
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return int(number)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def _none_or_round(value, digits):
    if value is None:
        return None
    number = _as_float(value, None)
    if number is None:
        return None
    return round(number, digits)


def _none_or_int(value):
    number = _as_float(value, None)
    if number is None:
        return None
    return int(number)


def _none_or_bool(value):
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return bool(value)


def _latest_value(df_display, column):
    if df_display is None or df_display.empty or column not in df_display.columns:
        return None
    return df_display.iloc[-1].get(column)


def latest_diagnostic_summary(df_display, components=None):
    """Return latest-row V2 diagnostics plus shared indicator fields."""
    facts = components.get("facts") if isinstance(components, dict) else None
    if facts is None and df_display is not None and not df_display.empty:
        facts = (build_c_signal_v2_state_components(df_display) or {}).get("facts")
    facts = facts if isinstance(facts, dict) else {}
    risk = facts.get("risk") if isinstance(facts.get("risk"), dict) else {}
    setup_facts = facts.get("setup") if isinstance(facts.get("setup"), dict) else {}
    prior_high_10 = None
    if df_display is not None and "high" in getattr(df_display, "columns", []):
        window = df_display["high"].tail(11)
        if len(window) >= 2:
            prior_high_10 = _none_or_round(window.iloc[:-1].max(), 2)
    return {
        "risk_break_score": _none_or_int(risk.get("risk_break_score")),
        "risk_heat_score": _none_or_int(risk.get("risk_heat_score")),
        "prior_high_10": prior_high_10,
        "prior_breakout": _none_or_bool(setup_facts.get("prior_breakout")),
        "momentum_efficiency": _none_or_round(
            _latest_value(df_display, "momentum_efficiency"),
            3,
        ),
        "custom_z": _none_or_round(
            _latest_value(df_display, "custom_z"),
            3,
        ),
        "volume_ratio": _none_or_round(
            _latest_value(df_display, "volume_ratio"),
            2,
        ),
        "return_pct": _none_or_round(
            _latest_value(df_display, "return_pct"),
            2,
        ),
        "bull_power": _none_or_round(
            _latest_value(df_display, "bull_power"),
            3,
        ),
        "bear_power": _none_or_round(
            _latest_value(df_display, "bear_power"),
            3,
        ),
        "bull_bear_balance": _none_or_round(
            _latest_value(df_display, "bull_bear_balance"),
            3,
        ),
        "bull_power_dominant": _none_or_bool(
            _latest_value(df_display, "bull_power_dominant"),
        ),
        "bear_power_dominant": _none_or_bool(
            _latest_value(df_display, "bear_power_dominant"),
        ),
        "williams_r": _none_or_round(
            _latest_value(df_display, "williams_r"),
            2,
        ),
        "williams_r_cross_bull": _none_or_bool(
            _latest_value(df_display, "williams_r_cross_bull"),
        ),
        "williams_r_cross_bear": _none_or_bool(
            _latest_value(df_display, "williams_r_cross_bear"),
        ),
        "williams_r_center_side": _latest_value(df_display, "williams_r_center_side"),
    }


def rank_scan_event(event, scores, signal_stats, scan_type):
    setup = scores["setup"]
    confirm = scores["confirm"]
    risk = scores["risk"]
    event_weight = EVENT_WEIGHTS.get(event.key, 6)
    win_rate = _as_float(signal_stats.get("win_rate"), 0.0)
    avg_ret = _as_float(signal_stats.get("avg_ret"), 0.0)

    if scan_type == "risk":
        return risk * 5 + event_weight + win_rate * 0.08 + max(0.0, -avg_ret) * 2 - confirm
    if scan_type == "bottom_div":
        return setup * 3 + confirm * 2 - risk * 2 + event_weight + win_rate * 0.05 + avg_ret
    return setup * 3 + confirm * 4 - risk * 3 + event_weight + win_rate * 0.06 + avg_ret


def _latest_price(df_display):
    try:
        return round(float(df_display.iloc[-1]["close"]), 2)
    except (KeyError, TypeError, ValueError):
        return None


def _latest_date(df_display):
    if df_display is None or df_display.empty or "date" not in df_display.columns:
        return "-"
    return format_scan_date(df_display.iloc[-1]["date"])


def _event_price_for_latest(df_display, key):
    latest = df_display.iloc[-1]
    if key in {"v2_top_fractal_observe", "v2_top_fractal_risk", "v2_strong_resistance_scale_out", "v2_exit_gate_sell"}:
        return _as_float(latest.get("high"), _as_float(latest.get("close"), 0.0))
    return _as_float(latest.get("low"), _as_float(latest.get("close"), 0.0))


def _v2_latest_event_key(state_model, scan_type):
    if not state_model:
        return ""
    state = state_model.get("state") or ""
    permission = state_model.get("permission") or ""
    permission_model = state_model.get("v2_permission_model")
    if not isinstance(permission_model, dict):
        permission_model = {}
    event_mapping = state_model.get("event_mapping") if isinstance(state_model.get("event_mapping"), dict) else {}
    signal_key = permission_model.get("signal_key") or event_mapping.get("v2_source_key") or ""
    facts = state_model.get("facts") if isinstance(state_model.get("facts"), dict) else {}
    trigger = facts.get("trigger") if isinstance(facts.get("trigger"), dict) else {}
    structure = facts.get("structure") if isinstance(facts.get("structure"), dict) else {}
    fractals = structure.get("fractals") if isinstance(structure.get("fractals"), dict) else {}
    risk = facts.get("risk") if isinstance(facts.get("risk"), dict) else {}

    if scan_type == "risk":
        if permission != "risk_only":
            return ""
        if str(signal_key).startswith("v2_"):
            return signal_key
        return ""

    if scan_type == "bottom_div":
        if state in {"repair_setup", "repair_watch"}:
            return "v2_repair_watch"
        if state == "research_bottom":
            return "v2_bottom_research"
        if trigger.get("bearish_engulfing_new_low"):
            return "v2_bearish_new_low"
        return ""

    if scan_type == "opportunity":
        if permission in {"attack_allowed", "breakout_allowed", "pullback_allowed"}:
            if str(signal_key).startswith("v2_"):
                return signal_key
            fallback_signal = {
                "attack_allowed": "v2_attack_day",
                "breakout_allowed": "v2_breakout",
                "pullback_allowed": "v2_pullback",
            }
            return fallback_signal.get(permission, "")
        if permission == "structure_only" or state in {
            "trigger_observed",
            "trigger_plan_waiting",
            "trigger_plan_blocked",
        }:
            return "v2_structure_candidate"
        return ""

    return ""


def build_v2_latest_scan_event(df_display, scan_type, state_model=None, components=None):
    """Return the V2 current-state admission event for a scan pool."""
    scan_type = normalize_scan_type(scan_type)
    if df_display is None or df_display.empty or "date" not in df_display.columns:
        return None, state_model
    state_model = state_model or build_c_signal_v2_state(df_display, components=components)
    key = _v2_latest_event_key(state_model, scan_type)
    if not key:
        return None, state_model

    latest = df_display.iloc[-1]
    price = _event_price_for_latest(df_display, key)
    if price is None:
        return None, state_model
    coord_price = price * 1.02 if key in {"v2_top_fractal_observe", "v2_top_fractal_risk", "v2_strong_resistance_scale_out", "v2_exit_gate_sell"} else price * 0.98
    event = SignalEvent(
        key=key,
        group="v2",
        date=_latest_date(df_display),
        coord_price=float(coord_price),
        price=_as_float(latest.get("close"), price),
        reason=state_model.get("reason") or "",
        value=state_model.get("state_label") or state_model.get("signal_name") or "",
    )
    return event, state_model


def build_scan_result(code, name, df_display, event, scan_type, signal_stats, state_model=None, components=None):
    scan_type = normalize_scan_type(scan_type)
    scores = latest_scan_score_summary(df_display, components=components)
    rank_score = rank_scan_event(event, scores, signal_stats, scan_type)
    definition = event.definition
    result = {
        "code": code,
        "name": name or code,
        "price": _latest_price(df_display),
        "date": _latest_date(df_display),
        "event_date": event.date,
        "signal": event.label,
        "signal_key": event.key,
        "signal_label": event.label,
        "signal_name": definition["name"],
        "signal_category": definition["category"],
        "reason": event.reason or definition["detail"],
        "scan_type": scan_type,
        "scan_title": _scan_config(scan_type)["title"],
        "setup_score": scores["setup"],
        "confirm_score": scores["confirm"],
        "risk_score": scores["risk"],
        "rank_score": round(rank_score, 1),
        "win_rate": _none_or_round(signal_stats.get("win_rate"), 1),
        "avg_ret": _none_or_round(signal_stats.get("avg_ret"), 2),
    }
    result.update(_event_source_fields(event))
    result.update(c_signal_v2_fields(event.key))
    result["v2_state_model"] = state_model or build_c_signal_v2_state(df_display, event_key=event.key, components=components)
    for key in (
        "candidate_substate",
        "candidate_substate_label",
        "candidate_display_label",
        "candidate_confirmation_price",
        "candidate_invalidation_price",
        "candidate_missing_confirmations",
        "candidate_trigger_plan",
    ):
        result[key] = result["v2_state_model"].get(key)
    result.update(build_c_signal_v2_priority(result))
    result.update(latest_diagnostic_summary(df_display, components=components))
    result.update(_pool_stage_fields(scan_type, event, scores, df_display))
    return attach_scan_explanation(result)


def scan_stock_frame(code, name, df_display, scan_type="opportunity", analysis_context=None):
    scan_type = normalize_scan_type(scan_type)
    analysis_context = analysis_context if isinstance(analysis_context, dict) else None
    if analysis_context is None:
        analysis_context = build_v2_analysis_context(
            df_display,
            include_events=False,
            include_trade_plan=False,
        )
    v2_components = analysis_context.get("components") if isinstance(analysis_context, dict) else None
    v2_state_model = analysis_context.get("state") if isinstance(analysis_context, dict) else None
    v2_event, v2_state_model = build_v2_latest_scan_event(
        df_display,
        scan_type,
        state_model=v2_state_model,
        components=v2_components,
    )
    if v2_event is None or v2_event.key not in _scan_config(scan_type)["keys"]:
        return None

    # Per-bar V2 event replay is O(n^2) facts rebuilding and dominated full-market
    # scan cost; scan admission/priority already come from the V2 state model, so
    # the scan path skips historical win-rate stats.
    signal_stats = {}
    return build_scan_result(
        code,
        name,
        df_display,
        v2_event,
        scan_type,
        signal_stats,
        state_model=v2_state_model,
        components=v2_components,
    )
