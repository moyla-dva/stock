"""C signal V2 fact extraction.

This module owns observable technical facts only. It deliberately avoids
turning those facts into buy/sell decisions so the V2 state and permission
layers can reuse the same truth without re-parsing legacy scores.
"""

import math

import pandas as pd


def _as_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        return number if number == number else default
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    number = _as_float(value)
    return default if number is None else int(number)


def _as_bool(value):
    if value is None:
        return False
    try:
        if math.isnan(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n", ""}:
            return False
    return bool(value)


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def _round(value, digits=2):
    number = _as_float(value)
    return None if number is None else round(number, digits)


def _pct_distance(a, b):
    a_value = _as_float(a)
    b_value = _as_float(b)
    if a_value is None or b_value in {None, 0}:
        return None
    return round((a_value - b_value) / b_value * 100, 2)


def _series(df, column, default=False):
    if column in df.columns:
        return df[column]
    return pd.Series(default, index=df.index)


def _latest_row(df_display):
    if df_display is None or df_display.empty:
        return None
    return df_display.iloc[-1]


def _fractal_payload(row, kind):
    price_key = "low" if kind == "bottom" else "high"
    return {
        "date": _format_date(row.get("date")),
        "kind": kind,
        "low": _round(row.get("low")),
        "high": _round(row.get("high")),
        "price": _round(row.get(price_key)),
    }


def build_williams_fractal_facts(df_display, lookback=80):
    """Detect confirmed five-bar Williams fractals.

    The latest two bars are excluded because a five-bar fractal needs two bars
    of right-side confirmation. Bars with direct containment against their
    previous bar are excluded from being the center point in this first pass.
    """
    if df_display is None or df_display.empty or not {"high", "low"}.issubset(df_display.columns):
        return {
            "available": False,
            "confirmation_lag": 2,
            "containment_count": 0,
            "latest_bottom": None,
            "latest_top": None,
            "recent_bottoms": [],
            "recent_tops": [],
            "double_bottom_higher_low": False,
            "top_lower_high": False,
            "summary": "缺少高低点数据，无法计算威廉分型。",
        }

    window = df_display.tail(lookback).copy()
    if len(window) < 5:
        return {
            "available": False,
            "confirmation_lag": 2,
            "containment_count": 0,
            "latest_bottom": None,
            "latest_top": None,
            "recent_bottoms": [],
            "recent_tops": [],
            "double_bottom_higher_low": False,
            "top_lower_high": False,
            "summary": "样本不足，至少需要 5 根 K 线确认分型。",
        }

    high = window["high"]
    low = window["low"]
    previous_high = high.shift(1)
    previous_low = low.shift(1)
    containment = (
        ((high <= previous_high) & (low >= previous_low))
        | ((high >= previous_high) & (low <= previous_low))
    ).fillna(False)

    bottoms = []
    tops = []
    for pos in range(2, len(window) - 2):
        if bool(containment.iloc[pos]):
            continue
        local_high = high.iloc[pos - 2:pos + 3]
        local_low = low.iloc[pos - 2:pos + 3]
        row = window.iloc[pos]
        center_high = high.iloc[pos]
        center_low = low.iloc[pos]
        if center_low == local_low.min() and int((local_low == center_low).sum()) == 1:
            bottoms.append(_fractal_payload(row, "bottom"))
        if center_high == local_high.max() and int((local_high == center_high).sum()) == 1:
            tops.append(_fractal_payload(row, "top"))

    recent_bottoms = bottoms[-3:]
    recent_tops = tops[-3:]
    double_bottom_higher_low = False
    if len(recent_bottoms) >= 2:
        double_bottom_higher_low = (
            recent_bottoms[-1]["price"] is not None
            and recent_bottoms[-2]["price"] is not None
            and recent_bottoms[-1]["price"] > recent_bottoms[-2]["price"]
        )
    top_lower_high = False
    if len(recent_tops) >= 2:
        top_lower_high = (
            recent_tops[-1]["price"] is not None
            and recent_tops[-2]["price"] is not None
            and recent_tops[-1]["price"] < recent_tops[-2]["price"]
        )

    if double_bottom_higher_low:
        summary = "已确认两个底分型，后一低点抬高。"
    elif recent_bottoms:
        summary = "已确认底分型，但双底抬高结构尚不完整。"
    elif recent_tops:
        summary = "已确认顶分型，优先作为风险或压力事实。"
    else:
        summary = "近期没有确认分型。"

    return {
        "available": True,
        "confirmation_lag": 2,
        "containment_count": int(containment.sum()),
        "latest_bottom": recent_bottoms[-1] if recent_bottoms else None,
        "latest_top": recent_tops[-1] if recent_tops else None,
        "recent_bottoms": recent_bottoms,
        "recent_tops": recent_tops,
        "double_bottom_higher_low": bool(double_bottom_higher_low),
        "top_lower_high": bool(top_lower_high),
        "summary": summary,
    }


def build_rectangle_facts(df_display, lookback=20, max_width_pct=20.0):
    if df_display is None or df_display.empty or not {"high", "low", "close"}.issubset(df_display.columns):
        return {"available": False, "summary": "缺少高低收数据，无法计算矩形边界。"}
    window = df_display.tail(lookback).copy()
    if len(window) < 10:
        return {"available": False, "summary": "样本不足，至少需要 10 根 K 线估算矩形。"}

    latest = window.iloc[-1]
    upper = _as_float(window["high"].max())
    lower = _as_float(window["low"].min())
    close = _as_float(latest.get("close"))
    mid = (upper + lower) / 2 if upper is not None and lower is not None else None
    width_pct = None if mid in {None, 0} else round((upper - lower) / mid * 100, 2)
    available = bool(width_pct is not None and width_pct <= max_width_pct)
    inside = bool(available and lower <= close <= upper) if close is not None else False
    near_upper_pct = _pct_distance(upper, close)
    near_lower_pct = _pct_distance(close, lower)
    c_point = lower

    return {
        "available": available,
        "lookback": int(len(window)),
        "upper": _round(upper),
        "lower": _round(lower),
        "mid": _round(mid),
        "width_pct": width_pct,
        "inside": inside,
        "near_upper_pct": near_upper_pct,
        "near_lower_pct": near_lower_pct,
        "breakout_price": _round(upper),
        "c_point": _round(c_point),
        "invalidation_price": _round(c_point),
        "summary": (
            f"近{len(window)}日矩形宽度 {width_pct:.2f}%，边界可跟踪。"
            if available and width_pct is not None
            else "近期波动区间过宽，暂不作为稳定矩形。"
        ),
    }


def build_trigger_facts(df_display, ignition_multiplier=1.0):
    if df_display is None or len(df_display) < 2:
        return {
            "available": False,
            "attack_day": False,
            "bearish_engulfing_new_low": False,
            "ignition": {"available": False},
            "summary": "样本不足，无法计算攻击日或起爆点。",
        }

    latest = df_display.iloc[-1]
    previous = df_display.iloc[-2]
    open_price = _as_float(latest.get("open"))
    high = _as_float(latest.get("high"))
    low = _as_float(latest.get("low"))
    close = _as_float(latest.get("close"))
    prev_open = _as_float(previous.get("open"))
    prev_high = _as_float(previous.get("high"))
    prev_low = _as_float(previous.get("low"))
    prev_close = _as_float(previous.get("close"))
    if None in {open_price, high, low, close, prev_open, prev_high, prev_low, prev_close}:
        return {
            "available": False,
            "attack_day": False,
            "bearish_engulfing_new_low": False,
            "ignition": {"available": False},
            "summary": "缺少 OHLC 数据，无法计算攻击日或起爆点。",
        }

    volume = _as_float(latest.get("volume"), 0.0) or 0.0
    volume_ma20 = _as_float(latest.get("vol_ma20"))
    if volume_ma20 is None and "volume" in df_display.columns:
        volume_ma20 = _as_float(df_display["volume"].tail(20).mean())
    volume_expand = bool(volume_ma20 and volume > volume_ma20 * 1.2)

    ranges = (df_display["high"] - df_display["low"]).tail(20) if {"high", "low"}.issubset(df_display.columns) else pd.Series([])
    avg_range = _as_float(ranges.mean())
    range_expansion = bool(avg_range and (high - low) >= avg_range * 1.25)
    bullish_engulfing = bool(close > open_price and prev_close < prev_open and open_price <= prev_close and close >= prev_open)
    breaks_prev_high = bool(close > prev_high or high > prev_high)
    attack_day = bool(close > open_price and breaks_prev_high and (bullish_engulfing or range_expansion or volume_expand))

    rolling_low = _as_float(df_display["low"].tail(20).min()) if "low" in df_display.columns else None
    bearish_engulfing = bool(close < open_price and prev_close > prev_open and open_price >= prev_close and close <= prev_open)
    bearish_engulfing_new_low = bool(bearish_engulfing and rolling_low is not None and low <= rolling_low)

    ignition_trigger = open_price + max(prev_high - prev_close, 0) * ignition_multiplier
    ignition_triggered = bool(high >= ignition_trigger and close >= ignition_trigger)
    ignition = {
        "available": True,
        "multiplier": ignition_multiplier,
        "trigger_price": _round(ignition_trigger),
        "triggered": ignition_triggered,
        "source": "today_open_plus_previous_high_close_gap",
    }

    if attack_day and ignition_triggered:
        summary = "攻击日与起爆点同时触发。"
    elif attack_day:
        summary = "出现攻击日事实，但仍需结构和交易计划确认。"
    elif ignition_triggered:
        summary = "起爆点触发，但仍需检查结构止损和收益风险比。"
    elif bearish_engulfing_new_low:
        summary = "出现阴包阳创新低，优先作为观察或风险事实。"
    else:
        summary = "暂无明确攻击日或起爆点事实。"

    return {
        "available": True,
        "attack_day": attack_day,
        "bullish_engulfing": bullish_engulfing,
        "breaks_prev_high": breaks_prev_high,
        "volume_expand": volume_expand,
        "range_expansion": range_expansion,
        "bearish_engulfing_new_low": bearish_engulfing_new_low,
        "ignition": ignition,
        "summary": summary,
    }


def _v2_scores(latest, fractals, rectangle, trigger, clock):
    clock_state = (clock or {}).get("state")
    risk_score = _as_int(latest.get("composite_risk_score"))
    risk_break_score = _as_int(latest.get("composite_risk_break_score"))
    risk_heat_score = _as_int(latest.get("composite_risk_heat_score"))

    research_score = 0
    if clock_state == "countdown":
        research_score += 35
    elif clock_state in {"compression_watch", "expanding"}:
        research_score += 20
    if _as_bool(latest.get("is_bottom_divergence")):
        research_score += 25
    if trigger.get("bearish_engulfing_new_low"):
        research_score += 15
    if _as_bool(latest.get("composite_watch")):
        research_score += 10

    structure_score = 0
    if fractals.get("latest_bottom"):
        structure_score += 25
    if fractals.get("double_bottom_higher_low"):
        structure_score += 35
    if rectangle.get("available"):
        structure_score += 30
    if _as_bool(latest.get("composite_pullback_setup")) or _as_bool(latest.get("composite_breakout_setup")):
        structure_score += 10

    trigger_quality = 0
    if trigger.get("attack_day"):
        trigger_quality += 30
    if (trigger.get("ignition") or {}).get("triggered"):
        trigger_quality += 30
    if _as_bool(latest.get("williams_r_cross_bull")):
        trigger_quality += 15
    if _as_bool(latest.get("composite_prior_breakout")):
        trigger_quality += 15
    if _as_bool(latest.get("composite_entry")):
        trigger_quality += 10

    execution_risk = risk_score * 18 + risk_break_score * 8 + risk_heat_score * 6
    return {
        "research_score": min(100, int(research_score)),
        "structure_score": min(100, int(structure_score)),
        "trigger_quality": min(100, int(trigger_quality)),
        "execution_risk": min(100, int(execution_risk)),
    }


def build_c_signal_v2_facts(df_display, *, clock=None):
    """Build the Phase 2.3 fact payload for the latest bar."""
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "version": 1,
            "source": "c_signal_v2_phase_2_3",
            "latest_date": "-",
            "scores": {"setup": 0, "confirm": 0, "risk": 0},
            "trend": {},
            "setup": {},
            "risk": {},
            "structure": {"candidate": False},
            "trigger": {"available": False},
            "clock": clock or {},
            "v2_scores": {"research_score": 0, "structure_score": 0, "trigger_quality": 0, "execution_risk": 0},
        }

    fractals = build_williams_fractal_facts(df_display)
    rectangle = build_rectangle_facts(df_display)
    trigger = build_trigger_facts(df_display)
    scores = {
        "setup": _as_int(latest.get("composite_setup_score")),
        "confirm": _as_int(latest.get("composite_confirm_score")),
        "risk": _as_int(latest.get("composite_risk_score")),
    }
    structure_candidate = bool(
        fractals.get("double_bottom_higher_low")
        or rectangle.get("available")
        or _as_bool(latest.get("composite_pullback_setup"))
        or _as_bool(latest.get("composite_breakout_setup"))
    )
    trigger_observed = bool(trigger.get("attack_day") or (trigger.get("ignition") or {}).get("triggered"))

    return {
        "version": 1,
        "source": "c_signal_v2_phase_2_3",
        "latest_date": _format_date(latest.get("date")),
        "scores": scores,
        "trend": {
            "above_ma20": bool(_as_float(latest.get("close")) is not None and _as_float(latest.get("ma20")) is not None and _as_float(latest.get("close")) >= _as_float(latest.get("ma20"))),
            "ma20_up": _as_bool(latest.get("ma20_up")),
            "trend_ok": _as_bool(latest.get("trend_ok")),
            "williams_r": _as_float(latest.get("williams_r")),
            "williams_r_center_side": latest.get("williams_r_center_side"),
            "williams_r_cross_bull": _as_bool(latest.get("williams_r_cross_bull")),
            "williams_r_cross_bear": _as_bool(latest.get("williams_r_cross_bear")),
            "bull_power_dominant": _as_bool(latest.get("bull_power_dominant")),
            "bear_power_dominant": _as_bool(latest.get("bear_power_dominant")),
        },
        "setup": {
            "repair_impulse": _as_bool(latest.get("composite_repair_impulse")),
            "repair_confirm": _as_bool(latest.get("composite_repair_confirm")),
            "pullback_setup": _as_bool(latest.get("composite_pullback_setup")),
            "breakout_setup": _as_bool(latest.get("composite_breakout_setup")),
            "prior_breakout": _as_bool(latest.get("composite_prior_breakout")),
            "bottom_divergence": _as_bool(latest.get("is_bottom_divergence")),
        },
        "risk": {
            "risk_score": scores["risk"],
            "risk_break_score": _as_int(latest.get("composite_risk_break_score")),
            "risk_heat_score": _as_int(latest.get("composite_risk_heat_score")),
            "has_risk": _as_bool(latest.get("composite_risk")) or _as_bool(latest.get("composite_risk_warn")),
            "has_exit": _as_bool(latest.get("composite_exit")),
        },
        "clock": {
            "state": (clock or {}).get("state"),
            "state_label": (clock or {}).get("state_label"),
            "action_label": (clock or {}).get("action_label"),
        },
        "structure": {
            "candidate": structure_candidate,
            "trigger_observed": trigger_observed,
            "fractals": fractals,
            "rectangle": rectangle,
            "summary": "结构事实已出现，等待许可和交易计划。" if structure_candidate else "结构事实不足，继续观察。",
        },
        "trigger": trigger,
        "v2_scores": _v2_scores(latest, fractals, rectangle, trigger, clock),
    }
