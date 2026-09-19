#!/usr/bin/env python3
"""Backfill a missed date range into the local daily history cache.

The batch-quote append script can only add the latest bar. When several
trading days were missed (holiday breaks, machine off), appending just the
latest quote would leave a gap in the cached K-line series and silently
corrupt every rolling calculation built on it. This script fetches the
missing range per stock from Tencent's daily kline endpoint (qfq) and writes
a new cache file keyed by the end bar date, never touching earlier files.

Typical flow before a snapshot rebuild:

    python scripts/backfill_daily_history_cache.py \
        --start-bar-date 2026-09-12 --end-bar-date 2026-09-17
    python scripts/append_daily_quotes_to_history_cache.py --data-date 2026-09-18
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.append_daily_quotes_to_history_cache import CACHE_COLUMNS, discover_latest_cache
from stock_analyzer.data_fetcher import cache_path_for_history
from stock_analyzer.providers.stock_history import (
    _fetch_tx_history_direct,
    market_symbol_for_tx,
)
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE


def parse_date_text(value):
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise SystemExit(f"date must be YYYY-MM-DD or YYYYMMDD: {value!r}")
    return datetime.strptime(text, "%Y%m%d").date()


def next_date_text(day):
    return (day + timedelta(days=1)).strftime("%Y%m%d")


def backfill_one(code, end_text, previous_path, start_text, fetch_start_text, dry_run=False):
    tx_code = market_symbol_for_tx(code)
    if not tx_code:
        return code, "skipped", "no_tx_symbol"
    try:
        fetched = _fetch_tx_history_direct(tx_code, fetch_start_text, end_text, adjust=DATA_ADJUST)
    except Exception as exc:
        return code, "failed", str(exc)
    if fetched is None or fetched.empty:
        return code, "skipped", "no_data"
    frame = fetched.rename(columns={"amount": "volume"})
    frame["date"] = frame["date"].astype(str)
    frame["turnover"] = None
    frame["amount"] = None
    frame = frame.reindex(columns=CACHE_COLUMNS)
    try:
        previous = pd.read_csv(previous_path)
    except Exception as exc:
        return code, "failed", f"read_cache: {exc}"
    previous = previous.reindex(columns=CACHE_COLUMNS)
    previous["date"] = previous["date"].astype(str)
    merged = pd.concat([previous, frame], ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    last_date = str(merged.iloc[-1]["date"])[:10]
    if last_date != str(end_text)[:4] + "-" + str(end_text)[4:6] + "-" + str(end_text)[6:]:
        return code, "skipped", f"no_bar_on_target_date (last={last_date})"
    if not dry_run:
        out_path = cache_path_for_history(code, start_text, end_text, adjust=DATA_ADJUST)
        merged.to_csv(out_path, index=False)
    new_rows = len(merged) - len(previous)
    return code, "appended", new_rows


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bar-date", required=True, help="first missed bar date, YYYY-MM-DD")
    parser.add_argument("--end-bar-date", required=True, help="last missed bar date, YYYY-MM-DD")
    parser.add_argument("--start-date", default=DATA_START_DATE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    start_bar = parse_date_text(args.start_bar_date)
    end_bar = parse_date_text(args.end_bar_date)
    if end_bar < start_bar:
        raise SystemExit("--end-bar-date must not be before --start-bar-date")
    start_text = str(args.start_date).replace("-", "")

    latest = discover_latest_cache(start_text)
    jobs = []
    for code, (end_text, path) in sorted(latest.items()):
        try:
            cache_end = datetime.strptime(end_text, "%Y%m%d").date()
        except ValueError:
            continue
        if cache_end >= end_bar:
            continue
        fetch_start = (max(start_bar, cache_end + timedelta(days=1))).strftime("%Y%m%d")
        jobs.append((code, end_bar.strftime("%Y%m%d"), path, start_text, fetch_start))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"codes needing {end_bar.isoformat()}: {len(jobs)}")

    appended = skipped = failed = 0
    started = time.time()
    workers = max(1, args.workers)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(backfill_one, code, end_text, path, start_text, fetch_start, args.dry_run): code
            for code, end_text, path, start_text, fetch_start in jobs
        }
        for future in as_completed(futures):
            code, status, detail = future.result()
            done += 1
            if status == "appended":
                appended += 1
            elif status == "failed":
                failed += 1
                print(f"  failed {code}: {detail}")
            else:
                skipped += 1
                if detail and "no_bar_on_target_date" in str(detail):
                    print(f"  skipped {code}: {detail}")
            if done % 500 == 0:
                print(f"  progress {done}/{len(jobs)} appended={appended} skipped={skipped} failed={failed}")

    elapsed = time.time() - started
    print(
        f"done: appended={appended} skipped={skipped} failed={failed} "
        f"elapsed={elapsed:.1f}s dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
