"""Composite strategy layer built from the existing signal families."""

import pandas as pd

from stock_analyzer.signals import calculate_bias20


def _column(df, name, default=False):
    if name in df.columns:
        return df[name]
    if isinstance(default, pd.Series):
        return default.reindex(df.index)
    return pd.Series(default, index=df.index)


def _as_bool(series):
    return series.fillna(False).astype(bool)


def _rolling_any(series, window):
    return _as_bool(series).astype(int).rolling(window=window, min_periods=1).max().astype(bool)


def _score(conditions, index):
    result = pd.Series(0, index=index)
    for condition in conditions:
        result = result + _as_bool(condition).astype(int)
    return result


def _cooldown(mask, bars):
    values = _as_bool(mask).tolist()
    result = []
    last_fire = -bars - 1
    for pos, value in enumerate(values):
        fire = bool(value) and pos - last_fire > bars
        result.append(fire)
        if fire:
            last_fire = pos
    return pd.Series(result, index=mask.index)


def _position_strategy_events(df, entry_raw, entry_type_raw, conditions, entry_cooldown=3):
    entry_values = _as_bool(entry_raw).tolist()
    entry_result = []
    entry_types = []
    warn_result = []
    exit_result = []
    risk_types = []
    risk_reasons = []
    in_position = False
    entry_price = None
    peak_price = None
    entry_pos = -1
    last_entry = -entry_cooldown - 1
    warned = False

    for pos, entry in enumerate(entry_values):
        idx = df.index[pos]
        entry_fire = False
        warn_fire = False
        exit_fire = False
        risk_type = ""
        risk_reason = ""

        if not in_position and entry and pos - last_entry > entry_cooldown:
            entry_fire = True
            in_position = True
            entry_price = float(df.at[idx, "close"])
            peak_price = float(df.at[idx, "high"])
            entry_pos = pos
            last_entry = pos
            warned = False
        elif in_position:
            close = float(df.at[idx, "close"])
            high = float(df.at[idx, "high"])
            peak_price = max(peak_price, high)
            position_ret = (close - entry_price) / entry_price * 100
            peak_ret = (peak_price - entry_price) / entry_price * 100
            drawdown = (close - peak_price) / peak_price * 100 if peak_price else 0
            held_bars = pos - entry_pos

            stop_loss = (
                position_ret <= -5
                or (
                    position_ret <= -3
                    and bool(conditions["ma20_cross_down"].loc[idx])
                    and bool(conditions["macd_bear"].loc[idx])
                )
            )
            take_profit = (
                peak_ret >= 8
                and (
                    drawdown <= -3
                    or bool(conditions["ma5_cross_down"].loc[idx])
                    or bool(conditions["macd_cross_down"].loc[idx])
                )
            )
            trend_break = (
                held_bars >= 2
                and (
                    bool(conditions["dif_zero_cross_down"].loc[idx])
                    or (
                        bool(conditions["ma20_cross_down"].loc[idx])
                        and bool(conditions["macd_bear"].loc[idx])
                        and position_ret <= -3
                    )
                )
            )

            if stop_loss:
                exit_fire = True
                risk_type = "stop_loss"
                risk_reason = "止损"
            elif take_profit:
                exit_fire = True
                risk_type = "take_profit"
                risk_reason = "止盈"
            elif trend_break:
                exit_fire = True
                risk_type = "trend_break"
                risk_reason = "趋势破坏"
            else:
                top_div_warn = bool(conditions["recent_top_div"].loc[idx]) and (
                    position_ret >= 2
                    or bool(conditions["close_down"].loc[idx])
                    or bool(conditions["macd_bear"].loc[idx])
                )
                warn_fire = (
                    not warned
                    and held_bars >= 1
                    and (
                        top_div_warn
                        or (
                            (
                                bool(conditions["ma5_cross_down"].loc[idx])
                                or bool(conditions["ma20_cross_down"].loc[idx])
                                or bool(conditions["macd_cross_down"].loc[idx])
                            )
                            and (
                                position_ret <= -1.5
                                or drawdown <= -3
                                or bool(conditions["high_context"].loc[idx])
                            )
                        )
                    )
                )
                if warn_fire:
                    risk_type = "top_divergence" if top_div_warn else "warn"
                    risk_reason = "顶背离预警" if top_div_warn else "风险预警"
                    warned = True

            if exit_fire:
                in_position = False
                warned = False

        entry_result.append(entry_fire)
        entry_types.append(entry_type_raw.loc[idx] if entry_fire else "")
        warn_result.append(warn_fire)
        exit_result.append(exit_fire)
        risk_types.append(risk_type)
        risk_reasons.append(risk_reason)

    return {
        "entry": pd.Series(entry_result, index=df.index),
        "entry_type": pd.Series(entry_types, index=df.index),
        "warn": pd.Series(warn_result, index=df.index),
        "exit": pd.Series(exit_result, index=df.index),
        "risk_type": pd.Series(risk_types, index=df.index),
        "risk_reason": pd.Series(risk_reasons, index=df.index),
    }


