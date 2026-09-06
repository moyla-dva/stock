"""Shared score bucket definitions for scan resonance and replay calibration."""

from stock_analyzer.scan_common import as_float


RESONANCE_CALIBRATION_BUCKETS = (
    {"key": "hot", "label": "75-100", "min": 75, "max": 100.01},
    {"key": "strong", "label": "50-75", "min": 50, "max": 75},
    {"key": "watch", "label": "25-50", "min": 25, "max": 50},
    {"key": "cold", "label": "0-25", "min": 0, "max": 25},
)


def resonance_bucket(score):
    score = as_float(score, 0.0)
    for bucket in RESONANCE_CALIBRATION_BUCKETS:
        if bucket["min"] <= score < bucket["max"]:
            return bucket["key"]
    return RESONANCE_CALIBRATION_BUCKETS[-1]["key"]
