"""Structured stock-profile relationship evidence."""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from stock_analyzer.catalog_cache import DEFAULT_CATALOG_CACHE_DIR
from stock_analyzer.code_utils import normalize_code
from stock_analyzer.scan_common import UNKNOWN_CONCEPT, UNKNOWN_SECTOR, result_concepts, result_sector


PROFILE_RELATION_SCHEMA_VERSION = "profile-relations.v1"
RELATION_EVIDENCE_FILENAME = "stock_relation_evidence.json"
DEFAULT_RELATION_EVIDENCE_PATH = Path(os.environ.get(
    "STOCK_ANALYZER_RELATION_EVIDENCE_PATH",
    DEFAULT_CATALOG_CACHE_DIR / RELATION_EVIDENCE_FILENAME,
))
_RELATION_EVIDENCE_LOCK = threading.Lock()

EVENT_CONCEPT_KEYWORDS = (
    "年报", "中报", "季报", "预增", "预减", "扭亏", "业绩",
    "回购", "增持", "减持", "重组", "并购", "股权转让",
)
WEAK_CONCEPT_KEYWORDS = (
    "次新", "注册制", "融资融券", "沪股通", "深股通", "MSCI",
    "破净", "高送转", "人民币贬值受益", "国企改革", "央企改革",
    "专精特新", "期货概念", "新股与次新股",
)

RELATION_GROUP_LABELS = {
    "core_business": "主营行业",
    "event_driven": "事件驱动",
    "market_tag": "市场标签",
    "weak_association": "弱关联",
    "expired_watch": "过期观察",
    "manual": "人工确认",
}

RELATION_TYPE_TO_GROUP = {
    "core_business": "core_business",
    "event_driven": "event_driven",
    "market_tag": "market_tag",
    "weak_association": "weak_association",
    "expired_watch": "expired_watch",
    "manual": "manual",
}


def _clean_text(value):
    return str(value or "").strip()


def _relation(
    *,
    name,
    kind,
    relation_type,
    source,
    confidence,
    evidence,
    evidence_group="market_tag",
    evidence_label="市场标签",
    verified_date="",
):
    return {
        "schema_version": PROFILE_RELATION_SCHEMA_VERSION,
        "relation_name": name,
        "relation_kind": kind,
        "relation_type": relation_type,
        "source": source,
        "confidence": confidence,
        "evidence_group": evidence_group,
        "evidence_label": evidence_label,
        "effective_date": "",
        "last_verified_date": verified_date or "",
        "evidence": evidence,
    }


def profile_relation_evidence_path(path=None, cache_dir=None):
    if path:
        return Path(path)
    if cache_dir is None:
        return DEFAULT_RELATION_EVIDENCE_PATH
    return Path(cache_dir) / RELATION_EVIDENCE_FILENAME


def _confidence(value, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, number))


def normalize_profile_relation_evidence(item, *, verified_date=""):
    """Normalize a manually or externally verified relation evidence row."""
    if not isinstance(item, dict):
        return None
    name = _clean_text(item.get("relation_name") or item.get("name"))
    if not name:
        return None
    relation_type = _clean_text(item.get("relation_type")) or "manual"
    evidence_group = _clean_text(item.get("evidence_group")) or RELATION_TYPE_TO_GROUP.get(relation_type, relation_type)
    evidence_label = _clean_text(item.get("evidence_label")) or RELATION_GROUP_LABELS.get(evidence_group, "人工确认")
    relation = _relation(
        name=name,
        kind=_clean_text(item.get("relation_kind") or item.get("kind")) or "manual",
        relation_type=relation_type,
        source=_clean_text(item.get("source")) or "manual_relation_evidence",
        confidence=_confidence(item.get("confidence"), 0.82),
        evidence=_clean_text(item.get("evidence")) or "本地关系证据覆盖",
        evidence_group=evidence_group,
        evidence_label=evidence_label,
        verified_date=_clean_text(item.get("last_verified_date")) or verified_date,
    )
    relation["effective_date"] = _clean_text(item.get("effective_date"))
    if item.get("evidence_url"):
        relation["evidence_url"] = _clean_text(item.get("evidence_url"))
    if item.get("note"):
        relation["note"] = _clean_text(item.get("note"))
    return relation


def read_profile_relation_evidence(path=None, cache_dir=None):
    """Read local manually/external verified relation evidence grouped by stock code."""
    evidence_path = profile_relation_evidence_path(path=path, cache_dir=cache_dir)
    try:
        with evidence_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"[profile_relations] 读取本地关系证据失败: {exc}")
        return {}

    stocks = payload.get("stocks") if isinstance(payload, dict) and isinstance(payload.get("stocks"), dict) else payload
    if not isinstance(stocks, dict):
        return {}

    output = {}
    for raw_code, rows in stocks.items():
        code = normalize_code(raw_code)
        if not code or not isinstance(rows, list):
            continue
        normalized = [
            relation
            for relation in (normalize_profile_relation_evidence(row) for row in rows)
            if relation
        ]
        if normalized:
            output[code] = normalized
    return output


