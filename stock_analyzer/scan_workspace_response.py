"""Response shaping for the scan workspace API."""

from stock_analyzer.c_signal_v2 import apply_c_signal_v2_priority
from stock_analyzer.scan_explainer import attach_scan_explanation
from stock_analyzer.scan_snapshot import display_snapshot_day
from stock_analyzer.scan_snapshot_meta import build_snapshot_meta
from stock_analyzer.scan_strategy_health import build_strategy_health
from stock_analyzer.scan_workspace_index import iter_workspace_pool_indexes
from stock_analyzer.scan_workspace_history_compare import rank_value, v2_priority_value
from stock_analyzer.versioning import build_strategy_meta


def _remove_legacy_market_context(result):
    """Prevent persisted pre-policy enrichment fields from affecting new reads."""
    for key in tuple(result):
        if key == "market_boost" or key.startswith(("sector_", "concept_")):
            result.pop(key, None)
    result["final_score"] = result.get("rank_score")


def sort_scan_results(results):
    return sorted(
        results,
        key=lambda item: (
            1 if item.get("strategy_status") == "current" else 0,
            v2_priority_value(item),
            rank_value(item),
            str(item.get("event_date") or item.get("date") or ""),
            str(item.get("code") or ""),
        ),
        reverse=True,
    )


def trim_workspace_pools(pools, max_items):
    """Sort pools, preserve full counts, and cap the displayed result payload."""
    for pool in pools.values():
        for result in pool.get("results", []):
            _remove_legacy_market_context(result)
    apply_c_signal_v2_priority(pools)
    for pool in pools.values():
        for result in pool["results"]:
            attach_scan_explanation(result)
        results = sort_scan_results(pool["results"])
        pool["count"] = len(results)
        pool["max_items"] = max_items
        pool["results"] = results[:max_items]
        pool["loaded_count"] = len(pool["results"])
        pool["has_more"] = pool["loaded_count"] < pool["count"]


def trim_workspace_overview(overview, limit=None):
    if not limit:
        return overview
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return overview
    if limit <= 0:
        return overview
    return (overview or [])[:limit]


def _pool_stat_priority(stat, name_key):
    return (
        int(stat.get("count") or stat.get("candidate_count") or 0),
        int(stat.get("signal_count") or stat.get("candidate_signal_count") or 0),
        str(stat.get("latest_event") or ""),
        str(stat.get(name_key) or ""),
    )


def trim_workspace_pool_stats(pools, limit=None):
    if not limit:
        return
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return
    if limit <= 0:
        return
    for pool in (pools or {}).values():
        if isinstance(pool.get("sector_stats"), list):
            pool["sector_stats"] = sorted(
                pool["sector_stats"],
                key=lambda stat: _pool_stat_priority(stat, "sector"),
                reverse=True,
            )[:limit]
        if isinstance(pool.get("concept_stats"), list):
            pool["concept_stats"] = sorted(
                pool["concept_stats"],
                key=lambda stat: _pool_stat_priority(stat, "concept"),
                reverse=True,
            )[:limit]


