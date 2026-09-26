"""Compare SQLite candidate summaries with their source snapshot results."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.candidate_read_model import CandidateSummary
from stock_analyzer.scan_index_store import DEFAULT_SCAN_INDEX_PATH, ScanIndexStore
from stock_analyzer.scan_snapshot import SNAPSHOT_DIR, SNAPSHOT_SCAN_TYPES
from stock_analyzer.versioning import DATA_START_DATE, SCAN_STRATEGY_VERSION


COMPARE_FIELDS = (
    "schema_version",
    "strategy_version",
    "code",
    "as_of",
    "bar_state",
    "data_source",
    "data_revision",
    "generated_at",
    "calendar_id",
    "calendar_revision",
    "calendar_evidence_level",
    "snapshot_day",
    "start_key",
    "snapshot_version",
    "strategy_status",
    "name",
    "pool",
    "event_date",
    "signal_key",
    "signal_label",
    "state",
    "permission",
    "plan_status",
    "priority_score",
    "priority_group",
    "reason_summary",
    "reason_tags",
    "missing_confirmations",
    "invalidation_price",
    "sector",
    "concepts",
    "price",
    "final_score",
    "confirm_score",
    "risk_score",
    "profile_quality_label",
    "profile_quality_score",
    "requires_trade_plan",
    "requires_stop_loss",
)


def _start_key(value: str) -> str:
    return str(value or "default").replace("-", "")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate indexed candidate summaries against source JSON snapshots."
    )
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    parser.add_argument("--snapshot-day", required=True, help="Snapshot day in YYYYMMDD form.")
    parser.add_argument("--strategy-version", default=SCAN_STRATEGY_VERSION)
    parser.add_argument("--start-key", default=_start_key(DATA_START_DATE))
    parser.add_argument(
        "--pool",
        action="append",
        dest="pools",
        choices=SNAPSHOT_SCAN_TYPES,
        help="Pool to validate; repeat for multiple pools. Defaults to all pools.",
    )
    parser.add_argument("--max-examples", type=int, default=20)
    return parser.parse_args()


def _source_candidates(args) -> dict[tuple[str, str], dict]:
    output = {}
    pattern = f"??????_{args.start_key}_{args.snapshot_day}.json"
    pools = tuple(args.pools or SNAPSHOT_SCAN_TYPES)
    for path in args.snapshot_dir.glob(pattern):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if snapshot.get("strategy_version") != args.strategy_version:
            continue
        for pool in pools:
            summary = CandidateSummary.from_snapshot(
                snapshot,
                pool,
                start_key=args.start_key,
            )
            if summary is not None:
                output[(summary.code, pool)] = summary.to_dict()
    return output


def _indexed_candidates(args, store) -> dict[tuple[str, str], dict]:
    output = {}
    pools = tuple(args.pools or SNAPSHOT_SCAN_TYPES)
    for pool in pools:
        offset = 0
        while True:
            page = store.query_candidates(
                pool=pool,
                snapshot_day=args.snapshot_day,
                strategy_version=args.strategy_version,
                start_key=args.start_key,
                limit=1000,
                offset=offset,
            )
            for candidate in page:
                output[(candidate["code"], pool)] = candidate
            if len(page) < 1000:
                break
            offset += len(page)
    return output


def main() -> int:
    args = _parse_args()
    args.snapshot_dir = args.snapshot_dir.expanduser().resolve()
    args.db = args.db.expanduser().resolve()
    args.start_key = _start_key(args.start_key)
    store = ScanIndexStore(args.db)

    source = _source_candidates(args)
    indexed = _indexed_candidates(args, store)
    source_keys = set(source)
    indexed_keys = set(indexed)
    missing = sorted(source_keys - indexed_keys)
    extra = sorted(indexed_keys - source_keys)
    mismatches = []
    mismatch_fields = Counter()

    for key in sorted(source_keys & indexed_keys):
        source_item = source[key]
        indexed_item = indexed[key]
        differences = {}
        for field in COMPARE_FIELDS:
            if source_item.get(field) == indexed_item.get(field):
                continue
            differences[field] = {
                "source": source_item.get(field),
                "index": indexed_item.get(field),
            }
            mismatch_fields[field] += 1
        if differences:
            mismatches.append({"code": key[0], "pool": key[1], "fields": differences})

    pools = tuple(args.pools or SNAPSHOT_SCAN_TYPES)
    summary = {
        "snapshot_day": args.snapshot_day,
        "strategy_version": args.strategy_version,
        "start_key": args.start_key,
        "source_count": len(source),
        "index_count": len(indexed),
        "source_by_pool": dict(Counter(pool for _, pool in source)),
        "index_by_pool": dict(Counter(pool for _, pool in indexed)),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "mismatch_count": len(mismatches),
        "mismatch_fields": dict(mismatch_fields),
        "pools": list(pools),
        "examples": {
            "missing": missing[: args.max_examples],
            "extra": extra[: args.max_examples],
            "mismatches": mismatches[: args.max_examples],
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not missing and not extra and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
