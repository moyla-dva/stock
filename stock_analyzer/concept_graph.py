"""Local sector/concept relationship graph.

The graph is an input layer for market-structure reasoning. It owns only
relation edges between sectors/concepts; scan pools may consume it later,
but they should not be the source of truth for these relations.
"""

import json
import os
import threading
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

from stock_analyzer.catalog_cache import DEFAULT_CATALOG_CACHE_DIR
from stock_analyzer.scan_common import UNKNOWN_CONCEPT, UNKNOWN_SECTOR, result_concepts, result_sector


CONCEPT_GRAPH_SCHEMA_VERSION = "concept-graph.v1"
CONCEPT_GRAPH_FILENAME = "concept_graph_edges.json"
DEFAULT_CONCEPT_GRAPH_PATH = Path(os.environ.get(
    "STOCK_ANALYZER_CONCEPT_GRAPH_PATH",
    DEFAULT_CATALOG_CACHE_DIR / CONCEPT_GRAPH_FILENAME,
))
GRAPH_KIND_VALUES = {"sector", "concept"}
GRAPH_RELATION_TYPES = {
    "upstream",
    "downstream",
    "same_theme",
    "member_overlap",
    "market_sync",
    "event_sync",
    "manual",
}
DIRECTED_RELATION_TYPES = {"upstream", "downstream"}
_GRAPH_LOCK = threading.Lock()


def _clean_text(value):
    return str(value or "").strip()


def _now_text():
    return datetime.now().isoformat(timespec="seconds")


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(max_value, value))


def concept_graph_path(path=None, cache_dir=None):
    if path:
        return Path(path)
    if cache_dir is None:
        return DEFAULT_CONCEPT_GRAPH_PATH
    return Path(cache_dir) / CONCEPT_GRAPH_FILENAME


def normalize_graph_node_kind(value):
    """Normalize local/profile naming into graph node kinds."""
    kind = _clean_text(value).lower()
    if kind in {"industry", "board", "板块", "行业"}:
        return "sector"
    if kind in {"concept", "theme", "概念", "题材"}:
        return "concept"
    if kind in GRAPH_KIND_VALUES:
        return kind
    return ""


def _node_sort_key(kind, name):
    kind_rank = {"sector": 0, "concept": 1}.get(kind, 9)
    return kind_rank, name


def _canonical_pair(source_kind, source_name, target_kind, target_name, relation_type):
    """Return a stable pair for undirected graph edges."""
    if relation_type in DIRECTED_RELATION_TYPES:
        return source_kind, source_name, target_kind, target_name
    left = (source_kind, source_name)
    right = (target_kind, target_name)
    if _node_sort_key(*left) <= _node_sort_key(*right):
        return source_kind, source_name, target_kind, target_name
    return target_kind, target_name, source_kind, source_name


def normalize_concept_graph_edge(item, *, default_source="manual"):
    """Normalize one graph edge from API payload, cache, or derived rows."""
    if not isinstance(item, dict):
        return None
    relation_type = _clean_text(item.get("relation_type")) or "manual"
    if relation_type not in GRAPH_RELATION_TYPES:
        relation_type = "manual"
    source_kind = normalize_graph_node_kind(item.get("source_kind") or item.get("from_kind"))
    target_kind = normalize_graph_node_kind(item.get("target_kind") or item.get("to_kind"))
    source_name = _clean_text(item.get("source_name") or item.get("from_name") or item.get("source"))
    target_name = _clean_text(item.get("target_name") or item.get("to_name") or item.get("target"))
    if not source_kind or not target_kind or not source_name or not target_name:
        return None
    source_kind, source_name, target_kind, target_name = _canonical_pair(
        source_kind,
        source_name,
        target_kind,
        target_name,
        relation_type,
    )
    if source_kind == target_kind and source_name == target_name:
        return None
    confidence = _clamp(_as_float(item.get("confidence"), 0.68))
    weight = _as_float(item.get("weight"), 0.0)
    edge = {
        "schema_version": CONCEPT_GRAPH_SCHEMA_VERSION,
        "source_kind": source_kind,
        "source_name": source_name,
        "target_kind": target_kind,
        "target_name": target_name,
        "relation_type": relation_type,
        "direction": "directed" if relation_type in DIRECTED_RELATION_TYPES else "undirected",
        "confidence": round(confidence, 4),
        "weight": round(weight, 4),
        "source": _clean_text(item.get("source")) or default_source,
        "evidence": _clean_text(item.get("evidence")) or "本地图谱关系",
        "effective_date": _clean_text(item.get("effective_date")),
        "last_verified_date": _clean_text(item.get("last_verified_date")),
        "updated_at": _clean_text(item.get("updated_at")) or _now_text(),
    }
    for key in (
        "shared_count",
        "union_count",
        "overlap_rate",
        "sample_codes",
        "sample_names",
        "note",
        "evidence_url",
    ):
        if key in item:
            edge[key] = item[key]
    return edge


