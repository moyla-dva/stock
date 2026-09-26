"""Build and publish contextual candidate ranking from persisted snapshots."""

from __future__ import annotations

import time
from typing import Any

from stock_analyzer.scan_rank_context import (
    rank_context_candidates,
    rank_context_source_fingerprint,
)
from stock_analyzer.scan_snapshot import normalize_snapshot_day
from stock_analyzer.scan_index_store import (
    RANK_CONTEXT_SCOPE_LATEST_FRESH,
    RANK_CONTEXT_SCOPE_SNAPSHOT,
    RANK_CONTEXT_SCOPES,
)
from stock_analyzer.scan_workspace import collect_scan_workspace
from stock_analyzer.scan_workspace_persistent_cache import (
    scan_workspace_dependency_fingerprint,
)


def materialize_workspace_rank_context(
    store,
    *,
    start_date: str,
    strategy_version: str,
    snapshot_day: str | None = None,
    context_scope: str = RANK_CONTEXT_SCOPE_SNAPSHOT,
    logger=None,
) -> dict[str, Any]:
    """Publish one complete cross-sectional ranking overlay for a population scope.

    The overlay remains separate from snapshot-local candidate facts. An existing
    complete revision is reused when all ranking dependencies are unchanged.
    """

    started_at = time.perf_counter()
    start_key = "".join(character for character in str(start_date) if character.isdigit())
    scope = str(context_scope or RANK_CONTEXT_SCOPE_SNAPSHOT).strip().lower()
    if scope not in RANK_CONTEXT_SCOPES:
        raise ValueError(f"unknown contextual rank scope: {scope}")
    requested_day = normalize_snapshot_day(snapshot_day)
    if snapshot_day and not requested_day:
        raise ValueError("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
    if not requested_day:
        requested_day = normalize_snapshot_day(store.status().get("latest_snapshot_day"))
    if not requested_day:
        raise RuntimeError("scan index did not resolve a snapshot day")
    if scope == RANK_CONTEXT_SCOPE_LATEST_FRESH:
        latest_index_day = normalize_snapshot_day(store.status().get("latest_snapshot_day"))
        if requested_day != latest_index_day:
            raise ValueError(
                "latest_fresh rank context requires the latest indexed snapshot day"
            )

    pruned_revision_count = store.prune_stale_rank_contexts()

    dependency_fingerprint = scan_workspace_dependency_fingerprint(
        start_date=start_date,
        snapshot_day=requested_day,
        index_store=store,
    )
    source_fingerprint = rank_context_source_fingerprint(
        dependency_fingerprint,
        snapshot_day=requested_day,
        strategy_version=strategy_version,
        start_key=start_key,
        context_scope=scope,
    )
    current = store.rank_context_status(
        snapshot_day=requested_day,
        strategy_version=strategy_version,
        start_key=start_key,
        context_scope=scope,
    )
    if current.get("available") and current.get("source_fingerprint") == source_fingerprint:
        return {
            "status": "reused",
            "snapshot_day": requested_day,
            "strategy_version": strategy_version,
            "start_key": start_key,
            "context_scope": scope,
            "candidate_count": int(current.get("candidate_count") or 0),
            "pruned_revision_count": pruned_revision_count,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "rank_context": current,
        }

    # All indexed candidates can age out of the live workspace between scans.
    # Publish an empty but complete latest-fresh context instead of requiring a
    # workspace loader that has no valid snapshot from which to infer the day.
    if (
        scope == RANK_CONTEXT_SCOPE_LATEST_FRESH
        and int(current.get("candidate_count") or 0) == 0
    ):
        status = store.materialize_rank_context(
            snapshot_day=requested_day,
            strategy_version=strategy_version,
            start_key=start_key,
            source_fingerprint=source_fingerprint,
            candidates=(),
            context_scope=scope,
        )
        return {
            "status": "materialized",
            "snapshot_day": requested_day,
            "strategy_version": strategy_version,
            "start_key": start_key,
            "context_scope": scope,
            "candidate_count": 0,
            "pruned_revision_count": pruned_revision_count,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "rank_context": status,
        }

    workspace = collect_scan_workspace(
        start_date=start_date,
        max_items=100000,
        snapshot_day=(
            None
            if scope == RANK_CONTEXT_SCOPE_LATEST_FRESH
        else requested_day
        ),
        latest_only=scope == RANK_CONTEXT_SCOPE_LATEST_FRESH,
        include_history_comparison=False,
    )
    resolved_day = normalize_snapshot_day(
        workspace.get("history_snapshot_day")
        or workspace.get("latest_snapshot_day")
    )
    if resolved_day != requested_day:
        raise RuntimeError(
            f"workspace snapshot day mismatch: expected={requested_day}, actual={resolved_day or '-'}"
        )
    candidates = rank_context_candidates(
        workspace,
        strategy_version=strategy_version,
    )
    status = store.materialize_rank_context(
        snapshot_day=resolved_day,
        strategy_version=strategy_version,
        start_key=start_key,
        source_fingerprint=source_fingerprint,
        candidates=candidates,
        context_scope=scope,
    )
    if logger:
        logger.info(
            "候选上下文排名已物化: day=%s scope=%s candidates=%s revision=%s",
            resolved_day,
            scope,
            len(candidates),
            status.get("context_revision") or "-",
        )
    return {
        "status": "materialized",
        "snapshot_day": resolved_day,
        "strategy_version": strategy_version,
        "start_key": start_key,
        "context_scope": scope,
        "candidate_count": len(candidates),
        "pruned_revision_count": pruned_revision_count,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "rank_context": status,
    }
