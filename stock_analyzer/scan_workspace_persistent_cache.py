"""Persistent cache for compact scan workspace responses."""

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from stock_analyzer import catalog, market_boards, scan_snapshot
from stock_analyzer.profile_relations import profile_relation_evidence_path
from stock_analyzer.versioning import (
    DATA_ADJUST,
    SCAN_EXPLANATION_VERSION,
    SCAN_STRATEGY_VERSION,
    SCAN_SNAPSHOT_SCHEMA_VERSION,
)


SCAN_WORKSPACE_CACHE_SCHEMA_VERSION = 1
SCAN_WORKSPACE_RESPONSE_CACHE_DIR = (
    Path(__file__).resolve().parents[1] / ".cache" / "scan_workspace_responses"
)


def _now_text():
    return datetime.now().isoformat(timespec="seconds")


def _path_stat(path):
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {
            "path": str(path),
            "exists": False,
            "mtime_ns": 0,
            "size": 0,
        }
    return {
        "path": str(path),
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _directory_stat(path, pattern="*"):
    path = Path(path)
    file_count = 0
    latest_mtime_ns = 0
    total_size = 0
    if path.exists():
        for item in path.glob(pattern):
            if not item.is_file():
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            file_count += 1
            latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
            total_size += stat.st_size
    return {
        "path": str(path),
        "pattern": pattern,
        "file_count": file_count,
        "latest_mtime_ns": latest_mtime_ns,
        "total_size": total_size,
    }


def scan_workspace_dependency_fingerprint(start_date=None):
    """Return a cheap invalidation fingerprint for compact workspace responses."""
    snapshot_paths = scan_snapshot.scan_snapshot_files(start_date=start_date)
    latest_snapshot_day = ""
    snapshot_count = 0
    latest_mtime_ns = 0
    total_size = 0
    for path in snapshot_paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot_count += 1
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        total_size += stat.st_size
        day = scan_snapshot.normalize_snapshot_day(str(path.stem).rsplit("_", 1)[-1])
        if day > latest_snapshot_day:
            latest_snapshot_day = day

    return {
        "schema_version": SCAN_WORKSPACE_CACHE_SCHEMA_VERSION,
        "strategy_version": SCAN_STRATEGY_VERSION,
        "snapshot_schema_version": SCAN_SNAPSHOT_SCHEMA_VERSION,
        "explanation_version": SCAN_EXPLANATION_VERSION,
        "data_adjust": DATA_ADJUST,
        "snapshots": {
            "path": str(scan_snapshot.SNAPSHOT_DIR),
            "file_count": snapshot_count,
            "latest_snapshot_day": latest_snapshot_day,
            "latest_mtime_ns": latest_mtime_ns,
            "total_size": total_size,
        },
        "catalog": [
            _path_stat(catalog.profile_cache_path()),
            _path_stat(catalog.concept_cache_path()),
            _path_stat(profile_relation_evidence_path(cache_dir=catalog.CATALOG_CACHE_DIR)),
        ],
        "board_market": _directory_stat(market_boards.BOARD_MARKET_CACHE_DIR, "*.json"),
    }


def _cache_digest(key, fingerprint):
    payload = {
        "key": key,
        "fingerprint": fingerprint,
    }
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _json_key(key):
    if isinstance(key, tuple):
        return list(key)
    if isinstance(key, list):
        return key
    return [key]


def _cache_path(key, fingerprint):
    return SCAN_WORKSPACE_RESPONSE_CACHE_DIR / f"{_cache_digest(key, fingerprint)}.json"


def _read_cached_payload(path, key, fingerprint):
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    meta = payload.get("workspace_cache_meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return None
    if meta.get("schema_version") != SCAN_WORKSPACE_CACHE_SCHEMA_VERSION:
        return None
    if meta.get("key") != _json_key(key) or meta.get("fingerprint") != fingerprint:
        return None
    payload["workspace_cache_meta"] = dict(meta, hit=True)
    return payload


def _write_cached_payload(path, payload, key, fingerprint):
    cached = dict(payload)
    cached["workspace_cache_meta"] = {
        "schema_version": SCAN_WORKSPACE_CACHE_SCHEMA_VERSION,
        "key": _json_key(key),
        "fingerprint": fingerprint,
        "stored_at": _now_text(),
        "hit": False,
    }
    tmp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(cached, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return payload
    return cached


def put_cached_compact_workspace_response(key, fingerprint, payload):
    """Store a compact workspace response without reading it first."""
    return _write_cached_payload(_cache_path(key, fingerprint), payload, key, fingerprint)


def get_cached_compact_workspace_response(key, fingerprint, factory, force_refresh=False):
    """Read or build a compact workspace response from a persistent JSON cache."""
    cache_path = _cache_path(key, fingerprint)
    if not force_refresh:
        cached = _read_cached_payload(cache_path, key, fingerprint)
        if cached is not None:
            return cached
    payload = factory()
    return _write_cached_payload(cache_path, payload, key, fingerprint)