def graph_edge_key(edge):
    relation_type = _clean_text(edge.get("relation_type"))
    return (
        edge.get("source_kind"),
        edge.get("source_name"),
        edge.get("target_kind"),
        edge.get("target_name"),
        relation_type,
    )


def _edge_priority(edge):
    source = _clean_text(edge.get("source"))
    manual_boost = 1 if source and source != "profile_member_overlap" else 0
    return (
        manual_boost,
        _as_float(edge.get("confidence"), 0),
        _as_float(edge.get("weight"), 0),
        _clean_text(edge.get("updated_at")),
    )


def merge_concept_graph_edges(*edge_groups):
    """Merge graph edges by stable key, preferring manual/high-confidence rows."""
    merged = {}
    for edges in edge_groups:
        for item in edges or []:
            edge = normalize_concept_graph_edge(item)
            if not edge:
                continue
            key = graph_edge_key(edge)
            current = merged.get(key)
            if current is None or _edge_priority(edge) >= _edge_priority(current):
                merged[key] = edge
    return sorted(
        merged.values(),
        key=lambda item: (
            -_as_float(item.get("confidence"), 0),
            -_as_float(item.get("weight"), 0),
            item.get("source_kind") or "",
            item.get("source_name") or "",
            item.get("target_kind") or "",
            item.get("target_name") or "",
        ),
    )


def build_concept_graph_adjacency(edges, *, min_confidence=0.0, relation_types=None):
    """Build a bidirectional adjacency index for normalized graph edges."""
    allowed_types = set(relation_types or [])
    adjacency = defaultdict(list)
    for raw_edge in edges or []:
        edge = normalize_concept_graph_edge(raw_edge)
        if not edge:
            continue
        if allowed_types and edge["relation_type"] not in allowed_types:
            continue
        if _as_float(edge.get("confidence"), 0.0) < min_confidence:
            continue
        left = (edge["source_kind"], edge["source_name"])
        right = (edge["target_kind"], edge["target_name"])
        left_neighbor = {
            "kind": right[0],
            "name": right[1],
            "relation_type": edge["relation_type"],
            "confidence": edge["confidence"],
            "weight": edge["weight"],
            "source": edge.get("source") or "",
            "evidence": edge.get("evidence") or "",
        }
        right_neighbor = {
            "kind": left[0],
            "name": left[1],
            "relation_type": edge["relation_type"],
            "confidence": edge["confidence"],
            "weight": edge["weight"],
            "source": edge.get("source") or "",
            "evidence": edge.get("evidence") or "",
        }
        adjacency[left].append(left_neighbor)
        adjacency[right].append(right_neighbor)
    for key, neighbors in list(adjacency.items()):
        dedup = {}
        for item in neighbors:
            dedup_key = (item["kind"], item["name"], item["relation_type"])
            current = dedup.get(dedup_key)
            if current is None or (
                _as_float(item.get("confidence"), 0.0),
                _as_float(item.get("weight"), 0.0),
            ) >= (
                _as_float(current.get("confidence"), 0.0),
                _as_float(current.get("weight"), 0.0),
            ):
                dedup[dedup_key] = item
        adjacency[key] = sorted(
            dedup.values(),
            key=lambda item: (
                -_as_float(item.get("confidence"), 0.0),
                -_as_float(item.get("weight"), 0.0),
                item.get("kind") or "",
                item.get("name") or "",
            ),
        )
    return dict(adjacency)


