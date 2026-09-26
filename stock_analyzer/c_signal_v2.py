"""C signal V2 state and permission model."""

from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_facts
from stock_analyzer.legacy_c_signal_adapter import c_signal_v2_fields, c_signal_v2_mark_fields
from stock_analyzer.market_permission import build_v2_environment_permission, evaluate_macro_entry_blocks
from stock_analyzer.technical_structures import build_technical_structures
from stock_analyzer.trade_plan import evaluate_v2_plan_gate


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


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def _permission_contract(
    *,
    mode,
    mode_label,
    permission,
    permission_label,
    signal_key,
    state,
    state_label,
    reason,
    next_action,
    can_open=False,
    block_reasons=None,
    required_confirmations=None,
    plan_gate=None,
):
    plan_gate = plan_gate or {}

    return {
        "schema_version": 1,
        "source": "c_signal_v2_p19_repair_watch",
        "mode": mode,
        "mode_label": mode_label,
        "permission": permission,
        "permission_label": permission_label,
        "signal_key": signal_key,
        "state": state,
        "state_label": state_label,
        "reason": reason,
        "next_action": next_action,
        "can_open": bool(can_open),
        "can_hold": signal_key == "v2_strong_resistance_scale_out" or permission != "risk_only",
        "block_reasons": list(block_reasons or []),
        "required_confirmations": list(required_confirmations or []),
        "plan_gate": plan_gate or None,
        "plan_status": plan_gate.get("status"),
        "plan_status_label": plan_gate.get("status_label"),
    }


_CANDIDATE_SUBSTATE_LABELS = {
    "structure_candidate": ("结构候选", "候"),
    "pullback_setup": ("回踩蓄势", "候"),
    "weak_repair_candidate": ("破位修复观察", "候?"),
    "strong_repair_watch": ("强修复待触发", "待触"),
    "reversal_confirmed": ("反包/触发确认", "触"),
    "entry_ready": ("计划可执行", "买"),
}


def _first_float(*values):
    for value in values:
        number = _as_float(value)
        if number is not None:
            return number
    return None


def _price_distance_pct(target, base):
    target_value = _as_float(target)
    base_value = _as_float(base)
    if target_value is None or base_value in {None, 0}:
        return None
    return round((target_value - base_value) / base_value * 100, 2)


def _drop_distance_pct(latest_price, stop_price):
    """从现价到下方止损位的距离，以现价为基，与上方空间百分比可直接比较。"""
    latest_value = _as_float(latest_price)
    stop_value = _as_float(stop_price)
    if latest_value in {None, 0} or stop_value is None:
        return None
    return round((latest_value - stop_value) / latest_value * 100, 2)


def _trigger_price_text(value):
    number = _as_float(value)
    return "-" if number is None else f"{number:.2f}"


def _candidate_trigger_plan(
    substate,
    *,
    label,
    display_label,
    confirmation_price,
    invalidation_price,
    missing_confirmations,
    latest_price=None,
):
    if not substate:
        return None

    status_map = {
        "structure_candidate": ("watch", "结构观察"),
        "pullback_setup": ("watch", "回踩蓄势"),
        "weak_repair_candidate": ("repair_watch", "破位修复"),
        "strong_repair_watch": ("pending_trigger", "待触发"),
        "reversal_confirmed": ("triggered_needs_plan", "触发待计划"),
        "entry_ready": ("entry_ready", "计划可执行"),
    }
    confirmation_label_map = {
        "structure_candidate": "结构触发价",
        "pullback_setup": "回踩确认价",
        "weak_repair_candidate": "修复确认价",
        "strong_repair_watch": "右侧确认价",
        "reversal_confirmed": "触发确认价",
        "entry_ready": "计划入场价",
    }
    summary_map = {
        "structure_candidate": "已有可跟踪结构，但尚未出现独立触发事实。",
        "pullback_setup": "价格进入回踩观察语境，但仍需要右侧重新转强。",
        "weak_repair_candidate": "旧结构有破坏，新底部线索出现，先看能否站回关键位。",
        "strong_repair_watch": "强修复线索已出现，但当前仍不是买点，必须等确认价被有效突破。",
        "reversal_confirmed": "触发事实已出现，但仍要通过 Plan Gate 后才允许显示买点。",
        "entry_ready": "触发、结构、目标和风险预算已进入可执行检查区。",
    }
    status, status_label = status_map.get(substate, ("watch", "观察"))
    confirmation_label = confirmation_label_map.get(substate, "确认价")
    confirm_text = _trigger_price_text(confirmation_price)
    invalid_text = _trigger_price_text(invalidation_price)
    has_confirmation = _as_float(confirmation_price) is not None
    has_invalidation = _as_float(invalidation_price) is not None

    if substate == "entry_ready":
        intraday_rule = f"盘中围绕计划入场价 {confirm_text} 和失效价 {invalid_text} 执行，不再把观察信号当作新买点。"
        next_session_rule = "继续按交易计划管理仓位、止损和收益风险比。"
    elif substate == "reversal_confirmed":
        intraday_rule = f"盘中已经出现触发事实，下一步只检查 Plan Gate；未通过前不显示买。"
        next_session_rule = f"若收盘仍守住触发确认价 {confirm_text}，继续补齐目标、止损和仓位预算。"
    elif substate == "strong_repair_watch":
        intraday_rule = f"盘中只有放量站上右侧确认价 {confirm_text}，且不跌破失效价 {invalid_text}，才进入触发复核。"
        next_session_rule = f"次日收盘有效突破 {confirm_text} 后，转入 `触`，再交给 Plan Gate 判断是否可买。"
    elif substate == "weak_repair_candidate":
        intraday_rule = f"先看能否站回修复确认价 {confirm_text}；站不回时只按破位修复观察处理。"
        next_session_rule = f"次日若不能站回 {confirm_text}，或跌破 {invalid_text}，退出修复观察。"
    elif substate == "pullback_setup":
        intraday_rule = f"盘中回踩不破失效价 {invalid_text}，再站回回踩确认价 {confirm_text} 才算转强。"
        next_session_rule = f"次日若跌破 {invalid_text}，回踩蓄势失效；若站上 {confirm_text}，进入触发复核。"
    else:
        intraday_rule = f"盘中先看能否突破结构触发价 {confirm_text}，没有触发前只观察。"
        next_session_rule = f"次日若仍不能站上 {confirm_text}，继续保持结构候选；跌破 {invalid_text} 则观察失效。"

    if not has_confirmation:
        intraday_rule = "确认价尚未形成，先等待矩形上沿、箱体中轴、前高或量峰压力之一变清楚。"
        next_session_rule = "次日先补齐可证伪结构，再讨论是否进入触发复核。"
    if not has_invalidation:
        failure_rule = "失效价尚未形成，不能执行入场，只能保留观察。"
    else:
        failure_rule = f"跌破失效价 {invalid_text} 后，本轮候选失效；若进入信号后跟踪，再交给 Exit Gate 管理。"

    checklist = []
    if has_confirmation:
        checklist.append(f"站上{confirmation_label} {confirm_text}")
    if has_invalidation:
        checklist.append(f"不跌破失效价 {invalid_text}")
    checklist.extend(missing_confirmations or [])

    return {
        "schema_version": 1,
        "status": status,
        "status_label": status_label,
        "substate": substate,
        "substate_label": label,
        "display_label": display_label,
        "summary": summary_map.get(substate, "等待更多右侧确认。"),
        "confirmation_price": confirmation_price,
        "confirmation_label": confirmation_label,
        "invalidation_price": invalidation_price,
        "invalidation_label": "结构失效价",
        "distance_to_confirmation_pct": _price_distance_pct(confirmation_price, latest_price),
        "distance_to_invalidation_pct": _drop_distance_pct(latest_price, invalidation_price),
        "missing_confirmations": list(missing_confirmations or []),
        "trigger_checklist": _unique_text(checklist),
        "intraday_rule": intraday_rule,
        "next_session_rule": next_session_rule,
        "failure_rule": failure_rule,
        "is_buy_point": substate == "entry_ready",
        "requires_plan_gate": substate in {"strong_repair_watch", "reversal_confirmed", "entry_ready"},
    }


