"""Human-readable explanations for scan candidates."""

from stock_analyzer.versioning import SCAN_EXPLANATION_VERSION

EXPLANATION_VERSION = SCAN_EXPLANATION_VERSION
UNKNOWN_SECTOR_LABEL = "未识别板块"


def _number(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _text(value, fallback="-"):
    text = str(value or "").strip()
    return text if text else fallback


def _format_percent(value):
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _format_signed_percent(value):
    number = _number(value)
    if number is None:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.2f}%"


def _concept_text(result, limit=3):
    concepts = result.get("concepts")
    if not isinstance(concepts, (list, tuple)):
        return ""
    clean = [str(item).strip() for item in concepts if str(item).strip()]
    return " / ".join(clean[:limit])


def classify_rank_score(score):
    value = _number(score)
    if value is None:
        return {"label": "强度待定", "tone": "muted", "hint": "缺少强度分"}
    if value >= 75:
        return {"label": "强势候选", "tone": "positive", "hint": "强度分进入高分段"}
    if value >= 50:
        return {"label": "有效候选", "tone": "positive", "hint": "强度分处于可关注区间"}
    if value >= 25:
        return {"label": "观察候选", "tone": "warning", "hint": "强度分仍需确认"}
    return {"label": "低强度", "tone": "muted", "hint": "强度分偏低"}


def classify_risk_score(score):
    value = _number(score, 0.0)
    if value >= 4:
        return {"label": "高风险", "tone": "danger", "hint": "风险分较高，应先看止损或背离"}
    if value >= 2:
        return {"label": "有风险", "tone": "warning", "hint": "存在风险因素，需要控制仓位"}
    if value >= 1:
        return {"label": "轻风险", "tone": "warning", "hint": "有轻微信号冲突"}
    return {"label": "风险低", "tone": "positive", "hint": "当前风险分较低"}


def classify_history_stats(win_rate, avg_ret):
    win = _number(win_rate)
    avg = _number(avg_ret)
    if win is None and avg is None:
        return {"label": "样本待积累", "tone": "muted", "hint": "缺少该信号的历史统计"}
    if (win is None or win >= 60) and (avg is None or avg > 0):
        return {"label": "历史占优", "tone": "positive", "hint": "胜率或均值支持该信号"}
    if (win is not None and win < 45) or (avg is not None and avg < 0):
        return {"label": "历史偏弱", "tone": "danger", "hint": "胜率或均值偏弱"}
    return {"label": "历史中性", "tone": "warning", "hint": "历史统计不强不弱"}


def classify_score_confidence(confidence):
    if not isinstance(confidence, dict):
        return {"label": "可信度待定", "tone": "muted", "hint": "缺少评分可信度信息"}
    level = confidence.get("level")
    if level == "high":
        return {"label": "可信度高", "tone": "positive", "hint": confidence.get("basis") or "回放样本充分"}
    if level == "medium":
        return {"label": "可信度中", "tone": "positive", "hint": confidence.get("basis") or "已有回放样本"}
    if level == "low":
        return {"label": "样本偏少", "tone": "warning", "hint": confidence.get("basis") or "样本仍需积累"}
    return {"label": "待验证", "tone": "muted", "hint": confidence.get("basis") or "暂无回放样本"}


