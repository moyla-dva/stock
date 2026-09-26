"""C signal V2 fact extraction.

This module owns observable technical facts only. It deliberately avoids
turning those facts into buy/sell decisions so the V2 state and permission
layers can reuse the same truth without re-parsing legacy scores.
"""

import math

import numpy as np
import pandas as pd

from stock_analyzer.indicators import calculate_macd


DIVERGENCE_LOOKBACK = 20
DIVERGENCE_RECENT_BARS = 8
RISK_BREAK_LOOKBACK = 20
PRIOR_HIGH_LOOKBACK = 20
PULLBACK_MA20_TOLERANCE_PCT = 3.0
PULLBACK_RECENT_HIGH_PCT = 3.0
BREAKOUT_SETUP_TOLERANCE_PCT = 1.5
HEAT_RETURN_3D_PCT = 6.0
HEAT_MA20_DEVIATION_PCT = 8.0
TREND_ADX_MIN = 15.0


def _as_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        return number if number == number else default
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    number = _as_float(value)
    return default if number is None else int(number)


def _as_bool(value):
    if value is None:
        return False
    try:
        if math.isnan(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n", ""}:
            return False
    return bool(value)


def _format_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "-")[:10]


def _round(value, digits=2):
    number = _as_float(value)
    return None if number is None else round(number, digits)


def _pct_distance(a, b):
    a_value = _as_float(a)
    b_value = _as_float(b)
    if a_value is None or b_value in {None, 0}:
        return None
    return round((a_value - b_value) / b_value * 100, 2)


def _series(df, column, default=False):
    if column in df.columns:
        return df[column]
    return pd.Series(default, index=df.index)


def _latest_row(df_display):
    if df_display is None or df_display.empty:
        return None
    return df_display.iloc[-1]


def _fractal_payload(row, kind):
    price_key = "low" if kind == "bottom" else "high"
    price_date_key = "low_date" if kind == "bottom" else "high_date"
    price_index_key = "low_source_index" if kind == "bottom" else "high_source_index"
    source_indices = [_source_index(value) for value in list(row.get("source_indices") or [])]
    price_source_index = row.get(price_index_key)
    return {
        "date": _format_date(row.get(price_date_key) or row.get("date")),
        "analysis_date": _format_date(row.get("date")),
        "kind": kind,
        "low": _round(row.get("low")),
        "high": _round(row.get("high")),
        "price": _round(row.get(price_key)),
        "source_start_date": _format_date(row.get("source_start_date") or row.get("date")),
        "source_end_date": _format_date(row.get("source_end_date") or row.get("date")),
        "source_indices": source_indices,
        "price_source_index": _source_index(price_source_index) if price_source_index is not None else None,
    }


