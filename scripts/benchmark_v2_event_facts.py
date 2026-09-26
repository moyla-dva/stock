"""Benchmark full V2 facts versus the event-focused facts profile.

The script is intentionally offline by default. It can run against synthetic
OHLCV data, a local CSV, or an existing local history cache entry.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.c_signal_v2_facts import (
    build_c_signal_v2_event_facts,
    build_c_signal_v2_facts,
)
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.data_fetcher import (
    _cached_history_candidates,
    beijing_now,
    read_history_cache_file,
)
from stock_analyzer.events import build_v2_signal_events
from stock_analyzer.versioning import DATA_ADJUST


def _stable_float(value, precision=6):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(number):
        return "nan"
    return round(number, precision)


def stable_event_signature(events, precision=6):
    """Return a deterministic event signature for semantic equality checks."""
    return [
        (
            event.key,
            event.group,
            event.date,
            _stable_float(event.coord_price, precision=precision),
            _stable_float(event.price, precision=precision),
            event.reason,
            event.value,
        )
        for event in events
    ]


def _time_events(frame, *, lookback, repeat, facts_builder):
    durations = []
    events = []
    for _ in range(max(1, int(repeat))):
        started = time.perf_counter()
        events = build_v2_signal_events(
            frame,
            lookback=lookback,
            facts_builder=facts_builder,
        )
        durations.append(time.perf_counter() - started)
    return {
        "events": events,
        "avg_seconds": statistics.fmean(durations),
        "min_seconds": min(durations),
        "max_seconds": max(durations),
    }


def benchmark_event_facts(frame, *, lookback=60, repeat=3):
    """Compare event output and timings for full facts and event facts."""
    if frame is None or frame.empty:
        raise ValueError("benchmark frame is empty")

    full = _time_events(
        frame,
        lookback=lookback,
        repeat=repeat,
        facts_builder=build_c_signal_v2_facts,
    )
    event_profile = _time_events(
        frame,
        lookback=lookback,
        repeat=repeat,
        facts_builder=build_c_signal_v2_event_facts,
    )
    full_signature = stable_event_signature(full["events"])
    event_signature = stable_event_signature(event_profile["events"])
    event_avg = event_profile["avg_seconds"]
    speedup = full["avg_seconds"] / event_avg if event_avg > 0 else None
    return {
        "lookback": lookback,
        "repeat": max(1, int(repeat)),
        "event_count": len(event_profile["events"]),
        "zero_diff": full_signature == event_signature,
        "speedup": speedup,
        "full_facts": {
            "avg_seconds": full["avg_seconds"],
            "min_seconds": full["min_seconds"],
            "max_seconds": full["max_seconds"],
        },
        "event_facts": {
            "avg_seconds": event_profile["avg_seconds"],
            "min_seconds": event_profile["min_seconds"],
            "max_seconds": event_profile["max_seconds"],
        },
        "full_signature": full_signature,
        "event_signature": event_signature,
    }


def _synthetic_raw_frame(rows):
    rows = max(30, int(rows))
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = []
    price = 10.0
    for idx in range(rows):
        drift = 0.018 if idx > rows * 0.45 else -0.012
        wave = math.sin(idx / 5.0) * 0.08
        price = max(3.0, price + drift + wave)
        close.append(round(price, 3))
    open_ = [round(value * (0.995 + (idx % 5) * 0.001), 3) for idx, value in enumerate(close)]
    high = [round(max(o, c) + 0.18 + (idx % 4) * 0.015, 3) for idx, (o, c) in enumerate(zip(open_, close))]
    low = [round(min(o, c) - 0.16 - (idx % 3) * 0.012, 3) for idx, (o, c) in enumerate(zip(open_, close))]
    volume = [1000 + (idx % 13) * 80 + max(0, idx - rows // 2) * 6 for idx in range(rows)]
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _prepare_frame(raw):
    frame = prepare_analysis_frame(raw, fill_initial_ma20=False)
    if frame is None or frame.empty:
        raise ValueError("unable to prepare benchmark frame")
    return frame


def _load_csv_frame(path):
    return _prepare_frame(pd.read_csv(path))


def _compact_date_text(value):
    return pd.to_datetime(value).strftime("%Y%m%d")


def _load_cached_code_frame(code, *, start_date=None, days=420, adjust=DATA_ADJUST):
    code = normalize_code(code)
    if not code:
        raise ValueError("invalid stock code")
    end = beijing_now()
    start_text = _compact_date_text(start_date) if start_date else (end - timedelta(days=int(days))).strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    candidates = _cached_history_candidates(code, start_text, end_text, adjust=adjust)
    if not candidates:
        raise FileNotFoundError(
            f"no local history cache for {code}, start={start_text}, adjust={adjust or 'none'}"
        )
    raw, _ = read_history_cache_file(candidates[0], code)
    return _prepare_frame(raw), str(candidates[0])


def _load_frame(args):
    if args.csv:
        return _load_csv_frame(args.csv), str(args.csv)
    if args.code:
        return _load_cached_code_frame(
            args.code,
            start_date=args.start_date,
            days=args.days,
            adjust=args.adjust,
        )
    return _prepare_frame(_synthetic_raw_frame(args.rows)), f"synthetic:{args.rows}"


def _without_signatures(result):
    compact = dict(result)
    compact.pop("full_signature", None)
    compact.pop("event_signature", None)
    return compact


def _format_seconds(value):
    return f"{value:.4f}s"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="Local OHLCV CSV to benchmark.")
    parser.add_argument("--code", help="Stock code. Reads an existing local history cache entry only.")
    parser.add_argument("--start-date", help="Cache start date for --code, e.g. 2025-01-01.")
    parser.add_argument("--days", type=int, default=420, help="Fallback cache window when --start-date is omitted.")
    parser.add_argument("--adjust", default=DATA_ADJUST, help="History adjust key for local cache lookup.")
    parser.add_argument("--rows", type=int, default=180, help="Synthetic OHLCV row count.")
    parser.add_argument("--lookback", type=int, default=60, help="Event lookback window.")
    parser.add_argument("--repeat", type=int, default=3, help="Timing repetitions per facts builder.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON output.")
    parser.add_argument("--allow-diff", action="store_true", help="Do not fail when event signatures differ.")
    args = parser.parse_args(argv)

    frame, source = _load_frame(args)
    result = benchmark_event_facts(frame, lookback=args.lookback, repeat=args.repeat)
    output = {"source": source, "rows": len(frame), **result}

    if args.json:
        print(json.dumps(_without_signatures(output), ensure_ascii=False, indent=2))
    else:
        speedup = output["speedup"]
        speedup_text = f"{speedup:.2f}x" if speedup is not None else "-"
        print("V2 event facts benchmark")
        print(f"source: {source}")
        print(f"rows: {len(frame)}, lookback: {args.lookback}, repeat: {max(1, int(args.repeat))}")
        print(f"events: {output['event_count']}, zero_diff: {output['zero_diff']}")
        print(f"full facts avg:  {_format_seconds(output['full_facts']['avg_seconds'])}")
        print(f"event facts avg: {_format_seconds(output['event_facts']['avg_seconds'])}")
        print(f"speedup: {speedup_text}")

    if not result["zero_diff"] and not args.allow_diff:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
