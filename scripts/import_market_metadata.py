"""Import local calendars, universe snapshots, or effective-dated security references."""

from __future__ import annotations

import argparse
import csv
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


def _load_input(path: Path):
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    return json.loads(path.read_text(encoding="utf-8"))


def _calendar_sessions(payload, date_column: str):
    if isinstance(payload, dict):
        payload = payload.get("sessions", [])
    output = []
    for item in payload:
        output.append(item.get(date_column) if isinstance(item, dict) else item)
    return output


def _universe_document(payload):
    if isinstance(payload, dict):
        return {
            "members": payload.get("members", []),
            "coverage_status": payload.get("coverage_status", "unknown"),
            "coverage": payload.get("coverage", {}),
            "warnings": payload.get("warnings", []),
        }
    return {
        "members": payload,
        "coverage_status": "unknown",
        "coverage": {},
        "warnings": [],
    }


def _security_reference_document(path: Path):
    if path.is_dir():
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("security-reference CSV bundle requires manifest.json")
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("security-reference manifest must be a JSON object")
        required_files = {
            "securities": "securities.csv",
            "evidence": "evidence.csv",
            "aliases": "aliases.csv",
            "memberships": "memberships.csv",
        }
        for key, filename in required_files.items():
            csv_path = path / filename
            if not csv_path.exists():
                raise ValueError(f"security-reference CSV bundle missing {filename}")
            document[key] = _load_input(csv_path)
        names_path = path / "names.csv"
        document["names"] = _load_input(names_path) if names_path.exists() else []
        return document
    if path.suffix.lower() != ".json":
        raise ValueError(
            "security-reference input must be a JSON document or a CSV bundle directory"
        )
    payload = _load_input(path)
    if not isinstance(payload, dict):
        raise ValueError("security-reference JSON input must be an object")
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_MARKET_METADATA_PATH)
    subparsers = parser.add_subparsers(dest="kind", required=True)

    calendar = subparsers.add_parser("calendar")
    calendar.add_argument("--input", type=Path, required=True)
    calendar.add_argument("--calendar-id", default="XSHG")
    calendar.add_argument("--date-column", default="session_date")
    calendar.add_argument("--source", required=True)
    calendar.add_argument("--evidence-level", required=True)

    universe = subparsers.add_parser("universe")
    universe.add_argument("--input", type=Path, required=True)
    universe.add_argument("--as-of", required=True)
    universe.add_argument("--source", required=True)
    universe.add_argument("--evidence-level", required=True)

    security_reference = subparsers.add_parser("security-reference")
    security_reference.add_argument(
        "--input",
        type=Path,
        required=True,
        help="JSON document or directory containing manifest.json and normalized CSV tables",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    input_path = args.input.expanduser().resolve()
    store = MarketMetadataStore(args.db.expanduser().resolve())
    if args.kind == "calendar":
        payload = _load_input(input_path)
        result = store.import_trading_calendar(
            _calendar_sessions(payload, args.date_column),
            calendar_id=args.calendar_id,
            source=args.source,
            evidence_level=args.evidence_level,
        )
    elif args.kind == "universe":
        payload = _load_input(input_path)
        document = _universe_document(payload)
        result = store.import_universe_snapshot(
            args.as_of,
            document["members"],
            source=args.source,
            evidence_level=args.evidence_level,
            coverage_status=document["coverage_status"],
            coverage=document["coverage"],
            warnings=document["warnings"],
        )
    else:
        document = _security_reference_document(input_path)
        result = store.import_security_reference(document)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
