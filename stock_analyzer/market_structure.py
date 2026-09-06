"""Independent market-structure rows built from local stock profiles."""

from stock_analyzer.scan_common import UNKNOWN_CONCEPT, UNKNOWN_SECTOR, result_concepts, result_sector
from stock_analyzer.profile_relations import build_stock_profile_relations


RELATION_GROUP_SCORES = {
    "core_business": 88.0,
    "manual": 82.0,
    "event_driven": 74.0,
    "market_tag": 54.0,
    "weak_association": 24.0,
    "expired_watch": 0.0,
}

RELATION_GROUP_COUNT_FIELDS = {
    "core_business": "relation_core_business_count",
    "manual": "relation_manual_count",
    "event_driven": "relation_event_driven_count",
    "market_tag": "relation_market_tag_count",
    "weak_association": "relation_weak_association_count",
    "expired_watch": "relation_expired_watch_count",
}


def _empty_candidate_stat(key_name, value):
    return {
        key_name: value,
        "count": 0,
        "opportunity_count": 0,
        "risk_count": 0,
        "bottom_div_count": 0,
        "signal_count": 0,
        "active_day_count": 0,
        "avg_rank": 0.0,
        "max_rank": 0.0,
        "avg_win_rate": None,
        "avg_ret": None,
        "latest_event": "-",
        f"{key_name}_score": 0.0,
    }


def build_market_universe(profile_cache):
    """Return sector and concept member counts from the local profile cache."""
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


def _relation_group(relation):
    return relation.get("evidence_group") or relation.get("relation_type") or "market_tag"


def _profile_relations(profile):
    relations = profile.get("profile_relations") if isinstance(profile, dict) else []
    if isinstance(relations, list) and relations:
        return relations
    return build_stock_profile_relations(profile)


def _empty_relation_stat():
    stat = {
        "relation_member_count": 0,
        "relation_score_total": 0.0,
        "relation_confidence_total": 0.0,
    }
    for field in RELATION_GROUP_COUNT_FIELDS.values():
        stat[field] = 0
    return stat


