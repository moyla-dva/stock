"""Canonical reason tags shared by workspace and persistent candidate queries."""

from __future__ import annotations

from typing import Any, Mapping

from stock_analyzer.signal_registry import signal_keys_for_reason, signal_labels_for_reason


CANDIDATE_REASON_TAGS = (
    "plan_ready",
    "plan_blocked",
    "macro_veto",
    "ma60",
    "ma250",
    "rr",
    "chase",
    "heat",
    "wide_stop",
    "c_pullback",
    "c_breakout",
    "c_attack",
    "exit_scale_out",
    "exit_sell",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _state_model(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(result.get("v2_state_model") or result.get("c_signal_v2_state"))


def _permission_model(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_state_model(result).get("v2_permission_model"))


def _plan_gate(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_permission_model(result).get("plan_gate"))


def _exit_gate(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_mapping(_state_model(result).get("facts")).get("exit_gate"))


def candidate_reason_texts(result: Mapping[str, Any]) -> tuple[str, ...]:
    model = _state_model(result)
    permission = _permission_model(result)
    gate = _plan_gate(result)
    texts: list[Any] = [
        result.get("reason"),
        result.get("v2_macro_veto_reason"),
        model.get("reason"),
        model.get("next_action"),
        permission.get("reason"),
        permission.get("next_action"),
        gate.get("target_label"),
        gate.get("target_source"),
    ]
    for container in (result, model, permission, gate):
        for key in (
            "block_reasons",
            "required_confirmations",
            "warnings",
            "v2_environment_block_reasons",
            "v2_environment_warnings",
        ):
            values = container.get(key) or []
            if isinstance(values, str):
                values = [values]
            if isinstance(values, (list, tuple, set)):
                texts.extend(values)
    return tuple(str(text) for text in texts if text)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def candidate_matches_reason(result: Mapping[str, Any], reason: str = "") -> bool:
    reason = str(reason or "").strip()
    if not reason:
        return True
    if reason not in CANDIDATE_REASON_TAGS:
        return False

    model = _state_model(result)
    gate = _plan_gate(result)
    exit_gate = _exit_gate(result)
    signal = str(
        result.get("v2_signal")
        or model.get("signal")
        or result.get("signal_label")
        or result.get("signal")
        or ""
    )
    signal_key = str(result.get("signal_key") or "")
    plan_status = str(
        gate.get("status")
        or model.get("plan_status")
        or result.get("v2_plan_status")
        or ""
    )
    state = str(model.get("state") or result.get("v2_state") or "")
    permission = str(model.get("permission") or result.get("v2_permission") or "")
    marker_role = str(exit_gate.get("marker_role") or exit_gate.get("markerRole") or "")
    text = " ".join(candidate_reason_texts(result))

    if reason == "plan_ready":
        return plan_status == "ready" or result.get("v2_priority_group") == "trade_ready"
    if reason == "plan_blocked":
        return plan_status == "blocked" or state == "trigger_plan_blocked"
    if reason == "macro_veto":
        return state == "macro_veto_blocked" or "宏观否决" in text or (
            "大周期" in text and permission == "forbidden"
        )
    if reason == "ma60":
        return _contains_any(
            text,
            ("MA60未", "MA60 未", "MA60下行", "MA60 下行", "未满足MA60", "未满足 MA60", "未上行"),
        )
    if reason == "ma250":
        return _contains_any(
            text,
            ("MA250下方", "MA250 下方", "低于MA250", "低于 MA250", "未站上MA250", "未站上 MA250", "年线下方", "跌破MA250", "跌破 MA250"),
        )
    if reason == "rr":
        return _contains_any(
            text,
            ("收益风险比低于", "收益风险比不足", "低于 2:1", "低于2:1", "2R不足", "不足2R", "未达2R", "未达到2R"),
        )
    if reason == "chase":
        return "追高" in text or "距 MA20" in text or "攻击日涨幅" in text
    if reason == "heat":
        return "过热" in text
    if reason == "wide_stop":
        return "止损距离超过" in text or "止损过宽" in text

    reason_labels = signal_labels_for_reason(reason)
    reason_keys = signal_keys_for_reason(reason)
    if reason_labels or reason_keys:
        return signal in reason_labels or signal_key in reason_keys
    if reason == "exit_sell":
        return marker_role == "sell"
    if reason == "exit_scale_out":
        return marker_role == "scale_out"
    return False


def candidate_reason_tags(result: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        reason
        for reason in CANDIDATE_REASON_TAGS
        if candidate_matches_reason(result, reason)
    )

