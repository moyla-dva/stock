"""C signal V2 semantic contract layered on top of legacy signal events."""

from copy import deepcopy

from stock_analyzer.market_permission import build_stock_trade_permission
from stock_analyzer.technical_structures import build_technical_structures


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
    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def _latest_row(df_display):
    if df_display is None or df_display.empty:
        return None
    return df_display.iloc[-1]


def _v2_state_contract(signal_key, *, state, state_label, permission, permission_label, reason, next_action):
    fields = c_signal_v2_fields(signal_key)
    return {
        "state": state,
        "state_label": state_label,
        "permission": permission,
        "permission_label": permission_label,
        "signal": fields["v2_signal"],
        "signal_name": fields["v2_signal_name"],
        "role": fields["v2_role"],
        "role_label": fields["v2_role_label"],
        "tone": fields["v2_tone"],
        "trade_intent": fields["trade_intent"],
        "trade_intent_label": fields["trade_intent_label"],
        "requires_trade_plan": fields["requires_trade_plan"],
        "requires_stop_loss": fields["requires_stop_loss"],
        "plan_scope": fields["v2_plan_scope"],
        "detail": fields["v2_detail"],
        "reason": reason,
        "next_action": next_action,
    }


def build_c_signal_v2_state(df_display, *, event_key=None, context=None):
    """Build the Phase 2.1 V2 state model from current facts.

    This does not replace the legacy strategy trigger yet. It creates a stable
    fact -> state -> permission -> action contract so later V2 trigger modules
    can plug in without changing the UI payload shape.
    """
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "version": 1,
            "source": "c_signal_v2_phase_2_1",
            "latest_date": "-",
            **_v2_state_contract(
                "",
                state="no_data",
                state_label="无数据",
                permission="forbidden",
                permission_label="禁止",
                reason="没有足够行情数据",
                next_action="先补齐行情数据",
            ),
            "scores": {"setup": 0, "confirm": 0, "risk": 0},
            "facts": {},
            "event_mapping": c_signal_v2_fields(event_key) if event_key else None,
        }

    permission_payload = build_stock_trade_permission(df_display, context=context)
    structures = build_technical_structures(df_display)
    scores = {
        "setup": _as_int(latest.get("composite_setup_score")),
        "confirm": _as_int(latest.get("composite_confirm_score")),
        "risk": _as_int(latest.get("composite_risk_score")),
    }
    entry_type = str(latest.get("composite_entry_type") or "").strip()
    exit_type = str(latest.get("composite_exit_type") or latest.get("composite_risk_type") or "").strip()
    has_entry = _as_bool(latest.get("composite_entry"))
    has_exit = _as_bool(latest.get("composite_exit"))
    has_risk = _as_bool(latest.get("composite_risk")) or _as_bool(latest.get("composite_risk_warn"))
    has_bottom = _as_bool(latest.get("is_bottom_divergence"))
    clock = structures.get("williams_clock", {})

    right_side = structures.get("right_side", {})
    facts = {
        "trend": {
            "above_ma20": right_side.get("above_ma20"),
            "ma20_up": right_side.get("ma20_up"),
            "trend_ok": right_side.get("trend_ok"),
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
            "bottom_divergence": has_bottom,
        },
        "risk": {
            "risk_score": scores["risk"],
            "risk_break_score": _as_int(latest.get("composite_risk_break_score")),
            "risk_heat_score": _as_int(latest.get("composite_risk_heat_score")),
            "has_risk": has_risk,
            "has_exit": has_exit,
        },
        "clock": {
            "state": clock.get("state"),
            "state_label": clock.get("state_label"),
            "action_label": clock.get("action_label"),
        },
    }

    if has_exit or permission_payload.get("mode") == "risk_control" or scores["risk"] >= 4:
        risk_key = "composite_exit"
        if exit_type == "stop_loss":
            risk_key = "composite_stop_loss"
        elif exit_type == "take_profit":
            risk_key = "composite_take_profit"
        contract = _v2_state_contract(
            risk_key,
            state="risk_control",
            state_label="风险处理",
            permission="risk_only",
            permission_label="只处理风险",
            reason=latest.get("composite_risk_reason") or "风险分过高或离场信号已触发",
            next_action=permission_payload.get("risk_action") or "停止新开，优先处理风险",
        )
    elif permission_payload.get("can_open") and entry_type == "breakout":
        contract = _v2_state_contract(
            "composite_breakout",
            state="breakout_triggered",
            state_label="突破触发",
            permission="breakout_allowed",
            permission_label="允许突破计划",
            reason=latest.get("composite_entry_reason") or "突破条件已出现",
            next_action="进入突破交易计划，检查高开、过热、止损和 2R",
        )
    elif permission_payload.get("can_open") and entry_type == "pullback":
        contract = _v2_state_contract(
            "composite_pullback",
            state="pullback_triggered",
            state_label="回踩触发",
            permission="pullback_allowed",
            permission_label="允许回踩计划",
            reason=latest.get("composite_entry_reason") or "回踩条件已出现",
            next_action="进入回踩交易计划，检查结构止损、仓位和 2R",
        )
    elif has_entry or _as_bool(latest.get("composite_repair_confirm")):
        contract = _v2_state_contract(
            "composite_confirm",
            state="repair_setup",
            state_label="修复观察",
            permission="watch_only",
            permission_label="只观察",
            reason=latest.get("composite_entry_reason") or "修复信号尚未进入可执行入场",
            next_action="等待结构触发，不提前重仓",
        )
    elif facts["setup"]["breakout_setup"]:
        contract = _v2_state_contract(
            "",
            state="breakout_setup",
            state_label="突破准备",
            permission="watch_only",
            permission_label="只观察",
            reason="价格靠近突破语境，但尚未进入可执行触发",
            next_action="等待明确突破触发，再交给交易计划",
        )
    elif facts["setup"]["pullback_setup"]:
        contract = _v2_state_contract(
            "",
            state="pullback_setup",
            state_label="回踩蓄势",
            permission="watch_only",
            permission_label="只观察",
            reason="价格回到可观察支撑语境，但还缺执行许可",
            next_action="等待回踩触发和风险下降",
        )
    elif has_bottom:
        contract = _v2_state_contract(
            "composite_bottom_divergence",
            state="research_bottom",
            state_label="底部研究",
            permission="watch_only",
            permission_label="只观察",
            reason="出现底背离观察事实",
            next_action="等待分型、矩形或触发器确认",
        )
    elif clock.get("state") in {"countdown", "compression_watch", "expanding"} or scores["setup"] >= 1:
        contract = _v2_state_contract(
            "composite_bottom_divergence",
            state="researchable",
            state_label="值得研究",
            permission="watch_only",
            permission_label="只观察",
            reason=clock.get("state_label") or "出现观察级结构事实",
            next_action=clock.get("action_label") or "加入观察，等待方向和触发",
        )
    else:
        contract = _v2_state_contract(
            "",
            state="idle",
            state_label="无结构",
            permission="forbidden",
            permission_label="禁止",
            reason="没有足够结构证据",
            next_action="继续等待新的事实信号",
        )

    return {
        "version": 1,
        "source": "c_signal_v2_phase_2_1",
        "latest_date": _format_date(latest.get("date")),
        **contract,
        "scores": scores,
        "facts": facts,
        "permission_context": {
            "mode": permission_payload.get("mode"),
            "mode_label": permission_payload.get("mode_label"),
            "can_open": permission_payload.get("can_open"),
            "can_hold": permission_payload.get("can_hold"),
        },
        "event_mapping": c_signal_v2_fields(event_key) if event_key else None,
    }


