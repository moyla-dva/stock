"""Confidence labels from candidate-local signal history."""

from stock_analyzer.scan_explainer import attach_scan_explanation


def _score_confidence(has_proxy_history):
    if has_proxy_history:
        return "low", "样本偏少"
    return "empty", "待验证"


def apply_score_confidence(pools):
    for pool in pools.values():
        for result in pool.get("results", []):
            has_proxy_history = result.get("win_rate") is not None or result.get("avg_ret") is not None
            level, label = _score_confidence(has_proxy_history)
            result["score_confidence"] = {
                "level": level,
                "label": label,
                "proxy_win_rate": result.get("win_rate"),
                "proxy_avg_ret": result.get("avg_ret"),
                "proxy_history_available": bool(has_proxy_history),
                "basis": (
                    "个股信号历史可用"
                    if has_proxy_history
                    else "个股信号历史缺失；行业/概念分桶回放未启用"
                ),
            }
            result["score_confidence_level"] = level
            result["score_confidence_label"] = label
            attach_scan_explanation(result)
