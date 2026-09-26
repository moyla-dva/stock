"""Macro permission layer for turning signals into action constraints."""


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


def _v2_state_entry_type(state_model):
    permission_model = state_model.get("v2_permission_model") if isinstance(state_model.get("v2_permission_model"), dict) else {}
    plan_gate = permission_model.get("plan_gate") if isinstance(permission_model.get("plan_gate"), dict) else {}
    entry_type = str(plan_gate.get("entry_type") or "").strip()
    if entry_type:
        return entry_type
    permission = str(state_model.get("permission") or "").strip()
    state = str(state_model.get("state") or "").strip()
    signal = str(state_model.get("signal") or "").strip()
    if permission == "attack_allowed" or state in {"attack_trigger", "ignition_triggered"} or signal == "C爆":
        return "attack"
    if permission == "breakout_allowed" or state == "entry_breakout" or signal == "C突":
        return "breakout"
    if permission == "pullback_allowed" or state == "entry_pullback" or signal == "C回":
        return "pullback"
    return ""


def evaluate_macro_entry_blocks(macro_tide, entry_type):
    """MA60/MA250/周线 MACD 的入场宏观判定唯一实现。

    c_signal_v2 的入场闸门与环境许可的宏观否决共用此核心；本函数只返回
    原始判定（block_reasons/warnings/macro 可用性），输出形状（label/tone/
    reason）由各消费端自行组装，禁止再复制判定逻辑。
    """
    macro_tide = macro_tide if isinstance(macro_tide, dict) else {}
    entry_type = str(entry_type or "").strip()
    ma60 = macro_tide.get("ma60") if isinstance(macro_tide.get("ma60"), dict) else {}
    ma250 = macro_tide.get("ma250") if isinstance(macro_tide.get("ma250"), dict) else {}
    weekly = macro_tide.get("weekly_macd") if isinstance(macro_tide.get("weekly_macd"), dict) else {}
    block_reasons = []
    warnings = []

    if entry_type in {"attack", "breakout"}:
        if ma250.get("available") and ma250.get("above") is False:
            block_reasons.append("C突/C爆 位于 MA250 下方，突破诱多风险过高")
        if weekly.get("available") and (
            weekly.get("dead_cross_down")
            or weekly.get("bearish_cross_down")
            or weekly.get("bearish_expanding")
        ):
            block_reasons.append("周线 MACD 死叉向下或空方扩张，突破不允许升级")
        if not ma250.get("available"):
            warnings.append("MA250 样本不足，突破大势仍需人工核对")
        if not weekly.get("available"):
            warnings.append("周线 MACD 样本不足，突破大势仍需人工核对")
    elif entry_type == "pullback":
        if ma60.get("available") and ma60.get("up") is not True:
            block_reasons.append("C回 所需的 MA60 上行条件未满足")
        if not ma60.get("available"):
            warnings.append("MA60 样本不足，回踩大势仍需人工核对")
    elif macro_tide.get("permission") in {"forbidden", "watch", "unknown"}:
        warnings.append(macro_tide.get("summary") or "大周期潮汐待核")

    return {
        "block_reasons": _unique_text(block_reasons),
        "warnings": _unique_text(warnings),
        "macro_available": bool(macro_tide.get("available")),
        "macro_summary": macro_tide.get("summary"),
    }


def _v2_macro_veto_permission(state_model):
    facts = state_model.get("facts") if isinstance(state_model.get("facts"), dict) else {}
    macro_tide = facts.get("macro_tide") if isinstance(facts.get("macro_tide"), dict) else {}
    entry_type = _v2_state_entry_type(state_model)
    gate = evaluate_macro_entry_blocks(macro_tide, entry_type)
    block_reasons = gate["block_reasons"]
    warnings = gate["warnings"]

    if block_reasons:
        return {
            "permission": "forbidden",
            "label": "宏观否决",
            "tone": "danger",
            "reason": block_reasons[0],
            "block_reasons": _unique_text(block_reasons),
            "warnings": _unique_text(warnings),
        }
    if warnings:
        return {
            "permission": "watch",
            "label": "宏观待核",
            "tone": "warning",
            "reason": warnings[0],
            "block_reasons": [],
            "warnings": _unique_text(warnings),
        }
    if macro_tide.get("available"):
        return {
            "permission": "allowed",
            "label": "宏观许可",
            "tone": "positive",
            "reason": macro_tide.get("summary") or "个股长周期未触发一票否决",
            "block_reasons": [],
            "warnings": [],
        }
    return {
        "permission": "unknown",
        "label": "宏观待核",
        "tone": "muted",
        "reason": "缺少个股长周期环境数据",
        "block_reasons": [],
        "warnings": [],
    }


def build_v2_environment_permission(result):
    """Apply only the per-stock macro gate; sector/concept are descriptive."""
    result = result or {}
    scan_type = str(result.get("scan_type") or result.get("_scan_type") or "opportunity")
    state_model = result.get("v2_state_model") if isinstance(result.get("v2_state_model"), dict) else {}
    state_permission = state_model.get("permission") or result.get("v2_permission") or ""

    macro_veto = _v2_macro_veto_permission(state_model)
    environment_permission = macro_veto["permission"]
    label = macro_veto["label"]
    tone = macro_veto["tone"]
    block_reasons = list(macro_veto.get("block_reasons") or [])
    warnings = list(macro_veto.get("warnings") or [])
    reasons = [macro_veto["reason"]] if macro_veto.get("reason") else []
    effect = "allow"
    effective_permission = state_permission or "unknown"

    if scan_type == "risk" or state_permission == "risk_only":
        environment_permission = "risk_only"
        label = "风险优先"
        tone = "danger"
        effect = "risk_first"
        effective_permission = "risk_only"
    elif environment_permission == "forbidden":
        effect = "block_entry"
        if state_permission in {"attack_allowed", "breakout_allowed", "pullback_allowed"}:
            effective_permission = "environment_blocked"
    elif environment_permission == "watch":
        effect = "downgrade_entry"
        if state_permission in {"attack_allowed", "breakout_allowed", "pullback_allowed"}:
            effective_permission = "environment_watch"
    elif environment_permission == "unknown":
        effect = "needs_context"
        if state_permission in {"attack_allowed", "breakout_allowed", "pullback_allowed"}:
            effective_permission = "environment_unknown"

    not_used = {
        "permission": "not_used",
        "label": "不参与判定",
        "reason": "行业/概念仅作候选分布统计",
    }

    return {
        "v2_environment_permission": environment_permission,
        "v2_environment_label": label,
        "v2_environment_tone": tone,
        "v2_environment_effect": effect,
        "v2_effective_permission": effective_permission,
        "v2_market_permission": environment_permission,
        "v2_macro_veto_permission": macro_veto["permission"],
        "v2_macro_veto_label": macro_veto["label"],
        "v2_macro_veto_tone": macro_veto["tone"],
        "v2_macro_veto_reason": macro_veto["reason"],
        "v2_macro_veto_block_reasons": macro_veto["block_reasons"],
        "v2_macro_veto_warnings": macro_veto["warnings"],
        "v2_sector_permission": not_used["permission"],
        "v2_sector_permission_label": not_used["label"],
        "v2_sector_permission_reason": not_used["reason"],
        "v2_concept_permission": not_used["permission"],
        "v2_concept_permission_label": not_used["label"],
        "v2_concept_permission_reason": not_used["reason"],
        "v2_environment_reasons": reasons,
        "v2_environment_block_reasons": [reason for reason in block_reasons if reason],
        "v2_environment_warnings": [reason for reason in warnings if reason],
    }
