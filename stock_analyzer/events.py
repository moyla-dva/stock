"""Signal event model and builders shared by serializers, scans, and UI payloads."""

from dataclasses import dataclass


SIGNAL_DEFINITIONS = {
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
    return events


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
    return {
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
