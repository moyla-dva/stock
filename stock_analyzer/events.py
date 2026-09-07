"""Signal event model and builders shared by serializers, scans, and UI payloads."""

from dataclasses import dataclass

from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_facts
from stock_analyzer.c_signal_v2 import c_signal_v2_mark_fields


SIGNAL_DEFINITIONS = {
    "v2_bottom_research": {
        "label": "C研",
        "name": "V2底部研究",
        "detail": "底部观察事实",
        "color": "#3b82f6",
        "category": "bottom",
        "order": 12,
    },
    "v2_structure_candidate": {
        "label": "C候",
        "name": "V2结构候选",
        "detail": "分型/矩形结构",
        "color": "#64748b",
        "category": "candidate",
        "order": 14,
    },
    "v2_attack_day": {
        "label": "C爆",
        "name": "V2攻击日",
        "detail": "攻击日触发",
        "color": "#0f9f6e",
        "category": "entry",
        "order": 16,
    },
    "v2_ignition": {
        "label": "C爆",
        "name": "V2起爆触发",
        "detail": "起爆点触发",
        "color": "#059669",
        "category": "entry",
        "order": 18,
    },
    "v2_bearish_new_low": {
        "label": "C研",
        "name": "V2阴包阳新低",
        "detail": "极端观察",
        "color": "#2563eb",
        "category": "bottom",
        "order": 22,
    },
    "v2_top_fractal_risk": {
        "label": "C风",
        "name": "V2顶分型风控",
        "detail": "顶分型风险",
        "color": "#b7791f",
        "category": "risk",
        "order": 42,
    },
    "composite_pullback": {
        "label": "C回",
        "name": "综合回踩",
        "detail": "持仓候选",
        "color": "#00897b",
        "category": "entry",
        "order": 10,
    },
    "composite_breakout": {
        "label": "C突",
        "name": "综合突破",
        "detail": "前高突破",
        "color": "#00897b",
        "category": "entry",
        "order": 20,
    },
    "composite_confirm": {
        "label": "C观",
        "name": "修复确认",
        "detail": "修复买点",
        "color": "#5f66d6",
        "category": "entry",
        "order": 30,
    },
    "composite_warning": {
        "label": "C预",
        "name": "综合预警",
        "detail": "持仓风险",
        "color": "#b7791f",
        "category": "risk",
        "order": 40,
    },
    "composite_stop_loss": {
        "label": "C止",
        "name": "综合止损",
        "detail": "亏损控制",
        "color": "#c83737",
        "category": "exit",
        "order": 50,
    },
    "composite_take_profit": {
        "label": "C盈",
        "name": "综合止盈",
        "detail": "收益保护",
        "color": "#2f8f46",
        "category": "exit",
        "order": 60,
    },
    "composite_exit": {
        "label": "C退",
        "name": "综合离场",
        "detail": "风险退出",
        "color": "#6f766f",
        "category": "exit",
        "order": 70,
    },
    "composite_bottom_divergence": {
        "label": "C底",
        "name": "综合底背离",
        "detail": "底部观察",
        "color": "#2563eb",
        "category": "bottom",
        "order": 80,
    },
    "composite_top_divergence": {
        "label": "C顶",
        "name": "综合顶背离",
        "detail": "顶部风险",
        "color": "#b7791f",
        "category": "top",
        "order": 90,
    },
    "old_gold": {
        "label": "★B",
        "name": "黄金B点",
        "detail": "左侧异动",
        "color": "#7c3aed",
        "category": "entry",
        "order": 100,
    },
    "old_pullback": {
        "label": "回",
        "name": "回踩买点",
        "detail": "缩量回踩",
        "color": "#5f66d6",
        "category": "entry",
        "order": 110,
    },
    "bottom_divergence": {
        "label": "底",
        "name": "底背离",
        "detail": "背离观察",
        "color": "#2563eb",
        "category": "bottom",
        "order": 120,
    },
    "new_gold": {
        "label": "N★B",
        "name": "新黄金B点",
        "detail": "趋势买点",
        "color": "#1565c0",
        "category": "entry",
        "order": 130,
    },
    "new_pullback": {
        "label": "N回",
        "name": "新回踩买点",
        "detail": "趋势回踩",
        "color": "#1976d2",
        "category": "entry",
        "order": 140,
    },
    "opt_gold": {
        "label": "O★B",
        "name": "优化B点",
        "detail": "优化买点",
        "color": "#ff6f00",
        "category": "entry",
        "order": 150,
    },
    "opt_pullback": {
        "label": "O回",
        "name": "优化回踩",
        "detail": "优化回踩",
        "color": "#ffca28",
        "category": "entry",
        "order": 160,
    },
}


