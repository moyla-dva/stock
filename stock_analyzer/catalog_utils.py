"""Shared normalization helpers for stock catalog modules."""

import re
from datetime import datetime


def clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def normalize_concepts(value, max_items=8):
    if value is None:
        raw_items = []
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = re.split(r"[、,，;；/|｜]+", str(value))

    concepts = []
    seen = set()
    for item in raw_items:
        text = clean_text(item)
        if not text or text in {"-", "--", "无", "暂无"}:
            continue
        if text in seen:
            continue
        seen.add(text)
        concepts.append(text)
        if len(concepts) >= max_items:
            break
    return concepts


def merge_concepts(*concept_lists, max_items=8):
    concepts = []
    seen = set()
    for concept_list in concept_lists:
        for concept in normalize_concepts(concept_list, max_items=max_items):
            if concept in seen:
                continue
            seen.add(concept)
            concepts.append(concept)
            if len(concepts) >= max_items:
                return concepts
    return concepts


def path_mtime_text(path):
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except Exception:
        return ""
    return ""
