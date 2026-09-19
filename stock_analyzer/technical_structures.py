"""Technical structure interpretation used by the trade decision layer."""

import math

import pandas as pd

from stock_analyzer.c_signal_v2_facts import build_v2_risk_facts


def _as_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def _as_bool(value):
    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def _percentile_rank(series, value):
    clean = pd.Series(series).dropna()
    if clean.empty or value is None:
        return None
    return float((clean <= value).sum() / len(clean) * 100)


def _consecutive_true(mask):
    count = 0
    for value in reversed(list(mask.fillna(False))):
        if not bool(value):
            break
        count += 1
    return count


def build_williams_clock(df_display, lookback=120):
    """Interpret Bollinger bandwidth as the Williams-clock countdown.

    The output deliberately avoids direction prediction. It only says whether
    volatility has contracted enough to deserve attention.
    """
    if df_display is None or df_display.empty:
        return {
            "available": False,
            "state": "no_data",
            "state_label": "无数据",
            "summary": "没有足够数据判断波幅倒计时。",
            "direction": "unknown",
            "direction_label": "方向未知",
            "metrics": {},
            "evidence": [],
            "warnings": ["威廉时钟不是买卖点，只是观察许可。"],
        }

    required = {"upper_band", "lower_band", "boll_mid", "close", "volume"}
    if not required.issubset(set(df_display.columns)):
        return {
            "available": False,
            "state": "missing_columns",
            "state_label": "缺少字段",
            "summary": "缺少布林或成交量字段，暂时无法计算威廉时钟。",
            "direction": "unknown",
            "direction_label": "方向未知",
            "metrics": {},
            "evidence": [],
            "warnings": ["威廉时钟不能用布林上下轨直接买卖。"],
        }

    window = df_display.tail(lookback).copy()
    latest = window.iloc[-1]
    mid = window["boll_mid"].replace(0, pd.NA)
    bandwidth = ((window["upper_band"] - window["lower_band"]) / mid * 100).astype("float64")
    latest_bandwidth = _as_float(bandwidth.iloc[-1])
    bandwidth_percentile = _percentile_rank(bandwidth, latest_bandwidth)
    compression_score = None if bandwidth_percentile is None else round(100 - bandwidth_percentile, 1)

    volume_window = min(120, max(20, len(window)))
    volume_ma = window["volume"].rolling(window=volume_window, min_periods=min(20, len(window))).mean()
    if volume_ma.isna().iloc[-1]:
        volume_ma = window["volume"].expanding(min_periods=1).mean()
    volume_dry = window["volume"] < volume_ma
    volume_dryness_days = _consecutive_true(volume_dry)

    recent_percentiles = [
        _percentile_rank(bandwidth.iloc[:idx + 1], _as_float(bandwidth.iloc[idx]))
        for idx in range(len(bandwidth))
    ]
    recent_compression = any(
        value is not None and value <= 20
        for value in recent_percentiles[-10:]
    )
    previous_bandwidth = _as_float(bandwidth.iloc[-2]) if len(bandwidth) >= 2 else None
    bandwidth_change_pct = None
    if latest_bandwidth is not None and previous_bandwidth and previous_bandwidth != 0:
        bandwidth_change_pct = (latest_bandwidth - previous_bandwidth) / previous_bandwidth * 100
    post_compression_expansion = bool(
        recent_compression
        and bandwidth_change_pct is not None
        and bandwidth_change_pct >= 8
        and (bandwidth_percentile or 0) > 20
    )

    state = "neutral"
    state_label = "波幅正常"
    action_label = "普通观察"
    evidence = []
    if compression_score is not None and compression_score >= 80 and volume_dryness_days >= 5:
        state = "countdown"
        state_label = "波幅倒计时"
        action_label = "开始研究"
        evidence.append("布林带宽处在历史低位，波幅明显收缩")
        evidence.append("成交量持续低于均量，符合缩量观察条件")
    elif post_compression_expansion:
        state = "expanding"
        state_label = "收缩后扩张"
        action_label = "等待方向确认"
        evidence.append("近期有过波幅收缩，现在带宽开始扩张")
    elif compression_score is not None and compression_score >= 70:
        state = "compression_watch"
        state_label = "收缩观察"
        action_label = "加入观察"
        evidence.append("布林带宽偏低，但成交萎缩或持续性还不充分")

    if not evidence:
        evidence.append("暂未看到足够强的波幅坍缩")

    return {
        "available": True,
        "state": state,
        "state_label": state_label,
        "action_label": action_label,
        "summary": (
            "威廉时钟只提示是否值得开始研究，方向仍未知；"
            "后续必须接三重滤网、市场结构和交易计划。"
        ),
        "direction": "unknown",
        "direction_label": "方向未知",
        "metrics": {
            "lookback_days": int(len(window)),
            "bandwidth": None if latest_bandwidth is None else round(latest_bandwidth, 3),
            "bandwidth_percentile": None if bandwidth_percentile is None else round(bandwidth_percentile, 1),
            "compression_score": compression_score,
            "volume_dryness_days": int(volume_dryness_days),
            "bandwidth_change_pct": None if bandwidth_change_pct is None else round(bandwidth_change_pct, 2),
            "post_compression_expansion": post_compression_expansion,
        },
        "evidence": evidence,
        "warnings": [
            "不要用布林上轨/下轨直接当买卖关键点。",
            "收缩后会扩张，但不会告诉你向上还是向下。",
        ],
    }


def build_technical_structures(df_display):
    """Return current technical structures as action evidence, not predictions."""
    if df_display is None or df_display.empty:
        return {
            "version": 1,
            "latest_date": "-",
            "right_side": {"available": False},
            "risk_context": {"available": False},
            "williams_clock": build_williams_clock(df_display),
        }

    latest = df_display.iloc[-1]
    close = _as_float(latest.get("close"))
    ma20 = _as_float(latest.get("ma20"))
    ma20_up = _as_bool(latest.get("ma20_up"))
    trend_ok = _as_bool(latest.get("trend_ok"))
    above_ma20 = bool(close is not None and ma20 is not None and close >= ma20)
    risk_score = int(_as_float(build_v2_risk_facts(df_display).get("risk_score"), 0) or 0)

    return {
        "version": 1,
        "latest_date": _format_date(latest.get("date")),
        "right_side": {
            "available": True,
            "above_ma20": above_ma20,
            "ma20_up": ma20_up,
            "trend_ok": trend_ok,
            "label": "右侧允许观察" if above_ma20 and ma20_up else "右侧不足",
            "detail": "价格在 MA20 上方且均线向上，才更接近右侧处理。" if above_ma20 and ma20_up else "仍需等待价格重新站稳 MA20 或趋势确认。",
        },
        "risk_context": {
            "available": True,
            "risk_score": risk_score,
            "label": "风险可控" if risk_score <= 2 else "风险压制",
            "detail": "风险分低，仍需按止损计划执行。" if risk_score <= 2 else "风险分偏高，先处理保护位，不新增暴露。",
        },
        "williams_clock": build_williams_clock(df_display),
    }
