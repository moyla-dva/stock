"""Data-source annotations for market-structure overview rows."""

from stock_analyzer.scan_common import UNKNOWN_CONCEPT, UNKNOWN_SECTOR, result_concepts, result_sector


def _has_number(value):
    return value is not None and value != ""


def _profile_universe_counts(profile_cache):
    sectors = set()
    concepts = set()
    for profile in (profile_cache or {}).values():
        sector = result_sector(profile)
        if sector and sector != UNKNOWN_SECTOR:
            sectors.add(sector)
        for concept in result_concepts(profile):
            if concept and concept != UNKNOWN_CONCEPT:
                concepts.add(concept)
    return len(sectors), len(concepts)


def _source_basis(stat):
    basis = []
    if int(stat.get("market_member_count") or 0) > 0:
        basis.append({"key": "profile_universe", "label": "画像成分", "role": "primary"})
    if int(stat.get("relation_member_count") or 0) > 0:
        label = "关系证据" if int(stat.get("relation_verified_count") or 0) > 0 else "画像标签"
        basis.append({"key": "profile_relations", "label": label, "role": "support"})
    if int(stat.get("breadth_sample_count") or 0) > 0:
        basis.append({"key": "history_breadth", "label": "本地宽度", "role": "support"})
    if _has_number(stat.get("market_strength_score")):
        label = "旧行情" if stat.get("market_cache_stale") else "板块行情"
        basis.append({"key": "board_market", "label": label, "role": "support"})
    if int(stat.get("candidate_count") or stat.get("count") or 0) > 0:
        basis.append({"key": "scan_candidates", "label": "候选验证", "role": "support"})
    if not basis:
        basis.append({"key": "scan_candidates", "label": "候选验证", "role": "primary"})
    return basis


def _confidence_label(basis):
    keys = {item["key"] for item in basis}
    if {"history_breadth", "board_market"}.issubset(keys):
        return "较高"
    if "profile_relations" in keys and ("history_breadth" in keys or "board_market" in keys):
        return "较高"
    if "history_breadth" in keys or "board_market" in keys:
        return "中等"
    if "profile_relations" in keys:
        return "参考"
    if "profile_universe" in keys:
        return "参考"
    return "候选"


def annotate_market_structure_rows(overview):
    """Attach source and confidence labels to already-built overview rows."""
    for stat in overview or []:
        basis = _source_basis(stat)
        labels = [item["label"] for item in basis]
        stat["structure_basis"] = basis
        stat["structure_source"] = "+".join(item["key"] for item in basis)
        stat["structure_source_label"] = "+".join(labels)
        stat["structure_confidence_label"] = _confidence_label(basis)
        if int(stat.get("market_member_count") or 0) > 0:
            stat["structure_mode"] = "market_universe"
            stat["structure_mode_label"] = "市场结构"
        else:
            stat["structure_mode"] = "candidate_validated"
            stat["structure_mode_label"] = "候选验证"


def build_market_structure_meta(sector_overview, concept_overview, profile_cache, concept_graph_status=None):
    """Summarize how complete the current market-structure data is."""
    sector_universe_count, concept_universe_count = _profile_universe_counts(profile_cache)
    sector_rows = sector_overview or []
    concept_rows = concept_overview or []
    has_universe = bool(sector_universe_count or concept_universe_count)

    def count_rows(rows, field):
        return sum(1 for item in rows if item.get(field))

    def sum_rows(rows, field):
        return sum(int(item.get(field) or 0) for item in rows)

    meta = {
        "mode": "market_universe" if has_universe else "candidate_validated",
        "mode_label": "全市场结构" if has_universe else "候选验证结构",
        "primary_basis": "profile_universe" if has_universe else "scan_candidates",
        "summary": (
            "当前以股票画像里的全量板块/概念为主，叠加候选验证、行情与本地宽度。"
            if has_universe
            else "当前缺少全量画像成分，仅能从扫描候选反推结构。"
        ),
        "sources": [
            {
                "key": "scan_candidates",
                "label": "候选验证",
                "role": "support" if has_universe else "primary",
                "available": True,
            },
            {
                "key": "profile_universe",
                "label": "股票画像",
                "role": "support",
                "available": bool(profile_cache),
            },
            {
                "key": "profile_relations",
                "label": "画像关系",
                "role": "support",
                "available": bool(count_rows(sector_rows + concept_rows, "relation_member_count")),
            },
            {
                "key": "concept_graph",
                "label": "关系图谱",
                "role": "support",
                "available": bool((concept_graph_status or {}).get("edge_count")),
            },
            {
                "key": "history_breadth",
                "label": "本地宽度",
                "role": "support",
                "available": bool(count_rows(sector_rows + concept_rows, "breadth_sample_count")),
            },
            {
                "key": "board_market",
                "label": "板块行情",
                "role": "support",
                "available": bool(count_rows(sector_rows + concept_rows, "market_strength_score")),
            },
        ],
        "sectors": {
            "rows": len(sector_rows),
            "universe_count": sector_universe_count,
            "market_supported_count": count_rows(sector_rows, "market_strength_score"),
            "breadth_supported_count": count_rows(sector_rows, "breadth_sample_count"),
            "relation_supported_count": count_rows(sector_rows, "relation_member_count"),
            "relation_verified_count": sum_rows(sector_rows, "relation_verified_count"),
        },
        "concepts": {
            "rows": len(concept_rows),
            "universe_count": concept_universe_count,
            "market_supported_count": count_rows(concept_rows, "market_strength_score"),
            "breadth_supported_count": count_rows(concept_rows, "breadth_sample_count"),
            "relation_supported_count": count_rows(concept_rows, "relation_member_count"),
            "relation_verified_count": sum_rows(concept_rows, "relation_verified_count"),
        },
    }
    return meta


def annotate_market_structure_sources(sector_overview, concept_overview, profile_cache, concept_graph_status=None):
    """Annotate rows and return a workspace-level source summary."""
    annotate_market_structure_rows(sector_overview)
    annotate_market_structure_rows(concept_overview)
    return build_market_structure_meta(
        sector_overview,
        concept_overview,
        profile_cache,
        concept_graph_status=concept_graph_status,
    )
