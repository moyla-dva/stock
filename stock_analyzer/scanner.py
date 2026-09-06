"""Market scan helpers built on top of the shared signal event layer."""

import math

from stock_analyzer.backtest import evaluate_signal_events
from stock_analyzer.c_signal_v2 import c_signal_v2_fields
from stock_analyzer.events import (
    build_composite_signal_events,
    build_new_signal_events,
    build_old_signal_events,
    build_opt_signal_events,
)
from stock_analyzer.scan_explainer import attach_scan_explanation


EVENT_BUILDERS = {
    "composite": build_composite_signal_events,
    "old": build_old_signal_events,
    "new": build_new_signal_events,
    "opt": build_opt_signal_events,
}

SCAN_CONFIG = {
    "opportunity": {
        "groups": ("composite",),
        "keys": {
            "composite_pullback",
            "composite_breakout",
            "composite_confirm",
        },
        "lookback": 0,
        "title": "参与候选",
    },
    "risk": {
        "groups": ("composite",),
        "keys": {
            "composite_warning",
            "composite_stop_loss",
            "composite_take_profit",
            "composite_exit",
            "composite_top_divergence",
        },
        "lookback": 0,
        "title": "风险验证",
    },
    "bottom_div": {
        "groups": ("composite",),
        "keys": {"composite_bottom_divergence"},
        "lookback": 2,
        "title": "修复观察",
    },
    # Backward-compatible scan modes used by older buttons/tests.
    "composite": {
        "groups": ("composite",),
        "keys": {"composite_pullback", "composite_breakout", "composite_confirm"},
        "lookback": 0,
        "title": "综合买点",
    },
    "new": {
        "groups": ("new",),
        "keys": {"new_gold", "new_pullback"},
        "lookback": 0,
        "title": "新B诊断",
    },
    "old": {
        "groups": ("old",),
        "keys": {"old_gold", "old_pullback"},
        "lookback": 0,
        "title": "旧B诊断",
    },
    "opt": {
        "groups": ("opt",),
        "keys": {"opt_gold", "opt_pullback"},
        "lookback": 0,
        "title": "优化B诊断",
    },
}

EVENT_WEIGHTS = {
    "composite_breakout": 18,
    "composite_pullback": 16,
    "composite_confirm": 14,
    "new_gold": 14,
    "new_pullback": 11,
    "old_gold": 10,
    "old_pullback": 8,
    "opt_gold": 12,
    "opt_pullback": 10,
    "composite_top_divergence": 18,
    "composite_stop_loss": 16,
    "composite_warning": 13,
    "composite_exit": 12,
    "composite_take_profit": 8,
    "composite_bottom_divergence": 12,
    "bottom_divergence": 10,
}

ENTRY_EVENT_KEYS = {"composite_pullback", "composite_breakout", "composite_confirm"}
CONFIRMED_RISK_EVENT_KEYS = {"composite_stop_loss", "composite_exit"}


def _has_entry_after_event(df_display, event):
    for candidate in build_events_for_groups(df_display, ("composite",)):
        if candidate.key in ENTRY_EVENT_KEYS and candidate.date >= event.date:
            return True
    return False


