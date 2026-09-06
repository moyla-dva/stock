"""Trade-plan contract derived from analyzed signal and structure evidence."""

import math

from stock_analyzer.market_permission import build_stock_trade_permission
from stock_analyzer.technical_structures import build_technical_structures


MAX_STOP_DISTANCE_PCT = 8.0
DEFAULT_RISK_PCT = 3.0
DEFAULT_MAX_CAPITAL_PCT = 30.0
BOARD_LOT_SIZE = 100
MIN_RISK_REWARD = 2.0
IDEAL_RISK_REWARD = 3.0


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


def _as_bool(value):
    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def _as_int(value, default=None):
    number = _as_float(value)
    if number is None:
        return default
    return int(number)


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def _round_price(value):
    return None if value is None else round(float(value), 2)


def _entry_type_label(entry_type):
    if entry_type == "breakout":
        return "突破确认"
    if entry_type == "pullback":
        return "回踩确认"
    if entry_type in {"repair-confirm", "watch-confirm"}:
        return "修复确认"
    return "综合触发"


def _recent_low(df_display, window=5):
    if df_display is None or df_display.empty or "low" not in df_display.columns:
        return None
    return _as_float(df_display.tail(window)["low"].min())


def _recent_high(df_display, window=5):
    if df_display is None or df_display.empty or "high" not in df_display.columns:
        return None
    return _as_float(df_display.tail(window)["high"].max())


def _column_latest(df_display, column):
    if df_display is None or df_display.empty or column not in df_display.columns:
        return None
    return df_display.iloc[-1].get(column)


def _previous_low(df_display):
    if df_display is None or len(df_display) < 2 or "low" not in df_display.columns:
        return None
    return _as_float(df_display.iloc[-2].get("low"))


def _stop_plan(df_display, latest, permission):
    close = _as_float(latest.get("close"))
    latest_low = _as_float(latest.get("low"))
    previous_low = _previous_low(df_display)
    recent_low = _recent_low(df_display)

    basis = "前一日低点/近五日低点"
    candidates = [value for value in [latest_low, previous_low, recent_low] if value is not None]
    stop_price = min(candidates) if candidates else None
    if close is not None and stop_price is not None and stop_price >= close:
        stop_price = None

    distance_pct = None
    risk_per_share = None
    if close is not None and stop_price is not None:
        risk_per_share = close - stop_price
        distance_pct = risk_per_share / close * 100

    if permission.get("mode") == "risk_control":
        basis = "原交易计划止损/趋势破坏位"

    return {
        "price": _round_price(stop_price),
        "basis": basis,
        "distance_pct": None if distance_pct is None else round(distance_pct, 2),
        "risk_per_share": None if risk_per_share is None else round(risk_per_share, 3),
        "too_wide": bool(distance_pct is not None and distance_pct > MAX_STOP_DISTANCE_PCT),
    }


def _entry_plan(df_display, latest, permission):
    close = _as_float(latest.get("close"))
    entry_type = str(latest.get("composite_entry_type") or "").strip()
    signal_reason = str(latest.get("composite_entry_reason") or "").strip()
    recent_high = _recent_high(df_display)
    recent_low = _recent_low(df_display)

    if permission.get("can_open"):
        return {
            "state": "triggered",
            "label": _entry_type_label(entry_type),
            "trigger_price": _round_price(close),
            "signal_date": _format_date(latest.get("date")),
            "signal_type": entry_type or "composite",
            "detail": signal_reason or "综合结构已经触发，进入止损和仓位校验。",
        }

    if permission.get("mode") in {"wait_trigger", "structure_watch"}:
        return {
            "state": "waiting",
            "label": "等待触发",
            "trigger_price": _round_price(recent_high),
            "signal_date": "",
            "signal_type": "",
            "detail": (
                "观察最近高点是否被有效突破，或回踩不破 "
                + (str(_round_price(recent_low)) if recent_low is not None else "关键支撑")
                + " 后再确认。"
            ),
        }

    return {
        "state": "blocked",
        "label": "禁止新开",
        "trigger_price": None,
        "signal_date": "",
        "signal_type": "",
        "detail": "当前没有可执行入场触发。",
    }