COMPACT_RESULT_KEYS = {
    "avg_ret",
    "bear_power",
    "bear_power_dominant",
    "bull_bear_balance",
    "bull_power",
    "bull_power_dominant",
    "candidate_confirmation_price",
    "candidate_display_label",
    "candidate_invalidation_price",
    "candidate_missing_confirmations",
    "candidate_substate",
    "candidate_substate_label",
    "candidate_trigger_plan",
    "code",
    "concepts",
    "confirm_score",
    "custom_z",
    "data_date",
    "date",
    "event_date",
    "explanation",
    "final_score",
    "history_delta",
    "momentum_efficiency",
    "name",
    "pool_stage_detail",
    "pool_stage_label",
    "pool_stage_tone",
    "price",
    "prior_breakout",
    "prior_high_10",
    "profile_relation_count",
    "profile_relation_group_summary",
    "profile_relation_summary",
    "rank_score",
    "reason",
    "requires_stop_loss",
    "requires_trade_plan",
    "return_pct",
    "risk_break_score",
    "risk_heat_score",
    "risk_score",
    "scan_admission_label",
    "scan_admission_source",
    "scan_title",
    "scan_type",
    "score_confidence",
    "score_confidence_label",
    "score_confidence_level",
    "sector",
    "setup_score",
    "signal",
    "signal_category",
    "signal_key",
    "signal_label",
    "signal_name",
    "snapshot_day",
    "snapshot_strategy_label",
    "snapshot_strategy_version",
    "strategy_source_label",
    "strategy_status",
    "trade_intent",
    "trade_intent_label",
    "v2_concept_permission",
    "v2_concept_permission_label",
    "v2_concept_permission_reason",
    "v2_detail",
    "v2_effective_permission",
    "v2_environment_block_reasons",
    "v2_environment_effect",
    "v2_environment_label",
    "v2_environment_permission",
    "v2_environment_reasons",
    "v2_environment_tone",
    "v2_environment_warnings",
    "v2_macro_veto_block_reasons",
    "v2_macro_veto_label",
    "v2_macro_veto_permission",
    "v2_macro_veto_reason",
    "v2_macro_veto_tone",
    "v2_macro_veto_warnings",
    "v2_market_permission",
    "v2_permission",
    "v2_plan_scope",
    "v2_plan_status",
    "v2_plan_status_label",
    "v2_priority_detail",
    "v2_priority_group",
    "v2_priority_label",
    "v2_priority_score",
    "v2_priority_source",
    "v2_priority_tone",
    "v2_queue",
    "v2_queue_label",
    "v2_queue_priority",
    "v2_role",
    "v2_role_label",
    "v2_sector_permission",
    "v2_sector_permission_label",
    "v2_sector_permission_reason",
    "v2_signal",
    "v2_signal_name",
    "v2_state",
    "v2_state_label",
    "v2_tone",
    "view_model",
    "volume_ratio",
    "williams_r",
    "williams_r_center_side",
    "williams_r_cross_bear",
    "williams_r_cross_bull",
    "win_rate",
}


COMPACT_V2_MODEL_KEYS = {
    "candidate_confirmation_price",
    "candidate_display_label",
    "candidate_invalidation_price",
    "candidate_missing_confirmations",
    "candidate_substate",
    "candidate_substate_label",
    "candidate_trigger_plan",
    "detail",
    "event_mapping",
    "latest_date",
    "next_action",
    "permission",
    "permission_context",
    "permission_label",
    "plan_scope",
    "reason",
    "requires_stop_loss",
    "requires_trade_plan",
    "role",
    "role_label",
    "scores",
    "signal",
    "signal_name",
    "source",
    "state",
    "state_label",
    "tone",
    "trade_intent",
    "trade_intent_label",
    "v2_state_schema_version",
    "version",
}


COMPACT_PERMISSION_MODEL_KEYS = {
    "block_reasons",
    "can_open",
    "mode",
    "mode_label",
    "next_action",
    "permission",
    "permission_label",
    "plan_gate",
    "plan_status",
    "plan_status_label",
    "reason",
    "required_confirmations",
    "schema_version",
    "signal_key",
    "source",
    "state",
    "state_label",
}


def _copy_keys(source, keys):
    if not isinstance(source, dict):
        return {}
    return {key: source[key] for key in keys if key in source}