def read_concept_graph_edges(path=None, cache_dir=None):
    """Read persisted graph edges from the local cache."""
    graph_path = concept_graph_path(path=path, cache_dir=cache_dir)
    try:
        with graph_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return []
    except Exception as exc:
        print(f"[concept_graph] 读取本地图谱失败: {exc}")
        return []
    raw_edges = payload.get("edges") if isinstance(payload, dict) else payload
    if not isinstance(raw_edges, list):
        return []
    return merge_concept_graph_edges(raw_edges)


def write_concept_graph_edges(edges, path=None, cache_dir=None):
    """Persist normalized graph edges."""
    graph_path = concept_graph_path(path=path, cache_dir=cache_dir)
    normalized = merge_concept_graph_edges(edges)
    payload = {
        "schema_version": CONCEPT_GRAPH_SCHEMA_VERSION,
        "updated_at": _now_text(),
        "edges": normalized,
    }
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = graph_path.with_suffix(graph_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    temp_path.replace(graph_path)
    return payload


def concept_graph_status(path=None, cache_dir=None):
    """Return compact local graph status for data governance panels."""
    graph_path = concept_graph_path(path=path, cache_dir=cache_dir)
    edges = read_concept_graph_edges(path=graph_path)
    node_keys = set()
    relation_counts = Counter()
    source_counts = Counter()
    for edge in edges:
        node_keys.add((edge["source_kind"], edge["source_name"]))
        node_keys.add((edge["target_kind"], edge["target_name"]))
        relation_counts[edge["relation_type"]] += 1
        source_counts[edge.get("source") or "unknown"] += 1
    updated_at = ""
    exists = graph_path.exists()
    if exists:
        try:
            updated_at = datetime.fromtimestamp(graph_path.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            updated_at = ""
    return {
        "path": str(graph_path),
        "exists": exists,
        "available": bool(edges),
        "edge_count": len(edges),
        "node_count": len(node_keys),
        "relation_type_counts": dict(relation_counts),
        "source_counts": dict(source_counts),
        "updated_at": updated_at,
    }


def upsert_concept_graph_edge(item, path=None, cache_dir=None):
    """Insert or replace one graph edge."""
    edge = normalize_concept_graph_edge(item or {})
    if not edge:
        raise ValueError("图谱边需要 source_kind/source_name/target_kind/target_name")
    graph_path = concept_graph_path(path=path, cache_dir=cache_dir)
    with _GRAPH_LOCK:
        edges = read_concept_graph_edges(path=graph_path)
        key = graph_edge_key(edge)
        edges = [row for row in edges if graph_edge_key(row) != key]
        edges.append(edge)
        write_concept_graph_edges(edges, path=graph_path)
    return {
        "edge": edge,
        "status": concept_graph_status(path=graph_path),
    }


def delete_concept_graph_edge(item=None, path=None, cache_dir=None, **kwargs):
    """Delete graph edges by pair and optional relation type."""
    payload = {}
    if isinstance(item, dict):
        payload.update(item)
    payload.update({key: value for key, value in kwargs.items() if value is not None})
    target = normalize_concept_graph_edge({**payload, "relation_type": payload.get("relation_type") or "manual"})
    if not target:
        raise ValueError("图谱边需要 source_kind/source_name/target_kind/target_name")
    target_relation_type = _clean_text(payload.get("relation_type"))
    graph_path = concept_graph_path(path=path, cache_dir=cache_dir)
    target_pair = graph_edge_key(target)[:4]
    with _GRAPH_LOCK:
        edges = read_concept_graph_edges(path=graph_path)
        kept = []
        removed_count = 0
        for edge in edges:
            key = graph_edge_key(edge)
            if key[:4] == target_pair and (not target_relation_type or key[4] == target_relation_type):
                removed_count += 1
                continue
            kept.append(edge)
        write_concept_graph_edges(kept, path=graph_path)
    return {
        "removed_count": removed_count,
        "status": concept_graph_status(path=graph_path),
    }


def _profile_nodes(profile):
    relation_group_map = {}
    relations = profile.get("profile_relations") if isinstance(profile, dict) else []
    if isinstance(relations, list):
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            name = _clean_text(relation.get("relation_name"))
            group = _clean_text(relation.get("evidence_group") or relation.get("relation_type"))
            kind = normalize_graph_node_kind(relation.get("relation_kind") or relation.get("kind"))
            if name and kind == "concept":
                relation_group_map[name] = group
    sector = result_sector(profile)
    if sector and sector != UNKNOWN_SECTOR:
        yield ("sector", sector)
    seen_concepts = set()
    for concept in result_concepts(profile):
        if not concept or concept == UNKNOWN_CONCEPT or concept in seen_concepts:
            continue
        if relation_group_map.get(concept) in {"weak_association", "expired_watch", "event_driven"}:
            continue
        seen_concepts.add(concept)
        yield ("concept", concept)


def _sample_codes(codes, limit=5):
    return sorted(codes)[:limit]


def build_profile_graph_edges(
    profile_cache,
    *,
    min_shared_members=3,
    min_overlap_rate=0.18,
    max_edges=300,
):
    """Derive relation edges from stock-profile co-membership.

    This does not claim upstream/downstream causality. It only says two nodes
    repeatedly appear on the same stocks, so they are candidates for
    market-structure relation reasoning.
    """
    members_by_node = defaultdict(set)
    pairs = defaultdict(set)
    for code, profile in (profile_cache or {}).items():
        nodes = sorted(set(_profile_nodes(profile)), key=lambda item: _node_sort_key(*item))
        if not nodes:
            continue
        for node in nodes:
            members_by_node[node].add(str(code))
        for left, right in combinations(nodes, 2):
            pairs[(left, right)].add(str(code))

    edges = []
    for (left, right), shared_codes in pairs.items():
        shared_count = len(shared_codes)
        if shared_count < min_shared_members:
            continue
        left_count = len(members_by_node[left])
        right_count = len(members_by_node[right])
        union_count = len(members_by_node[left] | members_by_node[right])
        min_side_count = max(min(left_count, right_count), 1)
        overlap_rate = shared_count / min_side_count
        if overlap_rate < min_overlap_rate:
            continue
        confidence = _clamp(0.32 + overlap_rate * 0.42 + min(shared_count, 30) * 0.012, 0.0, 0.92)
        weight = overlap_rate * 100
        edges.append(normalize_concept_graph_edge({
            "source_kind": left[0],
            "source_name": left[1],
            "target_kind": right[0],
            "target_name": right[1],
            "relation_type": "member_overlap",
            "confidence": round(confidence, 4),
            "weight": round(weight, 2),
            "source": "profile_member_overlap",
            "evidence": f"共同成分 {shared_count} 只，较小集合覆盖 {overlap_rate:.1%}",
            "shared_count": shared_count,
            "union_count": union_count,
            "overlap_rate": round(overlap_rate, 4),
            "sample_codes": _sample_codes(shared_codes),
        }))
    return [
        edge
        for edge in sorted(
            [item for item in edges if item],
            key=lambda item: (-item["confidence"], -item["weight"], -item.get("shared_count", 0)),
        )[:max_edges]
    ]


def build_concept_graph(
    profile_cache=None,
    *,
    include_derived=True,
    path=None,
    cache_dir=None,
    min_shared_members=3,
    min_overlap_rate=0.18,
    max_edges=300,
):
    """Build a query payload combining persisted and derived graph edges."""
    persisted_edges = read_concept_graph_edges(path=path, cache_dir=cache_dir)
    derived_edges = []
    if include_derived and profile_cache:
        derived_edges = build_profile_graph_edges(
            profile_cache,
            min_shared_members=min_shared_members,
            min_overlap_rate=min_overlap_rate,
            max_edges=max_edges,
        )
    edges = merge_concept_graph_edges(persisted_edges, derived_edges)
    node_keys = set()
    relation_counts = Counter()
    for edge in edges:
        node_keys.add((edge["source_kind"], edge["source_name"]))
        node_keys.add((edge["target_kind"], edge["target_name"]))
        relation_counts[edge["relation_type"]] += 1
    status = concept_graph_status(path=path, cache_dir=cache_dir)
    status.update({
        "edge_count": len(edges),
        "node_count": len(node_keys),
        "relation_type_counts": dict(relation_counts),
        "derived_count": len(derived_edges),
        "persisted_count": len(persisted_edges),
    })
    return {
        "schema_version": CONCEPT_GRAPH_SCHEMA_VERSION,
        "status": status,
        "edges": edges[:max_edges],
    }