def build_c_signal_v2_state_from_result(result):
    """Build a lightweight V2 state model from a persisted scan result."""
    result = result or {}
    signal_key = result.get("signal_key") or ""
    fields = c_signal_v2_fields(signal_key)
    risk_score = _as_int(result.get("risk_score"))
    confirm_score = _as_int(result.get("confirm_score"))
    setup_score = _as_int(result.get("setup_score"))
    scan_type = result.get("scan_type") or result.get("_scan_type") or ""
    role = fields.get("v2_role")

    if role == "risk" or scan_type == "risk":
        state = fields.get("v2_state") if role == "risk" else "risk_control"
        state_label = fields.get("v2_state_label") if role == "risk" else "风险处理"
        permission = "risk_only"
        permission_label = "只处理风险"
    elif fields.get("requires_trade_plan"):
        is_breakout = signal_key == "composite_breakout"
        state = "breakout_triggered" if is_breakout else "pullback_triggered"
        state_label = "突破触发" if is_breakout else "回踩触发"
        permission = "breakout_allowed" if is_breakout else "pullback_allowed"
        permission_label = "允许突破计划" if is_breakout else "允许回踩计划"
    elif role in {"watch", "candidate"}:
        state = fields.get("v2_state") or "structure_candidate"
        state_label = fields.get("v2_state_label") or fields.get("v2_role_label") or "观察"
        permission = "watch_only"
        permission_label = "只观察"
    else:
        state = "idle"
        state_label = "无结构"
        permission = "forbidden"
        permission_label = "禁止"

    return {
        "version": 1,
        "source": "scan_result_backfill",
        "latest_date": result.get("date") or "-",
        "event_date": result.get("event_date") or result.get("date") or "-",
        "state": state,
        "state_label": state_label,
        "permission": permission,
        "permission_label": permission_label,
        "signal": fields["v2_signal"],
        "signal_name": fields["v2_signal_name"],
        "role": fields["v2_role"],
        "role_label": fields["v2_role_label"],
        "tone": fields["v2_tone"],
        "trade_intent": fields["trade_intent"],
        "trade_intent_label": fields["trade_intent_label"],
        "requires_trade_plan": fields["requires_trade_plan"],
        "requires_stop_loss": fields["requires_stop_loss"],
        "plan_scope": fields["v2_plan_scope"],
        "detail": fields["v2_detail"],
        "reason": result.get("reason") or fields["v2_detail"],
        "next_action": result.get("trade_intent_label") or fields["trade_intent_label"],
        "scores": {
            "setup": setup_score,
            "confirm": confirm_score,
            "risk": risk_score,
        },
        "facts": {
            "snapshot": True,
            "source_label": result.get("strategy_source_label") or result.get("snapshot_strategy_label") or "",
        },
        "event_mapping": fields,
    }


