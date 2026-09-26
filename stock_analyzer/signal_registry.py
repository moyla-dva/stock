"""Central registry for scan pool and signal-key contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanPoolDefinition:
    key: str
    title: str
    signal_keys: tuple
    lookback: int = 0
    groups: tuple = ()

    def as_scan_config(self):
        return {
            "groups": tuple(self.groups),
            "keys": set(self.signal_keys),
            "lookback": self.lookback,
            "title": self.title,
        }


SCAN_POOL_DEFINITIONS = (
    ScanPoolDefinition(
        key="opportunity",
        title="参与候选",
        signal_keys=(
            "v2_ignition",
            "v2_attack_day",
            "v2_bear_trap_recovery",
            "v2_breakout",
            "v2_pullback",
            "v2_structure_candidate",
        ),
    ),
    ScanPoolDefinition(
        key="risk",
        title="风险验证",
        signal_keys=(
            "v2_exit_gate_sell",
            "v2_strong_resistance_scale_out",
            "v2_risk_break",
            "v2_risk_heat",
            "v2_top_fractal_observe",
            "v2_top_fractal_risk",
        ),
    ),
    ScanPoolDefinition(
        key="bottom_div",
        title="修复观察",
        signal_keys=(
            "v2_repair_watch",
            "v2_bottom_research",
            "v2_bearish_new_low",
        ),
        lookback=2,
    ),
)


EVENT_WEIGHT_DEFINITIONS = {
    "v2_ignition": 28,
    "v2_attack_day": 24,
    "v2_structure_candidate": 16,
    "v2_bottom_research": 12,
    "v2_repair_watch": 14,
    "v2_bearish_new_low": 10,
    "v2_top_fractal_observe": 8,
    "v2_top_fractal_risk": 8,
    "v2_strong_resistance_scale_out": 18,
    "v2_exit_gate_sell": 24,
    "v2_bear_trap_recovery": 20,
    "v2_breakout": 18,
    "v2_pullback": 16,
    "v2_risk_break": 20,
    "v2_risk_heat": 14,
}


SIGNAL_REASON_ALIASES = {
    "c_pullback": {
        "labels": ("C回",),
        "keys": ("v2_pullback",),
    },
    "c_breakout": {
        "labels": ("C突",),
        "keys": ("v2_breakout", "v2_bear_trap_recovery"),
    },
    "c_attack": {
        "labels": ("C爆",),
        "keys": ("v2_attack_day", "v2_ignition"),
    },
}


def build_scan_config():
    return {definition.key: definition.as_scan_config() for definition in SCAN_POOL_DEFINITIONS}


def build_event_weights():
    return dict(EVENT_WEIGHT_DEFINITIONS)


def scan_pool_keys():
    return tuple(definition.key for definition in SCAN_POOL_DEFINITIONS)


def signal_keys_for_reason(reason):
    alias = SIGNAL_REASON_ALIASES.get(str(reason or "").strip())
    if not alias:
        return set()
    return set(alias.get("keys") or ())


def signal_labels_for_reason(reason):
    alias = SIGNAL_REASON_ALIASES.get(str(reason or "").strip())
    if not alias:
        return set()
    return set(alias.get("labels") or ())
