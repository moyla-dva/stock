"""High-level analysis pipeline orchestration."""

import numpy as np

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.data_fetcher import fetch_stock_history
from stock_analyzer.indicators import (
    calculate_adx,
    calculate_anchored_vwap,
    calculate_bollinger_bands,
    calculate_bull_bear_power,
    calculate_cci,
    calculate_kdj,
    calculate_macd,
    calculate_williams_r,
    detect_divergence,
)
from stock_analyzer.market_data_identity import (
    attach_market_data_identity,
    frame_market_data_identity,
    market_data_revision,
)
from stock_analyzer.normalizer import normalize_price_frame
from stock_analyzer.signals import add_signal_columns
from stock_analyzer.versioning import DATA_ADJUST


def add_indicator_columns(df, fill_initial_ma20=False):
    """Add the app's current indicator columns to a normalized OHLCV DataFrame."""
    df["price_delta"] = df["close"].diff()
    vol_denom = df["volume"].replace(0, np.nan)
    df["custom"] = (df["price_delta"] / vol_denom) * 1000000
    df["custom"] = df["custom"].fillna(0)
    custom_mean = df["custom"].rolling(window=20, min_periods=5).mean()
    custom_std = df["custom"].rolling(window=20, min_periods=5).std().replace(0, np.nan)
    df["custom_z"] = ((df["custom"] - custom_mean) / custom_std).clip(-5, 5).fillna(0)

    df["return_pct"] = df["close"].pct_change() * 100
    volume_ma20 = df["volume"].rolling(window=20, min_periods=5).mean().replace(0, np.nan)
    df["volume_ratio"] = (df["volume"] / volume_ma20).replace([np.inf, -np.inf], np.nan).fillna(0)
    volatility20 = df["return_pct"].rolling(window=20, min_periods=5).std().replace(0, np.nan)
    df["momentum_efficiency"] = (
        (df["return_pct"] / volatility20) * df["volume_ratio"]
    ).replace([np.inf, -np.inf], np.nan).clip(-5, 5).fillna(0)

    df["dif"], df["dea"], df["macd_hist"] = calculate_macd(df)
    df = calculate_bull_bear_power(df)
    df = calculate_williams_r(df)
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()
    if fill_initial_ma20:
        df["ma20"] = df["ma20"].fillna(df["close"])

    df = calculate_bollinger_bands(df)
    df["cci"] = calculate_cci(df)
    df = calculate_kdj(df)
    df = calculate_adx(df)
    df = detect_divergence(df)
    df = calculate_anchored_vwap(df)
    return df


def prepare_analysis_frame(df, fill_initial_ma20=False):
    """Normalize raw provider data, add indicators, and add signal columns."""
    df = normalize_price_frame(df)
    if df is None or df.empty:
        return None

    identity = frame_market_data_identity(df)
    attach_market_data_identity(
        df,
        data_source=identity.get("data_source") or "unknown",
        bar_state=identity.get("bar_state") or "unknown",
        generated_at=identity.get("generated_at") or "unknown",
        cache_status=identity.get("cache_status") or "unknown",
        cache_written_at=identity.get("cache_written_at"),
        data_revision=market_data_revision(df),
    )
    identity = frame_market_data_identity(df)

    df = add_indicator_columns(df, fill_initial_ma20=fill_initial_ma20)
    df_display = df.copy()
    df_display.reset_index(drop=True, inplace=True)
    df_display = add_signal_columns(df_display)
    attach_market_data_identity(
        df_display,
        data_source=identity.get("data_source") or "unknown",
        bar_state=identity.get("bar_state") or "unknown",
        generated_at=identity.get("generated_at") or "unknown",
        cache_status=identity.get("cache_status") or "unknown",
        cache_written_at=identity.get("cache_written_at"),
        data_revision=identity.get("data_revision") or "unknown",
    )
    return df_display


def build_analysis_frame(
    code,
    days=120,
    start_date=None,
    fill_initial_ma20=False,
    use_cache=False,
    force_refresh=False,
    use_disable_proxies=False,
    logger=None,
    verbose=False,
    adjust=DATA_ADJUST,
    fetch_diagnostics=None,
):
    """Fetch and prepare the analysis DataFrame for a stock code."""
    code = normalize_code(code)
    if not code:
        return None

    df = fetch_stock_history(
        code,
        days=days,
        start_date=start_date,
        adjust=adjust,
        use_cache=use_cache,
        force_refresh=force_refresh,
        use_disable_proxies=use_disable_proxies,
        logger=logger,
        verbose=verbose,
        diagnostics=fetch_diagnostics,
    )
    if df is None or df.empty:
        return None
    return prepare_analysis_frame(df, fill_initial_ma20=fill_initial_ma20)
