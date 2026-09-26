"""Shared V2 analysis context for single-stock and scan flows."""

from stock_analyzer.c_signal_v2 import build_c_signal_v2_state, build_c_signal_v2_state_components
from stock_analyzer.events import build_v2_signal_events, build_v2_signal_events_cached
from stock_analyzer.serializers import latest_score_summary
from stock_analyzer.trade_plan import build_trade_plan


def build_v2_trade_context(base_context=None, components=None):
    """Return the context shape expected by permission and trade-plan builders."""
    trade_context = dict(base_context or {})
    components = components if isinstance(components, dict) else {}
    facts = components.get("facts") if isinstance(components.get("facts"), dict) else None
    structures = components.get("structures") if isinstance(components.get("structures"), dict) else None
    if facts is not None:
        trade_context.setdefault("c_signal_v2_facts", facts)
    if structures is not None:
        trade_context.setdefault("technical_structures", structures)
    return trade_context


def build_v2_analysis_context(
    df_display,
    *,
    context=None,
    event_key=None,
    event_lookback=60,
    include_events=True,
    include_state=True,
    include_trade_plan=False,
    events_cache_scope="",
):
    """Build reusable V2 facts/state/events/plan context for one analyzed frame."""
    components = build_c_signal_v2_state_components(df_display, context=context) or {}
    facts = components.get("facts") if isinstance(components.get("facts"), dict) else {}
    structures = components.get("structures") if isinstance(components.get("structures"), dict) else {}
    trade_context = build_v2_trade_context(context, components)

    events = []
    if include_events:
        known_facts_by_idx = {len(df_display) - 1: facts} if facts and df_display is not None and not getattr(df_display, "empty", True) else None
        events = build_v2_signal_events_cached(
            df_display,
            lookback=event_lookback,
            cache_scope=events_cache_scope,
            known_facts_by_idx=known_facts_by_idx,
        )

    state = None
    if include_state:
        state = build_c_signal_v2_state(
            df_display,
            event_key=event_key,
            context=trade_context,
            components=components,
        )

    trade_plan = None
    if include_trade_plan:
        if isinstance(state, dict) and isinstance(state.get("v2_permission_model"), dict):
            trade_context["v2_permission_model"] = state["v2_permission_model"]
        trade_plan = build_trade_plan(df_display, context=trade_context)

    if df_display is None or getattr(df_display, "empty", True):
        score_summary = {"date": "-", "setup": 0, "confirm": 0, "risk": 0, "watch": False}
    else:
        score_summary = latest_score_summary(df_display, facts=facts)

    return {
        "source": "v2_analysis_context_p23a",
        "components": components,
        "facts": facts,
        "structures": structures,
        "williams_clock": components.get("williams_clock") if isinstance(components, dict) else {},
        "trade_context": trade_context,
        "events": events,
        "event_lookback": event_lookback if include_events else None,
        "state": state,
        "trade_plan": trade_plan,
        "score_summary": score_summary,
    }
