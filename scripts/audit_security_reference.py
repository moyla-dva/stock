"""Audit effective-dated security reference coverage without network access."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.market_metadata_store import (
    DEFAULT_MARKET_METADATA_PATH,
    MarketMetadataStore,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_MARKET_METADATA_PATH)
    parser.add_argument("--dataset-id", default="A_SHARE_HISTORY")
    parser.add_argument("--revision")
    parser.add_argument("--as-of")
    parser.add_argument("--require-historical-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    store = MarketMetadataStore(args.db.expanduser().resolve())
    report = store.security_reference_coverage_report(
        dataset_id=args.dataset_id,
        revision=args.revision,
    )
    if args.as_of:
        report["point_in_time"] = store.security_reference_as_of(
            args.as_of,
            dataset_id=args.dataset_id,
            revision=args.revision,
        )
    if report.get("available"):
        with sqlite3.connect(store.path) as connection:
            report["sqlite_integrity"] = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            report["foreign_key_violation_count"] = len(
                connection.execute("PRAGMA foreign_key_check").fetchall()
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("available"):
        return 1
    if report.get("sqlite_integrity") != "ok" or report.get("foreign_key_violation_count"):
        return 1
    if args.require_historical_ready and not report.get("historical_research_eligible"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
