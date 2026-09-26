"""Shadow-only, weight-free V1 candidate eligibility and evidence projection."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


RANKING_FEATURE_SCHEMA_VERSION = 3
UNKNOWN = "unknown"
READY_PERMISSIONS = {"attack_allowed", "breakout_allowed", "pullback_allowed"}
RISK_STATES = {"risk_control", "risk_triggered", "exit_triggered"}
RESEARCH_STATES = {"research_bottom", "researchable"}
REPAIR_STATES = {"repair_setup", "repair_watch"}
TRIGGER_WAIT_STATES = {
    "trigger_observed",
    "trigger_plan_waiting",
    "trigger_plan_blocked",
    "entry_unconfirmed",
    "entry_breakout",
    "entry_pullback",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _date(value: Any) -> str:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def build_calendar_session_index(session_dates: Sequence[str]) -> dict[str, int]:
    """Build one reusable, revision-specific date-to-ordinal index."""
    return {
        normalized: index
        for index, value in enumerate(session_dates)
        if (normalized := _date(value))
    }


def _session_age(
    event_date: str,
    as_of: str,
    session_index: Mapping[str, int] | None,
) -> int | None:
    event = _date(event_date)
    cutoff = _date(as_of)
    if not event or not cutoff:
        return None
    if event == cutoff:
        return 0
    if not session_index:
        return None
    if event not in session_index or cutoff not in session_index:
        return None
    age = session_index[cutoff] - session_index[event]
    return age if age >= 0 else None


def _data_quality(
    snapshot: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    expected_session_date: str,
) -> dict[str, Any]:
    data_date = _date(snapshot.get("data_date"))
    expected = _date(expected_session_date)
    bar_state = _text(snapshot.get("bar_state"), default=UNKNOWN).lower()
    data_source = _text(snapshot.get("data_source"), default=UNKNOWN)
    data_revision = _text(snapshot.get("data_revision"), default=UNKNOWN)
    price = _number(result.get("price"))

    if not data_date or not expected:
        status = UNKNOWN
    elif data_date > expected:
        status = "invalid"
    elif bar_state != "closed":
        status = "incomplete" if bar_state in {"preview", "mixed"} else UNKNOWN
    elif data_date < expected:
        status = "stale"
    elif data_source == UNKNOWN or data_revision == UNKNOWN:
        status = UNKNOWN
    elif price is None or price <= 0:
        status = "incomplete"
    else:
        status = "current"

    age_sessions = None
    if data_date == expected:
        age_sessions = 0
    return {
        "status": status,
        "data_date": data_date or None,
        "expected_session_date": expected or None,
        "age_sessions": age_sessions,
        "bar_state": bar_state,
        "data_source": data_source,
        "data_revision": data_revision,
        "calendar_id": _text(snapshot.get("calendar_id"), default=UNKNOWN),
        "calendar_revision": _text(snapshot.get("calendar_revision"), default=UNKNOWN),
        "calendar_evidence_level": _text(
            snapshot.get("calendar_evidence_level"),
            default=UNKNOWN,
        ),
    }


def _classify(pool: str, permission: str, state: str, role: str, plan: str,
              environment: str, data_status: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if data_status == "invalid":
        return "blocked", ["data_date_after_as_of"]

    if permission == "risk_only" or role == "risk" or state in RISK_STATES:
        return "risk_control", ["risk_permission"]

    if permission == "forbidden" or plan == "blocked":
        return "blocked", ["permission_forbidden" if permission == "forbidden" else "plan_blocked"]

    if pool == "opportunity":
        if permission in READY_PERMISSIONS:
            if plan != "ready":
                reasons.append("plan_not_ready")
            if environment == "forbidden":
                return "blocked", ["environment_forbidden"]
            if environment != "allowed":
                reasons.append("environment_" + (environment or UNKNOWN))
            if data_status != "current":
                reasons.append("data_" + (data_status or UNKNOWN))
            if not reasons:
                return "ready", []
            return "waiting", reasons
        if permission == "structure_only":
            return "observe", ["trigger_not_observed"]
        if permission == "watch_only":
            if plan == "waiting" or state in TRIGGER_WAIT_STATES:
                return "waiting", ["confirmation_or_plan_waiting"]
            if state in REPAIR_STATES:
                return "observe", ["repair_observation"]
            if state in RESEARCH_STATES:
                return "observe", ["research_observation"]
            return "observe", ["watch_only"]
        return "unknown", ["permission_unknown"]

    if pool == "risk":
        if permission in {"watch_only", "structure_only"} or role == "watch":
            return "observe", ["risk_pool_observation"]
        return "unknown", ["risk_state_unknown"]

    if pool == "bottom_div":
        if permission in READY_PERMISSIONS:
            if plan == "ready" and environment == "allowed" and data_status == "current":
                return "entry_ready", []
            if environment == "forbidden":
                return "blocked", ["environment_forbidden"]
            if plan != "ready":
                reasons.append("plan_not_ready")
            if environment != "allowed":
                reasons.append("environment_" + (environment or UNKNOWN))
            if data_status != "current":
                reasons.append("data_" + (data_status or UNKNOWN))
            return "waiting", reasons
        if state in REPAIR_STATES:
            return "repair_watch", ["repair_observation"]
        if state in RESEARCH_STATES:
            return "research_watch", ["research_observation"]
        if permission == "structure_only" or role == "candidate":
            return "structure_watch", ["structure_confirmation_waiting"]
        if permission == "watch_only" or role == "watch":
            return "structure_watch", ["watch_only"]
        return "unknown", ["permission_unknown"]

    return "unknown", ["pool_unknown"]


def build_candidate_ranking_features_v1(
    snapshot: Mapping[str, Any],
    pool: str,
    result: Mapping[str, Any],
    *,
    expected_session_date: str = "",
    calendar_session_index: Mapping[str, int] | None = None,
    market_context: Mapping[str, Any] | None = None,
    environment_permission: str | None = None,
) -> dict[str, Any]:
    """Project one persisted candidate into unweighted V1 shadow features.

    This deliberately does not assign a ranking score or alter any production
    ordering. ``calendar_session_index`` must use the revisioned session sequence
    appropriate to this snapshot; absent dates yield unknown ages.
    """
    snapshot = _mapping(snapshot)
    result = _mapping(result)
    pool = str(pool or "").strip()
    state_model = _mapping(result.get("v2_state_model"))
    permission_model = _mapping(state_model.get("v2_permission_model"))
    facts = _mapping(state_model.get("facts"))
    structure = _mapping(facts.get("structure"))
    setup = _mapping(facts.get("setup"))
    trigger = _mapping(facts.get("trigger"))
    momentum = _mapping(facts.get("momentum"))
    risk = _mapping(facts.get("risk"))
    fractals = _mapping(structure.get("fractals"))
    latest_bottom = _mapping(fractals.get("latest_bottom"))

    # active_rectangle is the canonical short-term rectangle. Older snapshots
    # may only carry rectangle; never add both aliases together.
    if isinstance(structure.get("active_rectangle"), Mapping):
        rectangle = structure.get("active_rectangle")
        rectangle_source = "structure.active_rectangle"
    else:
        rectangle = structure.get("rectangle")
        rectangle_source = "structure.rectangle_legacy_fallback"
    rectangle = _mapping(rectangle)
    bear_trap = _mapping(structure.get("bear_trap_recovery"))
    ignition = _mapping(trigger.get("ignition"))
    exit_gate = _mapping(facts.get("exit_gate"))

    state = _text(state_model.get("state"), result.get("v2_state"))
    role = _text(state_model.get("role"), result.get("v2_role"))
    permission = _text(result.get("v2_permission"), state_model.get("permission"))
    plan_status = _text(
        result.get("v2_plan_status"),
        permission_model.get("plan_status"),
    )
    environment = _text(
        environment_permission,
        result.get("v2_environment_permission"),
        default=UNKNOWN,
    )
    if environment not in {"allowed", "watch", "forbidden", "unknown"}:
        environment = UNKNOWN

    data = _data_quality(
        snapshot,
        result,
        expected_session_date=expected_session_date,
    )
    tier, reasons = _classify(
        pool,
        permission,
        state,
        role,
        plan_status,
        environment,
        data["status"],
    )
    if data["status"] not in {"current", "invalid"}:
        data_reason = "data_" + data["status"]
        if data_reason not in reasons:
            reasons.append(data_reason)

    attack = _flag(trigger.get("attack_day"))
    ignition_triggered = _flag(ignition.get("triggered"))
    breakout = _flag(setup.get("breakout_trigger"))
    pullback = _flag(setup.get("pullback_trigger"))
    bear_trap_breakout = _flag(bear_trap.get("breakout_after_recovery"))
    entry_families = []
    if attack or ignition_triggered:
        entry_families.append("attack")
    if breakout or bear_trap_breakout:
        entry_families.append("breakout")
    if pullback:
        entry_families.append("pullback")

    context = _mapping(market_context)
    market_boost = _number(context.get("market_adjustment"))
    if market_boost is None:
        market_boost = _number(result.get("market_boost"))
    market_status = _text(context.get("status"))
    if market_status not in {"current", "stale", "future", "missing", "unknown"}:
        market_status = "unknown" if market_boost is not None else "missing"
    market_as_of = _date(context.get("as_of"))
    market_revision = _text(context.get("revision"), default=UNKNOWN)
    if market_status == "current" and (not market_as_of or market_revision == UNKNOWN):
        market_status = "unknown"

    pivot_date = _date(latest_bottom.get("analysis_date"))
    as_of = _date(expected_session_date or snapshot.get("data_date") or facts.get("latest_date"))
    v2_scores = _mapping(facts.get("v2_scores"))

    return {
        "schema_version": RANKING_FEATURE_SCHEMA_VERSION,
        "ranking_version": "candidate-ranking-v1-shadow",
        "pool": pool,
        "code": _text(result.get("code"), snapshot.get("code")),
        "as_of": as_of or None,
        "eligibility_tier": tier,
        "eligibility_reasons": reasons,
        "permission": permission or UNKNOWN,
        "plan_status": plan_status or UNKNOWN,
        "environment_permission": environment,
        "data_quality": data,
        "evidence": {
            "pivot_structure": {
                "latest_bottom_present": bool(latest_bottom),
                "double_bottom_higher_low": _flag(fractals.get("double_bottom_higher_low")),
                "known_on": pivot_date or None,
                "age_sessions": _session_age(pivot_date, as_of, calendar_session_index),
            },
            "active_range": {
                "source": rectangle_source,
                "available": _flag(rectangle.get("available")),
                "quality_score": _number(rectangle.get("quality_score")),
                "width_pct": _number(rectangle.get("width_pct")),
                "latest_position": _text(rectangle.get("latest_position")) or None,
            },
            "setup_families": [
                name
                for name, present in (
                    ("breakout", _flag(setup.get("breakout_setup"))),
                    ("pullback", _flag(setup.get("pullback_setup"))),
                    ("bear_trap_recovery", _flag(bear_trap.get("recovered"))),
                )
                if present
            ],
            "entry_trigger_families": entry_families,
            "entry_trigger_flags": {
                "attack_day": attack,
                "ignition": ignition_triggered,
                "breakout": breakout,
                "pullback": pullback,
                "bear_trap_breakout": bear_trap_breakout,
            },
            "momentum_confirmation": {
                "power_flip": _flag(momentum.get("power_flip")),
                "williams_r_power_cross": _flag(momentum.get("williams_r_power_cross")),
                "williams_r_cross_bull": _flag(
                    _mapping(facts.get("trend")).get("williams_r_cross_bull")
                ),
            },
            "volume_confirmation": {
                "volume_expand": _flag(trigger.get("volume_expand")),
                "range_expansion": _flag(trigger.get("range_expansion")),
            },
            "risk": {
                "break_score": _number(risk.get("risk_break_score")),
                "heat_score": _number(risk.get("risk_heat_score")),
                "has_exit": _flag(risk.get("has_exit")) or _text(exit_gate.get("action")) == "sell",
                "break_reasons": list(risk.get("break_reasons") or []),
                "heat_reasons": list(risk.get("heat_reasons") or []),
            },
        },
        "market_context": {
            "status": market_status,
            "adjustment": market_boost,
            "as_of": market_as_of or None,
            "revision": market_revision,
            "components": _mapping(context.get("components")),
        },
        # Retained for comparison only; the shadow layer never scores these.
        "legacy_scores": {
            "setup": _number(result.get("setup_score")),
            "confirm": _number(result.get("confirm_score")),
            "risk": _number(result.get("risk_score")),
            "structure_score": _number(v2_scores.get("structure_score")),
            "trigger_quality": _number(v2_scores.get("trigger_quality")),
            "research_score": _number(v2_scores.get("research_score")),
            "execution_risk": _number(v2_scores.get("execution_risk")),
        },
    }
