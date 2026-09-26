"""Compare a daily SQLite stock-universe snapshot with persisted market scan jobs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.current_universe_audit import (
    audit_current_universe_scan,
    load_scan_job_history,
)
from stock_analyzer.market_metadata_store import (
    DEFAULT_MARKET_METADATA_PATH,
    MarketMetadataStore,
)
from stock_analyzer.scan_jobs import DEFAULT_HISTORY_PATH


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Exact universe/session date, YYYY-MM-DD")
    parser.add_argument("--db", type=Path, default=DEFAULT_MARKET_METADATA_PATH)
    parser.add_argument("--jobs", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--output", type=Path, help="Optional path for a persistent JSON report")
    return parser.parse_args()


def main():
    args = _parse_args()
    try:
        jobs = load_scan_job_history(args.jobs)
        report = audit_current_universe_scan(
            args.as_of,
            MarketMetadataStore(args.db),
            jobs,
        )
    except Exception as exc:
        print(json.dumps({
            "as_of": args.as_of,
            "status": "audit_error",
            "error": str(exc),
        }, ensure_ascii=False, indent=2))
        return 1

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp_path = args.output.with_name(f"{args.output.name}.tmp")
        temp_path.write_text(rendered + "\n", encoding="utf-8")
        temp_path.replace(args.output)
    return 0 if report["status"] == "consistent" else 2


if __name__ == "__main__":
    raise SystemExit(main())
