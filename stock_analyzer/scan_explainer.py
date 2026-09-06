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


def classify_sector_score(score):
    value = _number(score)
    if value is None:
        return {"label": "板块共振待定", "tone": "muted", "hint": "缺少板块共振分"}
    if value >= 75:
        return {"label": "板块共振强", "tone": "positive", "hint": "同板块候选集中且风险较少"}
    if value >= 50:
        return {"label": "板块有共振", "tone": "positive", "hint": "板块内有一定候选聚集"}
    if value >= 25:
        return {"label": "板块弱共振", "tone": "warning", "hint": "板块支持有限"}
    return {"label": "板块未共振", "tone": "muted", "hint": "主要依赖个股信号"}


def classify_market_score(score):
    value = _number(score)
    if value is None:
        return {"label": "板指待定", "tone": "muted", "hint": "缺少板块指数强弱"}
    if value >= 75:
        return {"label": "板指强势", "tone": "positive", "hint": "板块指数趋势强"}
    if value >= 55:
        return {"label": "板指偏强", "tone": "positive", "hint": "板块指数处于偏强环境"}
    if value >= 40:
        return {"label": "板指震荡", "tone": "warning", "hint": "板块指数环境中性"}
    return {"label": "板指偏弱", "tone": "danger", "hint": "板块指数环境偏弱"}


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


def build_score_badges(result):
    risk = classify_risk_score(result.get("risk_score"))
    sector = classify_sector_score(result.get("sector_score"))
    market = classify_market_score(result.get("sector_market_score"))
    history = classify_history_stats(result.get("win_rate"), result.get("avg_ret"))
    confidence = classify_score_confidence(result.get("score_confidence"))
    badges = [
        {"label": "结构", "value": _text(result.get("setup_score")), "tone": "muted", "hint": "价格结构基础分"},
        {"label": "确认", "value": _text(result.get("confirm_score")), "tone": "positive", "hint": "趋势和量能确认分"},
        {"label": "风险", "value": _text(result.get("risk_score")), "tone": risk["tone"], "hint": risk["hint"]},
        {"label": "共振", "value": _text(result.get("sector_score")), "tone": sector["tone"], "hint": sector["hint"]},
    ]
    if result.get("pool_stage_label"):
        badges.insert(0, {
            "label": "阶段",
            "value": _text(result.get("pool_stage_label")),
            "tone": _text(result.get("pool_stage_tone"), "muted"),
            "hint": _text(result.get("pool_stage_detail"), "池子内阶段判断"),
        })
    if _number(result.get("sector_market_score")) is not None:
        badges.append({
            "label": "板指",
            "value": _text(result.get("sector_market_trend"), _text(result.get("sector_market_score"))),
            "tone": market["tone"],
            "hint": market["hint"],
        })
    if _number(result.get("concept_market_score")) is not None:
        concept_market = classify_market_score(result.get("concept_market_score"))
        badges.append({
            "label": "概指",
            "value": _text(result.get("concept_market_trend"), _text(result.get("concept_market_score"))),
            "tone": concept_market["tone"],
            "hint": concept_market["hint"],
        })
    badges.extend([
        {"label": "胜率", "value": _format_percent(result.get("win_rate")), "tone": history["tone"], "hint": history["hint"]},
        {"label": "均值", "value": _format_signed_percent(result.get("avg_ret")), "tone": history["tone"], "hint": history["hint"]},
        {"label": "可信", "value": _text((result.get("score_confidence") or {}).get("label"), confidence["label"]), "tone": confidence["tone"], "hint": confidence["hint"]},
    ])
    return badges


def build_scan_explanation(result):
    rank = classify_rank_score(result.get("rank_score"))
    sector = classify_sector_score(result.get("sector_score"))
    market = classify_market_score(result.get("sector_market_score"))
    risk = classify_risk_score(result.get("risk_score"))
    history = classify_history_stats(result.get("win_rate"), result.get("avg_ret"))
    confidence = classify_score_confidence(result.get("score_confidence"))
    signal_name = _text(result.get("signal_name") or result.get("signal_label") or result.get("signal"), "扫描信号")
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
        {
            "label": "板块背景",
            "value": f"{sector_context} · {sector['label']} · 机会 {_text(result.get('sector_signal_count'))} / 风险 {_text(result.get('sector_risk_count'))}",
            "tone": sector["tone"],
        },
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
    if result.get("pool_stage_label"):
        drivers.insert(0, {
            "label": "池子定位",
            "value": f"{_text(result.get('pool_stage_label'))} · {_text(result.get('pool_stage_detail'))}",
            "tone": _text(result.get("pool_stage_tone"), "muted"),
        })
    if _number(result.get("sector_market_score")) is not None:
        drivers.insert(3, {
            "label": "板块指数",
            "value": (
                f"{market['label']} · 5日 {_format_signed_percent(result.get('sector_market_ret_5'))}"
                f" · 板块加成 {_text(result.get('sector_market_boost'))}"
            ),
            "tone": market["tone"],
        })
    if _number(result.get("concept_market_score")) is not None:
        drivers.insert(4, {
            "label": "概念指数",
            "value": (
                f"{_text(result.get('concept_focus'), '概念')} · {_text(result.get('concept_market_trend'))}"
                f" · 5日 {_format_signed_percent(result.get('concept_market_ret_5'))}"
                f" · 概念加成 {_text(result.get('concept_market_boost'))}"
            ),
            "tone": classify_market_score(result.get("concept_market_score"))["tone"],
        })

    cautions = []
    if _number(result.get("risk_score"), 0.0) > 0:
        cautions.append({
            "label": "风险控制",
            "value": f"{risk['label']} · 风险分 {_text(result.get('risk_score'))}",
            "tone": risk["tone"],
        })
    if _number(result.get("sector_risk_count"), 0.0) > 0:
        cautions.append({
            "label": "板块压力",
            "value": f"同板块风险候选 {result.get('sector_risk_count')} 只",
            "tone": "warning",
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

    market_summary = f"，{market['label']}" if _number(result.get("sector_market_score")) is not None else ""
    stage_summary = f"{_text(result.get('pool_stage_label'))}，" if result.get("pool_stage_label") else ""
    summary = f"{stage_summary}{sector['label']}{market_summary}，{history['label']}，{risk['label']}，{confidence['label']}"
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
