"""Multi-timeframe confirmation helpers for the single-stock analysis view."""

from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_facts
from stock_analyzer.events import build_v2_signal_events
from stock_analyzer.intraday_fetcher import fetch_stock_minute_history
from stock_analyzer.legacy_c_signal_adapter import c_signal_v2_fields
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.serializers import analysis_frame_to_chart_payload, latest_score_summary
from stock_analyzer.timeframe_chart_cache import get_cached_timeframe_chart_payload

TIMEFRAME_PERIOD_ALIASES = {
    "60m": "hour_1",
    "1h": "hour_1",
    "hour_1": "hour_1",
    "hour1": "hour_1",
    "4h": "hour_4",
    "hour_4": "hour_4",
    "hour4": "hour_4",
}
HOURLY_TIMEFRAME_KEYS = {"hour_1", "hour_4"}
INTRADAY_CHART_EVENT_LOOKBACK = 40


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def signal_event_summary(event):
    if event is None:
        return None
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


def chart_mark_event_summary(point):
    if not isinstance(point, dict):
        return None
    key = point.get("signalKey") or point.get("signal_key") or ""
    if not key:
        return None
    summary = {
        "key": key,
        "signal_key": key,
        "label": point.get("signalLabel") or point.get("signalCode") or "",
        "signal_label": point.get("signalLabel") or point.get("signalCode") or "",
        "name": point.get("name") or "",
        "signal_name": point.get("name") or "",
        "date": point.get("date") or "",
        "reason": point.get("reason") or point.get("value") or "",
        "category": point.get("signalCategory") or "",
    }
    summary.update(c_signal_v2_fields(key))
    return summary


def _recent_chart_event_summary(chart):
    points = chart.get("mark_points_v2") if isinstance(chart, dict) else None
    if not points:
        return None
    return chart_mark_event_summary(points[-1])


def _recent_event_summary(frame, *, events=None):
    events = events if events is not None else build_v2_signal_events(frame, lookback=60)
    if not events:
        return None
    return signal_event_summary(events[-1])


def _timeframe_tone(frame, summary):
    risk = _safe_int(summary.get("risk"))
    confirm = _safe_int(summary.get("confirm"))
    setup = _safe_int(summary.get("setup"))
    watch = bool(summary.get("watch"))
    if risk >= 3:
        return "risk"
    if confirm >= 1:
        return "confirm"
    if setup >= 1 or watch:
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


def summarize_timeframe(
    frame,
    *,
    period_key,
    period_label,
    role_label,
    derived=False,
    score_summary=None,
    recent_event=None,
    recent_events=None,
    skip_event_summary=False,
):
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

    summary = score_summary or latest_score_summary(frame)
    if recent_event is None and not skip_event_summary:
        recent_event = _recent_event_summary(frame, events=recent_events)
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


def normalize_timeframe_period(period):
    """Return the internal payload key for a requested chart period."""
    if period is None:
        return None
    key = str(period).strip().lower().replace("-", "_")
    if not key or key in {"all", "hourly", "timeframes"}:
        return None
    return TIMEFRAME_PERIOD_ALIASES.get(key)


def _normalize_target_periods(target_periods):
    if target_periods is None:
        return set(HOURLY_TIMEFRAME_KEYS)
    if isinstance(target_periods, str):
        target_periods = [target_periods]

    selected = set()
    for period in target_periods:
        key = normalize_timeframe_period(period)
        if key:
            selected.add(key)
    return selected


def _timeframe_fetch_failure(period_key, exc):
    if period_key == "hour_4":
        return {
            "period": "4h",
            "label": "4h",
            "role": "结构确认",
            "available": False,
            "derived": True,
            "tone": "muted",
            "title": "4h 确认失败",
            "detail": f"4h 确认层暂不可用：{exc}",
        }
    return {
        "period": "60m",
        "label": "60m",
        "role": "入场确认",
        "available": False,
        "tone": "muted",
        "title": "60m 确认失败",
        "detail": f"分时确认层暂不可用：{exc}",
    }


def _build_chart_payload(frame, *, event_lookback):
    events = build_v2_signal_events(frame, lookback=event_lookback)
    facts = build_c_signal_v2_facts(frame)
    return analysis_frame_to_chart_payload(
        frame,
        v2_event_lookback=event_lookback,
        v2_events=events,
        facts=facts,
        include_legacy=False,
    )


