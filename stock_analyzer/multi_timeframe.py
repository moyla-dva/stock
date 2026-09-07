"""Multi-timeframe confirmation helpers for the single-stock analysis view."""

from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.c_signal_v2 import c_signal_v2_fields
from stock_analyzer.events import build_composite_signal_events
from stock_analyzer.intraday_fetcher import fetch_stock_minute_history
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.serializers import analysis_frame_to_chart_payload, latest_score_summary


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _recent_event_summary(frame):
    events = build_composite_signal_events(frame)
    if not events:
        return None
    event = events[-1]
    summary = {
        "key": event.key,
        "signal_key": event.key,
        "label": event.label,
        "signal_label": event.label,
        "name": event.name,
        "signal_name": event.name,
        "date": event.date,
        "reason": event.reason or event.value or "",
        "category": event.category,
    }
    summary.update(c_signal_v2_fields(event.key))
    return summary


def _timeframe_tone(frame, summary):
    latest = frame.iloc[-1] if frame is not None and not frame.empty else {}
    risk = _safe_int(summary.get("risk"))
    confirm = _safe_int(summary.get("confirm"))
    setup = _safe_int(summary.get("setup"))
    watch = bool(summary.get("watch"))
    if latest.get("composite_exit", False) or latest.get("composite_risk", False) or risk >= 3:
        return "risk"
    if latest.get("composite_entry", False) or confirm >= 4:
        return "confirm"
    if latest.get("is_bottom_divergence", False) or watch or setup >= 1:
        return "repair"
    return "watch"


def _timeframe_labels(period_label, role_label, tone, recent_event):
    signal_text = ""
    if recent_event:
        signal_text = recent_event.get("label", "") + recent_event.get("name", "")
        signal_text = signal_text.strip()

    if tone == "risk":
        title = period_label + " 风险偏高"
        detail = signal_text or role_label + "先看支撑是否失守。"
    elif tone == "confirm":
        title = period_label + " 偏强确认"
        detail = signal_text or role_label + "结构已给出参与确认。"
    elif tone == "repair":
        title = period_label + " 修复观察"
        detail = signal_text or role_label + "正在等待更强回踩/放量确认。"
    else:
        title = period_label + " 等待确认"
        detail = signal_text or role_label + "先观察，不急于追价。"
    return title, detail


def summarize_timeframe(frame, *, period_key, period_label, role_label, derived=False):
    if frame is None or frame.empty:
        return {
            "period": period_key,
            "label": period_label,
            "role": role_label,
            "available": False,
            "derived": derived,
            "tone": "muted",
            "title": period_label + " 暂无数据",
            "detail": "当前没有可用周期数据。",
        }

    summary = latest_score_summary(frame)
    recent_event = _recent_event_summary(frame)
    tone = _timeframe_tone(frame, summary)
    title, detail = _timeframe_labels(period_label, role_label, tone, recent_event)
    latest = frame.iloc[-1]
    latest_at = latest["date"].strftime("%Y-%m-%d %H:%M") if hasattr(latest["date"], "strftime") else str(latest["date"])
    return {
        "period": period_key,
        "label": period_label,
        "role": role_label,
        "available": True,
        "derived": derived,
        "tone": tone,
        "title": title,
        "detail": detail,
        "latest_at": latest_at,
        "bars": int(len(frame)),
        "scores": summary,
        "event": recent_event,
    }


def derive_four_hour_frame(minute_raw):
    """Build one A-share 4H/session bar per trading day from 60m bars."""
    minute_frame = normalize_price_frame(minute_raw)
    if minute_frame is None or minute_frame.empty:
        return minute_frame

    frame = minute_frame.copy()
    frame["session_date"] = frame["date"].dt.date
    return frame.groupby("session_date", as_index=False).agg({
        "date": "max",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })


def build_multi_timeframe_payload(code, daily_frame, *, logger=None, verbose=False):
    """Return lightweight daily/60m/4h confirmation summaries for one stock."""
    payload = {
        "daily": summarize_timeframe(
            daily_frame,
            period_key="1d",
            period_label="日线",
            role_label="主趋势",
        ),
        "hour_1": {
            "period": "60m",
            "label": "60m",
            "role": "入场确认",
            "available": False,
            "tone": "muted",
            "title": "60m 等待确认",
            "detail": "分时确认层尚未载入。",
        },
        "hour_4": {
            "period": "4h",
            "label": "4h",
            "role": "结构确认",
            "available": False,
            "derived": True,
            "tone": "muted",
            "title": "4h 等待 60m 数据",
            "detail": "4h 由 60m 合成，分时确认层尚未载入。",
        },
    }

    try:
        minute_raw = fetch_stock_minute_history(
            code,
            period="60",
            days=365,
            adjust="qfq",
            use_cache=True,
            use_disable_proxies=True,
            logger=logger,
            verbose=verbose,
        )
        minute_frame = prepare_analysis_frame(minute_raw, fill_initial_ma20=True)
        payload["hour_1"] = summarize_timeframe(
            minute_frame,
            period_key="60m",
            period_label="60m",
            role_label="入场确认",
        )
        payload["hour_1"]["chart"] = analysis_frame_to_chart_payload(minute_frame)
        hour4_raw = derive_four_hour_frame(minute_raw)
        hour4_frame = prepare_analysis_frame(hour4_raw, fill_initial_ma20=True)
        payload["hour_4"] = summarize_timeframe(
            hour4_frame,
            period_key="4h",
            period_label="4h",
            role_label="结构确认",
            derived=True,
        )
        payload["hour_4"]["chart"] = analysis_frame_to_chart_payload(hour4_frame)
        if payload["hour_4"].get("available"):
            payload["hour_4"]["detail"] = "由 60m 合成。 " + payload["hour_4"].get("detail", "")
    except Exception as exc:
        if logger:
            logger.warning(f"构建 60m 多周期确认失败: {exc}")
        payload["hour_1"] = {
            "period": "60m",
            "label": "60m",
            "role": "入场确认",
            "available": False,
            "tone": "muted",
            "title": "60m 确认失败",
            "detail": f"分时确认层暂不可用：{exc}",
        }

    return payload
