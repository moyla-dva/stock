"""Event-level backtest and attribution helpers."""

from collections import defaultdict


UP_CATEGORIES = {"entry", "bottom", "observe"}
DOWN_CATEGORIES = {"risk", "exit", "top"}


def event_direction(event):
    if event.category in DOWN_CATEGORIES:
        return "down"
    return "up"


def _date_positions(df_display):
    dates = df_display["date"].dt.strftime("%Y-%m-%d").tolist()
    return {date: idx for idx, date in enumerate(dates)}


def _empty_stats(label=None, name=None, category=None, direction=None, horizon=5):
    result = {
        "count": 0,
        "evaluated_count": 0,
        "win_rate": None,
        "avg_ret": None,
        "horizon": horizon,
    }
    if label is not None:
        result["label"] = label
    if name is not None:
        result["name"] = name
    if category is not None:
        result["category"] = category
    if direction is not None:
        result["direction"] = direction
    return result


def _stats_from_returns(returns, direction, horizon=5, label=None, name=None, category=None):
    stats = _empty_stats(
        label=label,
        name=name,
        category=category,
        direction=direction,
        horizon=horizon,
    )
    stats["count"] = len(returns)
    evaluated = [value for value in returns if value is not None]
    stats["evaluated_count"] = len(evaluated)
    if not evaluated:
        return stats

    if direction == "down":
        wins = [value < 0 for value in evaluated]
    else:
        wins = [value > 0 for value in evaluated]
    stats["win_rate"] = sum(wins) / len(evaluated) * 100
    stats["avg_ret"] = sum(evaluated) / len(evaluated)
    return stats


def _reason_parts(reason):
    return [part.strip() for part in str(reason or "").split("/") if part.strip()]


def evaluate_signal_events(df_display, events, horizon=5):
    """Evaluate SignalEvent objects and reason attribution over a fixed horizon."""
    date_positions = _date_positions(df_display)
    closes = df_display["close"].tolist()
    by_signal = defaultdict(list)
    signal_info = {}
    by_reason = defaultdict(list)
    reason_direction = {}

    for event in events:
        direction = event_direction(event)
        signal_info[event.key] = {
            "label": event.label,
            "name": event.name,
            "category": event.category,
            "direction": direction,
        }

        idx = date_positions.get(event.date)
        future_ret = None
        if idx is not None and idx + horizon < len(closes):
            future_ret = (closes[idx + horizon] - closes[idx]) / closes[idx] * 100

        by_signal[event.key].append(future_ret)
        for reason in _reason_parts(event.reason):
            by_reason[reason].append(future_ret)
            reason_direction[reason] = direction

    signal_stats = {}
    for key, returns in by_signal.items():
        info = signal_info[key]
        signal_stats[key] = _stats_from_returns(
            returns,
            info["direction"],
            horizon=horizon,
            label=info["label"],
            name=info["name"],
            category=info["category"],
        )

    reason_stats = {}
    for reason, returns in by_reason.items():
        reason_stats[reason] = _stats_from_returns(
            returns,
            reason_direction.get(reason, "up"),
            horizon=horizon,
            label=reason,
            name=reason,
        )

    return {
        "horizon": horizon,
        "by_signal": signal_stats,
        "by_reason": reason_stats,
    }
