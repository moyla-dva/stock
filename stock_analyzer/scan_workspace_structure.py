"""Build descriptive sector/concept candidate distributions for scan workspaces."""

from stock_analyzer.backtest import ENTRY_MODEL_EVENT_CLOSE
from stock_analyzer.scan_common import result_concepts, result_sector
from stock_analyzer.scan_confidence import apply_score_confidence
from stock_analyzer.scan_overview import build_concept_overview, build_sector_overview


REPLAY_HORIZONS = (3, 5, 10)


def _disabled_replay_calibration(horizons=REPLAY_HORIZONS, entry_model=ENTRY_MODEL_EVENT_CLOSE):
    """Keep the response shape while sector-bucket replay is retired."""
    return {
        "method": "disabled",
        "note": "板块/概念分桶回放已退役，不参与候选排序或许可",
        "entry_model": entry_model,
        "horizons": list(horizons),
        "candidate_count": 0,
        "requested_count": 0,
        "buckets": [],
    }


def build_workspace_structure(
    pools,
    replay_entry_model=ENTRY_MODEL_EVENT_CLOSE,
):
    """Build candidate-distribution summaries without sector or concept decision factors."""
    sector_candidate_overview = build_sector_overview(pools)
    concept_candidate_overview = build_concept_overview(pools)
    for scan_type, pool in pools.items():
        results = pool.get("results", [])
        seen_sectors = {result_sector(result) for result in results}
        seen_concepts = {
            concept
            for result in results
            for concept in result_concepts(result)
        }
        pool["sector_stats"] = [
            stat for stat in sector_candidate_overview
            if stat["sector"] in seen_sectors
        ]
        pool["concept_stats"] = [
            stat for stat in concept_candidate_overview
            if stat["concept"] in seen_concepts
        ]
        covered_count = sum(bool(result_concepts(result)) for result in results)
        pool["concept_coverage"] = {
            "covered_count": covered_count,
            "total_count": len(results),
            "coverage_rate": round(covered_count * 100 / len(results), 1) if results else 0.0,
        }

    resonance_calibration = {
        "method": "disabled",
        "note": "行业/概念候选聚集只作分布统计，不计算共振评分",
        "buckets": [],
    }
    replay_calibration = _disabled_replay_calibration(entry_model=replay_entry_model)
    apply_score_confidence(pools)

    market_structure_meta = {
        "mode": "candidate_distribution",
        "mode_label": "候选分布统计",
        "available": bool(sector_candidate_overview or concept_candidate_overview),
        "sectors": {"candidate_group_count": len(sector_candidate_overview), "market_supported_count": 0},
        "concepts": {"candidate_group_count": len(concept_candidate_overview), "market_supported_count": 0},
        "note": "仅统计当前扫描候选，不接入板块/概念行情、宽度或环境许可",
    }
    return {
        "sector_overview": sector_candidate_overview,
        "concept_overview": concept_candidate_overview,
        "concept_graph_status": {"status": "not_used", "experimental": False},
        "market_structure_meta": market_structure_meta,
        "resonance_calibration": resonance_calibration,
        "replay_calibration": replay_calibration,
    }