def _candidate_substate_fields(facts, permission_model=None, latest=None):
    """Return P25 candidate semantics without changing trade permission."""
    facts = facts if isinstance(facts, dict) else {}
    permission_model = permission_model if isinstance(permission_model, dict) else {}
    state = permission_model.get("state") or ""
    permission = permission_model.get("permission") or ""
    structure = facts.get("structure") if isinstance(facts.get("structure"), dict) else {}
    setup = facts.get("setup") if isinstance(facts.get("setup"), dict) else {}
    trigger = facts.get("trigger") if isinstance(facts.get("trigger"), dict) else {}
    momentum = facts.get("momentum") if isinstance(facts.get("momentum"), dict) else {}
    macro_tide = facts.get("macro_tide") if isinstance(facts.get("macro_tide"), dict) else {}
    target_structure = facts.get("target_structure") if isinstance(facts.get("target_structure"), dict) else {}
    bear_trap = structure.get("bear_trap_recovery") if isinstance(structure.get("bear_trap_recovery"), dict) else {}
    rectangle = structure.get("rectangle") if isinstance(structure.get("rectangle"), dict) else {}
    ignition = trigger.get("ignition") if isinstance(trigger.get("ignition"), dict) else {}
    selected_target = target_structure.get("selected_breakout_target") if isinstance(target_structure.get("selected_breakout_target"), dict) else {}
    ma250 = macro_tide.get("ma250") if isinstance(macro_tide.get("ma250"), dict) else {}
    has_clear_near_target = bool(
        _as_float(selected_target.get("price")) is not None
        and _as_float(selected_target.get("strength_score"), 0) >= 90
        and _as_float(selected_target.get("distance_pct"), 999) <= 15
    )
    no_short_box_repair_watch = bool(
        not rectangle.get("available")
        and setup.get("repair_impulse")
        and ma250.get("above") is True
        and has_clear_near_target
    )
    if permission == "risk_only" or state in {
        "exit_gate_sell",
        "scale_out_suggested",
        "risk_control",
        "repair_setup",
        "research_bottom",
        "researchable",
        "idle",
        "no_data",
    }:
        return {
            "candidate_substate": "",
            "candidate_substate_label": "",
            "candidate_display_label": "",
            "candidate_confirmation_price": None,
            "candidate_invalidation_price": None,
            "candidate_missing_confirmations": [],
            "candidate_trigger_plan": None,
        }

    if permission in {"attack_allowed", "breakout_allowed", "pullback_allowed"}:
        substate = "entry_ready"
    elif state in {"trigger_plan_blocked", "trigger_plan_waiting", "trigger_observed"}:
        substate = "reversal_confirmed"
    elif (
        bear_trap.get("recovered_to_mid")
        or no_short_box_repair_watch
        or (
            setup.get("pullback_setup")
            and (
                setup.get("repair_confirm")
                or setup.get("repair_impulse")
                or trigger.get("gap_fill_reversal")
                or momentum.get("power_flip")
            )
        )
    ):
        substate = "strong_repair_watch"
    elif (
        bear_trap.get("available")
        and not bear_trap.get("breakout_after_recovery")
        and (bear_trap.get("break_date") or bear_trap.get("recovered"))
    ):
        substate = "weak_repair_candidate"
    elif state == "pullback_setup" or setup.get("pullback_setup"):
        substate = "pullback_setup"
    elif structure.get("candidate") or state in {"structure_candidate", "breakout_setup"}:
        substate = "structure_candidate"
    else:
        return {
            "candidate_substate": "",
            "candidate_substate_label": "",
            "candidate_display_label": "",
            "candidate_confirmation_price": None,
            "candidate_invalidation_price": None,
            "candidate_missing_confirmations": [],
            "candidate_trigger_plan": None,
        }

    label, display_label = _CANDIDATE_SUBSTATE_LABELS[substate]
    invalidation_price = _v2_structure_stop(facts)
    plan_gate = permission_model.get("plan_gate")
    plan_gate = plan_gate if isinstance(plan_gate, dict) else {}
    if substate == "weak_repair_candidate":
        confirmation_price = _first_float(bear_trap.get("box_mid"), bear_trap.get("box_lower"), rectangle.get("mid"))
    elif substate == "strong_repair_watch":
        confirmation_price = _first_float(
            bear_trap.get("box_upper"),
            rectangle.get("upper"),
            rectangle.get("previous_upper"),
            selected_target.get("price"),
        )
    elif substate == "reversal_confirmed":
        confirmation_price = _first_float(plan_gate.get("entry_price"), rectangle.get("upper"))
    elif substate == "entry_ready":
        confirmation_price = _first_float(plan_gate.get("entry_price"))
    else:
        confirmation_price = _first_float(rectangle.get("upper"), rectangle.get("mid"))

    missing = {
        "structure_candidate": ["V2 触发事实", "交易计划校验"],
        "pullback_setup": ["回踩触发", "交易计划校验"],
        "weak_repair_candidate": ["站回防守线或箱体中轴", "再确认 V2 触发事实"],
        "strong_repair_watch": ["突破确认价", "Plan Gate 校验"],
        "reversal_confirmed": ["Plan Gate 校验"],
        "entry_ready": ["仓位风险预算"],
    }[substate]
    latest_price = latest.get("close") if hasattr(latest, "get") else None

    return {
        "candidate_substate": substate,
        "candidate_substate_label": label,
        "candidate_display_label": display_label,
        "candidate_confirmation_price": confirmation_price,
        "candidate_invalidation_price": invalidation_price,
        "candidate_missing_confirmations": missing,
        "candidate_trigger_plan": _candidate_trigger_plan(
            substate,
            label=label,
            display_label=display_label,
            confirmation_price=confirmation_price,
            invalidation_price=invalidation_price,
            missing_confirmations=missing,
            latest_price=latest_price,
        ),
    }