def _targets(close, stop):
    stop_price = stop.get("price")
    if close is None or stop_price is None or stop_price >= close:
        return {
            "r2": None,
            "r3": None,
            "note": "先确定有效止损位，再计算 R 倍数；这不是价格预测。",
        }
    risk = close - stop_price
    return {
        "r2": _round_price(close + risk * 2),
        "r3": _round_price(close + risk * 3),
        "note": "2R/3R 只是风险收益比刻度，不是目标价承诺。",
    }


def _context_float(context, key):
    if not isinstance(context, dict):
        return None
    return _as_float(context.get(key))


def _position_plan(close, stop, context):
    risk_per_share = stop.get("risk_per_share")
    account_size = _context_float(context, "account_size")
    risk_pct = _context_float(context, "risk_pct")
    risk_budget_amount = _context_float(context, "risk_budget_amount")
    max_capital_pct = _context_float(context, "max_capital_pct")
    missing_inputs = []

    if account_size is None:
        missing_inputs.append("account_size")
    if risk_budget_amount is None:
        if risk_pct is None:
            risk_pct = DEFAULT_RISK_PCT
        if account_size is not None:
            risk_budget_amount = account_size * risk_pct / 100
        else:
            missing_inputs.append("risk_budget_amount")
    if max_capital_pct is None:
        max_capital_pct = DEFAULT_MAX_CAPITAL_PCT

    plan = {
        "risk_per_share": risk_per_share,
        "formula": "账户余额 × 单笔风险比例 / 每股风险",
        "account_size": None if account_size is None else round(account_size, 2),
        "risk_pct": None if risk_pct is None else round(risk_pct, 2),
        "risk_budget_amount": None if risk_budget_amount is None else round(risk_budget_amount, 2),
        "max_capital_pct": round(max_capital_pct, 2),
        "max_capital_amount": None if account_size is None else round(account_size * max_capital_pct / 100, 2),
        "lot_size": BOARD_LOT_SIZE,
        "raw_shares": None,
        "shares_by_risk": None,
        "shares_by_capital": None,
        "suggested_shares": None,
        "suggested_lots": None,
        "estimated_capital": None,
        "estimated_risk_amount": None,
        "capped_by": None,
        "missing_inputs": missing_inputs,
        "rules": [
            "单笔风险先固定金额，再反推股数",
            "首笔风险预算默认 3%，账户约束默认最多动用 30% 资金",
            "每一笔加仓单独管理止损",
        ],
    }
    if close is None or risk_per_share is None or risk_per_share <= 0:
        return plan
    if risk_budget_amount is None:
        return plan

    raw_shares = risk_budget_amount / risk_per_share
    shares_by_risk = int(raw_shares // BOARD_LOT_SIZE) * BOARD_LOT_SIZE
    shares_by_capital = None
    capped_by = None
    if account_size is not None and max_capital_pct is not None:
        max_capital_amount = account_size * max_capital_pct / 100
        shares_by_capital = int((max_capital_amount / close) // BOARD_LOT_SIZE) * BOARD_LOT_SIZE
        if shares_by_capital < shares_by_risk:
            capped_by = "max_capital_pct"
    suggested_shares = shares_by_risk
    if shares_by_capital is not None:
        suggested_shares = min(shares_by_risk, shares_by_capital)
    suggested_shares = max(0, suggested_shares)

    plan.update({
        "raw_shares": round(raw_shares, 2),
        "shares_by_risk": shares_by_risk,
        "shares_by_capital": shares_by_capital,
        "suggested_shares": suggested_shares,
        "suggested_lots": int(suggested_shares / BOARD_LOT_SIZE),
        "estimated_capital": round(suggested_shares * close, 2),
        "estimated_risk_amount": round(suggested_shares * risk_per_share, 2),
        "capped_by": capped_by,
    })
    return plan


def _risk_reward_plan(close, stop, context, targets):
    risk_per_share = stop.get("risk_per_share")
    target_price = _context_float(context, "target_price")
    if target_price is None:
        target_price = _context_float(context, "expected_target_price")
    reward = None
    ratio = None
    status = "pending"
    label = "目标待确认"
    if close is not None and risk_per_share is not None and risk_per_share > 0 and target_price is not None:
        reward = target_price - close
        ratio = reward / risk_per_share
        if ratio >= IDEAL_RISK_REWARD:
            status = "ideal"
            label = "达到 3R"
        elif ratio >= MIN_RISK_REWARD:
            status = "pass"
            label = "达到 2R"
        else:
            status = "fail"
            label = "收益风险比不足"
    return {
        "min_ratio": MIN_RISK_REWARD,
        "ideal_ratio": IDEAL_RISK_REWARD,
        "target_price": _round_price(target_price),
        "reward_per_share": None if reward is None else round(reward, 3),
        "ratio": None if ratio is None else round(ratio, 2),
        "status": status,
        "label": label,
        "r2_price": targets.get("r2"),
        "r3_price": targets.get("r3"),
        "note": "明确目标价后，低于 2R 不进入执行；3R 为更优先计划。",
    }


def _ma20_deviation_pct(latest):
    close = _as_float(latest.get("close"))
    ma20 = _as_float(latest.get("ma20"))
    if close is None or not ma20:
        return None
    return (close / ma20 - 1) * 100


def _execution_constraints(latest, entry):
    constraints = []
    if entry.get("signal_type") != "breakout":
        return constraints

    return_pct = _as_float(latest.get("return_pct"))
    ma20_deviation = _ma20_deviation_pct(latest)
    risk_heat_score = _as_int(latest.get("composite_risk_heat_score"))
    volume_ratio = _as_float(latest.get("volume_ratio"))

    constraints.append({
        "key": "next_open_chase",
        "label": "次日高开禁追",
        "severity": "warning",
        "detail": "若次日开盘高于信号日收盘 1% 以上，不按开盘价追入，等待回踩或盘中确认。",
    })
    if return_pct is not None and return_pct >= 6:
        constraints.append({
            "key": "breakout_day_extended",
            "label": "突破日涨幅过大",
            "severity": "warning",
            "detail": f"突破日涨幅 {return_pct:.2f}%，历史分桶显示次日开盘口径偏弱。",
        })
    if ma20_deviation is not None and ma20_deviation >= 10:
        constraints.append({
            "key": "ma20_extended",
            "label": "距离 MA20 过远",
            "severity": "warning",
            "detail": f"当前距 MA20 {ma20_deviation:.2f}%，追涨回撤风险升高。",
        })
    if risk_heat_score is not None and risk_heat_score >= 3:
        constraints.append({
            "key": "heat_score_high",
            "label": "过热分偏高",
            "severity": "warning",
            "detail": f"过热分 {risk_heat_score}，C突需要降权或等待回踩确认。",
        })
    if volume_ratio is not None and (volume_ratio < 1.5 or volume_ratio >= 2.5):
        constraints.append({
            "key": "volume_ratio_outside_preferred",
            "label": "量比不在健康区间",
            "severity": "info",
            "detail": f"当前量比 {volume_ratio:.2f}，历史分桶中 1.5-2.5 更稳。",
        })
    return constraints


def _status(permission, stop):
    if permission.get("mode") == "risk_control":
        return "risk_control", "风险处理"
    if stop.get("too_wide"):
        return "blocked", "止损过远"
    if permission.get("can_open"):
        return "ready", "计划可校验"
    if permission.get("mode") in {"wait_trigger", "structure_watch"}:
        return "waiting", "等待触发"
    return "blocked", "不可执行"


def build_trade_plan(df_display, context=None):
    """Build the first stable trade-plan payload for the single-stock page."""
    permission = build_stock_trade_permission(df_display, context=context)
    structures = build_technical_structures(df_display)
    if df_display is None or df_display.empty:
        return {
            "version": 1,
            "status": "blocked",
            "status_label": "无数据",
            "title": "无法生成交易计划",
            "detail": "没有足够行情数据，先补数据。",
            "permission": permission,
            "technical_structures": structures,
            "entry": {},
            "stop": {},
            "position": {},
            "targets": {},
            "forbidden_reasons": permission.get("forbidden_reasons", []),
            "required_confirmations": permission.get("required_confirmations", []),
            "invalidation_conditions": [],
            "protection_rules": [],
            "next_actions": ["补齐行情数据"],
        }

    latest = df_display.iloc[-1]
    close = _as_float(latest.get("close"))
    stop = _stop_plan(df_display, latest, permission)
    entry = _entry_plan(df_display, latest, permission)
    targets = _targets(close, stop)
    position = _position_plan(close, stop, context or {})
    risk_reward = _risk_reward_plan(close, stop, context or {}, targets)
    execution_constraints = _execution_constraints(latest, entry)
    status, status_label = _status(permission, stop)
    forbidden_reasons = list(permission.get("forbidden_reasons", []))
    required_confirmations = list(permission.get("required_confirmations", []))
    if stop.get("too_wide"):
        forbidden_reasons.append(f"止损距离超过 {MAX_STOP_DISTANCE_PCT:.0f}%")
    if stop.get("price") is None and permission.get("can_open"):
        forbidden_reasons.append("缺少有效止损位")
        status = "blocked"
        status_label = "缺止损位"
    if risk_reward["status"] == "fail":
        forbidden_reasons.append(f"收益风险比低于 {MIN_RISK_REWARD:.0f}:1")
        status = "blocked"
        status_label = "收益风险比不足"
    elif risk_reward["status"] == "pending":
        required_confirmations.append("确认至少 2R 的目标空间")

    williams_clock = structures.get("williams_clock", {})
    plan_type = "observe"
    plan_type_label = "结构观察"
    if status == "risk_control":
        plan_type = "risk_control"
        plan_type_label = "风险处理"
    elif entry.get("state") == "triggered":
        plan_type = entry.get("signal_type") or "triggered"
        plan_type_label = entry.get("label") or "综合触发"
    elif williams_clock.get("state") in {"countdown", "compression_watch", "expanding"}:
        plan_type = "williams_clock_watch"
        plan_type_label = "威廉时钟观察"

    if status == "ready":
        title = "先算止损和仓位，再决定是否执行"
        detail = "单股触发已经出现，但仍要通过止损距离、仓位风险和触发质量校验。"
    elif status == "waiting":
        title = "只观察，不提前重仓"
        detail = entry.get("detail") or "结构未触发，等待可证伪的位置。"
    elif status == "risk_control":
        title = "先处理风险，不新增暴露"
        detail = permission.get("risk_action") or "风险已经压过机会，先按原计划退出或保护利润。"
    else:
        title = "当前不可执行"
        detail = "禁止原因需要先解除，再谈入场。"

    risk_per_share = stop.get("risk_per_share")
    return {
        "version": 1,
        "latest_date": _format_date(latest.get("date")),
        "latest_price": _round_price(close),
        "status": status,
        "status_label": status_label,
        "title": title,
        "detail": detail,
        "plan_type": plan_type,
        "plan_type_label": plan_type_label,
        "permission": permission,
        "technical_structures": structures,
        "entry": entry,
        "stop": stop,
        "position": position,
        "targets": targets,
        "risk_reward": risk_reward,
        "execution_constraints": execution_constraints,
        "forbidden_reasons": forbidden_reasons,
        "required_confirmations": required_confirmations,
        "invalidation_conditions": [
            "入场理由不存在或触发后没有浮盈安全垫",
            "跌破计划止损位",
            "风险分升高并出现趋势破坏",
            "行业/概念宽度收缩或板块结构转弱",
        ],
        "protection_rules": [
            "有浮盈后把亏损止损上移为利润保护",
            "卖飞不是错误，回避风险优先于吃完整段",
            "错了不摊低成本，不复仇交易",
        ],
        "next_actions": [
            permission.get("action") or "等待结构确认",
            "检查止损距离和风险预算",
            "核对行业/概念结构和标签证据",
        ],
    }
