"""Apply sector and concept resonance scores to scan candidates."""

from stock_analyzer.scan_common import as_float, result_concepts, result_sector
from stock_analyzer.scan_explainer import attach_scan_explanation
from stock_analyzer.scan_market_context import apply_result_market_context


def apply_sector_resonance(pools, sector_overview):
    stats_by_sector = {item["sector"]: item for item in sector_overview}
    for scan_type, pool in pools.items():
        seen_sectors = set()
        for result in pool.get("results", []):
            stat = stats_by_sector.get(result_sector(result))
            if not stat:
                continue
            seen_sectors.add(stat["sector"])
            result["sector_score"] = stat["sector_score"]
            result["sector_signal_count"] = stat["signal_count"]
            result["sector_opportunity_count"] = stat["opportunity_count"]
            result["sector_bottom_div_count"] = stat["bottom_div_count"]
            result["sector_risk_count"] = stat["risk_count"]
            result["sector_avg_rank"] = stat["avg_rank"]
            result["sector_latest_event"] = stat["latest_event"]
            result["sector_member_count"] = stat.get("market_member_count")
            result["sector_candidate_density"] = stat.get("candidate_density")
            result["sector_opportunity_density"] = stat.get("opportunity_density")
            result["sector_risk_density"] = stat.get("risk_density")
            result["sector_width_score"] = stat.get("width_score")
            result["sector_width_label"] = stat.get("width_label")
            result["sector_candidate_width_label"] = stat.get("candidate_width_label")
            result["sector_breadth_sample_count"] = stat.get("breadth_sample_count")
            result["sector_breadth_up_rate"] = stat.get("breadth_up_rate")
            result["sector_breadth_ma20_rate"] = stat.get("breadth_ma20_rate")
            result["sector_breadth_label"] = stat.get("breadth_label")
            result["sector_breadth_latest_date"] = stat.get("breadth_latest_date")
            result["sector_relation_quality_score"] = stat.get("relation_quality_score")
            result["sector_relation_quality_label"] = stat.get("relation_quality_label")
            result["sector_relation_verified_count"] = stat.get("relation_verified_count")
            result["sector_relation_weak_count"] = stat.get("relation_weak_count")
            result["final_score"] = round(as_float(result.get("rank_score"), 0.0) + stat["sector_score"] * 0.2, 1)
            apply_result_market_context(result, stat, scan_type, "sector", 0.85)
            attach_scan_explanation(result)

        pool["sector_stats"] = [
            stat for stat in sector_overview
            if stat["sector"] in seen_sectors
        ]


def apply_concept_resonance(pools, concept_overview):
    stats_by_concept = {item["concept"]: item for item in concept_overview}
    for scan_type, pool in pools.items():
        seen_concepts = set()
        covered_count = 0
        for result in pool.get("results", []):
            concepts = result_concepts(result)
            if concepts:
                covered_count += 1
            concept_stats = [stats_by_concept[concept] for concept in concepts if concept in stats_by_concept]
            if not concept_stats:
                continue
            best = max(concept_stats, key=lambda stat: stat["concept_score"])
            seen_concepts.update(stat["concept"] for stat in concept_stats)
            result["concept_score"] = best["concept_score"]
            result["concept_signal_count"] = best["signal_count"]
            result["concept_opportunity_count"] = best["opportunity_count"]
            result["concept_bottom_div_count"] = best["bottom_div_count"]
            result["concept_risk_count"] = best["risk_count"]
            result["concept_avg_rank"] = best["avg_rank"]
            result["concept_latest_event"] = best["latest_event"]
            result["concept_focus"] = best["concept"]
            result["concept_member_count"] = best.get("market_member_count")
            result["concept_candidate_density"] = best.get("candidate_density")
            result["concept_opportunity_density"] = best.get("opportunity_density")
            result["concept_risk_density"] = best.get("risk_density")
            result["concept_width_score"] = best.get("width_score")
            result["concept_width_label"] = best.get("width_label")
            result["concept_candidate_width_label"] = best.get("candidate_width_label")
            result["concept_breadth_sample_count"] = best.get("breadth_sample_count")
            result["concept_breadth_up_rate"] = best.get("breadth_up_rate")
            result["concept_breadth_ma20_rate"] = best.get("breadth_ma20_rate")
            result["concept_breadth_label"] = best.get("breadth_label")
            result["concept_breadth_latest_date"] = best.get("breadth_latest_date")
            result["concept_relation_quality_score"] = best.get("relation_quality_score")
            result["concept_relation_quality_label"] = best.get("relation_quality_label")
            result["concept_relation_verified_count"] = best.get("relation_verified_count")
            result["concept_relation_weak_count"] = best.get("relation_weak_count")
            result["final_score"] = round(
                as_float(result.get("final_score"), as_float(result.get("rank_score"), 0.0))
                + best["concept_score"] * 0.12,
                1,
            )
            apply_result_market_context(result, best, scan_type, "concept", 0.45)
            attach_scan_explanation(result)

        pool["concept_stats"] = [
            stat for stat in concept_overview
            if stat["concept"] in seen_concepts
        ]
        pool["concept_coverage"] = {
            "covered_count": covered_count,
            "total_count": len(pool.get("results", [])),
            "coverage_rate": round(covered_count * 100 / len(pool.get("results", [])), 1) if pool.get("results") else 0.0,
        }
