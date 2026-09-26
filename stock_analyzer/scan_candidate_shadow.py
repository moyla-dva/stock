"""Semantic shadow comparison for workspace and SQLite candidate reads."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


HARD_PARITY_FIELDS = (
    "event_date",
    "signal_key",
    "signal_label",
    "state",
    "permission",
    "plan_status",
    "missing_confirmations",
    "invalidation_price",
    "requires_trade_plan",
    "requires_stop_loss",
)

DESCRIPTIVE_FIELDS = (
    "name",
    "sector",
    "concepts",
    "price",
    "confirm_score",
    "risk_score",
    "reason_summary",
)

RANKING_FIELDS = (
    "priority_score",
    "priority_group",
    "final_score",
)


def _text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return None


def _texts(value: Any, *, unordered: bool = False) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return ()
    output = tuple(_text(item) for item in value if _text(item))
    return tuple(sorted(set(output))) if unordered else output


def normalize_shadow_candidate(
    candidate: Mapping[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Project old workspace and new index rows onto one comparison contract."""

    if source not in {"workspace", "index"}:
        raise ValueError(f"unknown candidate source: {source}")
    if source == "workspace":
        return {
            "code": _text(candidate.get("code")),
            "event_date": _text(candidate.get("event_date"), candidate.get("date")),
            "signal_key": _text(candidate.get("signal_key")),
            "signal_label": _text(
                candidate.get("v2_signal"),
                candidate.get("signal_label"),
                candidate.get("signal"),
            ),
            "state": _text(candidate.get("v2_state")),
            "permission": _text(candidate.get("v2_permission")),
            "plan_status": _text(candidate.get("v2_plan_status")),
            "missing_confirmations": _texts(
                candidate.get("candidate_missing_confirmations")
            ),
            "invalidation_price": _number(
                candidate.get("candidate_invalidation_price")
            ),
            "requires_trade_plan": bool(candidate.get("requires_trade_plan")),
            "requires_stop_loss": bool(candidate.get("requires_stop_loss")),
            "name": _text(candidate.get("name")),
            "sector": _text(candidate.get("sector")),
            "concepts": _texts(candidate.get("concepts"), unordered=True),
            "price": _number(candidate.get("price")),
            "confirm_score": _number(candidate.get("confirm_score")),
            "risk_score": _number(candidate.get("risk_score")),
            "reason_summary": _text(candidate.get("reason")),
            "priority_score": _number(candidate.get("v2_priority_score")),
            "priority_group": _text(candidate.get("v2_priority_group")),
            "final_score": _number(candidate.get("final_score")),
        }
    rank_context = candidate.get("rank_context")
    rank_context = rank_context if isinstance(rank_context, Mapping) else {}
    return {
        "code": _text(candidate.get("code")),
        "event_date": _text(candidate.get("event_date")),
        "signal_key": _text(candidate.get("signal_key")),
        "signal_label": _text(candidate.get("signal_label")),
        "state": _text(candidate.get("state")),
        "permission": _text(candidate.get("permission")),
        "plan_status": _text(candidate.get("plan_status")),
        "missing_confirmations": _texts(candidate.get("missing_confirmations")),
        "invalidation_price": _number(candidate.get("invalidation_price")),
        "requires_trade_plan": bool(candidate.get("requires_trade_plan")),
        "requires_stop_loss": bool(candidate.get("requires_stop_loss")),
        "name": _text(candidate.get("name")),
        "sector": _text(candidate.get("sector")),
        "concepts": _texts(candidate.get("concepts"), unordered=True),
        "price": _number(candidate.get("price")),
        "confirm_score": _number(candidate.get("confirm_score")),
        "risk_score": _number(candidate.get("risk_score")),
        "reason_summary": _text(candidate.get("reason_summary")),
        "priority_score": _number(
            rank_context.get("priority_score")
            if rank_context
            else candidate.get("priority_score")
        ),
        "priority_group": _text(
            rank_context.get("priority_group")
            if rank_context
            else candidate.get("priority_group")
        ),
        "final_score": _number(
            rank_context.get("final_score")
            if rank_context
            else candidate.get("final_score")
        ),
    }


