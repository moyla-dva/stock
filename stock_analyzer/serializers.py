"""Serializers that turn analysis frames into frontend payloads."""

from stock_analyzer.backtest import evaluate_signal_events
from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_facts
from stock_analyzer.events import (
    build_new_signal_events,
    build_old_signal_events,
    build_opt_signal_events,
    build_v2_signal_events,
    event_to_mark_point,
    signal_definitions_payload,
)


DEFAULT_V2_EVENT_LOOKBACK = 60


def _fact_date(value):
    if value is None:
        return ""
    return format_axis_date(value)


def _bottom_fractal_dates(facts):
    structure = facts.get("structure") if isinstance(facts, dict) else {}
    fractals = structure.get("fractals") if isinstance(structure, dict) else {}
    if not isinstance(fractals, dict):
        return set()
    candidates = list(fractals.get("recent_bottoms") or [])
    latest = fractals.get("latest_bottom")
    if isinstance(latest, dict):
        candidates.append(latest)
    output = set()
    for bottom in candidates:
        if not isinstance(bottom, dict):
            continue
        for key in ("date", "source_start_date", "source_end_date"):
            date = _fact_date(bottom.get(key))
            if date and date != "-":
                output.add(date)
    return output


def _annotate_mark_point_display_context(mark_points, facts):
    bottom_dates = _bottom_fractal_dates(facts)
    if not bottom_dates:
        return mark_points
    output = []
    for point in mark_points:
        coord = point.get("coord") or []
        point_date = point.get("date") or (coord[0] if coord else "")
        marker_role = point.get("markerRole") or point.get("marker_role") or ""
        signal = point.get("v2_signal") or point.get("signalLabel") or point.get("signalCode") or ""
        if point_date in bottom_dates and marker_role in {"sell", "scale_out"} and signal in {"C风", "C盈"}:
            point = dict(point)
            point["same_day_bottom_candidate"] = True
            point["display_context_hint"] = "break_with_bottom_fractal"
        output.append(point)
    return output


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


def latest_score_summary(df_display, *, facts=None):
    if df_display.empty:
        return {"date": "-", "setup": None, "confirm": None, "risk": None, "watch": False}
    latest = df_display.iloc[-1]
    date = format_axis_date(latest["date"])
    facts = facts if isinstance(facts, dict) else build_c_signal_v2_facts(df_display)
    scores = facts.get("scores") if isinstance(facts.get("scores"), dict) else {}
    setup = facts.get("setup") if isinstance(facts.get("setup"), dict) else {}
    return {
        "date": date,
        "setup": int(scores.get("setup") or 0),
        "confirm": int(scores.get("confirm") or 0),
        "risk": int(scores.get("risk") or 0),
        "watch": bool(setup.get("pullback_setup") or setup.get("breakout_setup")),
    }


def format_axis_date(value):
    if not hasattr(value, "strftime"):
        return str(value)
    if getattr(value, "hour", 0) or getattr(value, "minute", 0) or getattr(value, "second", 0):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def analysis_frame_to_chart_payload(
    df_display,
    *,
    v2_event_lookback=DEFAULT_V2_EVENT_LOOKBACK,
    v2_events=None,
    facts=None,
    include_legacy=False,
):
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

    if v2_events is None:
        v2_events = build_v2_signal_events(df_display, lookback=v2_event_lookback)

    facts = facts if isinstance(facts, dict) else build_c_signal_v2_facts(df_display)

    mark_points_v2 = [
        event_to_mark_point(event)
        for event in v2_events
    ]
    mark_points_v2 = _annotate_mark_point_display_context(mark_points_v2, facts)

    payload = {
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
        "mark_points": mark_points_v2,
        "mark_points_v2": mark_points_v2,
        "v2_event_lookback": v2_event_lookback,
        "event_stats": {
            "v2": evaluate_signal_events(df_display, v2_events),
        },
        "score_summary": latest_score_summary(df_display, facts=facts),
        "signal_definitions": signal_definitions_payload(),
    }

    if include_legacy:
        old_events = build_old_signal_events(df_display)
        new_events = build_new_signal_events(df_display)
        opt_events = build_opt_signal_events(df_display)
        mark_points_old = [event_to_mark_point(event) for event in old_events]
        mark_points_new = [event_to_mark_point(event) for event in new_events]
        mark_points_opt = [event_to_mark_point(event) for event in opt_events]
        old_b_col = "old_is_entry" if "old_is_entry" in df_display.columns else "is_b_point"
        new_b_col = "new_is_entry" if "new_is_entry" in df_display.columns else "new_is_b_point"
        opt_b_col = "opt_is_entry" if "opt_is_entry" in df_display.columns else "opt_is_b_point"
        payload.update({
            "mark_points": mark_points_old,
            "mark_points_old": mark_points_old,
            "mark_points_new": mark_points_new,
            "mark_points_opt": mark_points_opt,
            "stats_old": {
                "b": calc_signal_stats(df_display, old_b_col, direction="up"),
                "s": None,
            },
            "stats_new": {
                "b": calc_signal_stats(df_display, new_b_col, direction="up"),
                "s": None,
            },
            "stats_opt": {
                "b": calc_signal_stats(df_display, opt_b_col, direction="up"),
                "s": None,
            },
        })
        payload["event_stats"].update({
            "old": evaluate_signal_events(df_display, old_events),
            "new": evaluate_signal_events(df_display, new_events),
            "opt": evaluate_signal_events(df_display, opt_events),
        })

    return payload
