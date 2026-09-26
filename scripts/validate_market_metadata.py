"""Validate calendar and point-in-time universe metadata without network access."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.market_metadata_store import (
    DEFAULT_MARKET_METADATA_PATH,
    MarketMetadataStore,
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
    parser.add_argument("--as-of", required=True)
    parser.add_argument(
        "--profile-cache",
        type=Path,
        default=ROOT / ".cache" / "catalog" / "stock_profiles.json",
    )
    return parser.parse_args()


def _profile_codes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return set(payload) if isinstance(payload, dict) else set()


def main() -> int:
    args = _parse_args()
    store = MarketMetadataStore(args.db.expanduser().resolve())
    calendar = store.calendar_status("XSHG")
    universe = store.universe_as_of(args.as_of)
    universe_coverage = store.universe_coverage_report(args.as_of)
    hard_errors = []

    if not calendar["available"]:
        hard_errors.append("calendar unavailable")
    calendar_checks = {
        day: store.is_trading_session(day) == expected
        for day, expected in OFFICIAL_2026_CHECKS.items()
    }
    if not all(calendar_checks.values()):
        hard_errors.append("official 2026 holiday checks failed")
    official_context = store.session_context("2026-09-22", calendar_id="XSHG")
    if official_context.get("calendar_evidence_level") != "exchange-official":
        hard_errors.append("2026 calendar is not backed by exchange-official evidence")
    if not universe["available"] or not universe["exact_match"]:
        hard_errors.append("exact universe snapshot unavailable")

    members = universe.get("members") or []
    codes = [str(item.get("code") or "") for item in members]
    invalid_codes = sorted({code for code in codes if not re.fullmatch(r"\d{6}", code)})
    duplicate_codes = sorted(code for code, count in Counter(codes).items() if count > 1)
    listing_after_as_of = sorted(
        item["code"]
        for item in members
        if item.get("listing_date") and item["listing_date"] > args.as_of
    )
    delisted_on_or_before_as_of = sorted(
        item["code"]
        for item in members
        if item.get("delisting_date") and item["delisting_date"] <= args.as_of
    )
    if invalid_codes:
        hard_errors.append(f"invalid codes: {len(invalid_codes)}")
    if duplicate_codes:
        hard_errors.append(f"duplicate codes: {len(duplicate_codes)}")
    if listing_after_as_of:
        hard_errors.append(f"members listed after as_of: {len(listing_after_as_of)}")
    if delisted_on_or_before_as_of:
        hard_errors.append(
            f"members delisted on or before as_of: {len(delisted_on_or_before_as_of)}"
        )

    profile_codes = _profile_codes(args.profile_cache.expanduser().resolve())
    universe_codes = set(codes)
    with sqlite3.connect(store.path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok":
        hard_errors.append(f"sqlite integrity check: {integrity}")
    if foreign_key_violations:
        hard_errors.append(f"foreign key violations: {foreign_key_violations}")

    output = {
        "database_path": str(store.path),
        "calendar": calendar,
        "official_2026_checks": calendar_checks,
        "official_2026_context": official_context,
        "universe": {
            key: value
            for key, value in universe.items()
            if key != "members"
        },
        "universe_coverage": universe_coverage,
        "member_sources": dict(Counter(item.get("member_source") for item in members)),
        "profile_comparison": {
            "profile_count": len(profile_codes),
            "overlap_count": len(profile_codes & universe_codes),
            "only_universe_count": len(universe_codes - profile_codes),
            "only_profiles_count": len(profile_codes - universe_codes),
            "only_universe_examples": sorted(universe_codes - profile_codes)[:20],
            "only_profiles_examples": sorted(profile_codes - universe_codes)[:20],
        },
        "validation": {
            "invalid_code_count": len(invalid_codes),
            "duplicate_code_count": len(duplicate_codes),
            "listing_after_as_of_count": len(listing_after_as_of),
            "delisted_on_or_before_as_of_count": len(delisted_on_or_before_as_of),
            "sqlite_integrity": integrity,
            "foreign_key_violation_count": foreign_key_violations,
            "hard_errors": hard_errors,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not hard_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
