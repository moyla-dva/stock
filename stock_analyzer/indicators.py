"""Technical indicators used by the A-share analysis pipeline."""

import numpy as np


def calculate_kdj(df, period=9):
    low_list = df["low"].rolling(window=period, min_periods=1).min()
    high_list = df["high"].rolling(window=period, min_periods=1).max()
    denom = (high_list - low_list).replace(0, np.nan)
    rsv = (df["close"] - low_list) / denom * 100
    df["k"] = rsv.ewm(com=2, adjust=False).mean()
    df["d"] = df["k"].ewm(com=2, adjust=False).mean()
    df["j"] = 3 * df["k"] - 2 * df["d"]
    return df


def calculate_bull_bear_power(df):
    """Calculate Williams-style bull/bear power from each candle."""
    df["bull_power"] = (df["close"] - df["low"]).clip(lower=0)
    df["bear_power"] = (df["high"] - df["close"]).clip(lower=0)
    total_power = (df["bull_power"] + df["bear_power"]).replace(0, np.nan)
    df["bull_bear_balance"] = (
        (df["bull_power"] - df["bear_power"]) / total_power
    ).replace([np.inf, -np.inf], np.nan).fillna(0)
    df["bull_power_ma5"] = df["bull_power"].rolling(window=5, min_periods=1).mean()
    df["bear_power_ma5"] = df["bear_power"].rolling(window=5, min_periods=1).mean()
    df["bull_power_dominant"] = df["bull_power_ma5"] > df["bear_power_ma5"]
    df["bear_power_dominant"] = df["bear_power_ma5"] > df["bull_power_ma5"]
    return df


def calculate_williams_r(df, period=10):
    """Calculate Williams %R on a 0-100 scale where 50 is the center line."""
    highest_high = df["high"].rolling(window=period, min_periods=1).max()
    lowest_low = df["low"].rolling(window=period, min_periods=1).min()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    williams_r = ((highest_high - df["close"]) / denom * 100).replace(
        [np.inf, -np.inf],
        np.nan,
    )
    df["williams_r"] = williams_r.fillna(50)
    previous = df["williams_r"].shift(1)
    df["williams_r_cross_bull"] = (previous >= 50) & (df["williams_r"] < 50)
    df["williams_r_cross_bear"] = (previous <= 50) & (df["williams_r"] > 50)
    df["williams_r_center_side"] = np.where(
        df["williams_r"] < 50,
        "bull",
        np.where(df["williams_r"] > 50, "bear", "neutral"),
    )
    return df


def calculate_bollinger_bands(df, period=20, std_dev=2):
    df["boll_mid"] = df["close"].rolling(window=period).mean()
    df["boll_std"] = df["close"].rolling(window=period).std()
    df["upper_band"] = df["boll_mid"] + (df["boll_std"] * std_dev)
    df["lower_band"] = df["boll_mid"] - (df["boll_std"] * std_dev)
    return df


def calculate_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = (dif - dea) * 2
    return dif, dea, macd_hist


def calculate_cci(df, period=14):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(window=period).mean()

    def mad(x):
        return np.mean(np.abs(x - np.mean(x)))

    mad_values = tp.rolling(window=period).apply(mad, raw=True)
    denom = (0.015 * mad_values).replace(0, np.nan)
    return (tp - sma) / denom


def calculate_adx(df, period=14):
    df["h-l"] = df["high"] - df["low"]
    df["h-pc"] = abs(df["high"] - df["close"].shift(1))
    df["l-pc"] = abs(df["low"] - df["close"].shift(1))
    df["tr"] = df[["h-l", "h-pc", "l-pc"]].max(axis=1)

    df["up_move"] = df["high"] - df["high"].shift(1)
    df["down_move"] = df["low"].shift(1) - df["low"]

    df["pdm"] = np.where((df["up_move"] > df["down_move"]) & (df["up_move"] > 0), df["up_move"], 0)
    df["ndm"] = np.where((df["down_move"] > df["up_move"]) & (df["down_move"] > 0), df["down_move"], 0)

    tr_smooth = df["tr"].rolling(window=period).sum()
    pdm_smooth = df["pdm"].rolling(window=period).sum()
    ndm_smooth = df["ndm"].rolling(window=period).sum()

    tr_denom = tr_smooth.replace(0, np.nan)
    df["pdi"] = (pdm_smooth / tr_denom) * 100
    df["ndi"] = (ndm_smooth / tr_denom) * 100

    di_denom = (df["pdi"] + df["ndi"]).replace(0, np.nan)
    dx = (abs(df["pdi"] - df["ndi"]) / di_denom) * 100
    df["adx"] = dx.rolling(window=period).mean()
    return df


def detect_divergence(df, window=15):
    df["is_bottom_divergence"] = False
    df["is_top_divergence"] = False
    low_price = df["low"]
    dif = df["dif"]

    for i in range(window, len(df)):
        price_new_low = low_price.iloc[i] == low_price.iloc[i - window:i + 1].min()
        dif_not_low = dif.iloc[i] > dif.iloc[i - window:i + 1].min()
        dif_is_negative = dif.iloc[i] < 0
        if price_new_low and dif_not_low and dif_is_negative:
            df.at[i, "is_bottom_divergence"] = True

        price_new_high = df["high"].iloc[i] == df["high"].iloc[i - window:i + 1].max()
        dif_not_high = dif.iloc[i] < dif.iloc[i - window:i + 1].max()
        dif_is_positive = dif.iloc[i] > 0
        if price_new_high and dif_not_high and dif_is_positive:
            df.at[i, "is_top_divergence"] = True
    return df


def calculate_anchored_vwap(df):
    """Calculate anchored VWAP from the lowest low in the current data window."""
    if df is None:
        return None

    try:
        if df.empty:
            df["vwap"] = np.nan
            return df

        if "low" not in df.columns or "volume" not in df.columns:
            df["vwap"] = np.nan
            return df

        min_idx = df["low"].idxmin()
        df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
        df["pv"] = df["typical_price"] * df["volume"]
        df["vwap"] = np.nan

        subset = df.loc[min_idx:].copy()
        if subset.empty or subset["volume"].sum() == 0:
            return df

        subset["cum_pv"] = subset["pv"].cumsum()
        subset["cum_vol"] = subset["volume"].cumsum().replace(0, np.nan)
        subset["vwap"] = subset["cum_pv"] / subset["cum_vol"]
        df.loc[min_idx:, "vwap"] = subset["vwap"]
    except Exception:
        df["vwap"] = np.nan
    return df