def _unique_text(values):
    output = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _v2_structure_stop(facts):
    structure = facts.get("structure") if isinstance(facts.get("structure"), dict) else {}
    rectangle = structure.get("rectangle") if isinstance(structure.get("rectangle"), dict) else {}
    fractals = structure.get("fractals") if isinstance(structure.get("fractals"), dict) else {}
    bear_trap = structure.get("bear_trap_recovery") if isinstance(structure.get("bear_trap_recovery"), dict) else {}
    latest_bottom = fractals.get("latest_bottom") if isinstance(fractals.get("latest_bottom"), dict) else {}
    if bear_trap.get("breakout_after_recovery"):
        number = _as_float(bear_trap.get("stop_price"))
        if number is not None:
            return number
    for value in (
        rectangle.get("invalidation_price"),
        rectangle.get("c_point"),
        latest_bottom.get("price"),
    ):
        number = _as_float(value)
        if number is not None:
            return number
    return None


def _v2_target_reference(facts, *, entry_type=None, entry_price=None, context=None):
    context = context or {}
    for key in ("target_price", "expected_target_price"):
        number = _as_float(context.get(key))
        if number is not None:
            return {
                "price": number,
                "source": key,
                "label": "外部目标价",
                "status": "ready",
            }
    target_structure = facts.get("target_structure") if isinstance(facts.get("target_structure"), dict) else {}
    entry_kind = str(entry_type or "").strip()
    entry = _as_float(entry_price)
    if entry_kind == "pullback":
        pullback_target = target_structure.get("pullback_target") if isinstance(target_structure.get("pullback_target"), dict) else {}
        price = _as_float(pullback_target.get("price"))
        if price is not None and (entry is None or price > entry):
            return {
                "price": price,
                "source": pullback_target.get("source") or "rectangle_upper",
                "label": pullback_target.get("label") or "箱体上沿",
                "status": "ready",
            }
        return {
            "price": None,
            "source": "pullback_target_missing",
            "label": "回踩目标待确认",
            "status": "waiting",
        }
    if entry_kind in {"breakout", "attack"}:
        breakout_target = target_structure.get("selected_breakout_target") if isinstance(target_structure.get("selected_breakout_target"), dict) else {}
        price = _as_float(breakout_target.get("price"))
        if price is not None and (entry is None or price > entry):
            return {
                "price": price,
                "source": breakout_target.get("source") or "upper_resistance",
                "label": breakout_target.get("label") or "上方结构阻力",
                "status": "ready",
            }
        return {
            "price": None,
            "source": "breakout_target_missing",
            "label": "突破目标待确认",
            "status": "waiting",
        }
    return {
        "price": None,
        "source": "target_unresolved",
        "label": "目标待确认",
        "status": "waiting",
    }


def _ma20_deviation_pct(latest):
    close = _as_float(latest.get("close"))
    ma20 = _as_float(latest.get("ma20"))
    if close is None or not ma20:
        return None
    return (close / ma20 - 1) * 100


