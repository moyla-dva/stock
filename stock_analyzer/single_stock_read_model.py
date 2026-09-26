"""Stable read model for one on-demand stock analysis."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from stock_analyzer.versioning import DATA_START_DATE, SCAN_STRATEGY_VERSION


SINGLE_STOCK_ANALYSIS_SCHEMA_VERSION = 2
UNKNOWN_VALUE = "unknown"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _data_revision(payload: Mapping[str, Any]) -> str:
    core = {
        "code": payload.get("stock_code") or "",
        "dates": payload.get("dates") or [],
        "candles": payload.get("k_data") or [],
    }
    raw = json.dumps(
        core,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _trim_current_state(value: Any) -> dict[str, Any]:
    state = deepcopy(dict(_mapping(value)))
    facts = state.get("facts")
    if not isinstance(facts, dict):
        return state
    structure = facts.get("structure")
    if isinstance(structure, dict):
        structure.pop("normalized_bars", None)
        structure.pop("rectangle_candidates", None)
    return state


def _latest_bar(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    dates = list(payload.get("dates") or [])
    candles = list(payload.get("k_data") or [])
    if not dates or not candles or not isinstance(candles[-1], (list, tuple)):
        return None
    values = list(candles[-1])
    if len(values) < 4:
        return None
    return {
        "at": dates[-1],
        "open": values[0],
        "close": values[1],
        "low": values[2],
        "high": values[3],
    }


@dataclass(frozen=True)
class SingleStockAnalysis:
    schema_version: int
    identity: dict[str, Any]
    profile: dict[str, Any]
    market_data: dict[str, Any]
    chart: dict[str, Any]
    signal_observations: dict[str, Any]
    current_state: dict[str, Any]
    conditional_plan: dict[str, Any]
    timeframes: dict[str, Any]
    event_study: dict[str, Any]
    data_quality: dict[str, Any]

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        refresh_requested: bool = False,
    ) -> "SingleStockAnalysis":
        if not isinstance(payload, Mapping):
            raise ValueError("single-stock payload must be an object")
        dates = deepcopy(list(payload.get("dates") or []))
        candles = deepcopy(list(payload.get("k_data") or []))
        code = str(payload.get("stock_code") or "")
        tag_profile = deepcopy(dict(_mapping(payload.get("tag_profile"))))
        state = _trim_current_state(payload.get("c_signal_v2_state"))
        event_stats = deepcopy(dict(_mapping(payload.get("event_stats"))))
        data_identity = deepcopy(dict(_mapping(payload.get("data_identity"))))
        bar_state = str(data_identity.get("bar_state") or UNKNOWN_VALUE)
        data_source = str(data_identity.get("data_source") or UNKNOWN_VALUE)
        data_revision = str(data_identity.get("data_revision") or _data_revision(payload))
        generated_at = str(data_identity.get("generated_at") or UNKNOWN_VALUE)
        calendar_id = str(data_identity.get("calendar_id") or UNKNOWN_VALUE)
        calendar_revision = str(data_identity.get("calendar_revision") or UNKNOWN_VALUE)
        calendar_evidence_level = str(
            data_identity.get("calendar_evidence_level") or UNKNOWN_VALUE
        )

        signal_observations = {
            "events": deepcopy(list(payload.get("mark_points_v2") or [])),
            "event_lookback": payload.get("v2_event_lookback"),
            "score_summary": deepcopy(dict(_mapping(payload.get("score_summary")))),
            "definitions": deepcopy(dict(_mapping(payload.get("signal_definitions")))),
        }
        for key in ("mark_points_old", "mark_points_new", "mark_points_opt"):
            if key in payload:
                signal_observations[key] = deepcopy(list(payload.get(key) or []))

        return cls(
            schema_version=SINGLE_STOCK_ANALYSIS_SCHEMA_VERSION,
            identity={
                "schema_version": SINGLE_STOCK_ANALYSIS_SCHEMA_VERSION,
                "strategy_version": SCAN_STRATEGY_VERSION,
                "code": code,
                "as_of": dates[-1] if dates else UNKNOWN_VALUE,
                "bar_state": bar_state,
                "data_source": data_source,
                "data_revision": data_revision,
                "start_key": str(DATA_START_DATE).replace("-", ""),
                "generated_at": generated_at,
                "calendar_id": calendar_id,
                "calendar_revision": calendar_revision,
                "calendar_evidence_level": calendar_evidence_level,
            },
            profile={
                "code": code,
                "display_name": payload.get("stock_name") or code,
                "sector": payload.get("stock_sector") or "",
                "concepts": deepcopy(list(payload.get("stock_concepts") or [])),
                "tag_profile": tag_profile,
            },
            market_data={
                "latest_at": dates[-1] if dates else None,
                "row_count": min(len(dates), len(candles)),
                "latest_bar": _latest_bar(payload),
            },
            chart={
                "dates": dates,
                "candles": candles,
                "candle_fields": ["open", "close", "low", "high"],
                "series": {
                    "ma20": deepcopy(list(payload.get("ma20_data") or [])),
                    "vwap": deepcopy(list(payload.get("vwap_data") or [])),
                    "bull_power": deepcopy(list(payload.get("bull_power_data") or [])),
                    "bear_power": deepcopy(list(payload.get("bear_power_data") or [])),
                    "williams_r": deepcopy(list(payload.get("williams_r_data") or [])),
                    "custom": deepcopy(list(payload.get("custom_data") or [])),
                    "dif": deepcopy(list(payload.get("dif_data") or [])),
                    "dea": deepcopy(list(payload.get("dea_data") or [])),
                    "macd": deepcopy(list(payload.get("macd_data") or [])),
                },
            },
            signal_observations=signal_observations,
            current_state=state,
            conditional_plan=deepcopy(dict(_mapping(payload.get("trade_plan")))),
            timeframes=deepcopy(dict(_mapping(payload.get("multi_timeframes")))),
            event_study={
                "scope": "single_stock_historical_events",
                "results": event_stats,
            },
            data_quality={
                "bar_state": bar_state,
                "data_source": data_source,
                "cache_status": data_identity.get("cache_status") or UNKNOWN_VALUE,
                "cache_written_at": data_identity.get("cache_written_at") or UNKNOWN_VALUE,
                "calendar_id": calendar_id,
                "calendar_revision": calendar_revision,
                "calendar_evidence_level": calendar_evidence_level,
                "refresh_requested": bool(refresh_requested),
                "history_row_count": min(len(dates), len(candles)),
                "issues": [
                    issue
                    for issue, unavailable in (
                        ("bar_state_not_exposed_by_upstream", bar_state == UNKNOWN_VALUE),
                        ("data_source_not_exposed_by_upstream", data_source == UNKNOWN_VALUE),
                        (
                            "calendar_revision_not_exposed_by_upstream",
                            calendar_revision == UNKNOWN_VALUE,
                        ),
                    )
                    if unavailable
                ],
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
