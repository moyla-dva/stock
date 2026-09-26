"""Evaluate persisted candidate ranks against later cached daily bars.

This is a read-only event study. It does not model orders, fees, slippage, limit
locks, or portfolio construction and therefore must not be described as a
tradable backtest.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stock_analyzer.data_fetcher import CACHE_DIR, read_history_cache_file
from stock_analyzer.scan_index_store import DEFAULT_SCAN_INDEX_PATH, ScanIndexStore
from stock_analyzer.scan_rank_context import RANKING_POLICY_VERSION
from stock_analyzer.versioning import DATA_START_DATE, SCAN_STRATEGY_VERSION


DEFAULT_HORIZONS = (1, 3, 5, 10)
DEFAULT_BUCKETS = ((1, 10), (11, 30), (31, 100))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_SCAN_INDEX_PATH)
    parser.add_argument("--history-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--snapshot-day", action="append", default=[])
    parser.add_argument("--from-day", default="")
    parser.add_argument("--to-day", default="")
    parser.add_argument("--pool", default="opportunity")
    parser.add_argument("--strategy-version", default=SCAN_STRATEGY_VERSION)
    parser.add_argument("--start-date", default=DATA_START_DATE)
    parser.add_argument("--max-rank", type=int, default=100)
    parser.add_argument("--horizons", type=int, nargs="+", default=DEFAULT_HORIZONS)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _day_key(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else ""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _history_path(history_dir: Path, code: str, start_key: str) -> Path | None:
    canonical = history_dir / f"{code}_{start_key}_qfq.csv"
    if canonical.is_file():
        return canonical
    candidates = sorted(
        history_dir.glob(f"{code}_{start_key}_*_qfq.csv"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    return candidates[0] if candidates else None


def evaluate_candidate_frame(
    frame: pd.DataFrame,
    *,
    as_of: str,
    horizons: Iterable[int],
) -> dict[int, dict[str, Any]]:
    """Return next-open event-study metrics for one candidate."""

    required = {"date", "open", "close", "high", "low"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        return {}
    data = frame.loc[:, ["date", "open", "close", "high", "low"]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    cutoff = pd.to_datetime(as_of, errors="coerce")
    if pd.isna(cutoff):
        return {}
    entry_rows = data.index[data["date"] > cutoff].tolist()
    if not entry_rows:
        return {}
    entry_index = int(entry_rows[0])
    entry_price = _finite(data.at[entry_index, "open"])
    if entry_price is None or entry_price <= 0:
        return {}

    output: dict[int, dict[str, Any]] = {}
    for raw_horizon in horizons:
        horizon = int(raw_horizon)
        if horizon <= 0:
            continue
        exit_index = entry_index + horizon - 1
        if exit_index >= len(data):
            continue
        exit_price = _finite(data.at[exit_index, "close"])
        highs = pd.to_numeric(
            data.loc[entry_index:exit_index, "high"], errors="coerce"
        ).dropna()
        lows = pd.to_numeric(
            data.loc[entry_index:exit_index, "low"], errors="coerce"
        ).dropna()
        if exit_price is None or highs.empty or lows.empty:
            continue
        output[horizon] = {
            "entry_date": data.at[entry_index, "date"].date().isoformat(),
            "exit_date": data.at[exit_index, "date"].date().isoformat(),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": (exit_price / entry_price - 1.0) * 100.0,
            "mfe_pct": (float(highs.max()) / entry_price - 1.0) * 100.0,
            "mae_pct": (float(lows.min()) / entry_price - 1.0) * 100.0,
        }
    return output


def _rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for position in order[index:end]:
            ranks[position] = rank
        index = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    left_scale = sum((value - left_mean) ** 2 for value in left)
    right_scale = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_scale * right_scale)
    return numerator / denominator if denominator else None


def _summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [
        value
        for row in rows
        if (value := _finite(row.get("return_pct"))) is not None
    ]
    mfes = [
        value
        for row in rows
        if (value := _finite(row.get("mfe_pct"))) is not None
    ]
    maes = [
        value
        for row in rows
        if (value := _finite(row.get("mae_pct"))) is not None
    ]
    return {
        "evaluated_count": len(returns),
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 4)
        if returns else None,
        "mean_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "median_return_pct": round(statistics.median(returns), 4) if returns else None,
        "mean_mfe_pct": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "mean_mae_pct": round(sum(maes) / len(maes), 4) if maes else None,
    }


def _available_days(store: ScanIndexStore, args: argparse.Namespace) -> list[str]:
    explicit = {_day_key(day) for day in args.snapshot_day}
    explicit.discard("")
    with store._connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT snapshot_day
            FROM candidate_summaries
            WHERE strategy_version = ? AND start_key = ? AND pool = ?
            ORDER BY snapshot_day
            """,
            (args.strategy_version, args.start_key, args.pool),
        ).fetchall()
    days = [str(row[0]) for row in rows]
    if explicit:
        days = [day for day in days if day in explicit]
    from_day = _day_key(args.from_day)
    to_day = _day_key(args.to_day)
    if from_day:
        days = [day for day in days if day >= from_day]
    if to_day:
        days = [day for day in days if day <= to_day]
    return days


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    store = ScanIndexStore(args.db.expanduser().resolve())
    start_key = _day_key(args.start_date)
    if not start_key:
        raise ValueError("start_date must use YYYY-MM-DD or YYYYMMDD")
    args.start_key = start_key
    max_rank = max(1, min(int(args.max_rank), 1000))
    horizons = sorted({int(value) for value in args.horizons if int(value) > 0})
    history_dir = args.history_dir.expanduser().resolve()
    days = _available_days(store, args)
    observations: list[dict[str, Any]] = []
    day_reports = []
    history_cache: dict[str, tuple[pd.DataFrame | None, dict[str, Any]]] = {}

    for day in days:
        page = store.query_candidate_page(
            pool=args.pool,
            snapshot_day=day,
            strategy_version=args.strategy_version,
            rank_context_strategy_version=args.strategy_version,
            start_key=start_key,
            rank_mode="contextual",
            limit=max_rank,
        )
        ranking = page["ranking"]
        if ranking["mode"] != "contextual":
            day_reports.append({
                "snapshot_day": day,
                "status": "skipped",
                "reason": ranking.get("fallback_reason") or "contextual_rank_unavailable",
                "candidate_count": int(page.get("count") or 0),
            })
            continue

        evaluated_candidates = 0
        for rank, candidate in enumerate(page["results"], start=1):
            code = str(candidate.get("code") or "")
            if code not in history_cache:
                path = _history_path(history_dir, code, start_key)
                if path is None:
                    history_cache[code] = (None, {})
                else:
                    try:
                        history_cache[code] = read_history_cache_file(path, code)
                    except (OSError, ValueError):
                        history_cache[code] = (None, {})
            frame, meta = history_cache[code]
            outcomes = evaluate_candidate_frame(
                frame,
                as_of=str(candidate.get("as_of") or ""),
                horizons=horizons,
            )
            if outcomes:
                evaluated_candidates += 1
            for horizon, outcome in outcomes.items():
                observations.append({
                    "snapshot_day": day,
                    "rank": rank,
                    "code": code,
                    "name": str(candidate.get("name") or ""),
                    "as_of": str(candidate.get("as_of") or ""),
                    "horizon": horizon,
                    "rank_score": (candidate.get("rank_context") or {}).get("priority_score"),
                    "history_data_source": str(meta.get("data_source") or "unknown"),
                    "history_data_revision": str(meta.get("data_revision") or "unknown"),
                    **outcome,
                })
        day_reports.append({
            "snapshot_day": day,
            "status": "evaluated",
            "context_revision": ranking.get("context_revision") or "",
            "candidate_count": int(page.get("count") or 0),
            "requested_rank_count": len(page["results"]),
            "candidates_with_any_outcome": evaluated_candidates,
        })

    by_horizon: dict[str, Any] = {}
    for horizon in horizons:
        horizon_rows = [row for row in observations if row["horizon"] == horizon]
        bucket_reports = {}
        for lower, upper in DEFAULT_BUCKETS:
            if lower > max_rank:
                continue
            bucket_rows = [
                row for row in horizon_rows if lower <= int(row["rank"]) <= min(upper, max_rank)
            ]
            bucket_reports[f"{lower}-{min(upper, max_rank)}"] = _summary(bucket_rows)
        correlations = []
        rows_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in horizon_rows:
            rows_by_day[str(row["snapshot_day"])].append(row)
        for day_rows in rows_by_day.values():
            if len(day_rows) < 2:
                continue
            rank_values = [float(row["rank"]) for row in day_rows]
            return_values = [float(row["return_pct"]) for row in day_rows]
            correlation = _pearson(_rankdata(rank_values), _rankdata(return_values))
            if correlation is not None:
                correlations.append(correlation)
        by_horizon[str(horizon)] = {
            "all_ranks": _summary(horizon_rows),
            "rank_buckets": bucket_reports,
            "mean_daily_spearman_rank_vs_return": round(
                sum(correlations) / len(correlations), 4
            ) if correlations else None,
            "correlation_day_count": len(correlations),
        }

    return {
        "report_type": "candidate_rank_event_study",
        "evidence_level": "historical event study; not a tradable backtest",
        "strategy_version": args.strategy_version,
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "pool": args.pool,
        "entry_model": "next_session_open",
        "exit_model": "close_on_horizon_session_including_entry_session",
        "fees_and_slippage": "not_modeled",
        "limit_lock_and_tradability_filter": "not_modeled",
        "history_adjustment": "qfq",
        "max_rank": max_rank,
        "horizons": horizons,
        "snapshot_days_requested": days,
        "day_reports": day_reports,
        "summary_by_horizon": by_horizon,
        "observation_count": len(observations),
        "observations": observations,
    }


def main() -> int:
    args = _args()
    report = run_audit(args)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
