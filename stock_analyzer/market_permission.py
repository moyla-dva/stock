"""Trading permission layer for turning signals into action constraints."""

import math



def _as_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        if value is None:
            return default
        number = float(value)
        if math.isnan(number):
            return default
        return int(number)
    except (TypeError, ValueError):
        return default


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


def _board_permission(result, prefix):
    score = _as_float(result.get(f"{prefix}_score"))
    market_score = _as_float(result.get(f"{prefix}_market_score"))
    width_score = _as_float(result.get(f"{prefix}_width_score"))
    opportunity_count = _as_int(result.get(f"{prefix}_opportunity_count"), 0)
    bottom_count = _as_int(result.get(f"{prefix}_bottom_div_count"), 0)
    risk_count = _as_int(result.get(f"{prefix}_risk_count"), 0)
    signal_count = _as_int(result.get(f"{prefix}_signal_count"), 0)
    evidence = [
        value for value in (score, market_score, width_score)
        if value is not None
    ]
    has_counts = any(value > 0 for value in (opportunity_count, bottom_count, risk_count, signal_count))
    if not evidence and not has_counts:
        return {
            "permission": "unknown",
            "label": "环境待核",
            "tone": "muted",
            "reason": "缺少板块或概念环境数据",
        }

    supportive_count = opportunity_count + bottom_count
    if market_score is not None and market_score < 40:
        return {
            "permission": "forbidden",
            "label": "环境逆风",
            "tone": "danger",
            "reason": "板块指数偏弱，禁止把个股触发升级为可执行",
        }
    if risk_count > max(supportive_count, 0) and (score is None or score < 35):
        return {
            "permission": "forbidden",
            "label": "风险扩散",
            "tone": "danger",
            "reason": "同板块或概念风险候选多于机会候选",
        }
    if (
        (score is not None and score >= 60)
        or (market_score is not None and market_score >= 55)
        or (width_score is not None and width_score >= 25)
    ):
        return {
            "permission": "allowed",
            "label": "环境许可",
            "tone": "positive",
            "reason": "板块或概念共振足以支持候选升级",
        }
    if (
        (score is not None and score >= 25)
        or (market_score is not None and market_score >= 40)
        or (width_score is not None and width_score > 0)
        or supportive_count > 0
    ):
        return {
            "permission": "watch",
            "label": "环境观察",
            "tone": "warning",
            "reason": "环境有线索但不足以支持可执行升级",
        }
    return {
        "permission": "watch",
        "label": "环境弱",
        "tone": "warning",
        "reason": "板块或概念共振不足，个股触发只能观察",
    }


def _combine_environment_permissions(sector, concept):
    ordered = [sector, concept]
    if any(item["permission"] == "forbidden" for item in ordered):
        return "forbidden"
    if any(item["permission"] == "allowed" for item in ordered):
        return "allowed"
    if any(item["permission"] == "watch" for item in ordered):
        return "watch"
    return "unknown"


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
    """Build V2 market/sector permission without changing legacy scores."""
    result = result or {}
    scan_type = str(result.get("scan_type") or result.get("_scan_type") or "opportunity")
    state_model = result.get("v2_state_model") if isinstance(result.get("v2_state_model"), dict) else {}
    state_permission = state_model.get("permission") or result.get("v2_permission") or ""

    sector = _board_permission(result, "sector")
    concept = _board_permission(result, "concept")
    macro_veto = _v2_macro_veto_permission(state_model)
    environment_permission = _combine_environment_permissions(sector, concept)
    block_reasons = []
    warnings = []
    reasons = []
    for item in (sector, concept):
        reason = item.get("reason")
        if reason:
            reasons.append(reason)
        if item.get("permission") == "forbidden":
            block_reasons.append(reason)
        elif item.get("permission") in {"watch", "unknown"}:
            warnings.append(reason)
    if macro_veto.get("reason"):
        reasons.append(macro_veto.get("reason"))
    if macro_veto.get("permission") == "forbidden":
        block_reasons.extend(macro_veto.get("block_reasons") or [macro_veto.get("reason")])
    elif macro_veto.get("permission") in {"watch", "unknown"}:
        warnings.extend(macro_veto.get("warnings") or [macro_veto.get("reason")])

    if macro_veto.get("permission") == "forbidden":
        environment_permission = "forbidden"

    effect = "neutral"
    effective_permission = state_permission or "unknown"
    if scan_type == "risk" or state_permission == "risk_only":
        environment_permission = "risk_only"
        label = "风险优先"
        tone = "danger"
        effect = "risk_first"
        effective_permission = "risk_only"
    elif environment_permission == "allowed":
        label = "环境许可"
        tone = "positive"
        effect = "allow"
    elif environment_permission == "forbidden":
        label = "环境禁止"
        tone = "danger"
        effect = "block_entry"
        effective_permission = "environment_blocked" if state_permission in {
            "attack_allowed",
            "breakout_allowed",
            "pullback_allowed",
        } else state_permission or "forbidden"
    elif environment_permission == "watch":
        label = "环境观察"
        tone = "warning"
        effect = "downgrade_entry"
        effective_permission = "environment_watch" if state_permission in {
            "attack_allowed",
            "breakout_allowed",
            "pullback_allowed",
        } else state_permission or "watch_only"
    else:
        label = "环境待核"
        tone = "muted"
        effect = "needs_context"
        effective_permission = "environment_unknown" if state_permission in {
            "attack_allowed",
            "breakout_allowed",
            "pullback_allowed",
        } else state_permission or "unknown"

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
        "v2_sector_permission": sector["permission"],
        "v2_sector_permission_label": sector["label"],
        "v2_sector_permission_reason": sector["reason"],
        "v2_concept_permission": concept["permission"],
        "v2_concept_permission_label": concept["label"],
        "v2_concept_permission_reason": concept["reason"],
        "v2_environment_reasons": reasons,
        "v2_environment_block_reasons": [reason for reason in block_reasons if reason],
        "v2_environment_warnings": [reason for reason in warnings if reason],
    }
