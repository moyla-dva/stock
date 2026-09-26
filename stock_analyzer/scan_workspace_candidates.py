"""Filtered candidate shaping for scan workspace drill-downs."""

from stock_analyzer.scan_common import result_concepts
from stock_analyzer.candidate_reasons import candidate_matches_reason, candidate_reason_texts
from stock_analyzer.scanner import normalize_scan_type
from stock_analyzer.scan_workspace_index import workspace_pool_index, workspace_pool_page


def _normalize_text(value):
    return str(value or "").strip().lower()


def _candidate_event_date(result):
    return str(result.get("event_date") or result.get("date") or "")


def _candidate_matches(result, sector="", concept="", query="", reason="", code="", event_date=""):
    if code and str(result.get("code") or "") != str(code):
        return False
    if event_date and _candidate_event_date(result) != str(event_date):
        return False
    if sector and str(result.get("sector") or "") != sector:
        return False
    if concept and concept not in result_concepts(result):
        return False
    if not candidate_matches_reason(result, reason=reason):
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
        " ".join(candidate_reason_texts(result)),
    ]
    return any(query in _normalize_text(value) for value in haystack)


def filter_workspace_candidates(
    workspace,
    scan_type="opportunity",
    sector="",
    concept="",
    query="",
    reason="",
    code="",
    event_date="",
    limit=120,
    offset=0,
    compact_result_func=None,
):
    """Return a stable filtered candidate page from a full local workspace payload."""
    scan_type = normalize_scan_type(scan_type)
    index = workspace_pool_index(workspace, scan_type)
    filters = {
        "sector": sector or "",
        "concept": concept or "",
        "query": query or "",
        "reason": reason or "",
        "code": code or "",
        "event_date": event_date or "",
    }
    return workspace_pool_page(
        index,
        matcher=lambda result: _candidate_matches(
            result,
            sector=sector,
            concept=concept,
            query=query,
            reason=reason,
            code=code,
            event_date=event_date,
        ),
        filters=filters,
        limit=limit,
        offset=offset,
        result_mapper=compact_result_func,
    )