def _format_plain_number(value, digits=2):
    number = _number(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _breakout_diagnostic(result):
    if result.get("prior_high_10") is None and result.get("prior_breakout") is None:
        return None
    status = "已突破前高" if result.get("prior_breakout") is True else "未确认前高突破"
    return {
        "label": "突破诊断",
        "value": f"{status} · 近10日前高 {_format_plain_number(result.get('prior_high_10'))}",
        "tone": "positive" if result.get("prior_breakout") is True else "warning",
    }


def _risk_split_diagnostic(result):
    if result.get("risk_break_score") is None and result.get("risk_heat_score") is None:
        return None
    break_score = _text(result.get("risk_break_score"))
    heat_score = _text(result.get("risk_heat_score"))
    return {
        "label": "风险拆分",
        "value": f"破位 {break_score} / 过热 {heat_score}",
        "tone": classify_risk_score(result.get("risk_score"))["tone"],
    }


def _direction_diagnostic(result):
    if result.get("bull_power") is None and result.get("williams_r") is None:
        return None
    bull_power = _format_plain_number(result.get("bull_power"), digits=3)
    bear_power = _format_plain_number(result.get("bear_power"), digits=3)
    williams_r = _format_plain_number(result.get("williams_r"), digits=1)
    side = result.get("williams_r_center_side")
    if result.get("williams_r_cross_bull") is True:
        williams_text = f"%R {williams_r} · 下穿 50，中轴偏多"
        tone = "positive"
    elif result.get("williams_r_cross_bear") is True:
        williams_text = f"%R {williams_r} · 上穿 50，中轴偏空"
        tone = "warning"
    elif side == "bull":
        williams_text = f"%R {williams_r} · 50 下方，价格偏近高位"
        tone = "positive"
    elif side == "bear":
        williams_text = f"%R {williams_r} · 50 上方，价格偏离高位"
        tone = "warning"
    else:
        williams_text = f"%R {williams_r} · 中轴附近"
        tone = "muted"

    if result.get("bear_power_dominant") is True:
        power_text = f"多头力 {bull_power} / 空头力 {bear_power} · 空头力占优"
        tone = "warning" if tone != "positive" else "muted"
    elif result.get("bull_power_dominant") is True:
        power_text = f"多头力 {bull_power} / 空头力 {bear_power} · 多头力占优"
    else:
        power_text = f"多头力 {bull_power} / 空头力 {bear_power}"
    return {
        "label": "方向诊断",
        "value": f"{power_text} · {williams_text}",
        "tone": tone,
    }


def _v2_signal_driver(result):
    state_model = result.get("v2_state_model") or {}
    if state_model:
        plan_text = "需交易计划" if state_model.get("requires_trade_plan") else "不生成入场计划"
        stop_text = "需入场止损价" if state_model.get("requires_stop_loss") else "不要求入场止损价"
        return {
            "label": "V2状态",
            "value": (
                f"{_text(state_model.get('signal'))} {_text(state_model.get('signal_name'))}"
                f" · {_text(state_model.get('state_label'))} · {_text(state_model.get('permission_label'))}"
                f" · {plan_text} / {stop_text}"
            ),
            "tone": _text(state_model.get("tone"), "muted"),
        }
    if not result.get("v2_signal"):
        return None
    intent = _text(result.get("trade_intent_label"), "候选观察")
    plan_text = "需交易计划" if result.get("requires_trade_plan") else "不生成入场计划"
    stop_text = "需入场止损价" if result.get("requires_stop_loss") else "不要求入场止损价"
    return {
        "label": "V2定位",
        "value": (
            f"{_text(result.get('v2_signal'))} {_text(result.get('v2_signal_name'))}"
            f" · {_text(result.get('v2_role_label'))} · {intent} · {plan_text} / {stop_text}"
        ),
        "tone": _text(result.get("v2_tone"), "muted"),
    }


def _v2_fact_diagnostic(result):
    state_model = result.get("v2_state_model") or {}
    facts = state_model.get("facts") if isinstance(state_model.get("facts"), dict) else {}
    if not facts or facts.get("source") not in {
        "c_signal_v2_phase_2_3",
        "c_signal_v2_p4_facts",
        "c_signal_v2_p5_macro_facts",
        "c_signal_v2_p7_target_facts",
        "c_signal_v2_p8_macro_veto_facts",
        "c_signal_v2_p9a_normalized_bars_facts",
        "c_signal_v2_p9b_multi_rectangle_facts",
        "c_signal_v2_p9c_bear_trap_facts",
        "c_signal_v2_p10_resistance_zones_facts",
        "c_signal_v2_p11_exit_gate_facts",
        "c_signal_v2_p19_repair_watch_facts",
    }:
        return None

    structure = facts.get("structure") if isinstance(facts.get("structure"), dict) else {}
    trigger = facts.get("trigger") if isinstance(facts.get("trigger"), dict) else {}
    scores = facts.get("v2_scores") if isinstance(facts.get("v2_scores"), dict) else {}
    if not structure and not trigger and not scores:
        return None

    fragments = []
    fractals = structure.get("fractals") if isinstance(structure.get("fractals"), dict) else {}
    rectangle = structure.get("rectangle") if isinstance(structure.get("rectangle"), dict) else {}
    active_rectangle = structure.get("active_rectangle") if isinstance(structure.get("active_rectangle"), dict) else {}
    macro_rectangle = structure.get("macro_rectangle") if isinstance(structure.get("macro_rectangle"), dict) else {}
    bear_trap = structure.get("bear_trap_recovery") if isinstance(structure.get("bear_trap_recovery"), dict) else {}
    normalized_bars = structure.get("normalized_bars") if isinstance(structure.get("normalized_bars"), dict) else {}
    exit_gate = facts.get("exit_gate") if isinstance(facts.get("exit_gate"), dict) else {}
    repair = facts.get("repair") if isinstance(facts.get("repair"), dict) else {}
    ignition = trigger.get("ignition") if isinstance(trigger.get("ignition"), dict) else {}
    if repair.get("stage") == "repair_setup":
        fragments.append("修复观察")
        fragments.extend([str(value) for value in (repair.get("evidence") or [])[:3] if value])
    elif repair.get("stage") == "bottom_research":
        fragments.append("底背离研究")
    if fractals.get("double_bottom_higher_low"):
        fragments.append("双底抬高")
    elif fractals.get("latest_bottom"):
        fragments.append("底分型")
    if rectangle.get("available"):
        family = active_rectangle.get("family") or rectangle.get("family") or "短线"
        family_label = {"short": "短线", "swing": "波段", "macro": "一年"}.get(family, family)
        fragments.append(f"{family_label}矩形 {_text(rectangle.get('width_pct'))}%")
    if macro_rectangle and macro_rectangle.get("available"):
        fragments.append(f"一年矩形 {_text(macro_rectangle.get('width_pct'))}%")
    if normalized_bars.get("merge_count"):
        fragments.append(f"K线包含合并 {normalized_bars.get('merge_count')} 根")
    if bear_trap.get("breakout_after_recovery"):
        fragments.append("破底翻突破")
    elif bear_trap.get("recovered"):
        fragments.append("破底翻观察")
    if trigger.get("attack_day"):
        fragments.append("攻击日")
    if ignition.get("triggered"):
        fragments.append(f"起爆 {_text(ignition.get('trigger_price'))}")
    if exit_gate.get("action") == "sell":
        fragments.append("Exit Gate离场")
    elif exit_gate.get("action") == "scale_out":
        fragments.append("强阻减仓")
    elif (exit_gate.get("position_lifecycle") or {}).get("position_state") == "active":
        fragments.append("持仓防守线")
    if not fragments:
        fragments.append(structure.get("summary") or trigger.get("summary") or "事实仍在观察")

    score_text = (
        f"研究 {_text(scores.get('research_score'))}"
        f" / 结构 {_text(scores.get('structure_score'))}"
        f" / 触发 {_text(scores.get('trigger_quality'))}"
        f" / 风险 {_text(scores.get('execution_risk'))}"
    )
    tone = "positive" if trigger.get("attack_day") or ignition.get("triggered") else (
        "warning" if repair.get("stage") == "repair_setup" or structure.get("candidate") else "muted"
    )
    return {
        "label": "V2事实",
        "value": f"{' · '.join(fragments)} · {score_text}",
        "tone": tone,
    }


def _v2_plan_gate_driver(result):
    state_model = result.get("v2_state_model") or {}
    permission_model = state_model.get("v2_permission_model") if isinstance(state_model.get("v2_permission_model"), dict) else {}
    plan_gate = permission_model.get("plan_gate") if isinstance(permission_model.get("plan_gate"), dict) else {}
    if not plan_gate:
        return None
    fragments = [
        f"{_text(plan_gate.get('status_label'))}",
        f"{_text(plan_gate.get('entry_type'))}",
    ]
    if plan_gate.get("stop_distance_pct") is not None:
        fragments.append(f"止损 {_text(plan_gate.get('stop_distance_pct'))}%")
    if plan_gate.get("risk_reward_ratio") is not None:
        fragments.append(f"赔率 {_text(plan_gate.get('risk_reward_ratio'))}R")
    if plan_gate.get("target_label"):
        fragments.append(f"目标 {_text(plan_gate.get('target_label'))}")
    issues = plan_gate.get("block_reasons") or plan_gate.get("required_confirmations") or plan_gate.get("warnings") or []
    if issues:
        fragments.append(str(issues[0]))
    tone = {
        "ready": "positive",
        "waiting": "warning",
        "blocked": "danger",
    }.get(plan_gate.get("status"), "muted")
    return {
        "label": "交易闸门",
        "value": " · ".join(fragments),
        "tone": tone,
    }


def _v2_target_driver(result):
    state_model = result.get("v2_state_model") or {}
    facts = state_model.get("facts") if isinstance(state_model.get("facts"), dict) else {}
    target_structure = facts.get("target_structure") if isinstance(facts.get("target_structure"), dict) else {}
    if not target_structure:
        return None
    pullback_target = target_structure.get("pullback_target") if isinstance(target_structure.get("pullback_target"), dict) else {}
    breakout_target = target_structure.get("selected_breakout_target") if isinstance(target_structure.get("selected_breakout_target"), dict) else {}
    fragments = []
    if pullback_target.get("price") is not None:
        fragments.append(f"C回 {_text(pullback_target.get('label'))} {_text(pullback_target.get('price'))}")
    if breakout_target.get("price") is not None:
        strength = breakout_target.get("strength_score")
        distance = breakout_target.get("distance_pct")
        extra = []
        if strength is not None:
            extra.append(f"强度{_text(strength)}")
        if distance is not None:
            extra.append(f"距离{_text(distance)}%")
        suffix = f" ({' / '.join(extra)})" if extra else ""
        fragments.append(f"C突/C爆 {_text(breakout_target.get('label'))} {_text(breakout_target.get('price'))}{suffix}")
    if not fragments:
        fragments.append(_text(target_structure.get("summary"), "结构目标待确认"))
    return {
        "label": "结构目标",
        "value": " / ".join(fragments),
        "tone": "positive" if breakout_target or pullback_target else "warning",
    }


def _v2_macro_tide_driver(result):
    state_model = result.get("v2_state_model") or {}
    facts = state_model.get("facts") if isinstance(state_model.get("facts"), dict) else {}
    macro_tide = facts.get("macro_tide") if isinstance(facts.get("macro_tide"), dict) else {}
    if not macro_tide or not macro_tide.get("permission"):
        return None
    ma250 = macro_tide.get("ma250") if isinstance(macro_tide.get("ma250"), dict) else {}
    ma60 = macro_tide.get("ma60") if isinstance(macro_tide.get("ma60"), dict) else {}
    weekly = macro_tide.get("weekly_macd") if isinstance(macro_tide.get("weekly_macd"), dict) else {}
    fragments = []
    if ma60.get("available"):
        slope = "上行" if ma60.get("up") else "未上行"
        fragments.append(f"MA60 {slope} · 斜率 {_text(ma60.get('slope_pct'))}%")
    if ma250.get("available"):
        side = "站上" if ma250.get("above") else "跌破"
        fragments.append(f"MA250 {side} · 斜率 {_text(ma250.get('slope_pct'))}%")
    if weekly.get("available"):
        fragments.append(f"周MACD柱 {_text(weekly.get('hist'))} · 变化 {_text(weekly.get('hist_delta'))}")
    if not fragments:
        fragments.append(_text(macro_tide.get("summary"), "大周期数据不足"))
    tone = {
        "allowed": "positive",
        "watch": "warning",
        "forbidden": "danger",
        "unknown": "muted",
    }.get(macro_tide.get("permission"), "muted")
    return {
        "label": "大周期",
        "value": f"{_text(macro_tide.get('label'))} · {' / '.join(fragments)}",
        "tone": tone,
    }


def _v2_environment_driver(result):
    if not result.get("v2_environment_permission"):
        return None
    return {
        "label": "宏观环境",
        "value": (
            f"{_text(result.get('v2_macro_veto_label'), _text(result.get('v2_environment_label')))}"
            f" · {_text(result.get('v2_macro_veto_reason'), '仅用于宏观许可或否决')}"
        ),
        "tone": _text(result.get("v2_macro_veto_tone"), _text(result.get("v2_environment_tone"), "muted")),
    }


def build_score_badges(result):
    risk = classify_risk_score(result.get("risk_score"))
    history = classify_history_stats(result.get("win_rate"), result.get("avg_ret"))
    confidence = classify_score_confidence(result.get("score_confidence"))
    badges = [
        {"label": "结构", "value": _text(result.get("setup_score")), "tone": "muted", "hint": "价格结构基础分"},
        {"label": "确认", "value": _text(result.get("confirm_score")), "tone": "positive", "hint": "趋势和量能确认分"},
        {"label": "风险", "value": _text(result.get("risk_score")), "tone": risk["tone"], "hint": risk["hint"]},
    ]
    state_model = result.get("v2_state_model") or {}
    if state_model:
        badges.append({
            "label": "定位",
            "value": _text(state_model.get("permission_label"), _text(state_model.get("role_label"))),
            "tone": _text(state_model.get("tone"), "muted"),
            "hint": _text(state_model.get("reason"), _text(state_model.get("detail"), "V2 状态模型")),
        })
        permission_model = state_model.get("v2_permission_model") if isinstance(state_model.get("v2_permission_model"), dict) else {}
        plan_gate = permission_model.get("plan_gate") if isinstance(permission_model.get("plan_gate"), dict) else {}
        if plan_gate:
            badges.append({
                "label": "闸门",
                "value": _text(plan_gate.get("status_label")),
                "tone": {
                    "ready": "positive",
                    "waiting": "warning",
                    "blocked": "danger",
                }.get(plan_gate.get("status"), "muted"),
                "hint": "C回/C突/C爆 统一经过结构止损、赔率和追高风险校验",
            })
        facts = state_model.get("facts") if isinstance(state_model.get("facts"), dict) else {}
        target_structure = facts.get("target_structure") if isinstance(facts.get("target_structure"), dict) else {}
        if target_structure:
            selected = target_structure.get("selected_breakout_target") or target_structure.get("pullback_target") or {}
            badges.append({
                "label": "目标",
                "value": _text(selected.get("label"), "待确认"),
                "tone": "positive" if selected else "warning",
                "hint": "目标价按入场类型选择：C回看箱体上沿，C突/C爆看上方结构阻力",
            })
    elif result.get("v2_role_label"):
        badges.append({
            "label": "定位",
            "value": _text(result.get("v2_role_label")),
            "tone": _text(result.get("v2_tone"), "muted"),
            "hint": _text(result.get("v2_detail"), _text(result.get("v2_state_label"), "V2 信号定位")),
        })
    if result.get("pool_stage_label"):
        badges.insert(0, {
            "label": "阶段",
            "value": _text(result.get("pool_stage_label")),
            "tone": _text(result.get("pool_stage_tone"), "muted"),
            "hint": _text(result.get("pool_stage_detail"), "池子内阶段判断"),
        })
    if result.get("v2_environment_permission"):
        badges.append({
            "label": "环境",
            "value": _text(result.get("v2_environment_label")),
            "tone": _text(result.get("v2_environment_tone"), "muted"),
            "hint": "环境许可用于降级或阻止可执行候选，不单独制造买点",
        })
    macro_tide = {}
    if isinstance(state_model.get("facts"), dict) and isinstance(state_model["facts"].get("macro_tide"), dict):
        macro_tide = state_model["facts"]["macro_tide"]
    if macro_tide.get("permission"):
        macro_tone = {
            "allowed": "positive",
            "watch": "warning",
            "forbidden": "danger",
            "unknown": "muted",
        }.get(macro_tide.get("permission"), "muted")
        badges.append({
            "label": "大周期",
            "value": _text(macro_tide.get("label")),
            "tone": macro_tone,
            "hint": "大周期潮汐只负责许可或拦截可执行入场，不制造买点",
        })
    badges.extend([
        {"label": "胜率", "value": _format_percent(result.get("win_rate")), "tone": history["tone"], "hint": history["hint"]},
        {"label": "均值", "value": _format_signed_percent(result.get("avg_ret")), "tone": history["tone"], "hint": history["hint"]},
        {"label": "可信", "value": _text((result.get("score_confidence") or {}).get("label"), confidence["label"]), "tone": confidence["tone"], "hint": confidence["hint"]},
    ])
    return badges


def build_scan_explanation(result):
    rank = classify_rank_score(result.get("rank_score"))
    risk = classify_risk_score(result.get("risk_score"))
    history = classify_history_stats(result.get("win_rate"), result.get("avg_ret"))
    confidence = classify_score_confidence(result.get("score_confidence"))
    signal_name = _text(
        result.get("v2_signal_name") or result.get("signal_name") or result.get("signal_label") or result.get("signal"),
        "扫描信号",
    )
    sector_name = _text(result.get("sector"), UNKNOWN_SECTOR_LABEL)
    concept_text = _concept_text(result)
    sector_context = f"{sector_name} · {concept_text}" if concept_text else sector_name
    reason = _text(result.get("reason"), signal_name)

    drivers = [
        {"label": "事件触发", "value": reason, "tone": "positive"},
        {
            "label": "强度来源",
            "value": f"强度 {_text(result.get('rank_score'))} · 结构 {_text(result.get('setup_score'))} / 确认 {_text(result.get('confirm_score'))}",
            "tone": rank["tone"],
        },
        {"label": "所属行业/概念", "value": sector_context, "tone": "muted"},
        {
            "label": "历史表现",
            "value": f"胜率 {_format_percent(result.get('win_rate'))} · 均值 {_format_signed_percent(result.get('avg_ret'))}",
            "tone": history["tone"],
        },
        {
            "label": "评分可信",
            "value": (result.get("score_confidence") or {}).get("basis") or confidence["label"],
            "tone": confidence["tone"],
        },
    ]
    v2_driver = _v2_signal_driver(result)
    if v2_driver:
        drivers.insert(0, v2_driver)
    diagnostic_drivers = [
        item for item in (
            _v2_fact_diagnostic(result),
            _v2_plan_gate_driver(result),
            _v2_target_driver(result),
            _v2_macro_tide_driver(result),
            _v2_environment_driver(result),
            _breakout_diagnostic(result),
            _risk_split_diagnostic(result),
            _direction_diagnostic(result),
        )
        if item is not None
    ]
    if diagnostic_drivers:
        drivers[2:2] = diagnostic_drivers
    if result.get("pool_stage_label"):
        drivers.insert(0, {
            "label": "池子定位",
            "value": f"{_text(result.get('pool_stage_label'))} · {_text(result.get('pool_stage_detail'))}",
            "tone": _text(result.get("pool_stage_tone"), "muted"),
        })
    cautions = []
    if _number(result.get("risk_score"), 0.0) > 0:
        cautions.append({
            "label": "风险控制",
            "value": f"{risk['label']} · 风险分 {_text(result.get('risk_score'))}",
            "tone": risk["tone"],
        })
    if history["tone"] != "positive":
        cautions.append({
            "label": "样本校验",
            "value": f"{history['label']} · 需结合图表确认",
            "tone": history["tone"],
        })
    if confidence["tone"] != "positive":
        cautions.append({
            "label": "可信度",
            "value": confidence["hint"],
            "tone": confidence["tone"],
        })
    if not cautions:
        cautions.append({
            "label": "注意",
            "value": "仍需结合当日量价和止损位确认",
            "tone": "muted",
        })

    stage_summary = f"{_text(result.get('pool_stage_label'))}，" if result.get("pool_stage_label") else ""
    summary = f"{stage_summary}{history['label']}，{risk['label']}，{confidence['label']}"
    return {
        "version": EXPLANATION_VERSION,
        "headline": f"{rank['label']} · {signal_name}",
        "summary": summary,
        "card_summary": f"{summary} · {reason}",
        "drivers": drivers,
        "cautions": cautions,
        "score_badges": build_score_badges(result),
    }


def build_scan_view_model(result, explanation=None):
    explanation = explanation or build_scan_explanation(result)
    rank = classify_rank_score(result.get("final_score") if result.get("final_score") is not None else result.get("rank_score"))
    risk = classify_risk_score(result.get("risk_score"))
    confidence = classify_score_confidence(result.get("score_confidence"))
    state_model = result.get("v2_state_model") or {}
    if state_model:
        signal_text = (
            _text(state_model.get("signal"), "信号")
            + " "
            + _text(state_model.get("signal_name"), "")
        ).strip()
    elif result.get("v2_signal"):
        signal_text = (
            _text(result.get("v2_signal"), "信号")
            + " "
            + _text(result.get("v2_signal_name"), "")
        ).strip()
    else:
        signal_text = (
            _text(result.get("signal_label") or result.get("signal"), "信号")
            + " "
            + _text(result.get("signal_name"), "")
        ).strip()
    concept_text = _concept_text(result)
    sector = _text(result.get("sector"), UNKNOWN_SECTOR_LABEL)
    context = f"{sector} · {concept_text}" if concept_text else sector
    score = result.get("final_score") if result.get("final_score") is not None else result.get("rank_score")
    decision = _text(result.get("pool_stage_label"), "")
    if not decision or decision == "-":
        decision = _text(state_model.get("permission_label"), _text(result.get("v2_role_label"), ""))
    if not decision or decision == "-":
        decision = confidence["label"] if confidence["label"] != "可信度待定" else rank["label"]
    return {
        "headline": explanation["headline"],
        "summary": explanation["summary"],
        "card_summary": explanation["card_summary"],
        "signal_text": signal_text,
        "context": context,
        "decision_label": decision,
        "score_label": _text(score),
        "risk_label": risk["label"],
        "confidence_label": confidence["label"],
    }


def attach_scan_explanation(result):
    if result is not None:
        explanation = build_scan_explanation(result)
        result["explanation"] = explanation
        result["view_model"] = build_scan_view_model(result, explanation=explanation)
    return result
