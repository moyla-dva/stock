"""Shared helpers for scan workspace and scoring modules."""

UNKNOWN_SECTOR = "未识别板块"
UNKNOWN_CONCEPT = "未识别概念"


def as_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def avg_or_none(total, count, digits=1):
    if not count:
        return None
    return round(total / count, digits)


def result_sector(result):
    return str(result.get("sector") or "").strip() or UNKNOWN_SECTOR


def result_event_date(result):
    return str(result.get("event_date") or result.get("date") or "")


def result_concepts(result):
    concepts = result.get("concepts")
    if isinstance(concepts, (list, tuple)):
        return [str(item).strip() for item in concepts if str(item).strip()]
    if concepts:
        return [str(concepts).strip()]
    return []

