"""Stable on-demand detail projection for one indexed scan candidate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Mapping


CANDIDATE_DETAIL_SCHEMA_VERSION = 2


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _pick(source: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        key: deepcopy(source[key])
        for key in keys
        if key in source
    }


@dataclass(frozen=True)
class CandidateDetail:
    schema_version: int
    summary: dict[str, Any]
    decision_state: dict[str, Any]
    score_context: dict[str, Any]
    decision_explanation: dict[str, Any]
    rule_results: dict[str, Any]
    structure_facts: dict[str, Any]
    permission: dict[str, Any]
    conditional_plan: dict[str, Any]
    risk_conditions: dict[str, Any]
    environment_context: dict[str, Any]
    profile: dict[str, Any]
    related_snapshot: dict[str, Any]

    @classmethod
    def from_snapshot(
        cls,
        summary: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        pool: str,
    ) -> "CandidateDetail | None":
        result = _mapping(_mapping(snapshot.get("results")).get(pool))
        if not result:
            return None
        state = _mapping(result.get("v2_state_model") or result.get("c_signal_v2_state"))
        facts = _mapping(state.get("facts"))
        structure = _mapping(facts.get("structure"))
        explanation = _mapping(result.get("explanation"))
        view_model = _mapping(result.get("view_model"))
        permission = _mapping(state.get("v2_permission_model"))
        trade_plan = _mapping(result.get("trade_plan") or snapshot.get("trade_plan"))

        decision_explanation = _pick(
            explanation,
            ("version", "headline", "summary", "card_summary", "drivers", "cautions", "score_badges"),
        )
        if not decision_explanation:
            decision_explanation = _pick(
                view_model,
                ("headline", "summary", "card_summary", "decision_label", "signal_text"),
            )

        structure_facts = {
            "setup": deepcopy(_mapping(facts.get("setup"))),
            "structure": _pick(
                structure,
                (
                    "summary",
                    "candidate",
                    "trigger_observed",
                    "active_rectangle",
                    "rectangle",
                    "macro_rectangle",
                    "bear_trap_recovery",
                ),
            ),
            "trigger": deepcopy(_mapping(facts.get("trigger"))),
            "repair": deepcopy(_mapping(facts.get("repair"))),
            "divergence": deepcopy(_mapping(facts.get("divergence"))),
            "target_structure": deepcopy(_mapping(facts.get("target_structure"))),
        }

        environment_keys = (
            "v2_market_permission",
            "v2_environment_permission",
            "v2_environment_label",
            "v2_environment_tone",
            "v2_environment_effect",
            "v2_environment_reasons",
            "v2_environment_warnings",
            "v2_environment_block_reasons",
            "v2_sector_permission",
            "v2_sector_permission_label",
            "v2_sector_permission_reason",
            "v2_concept_permission",
            "v2_concept_permission_label",
            "v2_concept_permission_reason",
            "v2_macro_veto_permission",
            "v2_macro_veto_label",
            "v2_macro_veto_tone",
            "v2_macro_veto_reason",
            "v2_macro_veto_warnings",
            "v2_macro_veto_block_reasons",
        )

        return cls(
            schema_version=CANDIDATE_DETAIL_SCHEMA_VERSION,
            summary=deepcopy(dict(summary)),
            decision_state=_pick(
                state,
                (
                    "v2_state_schema_version",
                    "version",
                    "signal",
                    "signal_name",
                    "state",
                    "state_label",
                    "permission",
                    "permission_label",
                    "role",
                    "role_label",
                    "tone",
                    "reason",
                    "detail",
                    "next_action",
                    "trade_intent",
                    "trade_intent_label",
                    "plan_scope",
                    "requires_trade_plan",
                    "requires_stop_loss",
                    "candidate_display_label",
                    "candidate_substate",
                    "candidate_substate_label",
                    "candidate_trigger_plan",
                    "candidate_confirmation_price",
                    "candidate_invalidation_price",
                    "candidate_missing_confirmations",
                ),
            ),
            score_context=_pick(
                result,
                (
                    "setup_score",
                    "confirm_score",
                    "risk_score",
                    "rank_score",
                    "final_score",
                    "v2_priority_score",
                    "score_confidence",
                    "score_confidence_label",
                    "score_confidence_level",
                    "win_rate",
                    "avg_ret",
                ),
            ),
            decision_explanation=decision_explanation,
            rule_results={
                "event_mapping": deepcopy(_mapping(state.get("event_mapping"))),
                "scores": deepcopy(_mapping(state.get("scores") or facts.get("scores"))),
                "next_action": state.get("next_action") or result.get("trade_intent_label") or "",
            },
            structure_facts=structure_facts,
            permission=deepcopy(dict(permission)),
            conditional_plan=deepcopy(dict(trade_plan)),
            risk_conditions={
                "risk": deepcopy(_mapping(facts.get("risk"))),
                "exit_gate": deepcopy(_mapping(facts.get("exit_gate"))),
            },
            environment_context={
                "macro_tide": deepcopy(_mapping(facts.get("macro_tide"))),
                **_pick(result, environment_keys),
            },
            profile={
                "code": summary.get("code") or snapshot.get("code") or "",
                "name": summary.get("name") or snapshot.get("name") or "",
                "sector": summary.get("sector") or snapshot.get("sector") or "",
                "concepts": deepcopy(summary.get("concepts") or snapshot.get("concepts") or []),
                "quality_label": summary.get("profile_quality_label") or "",
                "quality_score": summary.get("profile_quality_score"),
            },
            related_snapshot={
                "snapshot_day": snapshot.get("snapshot_day") or "",
                "snapshot_version": snapshot.get("version") or 0,
                "snapshot_revision": summary.get("snapshot_revision") or "",
                "strategy_version": snapshot.get("strategy_version") or "",
                "data_adjust": snapshot.get("data_adjust") or "",
                "data_date": snapshot.get("data_date") or "",
                "row_count": snapshot.get("rows") or 0,
                "computed_scan_types": deepcopy(snapshot.get("computed_scan_types") or []),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