def _v2_plan_context(latest, context=None):
    gate_context = dict(context or {})
    for key in ("return_pct", "volume_ratio"):
        if key not in gate_context:
            gate_context[key] = _as_float(latest.get(key))
    if "ma20_deviation_pct" not in gate_context:
        gate_context["ma20_deviation_pct"] = _ma20_deviation_pct(latest)
    return gate_context


def _v2_plan_context_with_target(latest, target_reference, context=None):
    gate_context = _v2_plan_context(latest, context=context)
    if target_reference:
        gate_context["target_source"] = target_reference.get("source")
        gate_context["target_label"] = target_reference.get("label")
    return gate_context


def _v2_entry_attempt(facts, latest, event_key=None):
    structure = facts.get("structure") if isinstance(facts.get("structure"), dict) else {}
    trigger = facts.get("trigger") if isinstance(facts.get("trigger"), dict) else {}
    ignition = trigger.get("ignition") if isinstance(trigger.get("ignition"), dict) else {}
    setup = facts.get("setup") if isinstance(facts.get("setup"), dict) else {}
    bear_trap = structure.get("bear_trap_recovery") if isinstance(structure.get("bear_trap_recovery"), dict) else {}
    attack_day = bool(trigger.get("attack_day"))
    ignition_with_attack = bool(attack_day and ignition.get("triggered"))
    if ignition_with_attack:
        return {
            "entry_type": "attack",
            "signal_key": "v2_ignition",
            "permission": "attack_allowed",
            "permission_label": "允许攻击计划",
            "state": "ignition_triggered",
            "state_label": "起爆触发",
            "mode_label": "触发待计划",
            "reason": trigger.get("summary") or "V2 起爆点触发，进入交易计划校验",
            "next_action": "核对结构止损、收益风险比和仓位，不直接追入",
        }
    if attack_day:
        return {
            "entry_type": "attack",
            "signal_key": "v2_attack_day",
            "permission": "attack_allowed",
            "permission_label": "允许攻击计划",
            "state": "attack_trigger",
            "state_label": "攻击触发",
            "mode_label": "触发待计划",
            "reason": trigger.get("summary") or "V2 攻击日触发，进入交易计划校验",
            "next_action": "核对结构止损、收益风险比和仓位，不直接追入",
        }
    if bear_trap.get("breakout_after_recovery"):
        return {
            "entry_type": "breakout",
            "signal_key": "v2_bear_trap_recovery",
            "permission": "breakout_allowed",
            "permission_label": "允许突破计划",
            "state": "bear_trap_breakout",
            "state_label": "破底翻突破",
            "mode_label": "破底翻待计划",
            "reason": bear_trap.get("summary") or "轻微破底后快速收回并重新突破箱体上沿",
            "next_action": "按新的突破候选核对止损、目标价、2R、宏观许可和仓位预算",
        }
    if setup.get("breakout_trigger"):
        return {
            "entry_type": "breakout",
            "signal_key": "v2_breakout",
            "permission": "breakout_allowed",
            "permission_label": "允许突破计划",
            "state": "entry_breakout",
            "state_label": "突破可交易",
            "mode_label": "突破待计划",
            "reason": setup.get("summary") or "V2 矩形上沿或前高突破触发，进入交易闸门",
            "next_action": "只在结构止损、2R 空间和追高风险通过后按突破计划处理",
        }
    if setup.get("pullback_trigger"):
        return {
            "entry_type": "pullback",
            "signal_key": "v2_pullback",
            "permission": "pullback_allowed",
            "permission_label": "允许回踩计划",
            "state": "entry_pullback",
            "state_label": "回踩可交易",
            "mode_label": "回踩待计划",
            "reason": setup.get("summary") or "V2 回踩确认触发，进入交易闸门",
            "next_action": "只在结构止损、2R 空间和风险预算通过后按回踩计划处理",
        }
    return {}


def _v2_macro_entry_gate(macro_tide, entry_type):
    """宏观入场闸门：核心判定复用 market_permission.evaluate_macro_entry_blocks。"""
    gate = evaluate_macro_entry_blocks(macro_tide, entry_type)
    block_reasons = gate["block_reasons"]
    warnings = gate["warnings"]
    if block_reasons:
        return {
            "permission": "forbidden",
            "label": "宏观否决",
            "block_reasons": block_reasons,
            "warnings": warnings,
        }
    return {
        "permission": "allowed" if not warnings else "watch",
        "label": "宏观通过" if not warnings else "宏观待核",
        "block_reasons": [],
        "warnings": warnings,
    }