def _compact_structure_facts(structure):
    structure = structure if isinstance(structure, dict) else {}
    compact = _copy_keys(structure, {"available", "candidate", "summary", "source", "version"})
    rectangle_keys = {
        "available",
        "family",
        "lookback",
        "upper",
        "lower",
        "mid",
        "width_pct",
        "inside",
        "breaks_previous_upper",
        "breaks_previous_lower",
        "latest_position",
        "quality_score",
        "summary",
    }
    for key in ("rectangle", "active_rectangle", "macro_rectangle"):
        value = structure.get(key)
        if isinstance(value, dict):
            compact[key] = _copy_keys(value, rectangle_keys)
    bear_trap = structure.get("bear_trap_recovery")
    if isinstance(bear_trap, dict):
        compact["bear_trap_recovery"] = _copy_keys(bear_trap, {
            "available",
            "breakout_after_recovery",
            "macro_breakout_after_recovery",
            "recovered",
            "stop_price",
            "summary",
        })
    fractals = structure.get("fractals")
    if isinstance(fractals, dict):
        compact["fractals"] = _copy_keys(fractals, {
            "available",
            "confirmation_lag",
            "containment_count",
            "double_bottom_higher_low",
            "latest_bottom",
            "latest_top",
            "merge_count",
            "normalization_used",
            "normalized_count",
            "original_count",
            "summary",
            "top_lower_high",
        })
    normalized_bars = structure.get("normalized_bars")
    if isinstance(normalized_bars, dict):
        compact["normalized_bars"] = _copy_keys(normalized_bars, {
            "available",
            "containment_count",
            "dropped_count",
            "lookback",
            "merge_count",
            "normalized_count",
            "original_count",
            "summary",
        })
    return compact


def _compact_trigger_facts(trigger):
    trigger = trigger if isinstance(trigger, dict) else {}
    return _copy_keys(trigger, {"attack_day", "ignition", "summary", "source", "version"})


def compact_v2_facts(facts):
    facts = facts if isinstance(facts, dict) else {}
    compact = _copy_keys(facts, {"latest_date", "scores", "source", "version", "v2_scores"})
    for key in ("target_structure", "macro_tide", "exit_gate"):
        value = facts.get(key)
        if isinstance(value, dict):
            if key == "target_structure":
                compact[key] = _copy_keys(value, {
                    "available",
                    "pullback_target",
                    "reference_price",
                    "selected_breakout_target",
                    "summary",
                    "target_selection_reason",
                })
            elif key == "exit_gate":
                compact[key] = _copy_keys(value, {
                    "action",
                    "available",
                    "marker_level",
                    "marker_reason",
                    "marker_role",
                    "position_lifecycle",
                    "summary",
                })
            else:
                compact[key] = value
    return compact


def compact_v2_state_model(model):
    model = model if isinstance(model, dict) else {}
    compact = _copy_keys(model, COMPACT_V2_MODEL_KEYS)
    permission_model = model.get("v2_permission_model")
    if isinstance(permission_model, dict):
        compact["v2_permission_model"] = _copy_keys(permission_model, COMPACT_PERMISSION_MODEL_KEYS)
    facts = model.get("facts")
    if isinstance(facts, dict):
        compact["facts"] = compact_v2_facts(facts)
    return compact


def compact_explanation(explanation):
    explanation = explanation if isinstance(explanation, dict) else {}
    compact = _copy_keys(explanation, {"card_summary", "headline", "summary", "version"})
    if isinstance(explanation.get("drivers"), list):
        compact["drivers"] = explanation["drivers"][:1]
    if isinstance(explanation.get("cautions"), list):
        compact["cautions"] = explanation["cautions"][:1]
    if isinstance(explanation.get("score_badges"), list):
        compact["score_badges"] = explanation["score_badges"][:4]
    return compact


def compact_scan_result(result):
    """Return the list/detail contract without heavyweight analysis internals."""
    if not isinstance(result, dict):
        return result
    compact = _copy_keys(result, COMPACT_RESULT_KEYS)
    compact.pop("explanation", None)
    compact.pop("view_model", None)
    if isinstance(result.get("v2_state_model"), dict):
        compact["v2_state_model"] = compact_v2_state_model(result["v2_state_model"])
    if isinstance(result.get("explanation"), dict):
        compact["explanation"] = compact_explanation(result["explanation"])
    compact["_compact"] = True
    return compact


