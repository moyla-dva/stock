"""Audit that market scan jobs used the pinned current-universe revision."""

from __future__ import annotations

import json
from pathlib import Path


def _market_jobs_for_date(jobs, as_of):
    return [
        item for item in jobs
        if isinstance(item, dict)
        and str(item.get("scope") or "") == "market"
        and str(item.get("code_source") or "") == "market"
        and str(item.get("universe_as_of") or "") == as_of
    ]


def audit_current_universe_scan(as_of, store, jobs):
    """Compare an exact SQLite universe snapshot with persisted market scan jobs."""
    requested_as_of = str(as_of or "").strip()
    universe = store.universe_as_of(requested_as_of)
    if not universe.get("available") or not universe.get("exact_match"):
        return {
            "schema_version": 1,
            "as_of": requested_as_of,
            "status": "missing_universe_snapshot",
            "universe": {
                "available": bool(universe.get("available")),
                "revision": str(universe.get("revision") or ""),
                "member_count": int(universe.get("member_count") or 0),
            },
            "market_scan_jobs": [],
        }

    coverage = store.universe_coverage_report(requested_as_of)
    calendar = store.session_context(requested_as_of)
    expected = {
        "universe_as_of": requested_as_of,
        "universe_revision": str(universe.get("revision") or ""),
        "universe_source": str(universe.get("source") or ""),
        "universe_coverage_status": str(universe.get("coverage_status") or ""),
        "universe_member_count": int(universe.get("member_count") or 0),
        "universe_calendar_revision": str(calendar.get("calendar_revision") or ""),
    }
    eligible = bool(coverage.get("current_scan_eligible"))
    matching_jobs = _market_jobs_for_date(jobs or [], requested_as_of)
    job_reports = []
    for job in matching_jobs:
        mismatches = {}
        for field, expected_value in expected.items():
            if field == "universe_calendar_revision" and not expected_value:
                continue
            actual_value = job.get(field)
            if field == "universe_member_count":
                try:
                    actual_value = int(actual_value)
                except (TypeError, ValueError):
                    actual_value = None
            else:
                actual_value = str(actual_value or "")
            if actual_value != expected_value:
                mismatches[field] = {
                    "expected": expected_value,
                    "actual": actual_value,
                }
        job_reports.append({
            "id": str(job.get("id") or ""),
            "status": str(job.get("status") or "unknown"),
            "scan_type": str(job.get("scan_type") or ""),
            "started_at": str(job.get("started_at") or ""),
            "finished_at": str(job.get("finished_at") or ""),
            "requested_count": int(job.get("requested_count") or 0),
            "eligible_count": int(job.get("eligible_count") or 0),
            "mismatches": mismatches,
        })

    if not eligible:
        status = "universe_not_scan_eligible"
    elif not matching_jobs:
        status = "awaiting_market_scan"
    elif any(item["mismatches"] for item in job_reports):
        status = "mismatch"
    else:
        status = "consistent"

    return {
        "schema_version": 1,
        "as_of": requested_as_of,
        "status": status,
        "expected": expected,
        "universe": {
            "available": True,
            "exact_match": True,
            "coverage_status": str(universe.get("coverage_status") or ""),
            "current_scan_eligible": eligible,
            "warnings": list(universe.get("warnings") or []),
        },
        "calendar": {
            "is_session": calendar.get("is_session"),
            "revision": str(calendar.get("calendar_revision") or ""),
            "evidence_level": str(calendar.get("calendar_evidence_level") or ""),
        },
        "market_scan_jobs": job_reports,
    }


def load_scan_job_history(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    return [item for item in jobs if isinstance(item, dict)]