def build_c_signal_v2_permission(facts, latest, *, event_key=None, context=None):
    """Build the V2 permission contract purely from V2 facts.

    This is the single permission source for both scan admission and the
    single-stock trade plan. Executable permissions only appear after the
    macro entry gate and the plan gate (structural stop, 2R, chase risk) pass.
    """
    facts = facts or {}
    if latest is None:
        latest = {}
    context = dict(context or {})
    scores = facts.get("scores") or {"setup": 0, "confirm": 0, "risk": 0}
    structure = facts.get("structure") if isinstance(facts.get("structure"), dict) else {}
    trigger = facts.get("trigger") if isinstance(facts.get("trigger"), dict) else {}
    setup = facts.get("setup") if isinstance(facts.get("setup"), dict) else {}
    risk = facts.get("risk") if isinstance(facts.get("risk"), dict) else {}
    repair = facts.get("repair") if isinstance(facts.get("repair"), dict) else {}
    clock = facts.get("clock") if isinstance(facts.get("clock"), dict) else {}
    macro_tide = facts.get("macro_tide") if isinstance(facts.get("macro_tide"), dict) else {}
    exit_gate = facts.get("exit_gate") if isinstance(facts.get("exit_gate"), dict) else {}
    ignition = trigger.get("ignition") if isinstance(trigger.get("ignition"), dict) else {}
    entry_attempt = _v2_entry_attempt(facts, latest, event_key=event_key)

    has_entry = bool(entry_attempt)
    has_exit = bool(risk.get("has_exit")) or exit_gate.get("action") == "sell"
    has_risk = bool(risk.get("has_risk"))
    risk_score = _as_int(scores.get("risk"))
    risk_break_score = _as_int(risk.get("risk_break_score"))
    risk_heat_score = _as_int(risk.get("risk_heat_score"))
    context.setdefault("risk_heat_score", risk_heat_score)
    structure_candidate = bool(structure.get("candidate"))
    attack_day = bool(trigger.get("attack_day"))
    bear_trap = structure.get("bear_trap_recovery") if isinstance(structure.get("bear_trap_recovery"), dict) else {}
    trigger_observed = bool(
        attack_day
        or bear_trap.get("breakout_after_recovery")
    )

    exit_action = exit_gate.get("action")
    if exit_action == "sell":
        return _permission_contract(
            mode="exit_gate",
            mode_label="Exit Gate",
            permission="risk_only",
            permission_label="只处理风险",
            signal_key="v2_exit_gate_sell",
            state="exit_gate_sell",
            state_label="防守离场",
            reason=exit_gate.get("summary") or "Exit Gate 防守线被跌破",
            next_action="执行防守离场，退出后重新等待下一轮结构",
            can_open=False,
            block_reasons=["Exit Gate 已触发离场"],
        )
    if exit_action == "scale_out":
        return _permission_contract(
            mode="exit_gate",
            mode_label="Exit Gate",
            permission="risk_only",
            permission_label="只处理风险",
            signal_key="v2_strong_resistance_scale_out",
            state="scale_out_suggested",
            state_label="收益保护",
            reason=exit_gate.get("summary") or "触及核心强阻",
            next_action="检查收益保护条件；未跌破防守线时不生成 S 点",
            can_open=False,
            block_reasons=["触及核心强阻，优先管理已有仓位"],
        )

    if has_exit or risk_break_score >= 3 or risk_score >= 4:
        risk_key = "v2_risk_break" if risk_break_score >= 2 else "v2_risk_heat"
        return _permission_contract(
            mode="risk_control",
            mode_label="风险处理",
            permission="risk_only",
            permission_label="只处理风险",
            signal_key=risk_key,
            state="risk_control",
            state_label="风险处理",
            reason=risk.get("summary") or "V2 独立风险事实已触发",
            next_action="停止新开，优先处理风险",
            block_reasons=["V2 风险分过高或离场事实已触发"],
        )

    block_reasons = []
    if risk_score >= 3 or has_risk:
        block_reasons.append("风险条件已出现，不能升级为可执行")
    if not structure_candidate:
        block_reasons.append("缺少 V2 可证伪结构")
    if not trigger_observed:
        block_reasons.append("缺少 V2 独立触发事实")

    if entry_attempt and structure_candidate and risk_score <= 2 and not has_risk:
        macro_entry_gate = _v2_macro_entry_gate(macro_tide, entry_attempt.get("entry_type"))
        if macro_entry_gate.get("permission") == "forbidden":
            return _permission_contract(
                mode="macro_veto_blocked",
                mode_label="宏观否决",
                permission="forbidden",
                permission_label="禁止",
                signal_key="",
                state="macro_veto_blocked",
                state_label="宏观否决",
                reason="V2 触发事实出现，但入场类型对应的长周期防线未通过",
                next_action="保留单股 C 信号分析，等待长周期趋势重新满足后再评估交易计划",
                can_open=False,
                block_reasons=_unique_text(macro_entry_gate.get("block_reasons")),
                required_confirmations=["C突/C爆 重新站上 MA250", "周线 MACD 不再空方扩张", "C回 至少确认 MA60 上行", "交易计划校验"],
            )
        target_reference = _v2_target_reference(
            facts,
            entry_type=entry_attempt.get("entry_type"),
            entry_price=_as_float(latest.get("close")),
            context=context,
        )
        plan_gate = evaluate_v2_plan_gate(
            entry_type=entry_attempt.get("entry_type"),
            entry_price=_as_float(latest.get("close")),
            stop_price=_v2_structure_stop(facts),
            target_price=target_reference.get("price"),
            context=_v2_plan_context_with_target(latest, target_reference, context=context),
        )
        gate_block_reasons = plan_gate.get("block_reasons") or []
        gate_required_confirmations = plan_gate.get("required_confirmations") or []
        if not plan_gate.get("ready"):
            state = "trigger_plan_blocked" if plan_gate.get("status") == "blocked" else "trigger_plan_waiting"
            state_label = "计划拦截" if plan_gate.get("status") == "blocked" else "计划待确认"
            return _permission_contract(
                mode=state,
                mode_label=state_label,
                permission="forbidden" if plan_gate.get("status") == "blocked" else "watch_only",
                permission_label="禁止" if plan_gate.get("status") == "blocked" else "只观察",
                signal_key="",
                state=state,
                state_label=state_label,
                reason=(
                    entry_attempt.get("reason")
                    or trigger.get("summary")
                    or "V2 触发事实出现，但交易计划尚未通过"
                ),
                next_action="补齐或修正结构止损、目标空间和收益风险比后再评估",
                can_open=False,
                block_reasons=_unique_text(gate_block_reasons),
                required_confirmations=_unique_text(gate_required_confirmations),
                plan_gate=plan_gate,
            )
        if macro_entry_gate.get("warnings"):
            # 宏观"样本不足"不等于通过：计划本身可校验，但长周期防线缺样本时
            # 不放行为可执行，降为待核（有数据后的下一次重扫自然解除）。
            macro_warnings = _unique_text(macro_entry_gate.get("warnings"))
            return _permission_contract(
                mode="trigger_plan_waiting",
                mode_label="宏观待核",
                permission="watch_only",
                permission_label="只观察",
                signal_key="",
                state="trigger_plan_waiting",
                state_label="宏观样本待核",
                reason="；".join(macro_warnings),
                next_action="待长周期样本补齐后重新扫描确认；此前不标记为可执行",
                can_open=False,
                required_confirmations=_unique_text(list(macro_warnings) + ["仓位风险预算"]),
                plan_gate=plan_gate,
            )
        return _permission_contract(
            mode="trigger_plan_required",
            mode_label=entry_attempt.get("mode_label") or "触发待计划",
            permission=entry_attempt.get("permission"),
            permission_label=entry_attempt.get("permission_label"),
            signal_key=entry_attempt.get("signal_key"),
            state=entry_attempt.get("state"),
            state_label=entry_attempt.get("state_label"),
            reason=entry_attempt.get("reason") or "V2 入场触发通过交易闸门",
            next_action=entry_attempt.get("next_action") or "核对结构止损、收益风险比和仓位",
            can_open=True,
            required_confirmations=_unique_text(["仓位风险预算"]),
            plan_gate=plan_gate,
        )

    if trigger_observed:
        return _permission_contract(
            mode="trigger_observed",
            mode_label="触发观察",
            permission="watch_only",
            permission_label="只观察",
            signal_key="v2_ignition" if ignition.get("triggered") else "v2_attack_day",
            state="trigger_observed",
            state_label="触发事实出现",
            reason=trigger.get("summary") or "出现 V2 触发事实，但前置结构或风险条件未通过",
            next_action="先补齐结构边界、止损和收益风险比，不直接追入",
            block_reasons=block_reasons,
            required_confirmations=["V2 结构确认", "风险下降", "交易计划校验"],
        )

    if repair.get("stage") == "repair_setup":
        return _permission_contract(
            mode="repair_watch",
            mode_label="修复观察",
            permission="watch_only",
            permission_label="只观察",
            signal_key="v2_repair_watch",
            state="repair_setup",
            state_label="修复观察",
            reason=repair.get("summary") or "底背离后出现修复事实，但尚未形成可执行触发",
            next_action="继续观察结构右侧确认；只有后续转为 C回/C突/C爆 并通过 Plan Gate 才能执行",
            block_reasons=block_reasons,
            required_confirmations=repair.get("required_confirmations") or ["结构确认", "V2 触发事实", "交易计划校验"],
        )

    if setup.get("bottom_divergence"):
        return _permission_contract(
            mode="research",
            mode_label="研究观察",
            permission="watch_only",
            permission_label="只观察",
            signal_key="v2_bottom_research",
            state="research_bottom",
            state_label="底部研究",
            reason="出现底背离观察事实",
            next_action="等待分型、矩形或触发器确认",
            required_confirmations=["结构确认", "V2 触发事实"],
        )

    if has_entry:
        return _permission_contract(
            mode="entry_unconfirmed",
            mode_label="触发待确认",
            permission="watch_only",
            permission_label="只观察",
            signal_key=entry_attempt.get("signal_key") or "",
            state="entry_unconfirmed",
            state_label="触发待核",
            reason=entry_attempt.get("reason") or "V2 触发事实存在，但结构或风险条件未通过",
            next_action="先补齐结构边界、止损和收益风险比，不直接追入",
            block_reasons=block_reasons,
            required_confirmations=["V2 结构确认", "风险下降", "交易计划校验"],
        )

    if setup.get("breakout_setup"):
        return _permission_contract(
            mode="breakout_watch",
            mode_label="突破准备",
            permission="structure_only",
            permission_label="结构观察",
            signal_key="",
            state="breakout_setup",
            state_label="突破准备",
            reason="价格靠近突破语境，但尚未出现 V2 独立触发事实",
            next_action="等待明确攻击日、起爆点或更小级别突破触发",
            block_reasons=["尚未触发"],
            required_confirmations=["V2 触发事实", "交易计划校验"],
        )

    if setup.get("pullback_setup"):
        return _permission_contract(
            mode="pullback_watch",
            mode_label="回踩蓄势",
            permission="structure_only",
            permission_label="结构观察",
            signal_key="",
            state="pullback_setup",
            state_label="回踩蓄势",
            reason="价格回到可观察支撑语境，但尚未出现 V2 入场触发",
            next_action="等待回踩触发、风险下降和交易计划校验",
            block_reasons=["尚未触发"],
            required_confirmations=["回踩触发", "交易计划校验"],
        )

    if structure_candidate:
        return _permission_contract(
            mode="structure_watch",
            mode_label="结构观察",
            permission="structure_only",
            permission_label="结构观察",
            signal_key="",
            state="structure_candidate",
            state_label="结构候选",
            reason=structure.get("summary") or "出现 V2 结构事实，尚未触发",
            next_action="等待明确触发，再进入交易计划校验",
            block_reasons=["尚未触发"],
            required_confirmations=["V2 触发事实", "交易计划校验"],
        )

    if clock.get("state") in {"countdown", "compression_watch", "expanding"} or _as_int(scores.get("setup")) >= 1:
        return _permission_contract(
            mode="research",
            mode_label="研究观察",
            permission="watch_only",
            permission_label="只观察",
            signal_key="v2_bottom_research",
            state="researchable",
            state_label="值得研究",
            reason=clock.get("state_label") or "出现观察级结构事实",
            next_action=clock.get("action_label") or "加入观察，等待方向和触发",
            required_confirmations=["结构确认", "V2 触发事实"],
        )

    return _permission_contract(
        mode="idle",
        mode_label="无结构",
        permission="forbidden",
        permission_label="禁止",
        signal_key="",
        state="idle",
        state_label="无结构",
        reason="没有足够 V2 结构证据",
        next_action="继续等待新的事实信号",
        block_reasons=["没有交易结构"],
        required_confirmations=["先出现结构证据", "再等待入场触发"],
    )


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