@dataclass(frozen=True)
class SignalEvent:
    key: str
    group: str
    date: str
    coord_price: float
    price: float
    reason: str = ""
    value: str = ""

    @property
    def definition(self):
        return SIGNAL_DEFINITIONS[self.key]

    @property
    def name(self):
        return self.definition["name"]

    @property
    def label(self):
        return self.definition["label"]

    @property
    def color(self):
        return self.definition["color"]

    @property
    def category(self):
        return self.definition["category"]


def signal_definitions_payload():
    return {key: dict(value) for key, value in SIGNAL_DEFINITIONS.items()}


def has_recent_true(df_display, idx, column, lookback):
    if column not in df_display.columns or idx < lookback:
        return False
    return bool(df_display.iloc[idx - lookback:idx + 1][column].fillna(False).any())


def _date_for(row):
    value = row["date"]
    if not hasattr(value, "strftime"):
        return str(value)
    if getattr(value, "hour", 0) or getattr(value, "minute", 0) or getattr(value, "second", 0):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def _event(key, group, row, coord_price, reason="", value=""):
    return SignalEvent(
        key=key,
        group=group,
        date=_date_for(row),
        coord_price=float(coord_price),
        price=float(row["close"]),
        reason=str(reason or ""),
        value=str(value or reason or ""),
    )


def _fact_event(key, group, date, coord_price, price, reason="", value=""):
    return SignalEvent(
        key=key,
        group=group,
        date=str(date),
        coord_price=float(coord_price),
        price=float(price),
        reason=str(reason or ""),
        value=str(value or reason or ""),
    )


def _row_by_date(df_display):
    rows = {}
    for _, row in df_display.iterrows():
        rows[_date_for(row)] = row
    return rows


def _dedupe_append(events, seen, event):
    key = (event.key, event.date)
    if key in seen:
        return
    seen.add(key)
    events.append(event)


def _as_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        return number if number == number else default
    except (TypeError, ValueError):
        return default


def _low_coord(row):
    low = _as_float(row.get("low"), _as_float(row.get("close"), 0.0))
    return low * 0.98


def _high_coord(row):
    high = _as_float(row.get("high"), _as_float(row.get("close"), 0.0))
    return high * 1.02


def build_old_signal_events(df_display):
    events = []
    for idx, row in df_display.iterrows():
        old_gold_b = row["is_b_point"] and has_recent_true(df_display, idx, "is_bottom_divergence", 5)
        if old_gold_b:
            events.append(_event(
                "old_gold",
                "old",
                row,
                row["low"],
                reason="底背离确认后的旧逻辑买点",
                value="黄金底",
            ))
        elif row["is_pullback_b"]:
            events.append(_event(
                "old_pullback",
                "old",
                row,
                row["low"],
                reason="旧逻辑缩量回踩",
                value="缩量回踩",
            ))
        elif row["is_bottom_divergence"]:
            events.append(_event(
                "bottom_divergence",
                "old",
                row,
                row["low"] * 0.98,
                reason="MACD 底背离观察",
                value="底背离",
            ))
    return sorted(events, key=lambda event: (event.date, event.definition["order"]))