def _reasons(reason_conditions, index):
    reason_conditions = [(label, _as_bool(condition)) for label, condition in reason_conditions]
    values = []
    for idx in index:
        row_reasons = [label for label, condition in reason_conditions if bool(condition.loc[idx])]
        values.append(" / ".join(row_reasons))
    return pd.Series(values, index=index)


def add_composite_strategy_columns(df):
    """Add layered strategy outputs without replacing the legacy signal columns."""
    bias20 = calculate_bias20(df)

    ma20_safe = df["ma20"].where(df["ma20"] != 0, df["close"])
    near_ma20 = ((df["close"] - df["ma20"]).abs() / ma20_safe).fillna(999) < 0.015

    vwap = _column(df, "vwap", pd.NA)
    vwap_safe = vwap.where(vwap != 0)
    near_vwap = ((df["close"] - vwap).abs() / vwap_safe).fillna(999) < 0.015

    close_up = df["close"] > df["close"].shift(1)
    close_down = df["close"] < df["close"].shift(1)
    macd_bull = df["dif"] > df["dea"]
    macd_bear = df["dif"] < df["dea"]
    macd_cross_down = macd_bear & (df["dif"].shift(1) >= df["dea"].shift(1))
    dif_zero_cross_down = (df["dif"] < 0) & (df["dif"].shift(1) >= 0)
    ma5_cross_down = (df["close"] < df["ma5"]) & (df["close"].shift(1) >= df["ma5"].shift(1))
    ma20_cross_down = (df["close"] < df["ma20"]) & (df["close"].shift(1) >= df["ma20"].shift(1))

    efficiency_score = _column(df, "momentum_efficiency", df["custom"])
    efficiency_q80 = efficiency_score.rolling(window=20, min_periods=5).quantile(0.8)
    efficiency_high = (efficiency_score >= efficiency_q80) & (efficiency_score > 0)
    efficiency_acceleration = efficiency_score.diff().fillna(0)
    recent_bottom_div = _rolling_any(_column(df, "is_bottom_divergence"), 6)
    recent_top_div = _rolling_any(_column(df, "is_top_divergence"), 6)
    j_falling = (df["j"] < df["j"].shift(1)) & (df["j"].shift(1) < df["j"].shift(2))
    j_overheated = (df["j"] > 80) | ((df["j"].shift(1) > 80) & j_falling)
    prior_high_10 = df["high"].shift(1).rolling(window=10, min_periods=5).max()
    prior_breakout = (df["close"] > prior_high_10) & prior_high_10.notna()

    repair_impulse = _as_bool(_column(df, "is_b_point"))
    support_setup = near_ma20 | near_vwap
    trend_ok = _as_bool(_column(df, "trend_ok"))
    ma20_up = _as_bool(_column(df, "ma20_up"))
    volume_ok = df["volume"] > _column(df, "vol_ma20")

    setup_score = _score([
        repair_impulse,
        support_setup,
        recent_bottom_div,
        efficiency_high,
    ], df.index)
    confirm_score = _score([
        df["close"] >= df["ma20"] * 0.995,
        ma20_up,
        macd_bull,
        df["dif"] > 0,
        trend_ok,
        volume_ok,
    ], df.index)

    heat_bias = bias20 > 8
    touch_upper = _as_bool(_column(df, "touch_upper"))
    risk_break_score = _score([
        df["close"] < df["ma20"],
        macd_bear,
        _as_bool(_column(df, "break_ma5")),
        efficiency_score < 0,
    ], df.index)
    risk_heat_score = _score([
        heat_bias,
        j_overheated,
        touch_upper,
        recent_top_div,
    ], df.index)
    high_context = (risk_heat_score >= 2) | recent_top_div
    risk_score = (
        risk_break_score
        + _as_bool(risk_heat_score >= 2).astype(int)
        + _as_bool(recent_top_div & close_down).astype(int)
    ).clip(upper=5)

    old_gold_entry_raw = repair_impulse & recent_bottom_div
    old_pullback_entry_raw = _as_bool(_column(df, "is_pullback_b"))
    new_gold_entry_raw = _as_bool(_column(df, "new_is_b_point")) & recent_bottom_div
    new_pullback_entry_raw = _as_bool(_column(df, "new_is_pullback_b"))
    old_entry_raw = old_gold_entry_raw | old_pullback_entry_raw
    new_entry_raw = new_gold_entry_raw | new_pullback_entry_raw

    repair_confirm_raw = (
        repair_impulse
        & recent_bottom_div
        & (confirm_score >= 3)
        & (risk_break_score <= 1)
        & (risk_score <= 2)
        & ~macd_bear
    )
    pullback_setup_raw = (
        support_setup
        & (df["volume"] < _column(df, "vol_ma20"))
        & (df["close"] >= df["open"])
        & (df["close"] >= df["ma20"] * 0.995)
        & ma20_up
        & macd_bull
        & (bias20 < 15)
    )
    breakout_setup_raw = (
        close_up
        & prior_breakout
        & (df["close"] > df["ma20"])
        & ma20_up
        & macd_bull
        & (df["dif"] > 0)
        & (efficiency_score > 0)
        & (efficiency_acceleration > 0)
        & efficiency_high
        & volume_ok
        & trend_ok
        & (bias20 < 12)
        & ~recent_top_div
    )
    pullback_entry_raw = (
        pullback_setup_raw
        & (confirm_score >= 3)
        & (risk_break_score <= 1)
        & (risk_score <= 2)
    )
    breakout_entry_raw = (
        breakout_setup_raw
        & (confirm_score >= 4)
        & (risk_score <= 1)
    )
    entry_raw = repair_confirm_raw | pullback_entry_raw | breakout_entry_raw

    entry_type_raw = pd.Series("", index=df.index)
    entry_type_raw[pullback_entry_raw] = "pullback"
    entry_type_raw[breakout_entry_raw] = "breakout"
    entry_type_raw[repair_confirm_raw] = "repair-confirm"

    position_events = _position_strategy_events(
        df,
        entry_raw,
        entry_type_raw,
        {
            "ma5_cross_down": ma5_cross_down,
            "ma20_cross_down": ma20_cross_down,
            "macd_cross_down": macd_cross_down,
            "dif_zero_cross_down": dif_zero_cross_down,
            "macd_bear": macd_bear,
            "high_context": high_context,
            "recent_top_div": recent_top_div,
            "close_down": close_down,
        },
    )
    entry_signal = position_events["entry"]
    entry_type = position_events["entry_type"]
    warn_signal = position_events["warn"]
    exit_signal = position_events["exit"]
    risk_signal = exit_signal | warn_signal

    df["composite_setup_score"] = setup_score
    df["composite_confirm_score"] = confirm_score
    df["composite_risk_score"] = risk_score
    df["composite_risk_break_score"] = risk_break_score
    df["composite_risk_heat_score"] = risk_heat_score
    df["composite_watch"] = setup_score >= 2
    df["composite_efficiency_score"] = efficiency_score
    df["composite_prior_high_10"] = prior_high_10
    df["composite_prior_breakout"] = prior_breakout
    df["composite_repair_impulse"] = repair_impulse
    df["composite_repair_confirm"] = repair_confirm_raw
    df["composite_pullback_setup"] = pullback_setup_raw
    df["composite_breakout_setup"] = breakout_setup_raw
    df["old_is_entry"] = old_entry_raw
    df["new_is_entry"] = new_entry_raw
    df["opt_is_entry"] = _as_bool(_column(df, "opt_is_b_point")) | _as_bool(_column(df, "opt_is_pullback_b"))
    df["composite_entry"] = entry_signal
    df["composite_entry_type"] = entry_type
    df["composite_risk_warn"] = warn_signal
    df["composite_exit"] = exit_signal
    df["composite_risk"] = risk_signal
    df["composite_risk_type"] = position_events["risk_type"]
    df["composite_exit_type"] = position_events["risk_type"].where(exit_signal, "")

    df["composite_entry_reason"] = _reasons([
        ("底背离", recent_bottom_div),
        ("修复异动", repair_impulse),
        ("修复确认", repair_confirm_raw),
        ("旧B诊断", old_entry_raw),
        ("新B诊断", new_entry_raw),
        ("趋势有效", trend_ok),
        ("MA20向上", ma20_up),
        ("MACD多头", macd_bull),
        ("量能确认", volume_ok),
        ("缩量回踩", pullback_entry_raw),
        ("前高突破", breakout_entry_raw),
    ], df.index)
    risk_detail_reason = _reasons([
        ("高位过热", risk_heat_score >= 2),
        ("顶背离", recent_top_div),
        ("跌破MA5", ma5_cross_down | _as_bool(_column(df, "break_ma5"))),
        ("跌破MA20", ma20_cross_down | (df["close"] < df["ma20"])),
        ("MACD转弱", macd_cross_down | macd_bear),
        ("动量效率转负", efficiency_score < 0),
    ], df.index)
    df["composite_risk_reason"] = position_events["risk_reason"]
    df.loc[df["composite_risk"], "composite_risk_reason"] = (
        df.loc[df["composite_risk"], "composite_risk_reason"]
        + " / "
        + risk_detail_reason.loc[df["composite_risk"]]
    )

    return df