def build_c_signal_v2_state_components(df_display, *, context=None):
    """Build the frame-level V2 inputs that do not depend on ``event_key``.

    Facts, legacy permission and the williams clock only vary with the frame,
    so a caller that evaluates many events on the same frame (scanner pools)
    can build them once and share them across state models.
    """
    if _latest_row(df_display) is None:
        return None
    structures = build_technical_structures(df_display)
    clock = structures.get("williams_clock", {})
    facts = build_c_signal_v2_facts(df_display, clock=clock)
    return {
        "structures": structures,
        "williams_clock": clock,
        "facts": facts,
    }


def build_c_signal_v2_state(df_display, *, event_key=None, context=None, components=None):
    """Build the V2 state model from current facts.

    V2 is the only strategy chain: fact -> state -> permission -> action.
    Scan admission, candidate priority and the single-stock trade plan all
    consume this contract.
    """
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "version": 1,
            "source": "c_signal_v2_p19_repair_watch",
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

    if components is None:
        components = build_c_signal_v2_state_components(df_display, context=context) or {}
    facts = components.get("facts") or {}
    scores = facts.get("scores") or {"setup": 0, "confirm": 0, "risk": 0}
    permission_model = build_c_signal_v2_permission(
        facts,
        latest,
        event_key=event_key,
        context=context,
    )
    candidate_fields = _candidate_substate_fields(facts, permission_model, latest=latest)
    contract = _v2_state_contract(
        permission_model.get("signal_key") or "",
        state=permission_model.get("state") or "idle",
        state_label=permission_model.get("state_label") or "无结构",
        permission=permission_model.get("permission") or "forbidden",
        permission_label=permission_model.get("permission_label") or "禁止",
        reason=permission_model.get("reason") or "没有足够 V2 结构证据",
        next_action=permission_model.get("next_action") or "继续等待新的事实信号",
    )

    return {
        "version": 1,
        "source": "c_signal_v2_p19_repair_watch",
        "v2_state_schema_version": 2,
        "latest_date": _format_date(latest.get("date")),
        **contract,
        "scores": scores,
        "facts": facts,
        **candidate_fields,
        "v2_permission_model": permission_model,
        "permission_context": {
            "mode": permission_model.get("mode"),
            "mode_label": permission_model.get("mode_label"),
            "can_open": permission_model.get("can_open"),
            "can_hold": bool(permission_model.get("can_hold")),
            "risk_score": _as_int(scores.get("risk")),
            "risk_break_score": _as_int((facts.get("risk") or {}).get("risk_break_score")) if isinstance(facts.get("risk"), dict) else 0,
            "risk_heat_score": _as_int((facts.get("risk") or {}).get("risk_heat_score")) if isinstance(facts.get("risk"), dict) else 0,
            "candidate_substate": candidate_fields.get("candidate_substate"),
            "candidate_substate_label": candidate_fields.get("candidate_substate_label"),
            "candidate_display_label": candidate_fields.get("candidate_display_label"),
            "macro_tide_permission": (facts.get("macro_tide") or {}).get("permission") if isinstance(facts.get("macro_tide"), dict) else None,
            "macro_tide_label": (facts.get("macro_tide") or {}).get("label") if isinstance(facts.get("macro_tide"), dict) else None,
        },
        "event_mapping": c_signal_v2_fields(event_key) if event_key else None,
    }