def build_v2_signal_events(df_display):
    """Build independent V2 chart events from the V2 fact layer.

    These points are intentionally separate from legacy composite events. They
    express observable V2 facts and permissions, not a replacement for the
    existing scan trigger until later backtests approve that migration.
    """
    events = []
    if df_display is None or df_display.empty or "date" not in df_display.columns:
        return events

    seen = set()
    rows_by_date = _row_by_date(df_display)
    previous_rectangle_available = False
    last_burst_idx = -10

    for idx in range(len(df_display)):
        frame = df_display.iloc[:idx + 1]
        latest = frame.iloc[-1]
        facts = build_c_signal_v2_facts(frame)
        setup = facts.get("setup") or {}
        structure = facts.get("structure") or {}
        trigger = facts.get("trigger") or {}
        fractals = structure.get("fractals") if isinstance(structure.get("fractals"), dict) else {}
        rectangle = structure.get("rectangle") if isinstance(structure.get("rectangle"), dict) else {}
        ignition = trigger.get("ignition") if isinstance(trigger.get("ignition"), dict) else {}

        if setup.get("bottom_divergence"):
            _dedupe_append(events, seen, _event(
                "v2_bottom_research",
                "v2",
                latest,
                _low_coord(latest),
                reason="底背离进入 V2 研究观察",
                value="底部研究",
            ))

        if trigger.get("bearish_engulfing_new_low"):
            _dedupe_append(events, seen, _event(
                "v2_bearish_new_low",
                "v2",
                latest,
                _low_coord(latest),
                reason=trigger.get("summary") or "阴包阳创新低",
                value="极端观察",
            ))

        latest_bottom = fractals.get("latest_bottom") if isinstance(fractals.get("latest_bottom"), dict) else None
        if latest_bottom and fractals.get("double_bottom_higher_low"):
            bottom_row = rows_by_date.get(latest_bottom.get("date"))
            if bottom_row is not None:
                _dedupe_append(events, seen, _fact_event(
                    "v2_structure_candidate",
                    "v2",
                    latest_bottom.get("date"),
                    latest_bottom.get("price"),
                    bottom_row.get("close"),
                    reason="双底分型低点抬高",
                    value="结构候选",
                ))

        latest_top = fractals.get("latest_top") if isinstance(fractals.get("latest_top"), dict) else None
        risk = facts.get("risk") if isinstance(facts.get("risk"), dict) else {}
        if latest_top and (fractals.get("top_lower_high") or (risk.get("risk_heat_score") or 0) >= 2):
            top_row = rows_by_date.get(latest_top.get("date"))
            if top_row is not None:
                _dedupe_append(events, seen, _fact_event(
                    "v2_top_fractal_risk",
                    "v2",
                    latest_top.get("date"),
                    latest_top.get("price"),
                    top_row.get("close"),
                    reason="顶分型确认",
                    value="顶部风险",
                ))

        rectangle_available = bool(rectangle.get("available"))
        if rectangle_available and not previous_rectangle_available:
            _dedupe_append(events, seen, _event(
                "v2_structure_candidate",
                "v2",
                latest,
                _low_coord(latest),
                reason=rectangle.get("summary") or "矩形边界可跟踪",
                value="矩形候选",
            ))
        previous_rectangle_available = rectangle_available

        can_emit_burst = idx - last_burst_idx > 3
        if can_emit_burst and ignition.get("triggered") and trigger.get("attack_day"):
            _dedupe_append(events, seen, _event(
                "v2_ignition",
                "v2",
                latest,
                latest.get("low"),
                reason=trigger.get("summary") or "起爆点触发",
                value=f"起爆 {ignition.get('trigger_price')}",
            ))
            last_burst_idx = idx
        elif can_emit_burst and trigger.get("attack_day"):
            _dedupe_append(events, seen, _event(
                "v2_attack_day",
                "v2",
                latest,
                latest.get("low"),
                reason=trigger.get("summary") or "攻击日触发",
                value="攻击日",
            ))
            last_burst_idx = idx

    return sorted(events, key=lambda event: (event.date, event.definition["order"]))


