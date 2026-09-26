"""Build sector and concept overview models for scan workspaces."""

from stock_analyzer.scan_common import (
    UNKNOWN_CONCEPT,
    as_float,
    result_concepts,
    result_event_date,
    result_sector,
)


def build_overview(pools, key_name, values_func):
    overview = {}
    for scan_type, pool in pools.items():
        for result in pool.get("results", []):
            for value in values_func(result):
                stat = overview.setdefault(value, {
                    key_name: value,
                    "count": 0,
                    "opportunity_count": 0,
                    "risk_count": 0,
                    "bottom_div_count": 0,
                    "active_days": set(),
                    "total_rank": 0.0,
                    "max_rank": 0.0,
                    "win_rate_total": 0.0,
                    "win_rate_count": 0,
                    "avg_ret_total": 0.0,
                    "avg_ret_count": 0,
                    "latest_event": "",
                })
                rank_score = as_float(result.get("rank_score"), 0.0)
                stat["count"] += 1
                stat["total_rank"] += rank_score
                stat["max_rank"] = max(stat["max_rank"], rank_score)
                if scan_type == "risk":
                    stat["risk_count"] += 1
                elif scan_type == "bottom_div":
                    stat["bottom_div_count"] += 1
                else:
                    stat["opportunity_count"] += 1

                win_rate = result.get("win_rate")
                if win_rate is not None:
                    stat["win_rate_total"] += as_float(win_rate, 0.0)
                    stat["win_rate_count"] += 1
                avg_ret = result.get("avg_ret")
                if avg_ret is not None:
                    stat["avg_ret_total"] += as_float(avg_ret, 0.0)
                    stat["avg_ret_count"] += 1

                event_date = result_event_date(result)
                if event_date:
                    stat["active_days"].add(event_date)
                if event_date > stat["latest_event"]:
                    stat["latest_event"] = event_date

    stats = []
    for stat in overview.values():
        count = stat["count"] or 1
        output = {
            key_name: stat[key_name],
            "count": stat["count"],
            "opportunity_count": stat["opportunity_count"],
            "risk_count": stat["risk_count"],
            "bottom_div_count": stat["bottom_div_count"],
            "signal_count": stat["opportunity_count"] + stat["bottom_div_count"],
            "avg_rank": round(stat["total_rank"] / count, 1),
            "max_rank": round(stat["max_rank"], 1),
            "avg_win_rate": None,
            "avg_ret": None,
            "latest_event": stat["latest_event"] or "-",
            "active_day_count": len(stat["active_days"]),
        }
        if stat["win_rate_count"]:
            output["avg_win_rate"] = round(stat["win_rate_total"] / stat["win_rate_count"], 1)
        if stat["avg_ret_count"]:
            output["avg_ret"] = round(stat["avg_ret_total"] / stat["avg_ret_count"], 2)
        stats.append(output)

    return sorted(
        stats,
        key=lambda item: (
            item["count"],
            item["signal_count"],
            item["latest_event"],
            item[key_name],
        ),
        reverse=True,
    )


def build_sector_overview(pools):
    return build_overview(
        pools,
        "sector",
        lambda result: [result_sector(result)],
    )


def build_concept_overview(pools):
    return build_overview(
        pools,
        "concept",
        lambda result: result_concepts(result) or [UNKNOWN_CONCEPT],
    )
