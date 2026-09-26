#!/usr/bin/env python3
"""Measure legacy C experience facts against later returns.

The script rebuilds the signal-day frame from local daily-history cache and
evaluates the later close from the same cache file. It does not fetch network
data and does not use scan snapshots as the source of facts, so the signal
side stays anchored to the requested signal date.
"""

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
from stock_analyzer.c_signal_v2 import build_c_signal_v2_state, build_c_signal_v2_state_components
from stock_analyzer.code_utils import code_from_cache_filename, normalize_code
from stock_analyzer.data_fetcher import CACHE_DIR as HISTORY_CACHE_DIR, read_history_cache_file
from stock_analyzer.scan_snapshot import normalize_snapshot_day
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE


LEGACY_BUCKETS = (
    "legacy_low_risk_pullback",
    "legacy_bottom_repair_hint",
    "legacy_risk_hint",
)


def _date_text(value: str) -> str:
    text = str(value or "").replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        raise ValueError("date must be YYYY-MM-DD or YYYYMMDD")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _start_key(start_date: str) -> str:
    return str(start_date or "default").replace("-", "")


def _parse_pair(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    for separator in ("->", ":", ","):
        if separator in text:
            left, right = text.split(separator, 1)
            return _date_text(left), _date_text(right)
    raise ValueError("--pair must be SIGNAL_DATE:OUTCOME_DATE")


def discover_history_cache_paths(*, start_date: str, outcome_date: str) -> list[Path]:
    start_text = _start_key(start_date)
    outcome_text = normalize_snapshot_day(outcome_date)
    adjust_key = DATA_ADJUST or "none"
    paths = []
    for path in HISTORY_CACHE_DIR.glob(f"*_{start_text}_{outcome_text}_{adjust_key}.csv"):
        code = path.name.split("_", 1)[0]
        if normalize_code(code):
            paths.append(path)
    return sorted(paths)


def _close_on_or_before(frame: pd.DataFrame, date_text: str) -> tuple[str, float] | tuple[None, None]:
    eligible = frame[frame["date"] <= pd.Timestamp(date_text)]
    if eligible.empty:
        return None, None
    row = eligible.iloc[-1]
    close = row.get("close")
    try:
        return row["date"].strftime("%Y-%m-%d"), float(close)
    except Exception:
        return None, None


def _summary_stats(rows: list[dict]) -> dict:
    returns = [float(row["return_pct"]) for row in rows if row.get("return_pct") is not None]
    if not returns:
        return {
            "count": 0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "win_rate_pct": None,
            "up": 0,
            "flat": 0,
            "down": 0,
        }
    series = pd.Series(returns)
    up = int((series > 0).sum())
    flat = int((series == 0).sum())
    down = int((series < 0).sum())
    return {
        "count": int(len(returns)),
        "avg_return_pct": round(float(series.mean()), 3),
        "median_return_pct": round(float(series.median()), 3),
        "win_rate_pct": round(up * 100 / len(returns), 2),
        "up": up,
        "flat": flat,
        "down": down,
    }


def _bucket_report(rows: list[dict], key: str) -> dict:
    matched = [row for row in rows if key in row.get("legacy_keys", [])]
    by_signal = {}
    by_permission = {}
    by_candidate = {}
    for row in matched:
        by_signal[row.get("v2_signal") or "-"] = by_signal.get(row.get("v2_signal") or "-", 0) + 1
        by_permission[row.get("v2_permission") or "-"] = by_permission.get(row.get("v2_permission") or "-", 0) + 1
        candidate = row.get("candidate_substate") or "-"
        by_candidate[candidate] = by_candidate.get(candidate, 0) + 1
    samples = sorted(
        matched,
        key=lambda item: item.get("return_pct") if item.get("return_pct") is not None else -999,
        reverse=True,
    )[:8]
    return {
        **_summary_stats(matched),
        "by_v2_signal": dict(sorted(by_signal.items())),
        "by_v2_permission": dict(sorted(by_permission.items())),
        "by_candidate_substate": dict(sorted(by_candidate.items())),
        "candidate_substate_stats": _group_stats(matched, "candidate_substate"),
        "top_samples": [
            {
                "code": item["code"],
                "signal_close": item["signal_close"],
                "outcome_close": item["outcome_close"],
                "return_pct": item["return_pct"],
                "v2_signal": item.get("v2_signal"),
                "v2_permission": item.get("v2_permission"),
                "candidate_substate": item.get("candidate_substate"),
            }
            for item in samples
        ],
    }


def _group_stats(rows: list[dict], field: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row.get(field) or "-")
        groups.setdefault(key, []).append(row)
    stats = {}
    for key, items in groups.items():
        stats[key] = _summary_stats(items)
    return dict(sorted(stats.items(), key=lambda item: item[1]["count"], reverse=True))


def _summary_from_summaries(items: list[dict]) -> dict:
    count = sum(int(item.get("count") or 0) for item in items)
    if not count:
        return {
            "count": 0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "win_rate_pct": None,
            "up": 0,
            "flat": 0,
            "down": 0,
        }
    up = sum(int(item.get("up") or 0) for item in items)
    flat = sum(int(item.get("flat") or 0) for item in items)
    down = sum(int(item.get("down") or 0) for item in items)
    weighted_avg = sum((item.get("avg_return_pct") or 0) * int(item.get("count") or 0) for item in items) / count
    return {
        "count": count,
        "avg_return_pct": round(weighted_avg, 3),
        "median_return_pct": None,
        "win_rate_pct": round(up * 100 / count, 2),
        "up": up,
        "flat": flat,
        "down": down,
    }


def evaluate_one_path(args: tuple[str, str, str]) -> dict:
    path_text, signal_date, outcome_date = args
    path = Path(path_text)
    code = code_from_cache_filename(path.name)
    if not code:
        return {"status": "invalid_code", "path": path.name}
    try:
        normalized, _ = read_history_cache_file(path, code)
    except Exception as exc:
        return {"status": "read_failed", "code": code, "error": str(exc)}
    if normalized is None or normalized.empty or "date" not in normalized.columns:
        return {"status": "empty", "code": code}
    normalized = normalized.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    signal_actual_date, signal_close = _close_on_or_before(normalized, signal_date)
    outcome_actual_date, outcome_close = _close_on_or_before(normalized, outcome_date)
    if signal_close is None or outcome_close is None:
        return {"status": "missing_date", "code": code}
    signal_raw = normalized[normalized["date"] <= pd.Timestamp(signal_actual_date)]
    if len(signal_raw) < 30:
        return {"status": "insufficient_history", "code": code}

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            frame = prepare_analysis_frame(signal_raw, fill_initial_ma20=False)
        components = build_c_signal_v2_state_components(frame) or {}
        facts = components.get("facts") or {}
        legacy = facts.get("legacy_experience") or {}
        state = build_c_signal_v2_state(frame, components=components)
    except Exception as exc:
        return {"status": "analysis_failed", "code": code, "error": str(exc)}

    legacy_items = legacy.get("items") if isinstance(legacy.get("items"), list) else []
    return_pct = round((outcome_close / signal_close - 1) * 100, 3) if signal_close else None
    return {
        "status": "evaluated",
        "code": code,
        "signal_date": signal_actual_date,
        "outcome_date": outcome_actual_date,
        "signal_close": round(signal_close, 3),
        "outcome_close": round(outcome_close, 3),
        "return_pct": return_pct,
        "legacy_keys": [item.get("key") for item in legacy_items if item.get("key")],
        "legacy_labels": [item.get("label") for item in legacy_items if item.get("label")],
        "legacy_grants_permission": bool(legacy.get("grants_permission")),
        "v2_signal": state.get("signal"),
        "v2_state": state.get("state"),
        "v2_permission": state.get("permission"),
        "candidate_substate": state.get("candidate_substate"),
    }


def build_report(rows: list[dict], *, signal_date: str, outcome_date: str, elapsed_seconds: float, counts: dict) -> dict:
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    with_legacy = [row for row in evaluated if row.get("legacy_keys")]
    without_legacy = [row for row in evaluated if not row.get("legacy_keys")]
    return {
        "version": 1,
        "source": "legacy_experience_ablation_p21b",
        "signal_date": signal_date,
        "outcome_date": outcome_date,
        "counts": counts,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "baseline": _summary_stats(evaluated),
        "legacy_any": _summary_stats(with_legacy),
        "legacy_none": _summary_stats(without_legacy),
        "v2_candidate_substate": _group_stats(evaluated, "candidate_substate"),
        "buckets": {key: _bucket_report(evaluated, key) for key in LEGACY_BUCKETS},
        "permission_leak_count": sum(1 for row in with_legacy if row.get("legacy_grants_permission")),
    }


def write_markdown_report(report: dict, path: Path) -> None:
    def fmt(value, suffix=""):
        return "-" if value is None else f"{value}{suffix}"

    lines = [
        "# P21-B 旧 C 经验素材消融报告",
        "",
        f"> 信号日：{report['signal_date']}  ",
        f"> 结果日：{report['outcome_date']}  ",
        f"> 来源：本地日线缓存按信号日重新切片计算，旧 C 素材不授予许可。",
        "",
        "## 1. 总览",
        "",
        "| 样本 | 数量 | 平均收益 | 中位收益 | 胜率 | 上/平/下 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, key in (("全市场可评估", "baseline"), ("命中旧 C 素材", "legacy_any"), ("未命中旧 C 素材", "legacy_none")):
        item = report[key]
        lines.append(
            f"| {label} | {item['count']} | {fmt(item['avg_return_pct'], '%')} | "
            f"{fmt(item['median_return_pct'], '%')} | {fmt(item['win_rate_pct'], '%')} | "
            f"{item['up']}/{item['flat']}/{item['down']} |"
        )
    lines.extend([
        "",
        "## 2. 分素材表现",
        "",
        "| 素材 | 数量 | 平均收益 | 中位收益 | 胜率 | 主 V2 信号 | 主许可 |",
        "|---|---:|---:|---:|---:|---|---|",
    ])
    labels = {
        "legacy_low_risk_pullback": "旧 C 低风险回踩",
        "legacy_bottom_repair_hint": "旧 C 底部修复",
        "legacy_risk_hint": "旧 C 风险提示",
    }
    for key, item in report["buckets"].items():
        signal_text = ", ".join(f"{k}:{v}" for k, v in item["by_v2_signal"].items()) or "-"
        permission_text = ", ".join(f"{k}:{v}" for k, v in item["by_v2_permission"].items()) or "-"
        lines.append(
            f"| {labels.get(key, key)} | {item['count']} | {fmt(item['avg_return_pct'], '%')} | "
            f"{fmt(item['median_return_pct'], '%')} | {fmt(item['win_rate_pct'], '%')} | "
            f"{signal_text} | {permission_text} |"
        )
    lines.extend([
        "",
        "## 3. V2 子状态基准",
        "",
        "| 子状态 | 数量 | 平均收益 | 中位收益 | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for key, item in list(report.get("v2_candidate_substate", {}).items())[:10]:
        lines.append(
            f"| {key} | {item['count']} | {fmt(item['avg_return_pct'], '%')} | "
            f"{fmt(item['median_return_pct'], '%')} | {fmt(item['win_rate_pct'], '%')} |"
        )
    lines.extend([
        "",
        "## 4. 当前结论",
        "",
        "- P21-A 的边界成立：旧 C 素材只进入 facts，`permission_leak_count` 必须为 0。",
        "- 旧 C 素材整体区分度不足时，不能作为入场加权项恢复。",
        "- `legacy_low_risk_pullback` 若弱于全市场，只能保留为解释素材，不进入 `C回` 加分。",
        "- `legacy_bottom_repair_hint` 若弱于全市场，不能直接提高 `C修/C候` 权重。",
        "- `legacy_risk_hint` 命中过宽时，不能作为独立风险过滤器，只适合研究 Exit Gate 提前性。",
        "- 若某个 V2 子状态显著强于全市场，也必须先做多日期滚动消融，不能从单窗口直接改规则。",
        "",
        f"`permission_leak_count = {report['permission_leak_count']}`",
        "",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_legacy_experience_rows(
    *,
    signal_date: str,
    outcome_date: str,
    start_date: str = DATA_START_DATE,
    workers: int | None = None,
    limit: int | None = None,
    progress_every: int = 500,
) -> dict:
    signal_date = _date_text(signal_date)
    outcome_date = _date_text(outcome_date)
    paths = discover_history_cache_paths(start_date=start_date, outcome_date=outcome_date)
    if limit:
        paths = paths[:limit]
    workers = max(1, int(workers or min(8, os.cpu_count() or 4)))
    started = time.perf_counter()
    rows = []
    counts: dict[str, int] = {"total_paths": len(paths)}
    tasks = [(str(path), signal_date, outcome_date) for path in paths]

    if workers == 1:
        iterator = (evaluate_one_path(task) for task in tasks)
        for index, item in enumerate(iterator, start=1):
            rows.append(item)
            status = item.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
            if progress_every and index % progress_every == 0:
                print(f"progress {index}/{len(tasks)} evaluated={counts.get('evaluated', 0)}", file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(evaluate_one_path, task) for task in tasks]
            for index, future in enumerate(as_completed(futures), start=1):
                item = future.result()
                rows.append(item)
                status = item.get("status") or "unknown"
                counts[status] = counts.get(status, 0) + 1
                if progress_every and index % progress_every == 0:
                    print(f"progress {index}/{len(tasks)} evaluated={counts.get('evaluated', 0)}", file=sys.stderr, flush=True)

    return rows, counts, time.perf_counter() - started


def analyze_legacy_experience_ablation(
    *,
    signal_date: str,
    outcome_date: str,
    start_date: str = DATA_START_DATE,
    workers: int | None = None,
    limit: int | None = None,
    progress_every: int = 500,
) -> dict:
    signal_date = _date_text(signal_date)
    outcome_date = _date_text(outcome_date)
    rows, counts, elapsed = collect_legacy_experience_rows(
        signal_date=signal_date,
        outcome_date=outcome_date,
        start_date=start_date,
        workers=workers,
        limit=limit,
        progress_every=progress_every,
    )
    report = build_report(
        rows,
        signal_date=signal_date,
        outcome_date=outcome_date,
        elapsed_seconds=elapsed,
        counts=counts,
    )
    return report


def build_rollup_report(pair_reports: list[dict]) -> dict:
    bucket_rollup = {}
    for key in LEGACY_BUCKETS:
        bucket_rollup[key] = _summary_from_summaries([(report.get("buckets") or {}).get(key, {}) for report in pair_reports])
    substate_keys = sorted({
        key
        for report in pair_reports
        for key in (report.get("v2_candidate_substate") or {}).keys()
    })
    substate_rollup = {
        key: _summary_from_summaries([
            (report.get("v2_candidate_substate") or {}).get(key, {})
            for report in pair_reports
        ])
        for key in substate_keys
    }
    return {
        "version": 1,
        "source": "legacy_experience_ablation_rollup_p21c",
        "pair_count": len(pair_reports),
        "pairs": [
            {
                "signal_date": report.get("signal_date"),
                "outcome_date": report.get("outcome_date"),
                "baseline": report.get("baseline"),
                "legacy_any": report.get("legacy_any"),
                "legacy_none": report.get("legacy_none"),
                "buckets": {
                    key: {
                        "count": ((report.get("buckets") or {}).get(key) or {}).get("count"),
                        "avg_return_pct": ((report.get("buckets") or {}).get(key) or {}).get("avg_return_pct"),
                        "win_rate_pct": ((report.get("buckets") or {}).get(key) or {}).get("win_rate_pct"),
                    }
                    for key in LEGACY_BUCKETS
                },
            }
            for report in pair_reports
        ],
        "baseline": _summary_from_summaries([report.get("baseline") or {} for report in pair_reports]),
        "legacy_any": _summary_from_summaries([report.get("legacy_any") or {} for report in pair_reports]),
        "legacy_none": _summary_from_summaries([report.get("legacy_none") or {} for report in pair_reports]),
        "buckets": bucket_rollup,
        "v2_candidate_substate": dict(sorted(substate_rollup.items(), key=lambda item: item[1]["count"], reverse=True)),
        "permission_leak_count": sum(int(report.get("permission_leak_count") or 0) for report in pair_reports),
        "elapsed_seconds": round(sum(float(report.get("elapsed_seconds") or 0) for report in pair_reports), 3),
    }


def analyze_legacy_experience_rollup(
    *,
    pairs: list[tuple[str, str]],
    start_date: str = DATA_START_DATE,
    workers: int | None = None,
    limit: int | None = None,
    progress_every: int = 500,
) -> dict:
    pair_reports = []
    for signal_date, outcome_date in pairs:
        print(f"pair {signal_date}->{outcome_date}", file=sys.stderr, flush=True)
        pair_reports.append(analyze_legacy_experience_ablation(
            signal_date=signal_date,
            outcome_date=outcome_date,
            start_date=start_date,
            workers=workers,
            limit=limit,
            progress_every=progress_every,
        ))
    return build_rollup_report(pair_reports)


def write_rollup_markdown_report(report: dict, path: Path) -> None:
    def fmt(value, suffix=""):
        return "-" if value is None else f"{value}{suffix}"

    labels = {
        "legacy_low_risk_pullback": "旧 C 低风险回踩",
        "legacy_bottom_repair_hint": "旧 C 底部修复",
        "legacy_risk_hint": "旧 C 风险提示",
    }
    lines = [
        "# P21-C 旧 C / V2 子状态滚动消融报告",
        "",
        f"> 窗口数：{report.get('pair_count', 0)}  ",
        "> 来源：本地日线缓存按每个信号日重新切片计算；滚动汇总的中位数不做跨窗口合成。",
        "",
        "## 1. 窗口明细",
        "",
        "| 信号日 | 结果日 | 全市场均值 | 全市场胜率 | 旧 C 素材均值 | 旧 C 素材胜率 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in report.get("pairs", []):
        baseline = item.get("baseline") or {}
        legacy_any = item.get("legacy_any") or {}
        lines.append(
            f"| {item.get('signal_date')} | {item.get('outcome_date')} | "
            f"{fmt(baseline.get('avg_return_pct'), '%')} | {fmt(baseline.get('win_rate_pct'), '%')} | "
            f"{fmt(legacy_any.get('avg_return_pct'), '%')} | {fmt(legacy_any.get('win_rate_pct'), '%')} |"
        )
    lines.extend([
        "",
        "## 2. 滚动汇总",
        "",
        "| 样本 | 数量 | 加权平均收益 | 胜率 | 上/平/下 |",
        "|---|---:|---:|---:|---:|",
    ])
    for label, key in (("全市场可评估", "baseline"), ("命中旧 C 素材", "legacy_any"), ("未命中旧 C 素材", "legacy_none")):
        item = report.get(key) or {}
        lines.append(
            f"| {label} | {item.get('count', 0)} | {fmt(item.get('avg_return_pct'), '%')} | "
            f"{fmt(item.get('win_rate_pct'), '%')} | {item.get('up', 0)}/{item.get('flat', 0)}/{item.get('down', 0)} |"
        )
    lines.extend([
        "",
        "## 3. 旧 C 素材滚动汇总",
        "",
        "| 素材 | 数量 | 加权平均收益 | 胜率 |",
        "|---|---:|---:|---:|",
    ])
    for key, item in (report.get("buckets") or {}).items():
        lines.append(
            f"| {labels.get(key, key)} | {item.get('count', 0)} | "
            f"{fmt(item.get('avg_return_pct'), '%')} | {fmt(item.get('win_rate_pct'), '%')} |"
        )
    lines.extend([
        "",
        "## 4. V2 子状态滚动汇总",
        "",
        "| 子状态 | 数量 | 加权平均收益 | 胜率 |",
        "|---|---:|---:|---:|",
    ])
    for key, item in list((report.get("v2_candidate_substate") or {}).items())[:12]:
        lines.append(
            f"| {key} | {item.get('count', 0)} | {fmt(item.get('avg_return_pct'), '%')} | {fmt(item.get('win_rate_pct'), '%')} |"
        )
    lines.extend([
        "",
        "## 5. 当前结论",
        "",
        "- 旧 C 素材只作为解释和分组变量，不授予 V2 许可。",
        "- 若滚动汇总仍显示旧 C 素材与全市场接近，应继续裁剪其入场权重想象。",
        "- 后续策略优化应优先验证 V2 子状态和次日确认价，而不是继续叠加旧 C 字段。",
        "",
        f"`permission_leak_count = {report.get('permission_leak_count', 0)}`",
        "",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-date", default="")
    parser.add_argument("--outcome-date", default="")
    parser.add_argument(
        "--pair",
        action="append",
        default=[],
        help="rolling pair in SIGNAL_DATE:OUTCOME_DATE form; can be repeated",
    )
    parser.add_argument("--start-date", default=DATA_START_DATE)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=500)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.pair:
        report = analyze_legacy_experience_rollup(
            pairs=[_parse_pair(value) for value in args.pair],
            start_date=args.start_date,
            workers=args.workers,
            limit=args.limit,
            progress_every=args.progress_every,
        )
    else:
        if not args.signal_date or not args.outcome_date:
            raise SystemExit("--signal-date and --outcome-date are required unless --pair is provided")
        report = analyze_legacy_experience_ablation(
            signal_date=args.signal_date,
            outcome_date=args.outcome_date,
            start_date=args.start_date,
            workers=args.workers,
            limit=args.limit,
            progress_every=args.progress_every,
        )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    if args.markdown_out:
        if report.get("source") == "legacy_experience_ablation_rollup_p21c":
            write_rollup_markdown_report(report, Path(args.markdown_out))
        else:
            write_markdown_report(report, Path(args.markdown_out))
    print(text)
    if report.get("source") == "legacy_experience_ablation_rollup_p21c":
        return 0 if report.get("pair_count") else 1
    return 0 if report["counts"].get("evaluated") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
