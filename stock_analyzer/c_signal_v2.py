"""C signal V2 semantic contract layered on top of legacy signal events."""

from copy import deepcopy


_V2_BY_EVENT_KEY = {
    "composite_pullback": {
        "v2_signal": "C回",
        "v2_signal_name": "回踩入场",
        "v2_state": "entry_pullback",
        "v2_state_label": "回踩可交易",
        "v2_role": "entry",
        "v2_role_label": "可交易",
        "v2_tone": "positive",
        "trade_intent": "pullback_entry",
        "trade_intent_label": "可按回踩计划执行",
        "requires_trade_plan": True,
        "requires_stop_loss": True,
        "v2_plan_scope": "entry_plan_required",
        "v2_detail": "结构回踩获得趋势确认后，必须再经过入场价、止损、收益风险比和仓位校验。",
    },
    "composite_breakout": {
        "v2_signal": "C突",
        "v2_signal_name": "突破入场",
        "v2_state": "entry_breakout",
        "v2_state_label": "突破可交易",
        "v2_role": "entry",
        "v2_role_label": "可交易",
        "v2_tone": "positive",
        "trade_intent": "breakout_entry",
        "trade_intent_label": "可按突破计划执行",
        "requires_trade_plan": True,
        "requires_stop_loss": True,
        "v2_plan_scope": "entry_plan_required",
        "v2_detail": "突破事件只给出入场许可，追高、止损和 2R 要交给交易计划继续拦截。",
    },
    "composite_confirm": {
        "v2_signal": "C修",
        "v2_signal_name": "修复观察",
        "v2_state": "repair_watch",
        "v2_state_label": "修复观察",
        "v2_role": "watch",
        "v2_role_label": "观察",
        "v2_tone": "warning",
        "trade_intent": "watch_only",
        "trade_intent_label": "观察，不入场",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "invalid_condition_only",
        "v2_detail": "修复信号只说明左侧结构在改善，还没有进入可执行入场。",
    },
    "composite_bottom_divergence": {
        "v2_signal": "C研",
        "v2_signal_name": "底部研究",
        "v2_state": "research_bottom",
        "v2_state_label": "底部观察",
        "v2_role": "watch",
        "v2_role_label": "观察",
        "v2_tone": "muted",
        "trade_intent": "watch_only",
        "trade_intent_label": "研究观察",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "invalid_condition_only",
        "v2_detail": "底背离只进入研究池，需要后续结构和触发器确认。",
    },
    "composite_top_divergence": {
        "v2_signal": "C风",
        "v2_signal_name": "顶部风控",
        "v2_state": "risk_top_watch",
        "v2_state_label": "顶部风险",
        "v2_role": "risk",
        "v2_role_label": "风控",
        "v2_tone": "warning",
        "trade_intent": "risk_control",
        "trade_intent_label": "检查持仓风险",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "risk_action",
        "v2_detail": "顶部背离优先提示风险，不负责给出新的买入理由。",
    },
    "composite_warning": {
        "v2_signal": "C风",
        "v2_signal_name": "风险预警",
        "v2_state": "risk_warning",
        "v2_state_label": "风险预警",
        "v2_role": "risk",
        "v2_role_label": "风控",
        "v2_tone": "warning",
        "trade_intent": "risk_control",
        "trade_intent_label": "检查持仓风险",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "risk_action",
        "v2_detail": "风险条件出现时先处理仓位和保护利润，不新增入场许可。",
    },
    "composite_stop_loss": {
        "v2_signal": "C风",
        "v2_signal_name": "止损风控",
        "v2_state": "risk_stop_loss",
        "v2_state_label": "止损风控",
        "v2_role": "risk",
        "v2_role_label": "风控",
        "v2_tone": "danger",
        "trade_intent": "risk_control",
        "trade_intent_label": "执行止损纪律",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "risk_action",
        "v2_detail": "已进入止损处理，不再参与机会排序解释。",
    },
    "composite_take_profit": {
        "v2_signal": "C风",
        "v2_signal_name": "收益保护",
        "v2_state": "risk_take_profit",
        "v2_state_label": "收益保护",
        "v2_role": "risk",
        "v2_role_label": "风控",
        "v2_tone": "warning",
        "trade_intent": "risk_control",
        "trade_intent_label": "保护利润",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "risk_action",
        "v2_detail": "已有收益后的风控提示，优先看减仓或保护利润。",
    },
    "composite_exit": {
        "v2_signal": "C风",
        "v2_signal_name": "趋势离场",
        "v2_state": "risk_exit",
        "v2_state_label": "趋势离场",
        "v2_role": "risk",
        "v2_role_label": "风控",
        "v2_tone": "danger",
        "trade_intent": "risk_control",
        "trade_intent_label": "退出或暂停",
        "requires_trade_plan": False,
        "requires_stop_loss": False,
        "v2_plan_scope": "risk_action",
        "v2_detail": "趋势或计划已经破坏，先退出风险再看下一轮结构。",
    },
}

_LEGACY_ENTRY_KEYS = {
    "old_gold",
    "old_pullback",
    "new_gold",
    "new_pullback",
    "opt_gold",
    "opt_pullback",
}

_DEFAULT_V2 = {
    "v2_signal": "C候",
    "v2_signal_name": "结构候选",
    "v2_state": "structure_candidate",
    "v2_state_label": "结构候选",
    "v2_role": "candidate",
    "v2_role_label": "候选",
    "v2_tone": "muted",
    "trade_intent": "watch_only",
    "trade_intent_label": "候选观察",
    "requires_trade_plan": False,
    "requires_stop_loss": False,
    "v2_plan_scope": "invalid_condition_only",
    "v2_detail": "该事件只作为结构证据进入候选，不直接生成交易动作。",
}

_CAMEL_KEYS = {
    "v2_signal": "v2Signal",
    "v2_signal_name": "v2SignalName",
    "v2_state": "v2State",
    "v2_state_label": "v2StateLabel",
    "v2_role": "v2Role",
    "v2_role_label": "v2RoleLabel",
    "v2_tone": "v2Tone",
    "trade_intent": "tradeIntent",
    "trade_intent_label": "tradeIntentLabel",
    "requires_trade_plan": "requiresTradePlan",
    "requires_stop_loss": "requiresStopLoss",
    "v2_plan_scope": "v2PlanScope",
    "v2_detail": "v2Detail",
}


def c_signal_v2_fields(event_key):
    """Return V2 semantic fields for a legacy signal event key."""
    if event_key in _LEGACY_ENTRY_KEYS:
        return deepcopy(_DEFAULT_V2)
    return deepcopy(_V2_BY_EVENT_KEY.get(event_key, _DEFAULT_V2))


def c_signal_v2_mark_fields(event_key):
    """Return camelCase V2 fields for chart mark point payloads."""
    fields = c_signal_v2_fields(event_key)
    return {
        camel_key: fields[snake_key]
        for snake_key, camel_key in _CAMEL_KEYS.items()
    }
