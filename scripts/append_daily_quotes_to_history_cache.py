#!/usr/bin/env python3
"""Append the latest daily bar from Tencent batch quotes into the local history cache.

The production cache now uses one stable file per stock/start/adjust key. This
script remains useful for local data operations: it discovers both the new stable
cache file and legacy per-end-date files, appends the requested bar when missing,
and writes the canonical cache path.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stock_analyzer.data_fetcher import CACHE_DIR, cache_path_for_history
from stock_analyzer.providers.stock_history import market_symbol_for_tx
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE

QUOTE_URL = "https://qt.gtimg.cn/q="
CACHE_COLUMNS = ["date", "open", "close", "high", "low", "volume", "turnover", "amount"]
DEFAULT_MAX_CLOSE_JUMP_PCT = 35.0


def discover_latest_cache(start_text):
    """Return {code: (end_text, path)} for the newest cache file per code."""
    adjust_key = DATA_ADJUST or "none"
    latest = {}
    for path in list(CACHE_DIR.glob(f"*_{start_text}_{adjust_key}.csv")) + list(CACHE_DIR.glob(f"*_{start_text}_*_{adjust_key}.csv")):
        parts = path.stem.split("_")
        if len(parts) == 3:
            code, file_start, _ = parts
            end_text = ""
            try:
                frame = pd.read_csv(path, usecols=lambda column: column in {"date", "日期"})
                dates = pd.to_datetime(frame.get("date", frame.get("日期")), errors="coerce").dropna()
                if not dates.empty:
                    end_text = dates.max().strftime("%Y%m%d")
            except Exception:
                end_text = ""
        elif len(parts) == 4:
            code, file_start, end_text, _ = parts
        else:
            continue
        if file_start != start_text or len(code) != 6 or len(end_text) != 8:
            continue
        if code not in latest or end_text > latest[code][0]:
            latest[code] = (end_text, path)
    return latest


def fetch_quote_text(symbols, timeout=10):
    response = requests.get(QUOTE_URL + ",".join(symbols), timeout=timeout)
    response.raise_for_status()
    return response.content.decode("gbk", errors="ignore")


def parse_quotes(text):
    """Return {code: fields} parsed from the Tencent quote payload."""
    quotes = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        _, _, payload = line.partition("=")
        payload = payload.strip().rstrip(";").strip('"')
        fields = payload.split("~")
        if len(fields) < 39 or len(fields[2]) != 6:
            continue
        quotes[fields[2]] = fields
    return quotes


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _date_text(value):
    try:
        date = pd.to_datetime(value, errors="coerce")
    except Exception:
        return ""
    if pd.isna(date):
        return ""
    return date.strftime("%Y%m%d")


def _latest_cache_bar(frame):
    if frame is None or frame.empty or "date" not in frame.columns or "close" not in frame.columns:
        return "", None
    dated = frame[["date", "close"]].copy()
    dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
    dated["close"] = pd.to_numeric(dated["close"], errors="coerce")
    dated = dated.dropna(subset=["date", "close"]).sort_values("date")
    if dated.empty:
        return "", None
    latest = dated.iloc[-1]
    close = _number(latest.get("close"))
    return latest["date"].strftime("%Y%m%d"), close


def _business_days_to_target(previous_date_text, target_date_text):
    previous = pd.to_datetime(previous_date_text, format="%Y%m%d", errors="coerce")
    target = pd.to_datetime(target_date_text, format="%Y%m%d", errors="coerce")
    if pd.isna(previous) or pd.isna(target) or target <= previous:
        return 0
    start = previous + pd.offsets.BDay(1)
    return len(pd.bdate_range(start=start, end=target))


def append_rejection_reason(previous, bar, target_date_text, *, allow_gap=False, max_close_jump_pct=DEFAULT_MAX_CLOSE_JUMP_PCT):
    """Return a reason string when appending the quote bar would be unsafe."""
    latest_date, previous_close = _latest_cache_bar(previous)
    bar_date = _date_text(bar.get("date") if isinstance(bar, dict) else None)
    target_date_text = str(target_date_text or "").replace("-", "")
    if len(target_date_text) != 8:
        return "invalid_target_date"
    if bar_date != target_date_text:
        return "quote_date_mismatch"
    if not latest_date or previous_close is None:
        return "cache_latest_bar_missing"
    if bar_date <= latest_date:
        return "bar_already_cached"
    if not allow_gap and _business_days_to_target(latest_date, bar_date) != 1:
        return "cache_gap_detected"
    close = _number(bar.get("close") if isinstance(bar, dict) else None)
    if close is None or close <= 0:
        return "invalid_quote_close"
    if previous_close <= 0:
        return "invalid_previous_close"
    jump_pct = abs(close / previous_close - 1) * 100
    if jump_pct > float(max_close_jump_pct):
        return "close_jump_exceeds_limit"
    return ""


def bar_from_quote(fields, target_date_text):
    """Build one cache row from quote fields, or None when unusable."""
    close = _number(fields[3])
    open_price = _number(fields[5])
    high = _number(fields[33])
    low = _number(fields[34])
    volume = _number(fields[6])
    quote_date = str(fields[30])[:8]
    if quote_date != target_date_text:
        return None
    if None in (close, open_price, high, low) or close <= 0 or volume is None or volume <= 0:
        return None
    turnover_pct = _number(fields[38])
    amount_wan = _number(fields[37])
    return {
        "date": f"{quote_date[:4]}-{quote_date[4:6]}-{quote_date[6:]}",
        "open": open_price,
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "turnover": None if turnover_pct is None else round(turnover_pct / 100, 6),
        "amount": None if amount_wan is None else amount_wan * 10000,
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-date", required=True, help="target bar date, YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--start-date", default=DATA_START_DATE)
    parser.add_argument("--batch-size", type=int, default=60)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--allow-gap", action="store_true", help="append even when the local cache is missing earlier business days")
    parser.add_argument("--max-close-jump-pct", type=float, default=DEFAULT_MAX_CLOSE_JUMP_PCT)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    target_date = str(args.data_date).replace("-", "")
    if len(target_date) != 8 or not target_date.isdigit():
        raise SystemExit("--data-date must be YYYY-MM-DD or YYYYMMDD")
    start_text = str(args.start_date).replace("-", "")

    latest = discover_latest_cache(start_text)
    codes = sorted(code for code, (end_text, _) in latest.items() if end_text < target_date)
    if args.limit:
        codes = codes[: args.limit]
    print(f"codes needing {target_date}: {len(codes)}")

    appended = skipped = failed = 0
    started = time.time()
    batch_size = max(1, args.batch_size)
    for offset in range(0, len(codes), batch_size):
        chunk = codes[offset:offset + batch_size]
        symbols = [market_symbol_for_tx(code) for code in chunk]
        symbols = [symbol for symbol in symbols if symbol]
        try:
            quotes = parse_quotes(fetch_quote_text(symbols))
        except Exception as exc:  # network hiccup: skip this batch
            failed += len(chunk)
            print(f"  batch {offset // batch_size + 1} failed: {exc}")
            continue

        for code in chunk:
            fields = quotes.get(code)
            if fields is None:
                skipped += 1
                continue
            bar = bar_from_quote(fields, target_date)
            if bar is None:
                skipped += 1
                continue
            end_text, path = latest[code]
            try:
                previous = pd.read_csv(path)
            except Exception:
                failed += 1
                continue
            previous = previous.reindex(columns=CACHE_COLUMNS)
            rejection = append_rejection_reason(
                previous,
                bar,
                target_date,
                allow_gap=args.allow_gap,
                max_close_jump_pct=args.max_close_jump_pct,
            )
            if rejection:
                failed += 1
                print(f"  {code} rejected: {rejection} latest={end_text} target={target_date}")
                continue
            merged = pd.concat([previous, pd.DataFrame([bar])], ignore_index=True)
            merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")
            if not args.dry_run:
                out_path = cache_path_for_history(code, start_text, target_date, adjust=DATA_ADJUST)
                merged.to_csv(out_path, index=False)
            appended += 1

        if (offset // batch_size) % 10 == 0:
            done = min(offset + batch_size, len(codes))
            print(f"  progress {done}/{len(codes)} appended={appended} skipped={skipped} failed={failed}")

    elapsed = time.time() - started
    print(
        f"done: appended={appended} skipped={skipped} failed={failed} "
        f"elapsed={elapsed:.1f}s dry_run={args.dry_run}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