_V2_PRIORITY_GROUPS = {
    "trade_ready": {
        "label": "可执行计划",
        "detail": "V2 已进入入场许可，仍需交易计划校验止损、仓位和收益风险比。",
        "tone": "positive",
        "queue_priority": 5,
    },
    "repair_watch": {
        "label": "修复观察",
        "detail": "结构在修复，但尚未进入可执行入场许可。",
        "tone": "warning",
        "queue_priority": 4,
    },
    "research_watch": {
        "label": "研究观察",
        "detail": "只进入研究或观察，不生成交易计划。",
        "tone": "muted",
        "queue_priority": 3,
    },
    "structure_watch": {
        "label": "结构备选",
        "detail": "存在结构线索，但确认不足或仍需等待触发。",
        "tone": "muted",
        "queue_priority": 2,
    },
    "risk_control": {
        "label": "风险处理",
        "detail": "优先处理止损、趋势破坏或收益保护，不新增入场暴露。",
        "tone": "danger",
        "queue_priority": 1,
    },
    "blocked": {
        "label": "禁止",
        "detail": "当前没有足够的 V2 结构或许可。",
        "tone": "muted",
        "queue_priority": 0,
    },
}


def _v2_priority_group(scan_type, state_model):
    permission = state_model.get("permission") or ""
    state = state_model.get("state") or ""
    role = state_model.get("role") or ""

    if permission == "risk_only" or role == "risk":
        return "risk_control"
    if permission in {"breakout_allowed", "pullback_allowed"}:
        return "trade_ready"
    if state in {"repair_setup", "repair_watch"}:
        return "repair_watch"
    if state in {"research_bottom", "researchable"}:
        return "research_watch"
    if permission == "watch_only":
        return "structure_watch"
    return "blocked"


