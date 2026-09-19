#!/usr/bin/env python3
"""Fetch and append 2026-09-17 daily bars from Tencent into local history cache."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stock_analyzer.data_fetcher import CACHE_DIR, cache_path_for_history
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE
from scripts.append_daily_quotes_to_history_cache import discover_latest_cache

CACHE_COLUMNS = ["date", "open", "close", "high", "low", "volume", "turnover", "amount"]
TARGET_DATE_DASH = "2026-09-17"
TARGET_DATE_COMPACT = "20260917"
START_TEXT = DATA_START_DATE.replace("-", "")

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=40, pool_maxsize=40)
session.mount("https://", adapter)


def fetch_bar_917(code: str) -> tuple[str, list | None]:
    prefix = "sh" if code.startswith("6") else ("bj" if code.startswith(("8", "4", "920")) else "sz")
    sym = f"{prefix}{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,2,qfq"
    try:
        r = session.get(url, timeout=5)
        d = r.json().get("data", {}).get(sym, {})
        bars = d.get("qfqday", []) or d.get("day", [])
        if bars:
            for b in reversed(bars):
                if b[0] == TARGET_DATE_DASH:
                    return code, b
        return code, None
    except Exception:
        return code, None


def main():
    started = time.time()
    latest = discover_latest_cache(START_TEXT)
    all_codes = sorted(latest.keys())
    print(f"Total codes in cache: {len(all_codes)}")

    # Filter codes that already have 20260917
    codes_to_fetch = [
        c for c in all_codes
        if not cache_path_for_history(c, START_TEXT, TARGET_DATE_COMPACT, adjust=DATA_ADJUST).exists()
    ]
    print(f"Codes needing 20260917: {len(codes_to_fetch)}")

    appended = 0
    failed = 0
    skipped = 0

    batch_size = 500
    for offset in range(0, len(codes_to_fetch), batch_size):
        chunk = codes_to_fetch[offset : offset + batch_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=35) as ex:
            results = list(ex.map(fetch_bar_917, chunk))

        for code, bar in results:
            if not bar:
                skipped += 1
                continue
            try:
                open_p = float(bar[1])
                close_p = float(bar[2])
                high_p = float(bar[3])
                low_p = float(bar[4])
                vol = float(bar[5])
                if vol <= 0 or close_p <= 0:
                    skipped += 1
                    continue
                approx_amount = round(((open_p + high_p + low_p + close_p) / 4.0) * vol * 100.0, 2)

                end_text, prev_path = latest[code]
                prev_df = pd.read_csv(prev_path)
                prev_df = prev_df[prev_df["date"].astype(str).str[:10] != TARGET_DATE_DASH].copy()

                new_row = {
                    "date": TARGET_DATE_DASH,
                    "open": open_p,
                    "close": close_p,
                    "high": high_p,
                    "low": low_p,
                    "volume": vol,
                    "turnover": np.nan,
                    "amount": approx_amount,
                }
                merged = pd.concat([prev_df, pd.DataFrame([new_row])], ignore_index=True)
                merged = merged.drop_duplicates(subset=["date"], keep="last").sort_values("date")

                out_path = cache_path_for_history(code, START_TEXT, TARGET_DATE_COMPACT, adjust=DATA_ADJUST)
                merged.to_csv(out_path, index=False)
                appended += 1
            except Exception as e:
                failed += 1

        done = min(offset + batch_size, len(codes_to_fetch))
        elapsed = time.time() - started
        print(f"Progress {done}/{len(codes_to_fetch)}: appended={appended} skipped={skipped} failed={failed} ({elapsed:.1f}s)")

    print(f"\nAll done: appended={appended}, skipped={skipped}, failed={failed}, total_time={time.time()-started:.1f}s")


if __name__ == "__main__":
    main()
