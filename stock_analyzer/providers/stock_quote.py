"""Tencent realtime quote helpers for one-off current-day bars."""

import logging

import pandas as pd
import requests

from stock_analyzer.code_utils import normalize_code
from stock_analyzer.provider_network import configure_default_socket_timeout
from stock_analyzer.providers.stock_history import (
    market_symbol_for_tx,
    tencent_volume_to_shares,
)

LOGGER = logging.getLogger(__name__)

QUOTE_URL = "https://qt.gtimg.cn/q="


def _log(logger, level, message):
    target = logger or LOGGER
    getattr(target, level)(message)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def fetch_quote_text(symbols, timeout=None):
    symbols = [symbol for symbol in (symbols or []) if symbol]
    if not symbols:
        return ""
    response = requests.get(QUOTE_URL + ",".join(symbols), timeout=timeout or configure_default_socket_timeout())
    response.raise_for_status()
    return response.content.decode("gbk", errors="ignore")


def parse_quotes(text):
    """Return {code: fields} parsed from Tencent's quote payload."""
    quotes = {}
    for line in str(text or "").splitlines():
        if "=" not in line:
            continue
        _, _, payload = line.partition("=")
        payload = payload.strip().rstrip(";").strip('"')
        fields = payload.split("~")
        if len(fields) < 39 or len(fields[2]) != 6:
            continue
        quotes[fields[2]] = fields
    return quotes


def bar_from_quote_fields(fields, target_date_text=None):
    """Build a canonical OHLCV row from one Tencent quote field list."""
    if not fields or len(fields) < 39:
        return None
    close = _number(fields[3])
    open_price = _number(fields[5])
    high = _number(fields[33])
    low = _number(fields[34])
    volume = tencent_volume_to_shares(fields[2], _number(fields[6]))
    quote_date = str(fields[30] or "")[:8]
    target_date_text = str(target_date_text or quote_date).replace("-", "")
    if len(quote_date) != 8 or quote_date != target_date_text:
        return None
    if None in (close, open_price, high, low) or close <= 0 or volume is None or volume <= 0:
        return None
    turnover_pct = _number(fields[38])
    amount_wan = _number(fields[37])
    return {
        "date": f"{quote_date[:4]}-{quote_date[4:6]}-{quote_date[6:]}",
        "open": open_price,
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "turnover": None if turnover_pct is None else round(turnover_pct / 100, 6),
        "amount": None if amount_wan is None else amount_wan * 10000,
    }


def fetch_realtime_quote_bar(code, target_date_text=None, logger=None):
    """Fetch today's Tencent quote as a temporary daily bar for display refreshes."""
    code = normalize_code(code)
    symbol = market_symbol_for_tx(code)
    if not code or not symbol:
        return None
    try:
        quotes = parse_quotes(fetch_quote_text([symbol]))
        fields = quotes.get(code)
        return bar_from_quote_fields(fields, target_date_text=target_date_text)
    except Exception as exc:
        if logger:
            _log(logger, "warning", f"腾讯实时行情获取失败: {code}, error={exc}")
        return None


def merge_quote_bar(frame, bar):
    """Return frame with the quote bar appended/replacing the same-date row."""
    if not bar:
        return frame
    quote = pd.DataFrame([bar])
    if frame is None or frame.empty:
        return quote
    merged = pd.concat([frame, quote], ignore_index=True, sort=False)
    if "date" not in merged.columns:
        return merged
    merged["_date_key"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.dropna(subset=["_date_key"]).drop_duplicates(subset=["_date_key"], keep="last")
    merged = merged.sort_values("_date_key").drop(columns=["_date_key"])
    merged.reset_index(drop=True, inplace=True)
    return merged