def compact_workspace_response(workspace, active_scan_type=None):
    if not isinstance(workspace, dict):
        return workspace
    compact = dict(workspace)
    pools = {}
    for index in iter_workspace_pool_indexes(workspace):
        next_pool = dict(index.pool)
        if active_scan_type and index.scan_type != active_scan_type:
            next_pool["results"] = []
            next_pool["loaded_count"] = 0
            next_pool["has_more"] = bool(next_pool.get("count"))
        else:
            next_pool["results"] = [compact_scan_result(result) for result in index.results]
        pools[index.scan_type] = next_pool
    compact["pools"] = pools
    compact["compact"] = True
    return compact


def build_workspace_response(
    loaded,
    structure,
    start_date=None,
    max_items=120,
    overview_limit=None,
    pool_stats_limit=None,
):
    target_snapshot_day = loaded["target_snapshot_day"]
    latest_snapshots = loaded["latest_snapshots"]
    latest_snapshot_day = loaded["latest_snapshot_day"]
    latest_data_date = loaded["latest_data_date"]
    pools = loaded["pools"]
    trim_workspace_pool_stats(pools, pool_stats_limit)

    active_stale_snapshot_count = loaded["stale_snapshot_count"] if not latest_snapshots else 0
    snapshot_meta = build_snapshot_meta(
        start_date=start_date,
        snapshot_count=loaded["snapshot_count"],
        valid_snapshot_count=loaded["valid_snapshot_count"],
        stale_snapshot_count=active_stale_snapshot_count,
        stored_stale_snapshot_count=loaded["stale_snapshot_count"],
        current_strategy_snapshot_count=loaded["active_current_strategy_snapshot_count"],
        legacy_snapshot_count=loaded["active_legacy_snapshot_count"],
        stored_current_strategy_snapshot_count=loaded["current_strategy_snapshot_count"],
        stored_legacy_snapshot_count=loaded["legacy_snapshot_count"],
        scanned_count=len(latest_snapshots),
        latest_snapshot_day=latest_snapshot_day,
        latest_data_date=latest_data_date,
        history_snapshot_day=target_snapshot_day,
        strategy_version_counts=loaded.get("strategy_version_counts"),
        active_strategy_version_counts=loaded.get("active_strategy_version_counts"),
        strategy_version_labels=loaded.get("strategy_version_labels"),
    )
    strategy_health = build_strategy_health(pools, snapshot_meta)

    return {
        "start_date": start_date or "-",
        "snapshot_count": loaded["snapshot_count"],
        "valid_snapshot_count": loaded["valid_snapshot_count"],
        "stale_snapshot_count": active_stale_snapshot_count,
        "stored_stale_snapshot_count": loaded["stale_snapshot_count"],
        "current_strategy_snapshot_count": loaded["active_current_strategy_snapshot_count"],
        "legacy_snapshot_count": loaded["active_legacy_snapshot_count"],
        "stored_current_strategy_snapshot_count": loaded["current_strategy_snapshot_count"],
        "stored_legacy_snapshot_count": loaded["legacy_snapshot_count"],
        "scanned_count": len(latest_snapshots),
        "latest_snapshot_day": display_snapshot_day(latest_snapshot_day),
        "latest_data_date": latest_data_date,
        "history_mode": bool(target_snapshot_day),
        "history_snapshot_day": target_snapshot_day,
        "history_display_day": display_snapshot_day(target_snapshot_day),
        "snapshot_meta": snapshot_meta,
        "strategy_meta": build_strategy_meta(start_date=start_date),
        "strategy_health": strategy_health,
        "max_items": max_items,
        "concept_graph_status": structure.get("concept_graph_status") or {},
        "sector_overview": trim_workspace_overview(structure["sector_overview"], overview_limit),
        "concept_overview": trim_workspace_overview(structure["concept_overview"], overview_limit),
        "market_structure_meta": structure.get("market_structure_meta") or {},
        "resonance_calibration": structure["resonance_calibration"],
        "replay_calibration": structure["replay_calibration"],
        "pools": pools,
    }
