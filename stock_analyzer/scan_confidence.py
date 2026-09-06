"""Replay confidence and calibration summaries for scan candidates."""

from stock_analyzer.scan_buckets import RESONANCE_CALIBRATION_BUCKETS, resonance_bucket
from stock_analyzer.scan_common import as_float, avg_or_none, result_sector
from stock_analyzer.scan_explainer import attach_scan_explanation


def _replay_bucket_map(replay_calibration):
    buckets = {}
    if not isinstance(replay_calibration, dict):
        return buckets
    for bucket in replay_calibration.get("buckets", []) or []:
        if isinstance(bucket, dict) and bucket.get("key"):
            buckets[bucket["key"]] = bucket
    return buckets


def _bucket_replay_horizon(bucket, horizon="5"):
    horizons = bucket.get("horizons") if isinstance(bucket, dict) else None
    if not isinstance(horizons, dict):
        return {}
    return horizons.get(str(horizon)) or {}


def _score_confidence(sample_count, has_proxy_history):
    if sample_count >= 20:
        return "high", "回放充分"
    if sample_count >= 5:
        return "medium", "回放可参考"
    if sample_count > 0 or has_proxy_history:
        return "low", "样本偏少"
    return "empty", "待验证"


def apply_score_confidence(pools, replay_calibration=None):
    replay_buckets = _replay_bucket_map(replay_calibration)
    for scan_type, pool in pools.items():
        for result in pool.get("results", []):
            bucket_key = resonance_bucket(result.get("sector_score"))
            replay_bucket = replay_buckets.get(bucket_key, {})
            replay5 = _bucket_replay_horizon(replay_bucket, "5")
            sample_count = int(replay5.get("sample_count") or 0)
            replay_win_rate = replay5.get("win_rate")
            replay_avg_ret = replay5.get("avg_ret")
            replay_worst_ret = replay5.get("worst_ret")
            replay_avg_worst_ret = replay5.get("avg_worst_ret")
            has_proxy_history = result.get("win_rate") is not None or result.get("avg_ret") is not None
            level, label = _score_confidence(sample_count, has_proxy_history)
            replay_basis = (
                f"5日回放 {sample_count} 样本"
                + (
                    f" · 胜率 {replay_win_rate}% · 均值 {replay_avg_ret}%"
                    if sample_count and replay_win_rate is not None and replay_avg_ret is not None
                    else ""
                )
            )
            result["score_confidence"] = {
                "level": level,
                "label": label,
                "bucket": bucket_key,
                "replay_5d_sample_count": sample_count,
                "replay_5d_win_rate": replay_win_rate,
                "replay_5d_avg_ret": replay_avg_ret,
                "replay_5d_worst_ret": replay_worst_ret,
                "replay_5d_avg_worst_ret": replay_avg_worst_ret,
                "proxy_win_rate": result.get("win_rate"),
                "proxy_avg_ret": result.get("avg_ret"),
                "proxy_history_available": bool(has_proxy_history),
                "basis": replay_basis + (" · 信号历史可用" if has_proxy_history else " · 信号历史缺失"),
            }
            result["score_confidence_level"] = level
            result["score_confidence_label"] = label
            attach_scan_explanation(result)


def build_resonance_calibration(pools):
    buckets = {
        bucket["key"]: {
            "key": bucket["key"],
            "label": bucket["label"],
            "candidate_count": 0,
            "sector_count": 0,
            "sectors": set(),
            "score_total": 0.0,
            "rank_total": 0.0,
            "win_rate_total": 0.0,
            "win_rate_count": 0,
            "avg_ret_total": 0.0,
            "avg_ret_count": 0,
            "positive_count": 0,
        }
        for bucket in RESONANCE_CALIBRATION_BUCKETS
    }

    for scan_type in ("opportunity", "bottom_div"):
        for result in pools.get(scan_type, {}).get("results", []):
            if result_sector(result) == "未识别板块":
                continue
            bucket = buckets[resonance_bucket(result.get("sector_score"))]
            bucket["candidate_count"] += 1
            bucket["sectors"].add(result_sector(result))
            bucket["score_total"] += as_float(result.get("sector_score"), 0.0)
            bucket["rank_total"] += as_float(result.get("rank_score"), 0.0)

            win_rate = result.get("win_rate")
            if win_rate is not None:
                bucket["win_rate_total"] += as_float(win_rate, 0.0)
                bucket["win_rate_count"] += 1

            avg_ret = result.get("avg_ret")
            if avg_ret is not None:
                avg_ret_value = as_float(avg_ret, 0.0)
                bucket["avg_ret_total"] += avg_ret_value
                bucket["avg_ret_count"] += 1
                if avg_ret_value > 0:
                    bucket["positive_count"] += 1

    output_buckets = []
    for bucket_def in RESONANCE_CALIBRATION_BUCKETS:
        bucket = buckets[bucket_def["key"]]
        candidate_count = bucket["candidate_count"]
        avg_ret_count = bucket["avg_ret_count"]
        output_buckets.append({
            "key": bucket["key"],
            "label": bucket["label"],
            "candidate_count": candidate_count,
            "sector_count": len(bucket["sectors"]),
            "avg_sector_score": avg_or_none(bucket["score_total"], candidate_count, 1),
            "avg_rank": avg_or_none(bucket["rank_total"], candidate_count, 1),
            "avg_win_rate": avg_or_none(bucket["win_rate_total"], bucket["win_rate_count"], 1),
            "avg_ret": avg_or_none(bucket["avg_ret_total"], avg_ret_count, 2),
            "positive_rate": avg_or_none(bucket["positive_count"] * 100, avg_ret_count, 1),
            "sample_quality": "可参考" if candidate_count >= 10 else ("样本少" if candidate_count else "无样本"),
        })

    return {
        "method": "signal_history_proxy",
        "note": "按共振分桶聚合候选自带的信号历史胜率与均值",
        "buckets": output_buckets,
    }
