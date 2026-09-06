"""Build sector and concept overview models for scan workspaces."""

from stock_analyzer.scan_common import (
    UNKNOWN_CONCEPT,
    UNKNOWN_SECTOR,
    as_float,
    result_concepts,
    result_event_date,
    result_sector,
)


def sector_resonance_score(stat):
    if stat.get("sector") == UNKNOWN_SECTOR:
        return 0.0
    signal_count = stat["opportunity_count"] + stat["bottom_div_count"]
    raw_score = (
        signal_count * 8
        + stat["avg_rank"] * 0.35
        + stat["max_rank"] * 0.15
        + stat["bottom_div_count"] * 2
        - stat["risk_count"] * 5
    )
    return round(max(0.0, min(100.0, raw_score)), 1)


def concept_resonance_score(stat):
    if stat.get("concept") == UNKNOWN_CONCEPT:
        return 0.0
    signal_count = stat["opportunity_count"] + stat["bottom_div_count"]
    raw_score = (
        signal_count * 6
        + stat["avg_rank"] * 0.32
        + stat["max_rank"] * 0.12
        + stat["bottom_div_count"] * 1.5
        - stat["risk_count"] * 4
    )
    return round(max(0.0, min(100.0, raw_score)), 1)


def build_overview(pools, key_name, values_func, score_func):
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
        output[f"{key_name}_score"] = score_func(output)
        stats.append(output)

    return sorted(
        stats,
        key=lambda item: (
            item[f"{key_name}_score"],
            item["signal_count"],
            item["avg_rank"],
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
        sector_resonance_score,
    )


def build_concept_overview(pools):
    return build_overview(
        pools,
        "concept",
        lambda result: result_concepts(result) or [UNKNOWN_CONCEPT],
        concept_resonance_score,
    )


def _market_universe_counts(profile_cache):
    sectors = {}
    concepts = {}
    for profile in (profile_cache or {}).values():
        sector = result_sector(profile)
        if sector and sector != UNKNOWN_SECTOR:
            sectors[sector] = sectors.get(sector, 0) + 1
        for concept in result_concepts(profile):
            if concept and concept != UNKNOWN_CONCEPT:
                concepts[concept] = concepts.get(concept, 0) + 1
    return sectors, concepts


def _apply_width_metrics(stat, member_count):
    opportunity_width_count = int(stat.get("opportunity_count") or 0) + int(stat.get("bottom_div_count") or 0)
    risk_count = int(stat.get("risk_count") or 0)
    if member_count:
        opportunity_density = round(opportunity_width_count * 100 / member_count, 2)
        risk_density = round(risk_count * 100 / member_count, 2)
        candidate_density = round(int(stat.get("count") or 0) * 100 / member_count, 2)
    else:
        opportunity_density = None
        risk_density = None
        candidate_density = None

    width_score = 0.0 if opportunity_density is None else round(
        max(0.0, min(100.0, opportunity_density * 8 - (risk_density or 0) * 4)),
        1,
    )
    if opportunity_density is None:
        width_label = "缺成分"
    elif opportunity_density >= 5 and (risk_density or 0) <= opportunity_density:
        width_label = "扩散"
    elif opportunity_density >= 2:
        width_label = "有宽度"
    elif opportunity_density > 0:
        width_label = "点状"
    else:
        width_label = "无宽度"

    stat["market_member_count"] = member_count
    stat["candidate_density"] = candidate_density
    stat["opportunity_density"] = opportunity_density
    stat["risk_density"] = risk_density
    stat["width_score"] = width_score
    stat["width_label"] = width_label
    stat["market_universe_source"] = "profile_cache"


def apply_market_universe_to_overview(sector_overview, concept_overview, profile_cache):
    sector_counts, concept_counts = _market_universe_counts(profile_cache)

    for stat in sector_overview:
        member_count = sector_counts.get(stat.get("sector"), 0)
        _apply_width_metrics(stat, member_count)

    for stat in concept_overview:
        member_count = concept_counts.get(stat.get("concept"), 0)
        _apply_width_metrics(stat, member_count)
