"""Compare real workspace and SQLite candidate API reads without switching clients."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.scan_candidate_shadow import compare_candidate_reads
from stock_analyzer.scan_snapshot import SNAPSHOT_SCAN_TYPES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool",
        action="append",
        dest="pools",
        choices=SNAPSHOT_SCAN_TYPES,
        help="Pool to compare; repeat for multiple pools. Defaults to all pools.",
    )
    parser.add_argument(
        "--snapshot-day",
        action="append",
        dest="snapshot_days",
        help="Compare a snapshot day; repeat for multiple trading days. Defaults to latest.",
    )
    parser.add_argument("--sector", default="")
    parser.add_argument("--concept", default="")
    parser.add_argument("--query", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument(
        "--rank-mode",
        choices=("snapshot_local", "contextual"),
        default="snapshot_local",
    )
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-examples", type=int, default=20)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument(
        "--require-order",
        action="store_true",
        help="Fail when the complete ordering differs; disabled while ranking ownership is open.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _fetch_all(
    client,
    endpoint: str,
    params: dict,
    page_size: int,
    max_pages: int,
) -> tuple[list[dict], dict, float, dict]:
    results = []
    first_payload = None
    offset = 0
    pages = []
    stable_count = True
    offsets_match = True
    has_more_consistent = True
    started_at = time.perf_counter()
    while True:
        if len(pages) >= max_pages:
            raise RuntimeError(f"{endpoint} exceeded --max-pages={max_pages}")
        query = dict(params)
        query.update({"limit": page_size, "offset": offset})
        response = client.get(endpoint, query_string=query)
        payload = response.get_json(silent=True) or {}
        if response.status_code != 200:
            raise RuntimeError(
                f"{endpoint} returned {response.status_code}: "
                f"{json.dumps(payload, ensure_ascii=False)}"
            )
        if first_payload is None:
            first_payload = payload
        elif payload.get("count") != first_payload.get("count"):
            stable_count = False
        page = list(payload.get("results") or [])
        offsets_match = offsets_match and int(payload.get("offset") or 0) == offset
        expected_loaded = min(
            int(payload.get("count") or 0),
            offset + len(page),
        )
        has_more_consistent = has_more_consistent and bool(payload.get("has_more")) == (
            expected_loaded < int(payload.get("count") or 0)
        )
        pages.append({
            "offset": offset,
            "received": len(page),
            "count": payload.get("count"),
            "loaded_count": payload.get("loaded_count"),
            "has_more": bool(payload.get("has_more")),
        })
        results.extend(page)
        if not payload.get("has_more") or not page:
            break
        offset += len(page)
    elapsed = time.perf_counter() - started_at
    meta = first_payload or {}
    reported_count = int(meta.get("count") or 0)
    pagination = {
        "page_count": len(pages),
        "loaded_count": len(results),
        "reported_count": reported_count,
        "count_matches_loaded": reported_count == len(results),
        "stable_count": stable_count,
        "offsets_match": offsets_match,
        "has_more_consistent": has_more_consistent,
        "pages": pages,
        "gate_pass": bool(
            reported_count == len(results)
            and stable_count
            and offsets_match
            and has_more_consistent
        ),
    }
    return results, meta, elapsed, pagination


def main() -> int:
    args = _parse_args()
    page_size = max(1, min(int(args.page_size), 1000))
    max_examples = max(1, min(int(args.max_examples), 100))
    pools = tuple(args.pools or SNAPSHOT_SCAN_TYPES)
    snapshot_days = args.snapshot_days or [""]

    import app as web_app

    client = web_app.app.test_client()
    reports = {}
    overall_hard_pass = True
    overall_order_match = True
    for snapshot_day in snapshot_days:
        day_key = snapshot_day or "latest"
        reports[day_key] = {}
        for pool in pools:
            common_params = {
                "scan_type": pool,
                "snapshot_day": snapshot_day,
                "sector": args.sector,
                "concept": args.concept,
                "query": args.query,
                "reason": args.reason,
            }
            workspace_results, workspace_meta, workspace_seconds, workspace_pagination = _fetch_all(
                client,
                "/api/scan_workspace/candidates",
                {**common_params, "lite": 1},
                page_size,
                max(1, args.max_pages),
            )
            index_results, index_meta, index_seconds, index_pagination = _fetch_all(
                client,
                "/api/scan_index/candidates",
                {**common_params, "rank_mode": args.rank_mode},
                page_size,
                max(1, args.max_pages),
            )
            comparison = compare_candidate_reads(
                workspace_results,
                index_results,
                max_examples=max_examples,
            )
            index_ranking = index_meta.get("ranking") or {}
            rank_mode_applied = index_ranking.get("mode") == args.rank_mode
            comparison["rank_mode_applied"] = rank_mode_applied
            workspace_filters = workspace_meta.get("filters") or {}
            index_filters = index_meta.get("filters") or {}
            filter_fields = ("sector", "concept", "query", "reason")
            filters_match = all(
                str(workspace_filters.get(field) or "") == str(index_filters.get(field) or "")
                for field in filter_fields
            )
            workspace_reported_count = workspace_meta.get("count")
            index_reported_count = index_meta.get("count")
            count_parity = workspace_reported_count == index_reported_count
            snapshot_day_match = (
                workspace_meta.get("latest_snapshot_day")
                == index_meta.get("latest_snapshot_day")
            )
            read_contract_gate = bool(
                filters_match
                and count_parity
                and workspace_pagination["gate_pass"]
                and index_pagination["gate_pass"]
                and snapshot_day_match
            )
            comparison["read_contract_gate_pass"] = read_contract_gate
            comparison["request"] = {
                "workspace_seconds": round(workspace_seconds, 4),
                "index_seconds": round(index_seconds, 4),
                "workspace_reported_count": workspace_reported_count,
                "index_reported_count": index_reported_count,
                "count_parity": count_parity,
                "filters_match": filters_match,
                "snapshot_day_match": snapshot_day_match,
                "workspace_pagination": workspace_pagination,
                "index_pagination": index_pagination,
                "workspace_latest_snapshot_day": workspace_meta.get("latest_snapshot_day"),
                "index_latest_snapshot_day": index_meta.get("latest_snapshot_day"),
                "index_ranking": index_ranking,
            }
            reports[day_key][pool] = comparison
            overall_hard_pass = (
                overall_hard_pass
                and comparison["hard_gate_pass"]
                and read_contract_gate
                and rank_mode_applied
            )
            overall_order_match = (
                overall_order_match and comparison["ordering"]["exact_match"]
            )

    output_pools = reports
    if args.summary_only:
        output_pools = {
            day: {
                pool: {
                    "hard_gate_pass": report["hard_gate_pass"],
                    "read_contract_gate_pass": report["read_contract_gate_pass"],
                    "membership": report["membership"],
                    "hard_mismatch_count": report["hard_fields"]["mismatch_count"],
                    "descriptive_mismatch_count": report["descriptive_fields"]["mismatch_count"],
                    "ranking_mismatch_count": report["ranking_fields"]["mismatch_count"],
                    "ordering": report["ordering"],
                    "request": {
                        "workspace_seconds": report["request"]["workspace_seconds"],
                        "index_seconds": report["request"]["index_seconds"],
                        "count_parity": report["request"]["count_parity"],
                        "filters_match": report["request"]["filters_match"],
                        "snapshot_day_match": report["request"]["snapshot_day_match"],
                        "workspace_pagination_pass": report["request"]["workspace_pagination"]["gate_pass"],
                        "index_pagination_pass": report["request"]["index_pagination"]["gate_pass"],
                        "index_ranking_mode": report["request"]["index_ranking"].get("mode"),
                    },
                }
                for pool, report in day_reports.items()
            }
            for day, day_reports in reports.items()
        }

    output = {
        "hard_gate_pass": overall_hard_pass,
        "trading_day_count": len([day for day in snapshot_days if day]),
        "order_gate_required": bool(args.require_order),
        "order_gate_pass": overall_order_match,
        "filters": {
            "snapshot_days": snapshot_days,
            "sector": args.sector,
            "concept": args.concept,
            "query": args.query,
            "reason": args.reason,
            "rank_mode": args.rank_mode,
        },
        "pools": output_pools,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
    return 0 if overall_hard_pass and (overall_order_match or not args.require_order) else 1


if __name__ == "__main__":
    raise SystemExit(main())
