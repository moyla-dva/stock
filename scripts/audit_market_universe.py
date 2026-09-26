"""Audit one point-in-time stock universe without network access."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--allow-previous", action="store_true")
    parser.add_argument("--require-historical-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    store = MarketMetadataStore(args.db.expanduser().resolve())
    report = store.universe_coverage_report(
        args.as_of,
        allow_previous=args.allow_previous,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["available"] or not report["current_scan_eligible"]:
        return 1
    if args.require_historical_ready and not report["historical_research_eligible"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
