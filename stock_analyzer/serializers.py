"""Serializers that turn analysis frames into frontend payloads."""

from stock_analyzer.backtest import evaluate_signal_events
from stock_analyzer.events import (
    build_composite_signal_events,
    build_new_signal_events,
    build_old_signal_events,
    build_opt_signal_events,
    event_to_mark_point,
    signal_definitions_payload,
)


def calc_signal_stats(df_display, signal_col, horizon=5, direction="up"):
    future_ret = (df_display["close"].shift(-horizon) - df_display["close"]) / df_display["close"] * 100
    mask = df_display[signal_col].fillna(False)
    if mask.sum() == 0:
        return {"count": 0, "win_rate": None, "avg_ret": None, "horizon": horizon}
    if direction == "up":
        wins = (future_ret > 0) & mask
    else:
        wins = (future_ret < 0) & mask
    win_rate = wins.sum() / mask.sum() * 100
    avg_ret = future_ret[mask].mean()
    return {"count": int(mask.sum()), "win_rate": float(win_rate), "avg_ret": float(avg_ret), "horizon": horizon}


def latest_score_summary(df_display):
    if df_display.empty:
        return {"date": "-", "setup": None, "confirm": None, "risk": None, "watch": False}
    latest = df_display.iloc[-1]
    date = format_axis_date(latest["date"])
    return {
        "date": date,
        "setup": int(latest.get("composite_setup_score", 0)),
        "confirm": int(latest.get("composite_confirm_score", 0)),
        "risk": int(latest.get("composite_risk_score", 0)),
        "watch": bool(latest.get("composite_watch", False)),
    }


def format_axis_date(value):
    if not hasattr(value, "strftime"):
        return str(value)
    if getattr(value, "hour", 0) or getattr(value, "minute", 0) or getattr(value, "second", 0):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def analysis_frame_to_chart_payload(df_display):
    """Convert an analyzed DataFrame into the existing ECharts API payload."""
    dates = [format_axis_date(value) for value in df_display["date"]]
    k_data = df_display[["open", "close", "low", "high"]].values.tolist()
    custom_data = df_display["custom"].fillna(0).tolist()
    dif_data = df_display["dif"].fillna(0).tolist()
    dea_data = df_display["dea"].fillna(0).tolist()
    macd_data = df_display["macd_hist"].fillna(0).tolist()
    ma20_data = df_display["ma20"].fillna(0).tolist()
    vwap_data = df_display["vwap"].bfill().fillna(0).tolist()
    bull_power_data = (
        df_display["bull_power"].fillna(0).tolist()
        if "bull_power" in df_display.columns
        else []
    )
    bear_power_data = (
        df_display["bear_power"].fillna(0).tolist()
        if "bear_power" in df_display.columns
        else []
    )
    williams_r_data = (
        df_display["williams_r"].fillna(50).tolist()
        if "williams_r" in df_display.columns
        else []
    )

    old_events = build_old_signal_events(df_display)
    new_events = build_new_signal_events(df_display)
    opt_events = build_opt_signal_events(df_display)
    composite_events = build_composite_signal_events(df_display)

    mark_points = [event_to_mark_point(event) for event in old_events]
    mark_points_new = [event_to_mark_point(event) for event in new_events]
    mark_points_opt = [event_to_mark_point(event) for event in opt_events]

    mark_points_composite = [
        event_to_mark_point(event)
        for event in composite_events
    ]

    old_b_col = "old_is_entry" if "old_is_entry" in df_display.columns else "is_b_point"
    new_b_col = "new_is_entry" if "new_is_entry" in df_display.columns else "new_is_b_point"
    opt_b_col = "opt_is_entry" if "opt_is_entry" in df_display.columns else "opt_is_b_point"
    stats_old = {
        "b": calc_signal_stats(df_display, old_b_col, direction="up"),
        "s": None,
    }
    stats_new = {
        "b": calc_signal_stats(df_display, new_b_col, direction="up"),
        "s": None,
    }
    stats_opt = {
        "b": calc_signal_stats(df_display, opt_b_col, direction="up"),
        "s": None,
    }
    stats_composite = {
        "b": calc_signal_stats(df_display, "composite_entry", direction="up")
        if "composite_entry" in df_display.columns
        else {"count": 0, "win_rate": None, "avg_ret": None, "horizon": 5},
        "s": calc_signal_stats(df_display, "composite_exit", direction="down")
        if "composite_exit" in df_display.columns
        else {"count": 0, "win_rate": None, "avg_ret": None, "horizon": 5},
    }

    return {
        "dates": dates,
        "k_data": k_data,
        "ma20_data": ma20_data,
        "vwap_data": vwap_data,
        "bull_power_data": bull_power_data,
        "bear_power_data": bear_power_data,
        "williams_r_data": williams_r_data,
        "custom_data": custom_data,
        "dif_data": dif_data,
        "dea_data": dea_data,
        "macd_data": macd_data,
        "mark_points": mark_points,
        "mark_points_old": mark_points,
        "mark_points_new": mark_points_new,
        "mark_points_opt": mark_points_opt,
        "mark_points_composite": mark_points_composite,
        "stats_old": stats_old,
        "stats_new": stats_new,
        "stats_opt": stats_opt,
        "stats_composite": stats_composite,
        "event_stats": {
            "old": evaluate_signal_events(df_display, old_events),
            "new": evaluate_signal_events(df_display, new_events),
            "opt": evaluate_signal_events(df_display, opt_events),
            "composite": evaluate_signal_events(df_display, composite_events),
        },
        "score_summary": latest_score_summary(df_display),
        "signal_definitions": signal_definitions_payload(),
    }