def build_new_signal_events(df_display):
    events = []
    for idx, row in df_display.iterrows():
        new_gold_b = row["new_is_b_point"] and has_recent_true(df_display, idx, "is_bottom_divergence", 8)
        if new_gold_b:
            events.append(_event(
                "new_gold",
                "new",
                row,
                row["low"],
                reason="新逻辑趋势确认买点",
                value="新黄金底",
            ))
        elif row["new_is_pullback_b"]:
            events.append(_event(
                "new_pullback",
                "new",
                row,
                row["low"],
                reason="新逻辑趋势回踩",
                value="回踩确认",
            ))
    return events


def build_opt_signal_events(df_display):
    events = []
    for _, row in df_display.iterrows():
        if row["opt_is_b_point"]:
            events.append(_event(
                "opt_gold",
                "opt",
                row,
                row["high"],
                reason="优化逻辑买点",
                value="优化B",
            ))
        elif row["opt_is_pullback_b"]:
            events.append(_event(
                "opt_pullback",
                "opt",
                row,
                row["low"],
                reason="优化逻辑回踩",
                value="优化回踩",
            ))
    return events


def build_composite_signal_events(df_display):
    events = []
    for _, row in df_display.iterrows():
        has_composite_event = False
        if row.get("composite_entry", False):
            entry_type = row.get("composite_entry_type", "")
            if entry_type == "pullback":
                key = "composite_pullback"
            elif entry_type == "breakout":
                key = "composite_breakout"
            else:
                key = "composite_confirm"
            events.append(_event(
                key,
                "composite",
                row,
                row["low"],
                reason=row.get("composite_entry_reason", ""),
                value=row.get("composite_entry_reason", ""),
            ))
            has_composite_event = True
        if row.get("composite_exit", False):
            exit_type = row.get("composite_exit_type", "")
            if exit_type == "stop_loss":
                key = "composite_stop_loss"
            elif exit_type == "take_profit":
                key = "composite_take_profit"
            else:
                key = "composite_exit"
            events.append(_event(
                key,
                "composite",
                row,
                row["high"],
                reason=row.get("composite_risk_reason", ""),
                value=row.get("composite_risk_reason", ""),
            ))
            has_composite_event = True
        elif row.get("composite_risk_warn", False):
            events.append(_event(
                "composite_warning",
                "composite",
                row,
                row["high"],
                reason=row.get("composite_risk_reason", ""),
                value=row.get("composite_risk_reason", ""),
            ))
            has_composite_event = True

        if row.get("is_bottom_divergence", False) and not row.get("composite_entry", False):
            events.append(_event(
                "composite_bottom_divergence",
                "composite",
                row,
                row["low"] * 0.98,
                reason="MACD 底背离观察",
                value="底背离",
            ))

        if row.get("is_top_divergence", False) and not has_composite_event:
            events.append(_event(
                "composite_top_divergence",
                "composite",
                row,
                row["high"] * 1.02,
                reason="MACD 顶背离观察",
                value="顶背离",
            ))
    return events


def event_to_mark_point(event):
    definition = event.definition
    label = definition["label"]
    payload = {
        "name": definition["name"],
        "coord": [event.date, event.coord_price],
        "value": event.value,
        "itemStyle": {"color": definition["color"]},
        "label": {"formatter": label, "fontSize": 12, "fontWeight": "bold", "position": "inside"},
        "signalKey": event.key,
        "signalCode": label,
        "signalGroup": event.group,
        "signalCategory": definition["category"],
        "signalLabel": label,
        "signalDetail": definition["detail"],
        "signalColor": definition["color"],
        "signalOrder": definition["order"],
        "date": event.date,
        "price": event.price,
        "reason": event.reason,
    }
    payload.update(c_signal_v2_mark_fields(event.key))
    return payload
