"""Traceable identity metadata carried alongside market-data DataFrames."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping

import pandas as pd


MARKET_DATA_IDENTITY_ATTR = "market_data_identity"
VALID_BAR_STATES = {"closed", "preview", "mixed", "unknown"}


def market_data_revision(frame) -> str:
    if frame is None or frame.empty:
        return "unknown"
    columns = [
        column
        for column in ("date", "open", "high", "low", "close", "volume")
        if column in frame.columns
    ]
    if not columns:
        return "unknown"
    canonical = frame[columns].copy()
    if "date" in canonical.columns:
        dates = pd.to_datetime(canonical["date"], errors="coerce")
        canonical["date"] = dates.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    raw = canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def frame_market_data_identity(frame) -> dict[str, Any]:
    if frame is None:
        return {}
    attrs = getattr(frame, "attrs", {})
    identity = attrs.get(MARKET_DATA_IDENTITY_ATTR) if isinstance(attrs, Mapping) else None
    return deepcopy(dict(identity)) if isinstance(identity, Mapping) else {}


def attach_market_data_identity(
    frame,
    *,
    data_source: str | None = None,
    bar_state: str | None = None,
    generated_at: str | None = None,
    cache_status: str | None = None,
    cache_written_at: str | None = None,
    data_revision: str | None = None,
    calendar_id: str | None = None,
    calendar_revision: str | None = None,
    calendar_evidence_level: str | None = None,
):
    if frame is None:
        return frame
    identity = frame_market_data_identity(frame)
    if data_source:
        identity["data_source"] = str(data_source)
    if bar_state:
        normalized_state = str(bar_state).lower()
        identity["bar_state"] = (
            normalized_state if normalized_state in VALID_BAR_STATES else "unknown"
        )
    if generated_at:
        identity["generated_at"] = str(generated_at)
    if cache_status:
        identity["cache_status"] = str(cache_status)
    if cache_written_at:
        identity["cache_written_at"] = str(cache_written_at)
    if calendar_id:
        identity["calendar_id"] = str(calendar_id)
    if calendar_revision:
        identity["calendar_revision"] = str(calendar_revision)
    if calendar_evidence_level:
        identity["calendar_evidence_level"] = str(calendar_evidence_level)
    identity["data_revision"] = data_revision or identity.get("data_revision") or market_data_revision(frame)
    frame.attrs[MARKET_DATA_IDENTITY_ATTR] = identity
    return frame


def copy_market_data_identity(source, target):
    if target is None:
        return target
    identity = frame_market_data_identity(source)
    if identity:
        target.attrs[MARKET_DATA_IDENTITY_ATTR] = identity
    return target