def _add_relation_stat(stats, name, relation):
    if not name:
        return
    group = _relation_group(relation)
    stat = stats.setdefault(name, _empty_relation_stat())
    stat["relation_member_count"] += 1
    stat["relation_score_total"] += RELATION_GROUP_SCORES.get(group, RELATION_GROUP_SCORES["market_tag"])
    try:
        confidence = float(relation.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    stat["relation_confidence_total"] += max(0.0, min(1.0, confidence))
    field = RELATION_GROUP_COUNT_FIELDS.get(group)
    if field:
        stat[field] += 1


def build_market_relation_evidence(profile_cache):
    """Count relationship-quality evidence for sectors and concepts."""
    sectors = {}
    concepts = {}
    for profile in (profile_cache or {}).values():
        if not isinstance(profile, dict):
            continue
        for relation in _profile_relations(profile):
            name = str(relation.get("relation_name") or "").strip()
            kind = relation.get("relation_kind") or relation.get("kind")
            if not name:
                continue
            if kind == "industry":
                _add_relation_stat(sectors, name, relation)
            else:
                _add_relation_stat(concepts, name, relation)
    return sectors, concepts


def _relation_quality_label(stat):
    if not stat or not stat.get("relation_member_count"):
        return "未验证"
    core = int(stat.get("relation_core_business_count") or 0)
    manual = int(stat.get("relation_manual_count") or 0)
    event = int(stat.get("relation_event_driven_count") or 0)
    weak = int(stat.get("relation_weak_association_count") or 0)
    expired = int(stat.get("relation_expired_watch_count") or 0)
    market = int(stat.get("relation_market_tag_count") or 0)
    if core:
        return "主营确认"
    if manual:
        return "人工确认"
    if event:
        return "事件驱动"
    if expired and expired >= max(core + manual + event + market, 1):
        return "过期观察"
    if weak and weak >= max(core + manual + event + market, 1):
        return "弱关联"
    return "市场标签"


def _apply_relation_evidence(stat, relation_stat):
    relation_stat = relation_stat or {}
    member_count = int(relation_stat.get("relation_member_count") or 0)
    stat["relation_member_count"] = member_count
    for field in RELATION_GROUP_COUNT_FIELDS.values():
        stat[field] = int(relation_stat.get(field) or 0)
    stat["relation_verified_count"] = (
        stat["relation_core_business_count"]
        + stat["relation_manual_count"]
        + stat["relation_event_driven_count"]
    )
    stat["relation_weak_count"] = stat["relation_weak_association_count"] + stat["relation_expired_watch_count"]
    if member_count:
        stat["relation_quality_score"] = round(relation_stat.get("relation_score_total", 0.0) / member_count, 1)
        stat["relation_avg_confidence"] = round(relation_stat.get("relation_confidence_total", 0.0) / member_count, 2)
    else:
        stat["relation_quality_score"] = None
        stat["relation_avg_confidence"] = None
    stat["relation_quality_label"] = _relation_quality_label(stat)


def _apply_candidate_width(stat, member_count):
    opportunity_width_count = int(stat.get("opportunity_count") or 0) + int(stat.get("bottom_div_count") or 0)
    risk_count = int(stat.get("risk_count") or 0)
    candidate_count = int(stat.get("count") or 0)
    if member_count:
        opportunity_density = round(opportunity_width_count * 100 / member_count, 2)
        risk_density = round(risk_count * 100 / member_count, 2)
        candidate_density = round(candidate_count * 100 / member_count, 2)
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

    stat["candidate_count"] = candidate_count
    stat["candidate_signal_count"] = int(stat.get("signal_count") or 0)
    stat["candidate_score"] = stat.get("sector_score", stat.get("concept_score", 0.0))
    stat["market_member_count"] = member_count
    stat["candidate_density"] = candidate_density
    stat["opportunity_density"] = opportunity_density
    stat["risk_density"] = risk_density
    stat["width_score"] = width_score
    stat["width_label"] = width_label
    stat["market_universe_source"] = "profile_cache" if member_count else ""


def _merge_universe_rows(candidate_overview, key_name, universe_counts, relation_evidence=None):
    by_name = {
        item.get(key_name): dict(item)
        for item in (candidate_overview or [])
        if item.get(key_name)
    }
    names = set(universe_counts.keys()) | set(by_name.keys())
    rows = []
    for name in sorted(names):
        if not name or name in {UNKNOWN_SECTOR, UNKNOWN_CONCEPT}:
            continue
        row = by_name.get(name, _empty_candidate_stat(key_name, name))
        _apply_candidate_width(row, int(universe_counts.get(name, 0) or 0))
        _apply_relation_evidence(row, (relation_evidence or {}).get(name))
        rows.append(row)
    return rows


def build_market_structure_overview(sector_candidate_overview, concept_candidate_overview, profile_cache):
    """Build sector/concept overview rows from market universe plus candidate validation."""
    sector_counts, concept_counts = build_market_universe(profile_cache)
    sector_relations, concept_relations = build_market_relation_evidence(profile_cache)
    return (
        _merge_universe_rows(sector_candidate_overview, "sector", sector_counts, sector_relations),
        _merge_universe_rows(concept_candidate_overview, "concept", concept_counts, concept_relations),
    )


def _weighted_score(parts):
    total_weight = sum(weight for value, weight in parts if value is not None)
    if total_weight <= 0:
        return 0.0
    total = sum(float(value) * weight for value, weight in parts if value is not None)
    return round(max(0.0, min(100.0, total / total_weight)), 1)


def apply_market_structure_scores(overview, key_name):
    """Attach a market-structure score without changing candidate resonance scores."""
    for stat in overview or []:
        candidate_score = float(stat.get(f"{key_name}_score") or 0.0)
        market_score = stat.get("market_strength_score")
        breadth_score = stat.get("breadth_score")
        relation_score = stat.get("relation_quality_score")
        has_activity = candidate_score > 0 or market_score is not None or breadth_score is not None
        if market_score is not None or breadth_score is not None:
            structure_score = _weighted_score([
                (market_score, 0.46),
                (breadth_score, 0.28),
                (candidate_score if candidate_score > 0 else None, 0.18),
                (relation_score if has_activity else None, 0.08),
            ])
        else:
            structure_score = _weighted_score([
                (candidate_score if candidate_score > 0 else None, 0.84),
                (relation_score if candidate_score > 0 else None, 0.16),
            ])
        stat["structure_score"] = structure_score
        stat["structure_score_label"] = structure_score


def sort_market_structure_overview(overview):
    return sorted(
        overview or [],
        key=lambda item: (
            float(item.get("structure_score") or 0.0),
            int(item.get("candidate_signal_count") or item.get("signal_count") or 0),
            float(item.get("market_strength_score") or 0.0),
            float(item.get("breadth_score") or 0.0),
            int(item.get("market_member_count") or 0),
            str(item.get("latest_event") or ""),
        ),
        reverse=True,
    )