def _source_index(value):
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _source_from_row(index, row):
    high = _as_float(row.get("high"))
    low = _as_float(row.get("low"))
    if high is None or low is None:
        return None
    close = _as_float(row.get("close"))
    open_price = _as_float(row.get("open"), close)
    volume = _as_float(row.get("volume"), 0.0) or 0.0
    date = _format_date(row.get("date"))
    return {
        "index": _source_index(index),
        "date": date,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _bar_from_source(source):
    return _bar_from_sources([source], direction="single")


def _source_with_extreme(sources, key, *, prefer="max"):
    if prefer == "min":
        return min(sources, key=lambda item: item[key])
    return max(sources, key=lambda item: item[key])


def _bar_from_sources(sources, direction):
    if not sources:
        return None
    if direction == "down":
        high_source = _source_with_extreme(sources, "high", prefer="min")
        low_source = _source_with_extreme(sources, "low", prefer="min")
    else:
        high_source = _source_with_extreme(sources, "high", prefer="max")
        low_source = _source_with_extreme(sources, "low", prefer="max")
    first = sources[0]
    last = sources[-1]
    return {
        "date": last["date"],
        "open": first.get("open"),
        "high": high_source.get("high"),
        "low": low_source.get("low"),
        "close": last.get("close"),
        "volume": sum(_as_float(source.get("volume"), 0.0) or 0.0 for source in sources),
        "source_start_date": first["date"],
        "source_end_date": last["date"],
        "source_indices": [source["index"] for source in sources],
        "source_dates": [source["date"] for source in sources],
        "high_date": high_source.get("date"),
        "low_date": low_source.get("date"),
        "high_source_index": high_source.get("index"),
        "low_source_index": low_source.get("index"),
        "merge_direction": direction,
        "_sources": sources,
    }


def _is_contained_pair(previous, current):
    previous_high = _as_float(previous.get("high"))
    previous_low = _as_float(previous.get("low"))
    current_high = _as_float(current.get("high"))
    current_low = _as_float(current.get("low"))
    if None in {previous_high, previous_low, current_high, current_low}:
        return False
    current_inside_previous = (
        current_high <= previous_high
        and current_low >= previous_low
        and (current_high < previous_high or current_low > previous_low)
    )
    previous_inside_current = (
        current_high >= previous_high
        and current_low <= previous_low
        and (current_high > previous_high or current_low < previous_low)
    )
    return bool(current_inside_previous or previous_inside_current)


def _merge_direction(normalized, current):
    if normalized:
        latest_direction = normalized[-1].get("merge_direction")
        latest_sources = normalized[-1].get("source_indices") or []
        if latest_direction in {"up", "down"} and len(latest_sources) > 1:
            return latest_direction
    if len(normalized) >= 2:
        previous = normalized[-2]
        latest = normalized[-1]
        if latest["high"] > previous["high"] and latest["low"] >= previous["low"]:
            return "up"
        if latest["high"] <= previous["high"] and latest["low"] < previous["low"]:
            return "down"
        latest_close = _as_float(latest.get("close"))
        previous_close = _as_float(previous.get("close"))
        if latest_close is not None and previous_close is not None and latest_close != previous_close:
            return "up" if latest_close > previous_close else "down"
    latest_close = _as_float(normalized[-1].get("close")) if normalized else None
    current_close = _as_float(current.get("close"))
    if latest_close is not None and current_close is not None and current_close != latest_close:
        return "up" if current_close > latest_close else "down"
    return "up"


def _public_normalized_bar(bar):
    return {
        "date": bar.get("date"),
        "open": _round(bar.get("open")),
        "high": _round(bar.get("high")),
        "low": _round(bar.get("low")),
        "close": _round(bar.get("close")),
        "source_start_date": bar.get("source_start_date"),
        "source_end_date": bar.get("source_end_date"),
        "source_indices": list(bar.get("source_indices") or []),
        "source_dates": list(bar.get("source_dates") or []),
        "high_date": bar.get("high_date"),
        "low_date": bar.get("low_date"),
        "high_source_index": bar.get("high_source_index"),
        "low_source_index": bar.get("low_source_index"),
        "merge_direction": bar.get("merge_direction"),
        "merged_count": len(bar.get("source_indices") or []),
    }


def _normalize_kline_inclusion_frame(df_display, lookback=80):
    if df_display is None or df_display.empty or not {"high", "low"}.issubset(df_display.columns):
        return {
            "available": False,
            "frame": pd.DataFrame(),
            "bars": [],
            "original_count": 0,
            "normalized_count": 0,
            "containment_count": 0,
            "merge_count": 0,
            "dropped_count": 0,
            "summary": "缺少高低点数据，无法处理 K 线包含关系。",
        }

    window = df_display.tail(lookback) if lookback else df_display
    normalized = []
    containment_count = 0
    dropped_count = 0

    # to_dict("records") 与 iterrows 的逐行取值语义一致，但避免每行构建 Series。
    for index, row in zip(window.index, window.to_dict("records")):
        source = _source_from_row(index, row)
        if source is None:
            dropped_count += 1
            continue
        current = _bar_from_source(source)
        if normalized and _is_contained_pair(normalized[-1], current):
            containment_count += 1
            direction = _merge_direction(normalized, current)
            sources = list(normalized[-1].get("_sources") or []) + [source]
            normalized[-1] = _bar_from_sources(sources, direction)
            continue
        normalized.append(current)

    public_bars = [_public_normalized_bar(bar) for bar in normalized]
    frame = pd.DataFrame(public_bars)
    if not frame.empty:
        frame["high"] = pd.to_numeric(frame["high"], errors="coerce")
        frame["low"] = pd.to_numeric(frame["low"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    merge_count = sum(max(0, len(bar.get("source_indices") or []) - 1) for bar in public_bars)
    summary = (
        f"近{len(window)}根K线完成包含处理，合并 {merge_count} 根，输出 {len(public_bars)} 根结构K线。"
        if public_bars
        else "没有可用于包含处理的有效 K 线。"
    )
    return {
        "available": bool(public_bars),
        "frame": frame,
        "bars": public_bars,
        "original_count": int(len(window)),
        "normalized_count": int(len(public_bars)),
        "containment_count": int(containment_count),
        "merge_count": int(merge_count),
        "dropped_count": int(dropped_count),
        "summary": summary,
    }


def build_normalized_bar_facts(df_display, lookback=80, normalization=None):
    """Build structure bars after K-line inclusion handling."""
    if normalization is None:
        normalization = _normalize_kline_inclusion_frame(df_display, lookback=lookback)
    return {
        "available": normalization["available"],
        "lookback": int(lookback or normalization["original_count"]),
        "original_count": normalization["original_count"],
        "normalized_count": normalization["normalized_count"],
        "containment_count": normalization["containment_count"],
        "merge_count": normalization["merge_count"],
        "dropped_count": normalization["dropped_count"],
        "bars": normalization["bars"],
        "recent_bars": normalization["bars"][-10:],
        "summary": normalization["summary"],
    }


def build_momentum_facts(df_display, ma_window=3):
    """Build normalized candle-position momentum facts for V2."""
    if df_display is None or df_display.empty or not {"high", "low", "close"}.issubset(df_display.columns):
        return {
            "available": False,
            "balance": None,
            "balance_ma3": None,
            "balance_delta": None,
            "power_flip": False,
            "williams_r_power_cross": False,
            "summary": "缺少高低收数据，无法计算归一化动能。",
        }

    window = df_display.copy()
    high = window["high"].apply(_as_float)
    low = window["low"].apply(_as_float)
    close = window["close"].apply(_as_float)
    half_range = ((high - low) / 2).replace(0, pd.NA)
    midpoint = (high + low) / 2
    balance_series = ((close - midpoint) / half_range).clip(lower=-1.0, upper=1.0)
    balance_series = pd.to_numeric(balance_series, errors="coerce").fillna(0.0)
    balance_ma = balance_series.rolling(window=ma_window, min_periods=1).mean()
    latest_balance = _as_float(balance_series.iloc[-1])
    previous_balance = _as_float(balance_series.iloc[-2]) if len(balance_series) >= 2 else None
    balance_delta = None if previous_balance is None or latest_balance is None else latest_balance - previous_balance
    power_flip = bool(
        previous_balance is not None
        and latest_balance is not None
        and previous_balance < 0
        and latest_balance >= 0.5
        and balance_delta >= 0.7
    )

    williams_r = _as_float(window.iloc[-1].get("williams_r"))
    previous_williams_r = _as_float(window.iloc[-2].get("williams_r")) if len(window) >= 2 else None
    williams_r_delta = None
    williams_r_power_cross = False
    if williams_r is not None and previous_williams_r is not None:
        williams_r_delta = previous_williams_r - williams_r
        williams_r_power_cross = bool(previous_williams_r >= 50 and williams_r < 50 and williams_r_delta >= 25)

    if power_flip and williams_r_power_cross:
        summary = "归一化定价权与 Williams 中轴同步跃迁。"
    elif power_flip:
        summary = "归一化定价权出现迫切性跃迁。"
    elif williams_r_power_cross:
        summary = "Williams %R 强力切入多方区。"
    else:
        summary = "归一化动能未出现明确跃迁。"

    return {
        "available": True,
        "balance": _round(latest_balance, 3),
        "previous_balance": _round(previous_balance, 3),
        "balance_ma3": _round(balance_ma.iloc[-1], 3),
        "balance_delta": _round(balance_delta, 3),
        "power_flip": power_flip,
        "williams_r": _round(williams_r, 2),
        "previous_williams_r": _round(previous_williams_r, 2),
        "williams_r_delta": _round(williams_r_delta, 2),
        "williams_r_power_cross": williams_r_power_cross,
        "summary": summary,
    }


def _permission_summary(permission, reasons=None, warnings=None):
    labels = {
        "allowed": "顺风",
        "watch": "观察",
        "forbidden": "逆风",
        "unknown": "未知",
    }
    reason_text = "；".join(reasons or warnings or [])
    if reason_text:
        return f"{labels.get(permission, '未知')}：{reason_text}"
    return labels.get(permission, "未知")


def _unique_values(values):
    output = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _moving_average_tide(close, latest_close, *, length, slope_lookback, name, strict=False):
    payload = {
        "available": False,
        "value": None,
        "slope_pct": None,
        "above": None,
        "up": None,
        "permission": "unknown",
        "label": f"{name}未知",
        "summary": f"样本不足，暂不判断 {name} 潮汐。",
    }
    if len(close) < length or latest_close is None:
        return payload

    ma_series = close.rolling(window=length, min_periods=length).mean().dropna()
    if ma_series.empty:
        return payload

    latest_ma = _as_float(ma_series.iloc[-1])
    slope_ref_days = min(slope_lookback, max(0, len(ma_series) - 1))
    reference_ma = _as_float(ma_series.iloc[-slope_ref_days - 1]) if slope_ref_days else latest_ma
    slope_pct = None
    if latest_ma is not None and reference_ma not in {None, 0}:
        slope_pct = (latest_ma - reference_ma) / reference_ma * 100
    above_ma = bool(latest_ma is not None and latest_close >= latest_ma)
    ma_up = bool(slope_pct is not None and slope_pct > 0)
    if strict and not above_ma and slope_pct is not None and slope_pct < 0:
        permission = "forbidden"
        label = f"{name}逆风"
        summary = f"价格低于 {name} 且 {name} 下行。"
    elif not above_ma or (slope_pct is not None and slope_pct <= 0):
        permission = "watch"
        label = f"{name}观察"
        summary = f"价格或 {name} 斜率仍未完全转强。"
    else:
        permission = "allowed"
        label = f"{name}顺风"
        summary = f"价格站上 {name}，且 {name} 向上。"
    return {
        "available": True,
        "value": _round(latest_ma),
        "slope_pct": _round(slope_pct, 3),
        "above": above_ma,
        "up": ma_up,
        "permission": permission,
        "label": label,
        "summary": summary,
    }


def build_macro_tide_facts(df_display):
    """Build higher-cycle tide facts for the V2 permission layer.

    The macro tide is a veto/permission layer, not a signal generator. Missing
    data stays unknown so short samples and newly listed stocks are not
    mechanically rejected.
    """
    if df_display is None or df_display.empty or "close" not in df_display.columns:
        return {
            "available": False,
            "permission": "unknown",
            "label": "大周期未知",
            "ma60": {"available": False},
            "ma250": {"available": False},
            "weekly_macd": {"available": False},
            "block_reasons": [],
            "warnings": ["缺少收盘价数据，无法判断大周期潮汐。"],
            "summary": "缺少收盘价数据，无法判断大周期潮汐。",
        }

    window = df_display.copy()
    close = window["close"].apply(_as_float)
    latest_close = _as_float(close.iloc[-1])

    ma60 = _moving_average_tide(
        close,
        latest_close,
        length=60,
        slope_lookback=10,
        name="MA60",
        strict=False,
    )
    ma250 = _moving_average_tide(
        close,
        latest_close,
        length=250,
        slope_lookback=20,
        name="MA250",
        strict=True,
    )

    weekly_macd = {
        "available": False,
        "dif": None,
        "dea": None,
        "hist": None,
        "previous_hist": None,
        "hist_delta": None,
        "bearish_expanding": False,
        "bearish_cross_down": False,
        "permission": "unknown",
        "label": "周线MACD未知",
        "summary": "样本不足，暂不判断周线 MACD。",
    }
    if "date" in window.columns and latest_close is not None:
        dated = window[["date", "close"]].copy()
        dated["date"] = pd.to_datetime(dated["date"], errors="coerce")
        dated = dated.dropna(subset=["date", "close"]).sort_values("date")
        if len(dated) >= 80:
            weekly = dated.set_index("date")["close"].resample("W-FRI").last().dropna().to_frame("close")
            # 形成中的周不参与判定：最新交易日尚未走完其所在周时，剔除该周，
            # 避免周中 hist 反复翻转导致 bearish_cross_down 误报；EMA 暖机需要约
            # 3×slow 根样本，门槛取 60 根完整周（约 14 个月）。
            if len(weekly) and pd.notna(dated["date"].iloc[-1]) and dated["date"].iloc[-1].normalize() < weekly.index[-1]:
                weekly = weekly.iloc[:-1]
            if len(weekly) >= 60:
                dif, dea, hist = calculate_macd(weekly)
                latest_hist = _as_float(hist.iloc[-1])
                previous_hist = _as_float(hist.iloc[-2]) if len(hist) >= 2 else None
                hist_delta = None if latest_hist is None or previous_hist is None else latest_hist - previous_hist
                latest_dif = _as_float(dif.iloc[-1])
                latest_dea = _as_float(dea.iloc[-1])
                previous_dif = _as_float(dif.iloc[-2]) if len(dif) >= 2 else None
                previous_dea = _as_float(dea.iloc[-2]) if len(dea) >= 2 else None
                bearish_expanding = bool(latest_hist is not None and previous_hist is not None and latest_hist < 0 and latest_hist < previous_hist)
                bearish_cross_down = bool(latest_hist is not None and previous_hist is not None and previous_hist >= 0 and latest_hist < 0)
                dead_cross_down = bool(
                    latest_dif is not None
                    and latest_dea is not None
                    and latest_dif < latest_dea
                    and (
                        (previous_dif is not None and previous_dea is not None and previous_dif >= previous_dea)
                        or (hist_delta is not None and hist_delta < 0)
                    )
                )
                if bearish_expanding or bearish_cross_down or dead_cross_down:
                    weekly_permission = "forbidden"
                    weekly_label = "周线MACD逆风"
                    weekly_summary = "周线 MACD 死叉向下、绿柱扩大或刚跌入空方。"
                elif latest_hist is not None and (latest_hist < 0 or (hist_delta is not None and hist_delta < 0)):
                    weekly_permission = "watch"
                    weekly_label = "周线MACD观察"
                    weekly_summary = "周线 MACD 尚未转为明确顺风。"
                else:
                    weekly_permission = "allowed"
                    weekly_label = "周线MACD顺风"
                    weekly_summary = "周线 MACD 未形成空方扩张压力。"
                weekly_macd = {
                    "available": True,
                    "dif": _round(latest_dif, 4),
                    "dea": _round(latest_dea, 4),
                    "hist": _round(latest_hist, 4),
                    "previous_hist": _round(previous_hist, 4),
                    "hist_delta": _round(hist_delta, 4),
                    "bearish_expanding": bearish_expanding,
                    "bearish_cross_down": bearish_cross_down,
                    "dead_cross_down": dead_cross_down,
                    "permission": weekly_permission,
                    "label": weekly_label,
                    "summary": weekly_summary,
                }

    block_reasons = []
    warnings = []
    for item in (ma60, ma250, weekly_macd):
        if item.get("permission") == "forbidden":
            block_reasons.append(item.get("summary") or item.get("label"))
        elif item.get("permission") in {"watch", "unknown"}:
            warnings.append(item.get("summary") or item.get("label"))

    known_permissions = [
        item.get("permission")
        for item in (ma60, ma250, weekly_macd)
        if item.get("permission") != "unknown"
    ]
    if block_reasons:
        permission = "forbidden"
        label = "大周期逆风"
    elif any(value == "watch" for value in known_permissions):
        permission = "watch"
        label = "大周期观察"
    elif known_permissions and all(value == "allowed" for value in known_permissions):
        permission = "allowed"
        label = "大周期顺风"
    else:
        permission = "unknown"
        label = "大周期未知"

    return {
        "available": bool(known_permissions),
        "permission": permission,
        "label": label,
        "ma60": ma60,
        "ma250": ma250,
        "weekly_macd": weekly_macd,
        "block_reasons": _unique_values(block_reasons),
        "warnings": _unique_values(warnings),
        "summary": _permission_summary(permission, block_reasons, warnings),
    }


def _target_payload(source, label, price, *, date="", lookback=None, priority=100, age_bars=None):
    return {
        "source": source,
        "label": label,
        "price": _round(price),
        "date": _format_date(date) if date else "",
        "lookback": lookback,
        "priority": priority,
        "age_bars": age_bars,
    }


def _resistance_touch_count(window, price, tolerance_pct=1.5):
    price_value = _as_float(price)
    if window is None or window.empty or price_value in {None, 0} or "high" not in window.columns:
        return 0
    tolerance = abs(price_value) * tolerance_pct / 100
    highs = pd.to_numeric(window["high"], errors="coerce").dropna()
    if highs.empty:
        return 0
    return int(((highs - price_value).abs() <= tolerance).sum())


def _resistance_volume_weight(window, price, tolerance_pct=2.0):
    price_value = _as_float(price)
    if (
        window is None
        or window.empty
        or price_value in {None, 0}
        or "high" not in window.columns
        or "volume" not in window.columns
    ):
        return 1.0
    highs = pd.to_numeric(window["high"], errors="coerce")
    volume = pd.to_numeric(window["volume"], errors="coerce")
    avg_volume = _as_float(volume.mean())
    if not avg_volume:
        return 1.0
    tolerance = abs(price_value) * tolerance_pct / 100
    nearby_volume = volume[(highs - price_value).abs() <= tolerance].dropna()
    if nearby_volume.empty:
        return 1.0
    return round(max(0.5, min(2.0, _as_float(nearby_volume.mean(), avg_volume) / avg_volume)), 2)


def _resistance_zone_payload(
    source,
    label,
    price,
    *,
    window,
    reference_price,
    date="",
    date_range=None,
    lookback=None,
    priority=100,
    base_strength=45,
    age_bars=None,
    time_decay=None,
):
    price_value = _as_float(price)
    reference = _as_float(reference_price)
    if price_value is None or reference is None or price_value <= reference:
        return None
    touch_count = _resistance_touch_count(window, price_value)
    volume_weight = _resistance_volume_weight(window, price_value)
    distance_pct = _pct_distance(price_value, reference)
    if time_decay is None:
        age = _as_int(age_bars, None)
        lookback_value = _as_float(lookback)
        time_decay = max(0.2, 1 - age / lookback_value) if age is not None and lookback_value else 1.0
    time_decay = round(max(0.0, min(1.0, _as_float(time_decay, 1.0))), 2)
    strength_score = int(min(
        100,
        base_strength
        + min(24, touch_count * 4)
        + min(16, int((volume_weight - 1) * 20))
        + int(time_decay * 8),
    ))
    if strength_score >= 60:
        role = "target"
    elif strength_score >= 42:
        role = "warning"
    else:
        role = "ignore"
    return {
        "source": source,
        "label": label,
        "price": _round(price_value),
        "date": _format_date(date) if date else "",
        "date_range": date_range or (_format_date(date) if date else ""),
        "lookback": lookback,
        "priority": priority,
        "age_bars": age_bars,
        "touch_count": touch_count,
        "volume_weight": volume_weight,
        "distance_pct": distance_pct,
        "time_decay": time_decay,
        "strength_score": strength_score,
        "role": role,
    }


def _target_from_resistance_zone(zone):
    if not isinstance(zone, dict):
        return None
    return {
        "source": zone.get("source"),
        "label": zone.get("label"),
        "price": zone.get("price"),
        "date": zone.get("date", ""),
        "lookback": zone.get("lookback"),
        "priority": zone.get("priority"),
        "age_bars": zone.get("age_bars"),
        "strength_score": zone.get("strength_score"),
        "role": zone.get("role"),
        "touch_count": zone.get("touch_count"),
        "volume_weight": zone.get("volume_weight"),
        "distance_pct": zone.get("distance_pct"),
        "time_decay": zone.get("time_decay"),
    }


def _prior_high_target(window, reference_price, lookback, priority):
    if window is None or window.empty or "high" not in window.columns:
        return None
    previous = window.iloc[:-1].tail(lookback)
    if previous.empty:
        return None
    highs = previous["high"].apply(_as_float)
    high_price = _as_float(highs.max())
    if high_price is None or reference_price is None or high_price <= reference_price:
        return None
    high_idx = highs.idxmax()
    date = previous.loc[high_idx].get("date") if high_idx in previous.index else ""
    high_pos = previous.index.get_loc(high_idx) if high_idx in previous.index else len(previous) - 1
    age_bars = len(previous) - 1 - int(high_pos)
    return _target_payload(
        f"prior_high_{lookback}",
        f"{lookback}日前高",
        high_price,
        date=date,
        lookback=lookback,
        priority=priority,
        age_bars=age_bars,
    )


def _prior_high_resistance_zone(window, reference_price, lookback, priority, base_strength):
    target = _prior_high_target(window, reference_price, lookback, priority)
    if not target:
        return None
    return _resistance_zone_payload(
        target["source"],
        target["label"],
        target["price"],
        window=window.iloc[:-1].tail(lookback),
        reference_price=reference_price,
        date=target.get("date"),
        lookback=lookback,
        priority=priority,
        base_strength=base_strength,
        age_bars=target.get("age_bars"),
    )


def _unfilled_gap_targets(window, reference_price, lookback=250):
    if (
        window is None
        or len(window) < 3
        or reference_price is None
        or not {"high", "low"}.issubset(window.columns)
    ):
        return []
    scan = window.tail(lookback + 1)
    highs = pd.to_numeric(scan["high"], errors="coerce").to_numpy(dtype="float64")
    lows = pd.to_numeric(scan["low"], errors="coerce").to_numpy(dtype="float64")
    dates = scan["date"].tolist() if "date" in scan.columns else [None] * len(scan)
    total = len(scan)

    # suffix_max[pos] = highs[pos:] 的跳过 NaN 最大值；全 NaN 时为 -inf（等价 pandas .max() → NaN 比较 False）。
    suffix_max = np.full(total, -np.inf)
    running = -np.inf
    for pos in range(total - 1, -1, -1):
        value = highs[pos]
        if not np.isnan(value) and value > running:
            running = value
        suffix_max[pos] = running

    targets = []
    for pos in range(1, total - 1):
        previous_low = None if np.isnan(lows[pos - 1]) else float(lows[pos - 1])
        gap_day_high = None if np.isnan(highs[pos]) else float(highs[pos])
        if previous_low is None or gap_day_high is None or gap_day_high >= previous_low:
            continue
        if gap_day_high <= reference_price:
            continue
        filled = suffix_max[pos + 1] >= previous_low
        if filled:
            continue
        targets.append(_target_payload(
            "unfilled_gap_lower",
            "上方缺口下沿",
            gap_day_high,
            date=dates[pos],
            lookback=lookback,
            priority=10,
            age_bars=total - 1 - pos,
        ))
    targets.sort(key=lambda item: (item["priority"], item["price"] or 0))
    return targets[:3]


def _unfilled_gap_resistance_zones(window, reference_price, lookback=250):
    zones = []
    for target in _unfilled_gap_targets(window, reference_price, lookback=lookback):
        zone = _resistance_zone_payload(
            target["source"],
            target["label"],
            target["price"],
            window=window.tail(lookback),
            reference_price=reference_price,
            date=target.get("date"),
            lookback=lookback,
            priority=target.get("priority", 10),
            base_strength=72,
            age_bars=target.get("age_bars"),
        )
        if zone:
            zones.append(zone)
    return zones


def _volume_peak_resistance_zone(window, reference_price, lookback=250):
    if window is None or window.empty or not {"high", "volume"}.issubset(window.columns):
        return None
    scan = window.iloc[:-1].tail(lookback).copy()
    if scan.empty:
        return None
    volume = pd.to_numeric(scan["volume"], errors="coerce")
    if volume.dropna().empty:
        return None
    idx = volume.idxmax()
    row = scan.loc[idx]
    high = _as_float(row.get("high"))
    if high is None or reference_price is None or high <= reference_price:
        return None
    peak_pos = scan.index.get_loc(idx) if idx in scan.index else len(scan) - 1
    age_bars = len(scan) - 1 - int(peak_pos)
    return _resistance_zone_payload(
        "volume_peak",
        "历史量峰压力",
        high,
        window=scan,
        reference_price=reference_price,
        date=row.get("date"),
        lookback=lookback,
        priority=35,
        base_strength=58,
        age_bars=age_bars,
    )


def _macro_rectangle_resistance_zone(window, reference_price, macro_rectangle):
    if not isinstance(macro_rectangle, dict):
        return None
    price = _as_float(macro_rectangle.get("previous_upper") or macro_rectangle.get("upper"))
    if price is None or reference_price is None or price <= reference_price:
        return None
    return _resistance_zone_payload(
        "macro_rectangle_upper",
        "一年箱体上沿",
        price,
        window=window.tail(int(macro_rectangle.get("requested_lookback") or macro_rectangle.get("lookback") or 250)),
        reference_price=reference_price,
        date_range=f"{macro_rectangle.get('start_date', '')}~{macro_rectangle.get('end_date', '')}",
        lookback=macro_rectangle.get("lookback"),
        priority=18,
        base_strength=68,
        time_decay=1.0,
    )


def _dedupe_resistance_zones(zones):
    deduped = {}
    for zone in zones:
        if not zone or zone.get("price") is None:
            continue
        key = _round(zone.get("price"))
        existing = deduped.get(key)
        if existing is None or (zone.get("strength_score") or 0) > (existing.get("strength_score") or 0):
            deduped[key] = zone
    return sorted(deduped.values(), key=lambda item: (item.get("price") or 0, -(item.get("strength_score") or 0)))


def _select_breakout_resistance_target(resistance_zones):
    target_zones = [zone for zone in resistance_zones if zone.get("role") == "target"]
    if not target_zones:
        return None
    return min(target_zones, key=lambda item: (item.get("distance_pct") if item.get("distance_pct") is not None else 999, -(item.get("strength_score") or 0)))


def build_target_structure_facts(df_display, rectangle=None, macro_rectangle=None):
    """Build structural target references for V2 plan-gate math."""
    if df_display is None or df_display.empty or "close" not in df_display.columns:
        return {
            "available": False,
            "reference_price": None,
            "pullback_target": None,
            "breakout_targets": [],
            "selected_breakout_target": None,
            "resistance_zones": [],
            "target_selection_reason": "缺少收盘价数据。",
            "summary": "缺少收盘价数据，无法估算结构目标。",
        }

    window = df_display.copy()
    latest = window.iloc[-1]
    reference_price = _as_float(latest.get("close"))
    rectangle = rectangle if isinstance(rectangle, dict) else build_rectangle_facts(df_display)
    rectangle_upper = _as_float(rectangle.get("upper")) if isinstance(rectangle, dict) else None
    pullback_target = None
    if rectangle_upper is not None and reference_price is not None and rectangle_upper > reference_price:
        pullback_target = _target_payload(
            "rectangle_upper",
            "箱体上沿",
            rectangle_upper,
            lookback=rectangle.get("lookback"),
            priority=20,
        )

    zones = []
    zones.extend(_unfilled_gap_resistance_zones(window, reference_price))
    macro_zone = _macro_rectangle_resistance_zone(window, reference_price, macro_rectangle)
    if macro_zone:
        zones.append(macro_zone)
    volume_peak_zone = _volume_peak_resistance_zone(window, reference_price)
    if volume_peak_zone:
        zones.append(volume_peak_zone)
    for lookback, priority, base_strength in ((120, 20, 56), (60, 30, 48), (250, 40, 60)):
        zone = _prior_high_resistance_zone(window, reference_price, lookback, priority, base_strength)
        if zone:
            zones.append(zone)

    resistance_zones = _dedupe_resistance_zones(zones)
    selected_zone = _select_breakout_resistance_target(resistance_zones)
    selected_breakout_target = _target_from_resistance_zone(selected_zone)
    breakout_targets = [_target_from_resistance_zone(zone) for zone in resistance_zones]
    target_selection_reason = (
        f"选择最近核心强阻 {selected_zone['label']}，强度 {selected_zone['strength_score']}，距离 {selected_zone['distance_pct']}%。"
        if selected_zone
        else "未找到强度足够的上方阻力，突破型交易需等待目标确认。"
    )

    if selected_breakout_target:
        summary = f"突破型目标取 {selected_breakout_target['label']} {selected_breakout_target['price']}。"
    elif pullback_target:
        summary = f"回踩型目标取 {pullback_target['label']} {pullback_target['price']}；突破型目标待确认。"
    else:
        summary = "未找到有效上方结构目标，突破型交易需等待目标确认。"

    return {
        "available": bool(pullback_target or selected_breakout_target),
        "reference_price": _round(reference_price),
        "pullback_target": pullback_target,
        "breakout_targets": breakout_targets,
        "selected_breakout_target": selected_breakout_target,
        "resistance_zones": resistance_zones,
        "target_selection_reason": target_selection_reason,
        "summary": summary,
    }


def _pos_for_index(df_display, index):
    try:
        return int(df_display.index.get_loc(index))
    except (KeyError, TypeError, ValueError):
        return None


def _latest_bottom_before(fractals, source_pos):
    if not isinstance(fractals, dict):
        return None
    bottoms = list(fractals.get("recent_bottoms") or [])
    latest_bottom = fractals.get("latest_bottom")
    if isinstance(latest_bottom, dict) and latest_bottom not in bottoms:
        bottoms.append(latest_bottom)
    candidates = []
    for bottom in bottoms:
        if not isinstance(bottom, dict):
            continue
        price = _as_float(bottom.get("price"))
        bottom_pos = _as_int(bottom.get("price_source_index"), None)
        if price is None or bottom_pos is None or source_pos is None or bottom_pos > source_pos:
            continue
        candidates.append((bottom_pos, price, bottom))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][2]


def _recent_low_stop(window, end_pos, lookback=20):
    if window is None or window.empty or "low" not in window.columns or end_pos is None:
        return None
    scan = window.iloc[max(0, end_pos - lookback + 1):end_pos + 1]
    if scan.empty:
        return None
    return _as_float(pd.to_numeric(scan["low"], errors="coerce").min())


def _entry_initial_stop(window, entry_pos, entry_price, fractals=None):
    candidates = []
    entry_frame = window.iloc[:entry_pos + 1]
    rectangle = build_rectangle_facts(entry_frame)
    if isinstance(rectangle, dict):
        candidates.extend([rectangle.get("invalidation_price"), rectangle.get("c_point")])
    bottom = _latest_bottom_before(fractals, entry_pos)
    if isinstance(bottom, dict):
        candidates.append(bottom.get("price"))
    candidates.append(_recent_low_stop(window, entry_pos, lookback=20))
    valid = [
        _as_float(candidate)
        for candidate in candidates
        if _as_float(candidate) is not None and entry_price is not None and _as_float(candidate) < entry_price
    ]
    if valid:
        return max(valid), "c_point_or_bottom_fractal"
    return None, "missing_structure_stop"


def _confirmed_bottoms_after(fractals, entry_pos):
    if not isinstance(fractals, dict):
        return []
    bottoms = list(fractals.get("recent_bottoms") or [])
    output = []
    for bottom in bottoms:
        if not isinstance(bottom, dict):
            continue
        price = _as_float(bottom.get("price"))
        bottom_pos = _as_int(bottom.get("price_source_index"), None)
        if price is None or bottom_pos is None or bottom_pos < entry_pos:
            continue
        output.append((bottom_pos, price, bottom))
    output.sort(key=lambda item: item[0])
    return output


def _latest_ma_value(row, *columns):
    for column in columns:
        number = _as_float(row.get(column))
        if number is not None:
            return number, column
    return None, ""


def _strong_resistance_touch(latest, target_structure):
    if not isinstance(target_structure, dict):
        return None
    high = _as_float(latest.get("high"), _as_float(latest.get("close")))
    close = _as_float(latest.get("close"))
    if high is None and close is None:
        return None
    zones = [
        zone for zone in list(target_structure.get("resistance_zones") or [])
        if isinstance(zone, dict) and zone.get("role") == "target"
    ]
    for zone in sorted(zones, key=lambda item: item.get("distance_pct") if item.get("distance_pct") is not None else 999):
        price = _as_float(zone.get("price"))
        if price is None:
            continue
        touched = (high is not None and high >= price * 0.995) or (close is not None and abs(close - price) / price <= 0.01)
        if touched:
            return zone
    return None


def build_v2_entry_series(df_display, lookback=PRIOR_HIGH_LOOKBACK):
    """Per-bar V2 entry trigger: close breaks the prior N-day high."""
    if df_display is None or df_display.empty:
        return pd.Series(dtype=bool)
    highs = _numeric_series(df_display, "high")
    closes = _numeric_series(df_display, "close")
    if highs is None or closes is None:
        return pd.Series(False, index=df_display.index)
    flags = pd.Series(False, index=df_display.index)
    high_values = highs.tolist()
    close_values = closes.tolist()
    length = len(high_values)
    for i in range(lookback, length):
        prior = [value for value in high_values[i - lookback:i] if value is not None and value == value]
        current_close = close_values[i]
        if not prior or current_close is None or current_close != current_close:
            continue
        if current_close > max(prior):
            flags.iloc[i] = True
    return flags


def build_v2_break_series(df_display, lookback=RISK_BREAK_LOOKBACK):
    """Per-bar V2 structural break: close below the prior N-day low."""
    if df_display is None or df_display.empty:
        return pd.Series(dtype=bool)
    lows = _numeric_series(df_display, "low")
    closes = _numeric_series(df_display, "close")
    if lows is None or closes is None:
        return pd.Series(False, index=df_display.index)
    flags = pd.Series(False, index=df_display.index)
    low_values = lows.tolist()
    close_values = closes.tolist()
    length = len(low_values)
    for i in range(lookback, length):
        prior = [value for value in low_values[i - lookback:i] if value is not None and value == value]
        current_close = close_values[i]
        if not prior or current_close is None or current_close != current_close:
            continue
        if current_close < min(prior):
            flags.iloc[i] = True
    return flags


def _series_index_labels(df_display, series):
    if df_display is None or series is None or len(series) == 0:
        return []
    values = series.tolist()
    return [df_display.index[position] for position, value in enumerate(values) if value]


def build_exit_gate_facts(df_display, *, fractals=None, target_structure=None):
    """Build P11 exit semantics without converting every risk fact into a sell point."""
    if df_display is None or df_display.empty or not {"date", "close", "high", "low"}.issubset(df_display.columns):
        return {
            "available": False,
            "source": "c_signal_v2_p11_exit_gate",
            "position_lifecycle": {
                "entry_id": "",
                "entry_date": "",
                "entry_type": "",
                "entry_price": None,
                "initial_stop": None,
                "active_stop": None,
                "stop_source": "",
                "peak_price": None,
                "position_state": "inactive",
                "exit_reason": "",
            },
            "trailing_stop": {"available": False, "price": None, "source": ""},
            "observations": [],
            "action": "none",
            "marker_role": "observe",
            "marker_level": "weak",
            "marker_reason": "",
            "summary": "缺少行情数据，无法计算 Exit Gate。",
        }

    window = df_display.copy()
    latest = window.iloc[-1]
    latest_pos = len(window) - 1
    latest_close = _as_float(latest.get("close"))
    latest_high = _as_float(latest.get("high"), latest_close)
    entry_indices = _series_index_labels(window, build_v2_entry_series(window))
    exit_indices = _series_index_labels(window, build_v2_break_series(window))
    last_entry_idx = entry_indices[-1] if entry_indices else None
    last_exit_idx = exit_indices[-1] if exit_indices else None
    entry_pos = _pos_for_index(window, last_entry_idx)
    exit_pos = _pos_for_index(window, last_exit_idx)
    has_active_position = entry_pos is not None and (exit_pos is None or entry_pos > exit_pos)
    just_exited = exit_pos is not None and exit_pos == latest_pos and entry_pos is not None and exit_pos >= entry_pos

    observations = []
    if isinstance(fractals, dict):
        latest_top = fractals.get("latest_top") if isinstance(fractals.get("latest_top"), dict) else None
        if latest_top:
            observations.append({
                "type": "top_fractal",
                "marker_role": "observe",
                "marker_level": "normal" if fractals.get("top_lower_high") else "weak",
                "marker_reason": "top_fractal",
                "date": latest_top.get("date"),
                "price": latest_top.get("price"),
                "summary": "顶分型是局部阻力观察，不直接生成 S 点。",
            })
        latest_bottom = fractals.get("latest_bottom") if isinstance(fractals.get("latest_bottom"), dict) else None
        if latest_bottom:
            observations.append({
                "type": "bottom_fractal",
                "marker_role": "observe",
                "marker_level": "normal",
                "marker_reason": "bottom_fractal",
                "date": latest_bottom.get("date"),
                "price": latest_bottom.get("price"),
                "summary": "底分型可作为防守线上移候选。",
            })

    lifecycle = {
        "entry_id": "",
        "entry_date": "",
        "entry_type": "",
        "entry_price": None,
        "initial_stop": None,
        "active_stop": None,
        "stop_source": "",
        "peak_price": None,
        "position_state": "inactive",
        "exit_reason": "",
    }
    trailing_stop = {"available": False, "price": None, "source": "", "mode": "inactive"}
    action = "none"
    marker_role = "observe"
    marker_level = "weak"
    marker_reason = ""
    summary = "当前没有可追踪的 V2 信号后周期，Exit Gate 不生成 S 点。"
    scale_out = None

    if entry_pos is not None:
        entry = window.iloc[entry_pos]
        entry_price = _as_float(entry.get("close"))
        initial_stop, stop_source = _entry_initial_stop(window, entry_pos, entry_price, fractals=fractals)
        active_stop = initial_stop
        stop_source_active = stop_source
        for _, bottom_price, _bottom in _confirmed_bottoms_after(fractals, entry_pos):
            if active_stop is None or bottom_price > active_stop:
                active_stop = bottom_price
                stop_source_active = "bottom_fractal_step"

        holding_window = window.iloc[entry_pos:]
        peak_price = _as_float(pd.to_numeric(holding_window["high"], errors="coerce").max()) if "high" in holding_window.columns else None
        defensive_mode = "normal"
        fast_stop = None
        fast_source = ""
        ma5, ma_source = _latest_ma_value(latest, "ma5", "MA5")
        recent_3_low = _recent_low_stop(window, latest_pos, lookback=3)
        fast_candidates = [
            (ma5, ma_source or "ma5"),
            (recent_3_low, "recent_3_low"),
        ]
        fast_valid = [
            (price, source)
            for price, source in fast_candidates
            if price is not None and latest_close is not None and price < latest_close
        ]
        if fast_valid and active_stop is not None and latest_close is not None:
            stop_gap_pct = _pct_distance(latest_close, active_stop)
            ma20_extended = _as_bool(latest.get("ma20_extended"))
            if ma20_extended or (stop_gap_pct is not None and stop_gap_pct >= 12):
                fast_stop, fast_source = max(fast_valid, key=lambda item: item[0])
                if fast_stop > active_stop:
                    active_stop = fast_stop
                    stop_source_active = fast_source
                    defensive_mode = "accelerated"

        trailing_stop = {
            "available": active_stop is not None,
            "price": _round(active_stop),
            "source": stop_source_active,
            "mode": defensive_mode,
            "stop_gap_pct": _pct_distance(latest_close, active_stop) if active_stop is not None else None,
        }
        position_state = "active" if has_active_position else ("exited" if exit_pos is not None and exit_pos >= entry_pos else "inactive")
        exit_reason = ""
        if just_exited:
            exit_reason = "V2 结构破位离场，Exit Gate 承接为退出动作。"
        lifecycle = {
            "entry_id": f"{_format_date(entry.get('date'))}:v2_breakout",
            "entry_date": _format_date(entry.get("date")),
            "entry_type": "v2_breakout",
            "entry_price": _round(entry_price),
            "initial_stop": _round(initial_stop),
            "active_stop": _round(active_stop),
            "stop_source": stop_source_active,
            "peak_price": _round(peak_price),
            "position_state": position_state,
            "exit_reason": exit_reason,
        }

        manage_existing_position = bool(has_active_position and entry_pos < latest_pos)
        strong_zone = _strong_resistance_touch(latest, target_structure)
        stop_broken = active_stop is not None and latest_close is not None and latest_close < active_stop
        if manage_existing_position and stop_broken:
            action = "sell"
            marker_role = "sell"
            marker_level = "strong"
            marker_reason = "trailing_stop_break"
            lifecycle["position_state"] = "exited"
            lifecycle["exit_reason"] = f"收盘价跌破动态防守线 {trailing_stop['price']}"
            summary = lifecycle["exit_reason"]
        elif just_exited:
            action = "sell"
            marker_role = "sell"
            marker_level = "strong"
            marker_reason = "v2_structure_break"
            summary = lifecycle["exit_reason"]
        elif manage_existing_position and strong_zone:
            action = "scale_out"
            marker_role = "scale_out"
            marker_level = "normal"
            marker_reason = "strong_resistance"
            lifecycle["position_state"] = "scale_out"
            scale_out = {
                "source": strong_zone.get("source"),
                "label": strong_zone.get("label"),
                "price": strong_zone.get("price"),
                "strength_score": strong_zone.get("strength_score"),
                "distance_pct": strong_zone.get("distance_pct"),
                "reason": "触及核心强阻，只生成收益保护条件，不直接替代 S 点。",
            }
            summary = f"触及核心强阻 {strong_zone.get('label')}，收益保护条件已触发，未生成 S 点。"
        elif has_active_position:
            summary = "信号后跟踪周期有效，继续沿动态防守线观察。"
        elif lifecycle["position_state"] == "exited":
            summary = "上一轮信号后跟踪已结束，等待下一轮入场信号后重新激活防守线。"

    return {
        "available": bool(entry_pos is not None),
        "source": "c_signal_v2_p11_exit_gate",
        "position_lifecycle": lifecycle,
        "trailing_stop": trailing_stop,
        "observations": observations,
        "scale_out": scale_out,
        "action": action,
        "marker_role": marker_role,
        "marker_level": marker_level,
        "marker_reason": marker_reason,
        "summary": summary,
    }


def build_williams_fractal_facts(df_display, lookback=80, normalization_param=None):
    """Detect confirmed five-bar Williams fractals.

    The latest two bars are excluded because a five-bar fractal needs two bars
    of right-side confirmation. P9-A runs K-line inclusion handling first so
    fractals are detected on structure bars while still mapping back to the
    original trading dates.
    """
    if df_display is None or df_display.empty or not {"high", "low"}.issubset(df_display.columns):
        return {
            "available": False,
            "confirmation_lag": 2,
            "normalization_used": False,
            "original_count": 0,
            "normalized_count": 0,
            "containment_count": 0,
            "merge_count": 0,
            "latest_bottom": None,
            "latest_top": None,
            "recent_bottoms": [],
            "recent_tops": [],
            "double_bottom_higher_low": False,
            "top_lower_high": False,
            "summary": "缺少高低点数据，无法计算威廉分型。",
        }

    normalization = _normalize_kline_inclusion_frame(df_display, lookback=lookback) if normalization_param is None else normalization_param
    window = normalization["frame"]
    if len(window) < 5:
        return {
            "available": False,
            "confirmation_lag": 2,
            "normalization_used": bool(normalization["available"]),
            "original_count": normalization["original_count"],
            "normalized_count": normalization["normalized_count"],
            "containment_count": normalization["containment_count"],
            "merge_count": normalization["merge_count"],
            "latest_bottom": None,
            "latest_top": None,
            "recent_bottoms": [],
            "recent_tops": [],
            "double_bottom_higher_low": False,
            "top_lower_high": False,
            "summary": "样本不足，至少需要 5 根 K 线确认分型。",
        }

    high = window["high"]
    low = window["low"]

    bottoms = []
    tops = []
    all_source_indices = [
        _source_index(source_index)
        for indices in window["source_indices"]
        for source_index in list(indices or [])
        if isinstance(_source_index(source_index), int)
    ]
    latest_source_index = max(all_source_indices) if all_source_indices else None

    for pos in range(2, len(window)):
        row = window.iloc[pos]
        center_low_source_index = row.get("low_source_index")
        center_high_source_index = row.get("high_source_index")
        low_index = _source_index(center_low_source_index)
        high_index = _source_index(center_high_source_index)
        bottom_confirmed = latest_source_index is None or (
            isinstance(low_index, int) and low_index <= latest_source_index - 2
        )
        top_confirmed = latest_source_index is None or (
            isinstance(high_index, int) and high_index <= latest_source_index - 2
        )
        local_high = high.iloc[pos - 2:min(len(window), pos + 3)]
        local_low = low.iloc[pos - 2:min(len(window), pos + 3)]
        if len(local_high) < 4 or len(local_low) < 4:
            continue
        center_high = high.iloc[pos]
        center_low = low.iloc[pos]
        if bottom_confirmed and center_low == local_low.min() and int((local_low == center_low).sum()) == 1:
            bottoms.append(_fractal_payload(row, "bottom"))
        if top_confirmed and center_high == local_high.max() and int((local_high == center_high).sum()) == 1:
            tops.append(_fractal_payload(row, "top"))

    recent_bottoms = bottoms[-3:]
    recent_tops = tops[-3:]
    double_bottom_higher_low = False
    if len(recent_bottoms) >= 2:
        double_bottom_higher_low = (
            recent_bottoms[-1]["price"] is not None
            and recent_bottoms[-2]["price"] is not None
            and recent_bottoms[-1]["price"] > recent_bottoms[-2]["price"]
        )
    top_lower_high = False
    if len(recent_tops) >= 2:
        top_lower_high = (
            recent_tops[-1]["price"] is not None
            and recent_tops[-2]["price"] is not None
            and recent_tops[-1]["price"] < recent_tops[-2]["price"]
        )

    if double_bottom_higher_low:
        summary = "已确认两个底分型，后一低点抬高。"
    elif recent_bottoms:
        summary = "已确认底分型，但双底抬高结构尚不完整。"
    elif recent_tops:
        summary = "已确认顶分型，优先作为风险或压力事实。"
    else:
        summary = "近期没有确认分型。"

    return {
        "available": True,
        "confirmation_lag": 2,
        "normalization_used": True,
        "original_count": normalization["original_count"],
        "normalized_count": normalization["normalized_count"],
        "containment_count": normalization["containment_count"],
        "merge_count": normalization["merge_count"],
        "latest_bottom": recent_bottoms[-1] if recent_bottoms else None,
        "latest_top": recent_tops[-1] if recent_tops else None,
        "recent_bottoms": recent_bottoms,
        "recent_tops": recent_tops,
        "double_bottom_higher_low": bool(double_bottom_higher_low),
        "top_lower_high": bool(top_lower_high),
        "summary": summary,
    }


def build_rectangle_facts(df_display, lookback=20, max_width_pct=20.0):
    if df_display is None or df_display.empty or not {"high", "low", "close"}.issubset(df_display.columns):
        return {"available": False, "summary": "缺少高低收数据，无法计算矩形边界。"}
    window = df_display.tail(lookback).copy()
    if len(window) < 10:
        return {"available": False, "summary": "样本不足，至少需要 10 根 K 线估算矩形。"}

    latest = window.iloc[-1]
    upper = _as_float(window["high"].max())
    lower = _as_float(window["low"].min())
    lowest_close = _as_float(window["close"].min())
    close = _as_float(latest.get("close"))
    mid = (upper + lower) / 2 if upper is not None and lower is not None else None
    width_pct = None if mid in {None, 0} else round((upper - lower) / mid * 100, 2)
    available = bool(width_pct is not None and width_pct <= max_width_pct)
    inside = bool(available and lower <= close <= upper) if close is not None else False
    near_upper_pct = _pct_distance(upper, close)
    near_lower_pct = _pct_distance(close, lowest_close)
    c_point = lowest_close

    return {
        "available": available,
        "lookback": int(len(window)),
        "upper": _round(upper),
        "lower": _round(lower),
        "lowest_close": _round(lowest_close),
        "mid": _round(mid),
        "width_pct": width_pct,
        "inside": inside,
        "near_upper_pct": near_upper_pct,
        "near_lower_pct": near_lower_pct,
        "breakout_price": _round(upper),
        "c_point": _round(c_point),
        "c_point_source": "lowest_close",
        "invalidation_price": _round(c_point),
        "summary": (
            f"近{len(window)}日矩形宽度 {width_pct:.2f}%，C点取箱体最低收盘价。"
            if available and width_pct is not None
            else "近期波动区间过宽，暂不作为稳定矩形。"
        ),
    }


def _rectangle_touch_count(series, level, tolerance_pct):
    level_value = _as_float(level)
    if series is None or level_value in {None, 0}:
        return 0
    tolerance = abs(level_value) * tolerance_pct / 100
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return 0
    return int(((values - level_value).abs() <= tolerance).sum())


def _rectangle_latest_position(close, upper, lower):
    close_value = _as_float(close)
    upper_value = _as_float(upper)
    lower_value = _as_float(lower)
    if close_value is None or upper_value is None or lower_value is None:
        return "unknown"
    if close_value > upper_value:
        return "breakout"
    if close_value < lower_value:
        return "breakdown"
    width = upper_value - lower_value
    if width <= 0:
        return "unknown"
    ratio = (close_value - lower_value) / width
    if ratio >= 0.75:
        return "near_upper"
    if ratio <= 0.25:
        return "near_lower"
    return "middle"


def _rectangle_quality_score(width_pct, max_width_pct, upper_touches, lower_touches, close_series):
    width_value = _as_float(width_pct)
    max_width_value = _as_float(max_width_pct)
    if width_value is None or max_width_value in {None, 0}:
        return 0
    width_score = max(0, min(35, int(round((1 - min(width_value, max_width_value) / max_width_value) * 35))))
    touch_score = min(35, (upper_touches + lower_touches) * 5)
    closes = pd.to_numeric(close_series, errors="coerce").dropna()
    exchange_score = 0
    if len(closes) >= 6:
        median = closes.median()
        above = int((closes >= median).sum())
        below = int((closes < median).sum())
        exchange_score = min(20, min(above, below) * 4)
    return int(min(100, 10 + width_score + touch_score + exchange_score))


def _bounded_extremes(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return min(values), max(values)


def _rectangle_candidate_from_bars(bars, *, family, lookback, max_width_pct, normalization):
    """_rectangle_candidate_from_window 的列表版：与 pandas 路径逐字段等价，纯 Python 计数。"""
    if len(bars) < 10:
        return {
            "available": False,
            "family": family,
            "lookback": int(len(bars)),
            "requested_lookback": int(lookback),
            "summary": "样本不足，无法估算矩形。",
        }
    highs = [_as_float(bar.get("high")) for bar in bars]
    lows = [_as_float(bar.get("low")) for bar in bars]
    closes = [_as_float(bar.get("close")) for bar in bars]
    upper_pair = _bounded_extremes(highs)
    lower_pair = _bounded_extremes(lows)
    if upper_pair is None or lower_pair is None:
        return {
            "available": False,
            "family": family,
            "lookback": int(len(bars)),
            "requested_lookback": int(lookback),
            "summary": "样本不足，无法估算矩形。",
        }
    upper = upper_pair[1]
    lower = lower_pair[0]
    close_pairs = [value for value in closes if value is not None]
    lowest_close = min(close_pairs) if close_pairs else None
    close = _as_float(bars[-1].get("close"))
    previous_bars = bars[:-1]
    previous_upper = None
    previous_lower = None
    if previous_bars:
        prev_highs = [_as_float(bar.get("high")) for bar in previous_bars]
        prev_lows = [_as_float(bar.get("low")) for bar in previous_bars]
        prev_high_pair = _bounded_extremes(prev_highs)
        prev_low_pair = _bounded_extremes(prev_lows)
        previous_upper = prev_high_pair[1] if prev_high_pair else None
        previous_lower = prev_low_pair[0] if prev_low_pair else None
    mid = (upper + lower) / 2 if upper is not None and lower is not None else None
    width_pct = None if mid in {None, 0} else round((upper - lower) / mid * 100, 2)
    available = bool(width_pct is not None and width_pct <= max_width_pct)
    tolerance = abs(upper) * 1.5 / 100
    upper_touches = sum(1 for value in highs if value is not None and abs(value - upper) <= tolerance)
    lower_tolerance = abs(lower) * 1.5 / 100
    lower_touches = sum(1 for value in lows if value is not None and abs(value - lower) <= lower_tolerance)
    touch_count = int(upper_touches + lower_touches)
    latest_position = _rectangle_latest_position(close, upper, lower)
    sorted_closes = sorted(close_pairs)
    median = (
        sorted_closes[len(sorted_closes) // 2]
        if len(sorted_closes) % 2
        else (sorted_closes[len(sorted_closes) // 2 - 1] + sorted_closes[len(sorted_closes) // 2]) / 2
    ) if sorted_closes else None
    exchange_score = 0
    if len(sorted_closes) >= 6 and median:
        above = sum(1 for value in close_pairs if value >= median)
        below = len(close_pairs) - above
        exchange_score = min(20, min(above, below) * 4)
    width_value = _as_float(width_pct)
    max_width_value = _as_float(max_width_pct)
    if width_value is None or max_width_value in {None, 0}:
        quality_score = 0
    else:
        width_score = max(0, min(35, int(round((1 - min(width_value, max_width_value) / max_width_value) * 35))))
        quality_score = int(min(100, 10 + width_score + min(35, touch_count * 5) + exchange_score))
    start_date = bars[0].get("source_start_date") or bars[0].get("date")
    end_date = bars[-1].get("source_end_date") or bars[-1].get("date")

    return {
        "available": available,
        "family": family,
        "lookback": int(len(bars)),
        "requested_lookback": int(lookback),
        "source_kind": "normalized",
        "normalization_merge_count": normalization["merge_count"],
        "max_width_pct": _round(max_width_pct),
        "start_date": _format_date(start_date),
        "end_date": _format_date(end_date),
        "upper": _round(upper),
        "lower": _round(lower),
        "previous_upper": _round(previous_upper),
        "previous_lower": _round(previous_lower),
        "lowest_close": _round(lowest_close),
        "mid": _round(mid),
        "width_pct": width_pct,
        "inside": bool(available and lower <= close <= upper) if close is not None else False,
        "breaks_previous_upper": bool(close is not None and previous_upper is not None and close > previous_upper),
        "breaks_previous_lower": bool(close is not None and previous_lower is not None and close < previous_lower),
        "near_upper_pct": _pct_distance(upper, close),
        "near_lower_pct": _pct_distance(close, lowest_close),
        "breakout_price": _round(upper),
        "c_point": _round(lowest_close),
        "c_point_source": "lowest_close",
        "invalidation_price": _round(lowest_close),
        "touch_count": touch_count,
        "upper_touch_count": int(upper_touches),
        "lower_touch_count": int(lower_touches),
        "latest_position": latest_position,
        "quality_score": quality_score,
        "summary": (
            f"{family}近{len(bars)}根结构K线矩形宽度 {width_pct:.2f}%，质量 {quality_score}。"
            if width_pct is not None
            else f"{family}近{len(bars)}根结构K线无法计算稳定宽度。"
        ),
    }


def _rectangle_candidate_from_window(window, *, family, lookback, max_width_pct):
    if window is None or window.empty or len(window) < 10 or not {"high", "low", "close"}.issubset(window.columns):
        return {
            "available": False,
            "family": family,
            "lookback": int(lookback),
            "summary": "样本不足，无法估算矩形。",
        }
    normalization = _normalize_kline_inclusion_frame(window, lookback=lookback)
    if normalization["available"] and normalization["normalized_count"] >= 10:
        # 快路径：直接消费归一化 bars 列表，避免每根 K 线事件重放时反复构建 DataFrame。
        return _rectangle_candidate_from_bars(
            [bar for bar in normalization["bars"] if isinstance(bar, dict)],
            family=family,
            lookback=lookback,
            max_width_pct=max_width_pct,
            normalization=normalization,
        )
    scan = window.tail(lookback).copy()
    source_kind = "raw_fallback"
    if len(scan) < 10:
        return {
            "available": False,
            "family": family,
            "lookback": int(len(scan)),
            "requested_lookback": int(lookback),
            "summary": "样本不足，无法估算矩形。",
        }

    latest = scan.iloc[-1]
    upper = _as_float(scan["high"].max())
    lower = _as_float(scan["low"].min())
    lowest_close = _as_float(scan["close"].min())
    close = _as_float(latest.get("close"))
    previous_scan = scan.iloc[:-1]
    previous_upper = _as_float(previous_scan["high"].max()) if not previous_scan.empty else None
    previous_lower = _as_float(previous_scan["low"].min()) if not previous_scan.empty else None
    mid = (upper + lower) / 2 if upper is not None and lower is not None else None
    width_pct = None if mid in {None, 0} else round((upper - lower) / mid * 100, 2)
    available = bool(width_pct is not None and width_pct <= max_width_pct)
    upper_touches = _rectangle_touch_count(scan["high"], upper, 1.5)
    lower_touches = _rectangle_touch_count(scan["low"], lower, 1.5)
    touch_count = int(upper_touches + lower_touches)
    latest_position = _rectangle_latest_position(close, upper, lower)
    quality_score = _rectangle_quality_score(width_pct, max_width_pct, upper_touches, lower_touches, scan["close"])
    c_point = lowest_close
    start_date = scan.iloc[0].get("source_start_date") or scan.iloc[0].get("date")
    end_date = scan.iloc[-1].get("source_end_date") or scan.iloc[-1].get("date")

    return {
        "available": available,
        "family": family,
        "lookback": int(len(scan)),
        "requested_lookback": int(lookback),
        "source_kind": source_kind,
        "normalization_merge_count": normalization["merge_count"],
        "max_width_pct": _round(max_width_pct),
        "start_date": _format_date(start_date),
        "end_date": _format_date(end_date),
        "upper": _round(upper),
        "lower": _round(lower),
        "previous_upper": _round(previous_upper),
        "previous_lower": _round(previous_lower),
        "lowest_close": _round(lowest_close),
        "mid": _round(mid),
        "width_pct": width_pct,
        "inside": bool(available and lower <= close <= upper) if close is not None else False,
        "breaks_previous_upper": bool(close is not None and previous_upper is not None and close > previous_upper),
        "breaks_previous_lower": bool(close is not None and previous_lower is not None and close < previous_lower),
        "near_upper_pct": _pct_distance(upper, close),
        "near_lower_pct": _pct_distance(close, lowest_close),
        "breakout_price": _round(upper),
        "c_point": _round(c_point),
        "c_point_source": "lowest_close",
        "invalidation_price": _round(c_point),
        "touch_count": touch_count,
        "upper_touch_count": int(upper_touches),
        "lower_touch_count": int(lower_touches),
        "latest_position": latest_position,
        "quality_score": quality_score,
        "summary": (
            f"{family}近{len(scan)}根结构K线矩形宽度 {width_pct:.2f}%，质量 {quality_score}。"
            if width_pct is not None
            else f"{family}近{len(scan)}根结构K线无法计算稳定宽度。"
        ),
    }


def _best_rectangle_candidate(candidates):
    available = [item for item in candidates if item.get("available")]
    if not available:
        return None
    return max(available, key=lambda item: (item.get("quality_score") or 0, item.get("lookback") or 0))


def build_rectangle_candidate_facts(df_display):
    """Build short/swing/macro rectangle candidates for P9-B structure facts."""
    if df_display is None or df_display.empty or not {"high", "low", "close"}.issubset(df_display.columns):
        return {
            "available": False,
            "short_rectangle": None,
            "swing_rectangle": None,
            "macro_rectangle": None,
            "active_rectangle": {"available": False, "summary": "缺少高低收数据，无法生成多周期矩形。"},
            "all_candidates": [],
            "active_reason": "缺少高低收数据。",
            "summary": "缺少高低收数据，无法生成多周期矩形。",
        }

    normalization = _normalize_kline_inclusion_frame(df_display, lookback=250)
    groups = {
        "short": {"windows": (10, 15, 20, 30), "max_width_pct": 20.0},
        "swing": {"windows": (30, 40, 60), "max_width_pct": 30.0},
        "macro": {"windows": (120, 180, 250), "max_width_pct": 60.0},
    }

    grouped = {}
    all_candidates = []
    for family, config in groups.items():
        candidates = [
            _rectangle_candidate_from_window(
                df_display,
                family=family,
                lookback=lookback,
                max_width_pct=config["max_width_pct"],
            )
            for lookback in config["windows"]
        ]
        grouped[family] = {
            "candidates": candidates,
            "selected": _best_rectangle_candidate(candidates),
        }
        all_candidates.extend(candidates)

    short_rectangle = grouped["short"]["selected"]
    swing_rectangle = grouped["swing"]["selected"]
    macro_rectangle = grouped["macro"]["selected"]
    active_rectangle = short_rectangle or swing_rectangle
    if active_rectangle:
        active_reason = f"优先使用{active_rectangle['family']}矩形解释本次短线信号。"
    elif macro_rectangle:
        active_rectangle = {
            **macro_rectangle,
            "available": False,
            "active_blocked_by": "macro_not_entry_rectangle",
            "summary": "仅识别到一年级别矩形，作为结构背景，不直接用于短线入场止损。",
        }
        active_reason = "仅有一年级别矩形，不能直接作为短线入场矩形。"
    else:
        active_rectangle = {"available": False, "summary": "未找到宽度合格的短线或波段矩形。"}
        active_reason = "未找到宽度合格的矩形。"

    summary_parts = []
    for label, candidate in (("短线", short_rectangle), ("波段", swing_rectangle), ("一年", macro_rectangle)):
        if candidate:
            summary_parts.append(f"{label}{candidate['lookback']}根/质量{candidate['quality_score']}")
    summary = "；".join(summary_parts) if summary_parts else active_reason

    return {
        "available": bool(short_rectangle or swing_rectangle or macro_rectangle),
        "normalization": {
            "used": bool(normalization["available"]),
            "original_count": normalization["original_count"],
            "normalized_count": normalization["normalized_count"],
            "merge_count": normalization["merge_count"],
        },
        "short_rectangle": short_rectangle,
        "swing_rectangle": swing_rectangle,
        "macro_rectangle": macro_rectangle,
        "active_rectangle": active_rectangle,
        "active_reason": active_reason,
        "all_candidates": all_candidates,
        "summary": summary,
    }


def build_bear_trap_recovery_facts(df_display, rectangle=None, macro_rectangle=None, *, break_pct=3.0, recover_days=3):
    """Detect a mild box breakdown followed by quick recovery.

    This is a structure fact. It does not grant trade permission; the state and
    plan layers decide whether a recovered structure is tradable.
    """
    empty = {
        "available": False,
        "recovered": False,
        "breakout_after_recovery": False,
        "macro_breakout_after_recovery": False,
        "break_pct_limit": _round(break_pct, 2),
        "recover_days_limit": int(recover_days),
        "break_date": "",
        "recover_date": "",
        "break_low": None,
        "break_depth_pct": None,
        "box_lower": None,
        "box_mid": None,
        "box_upper": None,
        "stop_price": None,
        "summary": "缺少结构或行情数据，无法识别破底翻。",
    }
    if df_display is None or df_display.empty or not {"high", "low", "close"}.issubset(df_display.columns):
        return empty
    rectangle = rectangle if isinstance(rectangle, dict) else {}
    full_window = df_display.copy()
    if full_window.empty:
        return empty
    requested_lookback = _as_int(rectangle.get("requested_lookback") or rectangle.get("lookback"), 20)
    latest = full_window.iloc[-1]
    latest_high = _as_float(latest.get("high"))
    latest_low = _as_float(latest.get("low"))
    latest_close = _as_float(latest.get("close"))
    latest_open = _as_float(latest.get("open"), latest_close)
    if None in {latest_high, latest_low, latest_close}:
        return {**empty, "summary": "缺少最新高低收数据，无法识别破底翻。"}

    start_pos = max(0, len(full_window) - recover_days - 1)
    break_rows = []
    for pos in range(start_pos, len(full_window)):
        row = full_window.iloc[pos]
        prior = full_window.iloc[max(0, pos - requested_lookback):pos]
        if len(prior) < 10:
            continue
        lower = _as_float(prior["low"].min())
        upper = _as_float(prior["high"].max())
        if lower is None or upper is None or upper <= lower:
            continue
        low = _as_float(row.get("low"))
        close = _as_float(row.get("close"))
        if low is None:
            continue
        max_break_depth = lower * (1 - break_pct / 100)
        mild_break = bool(low < lower and low >= max_break_depth)
        severe_close_break = bool(close is not None and close < max_break_depth)
        if mild_break and not severe_close_break:
            break_rows.append((pos, row, low, lower, upper))

    fallback_lower = _as_float(rectangle.get("previous_lower") or rectangle.get("lower"))
    fallback_upper = _as_float(rectangle.get("previous_upper") or rectangle.get("upper"))
    if not break_rows:
        return {
            **empty,
            "available": bool(fallback_lower is not None and fallback_upper is not None),
            "box_lower": _round(fallback_lower),
            "box_upper": _round(fallback_upper),
            "box_mid": _round((fallback_upper + fallback_lower) / 2) if None not in {fallback_lower, fallback_upper} else None,
            "summary": "近期未出现轻微破底后的快速收回。",
        }

    break_pos, break_row, break_low, lower, upper = min(break_rows, key=lambda item: item[2])
    days_to_recover = len(full_window) - 1 - break_pos
    mid = (upper + lower) / 2
    recovered = bool(days_to_recover <= recover_days and latest_close >= lower)
    recovered_to_mid = bool(recovered and latest_close >= mid)
    breakout_after_recovery = bool(recovered and latest_close > upper)
    macro_upper = _as_float((macro_rectangle or {}).get("previous_upper") or (macro_rectangle or {}).get("upper")) if isinstance(macro_rectangle, dict) else None
    macro_breakout_after_recovery = bool(breakout_after_recovery and macro_upper is not None and latest_close > macro_upper)
    not_continued_selloff = bool(latest_close >= latest_open or latest_close >= _as_float(break_row.get("close"), latest_close))
    break_depth_pct = _pct_distance(break_low, lower)
    stop_price = break_low

    if breakout_after_recovery:
        summary = "破底翻后重新突破箱体上沿，可交给状态层解释为新的突破候选。"
    elif recovered_to_mid:
        summary = "轻微破底后已收回箱体中位，仍需等待突破触发。"
    elif recovered:
        summary = "轻微破底后已收回箱体下沿，仍属于修复观察。"
    else:
        summary = "发生轻微破底，但尚未完成快速收回。"

    return {
        "available": True,
        "recovered": recovered,
        "recovered_to_mid": recovered_to_mid,
        "breakout_after_recovery": breakout_after_recovery,
        "macro_breakout_after_recovery": macro_breakout_after_recovery,
        "not_continued_selloff": not_continued_selloff,
        "break_pct_limit": _round(break_pct, 2),
        "recover_days_limit": int(recover_days),
        "days_to_recover": int(days_to_recover),
        "break_date": _format_date(break_row.get("date")),
        "recover_date": _format_date(latest.get("date")),
        "break_low": _round(break_low),
        "break_depth_pct": break_depth_pct,
        "box_lower": _round(lower),
        "box_mid": _round(mid),
        "box_upper": _round(upper),
        "macro_upper": _round(macro_upper),
        "stop_price": _round(stop_price),
        "summary": summary,
    }


def build_trigger_facts(df_display, ignition_multiplier=1.0):
    if df_display is None or len(df_display) < 2:
        return {
            "available": False,
            "attack_day": False,
            "loose_attack_day": False,
            "bearish_engulfing_new_low": False,
            "gap_fill_reversal": False,
            "ignition": {"available": False},
            "summary": "样本不足，无法计算攻击日或起爆点。",
        }

    latest = df_display.iloc[-1]
    previous = df_display.iloc[-2]
    open_price = _as_float(latest.get("open"))
    high = _as_float(latest.get("high"))
    low = _as_float(latest.get("low"))
    close = _as_float(latest.get("close"))
    prev_open = _as_float(previous.get("open"))
    prev_high = _as_float(previous.get("high"))
    prev_low = _as_float(previous.get("low"))
    prev_close = _as_float(previous.get("close"))
    if None in {open_price, high, low, close, prev_open, prev_high, prev_low, prev_close}:
        return {
            "available": False,
            "attack_day": False,
            "loose_attack_day": False,
            "bearish_engulfing_new_low": False,
            "gap_fill_reversal": False,
            "ignition": {"available": False},
            "summary": "缺少 OHLC 数据，无法计算攻击日或起爆点。",
        }

    volume = _as_float(latest.get("volume"), 0.0) or 0.0
    volume_ma20 = _as_float(latest.get("vol_ma20"))
    if volume_ma20 is None and "volume" in df_display.columns:
        volume_ma20 = _as_float(df_display["volume"].tail(20).mean())
    volume_expand = bool(volume_ma20 and volume > volume_ma20 * 1.2)

    ranges = (df_display["high"] - df_display["low"]).tail(20) if {"high", "low"}.issubset(df_display.columns) else pd.Series([])
    avg_range = _as_float(ranges.mean())
    range_expansion = bool(avg_range and (high - low) >= avg_range * 1.25)
    bullish_engulfing = bool(close > open_price and prev_close < prev_open and open_price <= prev_close and close >= prev_open)
    breaks_prev_high = bool(close > prev_high or high > prev_high)
    loose_attack_day = bool(close > open_price and breaks_prev_high and (bullish_engulfing or range_expansion or volume_expand))

    strict_attack = {
        "available": False,
        "day1_date": "",
        "day2_date": "",
        "day3_date": _format_date(latest.get("date")),
        "trigger_price": None,
        "stop_price": None,
        "day1_small_bull": False,
        "day2_washout_bear": False,
        "day2_breaks_day1_low": False,
        "day2_tests_above_day1_high": False,
        "day2_stage_new_low": False,
        "day3_breaks_day2_high": False,
        "triggered": False,
    }
    if len(df_display) >= 3:
        day1 = df_display.iloc[-3]
        day2 = previous
        day1_open = _as_float(day1.get("open"))
        day1_high = _as_float(day1.get("high"))
        day1_low = _as_float(day1.get("low"))
        day1_close = _as_float(day1.get("close"))
        if None not in {day1_open, day1_high, day1_low, day1_close}:
            stage_lows = df_display.iloc[-3:-1]["low"] if "low" in df_display.columns else pd.Series([])
            stage_low = _as_float(stage_lows.min())
            trigger_price = prev_high + 0.01
            strict_attack.update({
                "available": True,
                "day1_date": _format_date(day1.get("date")),
                "day2_date": _format_date(day2.get("date")),
                "trigger_price": _round(trigger_price),
                "stop_price": _round(prev_low),
                "day1_small_bull": bool(day1_close > day1_open),
                "day2_washout_bear": bool(prev_open >= day1_close and prev_close < prev_open and prev_close <= (prev_high + prev_low) / 2),
                "day2_breaks_day1_low": bool(prev_low < day1_low),
                "day2_tests_above_day1_high": bool(prev_high > day1_high),
                "day2_stage_new_low": bool(stage_low is not None and prev_low <= stage_low),
                "day3_breaks_day2_high": bool(high >= trigger_price and close > open_price),
            })
            strict_attack["triggered"] = bool(
                strict_attack["day1_small_bull"]
                and strict_attack["day2_washout_bear"]
                and strict_attack["day2_breaks_day1_low"]
                and strict_attack["day2_tests_above_day1_high"]
                and strict_attack["day2_stage_new_low"]
                and strict_attack["day3_breaks_day2_high"]
            )
    attack_day = bool(strict_attack["triggered"])

    rolling_low = _as_float(df_display["low"].tail(20).min()) if "low" in df_display.columns else None
    bearish_engulfing = bool(close < open_price and prev_close > prev_open and open_price >= prev_close and close <= prev_open)
    bearish_engulfing_new_low = bool(bearish_engulfing and rolling_low is not None and low <= rolling_low)
    gap_down_pct = None if prev_close in {None, 0} else (open_price - prev_close) / prev_close * 100
    gap_fill_reversal = bool(
        gap_down_pct is not None
        and gap_down_pct <= -1.5
        and high >= prev_close
        and close > open_price
    )
    gap_fill = {
        "available": True,
        "gap_down_pct": _round(gap_down_pct, 2),
        "filled_previous_close": bool(high >= prev_close),
        "stop_price": _round(low) if gap_fill_reversal else None,
        "triggered": gap_fill_reversal,
    }

    ignition_trigger = open_price + max(prev_high - prev_close, 0) * ignition_multiplier
    ignition_triggered = bool(high >= ignition_trigger and close >= ignition_trigger)
    ignition = {
        "available": True,
        "multiplier": ignition_multiplier,
        "trigger_price": _round(ignition_trigger),
        "triggered": ignition_triggered,
        "source": "today_open_plus_previous_high_close_gap",
    }

    if attack_day and ignition_triggered:
        summary = "严格攻击日与起爆点同时触发。"
    elif attack_day:
        summary = "出现严格攻击日事实，但仍需结构和交易计划确认。"
    elif gap_fill_reversal:
        summary = "出现缺口回补反转事实，需以早盘低点校验止损赔率。"
    elif ignition_triggered:
        summary = "起爆点触发，但仍需检查结构止损和收益风险比。"
    elif bearish_engulfing_new_low:
        summary = "出现阴包阳创新低，优先作为观察或风险事实。"
    else:
        summary = "暂无明确攻击日或起爆点事实。"

    return {
        "available": True,
        "attack_day": attack_day,
        "loose_attack_day": loose_attack_day,
        "strict_attack": strict_attack,
        "bullish_engulfing": bullish_engulfing,
        "breaks_prev_high": breaks_prev_high,
        "volume_expand": volume_expand,
        "range_expansion": range_expansion,
        "bearish_engulfing_new_low": bearish_engulfing_new_low,
        "gap_fill_reversal": gap_fill_reversal,
        "gap_fill": gap_fill,
        "ignition": ignition,
        "summary": summary,
    }


def _numeric_series(df_display, column):
    if df_display is None or column not in getattr(df_display, "columns", []):
        return None
    return pd.to_numeric(df_display[column], errors="coerce")


def _v2_trend_flags(df_display):
    """V2-native trend flags so the fact layer stops reading legacy signal columns."""
    latest = _latest_row(df_display)
    if latest is None:
        return {"available": False, "above_ma20": False, "ma20_up": False, "trend_ok": False}
    close = _as_float(latest.get("close"))
    ma20 = _as_float(latest.get("ma20"))
    ma20_series = _numeric_series(df_display, "ma20")
    ma20_up = False
    if ma20_series is not None and len(ma20_series.dropna()) >= 4:
        current = _as_float(ma20_series.iloc[-1])
        prior = _as_float(ma20_series.iloc[-4])
        ma20_up = bool(current is not None and prior is not None and current > prior)
    adx = _as_float(latest.get("adx"))
    if adx is not None:
        trend_ok = bool(adx >= TREND_ADX_MIN)
    else:
        trend_ok = bool(close is not None and ma20 is not None and close >= ma20)
    return {
        "available": close is not None,
        "above_ma20": bool(close is not None and ma20 is not None and close >= ma20),
        "ma20_up": ma20_up,
        "trend_ok": trend_ok,
    }


def build_divergence_series(df_display, lookback=DIVERGENCE_LOOKBACK):
    """Return a per-bar V2 bottom divergence series (fresh low with improving MACD hist)."""
    if df_display is None or df_display.empty:
        return pd.Series(dtype=bool)
    lows = _numeric_series(df_display, "low")
    hist = _numeric_series(df_display, "macd_hist")
    if lows is None or hist is None:
        return pd.Series(False, index=df_display.index)
    low_values = lows.tolist()
    hist_values = hist.tolist()
    flags = pd.Series(False, index=df_display.index)
    length = len(low_values)
    for i in range(lookback, length):
        current_low = low_values[i]
        if current_low is None or current_low != current_low:
            continue
        start = i - lookback + 1
        window_lows = [value for value in low_values[start:i + 1] if value is not None and value == value]
        if not window_lows or current_low > min(window_lows):
            continue
        prior = [
            (position, low_values[position])
            for position in range(start, i)
            if low_values[position] is not None and low_values[position] == low_values[position]
        ]
        if not prior:
            continue
        prior_pos, prior_low = min(prior, key=lambda item: item[1])
        current_hist = hist_values[i]
        prior_hist = hist_values[prior_pos]
        if current_hist is None or current_hist != current_hist:
            continue
        if prior_hist is None or prior_hist != prior_hist:
            continue
        if current_low < prior_low and current_hist > prior_hist and prior_hist < 0:
            flags.iloc[i] = True
    return flags


def build_v2_divergence_facts(df_display, lookback=DIVERGENCE_LOOKBACK):
    """V2-native bottom divergence fact, replacing legacy ``is_bottom_divergence``."""
    series = build_divergence_series(df_display, lookback=lookback)
    if series.empty:
        return {
            "available": False,
            "bottom_divergence": False,
            "current": False,
            "recent": False,
            "lookback": lookback,
            "summary": "缺少行情数据，无法判断 V2 底背离。",
        }
    current = bool(series.iloc[-1])
    recent = bool(series.tail(DIVERGENCE_RECENT_BARS).any())
    if current:
        summary = "价格创新低但 MACD 柱改善，当前出现 V2 底背离。"
    elif recent:
        summary = "近 8 根出现 V2 底背离，等待右侧修复。"
    else:
        summary = "近期未出现 V2 底背离。"
    return {
        "available": True,
        "bottom_divergence": current,
        "current": current,
        "recent": recent,
        "lookback": lookback,
        "summary": summary,
    }


def build_v2_risk_facts(df_display, *, rectangle=None, exit_gate=None):
    """V2-native risk model replacing composite risk scores.

    ``risk_break_score`` counts structural breaks, ``risk_heat_score`` counts
    extension, and the two combine into a 0-4 ``risk_score`` used by permission
    gates (>=3 blocks entry, >=4 forces risk control).
    """
    latest = _latest_row(df_display)
    empty = {
        "available": False,
        "risk_score": 0,
        "risk_break_score": 0,
        "risk_heat_score": 0,
        "has_risk": False,
        "has_exit": False,
        "break_reasons": [],
        "heat_reasons": [],
        "summary": "缺少行情数据，无法评估 V2 风险。",
    }
    if latest is None:
        return empty
    close = _as_float(latest.get("close"))
    if close is None:
        return empty
    rectangle = rectangle if isinstance(rectangle, dict) else {}
    # 破位以"今天之前形成的结构"为参照：含当日的最低点永远不会被当日收盘跌破，
    # 否则 break_score 在生产路径上恒为 0（矩形下沿与近 20 日低点同病）。
    lower = _as_float(rectangle.get("previous_lower"))
    if lower is None:
        lower = _as_float(rectangle.get("lower"))
    break_score = 0
    break_reasons = []
    if lower is not None and close < lower:
        break_score += 1
        break_reasons.append("收盘跌破矩形下沿")
    lows = _numeric_series(df_display, "low")
    low_window = None
    if lows is not None and len(lows) > RISK_BREAK_LOOKBACK:
        low_window = _as_float(lows.iloc[-(RISK_BREAK_LOOKBACK + 1):-1].min())
    elif lows is not None and len(lows) > 1:
        low_window = _as_float(lows.iloc[:-1].min())
    if low_window is not None and close <= low_window:
        break_score += 1
        break_reasons.append(f"收盘创近{RISK_BREAK_LOOKBACK}日新低")
    break_score = min(3, break_score)

    heat_score = 0
    heat_reasons = []
    closes = _numeric_series(df_display, "close")
    if closes is not None and len(closes) >= 4:
        previous_close = _as_float(closes.iloc[-4])
        if previous_close:
            return_3d = (close / previous_close - 1) * 100
            if return_3d >= 15:
                heat_score = max(heat_score, 3)
            elif return_3d >= 10:
                heat_score = max(heat_score, 2)
            elif return_3d >= HEAT_RETURN_3D_PCT:
                heat_score = max(heat_score, 1)
            if return_3d >= HEAT_RETURN_3D_PCT:
                heat_reasons.append(f"近3日涨幅 {return_3d:.1f}%")
    ma20 = _as_float(latest.get("ma20"))
    if ma20:
        deviation = (close / ma20 - 1) * 100
        if deviation >= 20:
            heat_score = max(heat_score, 3)
        elif deviation >= 14:
            heat_score = max(heat_score, 2)
        elif deviation >= HEAT_MA20_DEVIATION_PCT:
            heat_score = max(heat_score, 1)
        if deviation >= HEAT_MA20_DEVIATION_PCT:
            heat_reasons.append(f"距 MA20 {deviation:.1f}%")
    heat_score = min(3, heat_score)

    exit_gate = exit_gate if isinstance(exit_gate, dict) else {}
    has_exit = exit_gate.get("action") == "sell"
    has_risk = bool(break_score >= 1 or heat_score >= 2 or has_exit)
    if has_exit:
        summary = "V2 离场事实已触发。"
    elif break_score:
        summary = "出现 V2 破位风险。"
    elif heat_score:
        summary = "出现 V2 过热风险。"
    else:
        summary = "V2 风险未触发。"
    return {
        "available": True,
        "risk_score": min(4, break_score + heat_score),
        "risk_break_score": break_score,
        "risk_heat_score": heat_score,
        "has_risk": has_risk,
        "has_exit": has_exit,
        "break_reasons": break_reasons,
        "heat_reasons": heat_reasons,
        "summary": summary,
    }


def build_v2_setup_facts(df_display, *, rectangle=None, trigger=None, momentum=None, divergence=None, normalized_bars=None):
    """V2-native setup/trigger facts replacing legacy ``composite_*_setup`` flags."""
    latest = _latest_row(df_display)
    empty = {
        "available": False,
        "breakout_setup": False,
        "pullback_setup": False,
        "breakout_trigger": False,
        "pullback_trigger": False,
        "prior_breakout": False,
        "repair_impulse": False,
        "repair_confirm": False,
        "bottom_divergence": False,
        "summary": "缺少行情数据，无法评估 V2 准备结构。",
    }
    if latest is None:
        return empty
    close = _as_float(latest.get("close"))
    open_price = _as_float(latest.get("open"))
    low = _as_float(latest.get("low"))
    ma20 = _as_float(latest.get("ma20"))
    if close is None:
        return empty
    rectangle = rectangle if isinstance(rectangle, dict) else {}
    # 突破必须以"今天之前形成的结构"为参照：含当日的窗口最高点永远不会被当日收盘突破。
    upper = _as_float(rectangle.get("previous_upper"))
    lower = _as_float(rectangle.get("previous_lower"))
    if lower is None:
        lower = _as_float(rectangle.get("lower"))
    highs = _numeric_series(df_display, "high")
    prior_high = None
    recent_high = None
    if highs is not None:
        if len(highs) > PRIOR_HIGH_LOOKBACK:
            prior_high = _as_float(highs.iloc[-(PRIOR_HIGH_LOOKBACK + 1):-1].max())
        recent_high = _as_float(highs.tail(10).max())
    tolerance = BREAKOUT_SETUP_TOLERANCE_PCT / 100
    # 矩形分支要求当日是独立结构 bar：若当日被包含合并进前一根（post-spike 回踩
    # 被长阳吸收），previous_upper 退化为长阳前的旧箱体，会把回踩误读成突破。
    fresh_breakout_bar = True
    if isinstance(normalized_bars, dict) and normalized_bars.get("available"):
        structure_bars = normalized_bars.get("recent_bars") or normalized_bars.get("bars") or []
        structure_bars = [bar for bar in structure_bars if isinstance(bar, dict)]
        if structure_bars:
            last_bar = structure_bars[-1]
            fresh_breakout_bar = len(last_bar.get("source_indices") or []) <= 1
    breakout_setup = bool(
        (upper is not None and close >= upper * (1 - tolerance))
        or (prior_high is not None and close >= prior_high * (1 - tolerance))
    )
    breakout_trigger = bool(
        (upper is not None and close > upper and fresh_breakout_bar)
        or (prior_high is not None and close > prior_high)
    )
    pullback_tolerance = PULLBACK_MA20_TOLERANCE_PCT / 100
    pulled_from_high = bool(
        ma20 is not None
        and recent_high is not None
        and recent_high >= ma20 * (1 + PULLBACK_RECENT_HIGH_PCT / 100)
    )
    pullback_setup = bool(
        pulled_from_high
        and ma20 is not None
        and close >= ma20 * (1 - pullback_tolerance)
        and (low is None or low <= ma20 * (1 + pullback_tolerance))
        and (lower is None or close >= lower)
    )
    pullback_trigger = bool(pullback_setup and open_price is not None and close > open_price)
    trigger = trigger if isinstance(trigger, dict) else {}
    momentum = momentum if isinstance(momentum, dict) else {}
    divergence = divergence if isinstance(divergence, dict) else {}
    repair_impulse = bool(trigger.get("gap_fill_reversal") or momentum.get("power_flip"))
    repair_confirm = bool(
        trigger.get("attack_day") or (trigger.get("ignition") or {}).get("triggered")
    )
    prior_breakout = bool(
        (prior_high is not None and close > prior_high)
        or rectangle.get("breaks_previous_upper")
    )
    return {
        "available": True,
        "breakout_setup": breakout_setup,
        "pullback_setup": pullback_setup,
        "breakout_trigger": breakout_trigger,
        "pullback_trigger": pullback_trigger,
        "prior_breakout": prior_breakout,
        "repair_impulse": repair_impulse,
        "repair_confirm": repair_confirm,
        "bottom_divergence": bool(divergence.get("bottom_divergence")),
        "recent_divergence": bool(divergence.get("recent")),
        "summary": "V2 结构准备已识别。" if (breakout_setup or pullback_setup) else "暂无 V2 结构准备。",
    }


def _v2_scores(latest, fractals, rectangle, trigger, clock, momentum, divergence, setup_facts, risk_facts):
    clock_state = (clock or {}).get("state")
    divergence = divergence if isinstance(divergence, dict) else {}
    setup_facts = setup_facts if isinstance(setup_facts, dict) else {}
    risk_facts = risk_facts if isinstance(risk_facts, dict) else {}

    research_score = 0
    if clock_state == "countdown":
        research_score += 35
    elif clock_state in {"compression_watch", "expanding"}:
        research_score += 20
    if divergence.get("recent"):
        research_score += 25
    if trigger.get("bearish_engulfing_new_low"):
        research_score += 15
    if setup_facts.get("pullback_setup") or setup_facts.get("breakout_setup"):
        research_score += 10

    structure_score = 0
    if fractals.get("latest_bottom"):
        structure_score += 25
    if fractals.get("double_bottom_higher_low"):
        structure_score += 35
    if rectangle.get("available"):
        structure_score += 30
    if setup_facts.get("pullback_setup") or setup_facts.get("breakout_setup"):
        structure_score += 10

    trigger_quality = 0
    if trigger.get("attack_day"):
        trigger_quality += 30
    if momentum.get("power_flip"):
        trigger_quality += 20
    if momentum.get("williams_r_power_cross"):
        trigger_quality += 15
    if (trigger.get("ignition") or {}).get("triggered"):
        trigger_quality += 30
    if _as_bool(latest.get("williams_r_cross_bull")):
        trigger_quality += 15
    if setup_facts.get("prior_breakout"):
        trigger_quality += 15

    risk_break_score = _as_int(risk_facts.get("risk_break_score"))
    risk_heat_score = _as_int(risk_facts.get("risk_heat_score"))
    execution_risk = _as_int(risk_facts.get("risk_score")) * 18 + risk_break_score * 8 + risk_heat_score * 6
    return {
        "research_score": min(100, int(research_score)),
        "structure_score": min(100, int(structure_score)),
        "trigger_quality": min(100, int(trigger_quality)),
        "execution_risk": min(100, int(execution_risk)),
    }


def build_repair_facts(df_display, *, fractals=None, momentum=None, divergence=None, setup_facts=None):
    """Describe bottom-divergence repair facts without granting entry permission."""
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "available": False,
            "stage": "none",
            "summary": "缺少行情数据，无法判断修复观察。",
            "evidence": [],
            "required_confirmations": ["补齐行情数据"],
        }

    window = df_display.tail(8) if df_display is not None and not df_display.empty else df_display
    divergence = divergence if isinstance(divergence, dict) else {}
    setup_facts = setup_facts if isinstance(setup_facts, dict) else {}
    current_bottom = bool(divergence.get("bottom_divergence") or divergence.get("current"))
    recent_bottom = bool(divergence.get("recent"))
    repair_impulse = bool(setup_facts.get("repair_impulse"))
    repair_confirm = bool(setup_facts.get("repair_confirm"))
    macd_hist = _series(df_display, "macd_hist", None).tail(4) if df_display is not None else pd.Series(dtype=float)
    macd_repair = False
    if len(macd_hist.dropna()) >= 2:
        latest_hist = _as_float(macd_hist.iloc[-1])
        previous_hist = _as_float(macd_hist.iloc[-2])
        macd_repair = bool(latest_hist is not None and previous_hist is not None and latest_hist > previous_hist)
    momentum = momentum if isinstance(momentum, dict) else {}
    momentum_repair = bool(
        momentum.get("power_flip")
        or momentum.get("williams_r_power_cross")
        or _as_bool(latest.get("williams_r_cross_bull"))
    )
    fractals = fractals if isinstance(fractals, dict) else {}
    structural_repair = bool(fractals.get("double_bottom_higher_low"))
    evidence = []
    if current_bottom:
        evidence.append("当前底背离")
    elif recent_bottom:
        evidence.append("近期底背离")
    if repair_impulse:
        evidence.append("修复异动")
    if repair_confirm:
        evidence.append("修复确认")
    if macd_repair:
        evidence.append("MACD柱改善")
    if momentum_repair:
        evidence.append("动能修复")
    if structural_repair:
        evidence.append("低点抬高")

    invalidation_price = None
    if window is not None and not window.empty and "low" in window.columns:
        invalidation_price = _round(window["low"].min())
    latest_bottom = fractals.get("latest_bottom") if isinstance(fractals.get("latest_bottom"), dict) else {}
    if latest_bottom.get("price") is not None:
        invalidation_price = latest_bottom.get("price")

    if recent_bottom and (repair_confirm or repair_impulse or macd_repair or momentum_repair or structural_repair):
        stage = "repair_setup"
        summary = "底背离后出现修复事实，只能进入修复观察。"
        required = ["C回/C突/C爆 触发", "Plan Gate 校验"]
    elif recent_bottom:
        stage = "bottom_research"
        summary = "底背离出现，但右侧修复证据不足。"
        required = ["修复异动", "结构确认", "V2 触发事实"]
    else:
        stage = "none"
        summary = "暂无底背离修复事实。"
        required = ["底背离或极端观察事实"]

    return {
        "available": stage != "none",
        "stage": stage,
        "current_bottom_divergence": current_bottom,
        "recent_bottom_divergence": recent_bottom,
        "repair_impulse": repair_impulse,
        "repair_confirm": repair_confirm,
        "macd_repair": macd_repair,
        "momentum_repair": momentum_repair,
        "structural_repair": structural_repair,
        "invalidation_price": invalidation_price,
        "evidence": evidence,
        "required_confirmations": required,
        "summary": summary,
    }


def _latest_true_in_window(df_display, columns, lookback=5):
    if df_display is None or df_display.empty:
        return None
    existing = [column for column in columns if column in df_display.columns]
    if not existing:
        return None
    window = df_display.tail(lookback)
    for idx in reversed(window.index):
        row = df_display.loc[idx]
        if any(_as_bool(row.get(column)) for column in existing):
            return row
    return None


def _legacy_signal_date(row):
    return _format_date(row.get("date")) if row is not None else "-"


def build_legacy_experience_facts(df_display):
    """Expose old C/B observations as reference evidence only.

    P21 deliberately keeps these facts out of permission and plan gates. The
    field answers "did an old idea notice something worth studying?" rather
    than "may we trade?".
    """
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "source": "legacy_experience_p21",
            "available": False,
            "grants_permission": False,
            "summary": "缺少行情数据，无法读取旧 C 经验素材。",
            "items": [],
        }

    pullback_row = _latest_true_in_window(
        df_display,
        ["new_is_pullback_b", "opt_is_pullback_b", "is_pullback_b"],
        lookback=5,
    )
    bottom_repair_row = _latest_true_in_window(
        df_display,
        ["new_is_b_point", "opt_is_b_point", "is_b_point", "is_bottom_divergence"],
        lookback=8,
    )
    risk_row = _latest_true_in_window(
        df_display,
        ["opt_is_s_warn", "opt_is_s_confirm", "opt_is_s_point", "new_is_s_point", "is_top_divergence", "is_s_point"],
        lookback=5,
    )

    items = []
    if pullback_row is not None:
        items.append({
            "key": "legacy_low_risk_pullback",
            "label": "旧C低风险回踩",
            "layer": "setup_evidence",
            "date": _legacy_signal_date(pullback_row),
            "evidence": [
                "旧 B/优化 B 回踩列命中",
                "只能作为 C回 或 待触 的辅助素材",
            ],
            "recommended_v2_use": "验证缩量、MA20/成本线附近和趋势未坏是否能提升 V2 回踩质量。",
            "grants_permission": False,
        })
    if bottom_repair_row is not None:
        items.append({
            "key": "legacy_bottom_repair_hint",
            "label": "旧C底部修复",
            "layer": "repair_evidence",
            "date": _legacy_signal_date(bottom_repair_row),
            "evidence": [
                "旧底背离/B点痕迹命中",
                "只能进入 C研/C修/C候 的解释素材",
            ],
            "recommended_v2_use": "验证 MACD 柱改善、低点抬高和动能修复是否能减少待触漏判。",
            "grants_permission": False,
        })
    if risk_row is not None:
        items.append({
            "key": "legacy_risk_hint",
            "label": "旧C风险提示",
            "layer": "risk_evidence",
            "date": _legacy_signal_date(risk_row),
            "evidence": [
                "旧 S/风险列命中",
                "只能作为 Exit Gate 分级素材",
            ],
            "recommended_v2_use": "验证旧风险提示是否能提前生成撤/减，而不是直接恢复 S 点。",
            "grants_permission": False,
        })

    return {
        "source": "legacy_experience_p21",
        "available": bool(items),
        "grants_permission": False,
        "priority": [item["key"] for item in items],
        "items": items,
        "summary": (
            "旧 C 经验素材已命中，仅作 V2 消融与解释参考。"
            if items else "未命中可吸收的旧 C 经验素材。"
        ),
    }


def build_c_signal_v2_facts(df_display, *, clock=None):
    """Build the Phase 2.3 fact payload for the latest bar."""
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "version": 1,
            "source": "c_signal_v2_p19_repair_watch_facts",
            "latest_date": "-",
            "scores": {"setup": 0, "confirm": 0, "risk": 0},
            "trend": {},
            "momentum": {},
            "macro_tide": {"available": False, "permission": "unknown", "label": "大周期未知"},
            "target_structure": {
                "available": False,
                "resistance_zones": [],
                "target_selection_reason": "缺少行情数据。",
                "summary": "缺少行情数据，无法估算结构目标。",
            },
            "setup": {},
            "repair": {
                "available": False,
                "stage": "none",
                "summary": "缺少行情数据，无法判断修复观察。",
                "evidence": [],
                "required_confirmations": ["补齐行情数据"],
            },
            "legacy_experience": build_legacy_experience_facts(df_display),
            "risk": {},
            "structure": {
                "candidate": False,
                "normalized_bars": {
                    "available": False,
                    "lookback": 80,
                    "original_count": 0,
                    "normalized_count": 0,
                    "containment_count": 0,
                    "merge_count": 0,
                    "dropped_count": 0,
                    "bars": [],
                    "recent_bars": [],
                    "summary": "缺少行情数据，无法处理 K 线包含关系。",
                },
                "rectangle_candidates": {
                    "available": False,
                    "short_rectangle": None,
                    "swing_rectangle": None,
                    "macro_rectangle": None,
                    "active_rectangle": {"available": False, "summary": "缺少行情数据，无法生成多周期矩形。"},
                    "all_candidates": [],
                    "summary": "缺少行情数据，无法生成多周期矩形。",
                },
                "active_rectangle": {"available": False, "summary": "缺少行情数据，无法生成多周期矩形。"},
                "macro_rectangle": None,
                "bear_trap_recovery": {
                    "available": False,
                    "recovered": False,
                    "breakout_after_recovery": False,
                    "summary": "缺少结构或行情数据，无法识别破底翻。",
                },
            },
            "exit_gate": build_exit_gate_facts(df_display),
            "trigger": {"available": False},
            "clock": clock or {},
            "v2_scores": {"research_score": 0, "structure_score": 0, "trigger_quality": 0, "execution_risk": 0},
        }

    structure_normalization = _normalize_kline_inclusion_frame(df_display, lookback=80)
    normalized_bars = build_normalized_bar_facts(df_display, normalization=structure_normalization)
    fractals = build_williams_fractal_facts(df_display, normalization_param=structure_normalization)
    rectangle_candidates = build_rectangle_candidate_facts(df_display)
    active_rectangle = rectangle_candidates.get("active_rectangle") if isinstance(rectangle_candidates, dict) else None
    rectangle = active_rectangle if isinstance(active_rectangle, dict) else build_rectangle_facts(df_display)
    macro_rectangle = rectangle_candidates.get("macro_rectangle") if isinstance(rectangle_candidates, dict) else None
    bear_trap_recovery = build_bear_trap_recovery_facts(
        df_display,
        rectangle=rectangle,
        macro_rectangle=macro_rectangle,
    )
    trigger = build_trigger_facts(df_display)
    momentum = build_momentum_facts(df_display)
    divergence = build_v2_divergence_facts(df_display)
    setup_facts = build_v2_setup_facts(
        df_display,
        rectangle=rectangle,
        trigger=trigger,
        momentum=momentum,
        divergence=divergence,
        normalized_bars=normalized_bars,
    )
    macro_tide = build_macro_tide_facts(df_display)
    target_structure = build_target_structure_facts(
        df_display,
        rectangle=rectangle,
        macro_rectangle=macro_rectangle,
    )
    exit_gate = build_exit_gate_facts(
        df_display,
        fractals=fractals,
        target_structure=target_structure,
    )
    risk_facts = build_v2_risk_facts(df_display, rectangle=rectangle, exit_gate=exit_gate)
    repair = build_repair_facts(
        df_display,
        fractals=fractals,
        momentum=momentum,
        divergence=divergence,
        setup_facts=setup_facts,
    )
    legacy_experience = build_legacy_experience_facts(df_display)
    trend_flags = _v2_trend_flags(df_display)
    structure_candidate = bool(
        fractals.get("double_bottom_higher_low")
        or rectangle.get("available")
        or bear_trap_recovery.get("recovered")
        or setup_facts.get("pullback_setup")
        or setup_facts.get("breakout_setup")
    )
    trigger_observed = bool(
        trigger.get("attack_day")
        or (trigger.get("ignition") or {}).get("triggered")
        or bear_trap_recovery.get("breakout_after_recovery")
    )
    scores = {
        "setup": 1 if (structure_candidate or setup_facts.get("breakout_setup") or setup_facts.get("pullback_setup")) else 0,
        "confirm": 1 if trigger_observed else 0,
        "risk": _as_int(risk_facts.get("risk_score")),
    }

    return {
        "version": 1,
        "source": "c_signal_v2_p19_repair_watch_facts",
        "latest_date": _format_date(latest.get("date")),
        "scores": scores,
        "trend": {
            "above_ma20": trend_flags.get("above_ma20"),
            "ma20_up": trend_flags.get("ma20_up"),
            "trend_ok": trend_flags.get("trend_ok"),
            "ma60": (macro_tide.get("ma60") or {}).get("value"),
            "above_ma60": (macro_tide.get("ma60") or {}).get("above"),
            "ma60_slope_pct": (macro_tide.get("ma60") or {}).get("slope_pct"),
            "ma60_up": (macro_tide.get("ma60") or {}).get("up"),
            "ma250": (macro_tide.get("ma250") or {}).get("value"),
            "above_ma250": (macro_tide.get("ma250") or {}).get("above"),
            "ma250_slope_pct": (macro_tide.get("ma250") or {}).get("slope_pct"),
            "macro_tide_permission": macro_tide.get("permission"),
            "weekly_macd_permission": (macro_tide.get("weekly_macd") or {}).get("permission"),
            "balance": momentum.get("balance"),
            "balance_ma3": momentum.get("balance_ma3"),
            "power_flip": momentum.get("power_flip"),
            "williams_r": _as_float(latest.get("williams_r")),
            "williams_r_center_side": latest.get("williams_r_center_side"),
            "williams_r_cross_bull": _as_bool(latest.get("williams_r_cross_bull")),
            "williams_r_cross_bear": _as_bool(latest.get("williams_r_cross_bear")),
            "williams_r_power_cross": momentum.get("williams_r_power_cross"),
            "bull_power_dominant": _as_bool(latest.get("bull_power_dominant")),
            "bear_power_dominant": _as_bool(latest.get("bear_power_dominant")),
        },
        "momentum": momentum,
        "macro_tide": macro_tide,
        "target_structure": target_structure,
        "exit_gate": exit_gate,
        "setup": {
            "repair_impulse": setup_facts.get("repair_impulse"),
            "repair_confirm": setup_facts.get("repair_confirm"),
            "pullback_setup": setup_facts.get("pullback_setup"),
            "breakout_setup": setup_facts.get("breakout_setup"),
            "breakout_trigger": setup_facts.get("breakout_trigger"),
            "pullback_trigger": setup_facts.get("pullback_trigger"),
            "prior_breakout": setup_facts.get("prior_breakout"),
            "bottom_divergence": setup_facts.get("bottom_divergence"),
            "recent_divergence": setup_facts.get("recent_divergence"),
            "summary": setup_facts.get("summary"),
        },
        "divergence": divergence,
        "repair": repair,
        "legacy_experience": legacy_experience,
        "risk": {
            "risk_score": risk_facts.get("risk_score"),
            "risk_break_score": risk_facts.get("risk_break_score"),
            "risk_heat_score": risk_facts.get("risk_heat_score"),
            "has_risk": risk_facts.get("has_risk"),
            "has_exit": risk_facts.get("has_exit"),
            "break_reasons": risk_facts.get("break_reasons"),
            "heat_reasons": risk_facts.get("heat_reasons"),
            "summary": risk_facts.get("summary"),
        },
        "clock": {
            "state": (clock or {}).get("state"),
            "state_label": (clock or {}).get("state_label"),
            "action_label": (clock or {}).get("action_label"),
        },
        "structure": {
            "candidate": structure_candidate,
            "trigger_observed": trigger_observed,
            "normalized_bars": normalized_bars,
            "rectangle_candidates": rectangle_candidates,
            "active_rectangle": active_rectangle,
            "macro_rectangle": macro_rectangle,
            "bear_trap_recovery": bear_trap_recovery,
            "fractals": fractals,
            "rectangle": rectangle,
            "summary": "结构事实已出现，等待许可和交易计划。" if structure_candidate else "结构事实不足，继续观察。",
        },
        "trigger": trigger,
        "v2_scores": _v2_scores(latest, fractals, rectangle, trigger, clock, momentum, divergence, setup_facts, risk_facts),
    }


def build_c_signal_v2_event_facts(df_display):
    """Build the subset of V2 facts consumed by chart event projection.

    This keeps the event timeline behavior equivalent to the full fact payload
    while avoiding macro tide, legacy-experience, trend-summary, and full score
    assembly that event projection does not read.
    """
    latest = _latest_row(df_display)
    if latest is None:
        return {
            "version": 1,
            "source": "c_signal_v2_event_facts",
            "latest_date": "-",
            "setup": {},
            "repair": {
                "available": False,
                "stage": "none",
                "summary": "缺少行情数据，无法判断修复观察。",
                "evidence": [],
                "required_confirmations": ["补齐行情数据"],
            },
            "risk": {},
            "structure": {
                "candidate": False,
                "fractals": {},
                "rectangle": {},
            },
            "exit_gate": build_exit_gate_facts(df_display),
            "trigger": {"available": False},
        }

    structure_normalization = _normalize_kline_inclusion_frame(df_display, lookback=80)
    normalized_bars = build_normalized_bar_facts(df_display, normalization=structure_normalization)
    fractals = build_williams_fractal_facts(df_display, normalization_param=structure_normalization)
    rectangle_candidates = build_rectangle_candidate_facts(df_display)
    active_rectangle = rectangle_candidates.get("active_rectangle") if isinstance(rectangle_candidates, dict) else None
    rectangle = active_rectangle if isinstance(active_rectangle, dict) else build_rectangle_facts(df_display)
    macro_rectangle = rectangle_candidates.get("macro_rectangle") if isinstance(rectangle_candidates, dict) else None
    bear_trap_recovery = build_bear_trap_recovery_facts(
        df_display,
        rectangle=rectangle,
        macro_rectangle=macro_rectangle,
    )
    trigger = build_trigger_facts(df_display)
    momentum = build_momentum_facts(df_display)
    divergence = build_v2_divergence_facts(df_display)
    setup_facts = build_v2_setup_facts(
        df_display,
        rectangle=rectangle,
        trigger=trigger,
        momentum=momentum,
        divergence=divergence,
        normalized_bars=normalized_bars,
    )
    target_structure = build_target_structure_facts(
        df_display,
        rectangle=rectangle,
        macro_rectangle=macro_rectangle,
    )
    exit_gate = build_exit_gate_facts(
        df_display,
        fractals=fractals,
        target_structure=target_structure,
    )
    risk_facts = build_v2_risk_facts(df_display, rectangle=rectangle, exit_gate=exit_gate)
    repair = build_repair_facts(
        df_display,
        fractals=fractals,
        momentum=momentum,
        divergence=divergence,
        setup_facts=setup_facts,
    )
    structure_candidate = bool(
        fractals.get("double_bottom_higher_low")
        or rectangle.get("available")
        or bear_trap_recovery.get("recovered")
        or setup_facts.get("pullback_setup")
        or setup_facts.get("breakout_setup")
    )
    trigger_observed = bool(
        trigger.get("attack_day")
        or (trigger.get("ignition") or {}).get("triggered")
        or bear_trap_recovery.get("breakout_after_recovery")
    )

    return {
        "version": 1,
        "source": "c_signal_v2_event_facts",
        "latest_date": _format_date(latest.get("date")),
        "setup": {
            "repair_impulse": setup_facts.get("repair_impulse"),
            "repair_confirm": setup_facts.get("repair_confirm"),
            "pullback_setup": setup_facts.get("pullback_setup"),
            "breakout_setup": setup_facts.get("breakout_setup"),
            "breakout_trigger": setup_facts.get("breakout_trigger"),
            "pullback_trigger": setup_facts.get("pullback_trigger"),
            "prior_breakout": setup_facts.get("prior_breakout"),
            "bottom_divergence": setup_facts.get("bottom_divergence"),
            "recent_divergence": setup_facts.get("recent_divergence"),
            "summary": setup_facts.get("summary"),
        },
        "repair": repair,
        "risk": {
            "risk_score": risk_facts.get("risk_score"),
            "risk_break_score": risk_facts.get("risk_break_score"),
            "risk_heat_score": risk_facts.get("risk_heat_score"),
            "has_risk": risk_facts.get("has_risk"),
            "has_exit": risk_facts.get("has_exit"),
            "break_reasons": risk_facts.get("break_reasons"),
            "heat_reasons": risk_facts.get("heat_reasons"),
            "summary": risk_facts.get("summary"),
        },
        "structure": {
            "candidate": structure_candidate,
            "trigger_observed": trigger_observed,
            "fractals": fractals,
            "rectangle": rectangle,
            "summary": "结构事实已出现，等待许可和交易计划。" if structure_candidate else "结构事实不足，继续观察。",
        },
        "exit_gate": exit_gate,
        "trigger": trigger,
    }
