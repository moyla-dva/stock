import pandas as pd


LEGACY_BOOLEAN_COLUMNS = (
    "is_b_point",
    "is_pullback_b",
    "is_s_point",
    "touch_upper",
    "break_ma5",
    "is_bottom_divergence",
    "is_top_divergence",
    "new_is_b_point",
    "new_is_pullback_b",
    "new_is_s_point",
    "opt_is_b_point",
    "opt_is_pullback_b",
    "opt_is_s_warn",
    "opt_is_s_confirm",
    "opt_is_s_point",
    "composite_entry",
    "composite_risk_warn",
    "composite_exit",
    "composite_risk",
)

LEGACY_TEXT_COLUMNS = (
    "composite_entry_type",
    "composite_risk_type",
    "composite_exit_type",
    "composite_entry_reason",
    "composite_risk_reason",
)


def add_legacy_signal_columns(frame):
    """Add legacy chart/snapshot columns only when a test exercises compatibility paths."""
    for column in LEGACY_BOOLEAN_COLUMNS:
        if column not in frame.columns:
            frame[column] = False
    for column in LEGACY_TEXT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def add_legacy_scores(frame, *, setup=0, confirm=0, risk=0, watch=False, break_score=None, heat_score=None):
    rows = len(frame)
    frame["composite_setup_score"] = [setup] * rows
    frame["composite_confirm_score"] = [confirm] * rows
    frame["composite_risk_score"] = [risk] * rows
    frame["composite_watch"] = [watch] * rows
    if break_score is not None:
        frame["composite_risk_break_score"] = [break_score] * rows
    if heat_score is not None:
        frame["composite_risk_heat_score"] = [heat_score] * rows
    return frame


def apply_legacy_entry(
    frame,
    *,
    index=-1,
    entry_type="pullback",
    reason="回踩确认",
    setup=None,
    confirm=None,
    risk=None,
    watch=None,
):
    add_legacy_signal_columns(frame)
    if any(value is not None for value in (setup, confirm, risk, watch)):
        add_legacy_scores(
            frame,
            setup=0 if setup is None else setup,
            confirm=0 if confirm is None else confirm,
            risk=0 if risk is None else risk,
            watch=False if watch is None else watch,
        )
    row_index = len(frame) + index if index < 0 else index
    frame.loc[row_index, "composite_entry"] = True
    frame.loc[row_index, "composite_entry_type"] = entry_type
    frame.loc[row_index, "composite_entry_reason"] = reason
    return frame


def mark_legacy_signals(frame, marks):
    add_legacy_signal_columns(frame)
    for index, columns in marks.items():
        row_index = len(frame) + index if index < 0 else index
        for column in columns:
            frame.loc[row_index, column] = True
    return frame


def build_minimal_signal_frame(rows=10, *, start="2026-01-01"):
    frame = pd.DataFrame({
        "date": pd.date_range(start, periods=rows, freq="D"),
        "open": [10.0] * rows,
        "high": [10.5] * rows,
        "low": [9.8] * rows,
        "close": [10.0 + i * 0.1 for i in range(rows)],
        "custom": [0.0] * rows,
        "dif": [0.0] * rows,
        "dea": [0.0] * rows,
        "macd_hist": [0.0] * rows,
        "ma20": [10.0] * rows,
        "vwap": [10.0] * rows,
    })
    return add_legacy_signal_columns(frame)
