"""Signal event model and builders shared by serializers, scans, and UI payloads."""

from dataclasses import dataclass

from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_facts
from stock_analyzer.legacy_c_signal_adapter import c_signal_v2_mark_fields


SIGNAL_DEFINITIONS = {
    "v2_bottom_research": {
        "label": "C研",
        "name": "V2底部研究",
        "detail": "底部观察事实",
        "color": "#3b82f6",
        "category": "bottom",
        "marker_role": "observe",
        "marker_level": "normal",
        "marker_reason": "bottom_research",
        "order": 12,
    },
    "v2_repair_watch": {
        "label": "C修",
        "name": "V2修复观察",
        "detail": "底背离后的修复事实",
        "color": "#7c3aed",
        "category": "bottom",
        "marker_role": "observe",
        "marker_level": "normal",
        "marker_reason": "repair_watch",
        "order": 13,
    },
    "v2_structure_candidate": {
        "label": "C候",
        "name": "V2结构候选",
        "detail": "分型/矩形结构",
        "color": "#64748b",
        "category": "candidate",
        "marker_role": "observe",
        "marker_level": "normal",
        "marker_reason": "structure_candidate",
        "order": 14,
    },
    "v2_attack_day": {
        "label": "C爆",
        "name": "V2攻击日",
        "detail": "攻击日触发",
        "color": "#0f9f6e",
        "category": "entry",
        "marker_role": "buy",
        "marker_level": "strong",
        "marker_reason": "attack_day",
        "order": 16,
    },
    "v2_ignition": {
        "label": "C爆",
        "name": "V2起爆触发",
        "detail": "起爆点触发",
        "color": "#059669",
        "category": "entry",
        "marker_role": "buy",
        "marker_level": "strong",
        "marker_reason": "ignition",
        "order": 18,
    },
    "v2_bearish_new_low": {
        "label": "C研",
        "name": "V2阴包阳新低",
        "detail": "极端观察",
        "color": "#2563eb",
        "category": "bottom",
        "marker_role": "observe",
        "marker_level": "normal",
        "marker_reason": "bearish_new_low",
        "order": 22,
    },
    "v2_breakout": {
        "label": "C突",
        "name": "V2突破入场",
        "detail": "矩形上沿或前高突破",
        "color": "#00897b",
        "category": "entry",
        "marker_role": "buy",
        "marker_level": "strong",
        "marker_reason": "breakout",
        "order": 15,
    },
    "v2_pullback": {
        "label": "C回",
        "name": "V2回踩入场",
        "detail": "回踩确认触发",
        "color": "#00897b",
        "category": "entry",
        "marker_role": "buy",
        "marker_level": "strong",
        "marker_reason": "pullback",
        "order": 14,
    },
    "v2_risk_break": {
        "label": "C风",
        "name": "V2破位风控",
        "detail": "结构破位风险",
        "color": "#c83737",
        "category": "risk",
        "marker_role": "scale_out",
        "marker_level": "strong",
        "marker_reason": "risk_break",
        "order": 43,
    },
    "v2_risk_heat": {
        "label": "C风",
        "name": "V2过热风控",
        "detail": "过热风险",
        "color": "#d97706",
        "category": "risk",
        "marker_role": "scale_out",
        "marker_level": "normal",
        "marker_reason": "risk_heat",
        "order": 42,
    },
    "v2_top_fractal_observe": {
        "label": "C研",
        "name": "V2顶分型观察",
        "detail": "局部阻力观察",
        "color": "#b7791f",
        "category": "top",
        "marker_role": "observe",
        "marker_level": "weak",
        "marker_reason": "top_fractal",
        "order": 41,
    },
    "v2_top_fractal_risk": {
        "label": "C研",
        "name": "V2顶分型观察",
        "detail": "局部阻力观察",
        "color": "#b7791f",
        "category": "top",
        "marker_role": "observe",
        "marker_level": "weak",
        "marker_reason": "top_fractal",
        "order": 42,
    },
    "v2_strong_resistance_scale_out": {
        "label": "C盈",
        "name": "V2强阻减仓",
        "detail": "强阻减仓建议",
        "color": "#d97706",
        "category": "risk",
        "marker_role": "scale_out",
        "marker_level": "normal",
        "marker_reason": "strong_resistance",
        "order": 44,
    },
    "v2_exit_gate_sell": {
        "label": "C风",
        "name": "V2防守离场",
        "detail": "Exit Gate离场",
        "color": "#c83737",
        "category": "exit",
        "marker_role": "sell",
        "marker_level": "strong",
        "marker_reason": "trailing_stop_break",
        "order": 46,
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


def event_date_key(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value)
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return text


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


def _marker_role_for(definition):
    role = definition.get("marker_role")
    if role:
        return role
    category = definition.get("category")
    if category == "entry":
        return "buy"
    if category == "exit":
        return "sell"
    if category == "risk":
        return "scale_out"
    return "observe"


def _marker_level_for(definition):
    level = definition.get("marker_level")
    if level:
        return level
    category = definition.get("category")
    if category in {"entry", "exit"}:
        return "strong"
    if category == "risk":
        return "normal"
    return "weak"


def _marker_reason_for(event, definition):
    return definition.get("marker_reason") or event.key


def _row_by_date(df_display):
    rows = {}
    for _, row in df_display.iterrows():
        display_date = _date_for(row)
        rows[display_date] = row
        rows[event_date_key(display_date)] = row
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


def build_v2_signal_events(df_display, lookback=None):
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
    start_idx = 0
    if lookback:
        start_idx = max(0, len(df_display) - int(lookback))
        if start_idx > 0:
            previous_facts = build_c_signal_v2_facts(df_display.iloc[:start_idx])
            previous_structure = previous_facts.get("structure") if isinstance(previous_facts.get("structure"), dict) else {}
            previous_rectangle = (
                previous_structure.get("rectangle")
                if isinstance(previous_structure.get("rectangle"), dict)
                else {}
            )
            previous_rectangle_available = bool(previous_rectangle.get("available"))

    for idx in range(start_idx, len(df_display)):
        frame = df_display.iloc[:idx + 1]
        latest = frame.iloc[-1]
        facts = build_c_signal_v2_facts(frame)
        setup = facts.get("setup") or {}
        structure = facts.get("structure") or {}
        trigger = facts.get("trigger") or {}
        fractals = structure.get("fractals") if isinstance(structure.get("fractals"), dict) else {}
        rectangle = structure.get("rectangle") if isinstance(structure.get("rectangle"), dict) else {}
        ignition = trigger.get("ignition") if isinstance(trigger.get("ignition"), dict) else {}
        exit_gate = facts.get("exit_gate") if isinstance(facts.get("exit_gate"), dict) else {}
        repair = facts.get("repair") if isinstance(facts.get("repair"), dict) else {}

        if repair.get("stage") == "repair_setup":
            _dedupe_append(events, seen, _event(
                "v2_repair_watch",
                "v2",
                latest,
                _low_coord(latest),
                reason=repair.get("summary") or "底背离后进入 V2 修复观察",
                value="修复观察",
            ))
        elif setup.get("bottom_divergence"):
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
                    "v2_top_fractal_observe",
                    "v2",
                    latest_top.get("date"),
                    latest_top.get("price"),
                    top_row.get("close"),
                    reason="顶分型确认",
                    value="顶部观察",
                ))

        exit_action = exit_gate.get("action")
        if exit_action in {"scale_out", "sell"}:
            _dedupe_append(events, seen, _event(
                "v2_exit_gate_sell" if exit_action == "sell" else "v2_strong_resistance_scale_out",
                "v2",
                latest,
                latest.get("high"),
                reason=exit_gate.get("summary") or "Exit Gate 触发",
                value=exit_gate.get("marker_reason") or exit_action,
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


def event_to_mark_point(event):
    definition = event.definition
    label = definition["label"]
    marker_role = _marker_role_for(definition)
    marker_level = _marker_level_for(definition)
    marker_reason = _marker_reason_for(event, definition)
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
        "markerRole": marker_role,
        "markerLevel": marker_level,
        "markerReason": marker_reason,
        "date": event.date,
        "price": event.price,
        "reason": event.reason,
    }
    payload.update(c_signal_v2_mark_fields(event.key))
    return payload
