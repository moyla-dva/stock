#!/usr/bin/env python3
"""Rebuild current scan snapshots from local daily-history cache."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stock_analyzer.analysis import prepare_analysis_frame
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.data_fetcher import (
    CACHE_DIR as HISTORY_CACHE_DIR,
    _cached_history_candidates,
    cache_path_for_history,
    read_history_cache_file,
)
from stock_analyzer.scan_snapshot import (
    build_scan_snapshot,
    is_current_strategy_snapshot,
    normalize_snapshot_day,
    read_scan_snapshot,
    read_scan_snapshot_file,
    scan_snapshot_day_files,
    write_scan_snapshot,
)
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE, SCAN_STRATEGY_VERSION

PROFILES_CACHE_FILE = PROJECT_ROOT / ".cache" / "catalog" / "stock_profiles.json"
_PROFILE_INDEX = None


def _load_profiles():
    global _PROFILE_INDEX
    if _PROFILE_INDEX is None:
        try:
            data = json.loads(PROFILES_CACHE_FILE.read_text(encoding="utf-8"))
            _PROFILE_INDEX = data if isinstance(data, dict) else {}
        except Exception:
            _PROFILE_INDEX = {}
    return _PROFILE_INDEX


def discover_cache_codes(start_date: str, snapshot_day: str) -> list[str]:
    """Return codes that already have a history cache file for the snapshot day."""
    start_text = _start_key(start_date)
    end_text = normalize_snapshot_day(snapshot_day)
    adjust_key = DATA_ADJUST or "none"
    codes = set()
    for path in HISTORY_CACHE_DIR.glob(f"*_{start_text}_{end_text}_{adjust_key}.csv"):
        parts = path.stem.split("_")
        if len(parts) == 4 and len(parts[0]) == 6 and parts[0].isdigit():
            codes.add(parts[0])
    for path in HISTORY_CACHE_DIR.glob(f"*_{start_text}_{adjust_key}.csv"):
        parts = path.stem.split("_")
        if len(parts) != 3 or len(parts[0]) != 6 or not parts[0].isdigit():
            continue
        try:
            frame = pd.read_csv(path, usecols=lambda column: column == "date")
            dates = pd.to_datetime(frame.get("date"), errors="coerce").dropna()
        except Exception:
            continue
        if not dates.empty and dates.max().strftime("%Y%m%d") >= end_text:
            codes.add(parts[0])
    return sorted(codes)



def _start_key(start_date: str) -> str:
    return str(start_date or "default").replace("-", "")


def _history_cache_path(code: str, start_date: str, snapshot_day: str) -> Path:
    """Resolve the history cache file: canonical name first, then newest legacy file.

    缓存键重构后存量文件仍是旧命名（{code}_{start}_{end}_{adjust}.csv），
    读取必须回退到 legacy 候选并取数据最新的一份。
    """
    start_text = _start_key(start_date)
    end_text = normalize_snapshot_day(snapshot_day)
    candidates = _cached_history_candidates(
        code, start_text, end_text, adjust=DATA_ADJUST
    )
    if candidates:
        return candidates[0]
    return cache_path_for_history(code, start_text, end_text, adjust=DATA_ADJUST)


def _data_date(frame) -> str:
    if frame is None or frame.empty or "date" not in frame.columns:
        return ""
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return dates.max().strftime("%Y-%m-%d") if not dates.empty else ""


def _rebuild_one(args: tuple[str, str, str, str | None, bool]) -> dict:
    path_text, start_date, snapshot_day, required_data_date, force_current = args
    path = Path(path_text)
    snapshot = read_scan_snapshot_file(path)
    if not snapshot:
        return {"status": "invalid_snapshot", "path": path.name}
    if (
        is_current_strategy_snapshot(snapshot)
        and not force_current
        and (not required_data_date or snapshot.get("data_date") == required_data_date)
    ):
        return {"status": "skipped_current", "code": snapshot.get("code") or path.name[:6]}

    code = normalize_code(snapshot.get("code")) or normalize_code(path.name)
    if not code:
        return {"status": "invalid_code", "path": path.name}

    cache_path = _history_cache_path(code, start_date, snapshot_day)
    if not cache_path.exists():
        return {"status": "missing_history_cache", "code": code, "cache": cache_path.name}

    try:
        raw, _ = read_history_cache_file(cache_path, code)
        with contextlib.redirect_stdout(io.StringIO()):
            frame = prepare_analysis_frame(raw, fill_initial_ma20=False)
    except Exception as exc:
        return {"status": "failed", "code": code, "error": str(exc)}

    actual_data_date = _data_date(frame)
    if required_data_date and actual_data_date != required_data_date:
        return {
            "status": "stale_data",
            "code": code,
            "data_date": actual_data_date,
            "required_data_date": required_data_date,
        }
    if frame is None or frame.empty:
        return {"status": "empty_frame", "code": code}

    rebuilt = build_scan_snapshot(
        code,
        snapshot.get("name") or code,
        frame,
        snapshot_day=snapshot_day,
        sector=snapshot.get("sector"),
        concepts=snapshot.get("concepts") or [],
    )
    write_scan_snapshot(rebuilt, start_date=start_date, snapshot_day=snapshot_day)
    return {
        "status": "rebuilt",
        "code": code,
        "data_date": rebuilt.get("data_date"),
        "strategy_version": rebuilt.get("strategy_version"),
    }


def _build_from_cache_one(args: tuple[str, str, str, str | None, bool]) -> dict:
    """Build a snapshot directly from the history cache for one code."""
    code, start_date, snapshot_day, required_data_date, force_current = args
    cache_path = _history_cache_path(code, start_date, snapshot_day)
    if not cache_path.exists():
        return {"status": "missing_history_cache", "code": code, "cache": cache_path.name}

    if not force_current:
        try:
            existing = read_scan_snapshot(code, start_date=start_date, snapshot_day=snapshot_day)
        except Exception:
            existing = None
        if (
            existing
            and is_current_strategy_snapshot(existing)
            and (not required_data_date or existing.get("data_date") == required_data_date)
        ):
            return {"status": "skipped_current", "code": code}

    profile = _load_profiles().get(code) or {}
    if not isinstance(profile, dict):
        profile = {}
    try:
        raw, _ = read_history_cache_file(cache_path, code)
        with contextlib.redirect_stdout(io.StringIO()):
            frame = prepare_analysis_frame(raw, fill_initial_ma20=False)
    except Exception as exc:
        return {"status": "failed", "code": code, "error": str(exc)}
    if frame is None or frame.empty:
        return {"status": "empty_frame", "code": code}

    actual_data_date = _data_date(frame)
    if required_data_date and actual_data_date != required_data_date:
        return {"status": "stale_data", "code": code, "data_date": actual_data_date}

    rebuilt = build_scan_snapshot(
        code,
        profile.get("name") or code,
        frame,
        snapshot_day=snapshot_day,
        sector=profile.get("sector"),
        concepts=profile.get("concepts") or [],
    )
    write_scan_snapshot(rebuilt, start_date=start_date, snapshot_day=snapshot_day)
    return {
        "status": "rebuilt",
        "code": code,
        "data_date": rebuilt.get("data_date"),
        "strategy_version": rebuilt.get("strategy_version"),
    }


def rebuild_snapshots_from_history_cache(
    *,
    snapshot_day: str,
    start_date: str = DATA_START_DATE,
    data_date: str | None = None,
    workers: int | None = None,
    limit: int | None = None,
    force_current: bool = False,
    progress_every: int = 250,
    codes_from_cache: bool = False,
) -> dict:
    started = time.perf_counter()
    snapshot_day = normalize_snapshot_day(snapshot_day)
    if not snapshot_day:
        raise ValueError("snapshot_day must be YYYYMMDD or YYYY-MM-DD")

    if codes_from_cache:
        codes = discover_cache_codes(start_date, snapshot_day)
        if limit:
            codes = codes[:limit]
        total = len(codes)
        tasks = [
            (code, start_date, snapshot_day, data_date, force_current)
            for code in codes
        ]
        worker = _build_from_cache_one
    else:
        paths = scan_snapshot_day_files(start_date=start_date, snapshot_day=snapshot_day)
        if limit:
            paths = paths[:limit]
        total = len(paths)
        tasks = [
            (str(path), start_date, snapshot_day, data_date, force_current)
            for path in paths
        ]
        worker = _rebuild_one

    workers = max(1, int(workers or min(8, os.cpu_count() or 4)))
    counts: dict[str, int] = {}
    samples: dict[str, list[dict]] = {}

    completed = 0
    if workers == 1:
        iterator = (worker(task) for task in tasks)
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        futures = [pool.submit(worker, task) for task in tasks]
        iterator = (future.result() for future in as_completed(futures))

    try:
        for item in iterator:
            status = item.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
            if status != "rebuilt":
                bucket = samples.setdefault(status, [])
                if len(bucket) < 10:
                    bucket.append(item)
            completed += 1
            if progress_every and completed % progress_every == 0:
                elapsed = time.perf_counter() - started
                print(
                    f"progress {completed}/{total} elapsed={elapsed:.1f}s rebuilt={counts.get('rebuilt', 0)}",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if workers != 1:
            pool.shutdown(wait=True)

    return {
        "snapshot_day": snapshot_day,
        "start_date": start_date,
        "required_data_date": data_date or "",
        "strategy_version": SCAN_STRATEGY_VERSION,
        "history_cache_dir": str(HISTORY_CACHE_DIR),
        "total": total,
        "workers": workers,
        "counts": counts,
        "samples": samples,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-day", required=True)
    parser.add_argument("--start-date", default=DATA_START_DATE)
    parser.add_argument("--data-date", default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force-current", action="store_true")
    parser.add_argument("--progress-every", type=int, default=250)
    parser.add_argument("--json-out", default="")
    parser.add_argument(
        "--codes-from-cache",
        action="store_true",
        help="build snapshots for every code that has a history cache file for snapshot-day",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = rebuild_snapshots_from_history_cache(
        snapshot_day=args.snapshot_day,
        start_date=args.start_date,
        data_date=args.data_date,
        workers=args.workers,
        limit=args.limit,
        force_current=args.force_current,
        progress_every=args.progress_every,
        codes_from_cache=args.codes_from_cache,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if not report["counts"].get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
