"""Compatibility facade for scan resonance helpers."""

from stock_analyzer.scan_buckets import RESONANCE_CALIBRATION_BUCKETS, resonance_bucket
from stock_analyzer.scan_confidence import apply_score_confidence, build_resonance_calibration
from stock_analyzer.scan_overview import (
    apply_market_universe_to_overview,
    build_concept_overview,
    build_overview,
    build_sector_overview,
    concept_resonance_score,
    sector_resonance_score,
)
from stock_analyzer.scan_resonance_scoring import apply_concept_resonance, apply_sector_resonance
