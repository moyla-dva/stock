"""Refresh market reference metadata from configured provider adapters."""

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
from stock_analyzer.providers.market_reference import (
    build_exchange_universe,
    load_exchange_validated_calendar,
)


OFFICIAL_2026_CHECKS = {
    "2026-09-21": True,
    "2026-09-24": True,
    "2026-09-25": False,
    "2026-09-28": True,
    "2026-10-01": False,
    "2026-10-07": False,
    "2026-10-08": True,
    "2026-10-10": False,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_MARKET_METADATA_PATH)
    subparsers = parser.add_subparsers(dest="kind", required=True)
    subparsers.add_parser("calendar")
    universe = subparsers.add_parser("universe")
    universe.add_argument("--as-of", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    store = MarketMetadataStore(args.db.expanduser().resolve())
    if args.kind == "calendar":
        payload = load_exchange_validated_calendar()
        result = store.import_trading_calendar(
            payload.sessions,
            source=payload.source,
            evidence_level=payload.evidence_level,
            evidence_segments=payload.evidence_segments,
        )
        checks = {
            day: store.is_trading_session(day) == expected
            for day, expected in OFFICIAL_2026_CHECKS.items()
        }
        result["official_2026_checks"] = checks
        result["official_2026_checks_passed"] = all(checks.values())
    else:
        payload = build_exchange_universe(args.as_of)
        result = store.import_universe_snapshot(
            payload.as_of,
            payload.members,
            source=payload.source,
            evidence_level=payload.evidence_level,
            coverage_status=payload.coverage_status,
            coverage=payload.coverage,
            warnings=payload.warnings,
        )
        result["members"] = result["members"][:5]
        result["members_truncated"] = result["member_count"] > 5
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
