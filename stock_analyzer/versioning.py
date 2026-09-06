"""Central version metadata for data windows, scan rules, and snapshots."""

DATA_START_DATE = "2025-04-29"
DATA_ADJUST = "qfq"

SCAN_STRATEGY_VERSION = "2026.09.06.1"
SCAN_STRATEGY_LABEL = "前复权日线 + C观/C回/C突校准"
SCAN_STRATEGY_NOTES = (
    "日线和分钟线统一使用前复权口径",
    "C观提高修复确认门槛，C底只作为修复观察",
    "C突必须突破近十日已形成前高，避免把普通趋势确认误标为突破",
    "综合层使用归一化动量效率因子，旧 custom 只保留为诊断证据",
    "风险分拆分为破位风险和过热风险，过热不再单独等同强风险",
    "交易许可使用硬门控，评分只用于排序和解释",
)

SCAN_EXPLANATION_VERSION = 1
SCAN_SNAPSHOT_SCHEMA_VERSION = 1


def build_strategy_meta(start_date=None):
    return {
        "strategy_version": SCAN_STRATEGY_VERSION,
        "strategy_label": SCAN_STRATEGY_LABEL,
        "data_start_date": start_date or DATA_START_DATE,
        "data_adjust": DATA_ADJUST,
        "snapshot_schema_version": SCAN_SNAPSHOT_SCHEMA_VERSION,
        "explanation_version": SCAN_EXPLANATION_VERSION,
        "notes": list(SCAN_STRATEGY_NOTES),
    }