def write_profile_relation_evidence(evidence_by_code, path=None, cache_dir=None):
    """Persist normalized relation evidence grouped by stock code."""
    evidence_path = profile_relation_evidence_path(path=path, cache_dir=cache_dir)
    stocks = {}
    for raw_code, rows in (evidence_by_code or {}).items():
        code = normalize_code(raw_code)
        if not code or not isinstance(rows, list):
            continue
        normalized = [
            relation
            for relation in (normalize_profile_relation_evidence(row) for row in rows)
            if relation
        ]
        if normalized:
            stocks[code] = normalized
    payload = {
        "schema_version": PROFILE_RELATION_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stocks": stocks,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    temp_path.replace(evidence_path)
    return payload


def profile_relation_evidence_status(path=None, cache_dir=None):
    """Return compact status for the local verified relation evidence file."""
    evidence_path = profile_relation_evidence_path(path=path, cache_dir=cache_dir)
    evidence = read_profile_relation_evidence(path=evidence_path)
    relation_count = sum(len(rows) for rows in evidence.values())
    updated_at = ""
    exists = evidence_path.exists()
    if exists:
        try:
            updated_at = datetime.fromtimestamp(evidence_path.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            updated_at = ""
    return {
        "path": str(evidence_path),
        "exists": exists,
        "available": relation_count > 0,
        "stock_count": len(evidence),
        "relation_count": relation_count,
        "updated_at": updated_at,
    }


def upsert_profile_relation_evidence(code, item, path=None, cache_dir=None):
    """Insert or replace one verified relation evidence row for a stock."""
    normalized_code = normalize_code(code)
    if not normalized_code:
        raise ValueError("无效的股票代码")
    relation = normalize_profile_relation_evidence(item or {})
    if not relation:
        raise ValueError("relation_name不能为空")
    evidence_path = profile_relation_evidence_path(path=path, cache_dir=cache_dir)
    relation_name = _clean_text(relation.get("relation_name"))
    with _RELATION_EVIDENCE_LOCK:
        evidence = read_profile_relation_evidence(path=evidence_path)
        rows = [
            row
            for row in evidence.get(normalized_code, [])
            if _clean_text(row.get("relation_name")) != relation_name
        ]
        rows.append(relation)
        evidence[normalized_code] = rows
        write_profile_relation_evidence(evidence, path=evidence_path)
    return {
        "code": normalized_code,
        "relation": relation,
        "status": profile_relation_evidence_status(path=evidence_path),
    }


def delete_profile_relation_evidence(code, relation_name=None, path=None, cache_dir=None):
    """Delete verified relation evidence for a stock, optionally by relation name."""
    normalized_code = normalize_code(code)
    if not normalized_code:
        raise ValueError("无效的股票代码")
    target_name = _clean_text(relation_name)
    evidence_path = profile_relation_evidence_path(path=path, cache_dir=cache_dir)
    with _RELATION_EVIDENCE_LOCK:
        evidence = read_profile_relation_evidence(path=evidence_path)
        current_rows = evidence.get(normalized_code, [])
        if target_name:
            rows = [
                row
                for row in current_rows
                if _clean_text(row.get("relation_name")) != target_name
            ]
            removed_count = len(current_rows) - len(rows)
            if rows:
                evidence[normalized_code] = rows
            else:
                evidence.pop(normalized_code, None)
        else:
            removed_count = len(current_rows)
            evidence.pop(normalized_code, None)
        write_profile_relation_evidence(evidence, path=evidence_path)
    return {
        "code": normalized_code,
        "removed_count": removed_count,
        "status": profile_relation_evidence_status(path=evidence_path),
    }


def classify_concept_relation(concept):
    """Classify concept evidence without pretending it is primary business proof."""
    concept = _clean_text(concept)
    if any(keyword in concept for keyword in EVENT_CONCEPT_KEYWORDS):
        return {
            "relation_type": "event_driven",
            "evidence_group": "event_driven",
            "evidence_label": RELATION_GROUP_LABELS["event_driven"],
            "confidence": 0.68,
            "evidence": "本地概念库事件/业绩类标签",
        }
    if any(keyword in concept for keyword in WEAK_CONCEPT_KEYWORDS):
        return {
            "relation_type": "weak_association",
            "evidence_group": "weak_association",
            "evidence_label": RELATION_GROUP_LABELS["weak_association"],
            "confidence": 0.48,
            "evidence": "本地概念库宽泛交易标签",
        }
    return {
        "relation_type": "market_tag",
        "evidence_group": "market_tag",
        "evidence_label": RELATION_GROUP_LABELS["market_tag"],
        "confidence": 0.64,
        "evidence": "本地股票概念库标签",
    }


def build_stock_profile_relations(profile=None, *, verified_date=""):
    """Build normalized relationship evidence from a cached stock profile."""
    profile = profile or {}
    relations = []
    sector = result_sector(profile)
    if sector and sector != UNKNOWN_SECTOR:
        relations.append(_relation(
            name=sector,
            kind="industry",
            relation_type="core_business",
            source="stock_profile_cache",
            confidence=0.74,
            evidence_group="core_business",
            evidence_label=RELATION_GROUP_LABELS["core_business"],
            verified_date=verified_date,
            evidence="本地股票画像行业分类，代表主营行业方向",
        ))
    for concept in result_concepts(profile):
        if not concept or concept == UNKNOWN_CONCEPT:
            continue
        classified = classify_concept_relation(concept)
        relations.append(_relation(
            name=concept,
            kind="concept",
            relation_type=classified["relation_type"],
            source="stock_concept_cache",
            confidence=classified["confidence"],
            evidence_group=classified["evidence_group"],
            evidence_label=classified["evidence_label"],
            verified_date=verified_date,
            evidence=classified["evidence"],
        ))
    return relations


def merge_profile_relations(base_relations, evidence_relations):
    """Merge automatic profile tags with verified evidence, preferring higher-confidence rows."""
    merged = {}
    for relation in (base_relations or []) + (evidence_relations or []):
        name = _clean_text(relation.get("relation_name"))
        key = name
        if not name:
            continue
        current = merged.get(key)
        confidence = _confidence(relation.get("confidence"), 0)
        current_confidence = _confidence(current.get("confidence"), 0) if current else -1
        source = _clean_text(relation.get("source"))
        current_source = _clean_text(current.get("source")) if current else ""
        is_verified = source not in {"stock_profile_cache", "stock_concept_cache"}
        current_is_auto = current_source in {"stock_profile_cache", "stock_concept_cache"}
        if (
            current is None
            or (is_verified and current_is_auto)
            or confidence > current_confidence
            or (confidence == current_confidence and is_verified and current_is_auto)
        ):
            merged[key] = relation
    return list(merged.values())


def summarize_profile_relation_groups(relations):
    groups = {}
    order = ["core_business", "manual", "event_driven", "market_tag", "weak_association", "expired_watch"]
    for relation in relations or []:
        key = relation.get("evidence_group") or relation.get("relation_type") or "market_tag"
        if key not in groups:
            groups[key] = {
                "key": key,
                "label": relation.get("evidence_label") or RELATION_GROUP_LABELS.get(key, key),
                "count": 0,
                "relations": [],
            }
        groups[key]["count"] += 1
        groups[key]["relations"].append(relation)
    return [
        groups[key]
        for key in order
        if key in groups
    ] + [
        groups[key]
        for key in groups
        if key not in order
    ]


def attach_profile_relations(result, profile=None, *, verified_date="", relation_evidence=None):
    """Attach profile relationship evidence to a scan result in-place."""
    result = result or {}
    merged_profile = dict(profile or {})
    merged_profile.setdefault("sector", result.get("sector"))
    merged_profile.setdefault("concepts", result.get("concepts"))
    relations = merge_profile_relations(
        build_stock_profile_relations(merged_profile, verified_date=verified_date),
        relation_evidence or [],
    )
    groups = summarize_profile_relation_groups(relations)
    result["profile_relations"] = relations
    result["profile_relation_count"] = len(relations)
    result["profile_relation_summary"] = " / ".join(
        _clean_text(item.get("relation_name"))
        for item in relations[:3]
        if _clean_text(item.get("relation_name"))
    )
    result["profile_relation_groups"] = groups
    result["profile_relation_group_summary"] = " / ".join(
        f"{group['label']} {group['count']}"
        for group in groups
    )
    return result


def build_profile_relation_cache(profile_cache, relation_evidence_cache=None, *, verified_date=""):
    """Return profile cache rows enriched with normalized relationship evidence."""
    output = {}
    for raw_code, profile in (profile_cache or {}).items():
        code = normalize_code(raw_code)
        if not code or not isinstance(profile, dict):
            continue
        enriched = dict(profile)
        enriched.setdefault("code", code)
        attach_profile_relations(
            enriched,
            enriched,
            verified_date=verified_date,
            relation_evidence=(relation_evidence_cache or {}).get(code, []),
        )
        output[code] = enriched
    return output
