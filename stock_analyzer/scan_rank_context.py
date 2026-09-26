"""Projection helpers for materialized cross-sectional candidate ranking."""

from __future__ import annotations

from typing import Any, Mapping


RANK_CONTEXT_SCHEMA_VERSION = 4
RANKING_POLICY_VERSION = "stock-structure-macro-only-v1"


def rank_context_candidates(
    workspace: Mapping[str, Any],
    *,
    strategy_version: str,
) -> list[dict[str, Any]]:
    """Extract one complete contextual score row for each matching candidate."""

    output = []
    for pool, pool_payload in (workspace.get("pools") or {}).items():
        if not isinstance(pool_payload, Mapping):
            continue
        for result in pool_payload.get("results") or []:
            if not isinstance(result, Mapping):
                continue
            result_strategy = str(result.get("snapshot_strategy_version") or "")
            if result_strategy and result_strategy != strategy_version:
                continue
            output.append({
                "pool": str(pool),
                "code": str(result.get("code") or ""),
                "event_date": str(result.get("event_date") or result.get("date") or ""),
                "context_priority_score": result.get("v2_priority_score"),
                "context_priority_group": str(result.get("v2_priority_group") or ""),
                "context_final_score": result.get("final_score"),
                # Schema columns remain nullable for reading old revisions, but
                # the active policy never materializes category market factors.
                "sector_score": None,
                "concept_score": None,
                "market_boost": None,
                "environment_permission": str(
                    result.get("v2_environment_permission") or "unknown"
                ),
                "market_context": {},
            })
    return output


def rank_context_source_fingerprint(
    dependency_fingerprint: Mapping[str, Any],
    *,
    snapshot_day: str,
    strategy_version: str,
    start_key: str,
    context_scope: str = "snapshot",
) -> dict[str, Any]:
    return {
        "schema_version": RANK_CONTEXT_SCHEMA_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "snapshot_day": str(snapshot_day),
        "strategy_version": str(strategy_version),
        "start_key": str(start_key),
        "context_scope": str(context_scope),
        "workspace_profile": {
            "include_replay": False,
            "include_market_universe": False,
            "include_market_breadth": False,
            "include_history_comparison": False,
            "ranking_source": RANKING_POLICY_VERSION,
            "candidate_scope": str(context_scope),
        },
        "dependencies": dict(dependency_fingerprint),
    }
