"""Read-only coverage audit for the weight-free CandidateRanking V1 shadow projection."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.candidate_ranking_v1 import (
    build_calendar_session_index,
    build_candidate_ranking_features_v1,
)
from stock_analyzer.market_metadata_store import DEFAULT_MARKET_METADATA_PATH
from stock_analyzer.scan_index_store import DEFAULT_SCAN_INDEX_PATH
from stock_analyzer.versioning import DATA_START_DATE, SCAN_STRATEGY_VERSION


SNAPSHOT_DIR = Path(os.environ.get(
    "STOCK_ANALYZER_SCAN_SNAPSHOT_DIR",
    ROOT / ".cache" / "scan_snapshots",
))
SNAPSHOT_SCAN_TYPES = frozenset({"opportunity", "risk", "bottom_div"})


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--scan-db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    parser.add_argument("--market-db", type=Path, default=DEFAULT_MARKET_METADATA_PATH)
    parser.add_argument("--snapshot-day", required=True, help="Snapshot day in YYYYMMDD form.")
    parser.add_argument("--strategy-version", default=SCAN_STRATEGY_VERSION)
    parser.add_argument("--start-key", default=str(DATA_START_DATE).replace("-", ""))
    return parser.parse_args()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _rank_context(scan_db: sqlite3.Connection, args) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    scope = "latest_fresh"
    run_key = f"{args.snapshot_day}:{args.strategy_version}:{args.start_key}:{scope}"
    run = scan_db.execute(
        """
        SELECT r.context_revision, r.status, r.candidate_count, r.computed_at,
               r.source_fingerprint_json
        FROM rank_context_heads h
        JOIN rank_context_runs r ON r.context_revision = h.context_revision
        WHERE h.run_key = ?
        """,
        (run_key,),
    ).fetchone()
    if run is None:
        return ({"available": False, "run_key": run_key}, {})

    revision = str(run["context_revision"])
    rank_columns = {
        str(row[1])
        for row in scan_db.execute("PRAGMA table_info(candidate_rank_contexts)")
    }
    has_provenance = {
        "environment_permission",
        "market_context_json",
    }.issubset(rank_columns)
    provenance_select = (
        "crc.environment_permission, crc.market_context_json"
        if has_provenance
        else "NULL AS environment_permission, NULL AS market_context_json"
    )
    rows = scan_db.execute(
        f"""
        SELECT cs.pool, cs.code, crc.market_boost,
               crc.context_priority_group, {provenance_select}
        FROM candidate_rank_contexts crc
        JOIN candidate_summaries cs ON cs.id = crc.candidate_id
        WHERE crc.context_revision = ?
          AND cs.snapshot_day = ? AND cs.strategy_version = ? AND cs.start_key = ?
        """,
        (revision, args.snapshot_day, args.strategy_version, args.start_key),
    )
    context_by_candidate = {}
    for row in rows:
        adjustment = row["market_boost"]
        priority_group = str(row["context_priority_group"] or "")
        try:
            components = json.loads(str(row["market_context_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            components = {}
        if not isinstance(components, dict):
            components = {}
        if has_provenance:
            environment_permission = str(row["environment_permission"] or "unknown")
        else:
            # A trade_ready priority is only assigned after the contextual
            # environment gate allows entry; older revisions did not store the
            # exact permission or its market inputs.
            environment_permission = (
                "allowed" if priority_group == "trade_ready" else "unknown"
            )
        context_by_candidate[(str(row["pool"]), str(row["code"]))] = {
            "market_adjustment": adjustment,
            "priority_group": priority_group,
            "environment_permission": environment_permission,
            "market_components": components,
            "provenance_available": has_provenance,
            "revision": revision,
        }

    fingerprint = json.loads(str(run["source_fingerprint_json"] or "{}"))
    return ({
        "available": str(run["status"]) == "complete",
        "run_key": run_key,
        "revision": revision,
        "status": str(run["status"]),
        "candidate_count": int(run["candidate_count"]),
        "computed_at": str(run["computed_at"]),
        "provenance_available": has_provenance,
        "workspace_profile": fingerprint.get("workspace_profile", {}),
    }, context_by_candidate)


def _market_context_for_audit(context: dict[str, Any], expected_session_date: str) -> dict[str, Any]:
    components = context.get("market_components")
    components = components if isinstance(components, dict) else {}
    applied = [
        (name, item)
        for name, item in components.items()
        if isinstance(item, dict)
        and any(
            item.get(key) is not None
            for key in ("adjustment", "observed_adjustment", "source", "as_of")
        )
    ]
    adjustment = context.get("market_adjustment")
    if not applied:
        return {
            "market_adjustment": adjustment,
            "status": (
                "unknown"
                if adjustment is not None or context.get("status") == "unknown"
                else "missing"
            ),
            "as_of": None,
            "revision": context.get("revision"),
            "components": components,
        }

    dates = []
    missing_provenance = False
    stale = False
    future = False
    expected = str(expected_session_date or "")
    for _name, item in applied:
        source = str(item.get("source") or "").strip()
        date_text = str(item.get("as_of") or "").strip()
        try:
            date_value = datetime.strptime(date_text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            try:
                date_value = datetime.strptime(date_text, "%Y%m%d").date().isoformat()
            except ValueError:
                date_value = ""
        if not source or not date_value or not expected:
            missing_provenance = True
        if date_value:
            dates.append(date_value)
            if expected and date_value < expected:
                stale = True
            elif expected and date_value > expected:
                future = True
        stale = stale or item.get("status") == "stale"
        future = future or item.get("status") == "future"

    if future:
        status = "future"
    elif stale:
        status = "stale"
    elif missing_provenance:
        status = "unknown"
    else:
        status = "current"
    return {
        "market_adjustment": adjustment,
        "status": status,
        "as_of": min(dates) if dates else None,
        "revision": context.get("revision"),
        "components": components,
    }


def _calendar_index(
    market_db: sqlite3.Connection,
    snapshot: dict[str, Any],
    cache: dict[tuple[str, str], dict[str, int]],
) -> dict[str, int]:
    calendar_id = str(snapshot.get("calendar_id") or "XSHG")
    revision = str(snapshot.get("calendar_revision") or "")
    snapshot_day = str(snapshot.get("snapshot_day") or "")
    if len(snapshot_day) == 8 and snapshot_day.isdigit():
        snapshot_day = f"{snapshot_day[:4]}-{snapshot_day[4:6]}-{snapshot_day[6:8]}"
    key = (calendar_id, revision)
    if key not in cache:
        rows = market_db.execute(
            """
            SELECT session_date FROM trading_sessions
            WHERE calendar_id = ? AND source_revision = ? AND session_date <= ?
            ORDER BY session_date
            """,
            (calendar_id, revision, snapshot_day),
        )
        cache[key] = build_calendar_session_index([str(row[0]) for row in rows])
    return cache[key]


def run_audit(args) -> dict[str, Any]:
    snapshot_dir = args.snapshot_dir.expanduser().resolve()
    scan_db_path = args.scan_db.expanduser().resolve()
    market_db_path = args.market_db.expanduser().resolve()

    scan_db = _read_only_connection(scan_db_path)
    market_db = _read_only_connection(market_db_path)
    try:
        context_run, context_by_candidate = _rank_context(scan_db, args)
        tier_counts: dict[str, Counter[str]] = defaultdict(Counter)
        data_counts: dict[str, Counter[str]] = defaultdict(Counter)
        permission_counts: dict[str, Counter[str]] = defaultdict(Counter)
        environment_counts: dict[str, Counter[str]] = defaultdict(Counter)
        market_counts: dict[str, Counter[str]] = defaultdict(Counter)
        age_values: dict[str, list[int]] = defaultdict(list)
        candidate_count = 0
        snapshot_count = 0
        invalid_snapshot_count = 0
        session_indexes: dict[tuple[str, str], dict[str, int]] = {}

        pattern = f"??????_{args.start_key}_{args.snapshot_day}.json"
        for path in snapshot_dir.glob(pattern):
            try:
                snapshot = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid_snapshot_count += 1
                continue
            if snapshot.get("strategy_version") != args.strategy_version:
                continue
            snapshot_count += 1
            calendar_index = _calendar_index(market_db, snapshot, session_indexes)
            expected_session_date = max(calendar_index, key=calendar_index.get, default="")
            for pool, result in (snapshot.get("results") or {}).items():
                if pool not in SNAPSHOT_SCAN_TYPES or not isinstance(result, dict):
                    continue
                code = str(result.get("code") or snapshot.get("code") or "")
                market_context = context_by_candidate.get((pool, code))
                if market_context is None:
                    market_context = {"status": "unknown"}
                audited_market_context = _market_context_for_audit(
                    market_context,
                    expected_session_date,
                )
                features = build_candidate_ranking_features_v1(
                    snapshot,
                    pool,
                    result,
                    expected_session_date=expected_session_date,
                    calendar_session_index=calendar_index,
                    market_context=audited_market_context,
                    environment_permission=market_context.get("environment_permission"),
                )
                candidate_count += 1
                tier_counts[pool][features["eligibility_tier"]] += 1
                data_counts[pool][features["data_quality"]["status"]] += 1
                permission_counts[pool][features["permission"]] += 1
                environment_counts[pool][features["environment_permission"]] += 1
                market_counts[pool][features["market_context"]["status"]] += 1
                age = features["evidence"]["pivot_structure"]["age_sessions"]
                if age is not None:
                    age_values[pool].append(age)

        def nested_counts(values):
            return {
                pool: dict(sorted(counter.items()))
                for pool, counter in sorted(values.items())
            }

        pivot_age = {}
        for pool, values in sorted(age_values.items()):
            pivot_age[pool] = {
                "count": len(values),
                "mean_sessions": round(sum(values) / len(values), 2),
                "max_sessions": max(values),
            }
        return {
            "snapshot_day": args.snapshot_day,
            "strategy_version": args.strategy_version,
            "start_key": args.start_key,
            "evidence_level": "single-snapshot feature coverage; not a ranking or return test",
            "snapshot_count": snapshot_count,
            "invalid_snapshot_count": invalid_snapshot_count,
            "candidate_count": candidate_count,
            "rank_context": context_run,
            "tier_counts": nested_counts(tier_counts),
            "data_quality_counts": nested_counts(data_counts),
            "permission_counts": nested_counts(permission_counts),
            "environment_permission_counts": nested_counts(environment_counts),
            "market_context_counts": nested_counts(market_counts),
            "pivot_age": pivot_age,
            "ranking_score_generated": False,
        }
    finally:
        scan_db.close()
        market_db.close()


def main() -> int:
    args = _args()
    args.start_key = str(args.start_key or "default").replace("-", "")
    report = run_audit(args)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
