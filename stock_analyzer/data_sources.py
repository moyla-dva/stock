"""Unified local data-source and cache status reporting."""

import csv
import json
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path

from stock_analyzer import catalog, data_fetcher, scan_jobs
from stock_analyzer.concept_graph import concept_graph_status
from stock_analyzer.profile_relations import profile_relation_evidence_status
from stock_analyzer.scan_cache import scan_cache_status
from stock_analyzer.versioning import DATA_ADJUST, DATA_START_DATE


DATA_SOURCE_STATUS_CACHE_SCHEMA_VERSION = 1
DATA_SOURCE_STATUS_CACHE_TTL_SECONDS = 300
DATA_SOURCE_STATUS_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "data_source_status"


def _now_text():
    return datetime.now().isoformat(timespec="seconds")


def _start_key(start_date=None):
    return str(start_date or "default").replace("-", "")


def _cache_path(start_date=None):
    return DATA_SOURCE_STATUS_CACHE_DIR / f"status_{_start_key(start_date)}_{DATA_ADJUST}.json"


def _read_cached_status(start_date=None, ttl_seconds=DATA_SOURCE_STATUS_CACHE_TTL_SECONDS):
    path = _cache_path(start_date)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    meta = payload.get("cache_meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict) or meta.get("schema_version") != DATA_SOURCE_STATUS_CACHE_SCHEMA_VERSION:
        return None
    try:
        stored_at = float(meta.get("stored_at") or 0)
    except (TypeError, ValueError):
        return None
    if ttl_seconds is not None and ttl_seconds >= 0:
        if datetime.now().timestamp() - stored_at > ttl_seconds:
            return None
    payload["cache_meta"] = dict(meta, hit=True)
    return payload


def _write_cached_status(payload, start_date=None):
    cached = dict(payload)
    cached["cache_meta"] = {
        "schema_version": DATA_SOURCE_STATUS_CACHE_SCHEMA_VERSION,
        "stored_at": datetime.now().timestamp(),
        "hit": False,
    }
    try:
        DATA_SOURCE_STATUS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _cache_path(start_date).with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(cached, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(_cache_path(start_date))
    except Exception:
        return payload
    return cached


def _mtime_text(path):
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""
    return ""


def _directory_stats(path, pattern="*"):
    path = Path(path)
    files = []
    if path.exists():
        files = [item for item in path.glob(pattern) if item.is_file()]
    total_bytes = 0
    latest_mtime = 0.0
    for item in files:
        try:
            stat = item.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        latest_mtime = max(latest_mtime, stat.st_mtime)
    return {
        "path": str(path),
        "file_count": len(files),
        "size_mb": round(total_bytes / 1024 / 1024, 2),
        "updated_at": datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds") if latest_mtime else "",
        "files": files,
    }


def _source(key, label, status, available, count=0, updated_at="", detail="", **extra):
    payload = {
        "key": key,
        "label": label,
        "status": status,
        "available": bool(available),
        "count": int(count or 0),
        "updated_at": updated_at or "",
        "detail": detail or "",
    }
    payload.update(extra)
    return payload


def _latest_history_end(files):
    latest = ""
    for path in files:
        latest = max(latest, _history_requested_end_key(path))
    if not latest:
        return ""
    return f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}"


def _history_requested_end_key(path):
    parts = path.stem.split("_")
    if len(parts) >= 3 and parts[2].isdigit() and len(parts[2]) == 8:
        return parts[2]
    return _read_latest_history_day_key(path)


def _display_history_day(day_key):
    if not day_key:
        return ""
    if len(day_key) == 8 and day_key.isdigit():
        return f"{day_key[:4]}-{day_key[4:6]}-{day_key[6:8]}"
    return day_key


def _read_latest_history_day_key(path):
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            if size <= 0:
                return ""
            handle.seek(max(0, size - 4096))
            lines = handle.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return ""

    for line in reversed(lines):
        text = line.strip()
        if not text or text.lower().startswith("date,") or text.startswith("日期,"):
            continue
        try:
            first_cell = next(csv.reader([text]))[0].strip()
        except (csv.Error, IndexError):
            continue
        for pattern in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(first_cell, pattern).strftime("%Y%m%d")
            except ValueError:
                continue
    return ""


def _latest_history_actual_day(files):
    by_requested = defaultdict(list)
    for path in files:
        requested = _history_requested_end_key(path)
        if requested:
            by_requested[requested].append(path)
    latest_actual = ""
    for requested in sorted(by_requested, reverse=True):
        if latest_actual and requested <= latest_actual:
            break
        for path in by_requested[requested]:
            latest_actual = max(latest_actual, _read_latest_history_day_key(path))
    return _display_history_day(latest_actual)


def _history_has_current_day_lag(requested_end, actual_day):
    if not requested_end or not actual_day or requested_end <= actual_day:
        return False
    try:
        requested = datetime.strptime(requested_end, "%Y-%m-%d")
    except ValueError:
        return False
    now = data_fetcher.beijing_now()
    if hasattr(now, "to_pydatetime"):
        now = now.to_pydatetime()
    return (
        now.strftime("%Y-%m-%d") == requested_end
        and requested.weekday() < 5
        and now.time() >= time(15, 10)
    )


def _history_source():
    stats = _directory_stats(data_fetcher.CACHE_DIR, f"*_{DATA_ADJUST}.csv")
    files = stats.pop("files")
    latest_end = _latest_history_end(files)
    latest_actual = _latest_history_actual_day(files) or latest_end
    has_current_day_lag = _history_has_current_day_lag(latest_end, latest_actual)
    status = "warning" if has_current_day_lag else ("ready" if stats["file_count"] else "empty")
    detail = (
        f"{stats['file_count']} 个{DATA_ADJUST}日线文件 · {stats['size_mb']} MB"
        + (f" · 真实到 {latest_actual}" if latest_actual else "")
        + (f" · 请求到 {latest_end}" if latest_end and latest_end != latest_actual else "")
    )
    return _source(
        "history",
        "日线缓存",
        status,
        stats["file_count"] > 0,
        count=stats["file_count"],
        updated_at=stats["updated_at"],
        detail=detail,
        cache="local",
        latest_data_date=latest_actual,
        latest_requested_end=latest_end,
        current_day_lag=has_current_day_lag,
        path=stats["path"],
        size_mb=stats["size_mb"],
    )


def _scan_snapshot_source(start_date, logger=None):
    status = scan_cache_status(start_date=start_date, logger=logger)
    stale_count = int(status.get("stale_count") or 0)
    invalid_count = int(status.get("invalid_count") or 0)
    current_count = int(status.get("current_strategy_count") or 0)
    status_key = "ready" if current_count else ("warning" if status.get("file_count") else "empty")
    if stale_count or invalid_count:
        status_key = "warning" if current_count else status_key
    detail = (
        f"当前 {current_count} · 旧策略 {status.get('legacy_strategy_count', 0)}"
        f" · 过期 {stale_count} · 无效 {invalid_count}"
    )
    return _source(
        "scan_snapshots",
        "扫描快照",
        status_key,
        current_count > 0,
        count=status.get("file_count", 0),
        updated_at=status.get("latest_display_day") or "",
        detail=detail,
        cache="local",
        latest_snapshot_day=status.get("latest_display_day") or "-",
        size_mb=status.get("size_mb") or 0,
        obsolete_strategy_count=status.get("obsolete_strategy_count") or 0,
    )


def _concept_source():
    status = catalog.get_stock_concept_cache_status()
    available = bool(status.get("available"))
    status_key = "ready" if available else "empty"
    detail = (
        f"覆盖 {status.get('stock_count', 0)} 只"
        f" · {status.get('concept_count', 0)} 概念"
        f" · {status.get('source') or '-'}"
    )
    return _source(
        "concepts",
        "概念库",
        status_key,
        available,
        count=status.get("stock_count", 0),
        updated_at=status.get("updated_at") or _mtime_text(catalog.concept_cache_path()),
        detail=detail,
        cache="local",
        concept_count=status.get("concept_count", 0),
        source=status.get("source") or "",
        path=str(catalog.concept_cache_path()),
    )


def _profile_source():
    profiles = catalog.get_cached_stock_profiles()
    path = catalog.profile_cache_path()
    named_count = sum(1 for item in profiles.values() if isinstance(item, dict) and item.get("name"))
    sector_count = sum(1 for item in profiles.values() if isinstance(item, dict) and item.get("sector"))
    concept_count = sum(1 for item in profiles.values() if isinstance(item, dict) and item.get("concepts"))
    status = "ready" if profiles else "empty"
    detail = f"画像 {len(profiles)} 只 · 名称 {named_count} · 板块 {sector_count} · 概念 {concept_count}"
    return _source(
        "profiles",
        "股票画像",
        status,
        bool(profiles),
        count=len(profiles),
        updated_at=_mtime_text(path),
        detail=detail,
        cache="local",
        path=str(path),
        named_count=named_count,
        sector_count=sector_count,
        concept_count=concept_count,
    )


def _profile_relation_evidence_source():
    status = profile_relation_evidence_status(cache_dir=catalog.CATALOG_CACHE_DIR)
    status_key = "ready" if status["relation_count"] else "empty"
    return _source(
        "profile_relation_evidence",
        "画像证据",
        status_key,
        status["available"],
        count=status["relation_count"],
        updated_at=status["updated_at"],
        detail=f"可选证据 · {status['stock_count']} 只股票 · {status['relation_count']} 条人工/公告证据",
        cache="local",
        path=status["path"],
        stock_count=status["stock_count"],
    )


def _concept_graph_source():
    status = concept_graph_status(cache_dir=catalog.CATALOG_CACHE_DIR)
    relation_summary = " / ".join(
        f"{key} {value}"
        for key, value in sorted(status.get("relation_type_counts", {}).items())
    ) or "暂无关系边"
    return _source(
        "concept_graph",
        "关系图谱（实验）",
        "experimental",
        status["available"],
        count=status["edge_count"],
        updated_at=status["updated_at"],
        detail=f"实验项 · {status['node_count']} 节点 · {status['edge_count']} 边 · {relation_summary}",
        cache="local+derived",
        path=status["path"],
        experimental=True,
        node_count=status["node_count"],
        relation_type_counts=status.get("relation_type_counts", {}),
    )


def _scan_jobs_source():
    path = Path(scan_jobs.DEFAULT_HISTORY_PATH)
    count = 0
    size_mb = 0.0
    if path.exists():
        try:
            size_mb = round(path.stat().st_size / 1024 / 1024, 2)
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
                count = len(payload["jobs"])
        except Exception:
            count = 0
    status = "ready" if count else ("warning" if path.exists() else "empty")
    detail = f"{count} 条任务记录 · {size_mb} MB" if path.exists() else "暂无任务记录"
    return _source(
        "scan_jobs",
        "任务记录",
        status,
        path.exists(),
        count=count,
        updated_at=_mtime_text(path),
        detail=detail,
        cache="local",
        path=str(path),
        size_mb=size_mb,
    )


def _build_data_source_status(start_date=DATA_START_DATE, logger=None):
    """Return a compact status model for all local data sources used by the app."""
    sources = [
        _history_source(),
        _scan_snapshot_source(start_date, logger=logger),
        _concept_source(),
        _profile_source(),
        _profile_relation_evidence_source(),
        _concept_graph_source(),
        _scan_jobs_source(),
        _source(
            "stock_list_provider",
            "股票列表",
            "provider",
            True,
            detail="启动扫描时从 Provider 获取，失败后使用兜底列表",
            cache="network+fallback",
        ),
    ]
    def is_experimental(item):
        return item.get("status") == "experimental" or bool(item.get("experimental"))

    core_sources = [item for item in sources if not is_experimental(item)]
    ready = sum(1 for item in core_sources if item["status"] in {"ready", "provider"})
    warnings = sum(1 for item in core_sources if item["status"] == "warning")
    empty = sum(1 for item in core_sources if item["status"] == "empty")
    experimental = sum(1 for item in sources if is_experimental(item))
    if warnings:
        overall_status = "warning"
        label = "可用，含待整理项" if ready and not empty else "部分需治理"
        warning_label = "待整理" if ready and not empty else "警告"
    elif ready:
        overall_status = "ready"
        label = "数据可用"
        warning_label = "警告"
    else:
        overall_status = "empty"
        label = "等待建立"
        warning_label = "警告"
    return {
        "updated_at": _now_text(),
        "overall": {
            "status": overall_status,
            "label": label,
            "ready_count": ready,
            "warning_count": warnings,
            "empty_count": empty,
            "experimental_count": experimental,
            "summary": f"{ready}/{len(core_sources)} 可用 · {warnings} {warning_label} · {empty} 未建立 · {experimental} 实验",
        },
        "sources": sources,
    }


def collect_data_source_status(
    start_date=DATA_START_DATE,
    logger=None,
    use_cache=False,
    force_refresh=False,
    cache_ttl_seconds=DATA_SOURCE_STATUS_CACHE_TTL_SECONDS,
):
    """Return a compact status model for all local data sources used by the app."""
    if use_cache and not force_refresh:
        cached = _read_cached_status(start_date=start_date, ttl_seconds=cache_ttl_seconds)
        if cached is not None:
            return cached
    payload = _build_data_source_status(start_date=start_date, logger=logger)
    if use_cache:
        return _write_cached_status(payload, start_date=start_date)
    return payload
