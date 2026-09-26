"""Materialize one complete contextual candidate-ranking overlay into SQLite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.scan_index_store import (
    DEFAULT_SCAN_INDEX_PATH,
    RANK_CONTEXT_SCOPES,
    RANK_CONTEXT_SCOPE_SNAPSHOT,
    ScanIndexStore,
)
from stock_analyzer.scan_rank_context_materializer import (
    materialize_workspace_rank_context,
)
from stock_analyzer.scan_snapshot import normalize_snapshot_day
from stock_analyzer.versioning import DATA_START_DATE, SCAN_STRATEGY_VERSION


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    parser.add_argument("--snapshot-day", default="")
    parser.add_argument("--start-date", default=DATA_START_DATE)
    parser.add_argument("--strategy-version", default=SCAN_STRATEGY_VERSION)
    parser.add_argument(
        "--scope",
        choices=sorted(RANK_CONTEXT_SCOPES),
        default=RANK_CONTEXT_SCOPE_SNAPSHOT,
        help="ranking population: full snapshot or current fresh candidates",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    requested_day = normalize_snapshot_day(args.snapshot_day)
    if args.snapshot_day and not requested_day:
        raise SystemExit("snapshot_day must use YYYYMMDD or YYYY-MM-DD")
    store = ScanIndexStore(args.db.expanduser().resolve())
    output = materialize_workspace_rank_context(
        store,
        start_date=args.start_date,
        snapshot_day=requested_day or None,
        strategy_version=args.strategy_version,
        context_scope=args.scope,
    )
    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=None if args.json else 2,
            separators=(",", ":") if args.json else None,
        )
    )
    return 0 if output.get("rank_context", {}).get("available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
