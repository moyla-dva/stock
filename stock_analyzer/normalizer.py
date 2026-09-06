"""Normalize market data from provider-specific shapes to the app OHLCV schema."""

import pandas as pd


PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def normalize_price_frame(df):
    """Return a sorted OHLCV DataFrame with canonical column names."""
    if df is None or df.empty:
        return df

    df = df.copy()
    if "日期" in df.columns:
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        })
    elif "时间" in df.columns:
        df = df.rename(columns={
            "时间": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        })
    elif "day" in df.columns:
        df = df.rename(columns={"day": "date"})
    elif "date" in df.columns and "amount" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"amount": "volume"})

    missing = [column for column in PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"行情数据缺少必要字段: {', '.join(missing)}")

    df = df[PRICE_COLUMNS]
    df["date"] = pd.to_datetime(df["date"])
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df.dropna(subset=["date", "open", "high", "low", "close"], inplace=True)
    df["volume"] = df["volume"].fillna(0)
    df = df.sort_values("date")
    df.reset_index(drop=True, inplace=True)
    return df
