"""Structured stock tag profile for separating facts from trading context."""

from stock_analyzer.profile_relations import build_stock_profile_relations
from stock_analyzer.scan_common import UNKNOWN_SECTOR, result_concepts, result_sector


TAG_PROFILE_VERSION = "stock-tag-profile.v1"


def _clean_text(value):
    return str(value or "").strip()


def _dedupe(items):
    output = []
    seen = set()
    for item in items or []:
        text = _clean_text(item)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _merge_profile_item(item=None, profile=None):
    merged = dict(profile or {})
    for key in ("code", "name", "sector", "concepts", "profile_relations"):
        value = (item or {}).get(key)
        if value not in (None, "", []):
            merged[key] = value
    return merged


def _relation_group(relation):
    return _clean_text(relation.get("evidence_group") or relation.get("relation_type") or "market_tag")


def _relation_name(relation):
    return _clean_text(relation.get("relation_name") or relation.get("name"))


def _relation_tags(relations, group_names):
    group_names = set(group_names)
    tags = []
    for relation in relations or []:
        if _relation_group(relation) not in group_names:
            continue
        name = _relation_name(relation)
        if not name:
            continue
        tags.append({
            "name": name,
            "kind": relation.get("relation_kind") or relation.get("kind") or "concept",
            "relation_type": relation.get("relation_type"),
            "evidence_group": _relation_group(relation),
            "confidence": relation.get("confidence"),
            "source": relation.get("source"),
            "evidence": relation.get("evidence"),
        })
    return tags


def _tag_names(tags):
    return _dedupe(tag.get("name") for tag in tags)


def _build_flags(concepts, groups):
    flags = []
    weak_count = len(groups["weak_association"]["tags"]) + len(groups["expired_watch"]["tags"])
    market_count = len(groups["market_tag"]["tags"])
    strong_count = (
        len(groups["official_industry"]["tags"])
        + len(groups["manual"]["tags"])
        + len(groups["event_driven"]["tags"])
    )
    if weak_count >= 2:
        flags.append({
            "key": "weak_tag_noise",
            "severity": "muted",
            "label": "弱关联偏多",
            "detail": "存在融资融券、股通、改革等宽泛标签，归因时应降权。",
        })
    if market_count and not strong_count:
        flags.append({
            "key": "market_tag_only",
            "severity": "warning",
            "label": "仅市场标签",
            "detail": "缺少主营或人工确认，不能只凭概念标签参与。",
        })
    return flags


def _quality_label(flags, groups):
    severities = {flag.get("severity") for flag in flags}
    strong_count = (
        len(groups["official_industry"]["tags"])
        + len(groups["manual"]["tags"])
        + len(groups["event_driven"]["tags"])
    )
    if "warning" in severities:
        return "需核对"
    if strong_count:
        return "静态清晰"
    return "证据不足"


def build_stock_tag_profile(item=None, profile=None):
    """Return a structured tag profile without changing trading decisions."""
    merged = _merge_profile_item(item=item, profile=profile)
    sector = result_sector(merged)
    official_industry = "" if sector == UNKNOWN_SECTOR else sector
    concepts = result_concepts(merged)
    relations = merged.get("profile_relations")
    if not isinstance(relations, list) or not relations:
        relations = build_stock_profile_relations({
            "sector": official_industry,
            "concepts": concepts,
        })

    groups = {
        "official_industry": {
            "key": "official_industry",
            "label": "静态行业",
            "layer": "fact",
            "tags": [{
                "name": official_industry,
                "kind": "industry",
                "evidence_group": "core_business",
                "confidence": 0.74,
                "source": "stock_profile_cache",
                "evidence": "本地股票画像行业分类",
            }] if official_industry else [],
        },
        "manual": {
            "key": "manual",
            "label": "人工确认",
            "layer": "verified",
            "tags": _relation_tags(relations, {"manual"}),
        },
        "event_driven": {
            "key": "event_driven",
            "label": "事件驱动",
            "layer": "event",
            "tags": _relation_tags(relations, {"event_driven"}),
        },
        "market_tag": {
            "key": "market_tag",
            "label": "市场标签",
            "layer": "clue",
            "tags": _relation_tags(relations, {"market_tag"}),
        },
        "weak_association": {
            "key": "weak_association",
            "label": "弱关联",
            "layer": "noise",
            "tags": _relation_tags(relations, {"weak_association"}),
        },
        "expired_watch": {
            "key": "expired_watch",
            "label": "过期观察",
            "layer": "noise",
            "tags": _relation_tags(relations, {"expired_watch"}),
        },
    }
    flags = _build_flags(concepts, groups)
    profile = {
        "version": TAG_PROFILE_VERSION,
        "code": _clean_text(merged.get("code")),
        "name": _clean_text(merged.get("name")),
        "official_industry": official_industry,
        "raw_concepts": _dedupe(concepts),
        "groups": groups,
        "governance": {
            "quality_label": _quality_label(flags, groups),
            "concept_count": len(_dedupe(concepts)),
            "market_tag_count": len(groups["market_tag"]["tags"]),
            "event_tag_count": len(groups["event_driven"]["tags"]),
            "weak_tag_count": len(groups["weak_association"]["tags"]) + len(groups["expired_watch"]["tags"]),
            "flags": flags,
        },
    }
    profile["summary"] = " / ".join(
        part for part in (
            f"行业:{official_industry}" if official_industry else "",
            f"市场标签:{len(groups['market_tag']['tags'])}" if groups["market_tag"]["tags"] else "",
            f"弱关联:{profile['governance']['weak_tag_count']}" if profile["governance"]["weak_tag_count"] else "",
        )
        if part
    ) or "画像待补"
    profile["primary_tags"] = _dedupe(
        [official_industry]
        + _tag_names(groups["manual"]["tags"])
        + _tag_names(groups["event_driven"]["tags"])
        + _tag_names(groups["market_tag"]["tags"])[:5]
    )
    profile["confidence"] = round(
        min(1.0, max(0.0, 0.36 + 0.08 * len(groups["market_tag"]["tags"]) - 0.05 * len(flags))),
        2,
    )
    if groups["manual"]["tags"]:
        profile["confidence"] = max(profile["confidence"], 0.82)
    elif official_industry:
        profile["confidence"] = max(profile["confidence"], 0.62)
    return profile


def attach_stock_tag_profile(result, profile=None):
    """Attach a structured tag profile to a mutable result payload."""
    if not isinstance(result, dict):
        return result
    result["tag_profile"] = build_stock_tag_profile(result, profile=profile)
    return result
