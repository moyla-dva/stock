"""Filtered candidate shaping for scan workspace drill-downs."""

from stock_analyzer.scan_common import result_concepts
from stock_analyzer.scanner import normalize_scan_type


def _normalize_text(value):
    return str(value or "").strip().lower()


def _candidate_matches(result, sector="", concept="", query=""):
    if sector and str(result.get("sector") or "") != sector:
        return False
    if concept and concept not in result_concepts(result):
        return False
    query = _normalize_text(query)
    if not query:
        return True
    haystack = [
        result.get("code"),
        result.get("name"),
        result.get("sector"),
        " ".join(result_concepts(result)),
        result.get("signal"),
        result.get("signal_label"),
        result.get("signal_name"),
        result.get("reason"),
    ]
    return any(query in _normalize_text(value) for value in haystack)


def filter_workspace_candidates(
    workspace,
    scan_type="opportunity",
    sector="",
    concept="",
    query="",
    limit=120,
    offset=0,
):
    """Return a stable filtered candidate page from a full local workspace payload."""
    scan_type = normalize_scan_type(scan_type)
    pools = workspace.get("pools") or {}
    pool = pools.get(scan_type) or {}
    results = [
        result
        for result in pool.get("results", [])
        if _candidate_matches(
            result,
            sector=sector,
            concept=concept,
            query=query,
        )
    ]
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or 120))
    page = results[offset:offset + limit]
    loaded_count = min(len(results), offset + len(page))
    return {
        "scan_type": scan_type,
        "filters": {
            "sector": sector or "",
            "concept": concept or "",
            "query": query or "",
        },
        "offset": offset,
        "limit": limit,
        "count": len(results),
        "loaded_count": loaded_count,
        "has_more": loaded_count < len(results),
        "pool_count": pool.get("count") or len(pool.get("results", [])),
        "results": page,
        "latest_snapshot_day": workspace.get("latest_snapshot_day"),
        "latest_data_date": workspace.get("latest_data_date"),
        "history_mode": workspace.get("history_mode"),
        "history_snapshot_day": workspace.get("history_snapshot_day"),
    }