def _index_by_code(
    candidates: Iterable[Mapping[str, Any]],
    *,
    source: str,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str]]:
    order = []
    indexed = {}
    duplicates = []
    for candidate in candidates:
        normalized = normalize_shadow_candidate(candidate, source=source)
        code = normalized["code"]
        if not code:
            continue
        order.append(code)
        if code in indexed:
            duplicates.append(code)
        indexed[code] = normalized
    return order, indexed, sorted(set(duplicates))


def _field_differences(
    workspace: Mapping[str, Mapping[str, Any]],
    index: Mapping[str, Mapping[str, Any]],
    fields: tuple[str, ...],
    *,
    max_examples: int,
) -> dict[str, Any]:
    counts = Counter()
    examples = []
    for code in sorted(set(workspace) & set(index)):
        differences = {}
        for field in fields:
            if workspace[code].get(field) == index[code].get(field):
                continue
            counts[field] += 1
            differences[field] = {
                "workspace": workspace[code].get(field),
                "index": index[code].get(field),
            }
        if differences and len(examples) < max_examples:
            examples.append({"code": code, "fields": differences})
    return {
        "mismatch_count": sum(1 for code in workspace if code in index and any(
            workspace[code].get(field) != index[code].get(field)
            for field in fields
        )),
        "mismatch_fields": dict(counts),
        "examples": examples,
    }


def compare_candidate_reads(
    workspace_candidates: Iterable[Mapping[str, Any]],
    index_candidates: Iterable[Mapping[str, Any]],
    *,
    max_examples: int = 20,
) -> dict[str, Any]:
    """Compare membership and semantics while keeping dynamic ranking separate."""

    workspace_list = list(workspace_candidates)
    index_list = list(index_candidates)
    workspace_order, workspace, workspace_duplicates = _index_by_code(
        workspace_list,
        source="workspace",
    )
    index_order, index, index_duplicates = _index_by_code(index_list, source="index")
    workspace_codes = set(workspace)
    index_codes = set(index)
    missing = sorted(workspace_codes - index_codes)
    extra = sorted(index_codes - workspace_codes)
    common = workspace_codes & index_codes

    workspace_positions = {code: position for position, code in enumerate(workspace_order)}
    index_positions = {code: position for position, code in enumerate(index_order)}
    displacements = [
        abs(workspace_positions[code] - index_positions[code])
        for code in common
    ]
    top_overlap = {}
    for size in (20, 50, 120):
        actual_size = min(size, len(workspace_order), len(index_order))
        overlap = len(
            set(workspace_order[:actual_size]) & set(index_order[:actual_size])
        ) if actual_size else 0
        top_overlap[str(size)] = {
            "compared": actual_size,
            "overlap": overlap,
            "ratio": round(overlap / actual_size, 4) if actual_size else 1.0,
        }

    hard = _field_differences(
        workspace,
        index,
        HARD_PARITY_FIELDS,
        max_examples=max_examples,
    )
    descriptive = _field_differences(
        workspace,
        index,
        DESCRIPTIVE_FIELDS,
        max_examples=max_examples,
    )
    ranking = _field_differences(
        workspace,
        index,
        RANKING_FIELDS,
        max_examples=max_examples,
    )
    hard_pass = not any((
        missing,
        extra,
        workspace_duplicates,
        index_duplicates,
        hard["mismatch_count"],
    ))
    return {
        "hard_gate_pass": hard_pass,
        "membership": {
            "workspace_count": len(workspace_list),
            "index_count": len(index_list),
            "common_count": len(common),
            "missing_from_index_count": len(missing),
            "extra_in_index_count": len(extra),
            "workspace_duplicate_codes": workspace_duplicates[:max_examples],
            "index_duplicate_codes": index_duplicates[:max_examples],
            "missing_from_index": missing[:max_examples],
            "extra_in_index": extra[:max_examples],
        },
        "hard_fields": hard,
        "descriptive_fields": descriptive,
        "ranking_fields": ranking,
        "ordering": {
            "exact_match": workspace_order == index_order,
            "same_position_count": sum(
                1
                for code in common
                if workspace_positions[code] == index_positions[code]
            ),
            "mean_absolute_displacement": (
                round(sum(displacements) / len(displacements), 3)
                if displacements
                else 0.0
            ),
            "max_absolute_displacement": max(displacements) if displacements else 0,
            "top_overlap": top_overlap,
        },
    }