def _timeframe_chart_payload(
    code,
    period_key,
    frame,
    *,
    event_lookback,
    use_chart_cache,
    force_chart_cache_refresh,
):
    factory = lambda: _build_chart_payload(frame, event_lookback=event_lookback)
    if use_chart_cache:
        return get_cached_timeframe_chart_payload(
            code,
            period_key,
            frame,
            event_lookback,
            factory,
            force_refresh=force_chart_cache_refresh,
            include_legacy=False,
        )
    return factory()


def build_multi_timeframe_payload(
    code,
    daily_frame,
    *,
    logger=None,
    verbose=False,
    allow_fetch=True,
    daily_score_summary=None,
    daily_recent_events=None,
    daily_recent_event=None,
    daily_skip_event_summary=False,
    target_periods=None,
    use_chart_cache=False,
    force_chart_cache_refresh=False,
    intraday_chart_event_lookback=INTRADAY_CHART_EVENT_LOOKBACK,
):
    """Return lightweight daily/60m/4h confirmation summaries for one stock."""
    target_keys = _normalize_target_periods(target_periods)
    payload = {
        "daily": summarize_timeframe(
            daily_frame,
            period_key="1d",
            period_label="日线",
            role_label="主趋势",
            score_summary=daily_score_summary,
            recent_event=daily_recent_event,
            recent_events=daily_recent_events,
            skip_event_summary=daily_skip_event_summary,
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

    if not allow_fetch:
        payload["hour_1"]["detail"] = "分时确认层已延后加载，以保证日线分析先返回。"
        payload["hour_4"]["detail"] = "4h 依赖 60m 数据，点击后再加载分时确认层。"
        payload["hour_1"]["chart_deferred"] = True
        payload["hour_4"]["chart_deferred"] = True
        return payload

    if not target_keys:
        return payload

    try:
        minute_raw = fetch_stock_minute_history(
            code,
            period="60",
            days=365,
            adjust="qfq",
            use_cache=True,
            cache_only=not allow_fetch,
            use_disable_proxies=True,
            logger=logger,
            verbose=verbose,
        )
        if minute_raw is None or minute_raw.empty:
            return payload
        if "hour_1" in target_keys:
            minute_frame = prepare_analysis_frame(minute_raw, fill_initial_ma20=True)
            minute_chart = _timeframe_chart_payload(
                code,
                "hour_1",
                minute_frame,
                event_lookback=intraday_chart_event_lookback,
                use_chart_cache=use_chart_cache,
                force_chart_cache_refresh=force_chart_cache_refresh,
            )
            payload["hour_1"] = summarize_timeframe(
                minute_frame,
                period_key="60m",
                period_label="60m",
                role_label="入场确认",
                score_summary=minute_chart.get("score_summary") if isinstance(minute_chart, dict) else None,
                recent_event=_recent_chart_event_summary(minute_chart),
                skip_event_summary=True,
            )
            payload["hour_1"]["chart"] = minute_chart

        if "hour_4" in target_keys:
            hour4_raw = derive_four_hour_frame(minute_raw)
            hour4_frame = prepare_analysis_frame(hour4_raw, fill_initial_ma20=True)
            hour4_chart = _timeframe_chart_payload(
                code,
                "hour_4",
                hour4_frame,
                event_lookback=intraday_chart_event_lookback,
                use_chart_cache=use_chart_cache,
                force_chart_cache_refresh=force_chart_cache_refresh,
            )
            payload["hour_4"] = summarize_timeframe(
                hour4_frame,
                period_key="4h",
                period_label="4h",
                role_label="结构确认",
                derived=True,
                score_summary=hour4_chart.get("score_summary") if isinstance(hour4_chart, dict) else None,
                recent_event=_recent_chart_event_summary(hour4_chart),
                skip_event_summary=True,
            )
            payload["hour_4"]["chart"] = hour4_chart
            if payload["hour_4"].get("available"):
                payload["hour_4"]["detail"] = "由 60m 合成。 " + payload["hour_4"].get("detail", "")
    except Exception as exc:
        if logger:
            logger.warning(f"构建 60m 多周期确认失败: {exc}")
        for period_key in target_keys:
            payload[period_key] = _timeframe_fetch_failure(period_key, exc)

    return payload
