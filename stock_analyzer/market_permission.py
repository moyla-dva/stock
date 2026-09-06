"""Trading permission layer for turning signals into action constraints."""

import math


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


def _as_bool(value):
    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def _latest_row(df_display):
    if df_display is None or df_display.empty:
        return None
    return df_display.iloc[-1]


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def build_stock_trade_permission(df_display, context=None):
    """Build a single-stock execution permission from the latest analyzed row.

    This is intentionally narrower than a full market permission engine. It gives
    the single-stock page a stable contract while broader market-structure
    checks are rebuilt around the same shape later.
    """
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "version": 1,
            "scope": "single_stock",
            "mode": "no_data",
            "mode_label": "无数据",
            "can_open": False,
            "can_add": False,
            "can_hold": False,
            "action": "先补齐行情数据",
            "risk_action": "不做判断",
            "forbidden_reasons": ["没有足够行情数据"],
            "warnings": [],
            "required_confirmations": ["补齐日线样本"],
            "scores": {"setup": 0, "confirm": 0, "risk": 0},
            "signals": {"entry": False, "risk": False, "exit": False, "watch": False},
            "context": {"alignment": "unknown", "detail": "未接入市场上下文"},
        }

    context = context or {}
    setup_score = _as_int(latest.get("composite_setup_score"))
    confirm_score = _as_int(latest.get("composite_confirm_score"))
    risk_score = _as_int(latest.get("composite_risk_score"))
    has_entry = _as_bool(latest.get("composite_entry"))
    has_risk = _as_bool(latest.get("composite_risk")) or _as_bool(latest.get("composite_risk_warn"))
    has_exit = _as_bool(latest.get("composite_exit"))
    has_watch = _as_bool(latest.get("composite_watch"))

    forbidden_reasons = []
    warnings = []
    required_confirmations = []
    can_open = False
    can_add = False
    can_hold = True
    mode = "observe"
    mode_label = "观察"
    action = "不急于参与，等待结构和触发更清楚"
    risk_action = "保持轻仓或空仓观察"

    if has_exit or risk_score >= 4:
        mode = "risk_control"
        mode_label = "风险处理"
        can_hold = False
        action = "停止新开，优先处理止损或趋势破坏"
        risk_action = "按原计划止损/减仓，不摊低成本"
        forbidden_reasons.append("风险分过高或离场信号已触发")
    elif has_risk or risk_score >= 3:
        mode = "defensive"
        mode_label = "防守"
        action = "暂不新开，先确认风险是否扩散"
        risk_action = "已有仓位先看保护位，未持仓不追"
        forbidden_reasons.append("风险条件已出现")
        warnings.append("需要先确认跌破、顶背离或趋势转弱是否继续")
    elif has_entry and confirm_score >= 3:
        mode = "execution_ready"
        mode_label = "可执行"
        can_open = True
        can_add = confirm_score >= 4 and risk_score <= 1
        action = "已有触发，可进入止损和仓位校验"
        risk_action = "先算亏多少，再决定买多少"
        required_confirmations.extend(["止损距离合格", "仓位风险合格"])
    elif has_watch and confirm_score >= 3:
        mode = "wait_trigger"
        mode_label = "等触发"
        action = "结构有雏形，但还缺明确入场触发"
        risk_action = "不要提前重仓，等待突破或回踩确认"
        forbidden_reasons.append("尚未触发入场")
        required_confirmations.extend(["突破最近高点", "回踩不破关键支撑", "量能或趋势确认"])
    elif has_watch or setup_score >= 2:
        mode = "structure_watch"
        mode_label = "结构观察"
        action = "只观察结构，不直接下单"
        risk_action = "等待确认分提升，同时避免左侧放大仓位"
        forbidden_reasons.append("确认不足")
        required_confirmations.extend(["确认分提升", "风险分下降"])
    else:
        forbidden_reasons.append("没有交易结构")
        required_confirmations.extend(["先出现结构证据", "再等待入场触发"])

    context_alignment = str(context.get("alignment") or "unlinked")
    context_detail = str(context.get("detail") or "当前仅代表单股技术确认，仍需核对市场结构")
    if context_alignment == "unlinked":
        warnings.append("未完成市场结构核对，不能把单股信号直接等同于可交易")

    return {
        "version": 1,
        "scope": "single_stock",
        "date": _format_date(latest.get("date")),
        "mode": mode,
        "mode_label": mode_label,
        "can_open": can_open,
        "can_add": can_add,
        "can_hold": can_hold,
        "action": action,
        "risk_action": risk_action,
        "forbidden_reasons": forbidden_reasons,
        "warnings": warnings,
        "required_confirmations": required_confirmations,
        "scores": {
            "setup": setup_score,
            "confirm": confirm_score,
            "risk": risk_score,
        },
        "signals": {
            "entry": has_entry,
            "risk": has_risk,
            "exit": has_exit,
            "watch": has_watch,
        },
        "context": {
            "alignment": context_alignment,
            "detail": context_detail,
        },
    }
