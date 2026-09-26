"""Canonical pool indexing helpers for scan workspace consumers."""

from dataclasses import dataclass

from stock_analyzer.scanner import normalize_scan_type


@dataclass(frozen=True)
class WorkspacePoolIndex:
    workspace: dict
    scan_type: str
    pool: dict
    results: tuple
    pool_count: int


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _workspace_dict(workspace):
    return workspace if isinstance(workspace, dict) else {}


def workspace_pool_index(workspace, scan_type="opportunity"):
    """Return the normalized pool index shared by list, detail, and compact views."""
    workspace = _workspace_dict(workspace)
    scan_type = normalize_scan_type(scan_type)
    pools = workspace.get("pools") if isinstance(workspace.get("pools"), dict) else {}
    pool = pools.get(scan_type) if isinstance(pools.get(scan_type), dict) else {}
    results = tuple(pool.get("results") or [])
    pool_count = _as_int(pool.get("count"), len(results))
    return WorkspacePoolIndex(
        workspace=workspace,
        scan_type=scan_type,
        pool=pool,
        results=results,
        pool_count=pool_count,
    )


def iter_workspace_pool_indexes(workspace):
    workspace = _workspace_dict(workspace)
    pools = workspace.get("pools") if isinstance(workspace.get("pools"), dict) else {}
    for scan_type in pools:
        yield workspace_pool_index(workspace, scan_type)


def workspace_page_meta(workspace):
    workspace = _workspace_dict(workspace)
    return {
        "latest_snapshot_day": workspace.get("latest_snapshot_day"),
        "latest_data_date": workspace.get("latest_data_date"),
        "history_mode": workspace.get("history_mode"),
        "history_snapshot_day": workspace.get("history_snapshot_day"),
    }


def workspace_pool_page(
    index,
    *,
    matcher=None,
    filters=None,
    limit=120,
    offset=0,
    result_mapper=None,
):
    """Return a stable filtered page from a WorkspacePoolIndex."""
    matcher = matcher or (lambda _result: True)
    filters = dict(filters or {})
    results = [result for result in index.results if matcher(result)]
    offset = max(0, _as_int(offset, 0))
    limit = max(1, _as_int(limit, 120))
    page = results[offset:offset + limit]
    if result_mapper is not None:
        page = [result_mapper(result) for result in page]
    loaded_count = min(len(results), offset + len(page))
    return {
        "scan_type": index.scan_type,
        "filters": filters,
        "offset": offset,
        "limit": limit,
        "count": len(results),
        "loaded_count": loaded_count,
        "has_more": loaded_count < len(results),
        "pool_count": index.pool_count,
        "results": page,
        **workspace_page_meta(index.workspace),
    }
