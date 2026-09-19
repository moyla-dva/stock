"""Central version metadata for data windows, scan rules, and snapshots."""

DATA_START_DATE = "2025-04-29"
DATA_ADJUST = "qfq"

SCAN_STRATEGY_VERSION = "2026.09.19.1"
SCAN_STRATEGY_LABEL = "C信号V2 P1-P12 + P19 修复观察 + 突破/破位口径修正"
SCAN_STRATEGY_NOTES = (
    "日线和分钟线统一使用前复权口径",
    "V2 独立许可接管扫描入池，旧 C 信号保留为对照证据",
    "C回/C突/C爆 统一经过 Plan Gate、结构止损、目标价和至少 2R 校验",
    "突破触发与破位风险均以今日之前形成的结构为参照（previous_upper/previous_lower/前20日）",
    "单股页交易计划与候选池共用同一 V2 许可契约（宏观否决、Plan Gate、结构止损）",
    "突破型目标价使用上方结构阻力，不再回退到已突破箱体上沿",
    "MA250、周线 MACD、MA60 和板块/概念环境只负责许可或否决",
    "K线包含处理、多周期矩形、破底翻、阻力强度进入结构事实层",
    "Exit Gate 输出观察、买入、减仓和卖出 marker 语义，评分只用于排序和解释",
    "底背离和 C修 进入独立修复观察状态，不再与入场许可混用",
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