def _pool_stage_fields(scan_type, event, scores, df_display):
    if scan_type == "risk":
        if event.key in CONFIRMED_RISK_EVENT_KEYS:
            return {
                "pool_stage": "confirmed_risk",
                "pool_stage_label": "强风险",
                "pool_stage_tone": "danger",
                "pool_stage_detail": "止损或趋势破坏已触发，优先看风险控制。",
            }
        if event.key == "composite_take_profit":
            return {
                "pool_stage": "profit_protection",
                "pool_stage_label": "收益保护",
                "pool_stage_tone": "warning",
                "pool_stage_detail": "已有收益后的回撤或转弱，偏向保护利润。",
            }
        if event.key == "composite_top_divergence":
            return {
                "pool_stage": "top_observe",
                "pool_stage_label": "顶部观察",
                "pool_stage_tone": "warning",
                "pool_stage_detail": "顶背离出现，但尚未形成持仓离场确认。",
            }
        if scores["risk"] >= 4:
            return {
                "pool_stage": "strong_warning",
                "pool_stage_label": "强预警",
                "pool_stage_tone": "danger",
                "pool_stage_detail": "风险分较高，需优先确认趋势是否破坏。",
            }
        return {
            "pool_stage": "risk_warning",
            "pool_stage_label": "风险预警",
            "pool_stage_tone": "warning",
            "pool_stage_detail": "风险条件出现，但尚未升级为强风险。",
        }

    if scan_type == "bottom_div":
        if _has_entry_after_event(df_display, event):
            return {
                "pool_stage": "converted",
                "pool_stage_label": "已转参与",
                "pool_stage_tone": "positive",
                "pool_stage_detail": "底背离后已经出现综合买点确认。",
            }
        if scores["risk"] >= 4:
            return {
                "pool_stage": "risk_blocked",
                "pool_stage_label": "风险压制",
                "pool_stage_tone": "danger",
                "pool_stage_detail": "底背离仍被风险条件压制，暂不按买点处理。",
            }
        if scores["confirm"] >= 4 and scores["risk"] <= 2:
            return {
                "pool_stage": "trend_confirmed",
                "pool_stage_label": "趋势确认",
                "pool_stage_tone": "positive",
                "pool_stage_detail": "趋势和量能确认较充分，可继续看是否转入参与候选。",
            }
        if scores["confirm"] >= 2 and scores["risk"] <= 3:
            return {
                "pool_stage": "watch_strengthening",
                "pool_stage_label": "观察加强",
                "pool_stage_tone": "warning",
                "pool_stage_detail": "底背离后有部分确认，但还不是完整买点。",
            }
        return {
            "pool_stage": "unconfirmed",
            "pool_stage_label": "未确认",
            "pool_stage_tone": "muted",
            "pool_stage_detail": "仅出现底背离，尚未得到趋势或量能确认。",
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


def _safe_build_events(df_display, group):
    builder = EVENT_BUILDERS[group]
    try:
        return builder(df_display)
    except KeyError:
        return []


def build_events_for_groups(df_display, groups):
    events = []
    for group in groups:
        events.extend(_safe_build_events(df_display, group))
    return events


def scan_events_for_type(df_display, scan_type):
    scan_type = normalize_scan_type(scan_type)
    if df_display is None or df_display.empty or "date" not in df_display.columns:
        return []

    config = _scan_config(scan_type)
    start = max(0, len(df_display) - 1 - config["lookback"])
    window_dates = {
        format_scan_date(value)
        for value in df_display.iloc[start:]["date"].tolist()
    }
    events = build_events_for_groups(df_display, config["groups"])
    return [
        event for event in events
        if event.key in config["keys"] and event.date in window_dates
    ]


def latest_score_summary(df_display):
    if df_display is None or df_display.empty:
        return {
            "date": "-",
            "setup": 0,
            "confirm": 0,
            "risk": 0,
            "watch": False,
        }

    latest = df_display.iloc[-1]
    return {
        "date": format_scan_date(latest.get("date", "-")),
        "setup": _as_int(latest.get("composite_setup_score", 0)),
        "confirm": _as_int(latest.get("composite_confirm_score", 0)),
        "risk": _as_int(latest.get("composite_risk_score", 0)),
        "watch": bool(latest.get("composite_watch", False)),
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


def latest_diagnostic_summary(df_display):
    """Return latest-row diagnostics already computed by the strategy layer."""
    return {
        "risk_break_score": _none_or_int(
            _latest_value(df_display, "composite_risk_break_score"),
        ),
        "risk_heat_score": _none_or_int(
            _latest_value(df_display, "composite_risk_heat_score"),
        ),
        "prior_high_10": _none_or_round(
            _latest_value(df_display, "composite_prior_high_10"),
            2,
        ),
        "prior_breakout": _none_or_bool(
            _latest_value(df_display, "composite_prior_breakout"),
        ),
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


def build_scan_result(code, name, df_display, event, scan_type, signal_stats):
    scan_type = normalize_scan_type(scan_type)
    scores = latest_score_summary(df_display)
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
    result.update(c_signal_v2_fields(event.key))
    result.update(latest_diagnostic_summary(df_display))
    result.update(_pool_stage_fields(scan_type, event, scores, df_display))
    return attach_scan_explanation(result)


def scan_stock_frame(code, name, df_display, scan_type="opportunity"):
    scan_type = normalize_scan_type(scan_type)
    events = scan_events_for_type(df_display, scan_type)
    if not events:
        return None

    config = _scan_config(scan_type)
    stats_events = [
        event for event in build_events_for_groups(df_display, config["groups"])
        if event.key in config["keys"]
    ]
    event_stats = evaluate_signal_events(df_display, stats_events)
    signal_stats_by_key = event_stats["by_signal"]

    ranked = []
    scores = latest_score_summary(df_display)
    for event in events:
        signal_stats = signal_stats_by_key.get(event.key, {})
        ranked.append((
            rank_scan_event(event, scores, signal_stats, scan_type),
            event.definition["order"],
            event,
            signal_stats,
        ))

    ranked.sort(key=lambda item: (item[0], -item[1], item[2].date))
    _, _, best_event, best_stats = ranked[-1]
    return build_scan_result(code, name, df_display, best_event, scan_type, best_stats)
