"""Stable candidate summary read model used by the persistent scan index."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from stock_analyzer.candidate_reasons import candidate_reason_tags
from stock_analyzer.versioning import SCAN_STRATEGY_VERSION


CANDIDATE_SUMMARY_SCHEMA_VERSION = 2
UNKNOWN_IDENTITY_VALUE = "unknown"
VALID_BAR_STATES = {"closed", "preview", "mixed", UNKNOWN_IDENTITY_VALUE}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "" or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _texts(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return ()
    output = []
    seen = set()
    for item in value:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return tuple(output)


def _present_value(
    primary: Mapping[str, Any],
    key: str,
    *fallbacks: tuple[Mapping[str, Any], str],
) -> Any:
    if key in primary:
        return primary.get(key)
    for source, fallback_key in fallbacks:
        if fallback_key in source:
            return source.get(fallback_key)
    return None


def _bar_state(value: Any) -> str:
    state = _text(value, default=UNKNOWN_IDENTITY_VALUE).lower()
    return state if state in VALID_BAR_STATES else UNKNOWN_IDENTITY_VALUE


@dataclass(frozen=True)
class CandidateSummary:
    """Small, query-oriented projection of one snapshot pool result."""

    schema_version: int
    strategy_version: str
    code: str
    as_of: str
    bar_state: str
    data_source: str
    data_revision: str
    generated_at: str
    calendar_id: str
    calendar_revision: str
    calendar_evidence_level: str
    snapshot_day: str
    start_key: str
    snapshot_version: int
    snapshot_revision: str
    strategy_status: str
    name: str
    pool: str
    event_date: str
    signal_key: str
    signal_label: str
    state: str
    permission: str
    plan_status: str
    priority_score: float | None
    priority_group: str
    reason_summary: str
    reason_tags: tuple[str, ...]
    missing_confirmations: tuple[str, ...]
    invalidation_price: float | None
    sector: str
    concepts: tuple[str, ...]
    price: float | None
    final_score: float | None
    confirm_score: float | None
    risk_score: float | None
    profile_quality_label: str
    profile_quality_score: float | None
    requires_trade_plan: bool
    requires_stop_loss: bool

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, Any],
        pool: str,
        *,
        snapshot_revision: str = "",
        start_key: str = "default",
    ) -> "CandidateSummary | None":
        results = _mapping(snapshot.get("results"))
        result = _mapping(results.get(pool))
        if not result:
            return None

        state_model = _mapping(result.get("v2_state_model") or result.get("c_signal_v2_state"))
        permission_model = _mapping(state_model.get("v2_permission_model"))
        plan_gate = _mapping(permission_model.get("plan_gate"))
        snapshot_strategy_version = _text(
            snapshot.get("strategy_version"),
            default=UNKNOWN_IDENTITY_VALUE,
        )
        bar_state = _bar_state(snapshot.get("bar_state"))

        missing_confirmations = _texts(_present_value(
            result,
            "candidate_missing_confirmations",
            (state_model, "candidate_missing_confirmations"),
            (permission_model, "required_confirmations"),
        ))
        concepts = _texts(result.get("concepts") or snapshot.get("concepts"))

        return cls(
            schema_version=CANDIDATE_SUMMARY_SCHEMA_VERSION,
            strategy_version=snapshot_strategy_version,
            code=_text(result.get("code"), snapshot.get("code")),
            as_of=_text(snapshot.get("data_date"), result.get("date"), default=UNKNOWN_IDENTITY_VALUE),
            bar_state=bar_state,
            data_source=_text(snapshot.get("data_source"), default=UNKNOWN_IDENTITY_VALUE),
            data_revision=_text(snapshot.get("data_revision"), default=UNKNOWN_IDENTITY_VALUE),
            generated_at=_text(snapshot.get("generated_at"), default=UNKNOWN_IDENTITY_VALUE),
            calendar_id=_text(snapshot.get("calendar_id"), default=UNKNOWN_IDENTITY_VALUE),
            calendar_revision=_text(
                snapshot.get("calendar_revision"),
                default=UNKNOWN_IDENTITY_VALUE,
            ),
            calendar_evidence_level=_text(
                snapshot.get("calendar_evidence_level"),
                default=UNKNOWN_IDENTITY_VALUE,
            ),
            snapshot_day=_text(snapshot.get("snapshot_day")),
            start_key=_text(start_key, default="default"),
            snapshot_version=int(snapshot.get("version") or 0),
            snapshot_revision=_text(snapshot_revision, default=UNKNOWN_IDENTITY_VALUE),
            strategy_status="current" if snapshot_strategy_version == SCAN_STRATEGY_VERSION else "legacy",
            name=_text(result.get("name"), snapshot.get("name"), result.get("code"), snapshot.get("code")),
            pool=_text(pool),
            event_date=_text(result.get("event_date"), result.get("date"), snapshot.get("data_date")),
            signal_key=_text(result.get("signal_key")),
            signal_label=_text(
                result.get("v2_signal"),
                result.get("signal_label"),
                result.get("signal"),
            ),
            state=_text(result.get("v2_state"), state_model.get("state")),
            permission=_text(result.get("v2_permission"), state_model.get("permission")),
            plan_status=_text(
                result.get("v2_plan_status"),
                state_model.get("plan_status"),
                permission_model.get("plan_status"),
                plan_gate.get("status"),
            ),
            priority_score=_number(result.get("v2_priority_score"), result.get("rank_score")),
            priority_group=_text(result.get("v2_priority_group")),
            reason_summary=_text(result.get("reason"), state_model.get("reason")),
            reason_tags=candidate_reason_tags(result),
            missing_confirmations=missing_confirmations,
            invalidation_price=_number(
                result.get("candidate_invalidation_price"),
                state_model.get("candidate_invalidation_price"),
            ),
            sector=_text(result.get("sector"), snapshot.get("sector")),
            concepts=concepts,
            price=_number(result.get("price")),
            final_score=_number(result.get("final_score"), result.get("rank_score")),
            confirm_score=_number(result.get("confirm_score")),
            risk_score=_number(result.get("risk_score")),
            profile_quality_label=_text(result.get("score_confidence_label")),
            profile_quality_score=_number(result.get("score_confidence")),
            requires_trade_plan=bool(_present_value(
                result,
                "requires_trade_plan",
                (state_model, "requires_trade_plan"),
            )),
            requires_stop_loss=bool(_present_value(
                result,
                "requires_stop_loss",
                (state_model, "requires_stop_loss"),
            )),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_tags"] = list(self.reason_tags)
        payload["missing_confirmations"] = list(self.missing_confirmations)
        payload["concepts"] = list(self.concepts)
        return payload
