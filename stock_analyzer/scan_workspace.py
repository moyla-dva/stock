"""Build the local scan workspace from persisted snapshots."""

from stock_analyzer.scan_workspace_history_compare import (
    apply_history_comparison,
    build_latest_reference,
)
from stock_analyzer.scan_workspace_loader import load_workspace_snapshot_pools
from stock_analyzer.scan_workspace_response import build_workspace_response, trim_workspace_pools
from stock_analyzer.scan_workspace_structure import build_workspace_structure


WORKSPACE_SCAN_TYPES = ("opportunity", "risk", "bottom_div")


def collect_scan_workspace(
    start_date=None,
    scan_types=WORKSPACE_SCAN_TYPES,
    max_items=120,
    logger=None,
    snapshot_day=None,
    replay_entry_model="event_close",
    overview_limit=None,
    pool_stats_limit=None,
    latest_only=False,
    include_history_comparison=True,
):
    loaded = load_workspace_snapshot_pools(
        start_date=start_date,
        scan_types=scan_types,
        logger=logger,
        snapshot_day=snapshot_day,
        latest_only=latest_only,
    )
    structure = build_workspace_structure(
        loaded["pools"],
        replay_entry_model=replay_entry_model,
    )

    trim_workspace_pools(loaded["pools"], max_items)

    target_snapshot_day = loaded["target_snapshot_day"]
    if target_snapshot_day and include_history_comparison:
        latest_reference = build_latest_reference(
            start_date=start_date,
            excluded_snapshot_day=target_snapshot_day,
            logger=logger,
        )
        apply_history_comparison(loaded["pools"], latest_reference)

    return build_workspace_response(
        loaded,
        structure,
        start_date=start_date,
        max_items=max_items,
        overview_limit=overview_limit,
        pool_stats_limit=pool_stats_limit,
    )