def build_c_signal_v2_state_from_result(result):
    """Build a lightweight V2 state model from a persisted scan result."""
    result = result or {}
    existing_state_model = result.get("v2_state_model") if isinstance(result.get("v2_state_model"), dict) else {}
    signal_key = result.get("signal_key") or ""
    fields = c_signal_v2_fields(signal_key)
    risk_score = _as_int(result.get("risk_score"))
    confirm_score = _as_int(result.get("confirm_score"))
    setup_score = _as_int(result.get("setup_score"))
    scan_type = result.get("scan_type") or result.get("_scan_type") or ""
    role = fields.get("v2_role")

    if scan_type == "risk" and fields and role == "watch":
        # 观察类契约（如顶分型观察）进入风险池时保持观察语义，不伪装成风险处理。
        state = fields.get("v2_state") or "risk_control"
        state_label = fields.get("v2_state_label") or "风险处理"
        permission = "watch_only"
        permission_label = "只观察"
    elif role == "risk" or scan_type == "risk":
        state = fields.get("v2_state") if role == "risk" else "risk_control"
        state_label = fields.get("v2_state_label") if role == "risk" else "风险处理"
        permission = "risk_only"
        permission_label = "只处理风险"
    elif fields.get("requires_trade_plan"):
        plan_status = result.get("v2_plan_status")
        is_attack = signal_key in {"v2_attack_day", "v2_ignition"}
        is_breakout = signal_key in {
            "v2_breakout",
            "composite_breakout",
            "v2_bear_trap_recovery",
        }
        state = "attack_trigger" if is_attack else ("entry_breakout" if is_breakout else "entry_pullback")
        state_label = "攻击触发" if is_attack else ("突破待核" if is_breakout else "回踩待核")
        if plan_status == "ready":
            permission = "attack_allowed" if is_attack else ("breakout_allowed" if is_breakout else "pullback_allowed")
            permission_label = "允许攻击计划" if is_attack else ("允许突破计划" if is_breakout else "允许回踩计划")
        else:
            permission = "watch_only"
            permission_label = "计划待核"
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

    candidate_info = {}
    if isinstance(existing_state_model.get("facts"), dict):
        candidate_permission_model = existing_state_model.get("v2_permission_model")
        if not isinstance(candidate_permission_model, dict):
            candidate_permission_model = {
                "state": existing_state_model.get("state") or state,
                "permission": existing_state_model.get("permission") or permission,
            }
        candidate_info = _candidate_substate_fields(
            existing_state_model.get("facts"),
            candidate_permission_model,
            latest={"close": result.get("price")},
        )

    candidate_substate = (
        result.get("candidate_substate")
        or existing_state_model.get("candidate_substate")
        or candidate_info.get("candidate_substate")
        or ""
    )
    existing_state = existing_state_model.get("state") or state
    existing_permission = existing_state_model.get("permission") or permission
    if not candidate_substate:
        if existing_permission in {"attack_allowed", "breakout_allowed", "pullback_allowed"}:
            candidate_substate = "entry_ready"
        elif existing_state in {"trigger_plan_waiting", "trigger_plan_blocked", "trigger_observed"}:
            candidate_substate = "reversal_confirmed"
        elif existing_state == "pullback_setup":
            candidate_substate = "pullback_setup"
        elif existing_state in {"structure_candidate", "breakout_setup"}:
            candidate_substate = "structure_candidate"
    candidate_label, candidate_display = _CANDIDATE_SUBSTATE_LABELS.get(candidate_substate, ("", ""))
    candidate_confirmation_price = _as_float(result.get("candidate_confirmation_price"), candidate_info.get("candidate_confirmation_price"))
    candidate_invalidation_price = _as_float(result.get("candidate_invalidation_price"), candidate_info.get("candidate_invalidation_price"))
    candidate_missing_confirmations = list(
        result.get("candidate_missing_confirmations")
        or candidate_info.get("candidate_missing_confirmations")
        or []
    )
    candidate_trigger_plan = (
        result.get("candidate_trigger_plan")
        or existing_state_model.get("candidate_trigger_plan")
        or candidate_info.get("candidate_trigger_plan")
    )
    if not candidate_trigger_plan and candidate_substate:
        candidate_trigger_plan = _candidate_trigger_plan(
            candidate_substate,
            label=result.get("candidate_substate_label") or candidate_label,
            display_label=result.get("candidate_display_label") or candidate_display,
            confirmation_price=candidate_confirmation_price,
            invalidation_price=candidate_invalidation_price,
            missing_confirmations=candidate_missing_confirmations,
            latest_price=result.get("price"),
        )

    return {
        "version": 1,
        "source": "scan_result_backfill_p6_trade_gate",
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
        "candidate_substate": candidate_substate,
        "candidate_substate_label": result.get("candidate_substate_label") or candidate_info.get("candidate_substate_label") or candidate_label,
        "candidate_display_label": result.get("candidate_display_label") or candidate_info.get("candidate_display_label") or candidate_display,
        "candidate_confirmation_price": candidate_confirmation_price,
        "candidate_invalidation_price": candidate_invalidation_price,
        "candidate_missing_confirmations": candidate_missing_confirmations,
        "candidate_trigger_plan": candidate_trigger_plan,
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
    if permission in {"breakout_allowed", "pullback_allowed", "attack_allowed"}:
        return "trade_ready"
    if state in {"repair_setup", "repair_watch"}:
        return "repair_watch"
    if state in {"research_bottom", "researchable"}:
        return "research_watch"
    if permission in {"watch_only", "structure_only"} or state in {"trigger_plan_waiting", "trigger_plan_blocked"}:
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
    permission = state_model.get("permission") or ""
    environment = build_v2_environment_permission(result)
    environment_permission = environment.get("v2_environment_permission")
    if (
        scan_type == "opportunity"
        and group_key == "trade_ready"
        and environment_permission in {"forbidden", "watch", "unknown"}
    ):
        group_key = "structure_watch"
    group = _V2_PRIORITY_GROUPS[group_key]
    # final_score may be a legacy workspace-enrichment value containing retired
    # sector/concept adjustments. The ranking base is now strictly stock-local.
    final_score = _as_float(result.get("rank_score"), 0.0) or 0.0
    confirm_score = _as_float(result.get("confirm_score"), 0.0) or 0.0
    setup_score = _as_float(result.get("setup_score"), 0.0) or 0.0
    risk_score = _as_float(result.get("risk_score"), 0.0) or 0.0

    score = _v2_priority_base(scan_type, group_key, permission)
    score += final_score * 0.72
    score += confirm_score * 7
    score += setup_score * 3
    if scan_type == "risk":
        score += risk_score * 18
    else:
        score -= risk_score * 12
    if scan_type == "opportunity":
        if environment_permission == "forbidden":
            score -= 140
        elif environment_permission == "watch":
            score -= 60
        elif environment_permission == "unknown":
            score -= 30
        elif environment_permission == "allowed":
            score += 30

    permission_model = state_model.get("v2_permission_model") if isinstance(state_model.get("v2_permission_model"), dict) else {}
    return {
        **environment,
        "v2_queue": group_key,
        "v2_queue_label": group["label"],
        "v2_permission": permission,
        "v2_plan_status": permission_model.get("plan_status"),
        "v2_plan_status_label": permission_model.get("plan_status_label"),
        "v2_priority_group": group_key,
        "v2_priority_label": group["label"],
        "v2_priority_detail": group["detail"],
        "v2_priority_tone": group["tone"],
        "v2_queue_priority": group["queue_priority"],
        "v2_priority_score": round(score, 1),
        "v2_priority_source": "c_signal_v2_priority",
    }


def apply_c_signal_v2_priority(pools):
    """Attach V2 priority fields to all scan workspace pool results."""
    for pool in (pools or {}).values():
        for result in pool.get("results", []):
            result.update(build_c_signal_v2_priority(result))
