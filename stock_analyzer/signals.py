"""Signal column calculations shared by chart analysis and batch scanning."""

import numpy as np
import pandas as pd


def calculate_bias20(df):
    """Calculate MA20 bias with the same NaN/zero protection used by the app."""
    ma20_safe = df["ma20"].replace(0, np.nan)
    bias20 = np.where(
        ma20_safe.notna(),
        (df["close"] - df["ma20"]) / ma20_safe * 100,
        0,
    )
    return pd.Series(bias20, index=df.index)


def add_signal_columns(df_display):
    """Add all current B/S signal columns used by the web chart and scanner."""
    window_size = 5
    rolling_max = df_display["custom"].rolling(window=window_size).max()
    rolling_min = df_display["custom"].rolling(window=window_size).min()
    bias20 = calculate_bias20(df_display)
    custom_q_high = df_display["custom"].rolling(window=20).quantile(0.8)
    custom_q_low = df_display["custom"].rolling(window=20).quantile(0.2)

    df_display["is_b_point"] = (
        (df_display["close"] > df_display["close"].shift(1))
        & (df_display["custom"] > 0)
        & (df_display["custom"] == rolling_max)
        & (bias20 < 15)
    )

    df_display["vol_ma20"] = df_display["volume"].rolling(window=20).mean()
    ma20_for_near = df_display["ma20"].replace(0, np.nan).fillna(df_display["close"])
    near_ma20 = (abs(df_display["close"] - df_display["ma20"]) / ma20_for_near) < 0.015

    near_vwap = False
    if "vwap" in df_display.columns:
        near_vwap = (abs(df_display["close"] - df_display["vwap"]) / df_display["vwap"]) < 0.015

    is_shrink_vol = df_display["volume"] < df_display["vol_ma20"]
    is_stable = df_display["close"] >= df_display["open"]

    df_display["is_pullback_b"] = (
        (near_ma20 | near_vwap)
        & is_shrink_vol
        & is_stable
        & (df_display["close"] > df_display["ma20"])
    )

    df_display["is_s_point"] = (
        (df_display["close"] < df_display["close"].shift(1))
        & (df_display["custom"] < 0)
        & (df_display["custom"] == rolling_min)
    )

    df_display["touch_upper"] = df_display["high"] >= df_display["upper_band"]
    df_display["break_ma5"] = df_display["close"] < df_display["ma5"]
    df_display["ma20_up"] = df_display["ma20"] > df_display["ma20"].shift(3)
    df_display["custom_acceleration"] = df_display["custom"].diff()

    df_display["new_is_b_point"] = (
        (df_display["close"] > df_display["close"].shift(1))
        & (df_display["close"] > df_display["ma20"])
        & df_display["ma20_up"]
        & (df_display["dif"] > df_display["dea"])
        & (df_display["dif"] > 0)
        & (df_display["custom"] > 0)
        & (df_display["custom_acceleration"] > 0)
        & (df_display["volume"] > df_display["vol_ma20"])
        & (bias20 < 15)
    )

    df_display["new_is_pullback_b"] = (
        (near_ma20 | near_vwap)
        & is_shrink_vol
        & is_stable
        & (df_display["close"] >= df_display["ma20"] * 0.995)
        & df_display["ma20_up"]
        & (df_display["dif"] > df_display["dea"])
        & (bias20 < 15)
    )

    df_display["new_is_s_point"] = (
        (df_display["close"] < df_display["close"].shift(1))
        & (df_display["dif"] < df_display["dea"])
        & (df_display["close"] < df_display["ma20"])
        & (df_display["break_ma5"] | df_display["touch_upper"])
    )

    df_display["trend_ok"] = df_display["adx"] >= 15
    df_display["opt_is_b_point"] = (
        df_display["trend_ok"]
        & (df_display["close"] > df_display["close"].shift(1))
        & (df_display["close"] >= df_display["ma20"] * 0.995)
        & df_display["ma20_up"]
        & (df_display["dif"] > df_display["dea"])
        & (df_display["dif"] > 0)
        & (df_display["custom"] > 0)
        & (df_display["custom_acceleration"] >= 0)
        & (df_display["custom_acceleration"] > df_display["custom_acceleration"].shift(1))
        & (df_display["custom"] >= custom_q_high)
        & (df_display["volume"] > df_display["vol_ma20"])
        & (bias20 < 15)
    )

    df_display["opt_is_pullback_b"] = (
        df_display["trend_ok"]
        & (near_ma20 | near_vwap)
        & is_shrink_vol
        & is_stable
        & (df_display["close"] >= df_display["ma20"] * 0.995)
        & df_display["ma20_up"]
        & (df_display["dif"] > df_display["dea"])
        & (bias20 < 15)
    )

    df_display["opt_is_s_warn"] = (
        (df_display["custom"] < 0)
        & (df_display["custom"] <= custom_q_low)
        & df_display["break_ma5"]
        & (df_display["j"] > 80)
        & (df_display["j"] < df_display["j"].shift(1))
        & (df_display["j"] < df_display["j"].shift(2))
        & (df_display["custom"] < df_display["custom"].shift(1))
    )

    df_display["opt_is_s_confirm"] = (
        (df_display["close"] < df_display["ma20"])
        & (df_display["dif"] < df_display["dea"])
        & (df_display["custom"] < 0)
        & (df_display["break_ma5"] | df_display["touch_upper"])
    )

    df_display["opt_is_s_point"] = df_display["opt_is_s_warn"] | df_display["opt_is_s_confirm"]

    return df_display
