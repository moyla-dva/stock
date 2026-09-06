"""Build structure, resonance, and calibration data for the scan workspace."""

from stock_analyzer import catalog
from stock_analyzer.backtest import ENTRY_MODEL_EVENT_CLOSE
from stock_analyzer.concept_graph import concept_graph_status
from stock_analyzer.market_breadth import apply_market_breadth_to_overview
from stock_analyzer.market_structure import (
    apply_market_structure_scores,
    build_market_structure_overview,
    sort_market_structure_overview,
)
from stock_analyzer.market_structure_sources import annotate_market_structure_sources
from stock_analyzer.resonance_calibration import (
    DEFAULT_REPLAY_HORIZONS,
    REPLAY_BUCKETS,
    build_replay_calibration,
)
from stock_analyzer.scan_market_context import apply_board_market_to_overview
from stock_analyzer.scan_resonance import (
    apply_concept_resonance,
    apply_score_confidence,
    apply_sector_resonance,
    build_concept_overview,
    build_resonance_calibration,
    build_sector_overview,
)


def _deferred_replay_calibration(horizons=DEFAULT_REPLAY_HORIZONS, entry_model=ENTRY_MODEL_EVENT_CLOSE):
    """Return the replay-calibration shape without reading historical price caches."""
    return {
        "method": "deferred",
        "note": "首屏轻量载入暂不读取本地日线缓存；需要时可刷新完整回放校准",
        "entry_model": entry_model,
        "horizons": list(horizons),
        "candidate_count": 0,
        "requested_count": 0,
        "buckets": [
            {
                "key": bucket["key"],
                "label": bucket["label"],
                "candidate_count": 0,
                "sector_count": 0,
                "horizons": {
                    str(horizon): {
                        "sample_count": 0,
                        "win_rate": None,
                        "avg_ret": None,
                        "worst_ret": None,
                        "avg_worst_ret": None,
                    }
                    for horizon in horizons
                },
                "sample_quality": "待回放",
            }
            for bucket in REPLAY_BUCKETS
        ],
    }


def build_workspace_structure(
    pools,
    profile_cache,
    start_date=None,
    board_market_reader=None,
    include_replay=True,
    replay_max_candidates=800,
    replay_entry_model=ENTRY_MODEL_EVENT_CLOSE,
    include_market_universe=True,
    include_market_breadth=True,
):
    """Enrich scan pools with market structure, resonance, and replay confidence."""
    sector_candidate_overview = build_sector_overview(pools)
    concept_candidate_overview = build_concept_overview(pools)
    if include_market_universe:
        sector_overview, concept_overview = build_market_structure_overview(
            sector_candidate_overview,
            concept_candidate_overview,
            profile_cache,
        )
    else:
        sector_overview = sector_candidate_overview
        concept_overview = concept_candidate_overview

    if include_market_breadth:
        apply_market_breadth_to_overview(sector_overview, concept_overview, profile_cache)

    apply_board_market_to_overview(
        sector_overview,
        "sector",
        "industry",
        board_market_reader=board_market_reader,
    )
    apply_sector_resonance(pools, sector_overview)

    apply_board_market_to_overview(
        concept_overview,
        "concept",
        "concept",
        board_market_reader=board_market_reader,
    )
    apply_concept_resonance(pools, concept_overview)
    apply_market_structure_scores(sector_overview, "sector")
    apply_market_structure_scores(concept_overview, "concept")
    graph_status = concept_graph_status(cache_dir=catalog.CATALOG_CACHE_DIR)
    graph_status["status"] = "experimental"
    graph_status["experimental"] = True
    market_structure_meta = annotate_market_structure_sources(
        sector_overview,
        concept_overview,
        profile_cache if include_market_universe else {},
        concept_graph_status=graph_status,
    )
    sector_overview = sort_market_structure_overview(sector_overview)
    concept_overview = sort_market_structure_overview(concept_overview)

    resonance_calibration = build_resonance_calibration(pools)
    replay_calibration = (
        build_replay_calibration(
            pools,
            start_date=start_date,
            max_candidates=replay_max_candidates,
            entry_model=replay_entry_model,
        )
        if include_replay
        else _deferred_replay_calibration(entry_model=replay_entry_model)
    )
    apply_score_confidence(pools, replay_calibration=replay_calibration)

    return {
        "sector_overview": sector_overview,
        "concept_overview": concept_overview,
        "concept_graph_status": graph_status,
        "market_structure_meta": market_structure_meta,
        "resonance_calibration": resonance_calibration,
        "replay_calibration": replay_calibration,
    }