def _v2_priority_base(scan_type, group_key, permission):
    if scan_type == "risk":
        return {
            "risk_control": 500,
            "repair_watch": 120,
            "research_watch": 90,
            "structure_watch": 80,
            "trade_ready": 60,
            "blocked": 0,
        }.get(group_key, 0)
    if scan_type == "bottom_div":
        return {
            "trade_ready": 420,
            "repair_watch": 390,
            "research_watch": 330,
            "structure_watch": 260,
            "risk_control": 120,
            "blocked": 0,
        }.get(group_key, 0)
    return {
        "trade_ready": 520 if permission == "breakout_allowed" else 500,
        "repair_watch": 360,
        "research_watch": 210,
        "structure_watch": 180,
        "risk_control": 60,
        "blocked": 0,
    }.get(group_key, 0)


def build_c_signal_v2_priority(result):
    """Return the V2 system-priority contract for a scan result."""
    result = result or {}
    state_model = result.get("v2_state_model") or result.get("c_signal_v2_state")
    if not state_model and result.get("signal_key"):
        state_model = build_c_signal_v2_state_from_result(result)
    state_model = state_model or {}

    scan_type = result.get("scan_type") or result.get("_scan_type") or "opportunity"
    group_key = _v2_priority_group(scan_type, state_model)
    group = _V2_PRIORITY_GROUPS[group_key]
    permission = state_model.get("permission") or ""
    final_score = _as_float(result.get("final_score"), _as_float(result.get("rank_score"), 0.0)) or 0.0
    confirm_score = _as_float(result.get("confirm_score"), 0.0) or 0.0
    setup_score = _as_float(result.get("setup_score"), 0.0) or 0.0
    risk_score = _as_float(result.get("risk_score"), 0.0) or 0.0
    sector_score = _as_float(result.get("sector_score"), 0.0) or 0.0
    concept_score = _as_float(result.get("concept_score"), 0.0) or 0.0
    confidence = result.get("score_confidence") if isinstance(result.get("score_confidence"), dict) else {}
    replay_avg = _as_float(confidence.get("replay_5d_avg_ret"), 0.0) or 0.0
    replay_sample_count = _as_int(confidence.get("replay_5d_sample_count"), 0)

    score = _v2_priority_base(scan_type, group_key, permission)
    score += final_score * 0.72
    score += max(sector_score, concept_score) * 0.18
    score += min(sector_score, concept_score) * 0.06
    score += confirm_score * 7
    score += setup_score * 3
    if scan_type == "risk":
        score += risk_score * 18
    else:
        score -= risk_score * 12
    if replay_sample_count:
        score += max(-8.0, min(8.0, replay_avg * 1.5))

    return {
        "v2_priority_group": group_key,
        "v2_priority_label": group["label"],
        "v2_priority_detail": group["detail"],
        "v2_priority_tone": group["tone"],
        "v2_queue_priority": group["queue_priority"],
        "v2_priority_score": round(score, 1),
        "v2_priority_source": "c_signal_v2_phase_2_2",
    }


def apply_c_signal_v2_priority(pools):
    """Attach V2 priority fields to all scan workspace pool results."""
    for pool in (pools or {}).values():
        for result in pool.get("results", []):
            result.update(build_c_signal_v2_priority(result))
